"""Existing public transport, multi-asset books and supporting exchange samples."""
import copy
import json
import select
import threading
import time
from common import number
from transport import PublicSocket
import market


class Books:
    """v3 ordered stream reconstruction.

    Late-but-ordered deltas are applied and freshness is judged at use time (market.healthy).
    Deltas older than the current snapshot are already reflected in it and are skipped.
    Only genuine inconsistency (out-of-order deltas, crossed or invalid levels, unknown
    assets, future timestamps, tick changes) clears the books and reconnects.
    """
    PING_SECONDS=1.5
    def __init__(self,m,rest):
        self.m=m;self.lock=threading.RLock();self.stop=threading.Event();self.books={};self.error='connecting';self.generation=0
        self.minimums={side:rest[side]['min_order_size'] for side in ('Up','Down')}
        self.ticks={side:rest[side]['tick_size'] for side in ('Up','Down')}
        self.events=0;self.last_frame=None;self.last_lag=None;self.snapshot_at={};self.disconnections=0;self.last_disconnect_reason=None
        self.resync_reasons={};self.superseded_deltas=0;self.superseded_snapshots=0;self.late_deltas_applied=0
        self.thread=threading.Thread(target=self.run,daemon=True)

    def clear(self,reason):
        with self.lock:
            self.books={};self.snapshot_at={};self.last_frame=None;self.last_lag=None;self.generation+=1;self.error=reason

    def alive(self,received):
        """Any frame on the unbroken connection, including PONG, proves liveness up to its receive time."""
        with self.lock:
            if self.last_frame is None or received>self.last_frame:self.last_frame=received

    def side(self,token):return next((s for s,t in self.m['tokens'].items() if t==token),None)

    def handle(self,event,received):
        if event.get('market')!=self.m['condition']:return
        kind=event.get('event_type')
        with self.lock:
            self.events+=1
            if kind=='book':
                token=event['asset_id'];side=self.side(token)
                if side is None:raise ValueError('unexpected_outcome')
                raw={**event,'min_order_size':self.minimums[side],'tick_size':self.ticks[side]}
                current=market.book(raw,token,self.m['condition'],received,self.generation,allow_empty=True,check_age=False)
                if current['source_at']>received+1:raise ValueError('future_book_timestamp')
                self.last_lag=received-current['source_at']
                old=self.books.get(side)
                if old and current['source_at']<old['source_at']:
                    self.superseded_snapshots+=1
                else:
                    self.books[side]=current;self.snapshot_at[side]=current['source_at'];self.error=None
            elif kind=='price_change':
                source=market.stamp(event['timestamp'])
                if source>received+1:raise ValueError('future_delta_timestamp')
                changed={}
                for row in event['price_changes']:
                    side=self.side(row['asset_id'])
                    if side is None:raise ValueError('unexpected_delta_asset')
                    old=self.books.get(side)
                    if old is None:continue
                    if source<self.snapshot_at[side]:
                        self.superseded_deltas+=1;continue
                    if source<old['source_at']:raise ValueError('delta_time_regression')
                    if row['side'] not in ('BUY','SELL'):raise ValueError('delta_side')
                    if side not in changed:
                        changed[side]={key:{format(number(p).normalize(),'f'):str(number(n)) for p,n in old[key]} for key in ('bids','asks')}
                    p,n=number(row['price']),number(row['size'])
                    if n<0 or not 0<p<1:raise ValueError('invalid_delta')
                    level=changed[side]['bids' if row['side']=='BUY' else 'asks'];key=format(p.normalize(),'f')
                    if n:level[key]=str(n)
                    else:level.pop(key,None)
                completed={}
                for side,levels in changed.items():
                    raw={'asset_id':self.m['tokens'][side],'market':self.m['condition'],'timestamp':source,
                        'min_order_size':self.minimums[side],'tick_size':self.ticks[side],
                        **{key:[{'price':p,'size':n} for p,n in rows.items()] for key,rows in levels.items()}}
                    completed[side]=market.book(raw,self.m['tokens'][side],self.m['condition'],received,self.generation,allow_empty=True,check_age=False)
                self.books.update(completed)
                self.last_lag=received-source
                if completed and received-source>3:self.late_deltas_applied+=1
            elif kind=='tick_size_change':
                side=self.side(event.get('asset_id'))
                if side is None:raise ValueError('unknown_tick_asset')
                tick=number(event['new_tick_size'])
                if not 0<tick<1:raise ValueError('invalid_tick_change')
                self.ticks[side]=str(tick)
                self.clear('tick_change_requires_full_snapshot');return
            elif kind=='market_resolved':self.clear('market_resolved');return
        self.alive(received)

    def snapshot(self):
        with self.lock:
            if set(self.books)!={'Up','Down'}:raise ValueError('waiting_for_full_stream_books')
            if self.last_frame is None or self.last_lag is None:raise ValueError('waiting_for_stream_liveness')
            books=copy.deepcopy(self.books)
            for b in books.values():
                b['depth_truncated']=len(b['bids'])>20 or len(b['asks'])>20
                b['bids']=b['bids'][:20];b['asks']=b['asks'][:20]
                b['confirmed_at']=self.last_frame;b['stream_lag']=self.last_lag
            return books

    def run(self):
        while not self.stop.is_set():
            ws=None
            try:
                self.clear('reconnecting')
                ws=PublicSocket('ws-subscriptions-clob.polymarket.com','/ws/market');ws.s.settimeout(8)
                ws.send(json.dumps({'assets_ids':list(self.m['tokens'].values()),'type':'market','custom_feature_enabled':True}))
                heartbeat=0;generation=self.generation;silent_since=time.monotonic()
                while not self.stop.is_set() and generation==self.generation:
                    now=time.monotonic()
                    if now-heartbeat>=self.PING_SECONDS:ws.send('PING');heartbeat=now
                    if not ws.s.pending() and not select.select([ws.s],[],[],.15)[0]:
                        if time.monotonic()-silent_since>8:raise ConnectionError('book_stream_silent')
                        continue
                    raw=ws.receive();received=time.time();silent_since=time.monotonic()
                    if generation!=self.generation:break
                    if not raw or raw in ('PING','PONG'):
                        self.alive(received);continue
                    events=json.loads(raw)
                    for event in events if isinstance(events,list) else [events]:self.handle(event,received)
            except Exception as exc:
                reason=str(exc) if isinstance(exc,ValueError) else type(exc).__name__
                with self.lock:
                    self.disconnections+=1;self.last_disconnect_reason=reason
                    self.resync_reasons[reason]=self.resync_reasons.get(reason,0)+1
                self.clear(reason);self.stop.wait(2)
            finally:
                if ws:ws.close()

    def status(self):
        with self.lock:return {'events':self.events,'generation':self.generation,'error':self.error,'last_frame':self.last_frame,
            'stream_lag':self.last_lag,'disconnects':self.disconnections,'last_disconnect_reason':self.last_disconnect_reason,
            'resync_reasons':dict(self.resync_reasons),'superseded_deltas':self.superseded_deltas,
            'superseded_snapshots':self.superseded_snapshots,'late_deltas_applied':self.late_deltas_applied,'venue_sequence_available':False}

    def close(self):self.stop.set();self.thread.join(timeout=.2)


class Exchange:
    """One-second supporting aggregate-trade samples, never a settlement proxy."""
    def __init__(self):
        self.lock=threading.Lock();self.stop=threading.Event();self.latest={};self.error='connecting';self.generation=0;self.gaps=0;self.ids={}
        self.thread=threading.Thread(target=self.run,daemon=True)

    def handle(self,raw,received):
        row=json.loads(raw).get('data',{})
        if row.get('e')!='aggTrade':return
        asset=row['s'].lower().replace('usdt','')
        if asset not in ('btc','eth','sol'):return
        stamp=market.stamp(row['T']);event=market.stamp(row['E']);price=number(row['p'])
        if price<=0 or not -1<=received-stamp<=3 or event>received+1:raise ValueError('stale_exchange_trade')
        with self.lock:
            prior=self.ids.get(asset)
            if prior is not None and row['a']!=prior+1:self.gaps+=1
            self.ids[asset]=row['a']
            self.latest[asset]={'asset':asset,'price':str(price),'source_at':stamp,'event_at':event,'received_at':received,
                'aggregate_trade_id':row['a'],'generation':self.generation,'role':'supporting_only_not_contractual','source':'Binance '+row['s']}
            self.error=None

    def run(self):
        while not self.stop.is_set():
            ws=None
            try:
                with self.lock:self.latest={};self.ids={};self.generation+=1
                path='/stream?streams='+'/'.join(a+'usdt@aggTrade' for a in ('btc','eth','sol'))
                ws=PublicSocket('data-stream.binance.vision',path)
                while not self.stop.is_set():
                    raw=ws.receive()
                    if raw:self.handle(raw,time.time())
            except Exception as exc:
                with self.lock:self.error=type(exc).__name__;self.latest={}
                self.stop.wait(3)
            finally:
                if ws:ws.close()

    def snapshot(self):
        with self.lock:return {'points':copy.deepcopy(self.latest),'error':self.error,'generation':self.generation,'gaps':self.gaps}
    def close(self):self.stop.set();self.thread.join(timeout=.2)
