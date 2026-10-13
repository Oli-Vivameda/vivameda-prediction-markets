#!/usr/bin/env python3
"""BTC five-minute research copilot. Public GETs only; no real execution."""
import argparse
import base64
import fcntl
import hashlib
import http.server
import json
import math
import os
import secrets
import signal
import socket
import sqlite3
import ssl
import statistics
import struct
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from quant import Research
from capture import Capture, BookStream, load_capture_settings
from shadow import Shadow
from operations import Operations

VERSION = 'btc5m-brownian-twap-v1'
UA = 'VivamedaPaperResearch/1.0'


def get_json(url):
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': 'application/json'})
    with urllib.request.urlopen(req, timeout=8) as response:
        return json.load(response)


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).isoformat().replace('+00:00', 'Z')


def unpack(value):
    return json.loads(value) if isinstance(value, str) else value


def finite(value, low=0, high=float('inf')):
    x = float(value)
    if not math.isfinite(x) or not low <= x <= high:
        raise ValueError('Number outside permitted range')
    return x


class PublicSocket:
    """Minimal RFC6455 client for the legacy public RTDS feed; no credentials."""
    def __init__(self, host='ws-live-data.polymarket.com', path='/'):
        self.s = ssl.create_default_context().wrap_socket(
            socket.create_connection((host, 443), timeout=8),
            server_hostname=host)
        self.s.settimeout(8)
        key = base64.b64encode(os.urandom(16)).decode()
        request = (f'GET {path} HTTP/1.1\r\nHost: {host}\r\n'
                   'Upgrade: websocket\r\nConnection: Upgrade\r\n'
                   f'Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n'
                   f'User-Agent: {UA}\r\n\r\n')
        self.s.sendall(request.encode())
        header = bytearray()
        while not header.endswith(b'\r\n\r\n') and len(header) < 16384:
            chunk = self.s.recv(1)
            if not chunk:
                raise ConnectionError('Empty websocket handshake')
            header.extend(chunk)
        accept = base64.b64encode(hashlib.sha1((key + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode()).digest()).decode()
        if b' 101 ' not in header.split(b'\r\n')[0] or accept.encode() not in header:
            self.s.close()
            raise ConnectionError('Public reference feed unavailable')

    def send(self, data, opcode=1):
        data = data.encode() if isinstance(data, str) else data
        n = len(data)
        prefix = bytes([0x80 | opcode, 0x80 | n]) if n < 126 else bytes([0x80 | opcode, 0xfe]) + struct.pack('!H', n)
        mask = os.urandom(4)
        self.s.sendall(prefix + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

    def read(self, n):
        data = b''
        while len(data) < n:
            part = self.s.recv(n - len(data))
            if not part:
                raise ConnectionError('Reference feed disconnected')
            data += part
        return data

    def receive(self):
        a, b = self.read(2)
        n = b & 127
        if n == 126:
            n = struct.unpack('!H', self.read(2))[0]
        elif n == 127:
            n = struct.unpack('!Q', self.read(8))[0]
        if n > 1048576 or b & 128 or not a & 128:
            raise ConnectionError('Unsupported reference frame')
        body = self.read(n)
        if a & 15 == 8:
            raise ConnectionError('Reference feed closed')
        if a & 15 == 9:
            self.send(body, 10)
            return None
        return body.decode() if a & 15 == 1 else None

    def close(self):
        self.s.close()


class Reference:
    def __init__(self):
        self.lock = threading.Lock()
        self.points = []
        self.error = 'Connecting to public Chainlink feed'
        self.on_tick = None
        self.stop = threading.Event()

    def add(self, timestamp, price, origin="stream"):
        t = finite(timestamp, 1)
        if t > 1e11:
            t /= 1000
        p = finite(price, 1)
        if t > time.time() + 2 or time.time() - t > 900:
            return
        arrival, mono = time.time(), time.monotonic_ns()
        accepted = False
        with self.lock:
            if not self.points or t > self.points[-1][0]:
                self.points.append((t, p))
                self.points = self.points[-1200:]
                self.error = None
                accepted = True
        if self.on_tick:
            self.on_tick({'price':p,'origin':origin,'accepted_for_model':accepted}, t, arrival, mono)

    def snapshot(self):
        with self.lock:
            return list(self.points), self.error

    def run(self):
        while not self.stop.is_set():
            ws = None
            try:
                ws = PublicSocket()
                ws.send(json.dumps({'action': 'subscribe', 'subscriptions': [
                    {'topic': 'crypto_prices_chainlink', 'type': '*',
                     'filters': json.dumps({'symbol': 'btc/usd'}, separators=(',', ':'))}]}))
                heartbeat = time.monotonic()
                while not self.stop.is_set():
                    if time.monotonic() - heartbeat >= 5:
                        ws.send('PING')
                        heartbeat = time.monotonic()
                    try:
                        raw = ws.receive()
                    except socket.timeout:
                        ws.send('PING')
                        continue
                    if not raw or raw in ('PONG', 'PING'):
                        continue
                    message = json.loads(raw)
                    # Legacy subscription snapshots are mislabeled crypto_prices,
                    # but btc/usd is the Chainlink symbol (Binance uses btcusdt).
                    if message.get('topic') not in ('crypto_prices_chainlink', 'crypto_prices'):
                        continue
                    payload = message.get('payload', {})
                    if payload.get('symbol') != 'btc/usd':
                        continue
                    for point in payload.get('data', [payload]):
                        if 'value' in point:
                            self.add(point['timestamp'], point['value'], 'snapshot' if 'data' in payload else 'stream')
            except Exception as exc:
                with self.lock:
                    self.error = type(exc).__name__ + ': reference feed unavailable'
                self.stop.wait(5)
            finally:
                if ws:
                    ws.close()


def probability(points, anchor, now, end, window):
    """Zero-drift arithmetic Brownian baseline for future final-window TWAP.
    Deliberately abstain inside averaging window; no unseen observed integral.
    """
    remaining = end - now
    if remaining <= max(10, window):
        raise ValueError('Skip: final averaging window / insufficient decision time')
    recent = [(t, p) for t, p in points if now - 180 <= t <= now]
    if len(recent) < 30 or recent[-1][0] - recent[0][0] < 90:
        raise ValueError('Warming up: need 90 seconds of Chainlink history')
    if not -1 <= now - recent[-1][0] <= 3:
        raise ValueError('Skip: Chainlink price is stale')
    gaps = [b[0] - a[0] for a, b in zip(recent, recent[1:])]
    if max(gaps) > 10:
        raise ValueError('Skip: reference history has gaps')
    qv = sum((b[1] - a[1]) ** 2 for a, b in zip(recent, recent[1:]))
    sigma = math.sqrt(qv / (recent[-1][0] - recent[0][0]))
    if sigma <= 0:
        raise ValueError('Skip: no measurable volatility')
    # Variance of average Brownian path over [T-w,T] is T-2w/3.
    sd = sigma * math.sqrt(remaining - 2 * window / 3)
    z = (recent[-1][1] - anchor) / sd
    p = min(.99, max(.01, .5 * (1 + math.erf(z / math.sqrt(2)))))
    return {'p_up': p, 'sigma_dollars_sqrt_second': sigma,
            'distance_dollars': recent[-1][1] - anchor,
            'remaining_seconds': remaining, 'reference_price': recent[-1][1],
            'reference_timestamp': recent[-1][0], 'model': VERSION,
            'calibrated': False, 'momentum_up': recent[-1][1] >= recent[0][1]}


def fill(book, budget, rate, exponent):
    budget = finite(budget, 1, 100)
    rate = finite(rate, 0, 1)
    if exponent != 1:
        raise ValueError('Unsupported fee schedule')
    shares = cost = fees = 0.
    for level in sorted(book.get('asks', []), key=lambda x: float(x['price'])):
        p, size = finite(level['price'], .001, .999), finite(level['size'], 0)
        per_fee = rate * p * (1 - p)
        n = min(size, max(0, budget - cost - fees) / (p + per_fee))
        shares += n
        cost += n * p
        fees += n * per_fee
        if cost + fees >= budget - 1e-7:
            break
    if shares <= 0 or cost + fees < budget - 1e-6:
        raise ValueError('Insufficient displayed liquidity for full paper order')
    if shares < float(book.get('min_order_size', 0)):
        raise ValueError('Below market minimum order size')
    return {'shares': shares, 'cost': cost, 'fees': fees, 'total': cost + fees,
            'average_price': cost / shares, 'break_even_probability': (cost + fees) / shares,
            'winning_payout': shares, 'winning_profit': shares - cost - fees,
            'fill_assumption': 'Displayed ask depth; no queue priority or future liquidity guarantee'}


class Journal:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = str(path)
        self.lock = threading.RLock()
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, kind TEXT, body TEXT, digest TEXT)')
        self.verify()

    def verify(self):
        prior = ''
        with self.connect() as db:
            for _, kind, body, digest in db.execute('SELECT * FROM events ORDER BY id'):
                expected = hashlib.sha256((prior + kind + body).encode()).hexdigest()
                if expected != digest:
                    raise ValueError('Paper journal hash chain differs; original records must be preserved')
                prior = digest

    def connect(self):
        return sqlite3.connect(self.path)

    def rows(self):
        with self.connect() as db:
            return [{'id': i, 'kind': k, **json.loads(b), 'digest': d} for i, k, b, d in db.execute('SELECT * FROM events ORDER BY id')]

    def append(self, kind, body):
        with self.lock, self.connect() as db:
            prior = db.execute('SELECT digest FROM events ORDER BY id DESC LIMIT 1').fetchone()
            body = {**body, 'recorded_at': time.time()}
            raw = json.dumps(body, sort_keys=True, separators=(',', ':'), allow_nan=False)
            digest = hashlib.sha256(((prior[0] if prior else '') + kind + raw).encode()).hexdigest()
            cursor = db.execute('INSERT INTO events(kind,body,digest) VALUES (?,?,?)', (kind, raw, digest))
            return cursor.lastrowid

    def portfolio(self):
        rows = self.rows()
        trades = [r for r in rows if r['kind'] == 'trade']
        settled = {r['trade_id']: r for r in rows if r['kind'] == 'settlement'}
        cash = 1000 - sum(r['fill']['total'] for r in trades) + sum(r['payout'] for r in settled.values())
        for r in trades:
            r['settlement'] = settled.get(r['id'])
        return {'starting_cash': 1000, 'cash': cash, 'open_positions': sum(r['id'] not in settled for r in trades),
                'realized_profit': sum(s['payout'] - next(t['fill']['total'] for t in trades if t['id'] == i)
                                       for i, s in settled.items()), 'trades': trades}


class Agent:
    def __init__(self, journal):
        self.journal = journal
        self.reference = Reference()
        self.lock = threading.RLock()
        self.market = None
        self.books = {}
        self.anchor = None
        self.anchor_slug = None
        self.error = 'Connecting'
        self.stop = threading.Event()
        self.last_prediction = 0
        self.last_settlement = 0
        self.research = Research(journal)
        self.capture = self.stream = self.shadow = None
        self.operations = None
        self.engine_heartbeat = time.time()

    def lab_context(self):
        with self.lock:
            points, _ = self.reference.snapshot()
            return dict(self.market) if self.market else None, self.anchor, points

    def start_lab(self):
        settings=load_capture_settings(self.journal.path)
        self.capture = Capture(settings['path'],settings['max_bytes'],settings['min_free'])
        self.reference.on_tick = lambda p,t,a,m: self.capture.offer('reference_tick',p,t,received_at=a,received_mono_ns=m)
        self.stream = BookStream(self.capture, PublicSocket)
        self.shadow = Shadow(self.journal,self.capture,self.stream,self.lab_context,probability,fill)
        self.operations = Operations(self.journal,self.health_snapshot)
        self.shadow.entry_guard = lambda: self.operations.health.get("shadow_allowed",False)
        threading.Thread(target=self.operations.run,daemon=True).start()
        threading.Thread(target=self.stream.run,daemon=True).start()
        threading.Thread(target=self.shadow.run,daemon=True).start()

    def health_snapshot(self):
        points,_=self.reference.snapshot()
        now=time.time();fresh=False
        try:
            if self.stream and self.market:self.stream.snapshot(self.market['conditionId'],now);fresh=True
        except ValueError:pass
        return {'capture':self.capture.state() if self.capture else None,
                'reference_age':now-points[-1][0] if points else None,
                'stream_error':self.stream.error if self.stream else 'not_started',
                'stream_fresh':fresh,'shadow_error':self.shadow.error if self.shadow else None,
                'engine_heartbeat':self.engine_heartbeat}

    def lab_state(self):
        return {'operations':self.operations.state() if self.operations else None,
                'capture':self.capture.state() if self.capture else None,
                'shadow':self.shadow.state() if self.shadow else None,
                'stream':{'events':self.stream.events,'error':self.stream.error} if self.stream else None}

    def close_lab(self):
        self.stop.set();self.reference.stop.set()
        if self.stream:self.stream.stop.set()
        if self.shadow:self.shadow.stop.set()
        if self.operations:self.operations.stop.set()
        if self.capture:self.capture.close()

    def refresh(self):
        now = time.time()
        start = int(now) // 300 * 300
        slug = f'btc-updown-5m-{start}'
        if not self.market or self.market['slug'] != slug:
            markets = get_json('https://gamma-api.polymarket.com/markets?slug=' + slug)
            if len(markets) != 1:
                raise ValueError('Current market identity unavailable')
            m = markets[0]
            if m.get('slug') != slug or unpack(m.get('outcomes')) != ['Up', 'Down']:
                raise ValueError('Unexpected market identity / outcomes')
            config = m.get('cryptoMarketConfig', {})
            if config.get('asset') != 'btc' or config.get('duration') != '5m':
                raise ValueError('Unverified BTC five-minute rules')
            source = m.get('resolutionSource', '')
            if not source.startswith('https://data.chain.link/streams/btc-usd'):
                raise ValueError('Unsupported resolution source')
            m['start_epoch'], m['end_epoch'] = start, start + 300
            actual_end = datetime.fromisoformat(m['endDate'].replace('Z', '+00:00')).timestamp()
            if abs(actual_end - m['end_epoch']) > 1:
                raise ValueError('Market deadline does not match slug')
            m['window'] = int(config.get('twapLookbackSeconds', 0)) if config.get('twapEnabled') else 0
            if m['window'] not in (0, 60):
                raise ValueError('Unsupported averaging window')
            with self.lock:
                self.market, self.anchor, self.anchor_slug, self.books = m, None, None, {}
        m = self.market
        if self.anchor is None:
            query = urllib.parse.urlencode({'symbol': 'BTC', 'eventStartTime': iso(start),
                                            'variant': 'fiveminute', 'endDate': iso(start + 300)})
            data = get_json('https://polymarket.com/api/crypto/crypto-price?' + query)
            if data.get('openPrice') is not None:
                with self.lock:
                    self.anchor = finite(data['openPrice'], 1)
                    self.anchor_slug = slug
        tokens = unpack(m['clobTokenIds'])
        if len(tokens) != 2:
            raise ValueError('Missing outcome tokens')
        books = {}
        for side, token in zip(('Up', 'Down'), tokens):
            b = get_json('https://clob.polymarket.com/book?token_id=' + token)
            if b.get('asset_id') != token or b.get('market') != m['conditionId']:
                raise ValueError('Order-book identity mismatch')
            b['received_at'] = time.time()
            books[side] = b
        with self.lock:
            self.books, self.error = books, None
            if self.stream:
                self.stream.configure(m, self.anchor, books)

    def assessment(self, budget=5):
        with self.lock:
            now = time.time()
            m = self.market
            points, feed_error = self.reference.snapshot()
            result = {'now': now, 'mode': 'PAPER ONLY', 'model': VERSION, 'calibrated': False,
                      'action': 'SKIP', 'market': m['question'] if m else None,
                      'slug': m['slug'] if m else None, 'error': self.error, 'feed_error': feed_error,
                      'anchor': self.anchor, 'anchor_source': 'Polymarket frontend openPrice (unofficial API)',
                      'budget': budget, 'quotes': {}, 'reason': 'Waiting for complete live data', 'manual_available': False}
            if not m:
                return result
            result['end_epoch'] = m['end_epoch']
            result['condition_id'] = m['conditionId']
            result['rule_hash'] = hashlib.sha256(m['description'].encode()).hexdigest()
            result['window_seconds'] = m['window']
            result['rules'] = m['description']
            result['remaining_seconds'] = max(0, m['end_epoch'] - now)
            result['reference_price'] = points[-1][1] if points else None
            result['reference_age'] = now - points[-1][0] if points else None
            schedule = m.get('feeSchedule', {})
            try:
                if self.error or not m.get('acceptingOrders') or m.get('closed') or now >= m['end_epoch'] - 10:
                    raise ValueError('Skip: unavailable market / decision deadline')
                if m.get('feesEnabled') and not schedule:
                    raise ValueError('Skip: fee schedule unknown')
                rate = schedule.get('rate', 0) if not m.get('feesEnabled') else schedule['rate']
                for side in ('Up', 'Down'):
                    b = self.books.get(side)
                    if not b or not -1 <= now - float(b['timestamp']) / 1000 <= 3 or now - b['received_at'] > 3:
                        raise ValueError('Skip: order book older than three seconds')
                    result['quotes'][side] = fill(b, budget, rate, schedule.get('exponent', 1))
                    result['quotes'][side]['book_timestamp'] = float(b['timestamp']) / 1000
                    result['quotes'][side]['received_at'] = b['received_at']
                result['manual_available'] = True
                if self.anchor is None or self.anchor_slug != m['slug']:
                    raise ValueError('Skip: missing contract starting price')
                prediction = probability(points, self.anchor, now, m['end_epoch'], m['window'])
                result['prediction'] = prediction
                for side, q in result['quotes'].items():
                    p = prediction['p_up'] if side == 'Up' else 1 - prediction['p_up']
                    q['model_probability'] = p
                    q['expected_profit'] = p * q['shares'] - q['total']
                    q['edge'] = p - q['break_even_probability']
                best = max(result['quotes'], key=lambda s: result['quotes'][s]['edge'])
                edge = result['quotes'][best]['edge']
                result['action'] = 'PAPER ' + best.upper() if edge >= .05 else 'SKIP'
                result['reason'] = (f"BTC is ${prediction['distance_dollars']:+.2f} from the starting price; "
                    f"{prediction['remaining_seconds']:.0f}s remain. Zero-drift volatility model estimates "
                    f"Up at {prediction['p_up']:.1%}. Best estimated net edge: {edge:.1%}. "
                    'Experimental probability; not validated trading advice.')
            except (ValueError, KeyError, TypeError) as exc:
                result['reason'] = str(exc)
                if not result.get('prediction'):
                    result['manual_available'] = False
            return self.research.enrich(result, self.books)

    def trade(self, side, budget, slug, request_id):
        if side not in ('Up', 'Down') or not isinstance(request_id, str) or not 8 <= len(request_id) <= 100:
            raise ValueError('Invalid paper order')
        with self.lock, self.journal.lock:
            for row in self.journal.rows():
                if row['kind'] == 'trade' and row.get('request_id') == request_id:
                    return row['id']
            a = self.assessment(budget)
            if slug != a['slug'] or not a['manual_available']:
                raise ValueError('Market changed or quote expired; refresh before paper buying')
            if budget > 10:
                raise ValueError('Paper policy: maximum $10 per trade')
            portfolio = self.journal.portfolio()
            exposure = sum(t['fill']['total'] for t in portfolio['trades'] if not t['settlement'])
            if exposure + budget > 50 + 1e-7:
                raise ValueError('Paper policy: maximum $50 unresolved exposure')
            today = time.strftime('%Y-%m-%d', time.gmtime())
            losses = sum(max(0, t['fill']['total']-t['settlement']['payout'])
                         for t in portfolio['trades'] if t['settlement']
                         and time.strftime('%Y-%m-%d', time.gmtime(t['settlement']['recorded_at'])) == today)
            if losses >= 20:
                raise ValueError('Paper policy: $20 daily realized loss limit reached')
            f = a['quotes'][side]
            if f['total'] > self.journal.portfolio()['cash'] + 1e-7:
                raise ValueError('Insufficient virtual cash')
            return self.journal.append('trade', {'request_id': request_id, 'slug': slug, 'side': side,
                'condition_id': self.market['conditionId'], 'end_epoch': self.market['end_epoch'],
                'fill': f, 'assessment': a, 'rule_hash': hashlib.sha256(self.market['description'].encode()).hexdigest(),
                'outcome_definition': 'Hold until explicit official winning token; $1 per winning share, $0 losing',
                'position_locked': True, 'policy': 'btc5m-locked-manual-v2',
                'execution': 'simulated', 'latency_assumption': 'Fresh displayed depth at click; no latency simulation'})

    def settle(self):
        portfolio = self.journal.portfolio()
        cache = {}
        for trade in portfolio['trades']:
            if trade['settlement'] or time.time() <= trade['end_epoch']:
                continue
            condition = trade['condition_id']
            if condition not in cache:
                cache[condition] = get_json('https://clob.polymarket.com/markets/' + condition)
            m = cache[condition]
            winners = [t for t in m.get('tokens', []) if t.get('winner') is True]
            if m.get('condition_id') != condition or not m.get('closed') or len(winners) != 1:
                continue
            winner = winners[0]['outcome']
            if winner not in ('Up', 'Down'):
                continue
            self.journal.append('settlement', {'trade_id': trade['id'], 'winner': winner,
                'payout': trade['fill']['shares'] if trade['side'] == winner else 0,
                'source': 'CLOB explicit winning token', 'condition_id': condition})

    def run(self):
        self.start_lab()
        threading.Thread(target=self.reference.run, daemon=True).start()
        while not self.stop.is_set():
            self.engine_heartbeat=time.time()
            try:
                self.refresh()
                if time.time() - self.last_prediction >= 30:
                    self.journal.append('assessment', self.assessment())
                    self.last_prediction = time.time()
                if time.time() - self.last_settlement >= 30:
                    self.settle()
                    self.last_settlement = time.time()
                if time.time() - self.research.last_resolve >= 30:
                    self.research.last_resolve = time.time()
                    self.research.resolve(get_json)
                if time.time() - self.research.last_watch >= 30:
                    self.research.last_watch = time.time()
                    self.research.poll_wallet(get_json)
            except Exception as exc:
                with self.lock:
                    self.error = type(exc).__name__ + ': data request failed'
            self.stop.wait(2)


def serve(agent, port):
    token = secrets.token_urlsafe(32)
    html = Path(__file__).with_name('dashboard.html').read_text().replace('__TOKEN__', token)

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def respond(self, data, status=200, content_type='application/json'):
            raw = data.encode() if isinstance(data, str) else json.dumps(data, allow_nan=False).encode()
            self.send_response(status)
            self.send_header('Content-Type', content_type + '; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()
            self.wfile.write(raw)

        def trusted(self):
            host = self.headers.get('Host', '')
            return host in (f'127.0.0.1:{port}', f'localhost:{port}')

        def do_GET(self):
            if not self.trusted():
                return self.respond({'error': 'Localhost only'}, 403)
            if self.path == '/':
                return self.respond(html, content_type='text/html')
            if self.path == '/api/state':
                return self.respond({'assessment': agent.assessment(), 'portfolio': agent.journal.portfolio(), **agent.research.state(), **agent.lab_state()})
            if self.path == '/api/report':
                from operations import daily_report, TZ
                from datetime import datetime
                return self.respond(daily_report(agent.journal.rows(),datetime.now(TZ).date()))
            if self.path == '/api/export':
                return self.respond(agent.journal.rows())
            self.respond({'error': 'Not found'}, 404)

        def do_POST(self):
            origin = self.headers.get('Origin')
            if not self.trusted() or origin not in (f'http://localhost:{port}', f'http://127.0.0.1:{port}') or self.headers.get('X-Paper-Token') != token:
                return self.respond({'error': 'Invalid local session'}, 403)
            try:
                if self.path not in ('/api/trade', '/api/watch'):
                    raise ValueError('Unknown action')
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 4096:
                    raise ValueError('Invalid body size')
                data = json.loads(self.rfile.read(length))
                if self.path == '/api/watch':
                    return self.respond(agent.research.watch(data['wallet']))
                i = agent.trade(data['side'], finite(data['budget'], 1, 100), data['slug'], data['request_id'])
                self.respond({'paper_trade_id': i})
            except (ValueError, KeyError, TypeError) as exc:
                self.respond({'error': str(exc)}, 400)

    server = http.server.ThreadingHTTPServer(('127.0.0.1', port), Handler)
    def stop_server(*args):
        agent.stop.set();agent.reference.stop.set()
        threading.Thread(target=server.shutdown,daemon=True).start()
    if threading.current_thread() is threading.main_thread():
        signal.signal(signal.SIGTERM,stop_server)
    print(f'Paper copilot: http://127.0.0.1:{port}', flush=True)
    try:
        server.serve_forever()
    finally:
        agent.close_lab()
        server.server_close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--database', default=str(Path.home() / '.vivameda-btc5m' / 'paper.sqlite3'))
    parser.add_argument('--probe-seconds', type=int, default=0)
    args = parser.parse_args()
    Path(args.database).parent.mkdir(parents=True, exist_ok=True)
    # Prevent two collectors / settlement workers using the same portfolio.
    instance_lock = open(args.database + '.lock', 'a')
    try:
        fcntl.flock(instance_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit('This paper portfolio is already running')
    agent = Agent(Journal(args.database))
    threading.Thread(target=agent.run, daemon=True).start()
    if args.probe_seconds:
        agent.stop.wait(min(180, max(1, args.probe_seconds)))
        print(json.dumps(agent.assessment(), indent=2))
        agent.close_lab()
    else:
        serve(agent, args.port)


if __name__ == '__main__':
    main()
