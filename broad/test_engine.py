import copy
import json
from pathlib import Path
import tempfile
import time
import unittest
from engine import metadata, book, paired, sweep, Store, payoff_check, features, PLAN_HASH, deadline_precision, epoch
from training import readiness, partition, evaluate, predict

def snapshot(now=1000000, condition=None, asks=('.47','.50'), rate='0'):
    c=condition or '0x'+'1'*64
    m={'condition':c,'slug':'example','question':'Example?', 'description':'Rules',
       'rule_hash':'rules','assets':['1','2'],'labels':['Yes','No'],'end':now+86400,
       'fee_rate':rate,'minimum':'5','tick':'.01','received':now,'protocol':'v1'}
    bs=[{'asset':a,'condition':c,'timestamp':now,'received':now,
         'bids':[[str(float(p)-.02),'100']], 'asks':[[p,'100']]} for a,p in zip(m['assets'],asks)]
    return {'market':m,'books':bs,'observed':now}

class Economics(unittest.TestCase):
    def test_pair_positive_without_fees(self):
        p=paired(snapshot(),1000000);self.assertTrue(p['qualifies']);self.assertLessEqual(float(p['cost']),5)
    def test_fees_remove_apparent_edge(self):
        self.assertFalse(paired(snapshot(rate='.07'),1000000,budget='10')['qualifies'])
    def test_insufficient_minimum(self):
        with self.assertRaises(ValueError):paired(snapshot(asks=('.6','.6')),1000000)
    def test_depth_sweep(self):
        c,f=sweep([['.4','2'],['.5','3']],5,'.07');self.assertAlmostEqual(float(c),2.3);self.assertGreater(f,0)
    def test_missing_depth(self):
        with self.assertRaises(ValueError):sweep([['.4','2']],5,0)
    def test_stale_and_skew(self):
        s=snapshot();s['books'][0]['timestamp']-=6
        with self.assertRaises(ValueError):paired(s,1000000)
        s=snapshot();s['books'][0]['received']-=3
        with self.assertRaises(ValueError):paired(s,1000000)
    def test_asset_identity(self):
        s=snapshot();s['books'][0]['asset']='3'
        with self.assertRaises(ValueError):paired(s,1000000)
    def test_deadline(self):
        s=snapshot();s['market']['end']=1000050
        with self.assertRaises(ValueError):paired(s,1000000)
    def test_metadata_age_not_reset(self):
        s=snapshot();s['market']['received']-=61
        with self.assertRaises(ValueError):paired(s,1000000)
    def test_calendar_deadline_precision(self):
        self.assertEqual(deadline_precision(epoch('2026-10-15T04:59:00Z'),'2026-10-15T00:00:00Z'),'calendar_date')
        with self.assertRaises(ValueError):deadline_precision(epoch('2026-10-15T04:59:00Z'),'2026-10-16T00:00:00Z')
    def test_nonfinite(self):
        with self.assertRaises(ValueError):sweep([['NaN','2']],1,0)
    def test_book_identity_and_sort(self):
        r={'asset_id':'1','market':'c','timestamp':'1000000000','bids':[{'price':'.4','size':'3'},{'price':'.3','size':'2'}],
           'asks':[{'price':'.6','size':'3'},{'price':'.5','size':'2'}]}
        b=book(r,'1','c',1000000,1000001);self.assertEqual(b['asks'][0][0],'0.5')
        with self.assertRaises(ValueError):book(r,'2','c',1000000,1000001)
    def test_metadata_unknown_protocol(self):
        with self.assertRaises(ValueError):metadata({'active':True,'closed':False,'acceptingOrders':True,'version':'v2','negRisk':False},1000000)
    def test_cross_market_requires_review(self):
        with self.assertRaises(ValueError):payoff_check({'reviewed':False},{},1000000)
    def test_cross_matrix(self):
        s=snapshot();c=s['market']['condition']
        spec={'reviewed':True,'exhaustive':True,'review_reference':'operator-reviewed-rules',
              'legs':[{'condition':c,'rule_hash':'rules','asset':a,'shares':'5'} for a in ['1','2']],
              'states':[{'payout_per_share':[1,0]},{'payout_per_share':[0,1]}]}
        p=payoff_check(spec,{c:s},1000000);self.assertAlmostEqual(float(p['worst_net']),.15)
        spec['legs'][0]['rule_hash']='changed'
        with self.assertRaises(ValueError):payoff_check(spec,{c:s},1000000)

class Accounting(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.s=Store(self.tmp.name)
    def tearDown(self):self.s.db.close();self.tmp.cleanup()
    def test_no_duplicate_or_restart_reset(self):
        p=paired(snapshot(),1000000);self.s.enter(p,1000000)
        with self.assertRaises(Exception):self.s.enter(p,1000001)
        again=Store(self.tmp.name);self.assertEqual(again.capital()['positions'],1);again.db.close()
    def test_open_cap(self):
        for i in range(4):self.s.enter(paired(snapshot(condition='0x'+str(i+1)*64),1000000),1000000)
        with self.assertRaises(ValueError):self.s.enter(paired(snapshot(condition='0x'+'5'*64),1000000),1000000)
    def test_settlement_exact(self):
        p=paired(snapshot(),1000000);self.s.enter(p,1000000)
        outcome={'condition_id':p['condition'],'closed':True,'tokens':[{'token_id':'1','winner':True},{'token_id':'2','winner':False}]}
        self.assertTrue(self.s.reconcile(p['condition'],outcome,1000100))
        self.assertFalse(self.s.reconcile(p['condition'],outcome,1000101))
        self.assertGreater(float(self.s.capital()['realized_net_profit']),0)
    def test_ambiguous_settlement_keeps_locked(self):
        p=paired(snapshot(),1000000);self.s.enter(p,1000000)
        self.assertFalse(self.s.reconcile(p['condition'],{'condition_id':p['condition'],'closed':True,'tokens':[]},1000100))
        self.assertEqual(self.s.capital()['open_positions'],1)
    def test_label_gap_and_identity(self):
        self.s.observe(snapshot());self.s.observe(snapshot(1000060))
        self.assertEqual(self.s.db.execute('SELECT count(*) FROM labels').fetchone()[0],1)
        self.s.observe(snapshot(1000120));s=snapshot(1000180);s['market']['rule_hash']='changed';self.s.observe(s)
        self.assertEqual(self.s.db.execute('SELECT count(*) FROM labels').fetchone()[0],2)
    def test_label_late_not_zero(self):
        self.s.observe(snapshot());self.s.observe(snapshot(1000100))
        self.assertEqual(self.s.db.execute('SELECT count(*) FROM labels').fetchone()[0],0)
    def test_training_not_ready(self):self.assertFalse(readiness(self.s)['ready'])
    def test_plan_change_refused(self):
        with self.s.db:self.s.db.execute("UPDATE settings SET value='changed' WHERE key='plan_hash'")
        with self.assertRaises(ValueError):Store(self.tmp.name)

def synthetic_rows():
    rows=[]
    for i in range(250):
        c='0x'+format(i,'064x');start=1000000+i*3600
        for k in range(12):
            s=snapshot(start+k*60,c,asks=('.47','.50'))
            s['books'][0]['bids'][0][1]=str(30+(i%10)*10)
            rows.append({'condition':c,'minute':int(s['observed']//60),'ts':s['observed'],
                         'snapshot':s,'target_ts':s['observed']+60,'target_json':json.dumps([int(i%3==0),int(i%4==0)])})
    return rows

class Training(unittest.TestCase):
    def test_disjoint_and_purged(self):
        a,b,c=partition(synthetic_rows());sets=[{r['condition'] for r in x} for x in (a,b,c)]
        self.assertFalse(sets[0]&sets[1] or sets[1]&sets[2] or sets[0]&sets[2])
        self.assertLess(max(r['target_ts'] for r in a),min(r['ts'] for r in b))
    def test_synthetic_pipeline_only(self):
        with tempfile.TemporaryDirectory() as d:
            result=evaluate(synthetic_rows(),d);self.assertTrue(result['trained']);self.assertFalse(result['edge_validated'])
            m=json.loads((Path(d)/'model.json').read_text());p=predict(m,features(snapshot(),0));self.assertTrue(0<p<1)

if __name__=='__main__':unittest.main()
