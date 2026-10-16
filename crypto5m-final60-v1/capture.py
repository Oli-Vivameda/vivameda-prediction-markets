"""Bounded persistent public feed capture and live outcome-book reconstruction."""
import hashlib
import json
import math
import os
from pathlib import Path
import queue
import shutil
import socket
import sqlite3
import threading
import time
import uuid
import zlib


def verify_capture(path):
    prior = ''
    total = 0
    with sqlite3.connect(str(path)) as db:
        for first,last,n,session,payload,digest in db.execute(
                'SELECT first_arrival,last_arrival,event_count,session,payload,digest FROM feed_batches ORDER BY id'):
            raw = zlib.decompress(payload)
            if hashlib.sha256(prior.encode()+raw).hexdigest() != digest:
                raise ValueError('Capture digest chain differs')
            events = json.loads(raw)
            if len(events)!=n or events[0][2]!=first or events[-1][2]!=last or any(e[6]!=session for e in events):
                raise ValueError('Capture batch metadata differs')
            total += n
            prior = digest
    return total


class Capture:
    def __init__(self, path, max_bytes=2*1024*1024*1024, min_free=2*1024*1024*1024):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.max_bytes, self.min_free = max_bytes, min_free
        self.session = uuid.uuid4().hex
        self.queue = queue.Queue(maxsize=20000)
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self.error = None
        self.enqueued = self.stored = self.dropped = 0
        self.last_write = None
        self.counts = {}
        self.queued_bytes = 0
        self.queue_byte_limit = 32*1024*1024
        with self.connect() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('CREATE TABLE IF NOT EXISTS feed_batches (id INTEGER PRIMARY KEY, '
                       'first_arrival REAL, last_arrival REAL, event_count INTEGER, session TEXT, '
                       'payload BLOB, digest TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS market_batches '
                       '(condition_id TEXT, batch_id INTEGER, PRIMARY KEY(condition_id,batch_id))')
            db.execute('CREATE INDEX IF NOT EXISTS feed_arrival ON feed_batches(first_arrival)')
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def connect(self):
        return sqlite3.connect(str(self.path), timeout=10)

    def bytes(self):
        return sum(p.stat().st_size for p in (self.path, Path(str(self.path)+'-wal'),
                                             Path(str(self.path)+'-shm')) if p.exists())

    def offer(self, kind, payload, source_timestamp=None, condition_id=None, asset_id=None,
              received_at=None, received_mono_ns=None):
        if self.error or self.stop.is_set():
            if self.error and not self.stop.is_set():
                with self.lock:self.dropped += 1
            return False
        try:
            raw = json.dumps(payload, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
            if len(raw) > 262144:
                raise ValueError('Capture payload exceeds bounded size')
            item = (kind, source_timestamp, time.time() if received_at is None else received_at,
                    time.monotonic_ns() if received_mono_ns is None else received_mono_ns,
                    condition_id, asset_id, self.session, raw)
            with self.lock:
                if self.queued_bytes+len(raw)>self.queue_byte_limit:raise queue.Full
                self.queue.put_nowait(item)
                self.queued_bytes+=len(raw)
                self.enqueued += 1
            return True
        except (ValueError, TypeError, queue.Full):
            with self.lock:
                self.error = 'Capture gap: payload/queue limit; shadow entries paused'
                self.dropped += 1
            return False

    def run(self):
        try:
            with self.connect() as db:
                last = db.execute('SELECT digest FROM feed_batches ORDER BY id DESC LIMIT 1').fetchone()
                prior = last[0] if last else ''
                while not self.stop.is_set() or not self.queue.empty():
                    batch = []
                    try: batch.append(self.queue.get(timeout=.25))
                    except queue.Empty: continue
                    if self.queue.qsize()<100:self.stop.wait(.02)
                    while len(batch) < 2000:
                        try: batch.append(self.queue.get_nowait())
                        except queue.Empty: break
                    if self.bytes() >= self.max_bytes or shutil.disk_usage(self.path.parent).free < self.min_free:
                        raise RuntimeError('Capture storage limit reached; records preserved, shadow paused')
                    # Compress complete event envelopes together to avoid repeating long token IDs.
                    envelopes = [[*row[:7], json.loads(row[7])] for row in batch]
                    raw = json.dumps(envelopes, separators=(',', ':'), allow_nan=False).encode()
                    digest = hashlib.sha256(prior.encode()+raw).hexdigest()
                    cursor = db.execute('INSERT INTO feed_batches(first_arrival,last_arrival,event_count,'
                                        'session,payload,digest) VALUES (?,?,?,?,?,?)',
                                        (batch[0][2], batch[-1][2], len(batch), self.session,
                                         zlib.compress(raw,level=1), digest))
                    for condition in {r[4] for r in batch if r[4]}:
                        db.execute('INSERT INTO market_batches VALUES (?,?)',(condition,cursor.lastrowid))
                    prior = digest
                    db.commit()
                    with self.lock:
                        self.queued_bytes -= sum(len(r[7]) for r in batch)
                        self.stored += len(batch)
                        self.last_write = time.time()
                        for r in batch: self.counts[r[0]] = self.counts.get(r[0], 0)+1
                    for _ in batch: self.queue.task_done()
                    # Keep the WAL bounded; no captured history is removed.
                    if self.stored % 100 < len(batch): db.execute('PRAGMA wal_checkpoint(PASSIVE)')
        except Exception as exc:
            with self.lock: self.error = str(exc) if isinstance(exc, RuntimeError) else 'Capture writer failed; shadow paused'

    def healthy(self):
        with self.queue.mutex:
            oldest_age=time.time()-self.queue.queue[0][2] if self.queue.queue else 0
        return (not self.error and self.thread.is_alive() and oldest_age<=2 and self.queue.qsize() < 5000
                and self.last_write is not None and time.time()-self.last_write <= 5)

    def state(self):
        with self.lock:
            return {'healthy': self.healthy(), 'error': self.error, 'session': self.session,
                    'stored_this_session': self.stored, 'enqueued_this_session': self.enqueued,
                    'dropped': self.dropped, 'queued': self.queue.qsize(), 'queued_bytes':self.queued_bytes, 'counts': dict(self.counts),
                    'last_write': self.last_write, 'bytes': self.bytes(), 'cap_bytes': self.max_bytes, 'min_free_bytes':self.min_free}

    def close(self):
        self.stop.set(); self.thread.join(timeout=3)

