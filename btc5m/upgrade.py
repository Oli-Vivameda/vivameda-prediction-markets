"""Reviewed non-root upgrade of the existing isolated paper process only."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
import time
import urllib.request
from launch import bundle, FILES
from capture import load_capture_settings
from storage_migration import validate_destination, copy_capture, write_config




def health():
    with urllib.request.urlopen('http://127.0.0.1:8765/api/state', timeout=2) as r:
        return json.load(r)


def start(runtime, data):
    log = open(data/'runtime.log', 'ab')
    return subprocess.Popen([sys.executable, str(runtime/'agent.py'), '--database', str(data/'paper.sqlite3')],
        cwd=runtime, stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)


def main():
    p=argparse.ArgumentParser();p.add_argument('--upgrade',action='store_true')
    p.add_argument('--expected-sha256');p.add_argument('--upgrade-from-sha256');p.add_argument('--runtime-root');p.add_argument('--capture-root');a=p.parse_args()
    pin=bundle()
    if not a.upgrade:
        print(json.dumps({'reviewed_bundle':pin,'upgraded':False}));return
    if os.geteuid()==0:raise SystemExit('Use the non-root engineering connection')
    if pin!=a.expected_sha256:raise SystemExit('Candidate hash differs')
    if not a.runtime_root:raise SystemExit('Supply the private runtime root')
    root=Path(a.runtime_root).resolve()
    data=root/'data';receipt_path=data/'launch-receipt.json'
    guard=open(data/'upgrade.lock','a');fcntl.flock(guard,fcntl.LOCK_EX|fcntl.LOCK_NB)
    receipt=json.loads(receipt_path.read_text())
    if receipt.get('supervised'):raise SystemExit('Supervised version requires service handoff review')
    old=Path(receipt['runtime']);pid=int(receipt['pid'])
    if receipt['reviewed_bundle']!=a.upgrade_from_sha256:raise SystemExit('Installed revision differs')
    if old.parent!=root or not old.is_dir():raise SystemExit('Unexpected runtime identity')
    proc=Path('/proc')/str(pid)
    if proc.stat().st_uid!=os.geteuid():raise SystemExit('Process owner differs')
    args=(proc/'cmdline').read_bytes().split(b'\0')
    if str(old/'agent.py').encode() not in args or str(data/'paper.sqlite3').encode() not in args:
        raise SystemExit('Process command differs; preserve listener')
    if (proc/'cwd').resolve()!=old:raise SystemExit('Process directory differs')
    old_files = tuple(n for n in FILES if (old/n).exists())
    old_hash = hashlib.sha256()
    for name in old_files:
        old_hash.update(name.encode()+b'\0'+(old/name).read_bytes()+b'\0')
    if old_hash.hexdigest() != receipt['reviewed_bundle']:
        raise SystemExit('Prior runtime source differs')
    capture_settings=load_capture_settings(data/'paper.sqlite3')
    migration_root=None
    if a.capture_root:
        if (data/'capture-config.json').exists():raise SystemExit('Existing capture configuration preserved')
        migration_root=validate_destination(Path(a.capture_root),capture_settings['path'],50*1024**3)
    health()  # Existing listener must work before replacement.
    # Copy candidate to immutable version directory before stopping anything.
    runtime=root/pin;runtime.mkdir(exist_ok=True)
    for name in FILES:
        raw=Path(__file__).with_name(name).read_bytes();target=runtime/name
        if target.exists() and target.read_bytes()!=raw:raise SystemExit('Version directory differs')
        if not target.exists():target.write_bytes(raw)
    backup=data/('paper-backup-'+str(time.time_ns())+'.sqlite3')
    with sqlite3.connect(data/'paper.sqlite3') as src, sqlite3.connect(backup) as dst:
        src.backup(dst)
    # pidfd pins the checked process identity rather than relying on a reusable PID.
    handle=os.pidfd_open(pid)
    signal.pidfd_send_signal(handle,signal.SIGTERM)
    os.close(handle)
    deadline=time.monotonic()+8
    while time.monotonic()<deadline:
        try:
            state=(proc/'stat').read_text().split(') ',1)[1].split()[0]
            if state=='Z':break
        except FileNotFoundError:break
        time.sleep(.1)
    else:raise SystemExit('Prior process did not exit; no second collector started')
    child=None
    migration=None
    created_config=None
    try:
        if migration_root:
            migration=copy_capture(capture_settings['path'],migration_root/'capture.sqlite3')
            created_config=write_config(data,migration_root/'capture.sqlite3',100*1024**3,50*1024**3)
        child=start(runtime,data)
        for _ in range(40):
            if child.poll() is not None:raise RuntimeError('Candidate exited')
            try:
                state=health()
                if state.get('policy')=='btc5m-locked-manual-v2' and state.get('live_execution') is False and state.get('capture') and state.get('shadow'):
                    break
            except (OSError, ValueError):pass
            time.sleep(.25)
        else:raise RuntimeError('Candidate health failed')
        out={'upgraded':True,'pid':child.pid,'runtime':str(runtime),'reviewed_bundle':pin,
             'prior_bundle':receipt['reviewed_bundle'],'backup':str(backup),
             'listener':'127.0.0.1:8765','live_execution':False,'health_verified':True,
             'existing_scanners_changed':False,'service_units_changed':False,'capture_enabled':True,'shadow_enabled':True,
             'capture_migration':migration,'capture_cap_gib':100 if migration else capture_settings['max_bytes']/1024**3,
             'free_space_floor_gib':50 if migration else capture_settings['min_free']/1024**3}
        receipt_path.write_text(json.dumps(out,indent=2)+'\n');print(json.dumps(out))
    except Exception:
        if child and child.poll() is None:
            child.terminate();child.wait(timeout=5)
        if created_config and created_config.exists():created_config.unlink()
        restored=start(old,data)
        receipt['pid']=restored.pid;receipt['rollback_after_upgrade_failure']=True
        receipt_path.write_text(json.dumps(receipt,indent=2)+'\n')
        raise


if __name__=='__main__':main()
