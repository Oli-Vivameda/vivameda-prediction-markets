"""Isolated public collector and frozen research-only paper operation."""
import argparse
import fcntl
import json
import math
import os
from pathlib import Path
import shutil
import signal
import sqlite3
import time
from common import D,number,canonical,digest,config
from capture import Capture
from feeds import Books,Exchange
from reference import Reference
from ledger import Ledger,portfolio,consumption,terms,entries_halted,realized_losses
import market
import model
import strategy


def connect_index(path):
    db=sqlite3.connect(str(path),timeout=10)
    db.execute('PRAGMA synchronous=FULL')
    db.execute('CREATE TABLE IF NOT EXISTS markets(condition TEXT PRIMARY KEY,end REAL,body TEXT,sha TEXT)')
    db.execute('CREATE TABLE IF NOT EXISTS outcomes(condition TEXT PRIMARY KEY,body TEXT,sha TEXT)')
    db.execute('CREATE TABLE IF NOT EXISTS observations(condition TEXT,bucket INTEGER,body TEXT,sha TEXT,PRIMARY KEY(condition,bucket))')
    db.execute('CREATE TABLE IF NOT EXISTS reconstructions(condition TEXT,kind TEXT,body TEXT,sha TEXT,PRIMARY KEY(condition,kind))')
    db.commit()
    return db


class Study:
    def __init__(self,state,bundle,c=None,start_feeds=True,clock=time.time):
        self.state=Path(state);self.state.mkdir(mode=0o700,parents=True,exist_ok=True)
        if self.state.is_symlink() or self.state.resolve()!=self.state or self.state.stat().st_uid!=os.geteuid():raise ValueError('unsafe_study_directory')
        self.clock=clock;self.config=c or config();self.bundle=bundle;now=clock()
        self.journal=Ledger(self.state/'ledger.sqlite3',self.config,bundle,now)
        self.journal.recover(now);self.db=connect_index(self.state/'index.sqlite3')
        self.capture=Capture(self.state/'capture.sqlite3',self.config['capture_cap_bytes'],self.config['minimum_free_bytes'])
        self.exchange=Exchange();self.reference=Reference();self.feeds={};self.markets={};self.history={a:[] for a in self.config['assets']}
        self.last_discover=0;self.last_sample=0;self.last_decision=0;self.last_resolve=0;self.last_status=0
        self.last_observed={};self.ended={};self.last_reconcile=0
        self.errors={};self.running_feeds=start_feeds
        if start_feeds:
            self.exchange.thread.start();self.reference.thread.start()
        self.capture.offer('study_start',{'config_sha256':digest(self.config),'bundle':bundle,'existing_ledger_resumed':now!=self.journal.started})

    def store(self,table,key,body,**extras):
        raw=canonical(body);sha=digest(body)
        if table=='observations':
            size=sum(p.stat().st_size for p in self.state.iterdir() if p.is_file() and p.name.startswith(('ledger.sqlite3','index.sqlite3')))
            if size>=self.config['ledger_cap_bytes'] or shutil.disk_usage(self.state).free<self.config['minimum_free_bytes']:
                self.errors['observation_index']='storage_guard; original records preserved'
                return False
        with self.db:
            if table=='markets':self.db.execute('INSERT OR IGNORE INTO markets VALUES(?,?,?,?)',(key,body['end'],raw,sha))
            elif table=='outcomes':self.db.execute('INSERT OR IGNORE INTO outcomes VALUES(?,?,?)',(key,raw,sha))
            elif table=='observations':self.db.execute('INSERT OR IGNORE INTO observations VALUES(?,?,?,?)',(key,extras['bucket'],raw,sha))
            else:raise ValueError('invalid_index_table')

    def index_guard(self):
        size=sum(p.stat().st_size for p in self.state.iterdir() if p.is_file() and p.name.startswith(('ledger.sqlite3','index.sqlite3')))
        return size<self.config['ledger_cap_bytes'] and shutil.disk_usage(self.state).free>=self.config['minimum_free_bytes']

    def discover(self,now):
        if self.capture.error or not self.index_guard():
            self.errors['storage_guard']='new discovery/entries paused; existing records retained'
            return
        if now-self.last_discover<self.config['discovery_seconds']:return
        self.last_discover=now;start=int(now)//300*300
        for asset in self.config['assets']:
            try:
                raw,m=market.discover(asset,start)
                self.capture.offer('market_metadata',{'raw':raw,'normalized':m},condition_id=m['condition'])
                old=self.markets.get(asset)
                if old and old['condition']==m['condition'] and terms(old)!=terms(m):
                    if asset in self.feeds:self.feeds.pop(asset).close()
                if old and old['condition']!=m['condition']:self.ended[asset]=(self.ended.get(asset,[])+[old])[-3:]
                self.markets[asset]=m;self.store('markets',m['condition'],m)
                if asset not in self.feeds or self.feeds[asset].m['condition']!=m['condition']:
                    if asset in self.feeds:self.feeds.pop(asset).close()
                    rest={side:market.get('https://clob.polymarket.com/book?token_id='+token) for side,token in m['tokens'].items()}
                    for side,b in rest.items():market.book(b,m['tokens'][side],m['condition'],self.clock(),allow_empty=True)
                    feed=Books(m,rest,refresh=lambda token:market.get('https://clob.polymarket.com/book?token_id='+token),crossed_grace=self.config['crossed_grace_seconds']);self.feeds[asset]=feed
                    if self.running_feeds:feed.thread.start()
                self.errors.pop(asset,None)
            except Exception as exc:
                self.errors[asset]=str(exc) if isinstance(exc,ValueError) else type(exc).__name__
                self.capture.offer('discovery_gap',{'asset':asset,'reason':self.errors[asset],'received_at':self.clock()})

    def sampled_books(self,asset,now):
        m=self.markets[asset];books=self.feeds[asset].snapshot()
        checked_at=max(now,self.clock())
        for b in books.values():market.fresh(b,m,checked_at,self.config)
        return books

    def diagnostics(self,asset,books,exchange,now):
        point=exchange['points'].get(asset);history=self.history[asset]
        if point and (not history or point['source_at']>history[-1]['source_at']):history.append(point)
        history[:]=[p for p in history if now-p['source_at']<=180]
        returns=volatility=None
        if len(history)>1:
            duration=history[-1]['source_at']-history[0]['source_at']
            if duration>0:
                values=[float(number(p['price'])) for p in history]
                returns=math.log(values[-1]/values[0]);volatility=math.sqrt(sum(math.log(b/a)**2 for a,b in zip(values,values[1:]))/duration)
        imbalance=None
        if books:
            b=books['Up'];bid=sum((number(n) for p,n in b['bids'][:5]),number(0));ask=sum((number(n) for p,n in b['asks'][:5]),number(0))
            imbalance=str((bid-ask)/(bid+ask)) if bid+ask>0 else None
        return {'supporting_exchange':point,'supporting_log_return':returns,'supporting_realized_volatility_per_sqrt_second':volatility,
            'book_imbalance':imbalance,'opening_reference':None,'contractual_reference':None,'normalized_distance':None,
            'missing_reason':'reference_inputs_recorded_separately'}

    def sample(self,now):
        if self.capture.error:return
        if now-self.last_sample<self.config['capture_seconds']:return
        self.last_sample=now;exchange=self.exchange.snapshot()
        self.capture.offer('exchange_samples',exchange,received_at=now)
        self.capture.offer('contractual_reference_samples',self.reference.snapshot(),received_at=self.clock())
        for asset,m in self.markets.items():
            try:books=self.sampled_books(asset,now);reason=None
            except (ValueError,KeyError) as exc:books=None;reason=str(exc)
            sampled_at=self.clock()
            context={'market':m['condition'],'asset':asset,'remaining':m['end']-now,'books':books,'book_gap':reason,
                'feed_status':self.feeds[asset].status() if asset in self.feeds else None,
                **self.diagnostics(asset,books,exchange,now)}
            self.capture.offer('observed_state',context,condition_id=m['condition'],received_at=sampled_at)

    def storage_ok(self):
        size=sum(p.stat().st_size for p in self.state.iterdir() if p.is_file() and p.name.startswith(('ledger.sqlite3','index.sqlite3')))
        return self.capture.healthy() and size<self.config['ledger_cap_bytes'] and shutil.disk_usage(self.state).free>=self.config['minimum_free_bytes']

    def decide(self,now):
        if self.capture.error or not self.index_guard():return
        bucket=int(now)//self.config['final_minute_decision_seconds']
        if bucket==self.last_decision:return
        self.last_decision=bucket
        for asset,m in self.markets.items():
            remaining=m['end']-now
            final=self.config['final_minute_min_remaining']<=remaining<=self.config['final_minute_max_remaining']
            # Outside the final minute: calibration observations only, every decision_seconds.
            if not final and now-self.last_observed.get(asset,0)<self.config['decision_seconds']:continue
            self.last_observed[asset]=now
            record={'asset':asset,'condition':m['condition'],'start':m['start'],'end':m['end'],'observed_at':now,
                'split':model.partition(m['start'],self.journal.started,self.config),'model_prediction':None,
                'market_probability':None,'stage':'collecting data—no validated edge','decisions':{},'rules_sha256':m['rules_sha256']}
            try:
                books=self.sampled_books(asset,now)
                now=self.clock();record['observed_at']=now
                reference=anchor=None;reference_error=None
                try:reference,anchor=self.reference.inputs(m,now)
                except ValueError as exc:reference_error=exc
                inputs={'market':m,'books':books,'reference':reference,'opening_twap':anchor,'observed_at':now}
                record['inputs_sha256']=digest(inputs)
                self.capture.offer('decision_inputs',inputs,condition_id=m['condition'],received_at=now)
                record['market_probability'],record['market_probability_method']=market.implied_p_up(books)
                if not final:raise ValueError('outside_final_minute')
                if reference_error:raise reference_error
                # Partial-TWAP forecast from the public Chainlink raw points and exact opening TWAP.
                prediction=model.predict_final(m,books,reference,anchor,now,self.config)
                record['model_prediction']=prediction
                # Exact input timestamps let the offline training builder prove no lookahead.
                received=[b[k] for b in books.values() for k in ('received_at','confirmed_at') if k in b]
                received+=[p['received_at'] for p in reference['points']]+[anchor['received_at']]
                sources=[b['source_at'] for b in books.values()]+[p['source_at'] for p in reference['points']]+[anchor['source_at']]
                record['input_max_received_at']=max(received);record['input_max_source_at']=max(sources)
            except (ValueError,KeyError) as exc:
                record['decisions']={s:'SKIP:'+str(exc) for s in self.config['strategies']}
            else:
                for name in self.config['strategies']:
                    try:
                        if (self.state/'STOP').exists():raise ValueError('owner_stop')
                        if not self.storage_ok():raise ValueError('capture_or_storage_guard')
                        if any(p['strategy']==name and p['market']['condition']==m['condition'] for p in self.journal.state['positions'].values()):
                            raise ValueError('already_entered_this_window')
                        proposed=strategy.plan(m,books,prediction,self.clock(),self.config,self.journal.state,name)
                        self.journal.append('reserve:'+proposed['id'],'reserve',proposed,self.clock())
                        record['decisions'][name]='RESERVED'
                    except (ValueError,sqlite3.IntegrityError) as exc:record['decisions'][name]='SKIP:'+str(exc)
            self.store('observations',m['condition'],record,bucket=bucket)
            self.capture.offer('decision',record,condition_id=m['condition'],received_at=self.clock())

    def attempts(self,now):
        for key,p in list(self.journal.state['positions'].items()):
            if p['finished']:continue
            if (self.state/'STOP').exists():
                self.journal.append('finish:'+key,'finish',{'id':key,'reason':'owner_stop_cancel_remaining'},self.clock());continue
            leg=len(p['attempts'])
            if leg and not p['attempts']['0']['fill']:
                self.journal.append('finish:'+key,'finish',{'id':key,'reason':'first_leg_unfilled'},self.clock());continue
            due=(p['created_at']+self.config['delay_seconds']) if leg==0 else (p['attempts']['0']['recorded_at']+self.config['pair_leg_delay_seconds'])
            if now<due:continue
            data={'id':key,'leg':leg,'fill':None,'reason':None}
            try:
                if not self.storage_ok():raise ValueError('capture_or_storage_guard')
                m=p['market'];side=p['plans'][leg]['side'];feed=self.feeds[m['asset']]
                if feed.generation!=p['generation'][side]:raise ValueError('intervening_feed_reconnect')
                if terms(self.markets[m['asset']])!=p['market_terms_sha256']:raise ValueError('market_terms_changed')
                raw,current=market.discover(m['asset'],m['start'])
                if terms(current)!=p['market_terms_sha256'] or current['closed'] or not current['accepting']:raise ValueError('market_terms_or_status_changed')
                requested=self.clock()
                if requested-due>self.config['maximum_lateness_seconds']:raise ValueError('missed_execution_window')
                raw=market.get('https://clob.polymarket.com/book?token_id='+m['tokens'][side]);received=self.clock()
                b=market.book(raw,m['tokens'][side],m['condition'],received,feed.generation)
                # Touch the stream again: stale/disconnected stream prevents a REST-only paper fill.
                self.sampled_books(m['asset'],received)
                target=p['plans'][leg]['quantity'] if leg==0 else p['attempts']['0']['fill']['shares']
                spent=sum((number(a['fill']['total']) for a in p['attempts'].values() if a['fill']),D(0))
                fill=market.execute_depth(b,m,number(p['budget'])-spent,target,consumption(self.journal.state),p['plans'][leg]['limit'],self.config['additional_cost_per_share'])
                if number(fill['shares'])<=0:raise ValueError('no_post_delay_liquidity')
                data.update(fill=fill,book=b,request_started=requested,received_at=received,
                    generation_at_reserve=p['generation'][side],continuity_without_venue_sequence=True)
                # The ledger rechecks timing, source timestamps, mapping, cost and consumed depth.
                self.journal.append('attempt:'+key+':'+str(leg),'attempt',data,self.clock())
            except (ValueError,OSError,KeyError,TypeError) as exc:
                data={'id':key,'leg':leg,'fill':None,'reason':str(exc) if isinstance(exc,ValueError) else type(exc).__name__}
                self.journal.append('attempt:'+key+':'+str(leg),'attempt',data,self.clock())
            p=self.journal.state['positions'][key]
            if len(p['attempts'])==len(p['plans']):self.journal.append('finish:'+key,'finish',{'id':key,'reason':'attempts_complete_hold_to_settlement'},self.clock())

    def resolve(self,now):
        if now-self.last_resolve<15:return
        self.last_resolve=now
        pending=list(self.db.execute('SELECT m.condition,m.body,m.sha FROM markets m LEFT JOIN outcomes o ON o.condition=m.condition WHERE o.condition IS NULL AND m.end<? ORDER BY m.end',(now,)))
        if pending:
            offset=(int(now)//15*6)%len(pending);pending=(pending[offset:]+pending[:offset])[:6]
        for condition,raw,sha in pending:
            try:
                m=json.loads(raw)
                if digest(m)!=sha:raise ValueError('market_index_integrity')
                proof=market.resolution(m)
                if proof is not None:
                    self.store('outcomes',condition,proof)
                    self.capture.offer('official_resolution',{'condition':condition,**proof},condition_id=condition,received_at=self.clock())
            except (OSError,ValueError,KeyError,TypeError) as exc:self.errors['resolution']=type(exc).__name__
        for key,p in list(self.journal.state['positions'].items()):
            if key in self.journal.state['credits'] or not p['finished']:continue
            result=self.db.execute('SELECT body,sha FROM outcomes WHERE condition=?',(p['market']['condition'],)).fetchone()
            if result is None:continue
            proof=json.loads(result[0])
            if digest(proof)!=result[1]:raise ValueError('outcome_index_integrity')
            if now<proof['confirmed_at']+self.config['redemption_delay_seconds']:continue
            payout=sum((number(a['fill']['shares']) for leg,a in p['attempts'].items() if a['fill'] and p['plans'][int(leg)]['side']==proof['winner']),D(0))
            self.journal.append('credit:'+key,'credit',{'id':key,'proof':proof,'payout':str(payout)},self.clock())

    def reconcile(self,now):
        """Preregistered check of our TWAP reconstruction against official Chainlink snapshots."""
        if now-self.last_reconcile<5:return
        self.last_reconcile=now
        done={(c,k) for c,k in self.db.execute('SELECT condition,kind FROM reconstructions')}
        for asset in self.config['assets']:
            for m in [*self.ended.get(asset,[]),*([self.markets[asset]] if asset in self.markets else [])]:
                for kind,ts in (('open',m['start']),('close',m['end'])):
                    if (m['condition'],kind) in done or now<ts+5:continue
                    with self.reference.lock:
                        official=self.reference.twaps[asset].get(ts);points=list(self.reference.points[asset].values())
                    if official is None:continue
                    try:
                        value,_,worst=model.step_average(points,ts-60,ts,self.config['reconstruction_max_step_seconds'])
                    except ValueError as exc:
                        if now<ts+120:continue
                        body={'asset':asset,'condition':m['condition'],'kind':kind,'at':ts,'official':official['price'],'reconstructed':None,'error_bps':None,'reason':str(exc)}
                    else:
                        off=float(number(official['price']))
                        body={'asset':asset,'condition':m['condition'],'kind':kind,'at':ts,'official':official['price'],'reconstructed':value,
                            'error_bps':(value-off)/off*10000,'max_step_seconds':worst,'reason':None}
                    with self.db:self.db.execute('INSERT OR IGNORE INTO reconstructions VALUES(?,?,?,?)',(m['condition'],kind,canonical(body),digest(body)))
                    self.capture.offer('twap_reconstruction',body,condition_id=m['condition'],received_at=self.clock())

    def reconstruction_summary(self):
        errors=[];missing=0
        for raw, in self.db.execute('SELECT body FROM reconstructions'):
            v=json.loads(raw)
            if v['error_bps'] is None:missing+=1
            else:errors.append(abs(v['error_bps']))
        errors.sort()
        return {'comparisons':len(errors),'unusable':missing,'median_abs_error_bps':errors[len(errors)//2] if errors else None,
            'max_abs_error_bps':errors[-1] if errors else None,'preregistered_limit_bps':1.0}

    def status(self,now):
        p={k:str(v) for k,v in portfolio(self.journal.state,self.config).items()};counts={}
        for raw, in self.db.execute('SELECT body FROM observations ORDER BY rowid DESC LIMIT 1000'):
            for name,reason in json.loads(raw)['decisions'].items():counts[name+':'+reason]=counts.get(name+':'+reason,0)+1
        result={'schema':self.config['version'],'observed_at':now,'started_at':self.journal.started,'bundle':self.bundle,
            'stage':'collecting data—no validated edge','edge_validated':False,'live_execution':False,'signer_access':False,
            'reference_adapter':'public Chainlink RTDS snapshots; no credentials accessed','reference_feed':self.reference.status(),'rules_verified_assets':sorted(self.markets),
            'market_count':self.db.execute('SELECT COUNT(*) FROM markets').fetchone()[0],
            'outcome_count':self.db.execute('SELECT COUNT(*) FROM outcomes').fetchone()[0],
            'observation_count':self.db.execute('SELECT COUNT(*) FROM observations').fetchone()[0],
            'positions':len(self.journal.state['positions']),'portfolio':p,'halted':self.journal.state['halted'],
            'entries_halted_today':entries_halted(self.journal.state,now),'day_halts':list(self.journal.state['day_halts']),
            'realized_losses':{k:str(v) for k,v in realized_losses(self.journal.state,self.config,now).items()},
            'capture':self.capture.state(),'recent_reasons_max_1000_observations':counts,'errors':self.errors,
            'book_feeds':{a:f.status() for a,f in self.feeds.items()},'exchange_feed':{k:v for k,v in self.exchange.snapshot().items() if k!='points'},
            'twap_reconstruction':self.reconstruction_summary(),'lane':'final-minute partial TWAP',
            'evaluation_final_after':self.journal.started+sum(self.config[k] for k in ('train_days','calibration_days','selection_days','final_days'))*86400}
        path=self.state/'status.new';path.write_text(canonical(result));path.chmod(0o600);path.replace(self.state/'status.json')
        return result

    def attempt_due_soon(self,now,horizon=6):
        for p in self.journal.state['positions'].values():
            if p['finished']:continue
            leg=len(p['attempts'])
            if leg==0:due=p['created_at']+self.config['delay_seconds']
            elif p['attempts']['0']['fill']:due=p['attempts']['0']['recorded_at']+self.config['pair_leg_delay_seconds']
            else:return True
            if due-now<=horizon:return True
        return False

    def tick(self):
        # Delayed fills are time-critical: run them first, and defer slow network housekeeping
        # (discovery, resolution) while one is pending. Entries close 70 s before window end,
        # so a pending fill never overlaps the next window's discovery.
        now=self.clock();self.journal.refresh_day(now);self.attempts(now)
        if not self.attempt_due_soon(self.clock()):self.discover(self.clock())
        self.sample(self.clock());self.attempts(self.clock());self.decide(self.clock());self.attempts(self.clock())
        if not self.attempt_due_soon(self.clock()):self.resolve(self.clock())
        self.reconcile(self.clock())
        if self.clock()-self.last_status>=5:self.last_status=self.clock();self.status(self.last_status)

    def close(self):
        for feed in self.feeds.values():
            if self.running_feeds:feed.close()
        if self.running_feeds:
            self.exchange.close();self.reference.close()
        self.capture.close();self.journal.close();self.db.close()


def main():
    from release import bundle
    p=argparse.ArgumentParser();p.add_argument('--state',required=True);p.add_argument('--expected-sha256',required=True);p.add_argument('--seconds',type=int,default=0);p.add_argument('--device',type=int,required=True);a=p.parse_args()
    if os.geteuid()==0:raise ValueError('run_under_existing_engineering_account')
    if a.expected_sha256!=bundle():raise ValueError('reviewed_bundle_mismatch')
    os.umask(0o077);state=Path(a.state)
    if not state.is_absolute() or state.is_symlink():raise ValueError('invalid_state_path')
    if not state.parent.is_dir() or state.parent.stat().st_dev!=a.device:raise ValueError('capture_volume_missing_or_changed_no_root_fallback')
    state.mkdir(mode=0o700,exist_ok=True)
    if state.stat().st_dev!=a.device:raise ValueError('wrong_state_device')
    stop=False
    def shutdown(*_):
        nonlocal stop;stop=True
    signal.signal(signal.SIGTERM,shutdown);signal.signal(signal.SIGINT,shutdown)
    with (state/'worker.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        study=Study(state,bundle());started=time.monotonic()
        try:
            while not stop and (not a.seconds or time.monotonic()-started<a.seconds):study.tick();time.sleep(.2)
        finally:
            study.status(time.time());study.close()

if __name__=='__main__':main()
