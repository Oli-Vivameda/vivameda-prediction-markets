"""Bounded recovery of one paper worker; designed for a systemd non-root service."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from launch import bundle
from operations import atomic_json


def recovery_due(heartbeat, now, started, last_bad):
    if now-started<150:return False
    if not heartbeat or now-heartbeat.get('timestamp',0)>90:return True
    h=heartbeat.get('health',{})
    if h.get('operator_action_required'):return False
    return bool(h.get('restart_requested')) and last_bad is not None and now-last_bad>=30


def restart_allowed(history, now):
    return len([t for t in history if now-t<3600])<3


def run(root, expected, stop=None):
    root=Path(root);data=root/'data';here=Path(__file__).resolve().parent
    if expected!=bundle():raise ValueError('Supervisor reviewed bundle differs')
    stop=stop or __import__('threading').Event()
    guard=open(data/'supervisor.lock','a');fcntl.flock(guard,fcntl.LOCK_EX|fcntl.LOCK_NB)
    state_path=data/'supervisor-state.json';beat_path=data/'ops-heartbeat.json'
    previous=json.loads(state_path.read_text()) if state_path.exists() else {}
    history=previous.get('restart_history',[])
    count=previous.get('restart_count',0);child=None
    def terminate(*args):stop.set()
    if __import__('threading').current_thread() is __import__('threading').main_thread():
        signal.signal(signal.SIGTERM,terminate);signal.signal(signal.SIGINT,terminate)
    try:
        while not stop.is_set():
            if child is None:
                if not restart_allowed(history,time.time()):
                    atomic_json(state_path,{'status':'cooldown','restart_count':count,'restart_history':history,
                        'updated_at':time.time(),'live_execution':False})
                    stop.wait(30);continue
                if beat_path.exists():beat_path.unlink()
                log=open(data/'runtime.log','ab')
                child=subprocess.Popen([sys.executable,str(here/'agent.py'),'--database',str(data/'paper.sqlite3')],
                    cwd=here,stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
                log.close();started=time.time();last_bad=None
                atomic_json(data/'launch-receipt.json',{'pid':child.pid,'runtime':str(here),
                    'reviewed_bundle':expected,'supervised':True,'live_execution':False,
                    'backup':previous.get('backup') or json.loads((data/'service-transition.json').read_text()).get('backup')})
            now=time.time()
            try:heartbeat=json.loads(beat_path.read_text())
            except (OSError,ValueError):heartbeat=None
            if heartbeat and heartbeat.get('pid')!=child.pid:heartbeat=None
            bad=bool(heartbeat and heartbeat.get('health',{}).get('restart_requested'))
            last_bad=last_bad or now if bad else None
            exited=child.poll() is not None
            if exited or recovery_due(heartbeat,now,started,last_bad):
                if not exited:
                    child.terminate()
                    try:child.wait(timeout=10)
                    except subprocess.TimeoutExpired:child.kill();child.wait()
                history=[t for t in history if now-t<3600]+[now];count+=1
                from agent import Journal
                Journal(data/'paper.sqlite3').append('ops_restart',{'reason':'worker_exit' if exited else 'watchdog',
                    'restart_count':count,'live_execution':False})
                atomic_json(state_path,{'status':'recovering','restart_count':count,'restart_history':history,'updated_at':now,'live_execution':False})
                child=None;stop.wait(min(60,5*2**min(len(history)-1,4)));continue
            atomic_json(state_path,{'status':'running','worker_pid':child.pid,'restart_count':count,
                'restart_history':history,'updated_at':now,'live_execution':False,
                'health':heartbeat.get('health') if heartbeat else None})
            stop.wait(5)
    finally:
        if child and child.poll() is None:
            child.terminate()
            try:child.wait(timeout=10)
            except subprocess.TimeoutExpired:child.kill();child.wait()


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--runtime-root',required=True);p.add_argument('--expected-sha256',required=True)
    a=p.parse_args();run(a.runtime_root,a.expected_sha256)
