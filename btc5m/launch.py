"""Start the reviewed paper-only copilot as the engineering user, on loopback."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
import urllib.request

HERE=Path(__file__).resolve().parent
FILES=('agent.py','dashboard.html','quant.py','capture.py','shadow.py','operations.py','supervisor.py','training.py','launch.py')
def bundle():
    h=hashlib.sha256()
    for name in FILES:
        h.update(name.encode()+b'\0'+(HERE/name).read_bytes()+b'\0')
    return h.hexdigest()

def main():
    p=argparse.ArgumentParser();p.add_argument('--start',action='store_true');p.add_argument('--expected-sha256');p.add_argument('--runtime-root');a=p.parse_args()
    pin=bundle()
    if not a.start:print(json.dumps({'reviewed_bundle':pin,'started':False}));return
    if os.geteuid()==0:raise SystemExit('Run as vivameda-engineer; root is unnecessary')
    if a.expected_sha256!=pin:raise SystemExit('Reviewed source hash differs')
    if not a.runtime_root:raise SystemExit('Supply the private runtime root')
    root=Path(a.runtime_root).resolve()
    runtime=root/pin
    data=root/'data'
    runtime.mkdir(parents=True,exist_ok=True);data.mkdir(exist_ok=True)
    for name in FILES:
        target=runtime/name
        if target.exists() and target.read_bytes()!=(HERE/name).read_bytes():raise SystemExit('Runtime version differs')
        if not target.exists():shutil.copyfile(HERE/name,target)
    with socket.socket() as s:
        if s.connect_ex(('127.0.0.1',8765))==0:raise SystemExit('Port 8765 already in use; existing listener preserved')
    log=open(data/'runtime.log','ab')
    child=subprocess.Popen([sys.executable,str(runtime/'agent.py'),'--database',str(data/'paper.sqlite3')],
        cwd=runtime,stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
    for _ in range(40):
        if child.poll() is not None:raise SystemExit('Paper server exited; inspect its private runtime log')
        try:
            with urllib.request.urlopen('http://127.0.0.1:8765/api/state',timeout=1) as response:
                state=json.load(response)
            receipt={'started':True,'pid':child.pid,'reviewed_bundle':pin,'runtime':str(runtime),
                     'listener':'127.0.0.1:8765','live_execution':False,'health_verified':True,
                     'existing_scanners_changed':False,'service_units_changed':False}
            (data/'launch-receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
            print(json.dumps(receipt));return
        except (OSError,ValueError):time.sleep(.25)
    child.terminate();raise SystemExit('Paper server health check failed')

if __name__=='__main__':main()
