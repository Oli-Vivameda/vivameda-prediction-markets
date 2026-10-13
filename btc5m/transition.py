"""Owned paper worker handoff. Stops only validated, pinned process identities."""
import argparse,json,os,signal,sqlite3,subprocess,sys,time
from pathlib import Path
from launch import bundle
from operations import atomic_json

def stop_owned(pid,script,cwd):
    proc=Path('/proc')/str(pid)
    if not proc.exists():return
    if proc.stat().st_uid!=os.geteuid() or str(script).encode() not in (proc/'cmdline').read_bytes().split(b'\0') or (proc/'cwd').resolve()!=cwd:
        raise ValueError('Owned process identity differs')
    fd=os.pidfd_open(pid);signal.pidfd_send_signal(fd,signal.SIGTERM);os.close(fd)
    deadline=time.monotonic()+20
    while time.monotonic()<deadline:
        if not proc.exists() or (proc/'stat').read_text().split(') ',1)[1].startswith('Z'):return
        time.sleep(.1)
    raise RuntimeError('Owned process did not stop')

def main():
    p=argparse.ArgumentParser();p.add_argument('--runtime-root',required=True);p.add_argument('--expected-sha256',required=True);p.add_argument('--stop-only',action='store_true');a=p.parse_args()
    if os.geteuid()==0:raise ValueError('Run handoff as engineering user')
    root=Path(a.runtime_root).resolve();data=root/'data';receipt=json.loads((data/'launch-receipt.json').read_text());runtime=Path(receipt['runtime'])
    if bundle()!=a.expected_sha256 or receipt['reviewed_bundle']!=a.expected_sha256 or runtime.parent!=root:raise ValueError('Reviewed version differs')
    prior=json.loads((data/'service-transition.json').read_text()) if (data/'service-transition.json').exists() else {}
    supervisor=prior.get('supervisor_pid')
    if supervisor:stop_owned(supervisor,runtime/'supervisor.py',runtime)
    stop_owned(int(receipt['pid']),runtime/'agent.py',runtime)
    if a.stop_only:print(json.dumps({'stopped':True}));return
    backup=data/('paper-supervision-backup-'+str(time.time_ns())+'.sqlite3')
    with sqlite3.connect(data/'paper.sqlite3') as src,sqlite3.connect(backup) as dst:src.backup(dst)
    atomic_json(data/'service-transition.json',{'backup':str(backup),'reviewed_bundle':a.expected_sha256})
    with open(data/'supervisor.log','ab') as log:
        child=subprocess.Popen([sys.executable,str(runtime/'supervisor.py'),'--runtime-root',str(root),'--expected-sha256',a.expected_sha256],cwd=runtime,stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
    atomic_json(data/'service-transition.json',{'backup':str(backup),'reviewed_bundle':a.expected_sha256,'supervisor_pid':child.pid})
    print(json.dumps({'supervisor_pid':child.pid,'reviewed_bundle':a.expected_sha256,'live_execution':False}))
if __name__=='__main__':main()
