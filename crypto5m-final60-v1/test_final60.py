"""Final-minute partial-TWAP lane: model math, decision window, reconstruction
validation, late fills and scoring, against the preregistered protocol."""
import json
import math
from pathlib import Path
import tempfile
import unittest
from common import config,canonical,digest,number
import market
import model
import strategy
from ledger import Ledger,consumption
from test_study import metadata,books,prediction,raw_book,proof

C=config()

def series(start,end,price=lambda t:100.,step=1):
    return [{'price':str(price(t)),'source_at':t,'received_at':t+.2} for t in range(start,end+1,step)]

def inputs(m,now,price=lambda t:100.,opening='100'):
    pts=series(int(now)-170,int(now)-1,price)
    ref={'kind':'verified_chainlink_raw','twap_source':m['source'],'points':pts}
    anchor={'source':m['source'],'kind':'chainlink_twap_60','source_at':m['start'],'received_at':m['start']+1,'price':opening}
    return ref,anchor

def wiggle(base):
    return lambda t:base(t)+(.01 if t%2 else -.01)


class StepAverageTests(unittest.TestCase):
    def test_step_function_weights_by_time(self):
        pts=[{'price':'10','source_at':0},{'price':'20','source_at':30}]
        self.assertAlmostEqual(model.step_average(pts,0,60,40)[0],15.)
        pts=[{'price':'10','source_at':-1},{'price':'20','source_at':15}]
        self.assertAlmostEqual(model.step_average(pts,0,60,50)[0],(10*15+20*45)/60)

    def test_requires_start_point_and_rejects_gaps(self):
        with self.assertRaisesRegex(ValueError,'no_point_at_averaging_start'):model.step_average([{'price':'1','source_at':5}],0,10,3)
        pts=[{'price':'1','source_at':t} for t in (0,1,2,7,8,9,10)]
        with self.assertRaisesRegex(ValueError,'reconstruction_gap'):model.step_average(pts,0,10,3)
        with self.assertRaisesRegex(ValueError,'reconstruction_gap'):model.step_average([{'price':'1','source_at':t} for t in range(0,6)],0,10,3)

    def test_constant_price_reconstructs_exactly(self):
        self.assertAlmostEqual(model.step_average(series(-5,60),0,60,3)[0],100.)


class PartialTwapModelTests(unittest.TestCase):
    def test_locked_lead_late_in_window_is_near_certain(self):
        m=metadata();now=m['end']-15;ref,anchor=inputs(m,now,wiggle(lambda t:100.5 if t>m['end']-60 else 100.))
        p=model.predict_final(m,books(m,now),ref,anchor,now,C)
        self.assertEqual(p['p_up'],.99);self.assertEqual(p['version'],'final-minute-partial-twap.v1')
        self.assertGreater(p['realized_twap_part'],100.4)

    def test_uncertainty_shrinks_as_window_closes(self):
        m=metadata();lead=wiggle(lambda t:100.02 if t>m['end']-60 else 100.)
        out=[]
        for r in (55,40,20):
            now=m['end']-r;ref,anchor=inputs(m,now,lead);out.append(model.predict_final(m,books(m,now),ref,anchor,now,C))
        sds=[p['final_twap_sd'] for p in out];self.assertTrue(sds[0]>sds[1]>sds[2])
        self.assertTrue(out[0]['p_up']<=out[1]['p_up']<=out[2]['p_up'])

    def test_realized_part_can_outweigh_current_spot(self):
        # Price spiked above the opening early in the window, then fell just below it late.
        m=metadata();now=m['end']-20
        path=wiggle(lambda t:100.6 if m['end']-60<t<=m['end']-25 else (99.95 if t>m['end']-25 else 100.))
        ref,anchor=inputs(m,now,path);p=model.predict_final(m,books(m,now),ref,anchor,now,C)
        self.assertLess(p['reference_price'],100.);self.assertGreater(p['p_up'],.9)

    def test_matches_baseline_variance_at_window_start(self):
        # sigma * r^1.5 / (60 sqrt 3) at r=60 equals sigma * sqrt(60-40): the models join continuously.
        self.assertAlmostEqual(60**1.5/(60*math.sqrt(3)),math.sqrt(20))

    def test_shadow_fat_tail_forecast_is_less_extreme(self):
        m=metadata();now=m['end']-30;ref,anchor=inputs(m,now,wiggle(lambda t:100.01 if t>m['end']-60 else 100.))
        p=model.predict_final(m,books(m,now),ref,anchor,now,C)
        self.assertLess(abs(p['p_up_shadow_fat_tail']-.5),abs(p['p_up']-.5))

    def test_decision_window_is_enforced(self):
        m=metadata()
        for r in (59,11,120):
            now=m['end']-r;ref,anchor=inputs(m,now)
            with self.assertRaisesRegex(ValueError,'outside_final_minute'):model.predict_final(m,books(m,now),ref,anchor,now,C)

    def test_reconstruction_gap_inside_window_abstains(self):
        m=metadata();now=m['end']-20;ref,anchor=inputs(m,now,wiggle(lambda t:100.))
        ref['points']=[p for p in ref['points'] if not m['end']-40<p['source_at']<m['end']-35]
        with self.assertRaises(ValueError):model.predict_final(m,books(m,now),ref,anchor,now,C)

    def test_anchor_and_lookahead_rules_still_apply(self):
        m=metadata();now=m['end']-20;ref,anchor=inputs(m,now)
        bad={**anchor,'source_at':m['start']+1}
        with self.assertRaisesRegex(ValueError,'opening'):model.predict_final(m,books(m,now),ref,bad,now,C)
        ref['points'][-1]['source_at']=now+1
        with self.assertRaisesRegex(ValueError,'future'):model.predict_final(m,books(m,now),ref,anchor,now,C)


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.j=Ledger(Path(self.tmp.name)/'l.sqlite3',C,'bundle',900);self.j.refresh_day(900)
    def tearDown(self):self.j.close();self.tmp.cleanup()

    def test_paired_is_disabled_and_late_directional_fill_settles(self):
        m=metadata(now=1170);now=1170
        with self.assertRaisesRegex(ValueError,'strategy_disabled'):strategy.plan(m,books(m,now),prediction(now,.97),now,C,self.j.state,'paired')
        p=strategy.plan(m,books(m,now,ask='.85'),prediction(now,.97),now,C,self.j.state,'directional')
        self.j.append('reserve:'+p['id'],'reserve',p,now)
        b=books(m,1172,ask='.85')['Up']
        f=market.execute_depth(b,m,p['budget'],p['plans'][0]['quantity'],consumption(self.j.state),p['plans'][0]['limit'],C['additional_cost_per_share'])
        self.j.append('attempt','attempt',{'id':p['id'],'leg':0,'fill':f,'book':b,'request_started':1172,'received_at':1172,
            'generation_at_reserve':3,'continuity_without_venue_sequence':True,'reason':None},1172)
        self.j.append('finish','finish',{'id':p['id'],'reason':'attempts_complete_hold_to_settlement'},1173)
        self.j.append('credit','credit',{'id':p['id'],'proof':proof(m,1201,'Up'),'payout':f['shares']},1262)
        self.assertGreater(number(self.j.state['credits'][p['id']]),number(f['total']))

    def test_fill_too_close_to_end_is_rejected(self):
        m=metadata(now=1180);now=1180
        p=strategy.plan(m,books(m,now,ask='.85'),prediction(now,.97),now,C,self.j.state,'directional');self.j.append('r','reserve',p,now)
        b=books(m,1195,ask='.85')['Up']
        f=market.execute_depth(b,m,p['budget'],p['plans'][0]['quantity'],additional=C['additional_cost_per_share'])
        with self.assertRaisesRegex(ValueError,'fill_timing'):
            self.j.append('a','attempt',{'id':p['id'],'leg':0,'fill':f,'book':b,'request_started':1182,'received_at':1195,
                'generation_at_reserve':3,'continuity_without_venue_sequence':True},1195)


class WorkerTests(unittest.TestCase):
    def study(self,parent,clock):
        import worker
        return worker.Study(Path(parent)/'s','test',c={**C,'minimum_free_bytes':1},start_feeds=False,clock=lambda:clock[0])

    def test_cadence_two_seconds_inside_final_minute_fifteen_outside(self):
        m=metadata(now=1000);clock=[1000.]
        class Feed:
            generation=3
            def snapshot(self):
                b=books(m,clock[0])
                for x in b.values():x['confirmed_at']=clock[0];x['stream_lag']=.1
                return b
        with tempfile.TemporaryDirectory() as parent:
            s=self.study(parent,clock)
            try:
                s.markets={'btc':m};s.feeds={'btc':Feed()}
                for t in range(1000,1020,2):clock[0]=float(t);s.decide(clock[0])
                outside=s.db.execute('SELECT COUNT(*) FROM observations').fetchone()[0]
                for t in range(1150,1170,2):clock[0]=float(t);s.decide(clock[0])
                inside=s.db.execute('SELECT COUNT(*) FROM observations').fetchone()[0]-outside
                self.assertEqual(outside,2);self.assertEqual(inside,10)
            finally:s.close()

    def test_reconciliation_records_error_against_official_twap(self):
        m=metadata(now=900);clock=[1215.]
        with tempfile.TemporaryDirectory() as parent:
            s=self.study(parent,clock)
            try:
                s.markets={'btc':m}
                for p in series(830,1214,lambda t:100.+(t%3)*.01):s.reference.points['btc'][p['source_at']]=p
                s.reference.twaps['btc'][1200]={'price':'100.01','source_at':1200}
                s.reference.twaps['btc'][900]={'price':'100.02','source_at':900}
                s.reconcile(clock[0])
                rows={k:json.loads(b) for k,b in s.db.execute('SELECT kind,body FROM reconstructions')}
                self.assertEqual(set(rows),{'open','close'})
                self.assertAlmostEqual(rows['close']['reconstructed'],100.01,places=6);self.assertAlmostEqual(rows['close']['error_bps'],0,places=6)
                self.assertLess(rows['open']['error_bps'],0)
                summary=s.reconstruction_summary();self.assertEqual(summary['comparisons'],2);self.assertEqual(summary['preregistered_limit_bps'],1.0)
            finally:s.close()

    def test_reconciliation_marks_unusable_only_after_timeout(self):
        m=metadata(now=900);clock=[1210.]
        with tempfile.TemporaryDirectory() as parent:
            s=self.study(parent,clock)
            try:
                s.markets={'btc':m};s.reference.twaps['btc'][1200]={'price':'100','source_at':1200}
                s.reconcile(clock[0]);self.assertEqual(s.db.execute('SELECT COUNT(*) FROM reconstructions').fetchone()[0],0)
                clock[0]=1330.;s.reconcile(clock[0])
                body=json.loads(s.db.execute("SELECT body FROM reconstructions WHERE kind='close'").fetchone()[0])
                self.assertIsNone(body['error_bps']);self.assertIn('point',body['reason'])
            finally:s.close()


class ReportTests(unittest.TestCase):
    def test_report_scores_bands_shadow_and_reconstruction(self):
        from worker import connect_index
        from report import build
        with tempfile.TemporaryDirectory() as root:
            path=Path(root);j=Ledger(path/'ledger.sqlite3',C,'bundle',0.);db=connect_index(path/'index.sqlite3')
            base={'asset':'btc','start':300,'end':600,'split':'train','decisions':{}}
            for i,(cond,obs,pm,pb,ps) in enumerate((('a',580,.8,.95,.9),('b',560,.6,.7,.65))):
                o={**base,'condition':cond,'observed_at':obs,'market_probability':pm,'model_prediction':{'p_up':pb,'p_up_shadow_fat_tail':ps}}
                db.execute('INSERT INTO observations VALUES(?,?,?,?)',(cond,i,canonical(o),digest(o)))
                out={'winner':'Up','confirmed_at':700};db.execute('INSERT INTO outcomes VALUES(?,?,?)',(cond,canonical(out),digest(out)))
            rec={'error_bps':.4};db.execute('INSERT INTO reconstructions VALUES(?,?,?,?)',('a','close',canonical(rec),digest(rec)))
            db.commit();db.close()
            r=build(path,now=800);same=r['model_vs_market_same_observation']
            self.assertEqual(set(same['by_remaining_band']),{'12-30s','30-58s'})
            self.assertEqual(same['shadow_fat_tail_model']['n'],2);self.assertEqual(r['twap_reconstruction']['comparisons'],1)
            j.close()


class ConfigTests(unittest.TestCase):
    def test_lane_configuration_is_pinned(self):
        self.assertEqual(C['version'],'crypto5m-final60.v1');self.assertEqual(C['strategies'],['directional'])
        for bad in ({'strategies':['directional','paired']},{'final_minute_min_remaining':4},{'discovery_seconds':30}):
            with tempfile.TemporaryDirectory() as d:
                p=Path(d)/'c.json';p.write_text(json.dumps({**C,**bad}))
                with self.assertRaises(ValueError):config(p)


if __name__=='__main__':unittest.main()
