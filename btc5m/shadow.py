"""Frozen prospective strategy with delayed public-depth fills and separate cash."""
import threading
import time

STRATEGY = 'btc5m-fixed180-delay-v3'
DELAYS = (.25, 2.)
BUDGET = 5.


class Shadow:
    def __init__(self, journal, capture, stream, context, predict, fill):
        self.journal, self.capture, self.stream = journal, capture, stream
        self.context, self.predict, self.fill = context, predict, fill
        self.stop = threading.Event()
        self.lock = threading.RLock()
        self.seen = set()
        self.pending = []
        self.records = []
        self.last_snapshot = self.last_settle = 0
        self.error = None
        self.entry_guard = None
        rows = journal.rows()
        self.records = [r for r in rows if r['kind'].startswith('shadow_') and r.get('strategy') == STRATEGY]
        for r in self.records:
            if r['kind'] == 'shadow_decision': self.seen.add(r['condition_id'])
        # An interrupted delayed order cannot be filled with a later hindsight quote.
        decided = {r['decision_id'] for r in self.records if r['kind'] == 'shadow_attempt'}
        for r in self.records[:]:
            if r['kind'] == 'shadow_decision' and r.get('side') and r['id'] not in decided:
                for delay in DELAYS:
                    self.append('shadow_attempt', {'decision_id':r['id'], 'condition_id':r['condition_id'],
                        'delay_seconds':delay, 'status':'cancelled_after_restart', 'filled':False})
            elif r['kind'] == 'shadow_decision' and r.get('side'):
                present = {x['delay_seconds'] for x in self.records if x['kind']=='shadow_attempt' and x['decision_id']==r['id']}
                for delay in DELAYS:
                    if delay not in present:
                        self.append('shadow_attempt', {'decision_id':r['id'], 'condition_id':r['condition_id'],
                            'delay_seconds':delay,'status':'cancelled_after_restart','filled':False})

    def append(self, kind, body):
        payload = {**body, 'strategy':STRATEGY, 'execution':'shadow_only', 'live_execution':False}
        i = self.journal.append(kind, payload)
        self.records.append({'id':i,'kind':kind,'recorded_at':time.time(),**payload})
        return i

    def portfolios(self):
        results = {r['attempt_id']:r for r in self.records if r['kind']=='shadow_result'}
        out = {}
        today = time.strftime('%Y-%m-%d',time.gmtime())
        for delay in DELAYS:
            attempts = [r for r in self.records if r['kind']=='shadow_attempt' and r['delay_seconds']==delay]
            fills = [r for r in attempts if r.get('filled')]
            open_fills = [r for r in fills if r['id'] not in results]
            payouts = sum(results[r['id']]['payout'] for r in fills if r['id'] in results)
            profit = sum(results[r['id']]['payout']-r['fill']['total'] for r in fills if r['id'] in results)
            loss = sum(max(0,r['fill']['total']-results[r['id']]['payout']) for r in fills
                       if r['id'] in results and time.strftime('%Y-%m-%d',time.gmtime(results[r['id']]['recorded_at']))==today)
            out[str(delay)] = {'starting_cash':1000., 'cash':1000.-sum(r['fill']['total'] for r in fills)+payouts,
                'open_exposure':sum(r['fill']['total'] for r in open_fills), 'realized_profit':profit,
                'gross_loss_today':loss, 'attempts':len(attempts),'fills':len(fills),
                'missed_fills':len(attempts)-len(fills),'settled':len(fills)-len(open_fills)}
        return out

    def collect(self, market, anchor, points, now):
        if now-self.last_snapshot < 1: return
        self.last_snapshot = now
        books = None
        try: books = self.stream.snapshot(market['conditionId'], now)
        except ValueError: pass
        compact = {}
        for side, b in (books or {}).items():
            compact[side] = {k:v for k,v in b.items() if k not in ('bids','asks')}
            compact[side]['bids'] = sorted(b['bids'],key=lambda x:float(x['price']),reverse=True)[:20]
            compact[side]['asks'] = sorted(b['asks'],key=lambda x:float(x['price']))[:20]
            compact[side]['depth_scope'] = 'top20; full stream snapshots/deltas retained separately'
        self.capture.offer('market_snapshot_1s', {'slug':market['slug'],'anchor':anchor,
            'remaining_seconds':market['end_epoch']-now,'books':compact,
            'reference_latest':points[-1] if points else None}, condition_id=market['conditionId'])

    def decide(self, market, anchor, points, now, mono):
        condition = market['conditionId']
        target = market['end_epoch']-180
        if condition in self.seen or now < target: return
        self.seen.add(condition)
        decision = {'condition_id':condition,'slug':market['slug'],'end_epoch':market['end_epoch'],
                    'decision_time':now,'decision_mono':mono,'side':None,'budget':BUDGET,
                    'delays_seconds':list(DELAYS),'rule_hash':market['description'],
                    'plan':'Hold to official resolution','capture_session':self.capture.session}
        try:
            if now > target+5: raise ValueError('Missed fixed decision window')
            if self.entry_guard and not self.entry_guard():raise ValueError('Operations health pause')
            if not self.capture.healthy(): raise ValueError('Capture unavailable; shadow paused')
            if not market.get('acceptingOrders') or market.get('closed'):
                raise ValueError('Market not open for orders')
            if anchor is None: raise ValueError('Missing contract threshold')
            books = self.stream.snapshot(condition, now)
            prediction = self.predict(points,anchor,now,market['end_epoch'],market['window'])
            fee = market.get('feeSchedule',{})
            if market.get('feesEnabled') and 'rate' not in fee: raise ValueError('Fee schedule unavailable')
            rate = fee.get('rate',0) if market.get('feesEnabled') else 0
            exponent = fee.get('exponent',1)
            quotes = {}
            for side,b in books.items():
                try:
                    q = self.fill(b,BUDGET,rate,exponent)
                    p = prediction['p_up'] if side=='Up' else 1-prediction['p_up']
                    q['edge'] = p-q['break_even_probability']; quotes[side] = q
                except ValueError: continue
            decision.update(prediction=prediction,quotes=quotes,books=books,
                            reference_points=[p for p in points if now-180<=p[0]<=now],
                            fee_rate=rate,fee_exponent=exponent)
            if not quotes: raise ValueError('No side has sufficient displayed depth')
            side = max(quotes,key=lambda s:quotes[s]['edge'])
            if quotes[side]['edge'] < .05: raise ValueError('Estimated net edge below five percentage points')
            decision['side'] = side
            decision['max_break_even_probability'] = min(.999,quotes[side]['break_even_probability']+.02)
            decision['reason'] = 'Frozen baseline selection; two delayed execution arms'
        except (ValueError,KeyError,TypeError) as exc:
            decision['side'] = None; decision['reason'] = str(exc)
        import hashlib
        decision['rule_hash'] = hashlib.sha256(market['description'].encode()).hexdigest()
        i = self.append('shadow_decision',decision)
        if decision.get('prediction') and decision.get('quotes'):
            for delay in DELAYS:
                self.pending.append({'decision_id':i,'decision':decision,'delay':delay,'due':mono+delay})

    def execute(self, now, mono):
        due = [p for p in self.pending if p['due']<=mono]
        for pending in due:
            self.pending.remove(pending)
            d, delay = pending['decision'],pending['delay']
            attempt = {'decision_id':pending['decision_id'],'condition_id':d['condition_id'],
                'slug':d['slug'],'end_epoch':d['end_epoch'],'side':d['side'],'delay_seconds':delay,
                'actual_delay_seconds':mono-d['decision_mono'],'filled':False}
            probe={'decision_id':pending['decision_id'],'condition_id':d['condition_id'],
                   'delay_seconds':delay,'actual_delay_seconds':mono-d['decision_mono'],
                   'due_mono':pending['due'],'available':False}
            try:
                if mono-pending['due']>1 or now>=d['end_epoch']-60:raise ValueError('Probe execution window closed')
                if not self.capture.healthy() or (self.entry_guard and not self.entry_guard()):raise ValueError('Probe health pause')
                books=self.stream.snapshot(d['condition_id'],now)
                compact={}
                for side,b in books.items():
                    compact[side]={k:v for k,v in b.items() if k not in ('asks','bids')}
                    compact[side]['asks']=sorted(b['asks'],key=lambda x:float(x['price']))[:20]
                    compact[side]['bids']=sorted(b['bids'],key=lambda x:float(x['price']),reverse=True)[:20]
                probe.update(available=True,books=compact,depth_scope='top20; fail if stake requires deeper liquidity')
            except (ValueError,KeyError,TypeError) as exc:probe['reason']=str(exc)
            self.append('shadow_quote_probe',probe)
            if not d['side']:continue
            try:
                if mono-pending['due'] > 1: raise ValueError('Missed execution window')
                if now>=d['end_epoch']-60: raise ValueError('Execution deadline closed')
                if self.entry_guard and not self.entry_guard():raise ValueError('Operations health pause')
                if not self.capture.healthy(): raise ValueError('Capture unavailable')
                account = self.portfolios()[str(delay)]
                if account['cash']<BUDGET or account['open_exposure']+BUDGET>50 or account['gross_loss_today']>=20:
                    raise ValueError('Shadow capital/risk stop')
                book = self.stream.snapshot(d['condition_id'],now)[d['side']]
                # Quote must have ARRIVED after the simulated execution time.
                if book['received_mono_ns']/1e9 < pending['due']:
                    raise ValueError('No post-delay book update; no assumed fill')
                q = self.fill(book,BUDGET,d['fee_rate'],d['fee_exponent'])
                if q['break_even_probability']>d['max_break_even_probability']:
                    raise ValueError('Frozen adverse-price limit exceeded')
                attempt.update(filled=True,status='filled',fill=q,book=book,
                    price_movement=q['break_even_probability']-d['quotes'][d['side']]['break_even_probability'])
            except (ValueError,KeyError,TypeError) as exc:
                attempt['status'] = str(exc)
            self.append('shadow_attempt',attempt)

    def settle(self):
        outcomes = {r['condition_id']:r for r in self.journal.rows() if r['kind']=='market_resolution'}
        settled = {r['attempt_id'] for r in self.records if r['kind']=='shadow_result'}
        for r in self.records[:]:
            if r['kind']!='shadow_attempt' or not r.get('filled') or r['id'] in settled: continue
            o = outcomes.get(r['condition_id'])
            if not o or o['winner'] not in ('Up','Down'): continue
            payout = r['fill']['shares'] if r['side']==o['winner'] else 0.
            self.append('shadow_result',{'attempt_id':r['id'],'condition_id':r['condition_id'],
                'winner':o['winner'],'payout':payout,'net_profit':payout-r['fill']['total'],
                'source':'CLOB explicit winning token','resolution_event_id':o['id']})

    def tick(self, now=None, mono=None):
        now = time.time() if now is None else now
        mono = time.monotonic() if mono is None else mono
        with self.lock:
            market,anchor,points = self.context()
            if market:
                self.collect(market,anchor,points,now)
                self.decide(market,anchor,points,now,mono)
            self.execute(now,mono)
            if now-self.last_settle>=30:
                self.last_settle=now;self.settle()

    def run(self):
        while not self.stop.is_set():
            try:
                self.tick();self.error=None
            except Exception as exc:
                self.error=type(exc).__name__+': shadow loop failed; strategy stopped'
                self.capture.offer('feed_status',{'shadow':'stopped_on_error','error':type(exc).__name__})
                self.stop.set()
            self.stop.wait(.1)

    def state(self):
        with self.lock:
            decisions = [r for r in self.records if r['kind']=='shadow_decision']
            return {'strategy':STRATEGY,'live_execution':False,'decisions':len(decisions),
                    'skips':sum(r['side'] is None for r in decisions),'pending_attempts':len(self.pending),
                    'portfolios':self.portfolios(),'error':self.error,
                    'latest_decision':decisions[-1] if decisions else None,
                    'note':'Observed delayed ask-depth simulation; queue position, impact and actual fills remain untested'}
