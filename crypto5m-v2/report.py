"""Read-only reproducible reporting; final-period results remain withheld until due."""
import argparse
import json
import random
import sqlite3
import time
from pathlib import Path
from common import D,number,digest,config
from ledger import Ledger,portfolio
import model


def scores(rows):
    if not rows:return {'n':0,'brier':None,'calibration':[]}
    bins=[]
    for band in range(10):
        selected=[(p,y) for p,y in rows if min(9,int(p*10))==band]
        if selected:bins.append({'band':band,'n':len(selected),'mean_prediction':sum(p for p,y in selected)/len(selected),'observed_up_rate':sum(y for p,y in selected)/len(selected)})
    return {'n':len(rows),'brier':sum((p-y)**2 for p,y in rows)/len(rows),'calibration':bins}


def cluster_interval(rows,resamples=2000):
    days={}
    for day,value in rows:days.setdefault(day,[]).append(value)
    if len(days)<10:return {'available':False,'reason':'fewer_than_ten_UTC_day_blocks','day_blocks':len(days)}
    rng=random.Random(20261016);keys=list(days);stats=[]
    for _ in range(resamples):
        sample=[v for key in rng.choices(keys,k=len(keys)) for v in days[key]];stats.append(sum(sample)/len(sample))
    stats.sort();return {'available':True,'day_blocks':len(days),'resamples':resamples,'mean_market_pnl_95_interval':[stats[int(.025*resamples)],stats[int(.975*resamples)]],'unit':'UTC-day block, all assets/strategies together'}


def build(state,now=None):
    now=time.time() if now is None else now;state=Path(state)
    with sqlite3.connect('file:'+str(state/'ledger.sqlite3')+'?mode=ro',uri=True) as db:
        row=db.execute("SELECT body FROM events WHERE kind='genesis'").fetchone()
        genesis=json.loads(row[0]);events=list(db.execute('SELECT event_key,kind,recorded,body,prior,sha FROM events ORDER BY id'))
    c=genesis['config'];started=genesis['started_at'];end=started+sum(c[k] for k in ('train_days','calibration_days','selection_days','final_days'))*86400
    final_released=now>=end;first={};outcomes={};observed=0;skips={}
    with sqlite3.connect('file:'+str(state/'index.sqlite3')+'?mode=ro',uri=True) as db:
        for condition,raw,sha in db.execute('SELECT condition,body,sha FROM outcomes'):
            v=json.loads(raw)
            if digest(v)!=sha:raise ValueError('outcome_integrity')
            outcomes[condition]=v
        for raw,sha in db.execute('SELECT body,sha FROM observations ORDER BY rowid'):
            v=json.loads(raw)
            if digest(v)!=sha:raise ValueError('observation_integrity')
            observed+=1
            for name,reason in v['decisions'].items():skips[name+':'+reason]=skips.get(name+':'+reason,0)+1
            if v['split']=='final' and not final_released:continue
            if v['split']=='excluded':continue
            if v['market_probability'] is not None:first.setdefault(v['condition'],v)
    probabilities={'market':[],'baseline':[]};by_asset={};coverage=[]
    for condition,v in first.items():
        o=outcomes.get(condition)
        if not o or o['confirmed_at']<=v['observed_at'] or v['observed_at']>=v['end']:continue
        y=int(o['winner']=='Up');probabilities['market'].append((v['market_probability'],y))
        by_asset.setdefault(v['asset'],[]).append((v['market_probability'],y))
        if v['model_prediction'] is not None:probabilities['baseline'].append((v['model_prediction']['p_up'],y))
    # Reconstruct using the ledger's actual schema without creating or writing anything.
    from ledger import empty,apply
    s=empty();equity_high=number(c['starting_cash']);maximum_drawdown=D(0);maximum_utilization=D(0)
    prior_hash='0'*64
    for event_key,kind,stamp,raw,prior,sha in events:
        if prior!=prior_hash or digest([prior,{'key':event_key,'kind':kind,'recorded':stamp,'body':json.loads(raw)}])!=sha:raise ValueError('report_ledger_integrity')
        prior_hash=sha
        if kind=='genesis':continue
        apply(s,kind,json.loads(raw),stamp,c);p=portfolio(s,c)
        equity_high=max(equity_high,p['equity_lower_bound']);maximum_drawdown=max(maximum_drawdown,equity_high-p['equity_lower_bound'])
        maximum_utilization=max(maximum_utilization,(p['reserved']+p['open_cost'])/number(c['starting_cash']))
    trades=[];total_fees=total_extra=D(0);unmatched=D(0)
    for key,p in s['positions'].items():
        fills=[a['fill'] for a in p['attempts'].values() if a['fill']]
        total_fees+=sum((number(f['fees']) for f in fills),D(0));total_extra+=sum((number(f['additional']) for f in fills),D(0))
        if p['strategy']=='paired':
            qty={side:sum((number(a['fill']['shares']) for leg,a in p['attempts'].items() if a['fill'] and p['plans'][int(leg)]['side']==side),D(0)) for side in ('Up','Down')}
            if key not in s['credits']:unmatched+=abs(qty['Up']-qty['Down'])
        split=model.partition(p['market']['start'],started,c)
        if split=='final' and not final_released:continue
        if key not in s['credits']:continue
        cost=sum((number(f['total']) for f in fills),D(0));pnl=number(s['credits'][key])-cost
        shares=sum((number(f['shares']) for f in fills),D(0));principal=sum((number(f['principal']) for f in fills),D(0))
        trades.append({'asset':p['market']['asset'],'condition':p['market']['condition'],'strategy':p['strategy'],
            'start':p['market']['start'],'remaining_band':int((p['market']['end']-p['created_at'])//60),
            'entry_price_band':int((principal/shares if shares else 0)*10),'pnl':float(pnl),'shares':float(shares),'partial_fills':sum(f['partial'] for f in fills)})
    market_pnl={}
    for t in trades:market_pnl[t['condition']]=market_pnl.get(t['condition'],0)+t['pnl']
    winners=sorted([(k,v) for k,v in market_pnl.items() if v>0],key=lambda x:x[1],reverse=True)[:5]
    groups={}
    for field in ('asset','strategy','remaining_band','entry_price_band'):
        groups[field]={}
        for t in trades:
            key=str(t[field]);g=groups[field].setdefault(key,{'settled_positions':0,'net_pnl':0.,'partial_fills':0})
            g['settled_positions']+=1;g['net_pnl']+=t['pnl'];g['partial_fills']+=t['partial_fills']
    status=json.loads((state/'status.json').read_text()) if (state/'status.json').exists() else {}
    return {'stage':'collecting data—no validated edge','live_execution':False,'edge_validated':False,
        'observations':observed,'unique_markets_with_price':len(first),'official_outcomes':len(outcomes),
        'predictions':len(probabilities['baseline']),'scores':{k:scores(v) for k,v in probabilities.items()},
        'market_scores_by_asset':{a:scores(v) for a,v in by_asset.items()},'decision_reasons':skips,
        'net_settled_pnl':sum(t['pnl'] for t in trades),'fees_all_periods':str(total_fees),'additional_costs_all_periods':str(total_extra),
        'maximum_equity_drawdown_lower_bound_all_periods':str(maximum_drawdown),'maximum_capital_utilization_all_periods':str(maximum_utilization),
        'unmatched_open_pair_shares':str(unmatched),'unwind_losses':'0; policy holds bounded unmatched shares to settlement',
        'net_pnl_without_five_largest_winning_markets':sum(market_pnl.values())-sum(v for k,v in winners),
        'uncertainty':cluster_interval([(int(t['start'])//86400,t['pnl']) for t in trades]),'breakdown':groups,
        'sensitivity':{'extra_one_cent_per_share':sum(t['pnl']-.01*t['shares'] for t in trades),
            'worst_case_zero_payout_on_recorded_positions':str(-sum((sum((number(a['fill']['total']) for a in p['attempts'].values() if a['fill']),D(0)) for p in s['positions'].values()),D(0))),
            'worse_latency_and_alternate_fills':'not estimable yet; alternative-delay book observations must be replayed, never invented'},
        'capture_health':status.get('capture'),'feed_health':status.get('book_feeds'),
        'holdout':{'final_released':final_released,'release_after':end,'final_scores_withheld':not final_released},
        'limits':['Public legacy Chainlink snapshot adapter is a retiring dependency; operational forecasts require fresh contiguous raw points and exact opening TWAP.',
            'One-second states preserve decision inputs, not every raw exchange or book tick.',
            'No out-of-sample advantage or real-fill guarantee; spread/depth/fee costs are explicit.']}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--state',required=True);a=p.parse_args();print(json.dumps(build(a.state),sort_keys=True,indent=2))
