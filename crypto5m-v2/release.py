"""Reviewed source manifest; independent of commit IDs and runtime data."""
import hashlib
from pathlib import Path
from common import digest
FILES=('common.py','capture.py','transport.py','market.py','feeds.py','reference.py','model.py','strategy.py','ledger.py','worker.py','report.py','release.py','install.py','test_study.py','test_reference.py','config.json','PROTOCOL.md')
ROOT=Path(__file__).resolve().parent

def manifest():return {name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in FILES}
def bundle():return digest(manifest())
