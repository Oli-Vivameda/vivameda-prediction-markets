"""Public, legacy Chainlink raw/TWAP snapshots. No credentials or financial API.

RTDS currently acknowledges subscriptions with a rolling one-minute history but
may not push updates. Re-request that documented public snapshot every second.
Do not fabricate missing seconds, opening prices, or substitute another vendor.
"""
import copy
import json
import select
import threading
import time
from common import D,number
from transport import PublicSocket

ASSETS=('btc','eth','sol')

class Reference:
    def __init__(self):
        self.lock=threading.RLock();self.stop=threading.Event();self.points={a:{} for a in ASSETS};self.twaps={a:{} for a in ASSETS}
        self.error='connecting';self.generation=0;self.responses=0;self.last_received=None;self.disconnects=0
        self.stale_snapshots_rejected=0;self.last_recorded_received=0
        self.thread=threading.Thread(target=self.run,daemon=True)

    def handle(self,event,received):
        topic=event.get('topic');payload=event.get('payload',{});kind=event.get('type')
        if topic not in ('crypto_prices','crypto_prices_chainlink','crypto_prices_twap_sixty'):return
        if not isinstance(payload,dict):raise ValueError('reference_payload')
        symbol=payload.get('symbol');asset=next((a for a in ASSETS if symbol==a+'/usd'),None)
        if asset is None:raise ValueError('reference_symbol')
        if payload.get('source','chainlink').lower()!='chainlink':raise ValueError('wrong_reference_vendor')
        twap=topic=='crypto_prices_twap_sixty'
        if twap and payload.get('window_s')!=60:raise ValueError('reference_twap_window')
        if kind not in ('subscribe','update'):raise ValueError('unknown_reference_message')
        rows=payload.get('data') if kind=='subscribe' else [payload]
        if not isinstance(rows,list) or not 1<=len(rows)<=240:raise ValueError('reference_snapshot_size')
        envelope=float(number(event['timestamp']))/1000
        if not -1<=received-envelope<=3:raise ValueError('stale_reference_envelope')
        parsed=[]
        for row in rows:
            source=float(number(row['timestamp']))/1000
            if source>envelope+1 or source>received or received-source>180:raise ValueError('reference_timestamp')
            # Legacy full_accuracy_value is E18; never apply this to PolyBolt.
            price=number(row['full_accuracy_value'])/D(10)**18 if twap and 'full_accuracy_value' in row else number(row['value'])
            if price<=0:raise ValueError('reference_price')
            parsed.append({'price':str(price),'source_at':source,'received_at':received,'vendor':'chainlink','transport':'public_rtds_snapshot','generation':self.generation})
        if any(a['source_at']>=b['source_at'] for a,b in zip(parsed,parsed[1:])):raise ValueError('reference_time_order')
        if not 0<=received-parsed[-1]['source_at']<=3:raise ValueError('stale_reference_point')
        with self.lock:
            target=(self.twaps if twap else self.points)[asset]
            for point in parsed:
                old=target.get(point['source_at'])
                if old and number(old['price'])!=number(point['price']):raise ValueError('reference_revision_requires_review')
            for point in parsed:target.setdefault(point['source_at'],point)
            for t in list(target):
                if t<received-900:del target[t]
            self.responses+=1;self.last_received=received;self.error=None

    def accept(self,event,received):
        try:self.handle(event,received)
        except ValueError as exc:
            if str(exc) not in ('stale_reference_envelope','stale_reference_point'):raise
            # Reject late snapshots without erasing other assets' valid history.
            # Each decision still rechecks its own raw point ages and gaps.
            with self.lock:self.stale_snapshots_rejected+=1

    def inputs(self,m,now):
        with self.lock:
            if self.error:raise ValueError('reference_unavailable:'+self.error)
            asset=m['asset'];points=copy.deepcopy([p for t,p in sorted(self.points[asset].items()) if now-180<=t<=now])
            anchor=copy.deepcopy(self.twaps[asset].get(m['start']))
            if anchor is None:raise ValueError('exact_opening_twap_unavailable')
            if not points or not 0<=now-points[-1]['source_at']<=3:raise ValueError('reference_stale')
            return ({'kind':'verified_chainlink_raw','twap_source':m['source'],'points':points,'transport':'public_rtds_snapshot','venue_sequence_available':False},
                    {**anchor,'source':m['source'],'kind':'chainlink_twap_60'})

    def run(self):
        subscriptions=[{'topic':topic,'type':'*','filters':json.dumps({'symbol':asset+'/usd'})}
            for asset in ASSETS for topic in ('crypto_prices_chainlink','crypto_prices_twap_sixty')]
        request=json.dumps({'action':'subscribe','subscriptions':subscriptions})
        while not self.stop.is_set():
            ws=None
            try:
                with self.lock:self.generation+=1;self.error='connecting';self.points={a:{} for a in ASSETS}
                ws=PublicSocket();last_request=0;last_ping=0
                while not self.stop.is_set():
                    now=time.monotonic()
                    if now-last_request>=1:ws.send(request);last_request=now
                    if now-last_ping>=3:ws.send('PING');last_ping=now
                    if not ws.s.pending() and not select.select([ws.s],[],[],.15)[0]:continue
                    raw=ws.receive()
                    if not raw or raw in ('PING','PONG'):continue
                    event=json.loads(raw,parse_float=str)
                    if not isinstance(event,dict):raise ValueError('reference_envelope')
                    self.accept(event,time.time())
            except Exception as exc:
                with self.lock:self.error=str(exc) if isinstance(exc,ValueError) else type(exc).__name__;self.disconnects+=1
                self.stop.wait(3)
            finally:
                if ws:ws.close()

    def snapshot(self):
        with self.lock:
            # Capture each newly received point once, not fifteen minutes of history every second.
            out={kind:{a:[copy.deepcopy(p) for p in rows[a].values() if p['received_at']>self.last_recorded_received] for a in ASSETS}
                 for kind,rows in (('raw',self.points),('twap60',self.twaps))}
            self.last_recorded_received=max([self.last_recorded_received]+[p['received_at'] for rows in out.values() for points in rows.values() for p in points])
            return {**out,'status':self.status()}
    def status(self):
        with self.lock:return {'adapter':'public_chainlink_rtds_snapshots','retiring_dependency':True,'error':self.error,'generation':self.generation,
            'stale_snapshots_rejected':self.stale_snapshots_rejected,'responses':self.responses,'last_received':self.last_received,'disconnects':self.disconnects,'venue_sequence_available':False,
            'assets':{a:{'raw_points':len(self.points[a]),'latest_source_at':max(self.points[a],default=None),'twap_points':len(self.twaps[a])} for a in ASSETS}}
    def close(self):self.stop.set();self.thread.join(timeout=.3)
