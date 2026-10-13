"""Frozen chronological challenger study; no model activation or real orders."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
import math
from pathlib import Path
import random
import time
from operations import atomic_json

PLAN={'schema':'btc_challenger_study.v1','start':'2026-10-14T00:00:00Z',
      'train_end':'2026-10-22T00:00:00Z','calibration_end':'2026-10-25T00:00:00Z',
      'end':'2026-10-28T00:00:00Z','minimum_markets':1000,'minimum_coverage':.8,
      'boundary_gap_seconds':300,'feature_version':'fixed180-numeric-v1',
      'bootstrap_day_resamples':2000,'seed':20261013,'automatic_promotion':False}
PLAN_SHA=hashlib.sha256(json.dumps(PLAN,sort_keys=True).encode()).hexdigest()
FEATURES=('baseline_logit','market_probability','normalized_distance','remaining_seconds',
          'sigma','momentum','up_spread','down_spread','up_imbalance','down_imbalance',
          'up_break_even','down_break_even')


def epoch(s):return datetime.fromisoformat(s.replace('Z','+00:00')).timestamp()
def clip(p):return min(1-1e-8,max(1e-8,float(p)))
def logit(p):p=clip(p);return math.log(p/(1-p))


def features(d):
    p=d['prediction'];books=d['books'];qs=d['quotes'];mids={};spreads={};imb={}
    for side in ('Up','Down'):
        b=books[side]
        bids=sorted(b['bids'],key=lambda x:float(x['price']),reverse=True)
        asks=sorted(b['asks'],key=lambda x:float(x['price']))
        bid,ask=float(bids[0]['price']),float(asks[0]['price'])
        if not 0<bid<=ask<1:raise ValueError('Invalid decision benchmark')
        mids[side]=(bid+ask)/2;spreads[side]=ask-bid
        bv=sum(float(x['size']) for x in bids[:5]);av=sum(float(x['size']) for x in asks[:5])
        if bv+av<=0:raise ValueError('Missing decision depth')
        imb[side]=(bv-av)/(bv+av)
    sd=p['sigma_dollars_sqrt_second']*math.sqrt(p['remaining_seconds']-40)
    if sd<=0:raise ValueError('Invalid decision volatility')
    x=[logit(p['p_up']),mids['Up']/sum(mids.values()),p['distance_dollars']/sd,
       p['remaining_seconds'],p['sigma_dollars_sqrt_second'],int(p['momentum_up']),
       spreads['Up'],spreads['Down'],imb['Up'],imb['Down'],
       qs['Up']['break_even_probability'],qs['Down']['break_even_probability']]
    if not all(math.isfinite(float(v)) for v in x):raise ValueError('Nonfinite features')
    return x


def decision_cohort(rows):
    start,end=epoch(PLAN['start']),epoch(PLAN['end']);cohort={}
    excluded=0
    for d in rows:
        if d['kind']!='shadow_decision' or not start<=d.get('decision_time',0)<end:continue
        if d.get('strategy')!='btc5m-fixed180-delay-v3':continue
        try:
            if not 175<=d['end_epoch']-d['decision_time']<=180:raise ValueError('Decision outside frozen window')
            if d['recorded_at']>=d['end_epoch']:raise ValueError('Post-deadline observation')
            x=features(d)
        except (ValueError,KeyError,TypeError,IndexError):excluded+=1;continue
        cohort.setdefault(d['condition_id'],{**d,'x':x})
    return sorted(cohort.values(),key=lambda d:d['decision_time']),excluded


def readiness(rows,now=None):
    now=time.time() if now is None else now
    ds,excluded=decision_cohort(rows)
    resolved={r['condition_id'] for r in rows if r['kind']=='market_resolution'}
    eligible=[d for d in ds if d['condition_id'] in resolved]
    expected=int((epoch(PLAN['end'])-epoch(PLAN['start']))/300)
    reasons=[]
    if now<epoch(PLAN['end']):reasons.append('registered_14_full_days_not_complete')
    if len(eligible)<PLAN['minimum_markets']:reasons.append('fewer_than_1000_eligible_resolved_markets')
    if len(eligible)<PLAN['minimum_coverage']*expected:reasons.append('registered_window_coverage_below_80_percent')
    return {'ready':not reasons,'reasons':reasons,'eligible_resolved_markets':len(eligible),
            'eligible_observations':len(ds),'excluded_incomplete':excluded,'expected_markets':expected,
            'earliest_training':PLAN['end'],'plan_sha256':PLAN_SHA,'automatic_promotion':False}


def split_days(decisions):
    a,b,end=epoch(PLAN['train_end']),epoch(PLAN['calibration_end']),epoch(PLAN['end'])
    gap=PLAN['boundary_gap_seconds']
    train=[d for d in decisions if d['end_epoch']<a-gap]
    cal=[d for d in decisions if a+gap<=d['decision_time'] and d['end_epoch']<b-gap]
    test=[d for d in decisions if b+gap<=d['decision_time'] and d['end_epoch']<end]
    return train,cal,test


def score(ps,ys):
    return {'brier':sum((p-y)**2 for p,y in zip(ps,ys))/len(ys),
            'log_loss':-sum(y*math.log(clip(p))+(1-y)*math.log(1-clip(p)) for p,y in zip(ps,ys))/len(ys)}


def replay(decisions,probabilities,rows,outcomes,delay):
    from agent import fill
    probes={(r['decision_id'],r['delay_seconds']):r for r in rows if r['kind']=='shadow_quote_probe'}
    cash=1000.;positions=[];trades=[];missed=0;unobservable=0;losses={}
    for d,p in zip(decisions,probabilities):
        now=d['decision_time'];day=datetime.fromtimestamp(now,timezone.utc).date().isoformat()
        for position in positions[:]:
            outcome=outcomes[position['condition']]
            if outcome['recorded_at']<=now:
                payout=position['shares'] if position['side']==outcome['winner'] else 0.
                cash+=payout
                settlement_day=datetime.fromtimestamp(outcome['recorded_at'],timezone.utc).date().isoformat()
                losses[settlement_day]=losses.get(settlement_day,0)+max(0,position['total']-payout)
                positions.remove(position)
        qs=d['quotes'];pr={'Up':p,'Down':1-p}
        side=max(qs,key=lambda s:pr[s]-qs[s]['break_even_probability'])
        if pr[side]-qs[side]['break_even_probability']<.05:continue
        if cash<5 or sum(t['total'] for t in positions)+5>50 or losses.get(day,0)>=20:continue
        probe=probes.get((d['id'],delay))
        if not probe or not probe.get('available'):unobservable+=1;continue
        try:
            if not delay<=probe['actual_delay_seconds']<=delay+1:raise ValueError('Late probe')
            book=probe['books'][side]
            if book['received_mono_ns']/1e9<probe['due_mono']:raise ValueError('No post-delay arrival')
            q=fill(book,5,d['fee_rate'],d['fee_exponent'])
            if q['break_even_probability']>min(.999,qs[side]['break_even_probability']+.02):raise ValueError('Adverse price')
        except (ValueError,KeyError,TypeError):missed+=1;continue
        cash-=q['total'];positions.append({'condition':d['condition_id'],'side':side,**q})
        outcome=outcomes[d['condition_id']]
        profit=(q['shares'] if side==outcome['winner'] else 0)-q['total']
        trades.append(profit)
    return {'fills':len(trades),'missed_fills':missed,'unobservable_opportunities':unobservable,
            'total_net_profit':sum(trades),'mean_net_profit':sum(trades)/len(trades) if trades else None,
            'note':'Top20 delayed-depth counterfactual; unobservable opportunities excluded, never assumed filled.'}


def run_study(journal,output,now=None):
    from agent import Journal
    rows=Journal(journal).rows();gate=readiness(rows,now);output=Path(output);output.mkdir(parents=True,exist_ok=True)
    atomic_json(output/'readiness.json',gate)
    if not gate['ready']:return {'trained':False,**gate}
    if (output/'evaluation.json').exists():return {'trained':False,'reason':'frozen_study_already_evaluated'}
    import numpy as np
    import sklearn
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    from sklearn.linear_model import LogisticRegression
    from sklearn.ensemble import HistGradientBoostingClassifier
    import joblib
    decisions,_=decision_cohort(rows);outcomes={r['condition_id']:r for r in rows if r['kind']=='market_resolution'}
    decisions=[d for d in decisions if d['condition_id'] in outcomes]
    train,cal,test=split_days(decisions)
    def y(ds):return np.array([int(outcomes[d['condition_id']]['winner']=='Up') for d in ds])
    yt,yc=y(train),y(cal)
    if min(len(train),len(cal),len(test))<100 or min(sum(yt),len(yt)-sum(yt),sum(yc),len(yc)-sum(yc))<30:
        return {'trained':False,'reason':'insufficient_phase_or_class_support'}
    models={'logistic':make_pipeline(StandardScaler(),LogisticRegression(C=1,max_iter=1000,random_state=20261013)),
            'boosted_tree':HistGradientBoostingClassifier(max_depth=3,max_iter=100,learning_rate=.05,
                       l2_regularization=.01,min_samples_leaf=20,early_stopping=False,random_state=20261013)}
    predictions={};artifacts={}
    for name,model in models.items():
        model.fit(np.array([d['x'] for d in train]),yt)
        cp=model.predict_proba(np.array([d['x'] for d in cal]))[:,1]
        calibrator=LogisticRegression(C=1e6,max_iter=1000,random_state=20261013).fit(
            np.array([[logit(p)] for p in cp]),yc)
        tp=model.predict_proba(np.array([d['x'] for d in test]))[:,1]
        predictions[name]=calibrator.predict_proba(np.array([[logit(p)] for p in tp]))[:,1].tolist()
        joblib.dump({'model':model,'calibrator':calibrator,'features':FEATURES,'plan':PLAN},output/(name+'.joblib'))
        artifacts[name]=hashlib.sha256((output/(name+'.joblib')).read_bytes()).hexdigest()
    predictions['baseline']=[d['prediction']['p_up'] for d in test]
    predictions['market']=[d['x'][1] for d in test]
    predictions['momentum']=[.75 if d['prediction']['momentum_up'] else .25 for d in test]
    frozen={'plan_sha256':PLAN_SHA,'conditions':[d['condition_id'] for d in test],'predictions':predictions}
    # Persist/hash predictions before extracting the test targets.
    atomic_json(output/'test-predictions.json',frozen)
    pred_sha=hashlib.sha256((output/'test-predictions.json').read_bytes()).hexdigest()
    ys=y(test).tolist()
    metrics={n:score(ps,ys) for n,ps in predictions.items()}
    reliability={}
    for name,ps in predictions.items():
        bins=[]
        for b in range(10):
            ids=[i for i,p in enumerate(ps) if min(9,int(p*10))==b]
            bins.append({'lower':b/10,'count':len(ids),'mean_prediction':sum(ps[i] for i in ids)/len(ids) if ids else None,'observed_up_fraction':sum(ys[i] for i in ids)/len(ids) if ids else None})
        reliability[name]=bins
    economics={n:{str(delay):replay(test,ps,rows,outcomes,delay) for delay in (.25,2.)} for n,ps in predictions.items()}
    days=sorted({datetime.fromtimestamp(d['decision_time'],timezone.utc).date().isoformat() for d in test})
    intervals={}
    for name in models:
        per_day=[]
        for day in days:
            indices=[i for i,d in enumerate(test) if datetime.fromtimestamp(d['decision_time'],timezone.utc).date().isoformat()==day]
            per_day.append(sum((predictions['baseline'][i]-ys[i])**2-(predictions[name][i]-ys[i])**2 for i in indices)/len(indices))
        rng=random.Random(PLAN['seed']);samples=sorted(sum(rng.choice(per_day) for _ in per_day)/len(per_day) for _ in range(2000))
        intervals[name]={'brier_improvement_day_bootstrap_95':[samples[49],samples[1949]],'test_days':len(days),
                         'note':'Few held-out days limit uncertainty inference; this is not a promotion certificate.'}
    result={'trained':True,'phase_counts':{'train':len(train),'calibration':len(cal),'test':len(test)},
            'plan':PLAN,'plan_sha256':PLAN_SHA,'predictions_sha256':pred_sha,'model_artifact_hashes':artifacts,
            'sklearn_version':sklearn.__version__,'numpy_version':np.__version__,'metrics':metrics,
            'reliability_bins':reliability,'economics':economics,'uncertainty':intervals,'automatic_promotion':False,'live_execution':False,
            'edge_validated':False,'github_sync':'pending_owner_connector'}
    atomic_json(output/'evaluation.json',result);return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--journal',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();print(json.dumps(run_study(a.journal,a.output)))
