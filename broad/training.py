"""Chronological, contract-disjoint quote-risk study; never activates live orders."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import random
import time
from engine import Store, PLAN_HASH, atomic, features, canonical

FEATURES=['spread','imbalance','log_depth','midpoint','log_seconds_remaining','fee_rate','gross_pair_edge']

def sigmoid(x):
    return 1/(1+math.exp(-max(-40,min(40,x))))

def predict(model,x):
    z=[(a-b)/c for a,b,c in zip(x,model['mean'],model['scale'])]
    p=sigmoid(model['intercept']+sum(a*b for a,b in zip(z,model['coef'])))
    cal=model.get('calibration')
    if cal:
        l=math.log(max(1e-9,p)/max(1e-9,1-p))
        p=sigmoid(cal['intercept']+cal['coef']*l)
    return p

def metrics(ps,ys):
    if not ys: raise ValueError('Empty evaluation')
    return {'brier':sum((p-y)**2 for p,y in zip(ps,ys))/len(ys),
            'log_loss':-sum(y*math.log(max(1e-9,p))+(1-y)*math.log(max(1e-9,1-p)) for p,y in zip(ps,ys))/len(ys)}

def dataset(store):
    return [{'condition':c,'minute':mi,'ts':ts,'snapshot':json.loads(s),'target_ts':target,
             'target_json':targets}
            for c,mi,ts,s,target,targets in store.db.execute('''SELECT o.condition,o.minute,o.ts,o.payload,l.target_ts,l.adverse
            FROM observations o JOIN labels l ON o.condition=l.condition AND o.minute=l.minute ORDER BY o.ts''')]

def partition(rows):
    first={}
    for r in rows:first.setdefault(r['condition'],r['ts'])
    markets=sorted(first,key=lambda c:(first[c],c)); n=len(markets)
    a,b=int(n*.6),int(n*.8)
    if not 0<a<b<n:raise ValueError('Insufficient distinct markets')
    groups=[set(markets[:a]),set(markets[a:b]),set(markets[b:])]
    cut1,cut2=first[markets[a]],first[markets[b]]
    parts=[[r for r in rows if r['condition'] in g and (i==2 or r['ts']<(cut1 if i==0 else cut2)-90)] for i,g in enumerate(groups)]
    return parts

def readiness(store,now=None):
    now=time.time() if now is None else now
    start=float(store.db.execute("SELECT value FROM settings WHERE key='started'").fetchone()[0])
    rows=dataset(store); contracts=len({r['condition'] for r in rows}); reasons=[]
    if now-start<14*86400:reasons.append('14_prospective_days_incomplete')
    if len(rows)<2000:reasons.append('fewer_than_2000_labelled_market_minutes')
    if contracts<200:reasons.append('fewer_than_200_distinct_contracts')
    return {'ready':not reasons,'reasons':reasons,'examples':len(rows),'contracts':contracts,
            'earliest_training':datetime.fromtimestamp(start+14*86400,timezone.utc).isoformat(),
            'plan_hash':PLAN_HASH,'live_execution':False,'automatic_promotion':False}

def evaluate(rows,output):
    """Only called after readiness; synthetic test harness uses separate in-memory rows."""
    import numpy as np
    from sklearn.preprocessing import StandardScaler
    from sklearn.linear_model import LogisticRegression
    train,cal,test=partition(rows)
    if min(map(len,[train,cal,test]))<100:raise ValueError('Phase support insufficient after temporal purge')
    def xs(rs):return [features(r['snapshot'],i) for r in rs for i in (0,1)]
    def ys(rs):return [y for r in rs for y in json.loads(r['target_json'])]
    xt,xc,xv=xs(train),xs(cal),xs(test); yt,yc=ys(train),ys(cal)
    if min(sum(yt),len(yt)-sum(yt),sum(yc),len(yc)-sum(yc))<30:raise ValueError('Training/calibration class support insufficient')
    scaler=StandardScaler().fit(xt)
    fit=LogisticRegression(C=1,max_iter=1000,random_state=20261014).fit(scaler.transform(xt),yt)
    cp=fit.predict_proba(scaler.transform(xc))[:,1]
    log=lambda ps:np.array([[math.log(max(1e-9,p)/max(1e-9,1-p))] for p in ps])
    calibrator=LogisticRegression(C=1,max_iter=1000,random_state=20261014).fit(log(cp),yc)
    raw=fit.predict_proba(scaler.transform(xv))[:,1]
    ps=calibrator.predict_proba(log(raw))[:,1].tolist()
    spread=LogisticRegression(C=1,max_iter=1000,random_state=20261014).fit(np.array(xt)[:,[0]],yt)
    spread_ps=spread.predict_proba(np.array(xv)[:,[0]])[:,1].tolist()
    base=sum(yt)/len(yt)
    predictions={'model':ps,'empirical_rate':[base]*len(ps),
                 'majority':[.999 if base>=.5 else .001]*len(ps),'spread_baseline':spread_ps}
    frozen={'plan_hash':PLAN_HASH,'contracts':[r['condition'] for r in test],
            'minutes':[r['minute'] for r in test],'predictions':predictions}
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    atomic(output/'test_predictions.json',frozen)
    prediction_hash=hashlib.sha256((output/'test_predictions.json').read_bytes()).hexdigest()
    # First test-target extraction occurs only after predictions are durable.
    yv=ys(test)
    portable={'schema':'quote_risk_logistic.v1','plan_hash':PLAN_HASH,'features':FEATURES,
              'mean':scaler.mean_.tolist(),'scale':scaler.scale_.tolist(),
              'coef':fit.coef_[0].tolist(),'intercept':float(fit.intercept_[0]),
              'calibration':{'coef':float(calibrator.coef_[0][0]),'intercept':float(calibrator.intercept_[0])},
              'automatic_promotion':False,'event_forecaster':False,'edge_validated':False}
    atomic(output/'model.json',portable)
    groups={}
    for i,r in enumerate(test):groups.setdefault(r['condition'],[]).extend([i*2,i*2+1])
    improvement=[sum((predictions['empirical_rate'][i]-yv[i])**2-(ps[i]-yv[i])**2 for i in ids)/len(ids) for ids in groups.values()]
    rng=random.Random(20261014)
    samples=sorted(sum(rng.choice(improvement) for _ in improvement)/len(improvement) for _ in range(2000))
    bins=[]
    for b in range(10):
        ids=[i for i,p in enumerate(ps) if min(9,int(p*10))==b]
        bins.append({'lower':b/10,'count':len(ids),'predicted':sum(ps[i] for i in ids)/len(ids) if ids else None,
                     'observed':sum(yv[i] for i in ids)/len(ids) if ids else None})
    result={'trained':True,'phase_examples':[len(x) for x in (train,cal,test)],
            'phase_contracts':[len({r['condition'] for r in x}) for x in (train,cal,test)],
            'test_classes':{'adverse':sum(yv),'nonadverse':len(yv)-sum(yv)},
            'metrics':{k:metrics(v,yv) for k,v in predictions.items()},'reliability':bins,
            'brier_improvement_market_bootstrap_95':[samples[49],samples[1949]],
            'predictions_sha256':prediction_hash,'model_sha256':hashlib.sha256((output/'model.json').read_bytes()).hexdigest(),
            'plan_hash':PLAN_HASH,'live_execution':False,'automatic_promotion':False,'edge_validated':False,
            'note':'Quote-risk prediction is not demonstrated trading profitability.'}
    atomic(output/'evaluation.json',result);return result

def train(store):
    out=store.root/'training';out.mkdir(exist_ok=True)
    gate=readiness(store);atomic(out/'readiness.json',gate)
    if (out/'evaluation.json').exists():return {'trained':False,'reason':'holdout_already_consumed','gate':gate}
    if not gate['ready']:return {'trained':False,'gate':gate}
    # Atomically consume test once; failed evaluations are visible and cannot silently retry.
    marker=out/'HOLDOUT_CONSUMED'
    with open(marker,'x') as f:f.write(PLAN_HASH)
    return evaluate(dataset(store),out)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--state-dir',required=True);a=p.parse_args()
    print(canonical(train(Store(a.state_dir))))
