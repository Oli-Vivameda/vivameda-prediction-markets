"""Verified SQLite copy and private destination setup; no dataset deletion."""
from contextlib import closing
import json
import os
from pathlib import Path
import shutil
import sqlite3
import time
from capture import verify_capture


def validate_destination(destination, source, floor):
    p=Path(destination)
    if not p.is_absolute() or p.resolve()!=p or p.is_symlink():
        raise ValueError('Capture root must be an absolute non-symlink directory')
    if not p.is_dir() or p.stat().st_uid!=os.geteuid() or p.stat().st_mode & 0o077:
        raise ValueError('Capture root must be owned and private (0700)')
    if not os.access(p,os.W_OK):raise ValueError('Capture root is not writable')
    if p.stat().st_dev==Path(source).parent.stat().st_dev:
        raise ValueError('Migration requires the reviewed separate filesystem')
    if (p/'capture.sqlite3').exists() or (p/'capture.sqlite3').is_symlink():
        raise ValueError('Existing destination preserved; migration refused')
    if shutil.disk_usage(p).free<floor+Path(source).stat().st_size:
        raise ValueError('Insufficient destination reserve')
    return p


def copy_capture(source, destination):
    source,destination=Path(source),Path(destination)
    if destination.exists():raise ValueError('Existing capture database preserved')
    temporary=destination.with_name('.capture-copy-'+str(time.time_ns())+'.sqlite3')
    try:
        with closing(sqlite3.connect(str(source))) as src,closing(sqlite3.connect(str(temporary))) as dst:
            src.backup(dst)
            if dst.execute('PRAGMA quick_check').fetchone()[0]!='ok':
                raise ValueError('Destination SQLite integrity check failed')
            before=src.execute('SELECT COUNT(*),COALESCE(SUM(event_count),0),MAX(id) FROM feed_batches').fetchone()
            after=dst.execute('SELECT COUNT(*),COALESCE(SUM(event_count),0),MAX(id) FROM feed_batches').fetchone()
            old=src.execute('SELECT digest FROM feed_batches ORDER BY id DESC LIMIT 1').fetchone()
            new=dst.execute('SELECT digest FROM feed_batches ORDER BY id DESC LIMIT 1').fetchone()
        if before!=after or old!=new:raise ValueError('Capture copy prefix differs')
        verified=verify_capture(temporary)
        if verified!=before[1]:raise ValueError('Capture copy event count differs')
        os.chmod(temporary,0o600)
        os.link(temporary,destination)
        temporary.unlink()
        return {'copied_events':verified,'copied_batches':before[0],'prefix_digest':old[0] if old else '',
                'source_preserved':source.exists(),'sqlite_integrity':'ok'}
    except Exception:
        if temporary.exists():temporary.unlink()
        raise


def write_config(data, destination, cap, floor):
    data,destination=Path(data),Path(destination)
    c={'schema':'btc_capture_storage.v1','path':str(destination),
       'device':destination.parent.stat().st_dev,'max_bytes':cap,'min_free':floor}
    config=data/'capture-config.json'
    if config.exists():raise ValueError('Existing capture configuration preserved')
    fd=os.open(config,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as out:
        json.dump(c,out,indent=2);out.write('\n');out.flush();os.fsync(out.fileno())
    return config
