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


def load_capture_settings(journal_path):
    data = Path(journal_path).parent
    config = data/'capture-config.json'
    if not config.exists():
        return {'path':data/'capture.sqlite3','max_bytes':2*1024**3,'min_free':2*1024**3,'configured':False}
    if config.is_symlink():raise ValueError('Capture config must be a regular private file')
    c = json.loads(config.read_text())
    if c.get('schema')!='btc_capture_storage.v1':raise ValueError('Unsupported capture storage config')
    path = Path(c['path'])
    if not path.is_absolute() or path.is_symlink() or path.parent.resolve()!=path.parent:
        raise ValueError('Unsafe capture destination')
    if not path.parent.is_dir() or path.parent.stat().st_uid!=os.geteuid():
        raise ValueError('Configured capture destination unavailable or not owned')
    if path.parent.stat().st_dev!=c['device']:
        raise ValueError('Capture volume changed or is not mounted; root fallback refused')
    cap,floor = c['max_bytes'],c['min_free']
    if type(cap) is not int or type(floor) is not int or not 0<cap<=1024*1024**3 or floor<0:
        raise ValueError('Invalid capture storage budget')
    return {'path':path,'max_bytes':cap,'min_free':floor,'configured':True}


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


def stamp(value):
    x = float(value)
    if x > 1e11: x /= 1000
    if not math.isfinite(x) or x <= 0: raise ValueError('Invalid feed timestamp')
    return x


class BookStream:
    def __init__(self, capture, socket_factory):
        self.capture, self.socket_factory = capture, socket_factory
        self.lock = threading.RLock()
        self.stop = threading.Event()
        self.market = None
        self.tokens = {}
        self.books = {}
        self.minimums = {}
        self.error = 'Connecting to public outcome stream'
        self.generation = 0
        self.events = 0

    def configure(self, market, anchor, rest_books):
        tokens = market['clobTokenIds']
        if isinstance(tokens, str): tokens = json.loads(tokens)
        identity = (market['conditionId'], tuple(tokens))
        with self.lock:
            prior = (self.market['conditionId'], tuple(self.tokens)) if self.market else None
            if prior != identity:
                self.market = dict(market)
                self.tokens = dict(zip(tokens, ('Up', 'Down')))
                self.books = {}
                self.minimums = {}
                self.generation += 1
                self.capture.offer('market_metadata', {'market': market, 'anchor': anchor},
                                   condition_id=market['conditionId'])
            elif self.market.get('_anchor') != anchor:
                self.capture.offer('market_anchor', {'anchor': anchor, 'slug': market['slug']},
                                   condition_id=market['conditionId'])
            self.market['_anchor'] = anchor
            for token, side in self.tokens.items():
                # Never infer a missing minimum order size as zero.
                if rest_books.get(side, {}).get('min_order_size') is not None:
                    self.minimums[token] = rest_books[side]['min_order_size']

    def handle(self, event, received_at=None, mono=None):
        received_at = time.time() if received_at is None else received_at
        mono = time.monotonic_ns() if mono is None else mono
        with self.lock:
            if not self.market or event.get('market') != self.market['conditionId']:
                return
            kind = event.get('event_type')
            source = stamp(event['timestamp']) if event.get('timestamp') else None
            self.capture.offer('market_stream', event, source, event['market'], event.get('asset_id'),
                               received_at, mono)
            self.events += 1
            if source is None or not -1 <= received_at-source <= 3:
                return
            if kind == 'book':
                token = event['asset_id']
                if token not in self.tokens: return
                old = self.books.get(token)
                if old and source < old['source_timestamp']: return
                b = {'bids': {float(x['price']): float(x['size']) for x in event['bids']},
                     'asks': {float(x['price']): float(x['size']) for x in event['asks']},
                     'source_timestamp': source, 'received_at': received_at,
                     'received_mono_ns': mono}
                self.books[token] = b
            elif kind == 'price_change':
                for change in event['price_changes']:
                    token = change['asset_id']; b = self.books.get(token)
                    if not b or source < b['source_timestamp']: continue
                    side = change['side']
                    if side not in ('BUY', 'SELL'): raise ValueError('Unknown book side')
                    levels = b['bids' if side == 'BUY' else 'asks']
                    price, size = float(change['price']), float(change['size'])
                    if not 0 < price < 1 or not math.isfinite(size) or size < 0:
                        raise ValueError('Invalid book delta')
                    if size: levels[price] = size
                    else: levels.pop(price, None)
                    b.update(source_timestamp=source, received_at=received_at, received_mono_ns=mono)
            elif kind == 'tick_size_change':
                # Discard old depth; resubscribe for a full snapshot before new fills.
                self.books = {}; self.generation += 1
                self.error = 'Tick-size change: waiting for a new snapshot'

    def snapshot(self, condition, now=None):
        now = time.time() if now is None else now
        with self.lock:
            if not self.market or condition != self.market['conditionId']:
                raise ValueError('Stream contract changed')
            out = {}
            for token, side in self.tokens.items():
                b = self.books.get(token)
                if not b or token not in self.minimums:
                    raise ValueError('Waiting for full stream depth / minimum-size metadata')
                if not -1 <= now-b['source_timestamp'] <= 3 or not 0 <= now-b['received_at'] <= 3:
                    raise ValueError('Stream book is stale')
                out[side] = {'asset_id': token, 'market': condition, 'timestamp': b['source_timestamp']*1000,
                             'received_at': b['received_at'], 'received_mono_ns': b['received_mono_ns'],
                             'min_order_size': self.minimums[token],
                             'bids': [{'price':str(p),'size':str(n)} for p,n in b['bids'].items() if n>0],
                             'asks': [{'price':str(p),'size':str(n)} for p,n in b['asks'].items() if n>0]}
            return out

    def run(self):
        while not self.stop.is_set():
            ws = None
            try:
                with self.lock:
                    tokens, generation = list(self.tokens), self.generation
                    self.books = {}
                if not tokens:
                    self.stop.wait(.25); continue
                ws = self.socket_factory('ws-subscriptions-clob.polymarket.com', '/ws/market')
                ws.s.settimeout(1)
                ws.send(json.dumps({'assets_ids':tokens, 'type':'market'}))
                heartbeat = time.monotonic()
                self.error = None
                while not self.stop.is_set() and generation == self.generation:
                    if time.monotonic()-heartbeat >= 8:
                        ws.send('PING'); heartbeat = time.monotonic()
                    try: raw = ws.receive()
                    except socket.timeout: continue
                    if not raw or raw in ('PONG','PING'): continue
                    arrival, mono = time.time(), time.monotonic_ns()
                    events = json.loads(raw)
                    for e in events if isinstance(events,list) else [events]:
                        self.handle(e, arrival, mono)
            except Exception:
                with self.lock:
                    self.error = 'Outcome stream unavailable; shadow entries paused'
                    self.books = {}
                self.capture.offer('feed_status', {'feed':'market','status':'disconnected'})
                self.stop.wait(2)
            finally:
                if ws: ws.close()
