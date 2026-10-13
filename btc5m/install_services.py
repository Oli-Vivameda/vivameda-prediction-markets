"""Reviewed root installation of dedicated BTC paper units; application runs non-root."""
import argparse,hashlib,json,os,subprocess,time,urllib.request
from pathlib import Path

def units(root,pin,training_python,capture_root):
    runtime=root/pin
    for path in (root,training_python,capture_root):
        if not path.is_absolute() or any(c.isspace() or c=='%' for c in str(path)):raise ValueError('Service paths must be absolute without whitespace or specifiers')
    def q(p):return '"'+str(p).replace('\\','\\\\').replace('"','\\"')+'"'
    common='User=vivameda-engineer\nGroup=vivameda-engineer\nNoNewPrivileges=true\nPrivateTmp=true\nProtectSystem=strict\nProtectHome=true\nReadWritePaths='+q(root/'data')+' '+q(capture_root)+'\n'
    main='[Unit]\nDescription=BTC five-minute paper supervisor\nAfter=network-online.target\nWants=network-online.target\n[Service]\n'+common+'WorkingDirectory='+str(runtime)+'\nExecStart=/usr/bin/python3 '+q(runtime/'supervisor.py')+' --runtime-root '+q(root)+' --expected-sha256 '+pin+'\nRestart=on-failure\nRestartSec=15\nTimeoutStopSec=30\nKillMode=control-group\nMemoryMax=2G\n[Install]\nWantedBy=multi-user.target\n'
    train='[Unit]\nDescription=Frozen BTC chronological challenger study\n[Service]\nType=oneshot\n'+common+'WorkingDirectory='+str(runtime)+'\nExecStart='+q(training_python)+' '+q(runtime/'training.py')+' --journal '+q(root/'data/paper.sqlite3')+' --output '+q(capture_root/'research')+'\nNice=15\nCPUQuota=100%\nMemoryMax=2G\nTimeoutStartSec=600\n'
    timer='[Unit]\nDescription=Daily frozen BTC study gate\n[Timer]\nOnCalendar=*-*-* 08:05:00 Asia/Nicosia\nPersistent=true\n[Install]\nWantedBy=timers.target\n'
    return {'vivameda-btc5m-paper.service':main,'vivameda-btc5m-training.service':train,'vivameda-btc5m-training.timer':timer}

def main():
    p=argparse.ArgumentParser();p.add_argument('--runtime-root',required=True);p.add_argument('--training-python',required=True);p.add_argument('--expected-sha256',required=True);p.add_argument('--installer-sha256',required=True);a=p.parse_args()
    if os.geteuid()!=0:raise SystemExit('Root is required to install system units')
    if hashlib.sha256(Path(__file__).read_bytes()).hexdigest()!=a.installer_sha256:raise ValueError('Installer hash differs')
    from launch import bundle,FILES
    if bundle()!=a.expected_sha256:raise ValueError('Reviewed source differs')
    root=Path(a.runtime_root).resolve();runtime=root/a.expected_sha256
    for n in FILES:
        if (runtime/n).read_bytes()!=Path(__file__).with_name(n).read_bytes():raise ValueError('Installed source differs')
    cfg=json.loads((root/'data/capture-config.json').read_text());capture=Path(cfg['path']).parent
    generated=units(root,a.expected_sha256,Path(a.training_python).absolute(),capture)
    dest=Path('/etc/systemd/system')
    for name in generated:
        if (dest/name).exists():raise ValueError('Existing BTC system units require explicit upgrade review')
    staging=root/'data/service-units';staging.mkdir(exist_ok=True)
    for name,body in generated.items():(staging/name).write_text(body)
    subprocess.run(['systemd-analyze','verify',*[str(staging/n) for n in generated]],check=True)
    subprocess.run(['runuser','-u','vivameda-engineer','--','/usr/bin/python3',str(Path(__file__).with_name('transition.py')),'--runtime-root',str(root),'--expected-sha256',a.expected_sha256,'--stop-only'],check=True)
    for name,body in generated.items():(dest/name).write_text(body)
    subprocess.run(['systemctl','daemon-reload'],check=True)
    try:
        subprocess.run(['systemctl','enable','--now','vivameda-btc5m-paper.service','vivameda-btc5m-training.timer'],check=True)
        for _ in range(30):
            try:
                state=json.load(urllib.request.urlopen('http://127.0.0.1:8765/api/state',timeout=2))
                if state.get('live_execution') is False and state.get('operations'):break
            except (OSError,ValueError):pass
            time.sleep(.5)
        else:raise RuntimeError('Installed service health unavailable')
    except Exception:
        subprocess.run(['systemctl','disable','--now','vivameda-btc5m-paper.service','vivameda-btc5m-training.timer'],check=False)
        for name in generated:
            if (dest/name).exists():(dest/name).unlink()
        subprocess.run(['systemctl','daemon-reload'],check=True)
        subprocess.run(['runuser','-u','vivameda-engineer','--','/usr/bin/python3',str(Path(__file__).with_name('transition.py')),'--runtime-root',str(root),'--expected-sha256',a.expected_sha256],check=True)
        raise
    print(json.dumps({'installed':True,'live_execution':False,'units':list(generated)}))
if __name__=='__main__':main()
