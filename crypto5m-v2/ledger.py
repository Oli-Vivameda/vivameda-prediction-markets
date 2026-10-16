"""One append-only experiment ledger; both strategies share cash and risk limits."""
import copy
import json
from pathlib import Path
import sqlite3
from common import D,number,canonical,digest
import market

ZERO='0'*64

def empty():return {'positions':{},'days':{},'halted':False,'consumed':{},'credits':{},'last_time':0}
def day(now):return int(now)//86400

def portfolio(s,c):
    positions=s['positions'];spent=sum((number(f['fill']['total']) for p in positions.values() for f in p['attempts'].values() if f['fill']),D(0))
    credits=sum((number(v) for v in s['credits'].values()),D(0))
    reserved=sum((number(p['budget'])-sum((number(x['fill']['total']) for x in p['attempts'].values() if x['fill']),D(0))
                  for p in positions.values() if not p['finished']),D(0))
    cash=number(c['starting_cash'])-spent+credits
    open_cost=sum((sum((number(x['fill']['total']) for x in p['attempts'].values() if x['fill']),D(0))
        for k,p in positions.items() if k not in s['credits']),D(0))
    return {'cash':cash,'available':cash-reserved,'reserved':reserved,'equity_lower_bound':cash,
            'open_cost':open_cost,'spent':spent,'credits':credits}

def consumption(s):return {tuple(json.loads(k)):number(v) for k,v in s['consumed'].items()}
def terms(m):return digest({k:m[k] for k in ('condition','tokens','rules_sha256','rate','tick','minimum_notional','version')})

def apply(s,kind,data,now,c):
    if now<s['last_time']:raise ValueError('event_time_regression')
    s['last_time']=now
    if kind=='day':
        k=str(day(now))
        if k in s['days'] or data!={'day':k,'equity':str(portfolio(s,c)['equity_lower_bound'])}:raise ValueError('invalid_day_baseline')
        s['days'][k]=data['equity'];return
    if kind=='halt':
        if s['halted'] or data.get('reason')!='daily_loss_limit':raise ValueError('invalid_halt')
        baseline=number(s['days'][str(day(now))])
        if baseline-portfolio(s,c)['equity_lower_bound']<number(c['daily_loss']):raise ValueError('halt_without_loss')
        s['halted']=True;return
    if kind=='reserve':
        key=data['id'];m=data['market'];budget=number(data['budget']);strategy=data['strategy']
        if strategy not in ('directional','paired') or key in s['positions'] or data.get('required_feeds_verified') is not True:raise ValueError('invalid_reservation')
        if s['halted'] or not m['active'] or m['closed'] or not m['accepting'] or not m['rules_verified']:raise ValueError('entries_disabled')
        if not m['start']<=now<m['end']-c['minimum_remaining_seconds']:raise ValueError('entry_window')
        if not 0<=now-m['retrieved_at']<=30:raise ValueError('stale_market_terms')
        if not 0<budget<=number(c['directional_cap' if strategy=='directional' else 'pair_cap']):raise ValueError('position_cap')
        if any(p['strategy']==strategy and p['market']['asset']==m['asset'] and p['market']['start']==m['start'] for p in s['positions'].values()):raise ValueError('duplicate_asset_window')
        committed=sum((sum((number(x['fill']['total']) for x in p['attempts'].values() if x['fill']),D(0)) if p['finished'] else number(p['budget'])
            for p in s['positions'].values() if p['market']['start']==m['start']),D(0))
        p=portfolio(s,c);baseline=number(s['days'][str(day(now))])
        if p['available']<budget or committed+budget>number(c['window_cap']):raise ValueError('shared_capital_or_window_limit')
        if max(D(0),baseline-p['equity_lower_bound'])+p['reserved']+budget>number(c['daily_loss']):raise ValueError('daily_reserved_loss_limit')
        plans=data['plans']
        if ([p['side'] for p in plans] not in (['Up'],['Down']) if strategy=='directional' else [p['side'] for p in plans]!=['Up','Down']):raise ValueError('invalid_leg_plan')
        if any(number(p['quantity'])<=0 or not 0<number(p['limit'])<1 for p in plans):raise ValueError('invalid_quantity_or_limit')
        import strategy as strategy_module
        if data!=strategy_module.plan(m,data['input_books'],data['prediction'],now,c,s,strategy):raise ValueError('reservation_math_or_evidence')
        s['positions'][key]={**data,'created_at':now,'attempts':{},'finished':False};return
    key=data['id'];p=s['positions'].get(key)
    if not p:raise ValueError('missing_position')
    if kind=='attempt':
        leg=data['leg'];legkey=str(leg)
        if type(leg) is not int or leg not in range(len(p['plans'])) or legkey in p['attempts'] or p['finished']:raise ValueError('duplicate_or_invalid_attempt')
        due=p['created_at']+c['delay_seconds']
        target=number(p['plans'][leg]['quantity'])
        if leg:
            prior=p['attempts'].get('0')
            if not prior or not prior['fill']:raise ValueError('second_leg_without_first')
            due=prior['recorded_at']+c['pair_leg_delay_seconds'];target=number(prior['fill']['shares'])
        fill=data['fill']
        if fill:
            b=data['book'];started=data['request_started'];received=data['received_at'];m=p['market']
            if not due<=started<=received<=now or received-due>c['maximum_lateness_seconds'] or now>=m['end']-c['minimum_remaining_seconds']:
                raise ValueError('fill_timing')
            if b['source_at']<due or data['generation_at_reserve']!=b['generation'] or data.get('continuity_without_venue_sequence') is not True:raise ValueError('intervening_gap_or_pre_delay_book')
            market.healthy(b,m,received,c)
            initial=p['input_books'][p['plans'][leg]['side']]
            if number(b['tick'])!=number(initial['tick']) or number(b['min_shares'])!=number(initial['min_shares']):raise ValueError('book_tick_or_minimum_changed')
            if b['token']!=m['tokens'][p['plans'][leg]['side']]:raise ValueError('wrong_outcome_fill')
            remaining=number(p['budget'])-sum((number(x['fill']['total']) for x in p['attempts'].values() if x['fill']),D(0))
            expected=market.execute_depth(b,m,remaining,target,consumption(s),p['plans'][leg]['limit'],c['additional_cost_per_share'])
            if fill!=expected or number(fill['shares'])<=0 or number(fill['unit_cost'])>number(p['plans'][leg]['maximum_unit_cost']):raise ValueError('fill_math_or_cost_limit')
            for price,quantity in fill['levels']:
                k=canonical([m['condition'],b['token'],price]);s['consumed'][k]=str(number(s['consumed'].get(k,0))+number(quantity))
        p['attempts'][legkey]={**data,'recorded_at':now};return
    if kind=='finish':
        if p['finished']:raise ValueError('duplicate_finish')
        if len(p['attempts'])!=len(p['plans']) and data.get('reason') not in ('restart_cancel_remaining','first_leg_unfilled','owner_stop_cancel_remaining'):
            raise ValueError('unfinished_legs')
        p['finished']=True;return
    if kind=='credit':
        if key in s['credits'] or not p['finished']:raise ValueError('duplicate_or_unfinished_credit')
        proof=data['proof'];m=p['market'];raw=proof['raw'];tokens=raw.get('tokens',[]);w=[t for t in tokens if t.get('winner') is True]
        if (raw.get('condition_id')!=m['condition'] or raw.get('closed') is not True or len(w)!=1
            or {t.get('outcome'):str(t.get('token_id')) for t in tokens}!=m['tokens']
            or proof['winner']!=w[0].get('outcome') or proof.get('redeemable_observed') is not True
            or not m['end']<proof['confirmed_at']<=now-c['redemption_delay_seconds']):raise ValueError('unconfirmed_or_early_payout')
        payout=sum((number(a['fill']['shares']) for leg,a in p['attempts'].items() if a['fill'] and p['plans'][int(leg)]['side']==proof['winner']),D(0))
        if number(data['payout'])!=payout:raise ValueError('incorrect_payout')
        s['credits'][key]=str(payout);return
    raise ValueError('unsupported_event')


class Ledger:
    def __init__(self,path,c,bundle,now):
        self.config=c;self.db=sqlite3.connect(str(path),timeout=10);self.db.execute('PRAGMA synchronous=FULL')
        self.db.execute('CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, event_key TEXT UNIQUE,kind TEXT,recorded REAL,body TEXT,prior TEXT,sha TEXT)')
        self.db.commit();self.state=empty();self.tip=ZERO;self.genesis=None
        for key,kind,stamp,raw,prior,sha in self.db.execute('SELECT event_key,kind,recorded,body,prior,sha FROM events ORDER BY id'):
            envelope={'key':key,'kind':kind,'recorded':stamp,'body':json.loads(raw)}
            if prior!=self.tip or digest([prior,envelope])!=sha:raise ValueError('ledger_integrity')
            if self.genesis is None:
                if kind!='genesis' or key!='genesis':raise ValueError('missing_genesis')
                self.genesis=envelope['body']
                if self.genesis['config']!=c or self.genesis['bundle']!=bundle:raise ValueError('experiment_pin_changed')
            else:apply(self.state,kind,envelope['body'],stamp,c)
            self.tip=sha
        if self.genesis is None:
            self.genesis={'config':c,'bundle':bundle,'started_at':now,'stage':'collecting data—no validated edge'}
            self._insert('genesis','genesis',self.genesis,now)
        self.started=self.genesis['started_at']

    def _insert(self,key,kind,data,now):
        now=float(now)
        envelope={'key':key,'kind':kind,'recorded':now,'body':data};sha=digest([self.tip,envelope])
        with self.db:self.db.execute('INSERT INTO events(event_key,kind,recorded,body,prior,sha) VALUES(?,?,?,?,?,?)',
            (key,kind,now,canonical(data),self.tip,sha))
        self.tip=sha

    def append(self,key,kind,data,now):
        candidate=copy.deepcopy(self.state);apply(candidate,kind,data,now,self.config)
        self._insert(key,kind,data,now);self.state=candidate

    def refresh_day(self,now):
        k=str(day(now))
        if k not in self.state['days']:self.append('day:'+k,'day',{'day':k,'equity':str(portfolio(self.state,self.config)['equity_lower_bound'])},now)
        if not self.state['halted'] and number(self.state['days'][k])-portfolio(self.state,self.config)['equity_lower_bound']>=number(self.config['daily_loss']):
            self.append('halt','halt',{'reason':'daily_loss_limit'},now)

    def recover(self,now):
        for k,p in list(self.state['positions'].items()):
            if not p['finished']:self.append('finish:'+k,'finish',{'id':k,'reason':'restart_cancel_remaining'},now)

    def close(self):self.db.close()
