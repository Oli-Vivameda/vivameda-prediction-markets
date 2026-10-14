"""Owner-operated reviewed paper-service installation; no financial execution."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import pwd
import shutil
import subprocess

ROOT=Path(__file__).resolve().parent
FILES=('engine.py','training.py','test_engine.py','PROTOCOL.md','install.py','README.md')

def bundle():
    hashes={n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in FILES}
    sha=hashlib.sha256(json.dumps(hashes,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return {'files':hashes,'bundle_sha256':sha,'live_execution':False}

def units(runtime,state,training_python):
    hardening='''User=vivameda-engineer
Group=vivameda-engineer
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
MemoryMax=512M
TasksMax=32
'''
    service=f'''[Unit]
Description=Vivameda broad Polymarket paper opportunity agent
After=network-online.target
Wants=network-online.target
[Service]
{hardening}WorkingDirectory={runtime}
ReadWritePaths={state}
ExecStart=/usr/bin/python3 {runtime}/engine.py run --state-dir {state} --markets 20 --interval 15
Restart=on-failure
RestartSec=30
CPUQuota=30%
[Install]
WantedBy=multi-user.target
'''
    train=f'''[Unit]
Description=Vivameda prospective quote-risk training gate
[Service]
Type=oneshot
{hardening}WorkingDirectory={runtime}
ReadWritePaths={state}
ExecStart={training_python} {runtime}/training.py --state-dir {state}
CPUQuota=50%
TimeoutStartSec=600
'''
    timer='''[Unit]
Description=Daily Vivameda broad Polymarket model-readiness check
[Timer]
OnCalendar=*-*-* 08:15:00 Asia/Nicosia
Persistent=true
Unit=vivameda-polymarket-all-training.service
[Install]
WantedBy=timers.target
'''
    return {'vivameda-polymarket-all.service':service,'vivameda-polymarket-all-training.service':train,
            'vivameda-polymarket-all-training.timer':timer}

def main():
    p=argparse.ArgumentParser();p.add_argument('--install',action='store_true');p.add_argument('--expected-sha256')
    p.add_argument('--training-python',default='/usr/bin/python3');a=p.parse_args();b=bundle()
    if not a.install:print(json.dumps(b,indent=2));return
    if os.geteuid()!=0:raise ValueError('Owner must install system units as root')
    if a.expected_sha256!=b['bundle_sha256']:raise ValueError('Reviewed bundle hash differs')
    training_python=Path(a.training_python)
    if not training_python.is_absolute() or not training_python.is_file():raise ValueError('Existing training Python required')
    # Only read/exercise isolated tests; no credentials, live orders or external requests.
    subprocess.run([str(training_python),'-m','unittest','-q','test_engine'],cwd=ROOT,check=True)
    base=Path('/var/lib/vivameda-engineering/products')
    runtime=base/'polymarket-all-v1-runtime';state=base/'polymarket-all-v1-state'
    if runtime.exists():raise ValueError('Existing installation preserved; reviewed upgrade required')
    user=pwd.getpwnam('vivameda-engineer')
    state.mkdir(mode=0o700,parents=True,exist_ok=True)
    if state.is_symlink():raise ValueError('State directory symlink refused')
    os.chown(state,user.pw_uid,user.pw_gid);os.chmod(state,0o700)
    runtime.mkdir(mode=0o755)
    for n in FILES:
        shutil.copyfile(ROOT/n,runtime/n);os.chmod(runtime/n,0o644)
    receipts=runtime/'RELEASE.json';receipts.write_text(json.dumps(b,indent=2))
    generated=units(runtime,state,training_python)
    for name,body in generated.items():
        target=Path('/etc/systemd/system')/name
        if target.exists():raise ValueError('Existing system unit preserved: '+name)
    for name,body in generated.items():(Path('/etc/systemd/system')/name).write_text(body)
    subprocess.run(['systemd-analyze','verify',*[str(Path('/etc/systemd/system')/n) for n in generated]],check=True)
    subprocess.run(['systemctl','daemon-reload'],check=True)
    subprocess.run(['systemctl','enable','--now','vivameda-polymarket-all.service','vivameda-polymarket-all-training.timer'],check=True)
    for n in ['vivameda-polymarket-all.service','vivameda-polymarket-all-training.timer']:
        subprocess.run(['systemctl','is-active','--quiet',n],check=True)
    print(json.dumps({'installed':True,**b,'model_trained':False,'runtime':str(runtime),'state':str(state)}))

if __name__=='__main__':main()
