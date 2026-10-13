import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from agent import Journal
from quant import POLICY, Research, report, market_baseline
import test_agent


class QuantTests(unittest.TestCase):
    def test_no_second_entry_or_flip(self):
        with tempfile.TemporaryDirectory() as d:
            a = test_agent.Tests().make_agent(Path(d)/'j.db')
            i = a.trade('Up', 5, 'test-slug', 'request-01')
            self.assertEqual(i, a.trade('Up', 5, 'test-slug', 'request-01'))
            for side in ('Up', 'Down'):
                with self.assertRaises(ValueError):
                    a.trade(side, 5, 'test-slug', 'request-02')
            self.assertEqual(a.assessment()['locked_position']['side'], 'Up')

    def test_entry_reason_preserved_when_forecast_changes(self):
        with tempfile.TemporaryDirectory() as d:
            a = test_agent.Tests().make_agent(Path(d)/'j.db')
            a.trade('Up', 5, 'test-slug', 'request-01')
            original = a.assessment()['locked_position']['entry_reason']
            a.anchor += 100
            self.assertEqual(a.assessment()['locked_position']['entry_reason'], original)

    def test_stake_limit(self):
        with tempfile.TemporaryDirectory() as d:
            a = test_agent.Tests().make_agent(Path(d)/'j.db')
            with self.assertRaises(ValueError): a.trade('Up', 11, 'test-slug', 'request-01')

    def test_exposure_limit(self):
        with tempfile.TemporaryDirectory() as d:
            a = test_agent.Tests().make_agent(Path(d)/'j.db')
            a.journal.append('trade', {'slug':'older','fill':{'total':50}})
            with self.assertRaises(ValueError): a.trade('Up', 5, 'test-slug', 'request-01')

    def test_daily_loss_stop(self):
        with tempfile.TemporaryDirectory() as d:
            a = test_agent.Tests().make_agent(Path(d)/'j.db')
            i = a.journal.append('trade', {'slug':'older','fill':{'total':20}})
            a.journal.append('settlement', {'trade_id':i,'payout':0})
            with self.assertRaises(ValueError): a.trade('Up', 5, 'test-slug', 'request-01')

    def test_normalized_midpoint(self):
        b = {s:{'bids':[{'price':p,'size':10}], 'asks':[{'price':str(float(p)+.02),'size':10}]}
             for s,p in [('Up','.6'),('Down','.3')]}
        self.assertAlmostEqual(market_baseline(b), .61/.92)

    def test_crossed_book_rejected(self):
        b = {s:{'bids':[{'price':'.6','size':1}],'asks':[{'price':'.5','size':1}]} for s in ('Up','Down')}
        with self.assertRaises(ValueError): market_baseline(b)

    def observation(self, j, condition='c', p=.8):
        return j.append('assessment', {'condition_id':condition,'slug':'s','policy':POLICY,
            'prediction':{'p_up':p,'momentum_up':True},'market_probability_up':.5,'end_epoch':time.time()+30})

    def test_market_count_not_repeated_prediction_count(self):
        with tempfile.TemporaryDirectory() as d:
            j=Journal(Path(d)/'j.db')
            for _ in range(10): self.observation(j)
            j.append('market_resolution', {'condition_id':'c','winner':'Up'})
            r=report(j.rows());self.assertEqual(r['resolved_markets'],1)
            self.assertAlmostEqual(r['metrics']['model']['brier'],.04)
            self.assertFalse(r['edge_validated'])

    def test_legacy_and_after_deadline_excluded(self):
        with tempfile.TemporaryDirectory() as d:
            j=Journal(Path(d)/'j.db')
            j.append('assessment', {'policy':POLICY,'condition_id':'c','prediction':{'p_up':.9},
                     'market_probability_up':.5,'end_epoch':time.time()-1})
            j.append('market_resolution', {'condition_id':'c','winner':'Up'})
            self.assertEqual(report(j.rows())['eligible_markets'],0)

    def test_resolve_all_predictions_without_trades_and_deduplicate(self):
        with tempfile.TemporaryDirectory() as d:
            j=Journal(Path(d)/'j.db');self.observation(j)
            r=Research(j)
            getter=lambda url:{'condition_id':'c','closed':True,'tokens':[{'winner':True,'outcome':'Down'}]}
            with patch('quant.time.time',return_value=time.time()+100):r.resolve(getter);r.resolve(getter)
            self.assertEqual(sum(x['kind']=='market_resolution' for x in j.rows()),1)

    def test_unconfirmed_winner_does_not_resolve(self):
        with tempfile.TemporaryDirectory() as d:
            j=Journal(Path(d)/'j.db');self.observation(j);r=Research(j)
            with patch('quant.time.time',return_value=time.time()+100):
                r.resolve(lambda u:{'condition_id':'c','closed':True,'tokens':[{'price':1,'outcome':'Up'}]})
            self.assertFalse(any(x['kind']=='market_resolution' for x in j.rows()))

    def test_wallet_validation(self):
        with tempfile.TemporaryDirectory() as d:
            r=Research(Journal(Path(d)/'j.db'))
            with self.assertRaises(ValueError):r.watch('not-a-wallet')
            r.watch('0x'+'a'*40)
            self.assertEqual(Research(r.journal).wallet,r.wallet)

    def test_wallet_dedup_and_no_invented_costs(self):
        with tempfile.TemporaryDirectory() as d:
            j=Journal(Path(d)/'j.db');self.observation(j)
            r=Research(j);r.watch('0x'+'a'*40)
            activity={'proxyWallet':r.wallet,'conditionId':'c','timestamp':time.time(),
                      'type':'TRADE','transactionHash':'tx','price':.5,'side':'BUY'}
            getter=lambda u:[activity]
            r.poll_wallet(getter);r.poll_wallet(getter)
            rows=[x for x in j.rows() if x['kind']=='account_activity']
            self.assertEqual(len(rows),1);self.assertIsNone(rows[0]['net_profit'])
            self.assertIsNotNone(rows[0]['pre_trade_assessment_id'])

    def test_old_trade_not_matched_to_future_assessment(self):
        with tempfile.TemporaryDirectory() as d:
            j=Journal(Path(d)/'j.db');self.observation(j);r=Research(j);r.watch('0x'+'a'*40)
            r.poll_wallet(lambda u:[{'proxyWallet':r.wallet,'conditionId':'c','timestamp':time.time()-100}])
            self.assertIsNone(j.rows()[-1]['pre_trade_assessment_id'])

    def test_wallet_identity_mismatch(self):
        with tempfile.TemporaryDirectory() as d:
            r=Research(Journal(Path(d)/'j.db'));r.watch('0x'+'a'*40)
            r.poll_wallet(lambda u:[{'proxyWallet':'0x'+'b'*40}])
            self.assertIsNotNone(r.wallet_error)
            self.assertEqual(r.state()['account']['captured_events'],0)


if __name__ == '__main__': unittest.main()
