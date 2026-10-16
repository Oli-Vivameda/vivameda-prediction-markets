"""Final-minute v2: one-sided books are normal in the last minute. Only the bought side
needs executable asks; freshness, identity and crossing rules still apply to both."""
from pathlib import Path
import tempfile
import unittest
from common import config,number
import market
import model
import strategy
from ledger import Ledger,consumption
from test_study import metadata,prediction
from test_final60 import inputs,wiggle

C=config()

def book(m,side,now,bids,asks):
    raw={'asset_id':m['tokens'][side],'market':m['condition'],'timestamp':now,'min_order_size':'5','tick_size':m['tick'],
        'bids':[{'price':p,'size':'200'} for p in bids],'asks':[{'price':p,'size':'200'} for p in asks]}
    return market.book(raw,m['tokens'][side],m['condition'],now,3,allow_empty=True)

def one_sided(m,now,up=(['0.89'],['0.9']),down=([],['0.11'])):
    return {'Up':book(m,'Up',now,*up),'Down':book(m,'Down',now,*down)}


class BookRuleTests(unittest.TestCase):
    def test_fresh_allows_empty_side_but_keeps_other_guards(self):
        m=metadata();b=one_sided(m,1000)
        market.fresh(b['Down'],m,1000,C)
        with self.assertRaisesRegex(ValueError,'stale'):market.fresh(b['Down'],m,1010,C)
        bad=dict(b['Down'],token='999')
        with self.assertRaisesRegex(ValueError,'stale_or_changed'):market.fresh(bad,m,1000,C)
        locked=book(m,'Up',1000,['0.5'],['0.5'])
        with self.assertRaisesRegex(ValueError,'crossed_or_locked'):market.fresh(locked,m,1000,C)

    def test_executable_buy_needs_asks_and_respects_spread_when_bids_exist(self):
        m=metadata()
        with self.assertRaisesRegex(ValueError,'no_executable_asks'):market.executable_buy(book(m,'Up',1000,['0.9'],[]),C)
        market.executable_buy(book(m,'Up',1000,[],['0.3']),C)
        with self.assertRaisesRegex(ValueError,'spread'):market.executable_buy(book(m,'Up',1000,['0.1'],['0.3']),C)

    def test_inherited_two_sided_rule_is_unchanged(self):
        m=metadata()
        with self.assertRaisesRegex(ValueError,'empty_book'):market.healthy(book(m,'Up',1000,[],['0.3']),m,1000,C)

    def test_implied_probability_fallbacks(self):
        m=metadata()
        both={'Up':book(m,'Up',1000,['0.6'],['0.62']),'Down':book(m,'Down',1000,['0.38'],['0.4'])}
        p,how=market.implied_p_up(both);self.assertEqual(how,'both_midpoints');self.assertAlmostEqual(p,.61/(1.0))
        p,how=market.implied_p_up(one_sided(m,1000));self.assertEqual(how,'up_midpoint');self.assertAlmostEqual(p,.895)
        p,how=market.implied_p_up(one_sided(m,1000,up=([],['0.97']),down=(['0.02'],['0.03'])))
        self.assertEqual(how,'down_midpoint_complement');self.assertAlmostEqual(p,.975)
        p,how=market.implied_p_up(one_sided(m,1000,up=([],['0.97']),down=([],['0.05'])))
        self.assertEqual(how,'normalized_best_asks');self.assertAlmostEqual(p,.97/1.02)
        with self.assertRaisesRegex(ValueError,'no_market_quote'):market.implied_p_up(one_sided(m,1000,up=(['0.9'],[]),down=([],[])))


class DecisionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.j=Ledger(Path(self.tmp.name)/'l.sqlite3',C,'bundle',900);self.j.refresh_day(900)
    def tearDown(self):self.j.close();self.tmp.cleanup()

    def test_buys_favourite_when_losing_side_has_no_bids(self):
        m=metadata(now=1170);b=one_sided(m,1170)
        p=strategy.plan(m,b,prediction(1170,.99),1170,C,self.j.state,'directional')
        self.assertEqual(p['plans'][0]['side'],'Up');self.j.append('r','reserve',p,1170)

    def test_can_buy_a_side_that_has_asks_but_no_bids(self):
        m=metadata(now=1170);b=one_sided(m,1170,up=([],['0.3']),down=(['0.69'],['0.7']))
        p=strategy.plan(m,b,prediction(1170,.5),1170,C,self.j.state,'directional');self.assertEqual(p['plans'][0]['side'],'Up')

    def test_no_trade_without_asks_on_the_favoured_side(self):
        m=metadata(now=1170);b=one_sided(m,1170,up=(['0.9'],[]),down=([],['0.11']))
        with self.assertRaisesRegex(ValueError,'no_directional_cost_adjusted_edge'):strategy.plan(m,b,prediction(1170,.99),1170,C,self.j.state,'directional')

    def test_late_fill_on_one_sided_rest_book_and_rejection_without_asks(self):
        m=metadata(now=1170);p=strategy.plan(m,one_sided(m,1170),prediction(1170,.99),1170,C,self.j.state,'directional')
        self.j.append('r','reserve',p,1170)
        empty_ask=book(m,'Up',1172,['0.89'],[])
        with self.assertRaises(ValueError):
            f=market.execute_depth(empty_ask,m,p['budget'],p['plans'][0]['quantity'],consumption(self.j.state),p['plans'][0]['limit'],C['additional_cost_per_share'])
            self.j.append('bad','attempt',{'id':p['id'],'leg':0,'fill':f,'book':empty_ask,'request_started':1172,'received_at':1172,
                'generation_at_reserve':3,'continuity_without_venue_sequence':True},1172)
        b=book(m,'Up',1172,[],['0.9'])
        f=market.execute_depth(b,m,p['budget'],p['plans'][0]['quantity'],consumption(self.j.state),p['plans'][0]['limit'],C['additional_cost_per_share'])
        self.j.append('a','attempt',{'id':p['id'],'leg':0,'fill':f,'book':b,'request_started':1172,'received_at':1172,
            'generation_at_reserve':3,'continuity_without_venue_sequence':True,'reason':None},1172)
        self.assertGreater(number(self.j.state['positions'][p['id']]['attempts']['0']['fill']['shares']),0)


class ModelTests(unittest.TestCase):
    def test_empty_up_book_does_not_crash_the_forecast(self):
        m=metadata();now=m['end']-20;ref,anchor=inputs(m,now,wiggle(lambda t:100.2 if t>m['end']-60 else 100.))
        b=one_sided(m,now,up=([],[]),down=(['0.02'],['0.03']))
        p=model.predict_final(m,b,ref,anchor,now,C)
        self.assertTrue(p['up_book_empty']);self.assertEqual(p['features'][3],0.);self.assertEqual(p['market_probability_method'],'down_midpoint_complement')


class WorkerTests(unittest.TestCase):
    def test_decision_with_one_sided_books_records_probability_and_method(self):
        import worker,json
        m=metadata(now=1170);now=1170.
        class Feed:
            generation=3
            def snapshot(self):
                b=one_sided(m,now)
                for x in b.values():x['confirmed_at']=now;x['stream_lag']=.1
                return b
        with tempfile.TemporaryDirectory() as parent:
            s=worker.Study(Path(parent)/'s','test',c={**C,'minimum_free_bytes':1},start_feeds=False,clock=lambda:now)
            try:
                s.markets={'btc':m};s.feeds={'btc':Feed()};s.journal.refresh_day(now);s.storage_ok=lambda:True
                ref,anchor=inputs(m,now,wiggle(lambda t:100.3 if t>m['end']-60 else 100.))
                s.reference.inputs=lambda mm,t:(ref,anchor)
                s.decide(now)
                record=json.loads(s.db.execute('SELECT body FROM observations').fetchone()[0])
                self.assertEqual(record['market_probability_method'],'up_midpoint');self.assertIsNotNone(record['model_prediction'])
                self.assertEqual(record['decisions']['directional'],'RESERVED')
            finally:s.close()


if __name__=='__main__':unittest.main()
