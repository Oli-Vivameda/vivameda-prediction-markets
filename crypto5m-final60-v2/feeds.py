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
    """v4 ordered stream reconstruction with in-place level updates.

    v3 rebuilt, re-sorted and re-hashed the whole book on every delta and saturated one
    core. v4 keeps each side as {Decimal price: Decimal size}, applies a delta by touching
    only the changed levels, and builds the validated snapshot (sorting, hashing) only
    when a consumer asks for it. Semantics are v3's: late ordered deltas are applied;
    deltas older than the snapshot are superseded; older snapshots are ignored; only real
    inconsistency clears and reconnects. Tick and minimum size are refreshed from the
    public REST book on every (re)connection, so a tick change during a disconnect
    cannot loop as invalid_book_level.
    """
    PING_SECONDS=1.5
    def __init__(self,m,rest,refresh=None,crossed_grace=2):
        self.m=m;self.lock=threading.RLock();self.stop=threading.Event();self.levels={};self.meta={};self.error='connecting';self.generation=0
        self.minimums={side:rest[side]['min_order_size'] for side in ('Up','Down')}
        self.ticks={side:rest[side]['tick_size'] for side in ('Up','Down')}
        self.tick_values={side:number(self.ticks[side]) for side in ('Up','Down')}
        self.refresh_source=refresh
        self.events=0;self.frames=0;self.last_frame=None;self.last_lag=None;self.snapshot_at={};self.disconnections=0;self.last_disconnect_reason=None
        self.resync_reasons={};self.superseded_deltas=0;self.superseded_snapshots=0;self.late_deltas_applied=0
        self.last_invalid=None;self.rule_refreshes=0;self.rule_refresh_errors=0
        self.processing_total=0.;self.processing_max=0.
        self.crossed_grace=crossed_grace;self.crossed_since={};self.crossing_episodes=0;self.crossings_resolved=0;self.crossing_max_seconds=0.;self.crossing_max_events=0;self.crossing_events={}
        self.thread=threading.Thread(target=self.run,daemon=True)

    def clear(self,reason):
        with self.lock:
            self.levels={};self.meta={};self.snapshot_at={};self.last_frame=None;self.last_lag=None;self.generation+=1;self.error=reason
            self.crossed_since={};self.crossing_events={}

    def alive(self,received):
        with self.lock:
            if self.last_frame is None or received>self.last_frame:self.last_frame=received

    def side(self,token):return next((s for s,t in self.m['tokens'].items() if t==token),None)

    def set_rules(self,rest):
        """Apply per-outcome tick/minimum from fresh public REST books (identity checked)."""
        with self.lock:
            for side in ('Up','Down'):
                raw=rest[side]
                if raw.get('asset_id')!=self.m['tokens'][side] or raw.get('market')!=self.m['condition']:raise ValueError('wrong_book_identity')
                tick=number(raw['tick_size']);minimum=number(raw['min_order_size'])
                if not 0<tick<1 or minimum<=0:raise ValueError('invalid_rest_rules')
                self.ticks[side]=str(tick);self.minimums[side]=str(minimum);self.tick_values[side]=tick
            self.rule_refreshes+=1

    def refresh_rules(self):
        if self.refresh_source is None:return
        try:self.set_rules({side:self.refresh_source(token) for side,token in self.m['tokens'].items()})
        except Exception:
            with self.lock:self.rule_refresh_errors+=1
            raise

    def resolve_crossing(self,side,received):
        span=received-self.crossed_since.pop(side);self.crossing_events.pop(side,None)
        self.crossings_resolved+=1;self.crossing_max_seconds=max(self.crossing_max_seconds,span)

    def check_crossing(self,now):
        with self.lock:
            for side,since in self.crossed_since.items():
                if now-since>self.crossed_grace:raise ValueError('persistent_crossed_book')

    def invalid(self,side,book_side,price,size,why):
        self.last_invalid={'side':side,'book_side':book_side,'price':str(price),'size':str(size),'tick':self.ticks.get(side),'why':why}
        raise ValueError('invalid_book_level')

    def handle(self,event,received):
        if event.get('market')!=self.m['condition']:return
        kind=event.get('event_type')
        with self.lock:
            self.events+=1
            if kind=='book':
                token=event['asset_id'];side=self.side(token)
                if side is None:raise ValueError('unexpected_outcome')
                source=market.stamp(event['timestamp'])
                if source>received+1:raise ValueError('future_book_timestamp')
                tick=self.tick_values[side];new={}
                for book_side in ('bids','asks'):
                    rows={}
                    for row in event[book_side]:
                        p,n=number(row['price']),number(row['size'])
                        if not 0<p<1 or n<0:self.invalid(side,book_side,p,n,'range')
                        if p%tick:self.invalid(side,book_side,p,n,'off_tick')
                        if p in rows:raise ValueError('duplicate_book_level')
                        if n:rows[p]=n
                    new[book_side]=rows
                if new['bids'] and new['asks'] and max(new['bids'])>min(new['asks']):raise ValueError('crossed_book')
                self.last_lag=received-source
                old=self.meta.get(side)
                if old and source<old['source_at']:
                    self.superseded_snapshots+=1
                else:
                    self.levels[side]=new;self.meta[side]={'source_at':source,'received_at':received}
                    self.snapshot_at[side]=source;self.error=None
                    if side in self.crossed_since:self.resolve_crossing(side,received)
            elif kind=='price_change':
                source=market.stamp(event['timestamp'])
                if source>received+1:raise ValueError('future_delta_timestamp')
                touched=set()
                for row in event['price_changes']:
                    side=self.side(row['asset_id'])
                    if side is None:raise ValueError('unexpected_delta_asset')
                    meta=self.meta.get(side)
                    if meta is None:continue
                    if source<self.snapshot_at[side]:
                        self.superseded_deltas+=1;continue
                    if source<meta['source_at']:raise ValueError('delta_time_regression')
                    if row['side']=='BUY':book_side='bids'
                    elif row['side']=='SELL':book_side='asks'
                    else:raise ValueError('delta_side')
                    p,n=number(row['price']),number(row['size'])
                    if not 0<p<1 or n<0:self.invalid(side,book_side,p,n,'range')
                    if p%self.tick_values[side]:self.invalid(side,book_side,p,n,'off_tick')
                    level=self.levels[side][book_side]
                    if n:level[p]=n
                    else:level.pop(p,None)
                    touched.add(side)
                for side in touched:
                    # v5: a crossed reconstructed book is tolerated briefly (never tradeable) and
                    # resynchronized only if it persists; venue matches can publish the aggressive
                    # level an instant before the matched level's removal.
                    b=self.levels[side]
                    self.meta[side]={'source_at':source,'received_at':received}
                    if b['bids'] and b['asks'] and max(b['bids'])>min(b['asks']):
                        if side not in self.crossed_since:
                            self.crossed_since[side]=received;self.crossing_events[side]=0;self.crossing_episodes+=1
                        self.crossing_events[side]+=1
                        self.crossing_max_events=max(self.crossing_max_events,self.crossing_events[side])
                    elif side in self.crossed_since:
                        self.resolve_crossing(side,received)
                self.check_crossing(received)
                self.last_lag=received-source
                if touched and received-source>3:self.late_deltas_applied+=1
            elif kind=='tick_size_change':
                side=self.side(event.get('asset_id'))
                if side is None:raise ValueError('unknown_tick_asset')
                tick=number(event['new_tick_size'])
                if not 0<tick<1:raise ValueError('invalid_tick_change')
                self.ticks[side]=str(tick);self.tick_values[side]=tick
                self.clear('tick_change_requires_full_snapshot');return
            elif kind=='market_resolved':self.clear('market_resolved');return
        self.alive(received)

    def build(self,side,meta,levels):
        """Full v2/v3 validation and snapshot identity, computed only on demand."""
        raw={'asset_id':self.m['tokens'][side],'market':self.m['condition'],'timestamp':meta['source_at'],
            'min_order_size':self.minimums[side],'tick_size':self.ticks[side],
            **{k:[{'price':format(p.normalize(),'f'),'size':str(n)} for p,n in levels[k].items()] for k in ('bids','asks')}}
        return market.book(raw,self.m['tokens'][side],self.m['condition'],meta['received_at'],self.generation,allow_empty=True,check_age=False)

    def snapshot(self):
        with self.lock:
            if set(self.levels)!={'Up','Down'}:raise ValueError('waiting_for_full_stream_books')
            if self.last_frame is None or self.last_lag is None:raise ValueError('waiting_for_stream_liveness')
            views={side:({'bids':dict(v['bids']),'asks':dict(v['asks'])},dict(self.meta[side])) for side,v in self.levels.items()}
            confirmed,lag=self.last_frame,self.last_lag
        books={}
        for side,(levels,meta) in views.items():
            b=self.build(side,meta,levels)
            b['depth_truncated']=len(b['bids'])>20 or len(b['asks'])>20
            b['bids']=b['bids'][:20];b['asks']=b['asks'][:20]
            b['confirmed_at']=confirmed;b['stream_lag']=lag
            books[side]=b
        return books

    def run(self):
        while not self.stop.is_set():
            ws=None
            try:
                self.clear('reconnecting')
                self.refresh_rules()
                ws=PublicSocket('ws-subscriptions-clob.polymarket.com','/ws/market');ws.s.settimeout(8)
                ws.send(json.dumps({'assets_ids':list(self.m['tokens'].values()),'type':'market','custom_feature_enabled':True}))
                heartbeat=0;generation=self.generation;silent_since=time.monotonic()
                while not self.stop.is_set() and generation==self.generation:
                    now=time.monotonic()
                    if now-heartbeat>=self.PING_SECONDS:ws.send('PING');heartbeat=now
                    self.check_crossing(time.time())
                    if not ws.s.pending() and not select.select([ws.s],[],[],.15)[0]:
                        if time.monotonic()-silent_since>8:raise ConnectionError('book_stream_silent')
                        continue
                    raw=ws.receive();received=time.time();silent_since=time.monotonic();started=time.perf_counter()
                    if generation!=self.generation:break
                    self.frames+=1
                    if not raw or raw in ('PING','PONG'):
                        self.alive(received);continue
                    events=json.loads(raw)
                    for event in events if isinstance(events,list) else [events]:self.handle(event,received)
                    spent=time.perf_counter()-started;self.processing_total+=spent
                    if spent>self.processing_max:self.processing_max=spent
            except Exception as exc:
                reason=str(exc) if isinstance(exc,ValueError) else type(exc).__name__
                with self.lock:
                    self.disconnections+=1;self.last_disconnect_reason=reason
                    self.resync_reasons[reason]=self.resync_reasons.get(reason,0)+1
                self.clear(reason);self.stop.wait(2)
            finally:
                if ws:ws.close()

    def status(self):
        with self.lock:return {'events':self.events,'frames':self.frames,'generation':self.generation,'error':self.error,'last_frame':self.last_frame,
            'stream_lag':self.last_lag,'disconnects':self.disconnections,'last_disconnect_reason':self.last_disconnect_reason,
            'resync_reasons':dict(self.resync_reasons),'superseded_deltas':self.superseded_deltas,
            'superseded_snapshots':self.superseded_snapshots,'late_deltas_applied':self.late_deltas_applied,
            'last_invalid_level':self.last_invalid,'rule_refreshes':self.rule_refreshes,'rule_refresh_errors':self.rule_refresh_errors,
            'processing_seconds_total':self.processing_total,'processing_seconds_max_frame':self.processing_max,
            'crossing_episodes':self.crossing_episodes,'crossings_resolved':self.crossings_resolved,
            'crossing_max_seconds_resolved':self.crossing_max_seconds,'crossing_max_events':self.crossing_max_events,
            'crossed_now':sorted(self.crossed_since),
            'venue_sequence_available':False}

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
