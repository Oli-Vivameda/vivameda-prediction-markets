"""Public-only, bounded broad-market collection and conservative paper agent."""
from __future__ import annotations
import argparse
import concurrent.futures
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import sqlite3
import time
import urllib.parse
import urllib.request

D = Decimal
ROOT = Path(__file__).resolve().parent
PLAN_HASH = hashlib.sha256((ROOT / 'PROTOCOL.md').read_bytes()).hexdigest()
GAMMA = 'https://gamma-api.polymarket.com'
CLOB = 'https://clob.polymarket.com'
CAP = 512 * 1024**2
FLOOR = 2 * 1024**3

def canonical(x):
    return json.dumps(x, sort_keys=True, separators=(',', ':'), allow_nan=False)

def digest(x):
    return hashlib.sha256(canonical(x).encode()).hexdigest()

def atomic(path, obj):
    path = Path(path)
    tmp = path.with_suffix(path.suffix + '.tmp')
    with open(tmp, 'w') as f:
        f.write(canonical(obj)); f.flush(); os.fsync(f.fileno())
    os.replace(tmp, path)

def number(x):
    v = D(str(x))
    if not v.is_finite():
        raise ValueError('Nonfinite amount')
    return v

def epoch(s):
    d = datetime.fromisoformat(s.replace('Z', '+00:00'))
    if d.tzinfo is None:
        raise ValueError('Deadline has no timezone')
    return d.timestamp()

def array(x):
    return json.loads(x) if isinstance(x, str) else x

def deadline_precision(gamma_end, venue_end):
    v=epoch(venue_end)
    if abs(v-gamma_end)<=1:return 'exact'
    # Legacy CLOB metadata often exposes only the UTC calendar date, while
    # Gamma supplies the timed deadline. Retain both; never replace exact time.
    vd=datetime.fromtimestamp(v,timezone.utc)
    gd=datetime.fromtimestamp(gamma_end,timezone.utc)
    if vd.hour==vd.minute==vd.second==0 and vd.date()==gd.date():return 'calendar_date'
    raise ValueError('Venue deadline differs')

def get(url):
    if not url.startswith((GAMMA + '/', CLOB + '/')):
        raise ValueError('Public endpoint outside allowlist')
    req = urllib.request.Request(url, headers={'User-Agent': 'VivamedaResearch/1.0'})
    started = time.time()
    with urllib.request.urlopen(req, timeout=10) as r:
        raw = r.read(2_000_001)
    if len(raw) > 2_000_000:
        raise ValueError('Response size cap')
    return json.loads(raw), started, time.time()

def metadata(m, received):
    if m.get('active') is not True or m.get('closed') is not False or m.get('acceptingOrders') is not True:
        raise ValueError('Market not accepting orders')
    if m.get('version') != 'v1' or m.get('negRisk') is not False:
        raise ValueError('Unsupported protocol or negative-risk market')
    ids = array(m.get('clobTokenIds'))
    labels = array(m.get('outcomes'))
    if not isinstance(ids, list) or len(ids) != 2 or len(set(ids)) != 2:
        raise ValueError('Invalid complementary asset identities')
    if not isinstance(labels, list) or len(labels) != 2 or len(set(labels)) != 2:
        raise ValueError('Invalid outcomes')
    condition = m.get('conditionId', '')
    if not isinstance(condition, str) or not condition.startswith('0x') or len(condition) != 66:
        raise ValueError('Invalid condition identity')
    description = m.get('description')
    if not description:
        raise ValueError('Missing settlement rules')
    if m.get('feesEnabled') is False:
        rate = D(0)
    elif m.get('feesEnabled') is True:
        f = m.get('feeSchedule') or {}
        if f.get('takerOnly') is not True or number(f.get('exponent', -1)) != 1:
            raise ValueError('Unknown fee formula')
        rate = number(f.get('rate'))
        if not 0 <= rate <= D('.1'):
            raise ValueError('Invalid fee rate')
    else:
        raise ValueError('Unknown costs')
    minimum = number(m.get('orderMinSize'))
    tick = number(m.get('orderPriceMinTickSize'))
    if minimum <= 0 or not 0 < tick < 1:
        raise ValueError('Invalid trading limits')
    return {'condition': condition, 'slug': m['slug'], 'question': m['question'],
            'rule_hash': hashlib.sha256(description.encode()).hexdigest(),
            'description': description, 'assets': ids, 'labels': labels,
            'end': epoch(m['endDate']), 'fee_rate': str(rate), 'minimum': str(minimum),
            'tick': str(tick), 'received': received, 'protocol': 'v1'}

def book(raw, asset, condition, request_start, received):
    if str(raw.get('asset_id')) != asset or raw.get('market') != condition:
        raise ValueError('Book identity mismatch')
    stamp = float(raw['timestamp']) / 1000
    if not request_start - 5 <= stamp <= received + 1 or received - request_start > 5:
        raise ValueError('Stale or slow book')
    out = {'asset': asset, 'condition': condition, 'timestamp': stamp,
           'received': received, 'hash': raw.get('hash')}
    for key in ('bids', 'asks'):
        levels = []
        for x in raw.get(key, []):
            p, q = number(x['price']), number(x['size'])
            if not 0 < p < 1 or q <= 0:
                raise ValueError('Invalid book level')
            levels.append((p, q))
        levels.sort(reverse=key == 'bids')
        out[key] = [[str(p), str(q)] for p, q in levels]
    if not out['bids'] or not out['asks'] or number(out['bids'][0][0]) >= number(out['asks'][0][0]):
        raise ValueError('Empty or crossed book')
    return out

def sweep(asks, quantity, rate):
    left, cost, fee = number(quantity), D(0), D(0)
    for p, q in asks:
        p, q = number(p), number(q)
        take = min(q, left)
        cost += take * p
        fee += take * number(rate) * p * (1 - p)
        left -= take
        if left == 0:
            break
    if left:
        raise ValueError('Insufficient executable depth')
    return cost, fee

def validate_snapshot(s, now):
    m, bs = s['market'], s['books']
    if not 0 <= now - m['received'] <= 60 or m['end'] - now <= 60:
        raise ValueError('Stale metadata or too close to deadline')
    if len(bs) != 2 or [b['asset'] for b in bs] != m['assets']:
        raise ValueError('Complementary identities differ')
    for b in bs:
        if b['condition'] != m['condition'] or not -1 <= now - b['timestamp'] <= 5 or not 0 <= now-b['received'] <= 5:
            raise ValueError('Stale or mismatched pair')
    if abs(bs[0]['received']-bs[1]['received']) > 2:
        raise ValueError('Sequential pair too far apart')

def paired(s, now, budget='5'):
    validate_snapshot(s, now)
    m, bs = s['market'], s['books']
    rate = number(m['fee_rate'])
    top = sum(number(b['asks'][0][0]) for b in bs)
    top += sum(rate * number(b['asks'][0][0]) * (1-number(b['asks'][0][0])) for b in bs)
    q = (number(budget) / top).quantize(D('.000001'), rounding=ROUND_DOWN)
    q = min(q, *(sum(number(x[1]) for x in b['asks']) for b in bs))
    if q < number(m['minimum']):
        raise ValueError('Budget cannot satisfy minimum shares')
    # Deeper levels may be dearer than best ask; reduce size until all-in fits.
    for _ in range(6):
        fills = [sweep(b['asks'], q, rate) for b in bs]
        total = sum(c+f for c, f in fills)
        if total <= number(budget):
            break
        q = (q * number(budget) / total).quantize(D('.000001'), rounding=ROUND_DOWN)
    else:
        raise ValueError('Budget/depth did not converge')
    if q < number(m['minimum']):
        raise ValueError('Depth-adjusted size below minimum')
    net = q - total
    buffer = q * D('.01')
    return {'strategy': 'paired_taker', 'condition': m['condition'], 'rule_hash': m['rule_hash'],
            'assets': m['assets'], 'shares_each': str(q), 'cost': str(total),
            'fees': str(sum(f for c, f in fills)), 'gross_payout': str(q),
            'net_profit_if_both_filled': str(net), 'buffer': str(buffer),
            'qualifies': net > buffer, 'atomic_execution': False,
            'per_share_net_edge': float(net/q), 'snapshot_hash': digest(s)}

def features(s, side):
    b, m = s['books'][side], s['market']
    bid, ask = number(b['bids'][0][0]), number(b['asks'][0][0])
    bv = sum(number(q) for p, q in b['bids'][:5])
    av = sum(number(q) for p, q in b['asks'][:5])
    pair_cost = sum(number(x['asks'][0][0]) for x in s['books'])
    return [float(ask-bid), float((bv-av)/(bv+av)), math.log1p(float(bv+av)),
            float((ask+bid)/2), math.log1p(max(0, m['end']-s['observed'])),
            float(m['fee_rate']), float(1-pair_cost)]

def maker_candidate(s):
    m = s['market']; quotes = []
    for b in s['books']:
        bid, ask = number(b['bids'][0][0]), number(b['asks'][0][0])
        quotes.append({'asset': b['asset'], 'bid': str(bid), 'ask': str(ask),
                       'spread': str(ask-bid)})
    return {'strategy': 'maker_watch', 'quotes': quotes, 'condition': m['condition'],
            'assumed_fills': 0, 'assumed_rewards': 0, 'trade_enabled': False,
            'note': 'Watch candidate only; passive fills and adverse selection not validated.'}

def payoff_check(spec, snapshots, now):
    """Only explicit exhaustive reviewed states; no semantic inference."""
    if spec.get('reviewed') is not True or spec.get('exhaustive') is not True or not spec.get('review_reference'):
        raise ValueError('Unreviewed logical relationship')
    legs, states = spec['legs'], spec['states']
    if not legs or not states:
        raise ValueError('Missing payoff matrix')
    cost = D(0)
    for leg in legs:
        s = snapshots[leg['condition']]; validate_snapshot(s, now)
        if s['market']['rule_hash'] != leg['rule_hash']:
            raise ValueError('Reviewed rules changed')
        idx = s['market']['assets'].index(leg['asset'])
        q = number(leg['shares'])
        if q < number(s['market']['minimum']):
            raise ValueError('Leg below venue minimum')
        c, f = sweep(s['books'][idx]['asks'], q, s['market']['fee_rate'])
        cost += c+f
    values=[]
    for state in states:
        if len(state['payout_per_share']) != len(legs):
            raise ValueError('Incomplete state payoff')
        pays=[number(x) for x in state['payout_per_share']]
        if any(not 0 <= x <= 1 for x in pays):
            raise ValueError('Invalid payoff')
        values.append(sum(number(l['shares'])*p for l,p in zip(legs,pays)))
    return {'strategy':'reviewed_cross_market','cost':str(cost),
            'worst_payout':str(min(values)), 'worst_net':str(min(values)-cost),
            'trade_enabled':False,'review_reference':spec['review_reference']}

class Store:
    def __init__(self, root):
        self.root=Path(root)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.root,0o700)
        self.db=sqlite3.connect(self.root/'lab.sqlite3', timeout=10)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, ts REAL, kind TEXT, payload TEXT, prior TEXT, hash TEXT);
        CREATE TABLE IF NOT EXISTS observations(condition TEXT, minute INTEGER, ts REAL, payload TEXT, PRIMARY KEY(condition,minute));
        CREATE TABLE IF NOT EXISTS labels(condition TEXT, minute INTEGER, target_ts REAL, adverse TEXT, PRIMARY KEY(condition,minute));
        CREATE TABLE IF NOT EXISTS positions(condition TEXT PRIMARY KEY, rule_hash TEXT, cost TEXT, shares TEXT, assets TEXT, state TEXT, payout TEXT, opened REAL, resolved REAL);
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT);
        ''')
        row=self.db.execute("SELECT value FROM settings WHERE key='plan_hash'").fetchone()
        if row and row[0]!=PLAN_HASH:
            raise ValueError('Existing study protocol differs; new version required')
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO settings VALUES('plan_hash',?)",(PLAN_HASH,))
            self.db.execute("INSERT OR IGNORE INTO settings VALUES('started',?)",(str(time.time()),))

    def guard(self):
        size=sum(p.stat().st_size for p in self.root.glob('*') if p.is_file())
        if size>=CAP or shutil.disk_usage(self.root).free<FLOOR:
            raise ValueError('Storage guard; preserve recordings, no deletion')

    def event(self,kind,payload,ts=None):
        self.guard(); ts=time.time() if ts is None else ts
        previous=self.db.execute('SELECT hash FROM events ORDER BY id DESC LIMIT 1').fetchone()
        prior=previous[0] if previous else '0'*64
        body=canonical(payload); h=digest([ts,kind,body,prior])
        with self.db:
            self.db.execute('INSERT INTO events(ts,kind,payload,prior,hash) VALUES(?,?,?,?,?)',(ts,kind,body,prior,h))
        return h

    def observe(self,s):
        self.guard(); m=s['market']; minute=int(s['observed']//60)
        # Label only earlier, identity-stable observations with valid elapsed time.
        rows=self.db.execute('SELECT minute,ts,payload FROM observations WHERE condition=? AND ts BETWEEN ? AND ? AND minute NOT IN (SELECT minute FROM labels WHERE condition=?)',
            (m['condition'],s['observed']-90,s['observed']-60,m['condition'])).fetchall()
        with self.db:
            for oldminute,stamp,payload in rows:
                old=json.loads(payload)
                if old['market']['rule_hash']!=m['rule_hash'] or old['market']['assets']!=m['assets']:
                    continue
                targets=[]
                for i in (0,1):
                    prev=features(old,i); current=features(s,i)
                    targets.append(int(current[3]<prev[3]-prev[0]/2))
                self.db.execute('INSERT OR IGNORE INTO labels VALUES(?,?,?,?)',
                    (m['condition'],oldminute,s['observed'],canonical(targets)))
            self.db.execute('INSERT OR IGNORE INTO observations VALUES(?,?,?,?)',
                (m['condition'],minute,s['observed'],canonical(s)))

    def capital(self):
        rows=self.db.execute('SELECT cost,shares,state,payout FROM positions').fetchall()
        spent=sum(number(r[0]) for r in rows)
        payouts=sum(number(r[3]) for r in rows if r[2]=='resolved')
        opened=sum(number(r[0]) for r in rows if r[2]=='open')
        realized=sum(number(r[3])-number(r[0]) for r in rows if r[2]=='resolved')
        return {'cash':str(D(100)-spent+payouts),'open_cost':str(opened),
                'realized_net_profit':str(realized),'positions':len(rows),
                'open_positions':sum(r[2]=='open' for r in rows)}

    def enter(self,p,now):
        self.guard()
        if not p['qualifies'] or number(p['cost'])>5 or number(p['cost'])<=0:
            raise ValueError('Paper plan not qualified')
        self.db.execute('BEGIN IMMEDIATE')
        try:
            c=self.capital()
            if number(c['cash'])<number(p['cost']) or number(c['open_cost'])+number(p['cost'])>20:
                raise ValueError('Paper capital limit')
            self.db.execute('INSERT INTO positions VALUES(?,?,?,?,?,?,?, ?,?)',
                (p['condition'],p['rule_hash'],p['cost'],p['shares_each'],canonical(p['assets']),
                 'open',None,now,None))
            self.db.commit()
        except Exception:
            self.db.rollback(); raise
        self.event('paper_pair_entry',p)

    def reconcile(self, condition, outcome, now):
        row=self.db.execute('SELECT assets,shares,state FROM positions WHERE condition=?',(condition,)).fetchone()
        if not row or row[2]!='open':
            return False
        if outcome.get('condition_id')!=condition or outcome.get('closed') is not True:
            return False
        tokens=outcome.get('tokens') or []
        assets=json.loads(row[0]); winners=[t for t in tokens if t.get('winner') is True]
        if len(tokens)!=2 or sorted(str(t['token_id']) for t in tokens)!=sorted(assets) or len(winners)!=1:
            return False
        with self.db:
            self.db.execute("UPDATE positions SET state='resolved',payout=?,resolved=? WHERE condition=? AND state='open'",(row[1],now,condition))
        self.event('paper_settlement',{'condition':condition,'virtual_payout':row[1],
                                     'real_redemption':False})
        return True

class PublicVenue:
    def catalogue(self, offset, limit=100, volume=False):
        params={'active':'true','closed':'false','limit':limit,'offset':offset}
        if volume: params.update(order='volume24hr',ascending='false')
        data,start,end=get(GAMMA+'/markets?'+urllib.parse.urlencode(params))
        if not isinstance(data,list): raise ValueError('Unexpected catalogue')
        for m in data:m['_fetched_at']=end
        return data

    def capture(self,m):
        meta=metadata(m,m['_fetched_at']); bs=[]
        detail,start,end=get(CLOB+'/markets/'+meta['condition'])
        if detail.get('condition_id')!=meta['condition'] or detail.get('closed') is not False or detail.get('accepting_orders') is not True:
            raise ValueError('Trading state or identity not confirmed')
        if detail.get('version')!='v1' or detail.get('seconds_delay')!=0 or detail.get('neg_risk') is not False:
            raise ValueError('Unsupported venue protocol or matching delay')
        tokens=detail.get('tokens') or []
        actual={str(t['token_id']):t['outcome'] for t in tokens}
        if actual!=dict(zip(meta['assets'],meta['labels'])):
            raise ValueError('Venue outcome mapping differs')
        if number(detail['minimum_order_size'])!=number(meta['minimum']) or number(detail['minimum_tick_size'])!=number(meta['tick']):
            raise ValueError('Venue trading limits differ')
        if hashlib.sha256((detail.get('description') or '').encode()).hexdigest()!=meta['rule_hash']:
            raise ValueError('Venue settlement rules differ')
        meta['venue_deadline_precision']=deadline_precision(meta['end'],detail['end_date_iso'])
        meta['venue_end_date']=detail['end_date_iso']
        meta['deadline_source']='gamma_exact_with_identical_venue_rules'
        # Independent GET books in parallel, but explicitly not atomic.
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            jobs=[pool.submit(get,CLOB+'/book?'+urllib.parse.urlencode({'token_id':a})) for a in meta['assets']]
            for a,job in zip(meta['assets'],jobs):
                raw,start,end=job.result(); bs.append(book(raw,a,meta['condition'],start,end))
        s={'market':meta,'books':bs,'observed':time.time()}
        validate_snapshot(s,s['observed']); return s

    def fresh(self,slug):
        data,start,end=get(GAMMA+'/markets?'+urllib.parse.urlencode({'slug':slug}))
        if len(data)!=1 or data[0].get('slug')!=slug: raise ValueError('Market identity unavailable')
        data[0]['_fetched_at']=end
        return self.capture(data[0])

    def outcome(self,condition):
        return get(CLOB+'/markets/'+condition)[0]

class Agent:
    def __init__(self,store,venue=None,market_limit=20):
        self.store=store; self.venue=venue or PublicVenue(); self.limit=market_limit
        self.pending={}; self.last_catalogue=0; self.catalogue=[]; self.offset=0
        self.latest={}

    def discover(self):
        ordinary=self.venue.catalogue(self.offset)
        hot=self.venue.catalogue(0,volume=True)
        self.offset=self.offset+100 if len(ordinary)==100 else 0
        seen={}; skipped={}
        for m in hot+ordinary:
            try:
                meta=metadata(m,time.time())
                if meta['end']-time.time()<=60: raise ValueError('Past or near deadline')
                seen.setdefault(meta['condition'],m)
            except (ValueError,TypeError,KeyError) as e:
                reason=str(e); skipped[reason]=skipped.get(reason,0)+1
        # Alternate popular and rotating pages instead of starving rotating results.
        a=list(seen.values()); self.catalogue=a[:self.limit//2]
        for m in ordinary:
            if m.get('conditionId') in seen and m not in self.catalogue:
                self.catalogue.append(m)
                if len(self.catalogue)>=self.limit: break
        for m in a:
            if m not in self.catalogue and len(self.catalogue)<self.limit: self.catalogue.append(m)
        self.last_catalogue=time.time()
        return {'raw_rows':len(hot)+len(ordinary),'distinct_supported':len(seen),
                'tracked':len(self.catalogue),'rotating_offset':self.offset,'excluded':skipped,
                'exhaustive_universe':False}

    def cycle(self):
        self.store.guard(); now=time.time(); report={'mode':'paper','live_execution':False,
            'plan_hash':PLAN_HASH,'started':now,'captured':0,'errors':{},'pairs':0,'maker_watch':0}
        if now-self.last_catalogue>=50:
            try: report['discovery']=self.discover()
            except Exception as e:
                report['discovery_error']=type(e).__name__; self.catalogue=[]
        # Recheck delayed candidates first, with new contract metadata and books.
        for condition,pending in list(self.pending.items()):
            if now<pending['due']: continue
            del self.pending[condition]
            try:
                if now-pending['due']>10: raise ValueError('Delayed probe missed')
                fresh=self.venue.fresh(pending['slug']); p=paired(fresh,time.time())
                if p['rule_hash']!=pending['plan']['rule_hash'] or p['assets']!=pending['plan']['assets']:
                    raise ValueError('Contract changed after decision')
                if p['per_share_net_edge']<pending['plan']['per_share_net_edge']-.005:
                    raise ValueError('Adverse delayed price')
                self.store.event('paper_delayed_probe',{'decision_hash':pending['hash'],'plan':p})
                self.store.enter(p,time.time()); report['pairs']+=1
            except Exception as e:
                self.store.event('paper_pair_skip',{'condition':condition,'reason':type(e).__name__+': '+str(e)[:160]})
        for condition, in self.store.db.execute("SELECT condition FROM positions WHERE state='open'").fetchall():
            try:self.store.reconcile(condition,self.venue.outcome(condition),time.time())
            except Exception:report['errors']['resolution_unavailable']=report['errors'].get('resolution_unavailable',0)+1
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            jobs=[pool.submit(self.venue.capture,m) for m in self.catalogue]
            for job in concurrent.futures.as_completed(jobs):
                try:
                    s=job.result(); self.store.observe(s); report['captured']+=1
                    condition=s['market']['condition']; self.latest[condition]=s
                    watch=maker_candidate(s); report['maker_watch']+=1
                    self.store.event('maker_watch',watch)
                    try:p=paired(s,time.time())
                    except ValueError:continue
                    self.store.event('pair_quote',p)
                    exists=self.store.db.execute('SELECT 1 FROM positions WHERE condition=?',(condition,)).fetchone()
                    if p['qualifies'] and condition not in self.pending and not exists:
                        h=self.store.event('paper_pair_decision',{'plan':p,'decision_time':time.time()})
                        self.pending[condition]={'due':time.time()+2,'slug':s['market']['slug'],'plan':p,'hash':h}
                except Exception as e:
                    k=type(e).__name__+': '+str(e)[:120]
                    report['errors'][k]=report['errors'].get(k,0)+1
        relationships=self.store.root/'reviewed-relationships.json'
        if relationships.exists():
            for spec in json.loads(relationships.read_text()):
                try:self.store.event('reviewed_cross_market',payoff_check(spec,self.latest,time.time()))
                except Exception as e:self.store.event('cross_market_skip',{'reason':type(e).__name__})
        report.update(finished=time.time(),capital=self.store.capital(),pending=len(self.pending))
        report['health']='healthy' if report['captured'] else 'no_complete_books'
        self.store.event('cycle',report); atomic(self.store.root/'status.json',report)
        return report

def main():
    p=argparse.ArgumentParser(); p.add_argument('command',choices=['scan','run','status','verify'])
    p.add_argument('--state-dir',required=True); p.add_argument('--markets',type=int,default=20)
    p.add_argument('--interval',type=float,default=15); p.add_argument('--cycles',type=int,default=0)
    a=p.parse_args()
    if not 2<=a.markets<=50 or a.interval<5: raise ValueError('Bounds invalid')
    root=Path(a.state_dir)
    if not root.is_absolute() or root.is_symlink(): raise ValueError('Absolute private directory required')
    store=Store(root)
    if a.command=='status':
        print(canonical({'capital':store.capital(),'live_execution':False,
            'status':json.loads((root/'status.json').read_text()) if (root/'status.json').exists() else None})); return
    if a.command=='verify':
        prior='0'*64; count=0
        for ts,kind,payload,prev,h in store.db.execute('SELECT ts,kind,payload,prior,hash FROM events ORDER BY id'):
            if prev!=prior or digest([ts,kind,payload,prev])!=h: raise ValueError('Journal integrity failed')
            prior=h; count+=1
        print(canonical({'journal_verified':True,'events':count,'tip':prior})); return
    lock=open(root/'agent.lock','a'); fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    agent=Agent(store,market_limit=a.markets); i=0
    while not (root/'STOP').exists():
        try: print(canonical(agent.cycle()),flush=True)
        except Exception as e:
            atomic(root/'status.json',{'health':'halted','reason':type(e).__name__+': '+str(e)[:160],'live_execution':False})
            raise
        i+=1
        if a.command=='scan' or a.cycles and i>=a.cycles: break
        time.sleep(2 if agent.pending else a.interval)

if __name__=='__main__': main()
