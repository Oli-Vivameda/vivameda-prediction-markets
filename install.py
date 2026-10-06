"""Reviewed standalone hourly scanner installer; owner root activation."""
import argparse, datetime, hashlib, json, os, pathlib, pwd, re, shutil, subprocess
BASE=pathlib.Path(__file__).resolve().parent
DEST=pathlib.Path('/opt/vivameda-prediction-scanner')
SYSTEM=pathlib.Path('/etc/systemd/system')
FILES=('scanner.py','bridge.py','paper.py','cycle.py','notify.py',
       'vivameda-prediction-scanner.service','vivameda-prediction-scanner.timer')
TESTS=('test_scanner','test_ledger','test_notify','test_install','test_configure_telegram')
CREDENTIAL_SOURCE=DEST/'telegram_credentials.json'

def digest():
    names=FILES+('install.py','configure_telegram.py',)+tuple(n+'.py' for n in TESTS)
    return hashlib.sha256(json.dumps({n:hashlib.sha256((BASE/n).read_bytes()).hexdigest()
            for n in names},sort_keys=True,separators=(',',':')).encode()).hexdigest()

def command(args,**kw):
    return subprocess.run(args,check=True,capture_output=True,text=True,**kw)

def stop_existing(unit):
    state=command(['systemctl','show',unit,'--property=LoadState','--value'],timeout=10).stdout.strip()
    if state=='not-found':return False
    if not state:raise RuntimeError('Unable to determine scoped unit state')
    command(['systemctl','stop',unit],timeout=30)
    return True

def main():
    p=argparse.ArgumentParser();p.add_argument('--install',action='store_true')
    p.add_argument('--expected-sha256');a=p.parse_args()
    bundle=digest()
    if a.expected_sha256 and bundle!=a.expected_sha256:raise SystemExit('Reviewed source hash changed')
    tests=command(['/usr/bin/python3','-m','unittest','-v',*TESTS],cwd=BASE,timeout=60)
    count=re.search(r'Ran (\d+) tests',tests.stderr)
    if not count:raise RuntimeError('Test receipt missing')
    tests_passed=int(count.group(1))
    command(['/usr/bin/python3','-m','py_compile',*[str(BASE/n) for n in FILES if n.endswith('.py')]],timeout=30)
    command(['systemd-analyze','verify',str(BASE/FILES[-2]),str(BASE/FILES[-1])],timeout=30)
    if not a.install:
        print(json.dumps({'bundle_sha256':bundle,'tests_passed':tests_passed,'unit_syntax_passed':True,
                          'installed':False,'cadence':'hourly','telegram_enabled':True,'live_execution':False}))
        return
    if not a.expected_sha256:raise SystemExit('An exact reviewed hash is required')
    if os.geteuid()!=0:raise SystemExit('Root activation required; connector engineering is non-root')
    agent=pwd.getpwnam('vivameda-agent')
    # Preserve the configured prediction destination, including dedicated bot pairing.
    if CREDENTIAL_SOURCE.is_symlink():raise SystemExit('Symlink credential source refused')
    credentials=json.loads(CREDENTIAL_SOURCE.read_text())
    if not credentials.get('bot_token') or not credentials.get('chat_id'):
        raise SystemExit('Existing owner Telegram configuration incomplete')
    stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    backup=pathlib.Path('/opt/vivameda-operations')/('prediction-scanner-backup-'+stamp)
    backup.mkdir(parents=True,mode=0o700)
    old_files=[]
    targets={n:(SYSTEM/n if n.endswith(('.service','.timer')) else DEST/n) for n in FILES}
    for n,target in targets.items():
        if target.is_symlink():raise SystemExit('Symlink runtime target refused')
        if target.exists():shutil.copyfile(target,backup/n);old_files.append(n)
    creds_target=DEST/'telegram_credentials.json'
    if creds_target.is_symlink():raise SystemExit('Symlink credential target refused')
    prior_creds=creds_target.exists()
    if prior_creds:shutil.copyfile(creds_target,backup/'telegram_credentials.json')
    prior_enabled=subprocess.run(['systemctl','is-enabled',FILES[-1]],capture_output=True,text=True).stdout.strip()=='enabled'
    prior_active=subprocess.run(['systemctl','is-active',FILES[-1]],capture_output=True,text=True).stdout.strip()=='active'
    try:
        stop_existing(FILES[-1]);stop_existing(FILES[-2])
        DEST.mkdir(mode=0o755,exist_ok=True)
        for n,target in targets.items():
            shutil.copyfile(BASE/n,target);target.chmod(0o644)
        # Credentials are private, excluded from source, and read only by the service group.
        creds_target.write_text(json.dumps(credentials))
        creds_target.chmod(0o640);os.chown(creds_target,0,agent.pw_gid)
        command(['systemctl','daemon-reload'],timeout=30)
        command(['systemctl','start',FILES[-2]],timeout=650)
        receipt=json.loads(pathlib.Path('/var/lib/vivameda-prediction-scanner/cycle_latest.json').read_text())
        if not any(f['received']>0 and f['error'] is None for f in receipt['feeds'].values()):
            raise RuntimeError('No verified public feed in installed cycle')
        if receipt.get('telegram',{}).get('failed',0):
            raise RuntimeError('Candidate notification failed')
        command(['runuser','-u','vivameda-agent','--','/usr/bin/python3',str(DEST/'notify.py'),'startup'],cwd=DEST,timeout=30)
        command(['systemctl','enable','--now',FILES[-1]],timeout=30)
        if command(['systemctl','is-active',FILES[-1]],timeout=10).stdout.strip()!='active':
            raise RuntimeError('Scanner timer not active')
        match=all(hashlib.sha256(target.read_bytes()).digest()==hashlib.sha256((BASE/n).read_bytes()).digest()
                  for n,target in targets.items())
        if not match:raise RuntimeError('Runtime source mismatch')
        next_run=command(['systemctl','show',FILES[-1],'--property=NextElapseUSecRealtime','--value'],timeout=10).stdout.strip()
        print(json.dumps({'installed':True,'bundle_sha256':bundle,'tests_passed':tests_passed,
                          'runtime_files_match':True,'backup':str(backup),'timer_active':True,
                          'cadence':'hourly','next_run':next_run,'telegram_startup_confirmed':True,
                          'feeds':receipt['feeds'],'candidate_count':receipt['candidate_count'],
                          'notifications':receipt['telegram'],'live_execution':False,
                          'paid_provider_requests':0,'other_services_modified':False}))
    except Exception:
        subprocess.run(['systemctl','stop',FILES[-1]],capture_output=True)
        subprocess.run(['systemctl','stop',FILES[-2]],capture_output=True)
        for n,target in targets.items():
            if n in old_files:shutil.copyfile(backup/n,target)
            elif target.exists():target.unlink()
        if prior_creds:
            shutil.copyfile(backup/'telegram_credentials.json',creds_target)
            creds_target.chmod(0o640);os.chown(creds_target,0,agent.pw_gid)
        elif creds_target.exists():creds_target.unlink()
        subprocess.run(['systemctl','daemon-reload'],capture_output=True)
        subprocess.run(['systemctl','enable' if prior_enabled else 'disable',FILES[-1]],capture_output=True)
        if prior_active:subprocess.run(['systemctl','start',FILES[-1]],capture_output=True)
        raise

if __name__=='__main__':
    try:main()
    except Exception as exc:
        # Never include exception bodies or command output: private destination/token may be present.
        raise SystemExit('Scanner activation failed ('+type(exc).__name__+'); prior scoped installation restored where applicable.')
