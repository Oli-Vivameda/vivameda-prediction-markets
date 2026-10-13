"""Reviewed upgrade of the dedicated standalone non-root paper supervisor."""
import argparse,json,os,sqlite3,subprocess,sys,time,fcntl
from pathlib import Path
from launch import FILES,bundle
from transition import stop_owned
from operations import atomic_json

def main():
    p=argparse.ArgumentParser();p.add_argument('--runtime-root',required=True);p.add_argument('--expected-sha256',required=True);p.add_argument('--prior-sha256',required=True);a=p.parse_args()
    if os.geteuid()==0 or bundle()!=a.expected_sha256:raise ValueError('Reviewed non-root upgrade required')
    root=Path(a.runtime_root).resolve();data=root/'data';guard=open(data/'upgrade.lock','a');fcntl.flock(guard,fcntl.LOCK_EX|fcntl.LOCK_NB)
    receipt=json.loads((data/'launch-receipt.json').read_text());transition=json.loads((data/'service-transition.json').read_text());old=Path(receipt['runtime'])
    if receipt['reviewed_bundle']!=a.prior_sha256 or old!=root/a.prior_sha256:raise ValueError('Prior identity differs')
    active=subprocess.run(['systemctl','is-active','--quiet','vivameda-btc5m-paper.service']).returncode==0
    if active:raise ValueError('System-service upgrade requires reviewed root handoff')
    runtime=root/a.expected_sha256;runtime.mkdir(exist_ok=True)
    for n in FILES:
        raw=Path(__file__).with_name(n).read_bytes();dest=runtime/n
        if dest.exists() and dest.read_bytes()!=raw:raise ValueError('Version differs')
        dest.write_bytes(raw)
    stop_owned(transition['supervisor_pid'],old/'supervisor.py',old)
    latest=json.loads((data/'launch-receipt.json').read_text());stop_owned(latest['pid'],old/'agent.py',old)
    backup=data/('paper-ops-upgrade-'+str(time.time_ns())+'.sqlite3')
    with sqlite3.connect(data/'paper.sqlite3') as src,sqlite3.connect(backup) as dst:src.backup(dst)
    def start(version,pin):
        atomic_json(data/'service-transition.json',{'backup':str(backup),'reviewed_bundle':pin})
        with open(data/'supervisor.log','ab') as log:child=subprocess.Popen([sys.executable,str(version/'supervisor.py'),'--runtime-root',str(root),'--expected-sha256',pin],cwd=version,stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
        atomic_json(data/'service-transition.json',{'backup':str(backup),'reviewed_bundle':pin,'supervisor_pid':child.pid})
        return child
    child=start(runtime,a.expected_sha256)
    try:
        for _ in range(40):
            if child.poll() is not None:raise RuntimeError('Supervisor exited')
            try:
                r=json.loads((data/'launch-receipt.json').read_text())
                if r['reviewed_bundle']==a.expected_sha256 and r.get('supervised'):
                    print(json.dumps({'upgraded':True,'reviewed_bundle':a.expected_sha256,'supervisor_pid':child.pid,'live_execution':False}));return
            except (OSError,ValueError):pass
            time.sleep(.25)
        raise RuntimeError('Supervisor receipt unavailable')
    except Exception:
        child.terminate();child.wait(timeout=20);start(old,a.prior_sha256);raise
if __name__=='__main__':main()
