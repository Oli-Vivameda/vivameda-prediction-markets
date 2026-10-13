"""Disposable synthetic pipeline acceptance, never real study outcomes."""
import hashlib,json,os,random,tempfile
from pathlib import Path
for k in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS'):os.environ[k]='1'
from agent import Journal
from training import PLAN,epoch,run_study

def main():
    rng=random.Random(123)
    with tempfile.TemporaryDirectory() as t:
        j=Journal(Path(t)/'j.db');rows=[];start=epoch(PLAN['start'])
        for i in range(4032):
            now=start+i*300+120;winner='Up' if rng.random()<.5 else 'Down';p=.4+.2*rng.random()
            books={s:{'bids':[{'price':'.49','size':'100'}],'asks':[{'price':'.51','size':'100'}]} for s in ('Up','Down')}
            d={'id':i+1,'kind':'shadow_decision','strategy':'btc5m-fixed180-delay-v3','condition_id':str(i),'decision_time':now,'recorded_at':now,'end_epoch':now+180,'books':books,'quotes':{s:{'break_even_probability':.52} for s in books},'prediction':{'p_up':p,'sigma_dollars_sqrt_second':5,'remaining_seconds':180,'distance_dollars':rng.random()*10,'momentum_up':i%2},'fee_rate':.07,'fee_exponent':1}
            rows.append(d);rows.append({'kind':'market_resolution','condition_id':str(i),'winner':winner,'recorded_at':now+200})
        # Supply synthetic rows directly; avoid changing Journal or source and never retain label files.
        from unittest.mock import patch
        with patch.object(Journal,'rows',return_value=rows):result=run_study(j.path,Path(t)/'research',epoch(PLAN['end'])+3600)
        assert result['trained'] and not result['automatic_promotion'] and not result['live_execution']
        assert set(result['metrics'])=={'logistic','boosted_tree','baseline','market','momentum'}
        assert all(len(b)==10 for b in result['reliability_bins'].values())
        assert all(a['0.25']['fills']==0 for a in result['economics'].values())
        sha=hashlib.sha256((Path(t)/'research/test-predictions.json').read_bytes()).hexdigest()
        assert sha==result['predictions_sha256']
        with patch.object(Journal,'rows',return_value=rows):assert run_study(j.path,Path(t)/'research',epoch(PLAN['end'])+3600)['reason']=='frozen_study_already_evaluated'
        print(json.dumps({'synthetic_only':True,'pipeline_passed':True,'phase_counts':result['phase_counts'],'sklearn_version':result['sklearn_version'],'numpy_version':result['numpy_version'],'real_training':False}))
if __name__=='__main__':main()
