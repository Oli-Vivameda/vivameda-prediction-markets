from datetime import datetime,timezone
from decimal import Decimal as D
from pathlib import Path
from types import SimpleNamespace as N
from unittest.mock import patch
import hashlib,json,sqlite3,tempfile,unittest
from risk import Ledger
from planning import plan
from pilot import execute,active_guard,eligibility
from venue import load_secret,validate_market

class Tests(unittest.TestCase):
    def data(self):
        d={'id':1,'strategy':'btc5m-fixed180-delay-v3','condition_id':'c','slug':'btc-updown-5m-820','side':'Up','decision_time':997.8,'end_epoch':1180,'rule_hash':hashlib.sha256(b'rules').hexdigest(),'books':{'Up':{'asset_id':'1'}},'quotes':{'Up':{'break_even_probability':.518}},'prediction':{'p_up':.8},'fee_rate':.07,'fee_exponent':1}
        b=N(asset_id='1',market='c',timestamp=datetime.fromtimestamp(1000,timezone.utc),tick_size=D('.01'),min_order_size=D(5),asks=[N(price=D('.50'),size=D(100))])
        return d,b
    def venue(self):
        self.balance_calls=0
        def balance():self.balance_calls+=1;return D(10) if self.balance_calls==1 else D('7.30')
        return N(balance=balance,sign=lambda p:N(maker_amount=2650000,taker_amount=5300000),post=lambda s:N(ok=True,status='matched',order_id='order-1',trade_ids=['t']),confirm=lambda r,p:{'onchain_fill_confirmed':True})
    def test_plan_fees_tick_and_minimum(self):
        d,b=self.data();p=plan(d,b,1000);self.assertEqual(p['max_price'],'0.53');self.assertEqual(p['reservation'],'3');self.assertEqual(p['side'],'Up')
    def test_minimum_can_block_small_budget(self):
        d,b=self.data();b.min_order_size=D(10)
        with self.assertRaises(ValueError):plan(d,b,1000)
    def test_stale_book_and_late_candidate(self):
        d,b=self.data()
        with self.assertRaises(ValueError):plan(d,b,1004)
        b.timestamp=datetime.fromtimestamp(990,timezone.utc)
        with self.assertRaises(ValueError):plan(d,b,1000)
    def test_identity_mismatch(self):
        d,b=self.data();b.asset_id='2'
        with self.assertRaises(ValueError):plan(d,b,1000)
    def test_lifetime_budget_does_not_recycle(self):
        with tempfile.TemporaryDirectory() as t:
            l=Ledger(Path(t)/'l.db')
            for i in range(3):
                l.reserve({'condition_id':str(i)},10);l.transition(str(i),'aborted')
            self.assertEqual(l.state()['reserved_lifetime'],'9')
            with self.assertRaises(ValueError):l.reserve({'condition_id':'4'},10)
    def test_pending_blocks_restart(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'l.db';l=Ledger(p);l.reserve({'condition_id':'c'},10)
            restored=Ledger(p)
            with self.assertRaises(ValueError):restored.reserve({'condition_id':'new'},10)
    def test_duplicate_condition_refused(self):
        with tempfile.TemporaryDirectory() as t:
            l=Ledger(Path(t)/'l.db');l.reserve({'condition_id':'c'},10);l.transition('c','aborted')
            with self.assertRaises(sqlite3.IntegrityError):l.reserve({'condition_id':'c'},10)
    def test_above_ten_balance_refused(self):
        with tempfile.TemporaryDirectory() as t:
            with self.assertRaises(ValueError):Ledger(Path(t)/'l.db').reserve({'condition_id':'c'},D('10.01'))
    def test_confirmed_fill_and_cost(self):
        d,b=self.data();p=plan(d,b,1000)
        with tempfile.TemporaryDirectory() as t:
            l=Ledger(Path(t)/'l.db');execute(l,self.venue(),p,Path(t)/'STOP',lambda:1000)
            self.assertEqual(l.rows()[0]['state'],'confirmed');l.verify()
    def test_timeout_never_retries(self):
        d,b=self.data();p=plan(d,b,1000);v=self.venue();calls=[]
        def post(s):calls.append(s);raise TimeoutError()
        v.post=post
        with tempfile.TemporaryDirectory() as t:
            l=Ledger(Path(t)/'l.db')
            with self.assertRaises(RuntimeError):execute(l,v,p,Path(t)/'STOP',lambda:1000)
            self.assertEqual(len(calls),1);self.assertEqual(l.rows()[0]['state'],'unknown')
            with self.assertRaises(ValueError):l.reserve({'condition_id':'new'},10)
    def test_settlement_ambiguity_stops(self):
        d,b=self.data();p=plan(d,b,1000);v=self.venue();v.confirm=lambda r,p:(_ for _ in ()).throw(TimeoutError())
        with tempfile.TemporaryDirectory() as t:
            l=Ledger(Path(t)/'l.db')
            with self.assertRaises(RuntimeError):execute(l,v,p,Path(t)/'STOP',lambda:1000)
            self.assertEqual(l.rows()[0]['state'],'unknown')
    def test_stop_prevents_reservation_or_post(self):
        d,b=self.data();p=plan(d,b,1000)
        with tempfile.TemporaryDirectory() as t:
            l=Ledger(Path(t)/'l.db');stop=Path(t)/'STOP';stop.touch()
            with self.assertRaises(ValueError):execute(l,self.venue(),p,stop,lambda:1000)
            self.assertEqual(l.rows(),[])
    def test_execution_window_expiry_prevents_signing(self):
        d,b=self.data();p=plan(d,b,1000)
        with tempfile.TemporaryDirectory() as t:
            l=Ledger(Path(t)/'l.db')
            with self.assertRaises(ValueError):execute(l,self.venue(),p,Path(t)/'STOP',lambda:1000,deadline=999)
            self.assertEqual(l.rows(),[])
    def test_geofence_unavailable_fails_closed(self):
        with patch('pilot.read_json',side_effect=TimeoutError()):self.assertFalse(eligibility()['eligible'])
        with patch('pilot.read_json',return_value={'blocked':True,'country':'XX'}):self.assertFalse(eligibility()['eligible'])
    def test_health_guard_blocks_paper_fault(self):
        with self.assertRaises(ValueError):active_guard({'operations':{'health':{'mode':'degraded'}}},1000)
    def test_world_readable_secret_refused(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'secret.json';p.write_text('{}');p.chmod(0o644)
            with self.assertRaises(ValueError):load_secret(p)
    def test_reservation_table_tampering_refused(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'l.db';l=Ledger(p);l.reserve({'condition_id':'c'},10)
            with sqlite3.connect(p) as db:db.execute("UPDATE intents SET reserved='0'")
            with self.assertRaises(ValueError):Ledger(p)
    def test_market_rules_and_v2_fail_closed(self):
        d,b=self.data()
        m=N(version=None,condition_id='c',slug=d['slug'],description='rules',state=N(accepting_orders=True,closed=False,end_date=datetime.fromtimestamp(1180,timezone.utc)),trading=N(seconds_delay=0,fees_enabled=True,fee_schedule=N(rate=D('.07'),exponent=D(1))),outcomes=N(yes=N(label='Up',token_id='1'),no=N(label='Down',token_id='2')))
        validate_market(m,d);m.version='v2'
        with self.assertRaises(ValueError):validate_market(m,d)
        m.version=None;m.description='changed'
        with self.assertRaises(ValueError):validate_market(m,d)
    def test_journal_tampering_refused(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'l.db';l=Ledger(p);l.reserve({'condition_id':'c'},10)
            with sqlite3.connect(p) as db:db.execute("UPDATE events SET body='{}'")
            with self.assertRaises(ValueError):Ledger(p)
if __name__=='__main__':unittest.main()
