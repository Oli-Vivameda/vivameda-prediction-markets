import json
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
import zlib
from unittest.mock import patch
from agent import Journal, fill
from capture import Capture, BookStream, verify_capture
from shadow import Shadow, STRATEGY


class FakeCapture:
    session = 'test-session'
    ok = True
    def healthy(self): return self.ok
    def offer(self,*args,**kwargs): return True


class FakeStream:
    def __init__(self, now, mono):
        self.books = {s:{'market':'c','asset_id':s,'timestamp':now*1000,'received_at':now,
                      'received_mono_ns':int(mono*1e9),'min_order_size':1,
                      'bids':[{'price':'.49','size':'100'}],
                      'asks':[{'price':'.5','size':'100'}]} for s in ('Up','Down')}
    def snapshot(self,condition,now=None):
        if condition!='c':raise ValueError('Changed contract')
        return self.books


class ShadowTests(unittest.TestCase):
    def make(self,path):
        self.now = time.time();self.mono = 100.
        self.market = {'conditionId':'c','slug':'btc-test','end_epoch':self.now+180,
                       'description':'Frozen official rules','window':60,'acceptingOrders':True,
                       'closed':False,'feesEnabled':True,'feeSchedule':{'rate':.07,'exponent':1}}
        self.capture = FakeCapture();self.stream = FakeStream(self.now,self.mono)
        self.j = Journal(path)
        return Shadow(self.j,self.capture,self.stream,lambda:(self.market,83000,[(self.now,83010)]),
                      lambda *a:{'p_up':.8,'momentum_up':True},fill)

    def test_fixed_window_one_decision_independent_of_manual(self):
        with tempfile.TemporaryDirectory() as d:
            s=self.make(Path(d)/'j.db')
            self.j.append('trade',{'slug':'btc-test','side':'Down','fill':{'total':5}})
            s.tick(self.now-.01,99.9);self.assertEqual(s.state()['decisions'],0)
            s.tick(self.now,100.);s.tick(self.now+.1,100.1)
            self.assertEqual(s.state()['decisions'],1)
            self.assertEqual(s.state()['latest_decision']['side'],'Up')

    def test_two_delayed_arms_no_immediate_fill(self):
        with tempfile.TemporaryDirectory() as d:
            s=self.make(Path(d)/'j.db');s.tick(self.now,100.)
            self.assertEqual(len(s.pending),2)
            s.tick(self.now+.1,100.1);self.assertEqual(s.portfolios()['0.25']['fills'],0)
            for b in self.stream.books.values():b['received_mono_ns']=int(100.29*1e9)
            s.tick(self.now+.3,100.3)
            self.assertEqual(s.portfolios()['0.25']['fills'],1)
            self.assertEqual(s.portfolios()['2.0']['fills'],0)
            for b in self.stream.books.values():b['received_mono_ns']=int(102.09*1e9)
            s.tick(self.now+2.1,102.1)
            self.assertEqual(s.portfolios()['2.0']['fills'],1)
            self.assertEqual(self.j.portfolio()['cash'],1000)

    def test_no_post_delay_update_no_fill(self):
        with tempfile.TemporaryDirectory() as d:
            s=self.make(Path(d)/'j.db');s.tick(self.now,100.);s.tick(self.now+.3,100.3)
            a=s.records[-1];self.assertFalse(a['filled']);self.assertIn('post-delay',a['status'])

    def test_worse_price_uses_later_depth_and_fails_limit(self):
        with tempfile.TemporaryDirectory() as d:
            s=self.make(Path(d)/'j.db');s.tick(self.now,100.)
            self.stream.books['Up']['asks']=[{'price':'.7','size':'100'}]
            self.stream.books['Up']['received_mono_ns']=int(100.3*1e9)
            s.tick(self.now+.4,100.4)
            self.assertFalse(s.records[-1]['filled']);self.assertIn('adverse',s.records[-1]['status'])
            self.assertEqual(s.records[0]['quotes']['Up']['average_price'],.5)

    def test_depth_disappears_records_missed_fill(self):
        with tempfile.TemporaryDirectory() as d:
            s=self.make(Path(d)/'j.db');s.tick(self.now,100.)
            self.stream.books['Up']['asks']=[]
            self.stream.books['Up']['received_mono_ns']=int(100.3*1e9)
            s.tick(self.now+.4,100.4)
            self.assertEqual(s.portfolios()['0.25']['missed_fills'],1)

    def test_no_retroactive_decision(self):
        with tempfile.TemporaryDirectory() as d:
            s=self.make(Path(d)/'j.db');s.tick(self.now+6,106)
            self.assertEqual(s.state()['skips'],1);self.assertFalse(s.pending)

    def test_no_fill_after_deadline(self):
        with tempfile.TemporaryDirectory() as d:
            s=self.make(Path(d)/'j.db');s.tick(self.now,100.)
            s.pending[0]['due']=221.25
            s.tick(self.now+121.3,221.3)
            self.assertFalse(s.records[-1]['filled'])

    def test_missing_fee_and_capture_failure_abstain(self):
        for field in ('fee','capture'):
            with tempfile.TemporaryDirectory() as d:
                s=self.make(Path(d)/'j.db')
                if field=='fee':self.market['feeSchedule']={}
                else:self.capture.ok=False
                s.tick(self.now,100.)
                self.assertEqual(s.state()['skips'],1);self.assertFalse(s.pending)

    def test_restart_cancels_pending_each_arm_once(self):
        with tempfile.TemporaryDirectory() as d:
            s=self.make(Path(d)/'j.db');s.tick(self.now,100.)
            r=Shadow(self.j,self.capture,self.stream,s.context,s.predict,fill)
            self.assertFalse(r.pending)
            self.assertEqual(sum(x['kind']=='shadow_attempt' for x in r.records),2)
            r2=Shadow(self.j,self.capture,self.stream,s.context,s.predict,fill)
            self.assertEqual(sum(x['kind']=='shadow_attempt' for x in r2.records),2)

    def test_settlement_separate_cash_and_idempotent(self):
        with tempfile.TemporaryDirectory() as d:
            s=self.make(Path(d)/'j.db');s.tick(self.now,100.)
            for b in self.stream.books.values():b['received_mono_ns']=int(100.29*1e9)
            s.tick(self.now+.3,100.3)
            self.j.append('market_resolution',{'condition_id':'c','winner':'Up'})
            s.settle();s.settle()
            p=s.portfolios()['0.25'];self.assertEqual(p['settled'],1);self.assertGreater(p['realized_profit'],0)
            self.assertEqual(self.j.portfolio()['cash'],1000)

    def test_risk_stop_prevents_delayed_fill(self):
        with tempfile.TemporaryDirectory() as d:
            s=self.make(Path(d)/'j.db');s.tick(self.now,100.)
            for b in self.stream.books.values():b['received_mono_ns']=int(100.29*1e9)
            with patch.object(s,'portfolios',return_value={'0.25':{'cash':1000,'open_exposure':50,'gross_loss_today':0}}):
                s.execute(self.now+.3,100.3)
            self.assertFalse(s.records[-1]['filled']);self.assertIn('risk',s.records[-1]['status'])


class CaptureTests(unittest.TestCase):
    def wait(self,c,count):
        deadline=time.monotonic()+2
        while c.stored<count and not c.error and time.monotonic()<deadline:time.sleep(.01)

    def test_persistent_raw_timestamps_and_compression(self):
        with tempfile.TemporaryDirectory() as d:
            c=Capture(Path(d)/'capture.db',min_free=0)
            c.offer('reference_tick',{'price':83000,'origin':'stream'},100,received_at=101,received_mono_ns=9)
            self.wait(c,1);c.close()
            with sqlite3.connect(c.path) as db:r=db.execute('SELECT payload,digest FROM feed_batches').fetchone()
            event=json.loads(zlib.decompress(r[0]))[0]
            self.assertEqual(event[1:4],[100.,101.,9]);self.assertEqual(event[7]['price'],83000)
            self.assertEqual(len(r[1]),64)

    def test_storage_guard_preserves_and_pauses(self):
        with tempfile.TemporaryDirectory() as d:
            c=Capture(Path(d)/'capture.db',max_bytes=1,min_free=0);c.offer('x',{})
            self.wait(c,1);self.assertFalse(c.healthy());self.assertIsNotNone(c.error);c.close()

    def test_burst_capture_preserves_all_events(self):
        with tempfile.TemporaryDirectory() as d:
            c=Capture(Path(d)/'capture.db',min_free=0)
            for i in range(500):self.assertTrue(c.offer('market_stream',{'price':.5,'sequence':i},i+1))
            self.wait(c,500);c.close()
            self.assertEqual(c.stored,500);self.assertEqual(c.dropped,0)
            self.assertEqual(verify_capture(c.path),500)

    def test_capture_tampering_detected(self):
        with tempfile.TemporaryDirectory() as d:
            c=Capture(Path(d)/'capture.db',min_free=0);c.offer('reference_tick',{'price':83000})
            self.wait(c,1);c.close()
            with sqlite3.connect(c.path) as db:db.execute("UPDATE feed_batches SET digest='changed'")
            with self.assertRaises(ValueError):verify_capture(c.path)

    def stream(self):
        s=BookStream(FakeCapture(),None)
        now=time.time()
        m={'conditionId':'c','clobTokenIds':['u','d'],'slug':'test'}
        s.configure(m,83000,{side:{'min_order_size':1} for side in ('Up','Down')})
        for token in ('u','d'):
            s.handle({'event_type':'book','market':'c','asset_id':token,'timestamp':now*1000,
                      'bids':[{'price':'.49','size':'100'}],'asks':[{'price':'.5','size':'100'}]},now,1000000000)
        return s,now

    def test_full_book_then_delta_removal_and_update(self):
        s,now=self.stream()
        s.handle({'event_type':'price_change','market':'c','timestamp':(now+.1)*1000,
                  'price_changes':[{'asset_id':'u','side':'SELL','price':'.5','size':'0'},
                                   {'asset_id':'u','side':'SELL','price':'.6','size':'20'}]},now+.1,2_000_000_000)
        b=s.snapshot('c',now+.1)['Up'];self.assertEqual(b['asks'],[{'price':'0.6','size':'20.0'}])

    def test_out_of_order_delta_does_not_change_depth(self):
        s,now=self.stream()
        s.handle({'event_type':'price_change','market':'c','timestamp':(now-.1)*1000,
                  'price_changes':[{'asset_id':'u','side':'SELL','price':'.5','size':'0'}]},now,2_000_000_000)
        self.assertEqual(len(s.snapshot('c',now)['Up']['asks']),1)

    def test_stale_foreign_or_missing_minimum_blocks_fill(self):
        s,now=self.stream()
        with self.assertRaises(ValueError):s.snapshot('c',now+4)
        with self.assertRaises(ValueError):s.snapshot('other',now)
        s.minimums={}
        with self.assertRaises(ValueError):s.snapshot('c',now)

    def test_rollover_discards_old_depth(self):
        s,now=self.stream()
        s.configure({'conditionId':'next','clobTokenIds':['n','m'],'slug':'next'},84000,{})
        with self.assertRaises(ValueError):s.snapshot('next',now)


if __name__=='__main__':unittest.main()
