"""Transparent TWAP-aware baseline and strictly chronological logistic fit interface."""
import math
import statistics
from common import number,digest

FEATURES=('normalized_distance','remaining_fraction','normalized_momentum','imbalance')
FINAL_FEATURES=('normalized_distance','remaining_of_final_minute','realized_fraction','imbalance')
FINAL_VERSION='final-minute-partial-twap.v1'

def partition(start,genesis,c):
    offset=(start-genesis)/86400
    if offset<0:return 'excluded'
    if offset<c['train_days']:return 'train'
    if offset<c['train_days']+c['calibration_days']:return 'calibration'
    if offset<c['train_days']+c['calibration_days']+c['selection_days']:return 'selection'
    if offset<sum(c[k] for k in ('train_days','calibration_days','selection_days','final_days')):return 'final'
    return 'after'

def predict(m,books,reference,anchor,now):
    if reference is None or anchor is None:raise ValueError('contractual_reference_or_opening_twap_unavailable')
    if (anchor['source']!=m['source'] or anchor['kind']!='chainlink_twap_60' or anchor['source_at']!=m['start']
        or anchor['received_at']>now):raise ValueError('unverified_opening_reference')
    remaining=m['end']-now
    if remaining<=60:raise ValueError('inside_final_averaging_window')
    points=reference['points']
    if reference.get('kind')!='verified_chainlink_raw' or reference.get('twap_source')!=m['source']:
        raise ValueError('wrong_contractual_reference_source')
    if any(p['source_at']>now or p['received_at']>now or p['received_at']<p['source_at']-1 for p in points):raise ValueError('future_input_timestamp')
    recent=[p for p in points if now-180<=p['source_at']<=now]
    if len(recent)<30 or recent[-1]['source_at']-recent[0]['source_at']<90:raise ValueError('reference_warmup')
    times=[p['source_at'] for p in recent]
    if any(not 0<b-a<=5 for a,b in zip(times,times[1:])) or not 0<=now-recent[-1]['received_at']<=3 or not 0<=now-times[-1]<=3:
        raise ValueError('reference_gap_or_stale')
    values=[float(number(p['price'])) for p in recent];opening=float(number(anchor['price']))
    if min(values+[opening])<=0:raise ValueError('nonpositive_reference')
    sigma=math.sqrt(sum((b-a)**2 for a,b in zip(values,values[1:]))/(times[-1]-times[0]))
    if not sigma>0:raise ValueError('zero_volatility')
    sd=sigma*math.sqrt(remaining-40);z=(values[-1]-opening)/sd
    cutoff=now-30;prior=next((p for p in reversed(recent) if p['source_at']<=cutoff),None)
    if prior is None:raise ValueError('missing_momentum_history')
    momentum=(values[-1]-float(number(prior['price'])))/(sigma*math.sqrt(30))
    b=books['Up'];bv=sum(float(number(n)) for p,n in b['bids'][:5]);av=sum(float(number(n)) for p,n in b['asks'][:5])
    imbalance=(bv-av)/(bv+av)
    mids={s:(float(number(books[s]['asks'][0][0]))+float(number(books[s]['bids'][0][0])))/2 for s in ('Up','Down')}
    return {'p_up':min(.99,max(.01,.5*(1+math.erf(z/math.sqrt(2))))),'market_p_up':mids['Up']/sum(mids.values()),
        'features':[z,remaining/300,momentum,imbalance],'feature_names':FEATURES,'version':'arithmetic-brownian-final60.v1',
        'calibrated':False,'reference_at':times[-1],'reference_received_at':recent[-1]['received_at'],
        'opening_reference_at':anchor['source_at'],'observed_at':now,'reference_price':values[-1],
        'opening_reference':opening,'sigma':sigma,'remaining':remaining}

def sigmoid(z):return 1/(1+math.exp(-max(-30,min(30,z))))
def optimize(xs,ys,iterations=600):
    coef=[0.]*(len(xs[0])+1)
    for _ in range(iterations):
        gradient=[0.]*len(coef)
        for x,y in zip(xs,ys):
            x=[1.]+x;error=sigmoid(sum(a*b for a,b in zip(coef,x)))-y
            for j,v in enumerate(x):gradient[j]+=error*v/len(xs)
        coef=[v-.1*(g+(.01*v if j else 0)) for j,(v,g) in enumerate(zip(coef,gradient))]
    return coef

def fit(rows,asset,genesis,c,now):
    """Explicit offline operation only. Never reads final-period targets into fitting."""
    cutoff=genesis+c['train_days']*86400;cal_end=cutoff+c['calibration_days']*86400
    if now<cal_end:raise ValueError('chronological_training_gate_not_due')
    train=[];cal=[];seen=set()
    for r in rows:
        if r['asset']!=asset:continue
        split=partition(r['start'],genesis,c)
        if split not in ('train','calibration'):continue
        if (r['start']%300 or r['end']!=r['start']+300 or not r['start']<=r['observed_at']<r['end']
            or r['outcome_available_at']<=r['end']):raise ValueError('invalid_training_chronology')
        boundary=cutoff if split=='train' else cal_end
        # Gap and settled-label availability precede each fitting boundary.
        if r['end']>=boundary-300 or r['outcome_available_at']>boundary or r['observed_at']>=r['end']:
            continue
        if r['input_max_received_at']>r['observed_at'] or r['input_max_source_at']>r['observed_at']:raise ValueError('training_timestamp_leakage')
        identity=(r['asset'],r['start'])
        if identity in seen:raise ValueError('duplicate_training_window')
        seen.add(identity)
        if len(r['features'])!=4 or not all(math.isfinite(float(v)) for v in r['features']) or r['y'] not in (0,1):raise ValueError('invalid_training_row')
        (train if split=='train' else cal).append(r)
    if len(train)<c['minimum_training_windows_per_asset'] or len(cal)<100 or len({r['y'] for r in train})<2 or len({r['y'] for r in cal})<2:
        raise ValueError('insufficient_chronological_training_data')
    means=[statistics.mean(r['features'][j] for r in train) for j in range(4)]
    scales=[max(1e-8,statistics.pstdev(r['features'][j] for r in train)) for j in range(4)]
    transform=lambda r:[(v-a)/b for v,a,b in zip(r['features'],means,scales)]
    coef=optimize([transform(r) for r in train],[r['y'] for r in train])
    logits=[[sum(a*b for a,b in zip(coef,[1.]+transform(r))) ] for r in cal]
    calibration=optimize(logits,[r['y'] for r in cal])
    artifact={'version':'asset-logistic.v1','asset':asset,'means':means,'scales':scales,'coefficients':coef,
        'calibration':calibration,'training_cutoff':cutoff,'calibration_cutoff':cal_end,'training_windows':len(train),
        'calibration_windows':len(cal),'features':FEATURES,'input_rows_sha256':digest(train+cal),'automatic_promotion':False}
    return artifact


def step_average(points,start,end,max_step):
    """Time-weighted average of raw points as a step function over (start, end].

    Requires a point at or before start, and no moment in the interval may rely on a
    point older than max_step seconds. Returns (average, coverage_seconds, max_step_used).
    """
    if not end>start:raise ValueError('empty_averaging_interval')
    ordered=sorted(points,key=lambda p:p['source_at'])
    prior=[p for p in ordered if p['source_at']<=start]
    if not prior:raise ValueError('no_point_at_averaging_start')
    current=prior[-1];inside=[p for p in ordered if start<p['source_at']<=end]
    if start-current['source_at']>max_step:raise ValueError('reconstruction_gap')
    total=0.;cursor=start;worst=start-current['source_at']
    for p in inside:
        if p['source_at']-current['source_at']>max_step:raise ValueError('reconstruction_gap')
        worst=max(worst,p['source_at']-current['source_at'])
        total+=float(number(current['price']))*(p['source_at']-cursor);cursor=p['source_at'];current=p
    if end-current['source_at']>max_step:raise ValueError('reconstruction_gap')
    worst=max(worst,end-current['source_at'])
    total+=float(number(current['price']))*(end-cursor)
    return total/(end-start),end-start,worst

def predict_final(m,books,reference,anchor,now,c):
    """Partial-TWAP forecast inside the final averaging minute (preregistered)."""
    if reference is None or anchor is None:raise ValueError('contractual_reference_or_opening_twap_unavailable')
    if (anchor['source']!=m['source'] or anchor['kind']!='chainlink_twap_60' or anchor['source_at']!=m['start']
        or anchor['received_at']>now):raise ValueError('unverified_opening_reference')
    remaining=m['end']-now
    if not c['final_minute_min_remaining']<=remaining<=c['final_minute_max_remaining']:raise ValueError('outside_final_minute_decision_window')
    points=reference['points']
    if reference.get('kind')!='verified_chainlink_raw' or reference.get('twap_source')!=m['source']:
        raise ValueError('wrong_contractual_reference_source')
    if any(p['source_at']>now or p['received_at']>now or p['received_at']<p['source_at']-1 for p in points):raise ValueError('future_input_timestamp')
    recent=[p for p in points if now-180<=p['source_at']<=now]
    if len(recent)<30 or recent[-1]['source_at']-recent[0]['source_at']<90:raise ValueError('reference_warmup')
    times=[p['source_at'] for p in recent]
    if any(not 0<b-a<=5 for a,b in zip(times,times[1:])) or not 0<=now-recent[-1]['received_at']<=3 or not 0<=now-times[-1]<=3:
        raise ValueError('reference_gap_or_stale')
    values=[float(number(p['price'])) for p in recent];opening=float(number(anchor['price']))
    if min(values+[opening])<=0:raise ValueError('nonpositive_reference')
    sigma=math.sqrt(sum((b-a)**2 for a,b in zip(values,values[1:]))/(times[-1]-times[0]))
    if not sigma>0:raise ValueError('zero_volatility')
    window_start=m['end']-60;elapsed=now-window_start
    realized,_,worst=step_average(recent,window_start,now,c['reconstruction_max_step_seconds'])
    latest=values[-1];mean=(elapsed*realized+remaining*latest)/60
    def probability(s):
        sd=s*remaining**1.5/(60*math.sqrt(3));return min(.99,max(.01,.5*(1+math.erf((mean-opening)/sd/math.sqrt(2))))),sd
    p_up,sd=probability(sigma);shadow,_=probability(sigma*float(number(c['shadow_sigma_multiplier'])))
    b=books['Up'];bv=sum(float(number(n)) for p,n in b['bids'][:5]);av=sum(float(number(n)) for p,n in b['asks'][:5])
    imbalance=(bv-av)/(bv+av)
    mids={s:(float(number(books[s]['asks'][0][0]))+float(number(books[s]['bids'][0][0])))/2 for s in ('Up','Down')}
    return {'p_up':p_up,'p_up_shadow_fat_tail':shadow,'market_p_up':mids['Up']/sum(mids.values()),
        'features':[(mean-opening)/sd,remaining/60,elapsed/60,imbalance],'feature_names':FINAL_FEATURES,'version':FINAL_VERSION,
        'calibrated':False,'reference_at':times[-1],'reference_received_at':recent[-1]['received_at'],
        'opening_reference_at':anchor['source_at'],'observed_at':now,'reference_price':latest,'opening_reference':opening,
        'realized_twap_part':realized,'realized_seconds':elapsed,'expected_final_twap':mean,'final_twap_sd':sd,
        'reconstruction_max_step':worst,'sigma':sigma,'remaining':remaining}
