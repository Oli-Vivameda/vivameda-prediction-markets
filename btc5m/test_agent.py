import math
import tempfile
import time
import unittest
from unittest.mock import patch
from pathlib import Path
from agent import Agent, Journal, Reference, fill, probability


class Tests(unittest.TestCase):
    def test_depth_and_fees(self):
        b = {'asks': [{'price': '.8', 'size': '100'}, {'price': '.5', 'size': '2'}]}
        f = fill(b, 5, .07, 1)
        self.assertGreater(f['average_price'], .5)
        self.assertAlmostEqual(f['total'], 5)
        self.assertGreater(f['fees'], 0)
        self.assertAlmostEqual(f['winning_profit'], f['shares']-5)

    def test_insufficient_depth(self):
        with self.assertRaises(ValueError):
            fill({'asks': [{'price': '.5', 'size': '1'}]}, 5, .07, 1)

    def test_nan_rejected(self):
        with self.assertRaises(ValueError):
            fill({'asks': [{'price': 'NaN', 'size': '100'}]}, 5, .07, 1)

    def test_unknown_fee_rejected(self):
        with self.assertRaises(ValueError):
            fill({'asks': [{'price': '.5', 'size': '100'}]}, 5, .07, 2)

    def points(self):
        now = time.time()
        return now, [(now-i, 83000+math.sin(i)*5) for i in reversed(range(120))]

    def test_symmetric_probability(self):
        now, points = self.points()
        p = probability(points, points[-1][1], now, now+120, 60)
        self.assertAlmostEqual(p['p_up'], .5)
        self.assertFalse(p['calibrated'])

    def test_up_down_monotonic(self):
        now, points = self.points()
        a = probability(points, 82990, now, now+120, 60)
        b = probability(points, 83010, now, now+120, 60)
        self.assertGreater(a['p_up'], b['p_up'])

    def test_stale_price(self):
        now, points = self.points()
        with self.assertRaises(ValueError):
            probability(points, 83000, now+6, now+120, 60)

    def test_final_twap_window(self):
        now, points = self.points()
        with self.assertRaises(ValueError):
            probability(points, 83000, now, now+60, 60)

    def test_warmup(self):
        now, points = self.points()
        with self.assertRaises(ValueError):
            probability(points[-10:], 83000, now, now+120, 60)

    def test_gaps(self):
        now, points = self.points()
        points = points[:50] + points[70:]
        with self.assertRaises(ValueError):
            probability(points, 83000, now, now+120, 60)

    def make_agent(self, path):
        a = Agent(Journal(path))
        now, points = self.points()
        a.error = None
        a.reference.points = points
        a.market = {'slug':'test-slug', 'question':'BTC', 'description':'Frozen rules',
                    'conditionId':'condition', 'start_epoch':now-100, 'end_epoch':now+200,
                    'window':60, 'acceptingOrders':True, 'closed':False, 'feesEnabled':True,
                    'feeSchedule':{'rate':.07,'exponent':1}}
        a.anchor, a.anchor_slug = 83000, 'test-slug'
        a.books = {s:{'timestamp':str(now*1000),'received_at':now,
                      'asks':[{'price':'.5','size':'10000'}]} for s in ('Up','Down')}
        return a

    def test_market_change_refused(self):
        with tempfile.TemporaryDirectory() as d:
            a=self.make_agent(Path(d)/'j.db')
            with self.assertRaises(ValueError):a.trade('Up',5,'wrong','request-01')

    def test_stale_book_refused(self):
        with tempfile.TemporaryDirectory() as d:
            a=self.make_agent(Path(d)/'j.db');a.books['Up']['timestamp']=str((time.time()-10)*1000)
            with self.assertRaises(ValueError):a.trade('Up',5,'test-slug','request-01')

    def test_idempotent_and_frozen(self):
        with tempfile.TemporaryDirectory() as d:
            a=self.make_agent(Path(d)/'j.db');i=a.trade('Up',5,'test-slug','request-01')
            a.market['description']='Later changed rules'
            self.assertEqual(i,a.trade('Up',5,'test-slug','request-01'))
            p=a.journal.portfolio();self.assertAlmostEqual(p['cash'],995)
            self.assertEqual(p['open_positions'],1)
            self.assertEqual(p['trades'][0]['assessment']['rules'],'Frozen rules')

    def test_final_price_not_settlement(self):
        with tempfile.TemporaryDirectory() as d:
            a=self.make_agent(Path(d)/'j.db');a.trade('Up',5,'test-slug','request-01')
            with patch('agent.time.time',return_value=time.time()+1000),patch('agent.get_json',return_value={'condition_id':'condition','closed':True,'tokens':[{'outcome':'Up','price':1}]}):a.settle()
            self.assertEqual(a.journal.portfolio()['open_positions'],1)

    def test_explicit_winner_settlement(self):
        with tempfile.TemporaryDirectory() as d:
            a=self.make_agent(Path(d)/'j.db');a.trade('Down',5,'test-slug','request-01')
            with patch('agent.time.time',return_value=time.time()+1000),patch('agent.get_json',return_value={'condition_id':'condition','closed':True,'tokens':[{'outcome':'Up','winner':True}]}):a.settle();a.settle()
            p=a.journal.portfolio();self.assertEqual(p['open_positions'],0)
            self.assertEqual(p['realized_profit'],-5)

    def test_unknown_fees_no_manual(self):
        with tempfile.TemporaryDirectory() as d:
            a=self.make_agent(Path(d)/'j.db');del a.market['feeSchedule']
            self.assertFalse(a.assessment()['manual_available'])

    def test_journal_tampering_detected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'j.db';j=Journal(p);j.append('assessment',{'action':'SKIP'})
            with j.connect() as db:db.execute("UPDATE events SET body='{}'")
            with self.assertRaises(ValueError):Journal(p)

    def test_old_open_positions_not_truncated(self):
        with tempfile.TemporaryDirectory() as d:
            a=self.make_agent(Path(d)/'j.db')
            for i in range(55):
                a.journal.append('trade', {'slug':'old-'+str(i), 'side':'Up', 'fill':{'total':5}, 'assessment':{}})
            self.assertEqual(len(a.journal.portfolio()['trades']),55)

    def test_reference_subscription_and_snapshot_compatibility(self):
        r=Reference();frames=[]
        class Feed:
            def send(self,body,opcode=1):frames.append(body)
            def receive(self):
                r.stop.set()
                import json
                return json.dumps({'topic':'crypto_prices','type':'subscribe','payload':{
                    'symbol':'btc/usd','data':[{'timestamp':time.time()*1000,'value':83000}]}})
            def close(self):pass
        with patch('agent.PublicSocket',return_value=Feed()):r.run()
        import json
        self.assertEqual(json.loads(frames[0])['subscriptions'][0]['filters'],'{"symbol":"btc/usd"}')
        self.assertEqual(len(r.points),1)
        self.assertEqual(r.points[0][1],83000)


if __name__=='__main__':unittest.main()
