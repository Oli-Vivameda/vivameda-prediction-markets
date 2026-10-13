from datetime import date
import tempfile,unittest
from pathlib import Path
from operations import assess_health,day_bounds,daily_report
from supervisor import recovery_due,restart_allowed
from training import PLAN,epoch,readiness,split_days,features,run_study
from agent import Journal
from install_services import units

class OperationsTests(unittest.TestCase):
    def healthy(self):return {'capture':{'healthy':True},'reference_age':1,'stream_fresh':True,'engine_heartbeat':999}
    def test_fresh_allows_and_stale_pauses(self):
        s=self.healthy();self.assertTrue(assess_health(s,1000,0)['shadow_allowed']);s['reference_age']=5
        h=assess_health(s,1000,0);self.assertFalse(h['shadow_allowed']);self.assertFalse(h['restart_requested'])
    def test_storage_does_not_restart_loop(self):
        s=self.healthy();s['capture']={'healthy':False,'error':'Capture storage limit reached'}
        h=assess_health(s,1000,0);self.assertTrue(h['operator_action_required']);self.assertFalse(h['restart_requested'])
    def test_stalled_worker_requests_recovery_after_warmup(self):
        s=self.healthy();s['engine_heartbeat']=100
        self.assertTrue(assess_health(s,1000,0)['restart_requested']);self.assertFalse(assess_health(s,1000,950)['restart_requested'])
    def test_cyprus_day_handles_dst(self):
        a,b=day_bounds(date(2026,10,25));self.assertEqual(b-a,25*3600)
        a,b=day_bounds(date(2026,3,29));self.assertEqual(b-a,23*3600)
    def test_empty_day_never_verified(self):
        self.assertFalse(daily_report([],date(2026,10,12),epoch('2026-10-14T00:00:00Z'))['full_day_verified'])
    def test_recovery_warmup_block_and_budget(self):
        self.assertFalse(recovery_due(None,100,0,None));self.assertTrue(recovery_due(None,200,0,None))
        self.assertFalse(recovery_due({'timestamp':200,'health':{'operator_action_required':True,'restart_requested':True}},200,0,0))
        self.assertFalse(restart_allowed([10,20,30],100));self.assertTrue(restart_allowed([10,20,30],4000))
    def test_training_date_and_coverage_gate(self):
        h=readiness([],epoch(PLAN['end'])-1);self.assertFalse(h['ready']);self.assertEqual(h['expected_markets'],4032)
        self.assertIn('registered_14_full_days_not_complete',h['reasons'])
    def test_purged_phase_boundary(self):
        a=epoch(PLAN['train_end']);b=epoch(PLAN['calibration_end'])
        ds=[{'decision_time':a-500,'end_epoch':a-320},{'decision_time':a-180,'end_epoch':a},{'decision_time':a+301,'end_epoch':a+481},{'decision_time':b+301,'end_epoch':b+481}]
        tr,cal,te=split_days(ds);self.assertEqual([len(tr),len(cal),len(te)],[1,1,1])
    def test_no_dependency_or_fit_before_gate(self):
        with tempfile.TemporaryDirectory() as d:
            Journal(Path(d)/'j.db');result=run_study(Path(d)/'j.db',Path(d)/'research',epoch(PLAN['start']))
            self.assertFalse(result['trained']);self.assertFalse((Path(d)/'research/evaluation.json').exists())
    def test_capture_handles_ten_thousand_event_burst(self):
        from capture import Capture,verify_capture
        import time
        with tempfile.TemporaryDirectory() as d:
            c=Capture(Path(d)/'c.db',min_free=0)
            for i in range(10000):self.assertTrue(c.offer('burst',{'i':i,'asset':'test'}))
            deadline=time.monotonic()+10
            while c.stored<10000 and time.monotonic()<deadline:time.sleep(.01)
            self.assertEqual(c.stored,10000);self.assertEqual(c.dropped,0);c.close()
            self.assertEqual(verify_capture(Path(d)/'c.db'),10000)
    def test_capture_byte_budget_latches_gap(self):
        from capture import Capture
        with tempfile.TemporaryDirectory() as d:
            c=Capture(Path(d)/'c.db',min_free=0);c.queue_byte_limit=1
            self.assertFalse(c.offer('test',{'x':'bounded'}));self.assertFalse(c.healthy());c.close()
    def test_dedicated_nonroot_units(self):
        u=units(Path('/tmp/runtime'),'a'*64,Path('/tmp/python'),Path('/tmp/capture'))
        self.assertEqual(len(u),3);self.assertIn('User=vivameda-engineer',u['vivameda-btc5m-paper.service']);self.assertIn('Asia/Nicosia',u['vivameda-btc5m-training.timer'])
if __name__=='__main__':unittest.main()
