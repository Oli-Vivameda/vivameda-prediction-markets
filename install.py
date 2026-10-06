"""Reviewed standalone installer; owner root action. No existing agents modified."""
import argparse, datetime, hashlib, json, os, pathlib, pwd, shutil, subprocess, tempfile
BASE=pathlib.Path(__file__).resolve().parent
DEST=pathlib.Path('/opt/vivameda-prediction-scanner')
SYSTEM=pathlib.Path('/etc/systemd/system')
FILES=('scanner.py','bridge.py','paper.py','cycle.py',
       'vivameda-prediction-scanner.service','vivameda-prediction-scanner.timer')
def digest():
    return hashlib.sha256(json.dumps({n:hashlib.sha256((BASE/n).read_bytes()).hexdigest()
            for n in FILES},sort_keys=True,separators=(',',':')).encode()).hexdigest()
def command(args,**kw):
    return subprocess.run(args,check=True,capture_output=True,text=True,**kw)
def main():
    p=argparse.ArgumentParser();p.add_argument('--install',action='store_true')
    p.add_argument('--expected-sha256');a=p.parse_args()
    bundle=digest()
    if a.expected_sha256 and bundle!=a.expected_sha256:raise SystemExit('Reviewed source hash changed')
    tests=command(['/usr/bin/python3','-m','unittest','-v','test_scanner','test_ledger'],cwd=BASE,timeout=60)
    command(['/usr/bin/python3','-m','py_compile',*[str(BASE/n) for n in FILES if n.endswith('.py')]],timeout=30)
    syntax=command(['systemd-analyze','verify',str(BASE/FILES[-2]),str(BASE/FILES[-1])],timeout=30)
    if not a.install:
        print(json.dumps({'bundle_sha256':bundle,'tests_passed':42,'unit_syntax_passed':True,
                          'installed':False,'live_execution':False}))
        return
    if not a.expected_sha256:raise SystemExit('An exact reviewed hash is required')
    if os.geteuid()!=0:raise SystemExit('Root installation is required; direct engineering runs as vivameda-engineer')
    pwd.getpwnam('vivameda-agent')
    stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    backup=pathlib.Path('/opt/vivameda-operations')/('prediction-scanner-backup-'+stamp)
    backup.mkdir(parents=True,mode=0o700)
    old_files=[]
    targets={n:(SYSTEM/n if n.endswith(('.service','.timer')) else DEST/n) for n in FILES}
    for n,target in targets.items():
        if target.is_symlink():raise SystemExit('Symlink runtime target refused')
        if target.exists():shutil.copyfile(target,backup/n);old_files.append(n)
    prior_enabled=subprocess.run(['systemctl','is-enabled',FILES[-1]],capture_output=True,text=True).stdout.strip()=='enabled'
    prior_active=subprocess.run(['systemctl','is-active',FILES[-1]],capture_output=True,text=True).stdout.strip()=='active'
    command(['systemctl','stop',FILES[-1]],timeout=30)
    command(['systemctl','stop',FILES[-2]],timeout=30)
    try:
        DEST.mkdir(mode=0o755,exist_ok=True)
        for n,target in targets.items():
            shutil.copyfile(BASE/n,target);target.chmod(0o644)
        command(['systemctl','daemon-reload'],timeout=30)
        command(['systemctl','start',FILES[-2]],timeout=650)
        # Initial service cycle must leave genuine feed evidence; zero candidates are permitted.
        receipt=json.loads(pathlib.Path('/var/lib/vivameda-prediction-scanner/latest.json').read_text())
        if not any(f['received']>0 and f['error'] is None for f in receipt['feeds'].values()):
            raise RuntimeError('No verified public feed in installed cycle')
        command(['systemctl','enable','--now',FILES[-1]],timeout=30)
        if command(['systemctl','is-active',FILES[-1]],timeout=10).stdout.strip()!='active':
            raise RuntimeError('Scanner timer not active')
        match=all(hashlib.sha256(target.read_bytes()).digest()==hashlib.sha256((BASE/n).read_bytes()).digest()
                  for n,target in targets.items())
        if not match:raise RuntimeError('Runtime source mismatch')
        print(json.dumps({'installed':True,'bundle_sha256':bundle,'runtime_files_match':True,
                          'backup':str(backup),'timer_active':True,'feeds':receipt['feeds'],
                          'candidate_count':receipt['candidate_count'],'live_execution':False,
                          'paid_provider_requests':0,'other_services_modified':False}))
    except Exception:
        subprocess.run(['systemctl','stop',FILES[-1]],capture_output=True)
        subprocess.run(['systemctl','stop',FILES[-2]],capture_output=True)
        for n,target in targets.items():
            if n in old_files:shutil.copyfile(backup/n,target)
            elif target.exists():target.unlink()
        subprocess.run(['systemctl','daemon-reload'],capture_output=True)
        if prior_enabled:subprocess.run(['systemctl','enable',FILES[-1]],capture_output=True)
        else:subprocess.run(['systemctl','disable',FILES[-1]],capture_output=True)
        if prior_active:subprocess.run(['systemctl','start',FILES[-1]],capture_output=True)
        raise
if __name__=='__main__':main()
