import json, tempfile, time, unittest
from pathlib import Path
import scanner as s, paper, bridge
from test_scanner import fixture

class Ledger(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)/'state'
        self.scan=s.scan(self.root,1,fixture,2)
    def tearDown(self):self.tmp.cleanup()
    def records(self,side='yes'):
        c=next(c for c in self.scan['shortlist'] if c['market']['venue']=='polymarket')
        rec=dict(snapshot_id=c['snapshot_id'],p_low=.7,p_high=.8,model_version='test',
                 evidence_refs=['source'],evidence_observed_at=[time.time()],
                 entity_verified=True,rules_reviewed=True,scope_verified=True,reviewer='test')
        f=s.freeze_forecast(self.root,rec)
        with s.connection(self.root) as db:
            quotes=[(k,json.loads(body)) for k,body in db.execute('SELECT id,body FROM requests')]
        qid=next(k for k,q in quotes if q.get('snapshot_id')==c['snapshot_id'] and 'book' in q)
        return dict(forecast_id=f['forecast_id'],quote_request_id=qid,side=side,units=5,
                    fees_per_share=.01,slippage_per_share=.01,cost_source='test reviewed schedule',
                    cost_reviewed=True,reviewer='test')
    def test_paper_entry_costs(self):
        r=paper.enter(self.root,self.records());self.assertAlmostEqual(r['all_in_per_share'],.42)
        self.assertFalse(r['live_execution'])
    def test_depth_vwap(self):self.assertAlmostEqual(paper.vwap([[.4,5],[.6,5]],10),.5)
    def test_insufficient_depth(self):
        with self.assertRaises(ValueError):paper.vwap([[.4,1]],2)
    def test_zero_units(self):
        with self.assertRaises(ValueError):paper.vwap([[.4,1]],0)
    def test_unreviewed_costs(self):
        r=self.records();r['cost_reviewed']=False
        with self.assertRaises(ValueError):paper.enter(self.root,r)
    def test_unknown_costs(self):
        r=self.records();r['fees_per_share']=None
        with self.assertRaises(ValueError):paper.enter(self.root,r)
    def test_no_side_no_edge(self):
        with self.assertRaises(ValueError):paper.enter(self.root,self.records('no'))
    def test_stale_quote(self):
        r=self.records()
        with self.assertRaises(ValueError):paper.enter(self.root,r,now=time.time()+61)
    def test_duplicate_paper_refused(self):
        r=self.records();paper.enter(self.root,r)
        with self.assertRaises(Exception):paper.enter(self.root,r)
    def test_paper_settlement(self):
        r=self.records();paper.enter(self.root,r)
        future=s.timestamp('2099-01-02T00:00:00Z')
        s.settle(self.root,dict(forecast_id=r['forecast_id'],yes_payout=1,
                 official_source='official',observed_at=future,final_reviewed=True),now=future)
        report=paper.report(self.root)
        self.assertAlmostEqual(report['simulated_pnl'],2.9)
    def test_duplicate_outcome_refused(self):
        r=self.records();future=s.timestamp('2099-01-02T00:00:00Z')
        o=dict(forecast_id=r['forecast_id'],yes_payout=1,official_source='official',observed_at=future,final_reviewed=True)
        s.settle(self.root,o,now=future)
        with self.assertRaises(Exception):s.settle(self.root,o,now=future)
    def test_daily_bridge_reuse(self):
        calls=[]
        def fake(name,archive):calls.append(name);return {'evidence':'synthetic'}
        a=bridge.enrich(self.root,2,company_call=fake)
        b=bridge.enrich(self.root,2,company_call=fake)
        self.assertEqual(calls,['Adobe']);self.assertEqual(b['new_research_packets'],0)
    def test_bridge_permission_error_abstains(self):
        def fail(name,archive):raise PermissionError()
        r=bridge.enrich(self.root,2,company_call=fail)
        self.assertEqual(r['reports'][0]['status'],'RESEARCH_UNAVAILABLE')
    def test_no_unsettled_profit(self):
        paper.enter(self.root,self.records());r=paper.report(self.root)
        self.assertIsNone(r['positions'][0]['simulated_pnl']);self.assertEqual(r['simulated_pnl'],0)
if __name__=='__main__':unittest.main()
