"""Root installs only the new isolated paper study; existing units are never changed."""
import argparse
import json
import os
from pathlib import Path
import pwd
import shutil
import subprocess
import tempfile
import time
from release import bundle,manifest,ROOT,FILES
from common import config

RUNTIME=Path('/opt/vivameda-crypto5m-final60-v2')
UNIT='vivameda-crypto5m-final60-v2.service'


def definition(state,device,pin):
    state=Path(state)
    if not state.is_absolute() or any(x.isspace() or x=='%' for x in str(state)):raise ValueError('unsafe_state_path')
    return f'''[Unit]
Description=Vivameda BTC ETH SOL five-minute isolated paper final-minute partial-TWAP study v2
After=network-online.target
Wants=network-online.target
RequiresMountsFor={state.parent}

[Service]
Type=simple
User=vivameda-engineer
Group=vivameda-engineer
WorkingDirectory={RUNTIME}
ExecStart=/usr/bin/python3 -B {RUNTIME}/worker.py --state {state} --device {device} --expected-sha256 {pin}
Environment=PYTHONDONTWRITEBYTECODE=1
UMask=0077
Restart=on-failure
RestartSec=20
TimeoutStopSec=15
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
NoNewPrivileges=true
CapabilityBoundingSet=
ReadWritePaths={state}
InaccessiblePaths=-/var/lib/vivameda-engineering/products/polymarket-all-live-v1-state
InaccessiblePaths=-/var/lib/vivameda-engineering/products/btc5m-owner-entry-v1-state
InaccessiblePaths=-/var/lib/vivameda-engineering/products/btc5m-continuous-v1-state
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
MemoryMax=512M
CPUQuota=100%

[Install]
WantedBy=multi-user.target
'''


def install(expected,state,device):
    if os.geteuid()!=0 or expected!=bundle():raise ValueError('root_and_exact_reviewed_bundle_required')
    c=config();state=Path(state);unit=Path('/etc/systemd/system')/UNIT
    if RUNTIME.exists() or unit.exists():raise ValueError('existing_deployment_preserved_review_upgrade_separately')
    if not state.is_absolute() or state.is_symlink() or state.resolve()!=state:raise ValueError('unsafe_state_path')
    if not state.parent.is_dir() or state.parent.stat().st_dev!=device:raise ValueError('capture_volume_missing_or_changed')
    if shutil.disk_usage(state.parent).free<c['minimum_free_bytes']:raise ValueError('storage_guard')
    actor=pwd.getpwnam('vivameda-engineer')
    def drop():os.initgroups(actor.pw_name,actor.pw_gid);os.setgid(actor.pw_gid);os.setuid(actor.pw_uid)
    subprocess.run(['/usr/bin/python3','-B','-m','unittest','-q','test_study','test_reference','test_v3','test_v4','test_v5','test_final60','test_final60_v2'],cwd=ROOT,preexec_fn=drop,check=True)
    if state.exists():
        if state.stat().st_dev!=device or state.stat().st_uid!=actor.pw_uid or state.stat().st_mode&0o077:raise ValueError('existing_study_ownership_or_volume')
        # Validate resume without reading raw market rows or changing the prior ledger.
        if (state/'ledger.sqlite3').exists():
            code='from pathlib import Path; from common import config; from ledger import Ledger; from release import bundle; import time; j=Ledger(Path('+repr(str(state/'ledger.sqlite3'))+'),config(),bundle(),time.time()); j.close()'
            subprocess.run(['/usr/bin/python3','-B','-c',code],cwd=ROOT,preexec_fn=drop,check=True)
    else:state.mkdir(mode=0o700);os.chown(state,actor.pw_uid,actor.pw_gid)
    body=definition(state,device,expected)
    with tempfile.TemporaryDirectory() as temp:
        p=Path(temp)/UNIT;p.write_text(body);subprocess.run(['systemd-analyze','verify',str(p)],check=True)
    expected_files=manifest();RUNTIME.mkdir(mode=0o750);os.chown(RUNTIME,0,actor.pw_gid)
    for name in FILES:
        target=RUNTIME/name
        with target.open('xb') as f:f.write((ROOT/name).read_bytes())
        target.chmod(0o640);os.chown(target,0,actor.pw_gid)
    import hashlib
    if expected!=bundle() or any(hashlib.sha256((RUNTIME/n).read_bytes()).hexdigest()!=h for n,h in expected_files.items()):raise ValueError('source_changed_during_install')
    unit.write_text(body);unit.chmod(0o644)
    subprocess.run(['systemctl','daemon-reload'],check=True);subprocess.run(['systemctl','enable','--now',UNIT],check=True)
    subprocess.run(['systemctl','is-active','--quiet',UNIT],check=True)
    receipt={'installed':True,'bundle_sha256':expected,'source_hashes':expected_files,'service':UNIT,'installed_at':time.time(),
        'stage':'collecting data—no validated edge','live_execution':False,'signer_read':False,'paid_calls':0,
        'existing_units_changed':False,'real_budgets_changed':False,'original_journals_changed':False}
    p=RUNTIME/'INSTALL_RECEIPT.json';p.write_text(json.dumps(receipt,indent=2,sort_keys=True));p.chmod(0o640);os.chown(p,0,actor.pw_gid)
    return receipt

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--install',action='store_true');p.add_argument('--expected-sha256');p.add_argument('--state');p.add_argument('--device',type=int);a=p.parse_args()
    print(json.dumps(install(a.expected_sha256,a.state,a.device) if a.install else {'bundle_sha256':bundle(),'live_execution':False}))
