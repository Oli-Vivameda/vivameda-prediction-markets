"""Version 3 behaviour: stream resilience, liveness freshness, realized-loss halts,
attempt-first scheduling, same-observation scoring and the offline training builder."""
import json
from pathlib import Path
import tempfile
import unittest
from common import D,config,digest,canonical,number
import market
import strategy
from feeds import Books
from ledger import Ledger,portfolio,entries_halted,realized_losses,consumption
from test_study import metadata,raw_book,books,prediction,proof


def live_feed(m=None,now=1000):
    m=m or metadata();rest={s:raw_book(m,s,now) for s in ('Up','Down')};feed=Books(m,rest)
    for side in ('Up','Down'):feed.handle({**rest[side],'event_type':'book'},now)
    return m,feed

def delta(m,ts,price='.44',size='5',side='BUY',token='Up'):
    return {'event_type':'price_change','market':m['condition'],'timestamp':ts,
        'price_changes':[{'asset_id':m['tokens'][token],'side':side,'price':price,'size':size}]}


class StreamTests(unittest.TestCase):
    def test_late_ordered_delta_is_applied_without_reconnect_but_not_tradeable_until_lag_clears(self):
        m,feed=live_feed();g=feed.generation
        feed.handle(delta(m,1000,'.44'),1005)
        self.assertEqual(feed.generation,g);self.assertEqual(feed.late_deltas_applied,1)
        b=feed.snapshot()['Up'];self.assertIn(['0.44','5'],b['bids'])
        with self.assertRaisesRegex(ValueError,'stale'):market.healthy(b,m,1005,config())
        feed.handle(delta(m,1006,'.43'),1006.2)
        market.healthy(feed.snapshot()['Up'],m,1006.5,config())

    def test_delta_older_than_snapshot_is_superseded_not_fatal(self):
        m,feed=live_feed();before=feed.snapshot()['Up']['bids']
        feed.handle(delta(m,999,'.40'),1000.5)
        self.assertEqual(feed.superseded_deltas,1);self.assertEqual(feed.snapshot()['Up']['bids'],before);self.assertEqual(feed.generation,0)

    def test_out_of_order_deltas_still_force_resync(self):
        m,feed=live_feed();feed.handle(delta(m,1002,'.44'),1002)
        with self.assertRaisesRegex(ValueError,'regression'):feed.handle(delta(m,1001,'.43'),1002.1)

    def test_older_snapshot_does_not_replace_newer_book(self):
        m,feed=live_feed();feed.handle(delta(m,1002,'.44'),1002)
        old={**raw_book(m,'Up',999),'event_type':'book'};feed.handle(old,1002.5)
        self.assertEqual(feed.superseded_snapshots,1);self.assertIn(['0.44','5'],feed.snapshot()['Up']['bids'])

    def test_future_timestamps_force_resync(self):
        m,feed=live_feed()
        with self.assertRaisesRegex(ValueError,'future'):feed.handle(delta(m,1010),1000)
        with self.assertRaisesRegex(ValueError,'future'):feed.handle({**raw_book(m,'Up',1010),'event_type':'book'},1000)

    def test_quiet_book_stays_healthy_only_while_connection_proves_liveness(self):
        m,feed=live_feed();c=config()
        with self.assertRaisesRegex(ValueError,'stale'):market.healthy(feed.snapshot()['Up'],m,1010,c)
        feed.alive(1009.5);market.healthy(feed.snapshot()['Up'],m,1010,c)
        feed.clear('disconnected')
        with self.assertRaises(ValueError):feed.snapshot()

    def test_locked_book_is_not_tradeable(self):
        m,feed=live_feed();feed.handle(delta(m,1001,'.46','5','BUY'),1001)
        with self.assertRaisesRegex(ValueError,'crossed_or_locked'):market.healthy(feed.snapshot()['Up'],m,1001,config())

    def test_rest_books_keep_strict_v2_age_rules(self):
        m=metadata()
        with self.assertRaisesRegex(ValueError,'stale_book'):market.book(raw_book(m,'Up',990),'1',m['condition'],1000)
        b=books(m,1000)['Up'];self.assertNotIn('confirmed_at',b)
        with self.assertRaisesRegex(ValueError,'stale'):market.healthy(b,m,1004,config())

    def test_resync_reasons_are_counted_for_diagnosis(self):
        m,feed=live_feed();s=feed.status()
        for key in ('resync_reasons','superseded_deltas','superseded_snapshots','late_deltas_applied','stream_lag'):self.assertIn(key,s)


class HaltTests(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'ledger.sqlite3'
    def tearDown(self):self.j.close();self.tmp.cleanup()
    def open(self,**overrides):
        self.c={**config(),**overrides};self.j=Ledger(self.path,self.c,'bundle',999);self.j.refresh_day(999)
    def losing_positions(self):
        ids=[]
        for i,asset in enumerate(('btc','eth','sol','btc')):
            now=1000+i*10 if i<3 else 1300;start=900 if i<3 else 1200;m=metadata(asset,start,now)
            m['rate']='0';m['tick']='0.001'
            if i==3:m['condition']='0x'+'d'*64
            p=strategy.plan(m,books(m,now,ask='.497'),prediction(now),now,self.c,self.j.state,'directional')
            self.j.append('reserve:'+p['id'],'reserve',p,now)
            b=books(m,now+2,ask='.497')['Up']
            f=market.execute_depth(b,m,p['budget'],p['plans'][0]['quantity'],consumption(self.j.state),p['plans'][0]['limit'],self.c['additional_cost_per_share'])
            self.j.append('attempt:'+p['id'],'attempt',{'id':p['id'],'leg':0,'fill':f,'book':b,'request_started':now+2,'received_at':now+2,
                'generation_at_reserve':3,'continuity_without_venue_sequence':True,'reason':None},now+2)
            self.j.append('finish:'+p['id'],'finish',{'id':p['id'],'reason':'attempts_complete_hold_to_settlement'},now+3)
            ids.append(p)
        for p in ids:
            self.j.append('credit:'+p['id'],'credit',{'id':p['id'],'proof':proof(p['market'],1501,'Down'),'payout':'0'},1561)
        return ids

    def test_realized_daily_loss_halts_entries_today_and_resumes_next_utc_day(self):
        self.open();self.losing_positions()
        self.assertEqual(realized_losses(self.j.state,self.c,1562)['day'],100)
        self.j.refresh_day(1562);self.assertEqual(self.j.state['day_halts'],['0']);self.assertFalse(self.j.state['halted'])
        self.assertTrue(entries_halted(self.j.state,1562))
        m=metadata('eth',1500,1510);m['condition']='0x'+'f'*64
        with self.assertRaisesRegex(ValueError,'entries_disabled'):
            self.j.append('r','reserve',strategy.plan(m,books(m,1510),prediction(1510),1510,self.c,self.j.state,'directional'),1510+60)
        self.j.refresh_day(86401);self.assertFalse(entries_halted(self.j.state,86401));self.assertEqual(self.j.state['day_halts'],['0'])
        m=metadata('eth',86400,86401);m['condition']='0x'+'9'*64
        self.j.append('r2','reserve',strategy.plan(m,books(m,86401),prediction(86401),86401,self.c,self.j.state,'directional'),86401)

    def test_cumulative_realized_loss_latches_permanently(self):
        self.open(cumulative_loss='100');self.losing_positions()
        self.j.refresh_day(1562);self.assertTrue(self.j.state['halted'])
        self.j.refresh_day(86401);self.assertTrue(entries_halted(self.j.state,86401))

    def test_halt_is_replayed_and_forged_halts_are_rejected(self):
        self.open()
        for data in ({'reason':'daily_realized_loss_limit','day':'0'},{'reason':'cumulative_realized_loss_limit'},{'reason':'daily_loss_limit'}):
            with self.assertRaises(ValueError):self.j.append('forged','halt',data,1000)
        self.losing_positions();self.j.refresh_day(1562);self.j.close()
        self.j=Ledger(self.path,self.c,'bundle',1600);self.assertEqual(self.j.state['day_halts'],['0'])

    def test_winning_settlement_is_not_a_loss(self):
        self.open();m=metadata()
        p=strategy.plan(m,books(m),prediction(),1000,self.c,self.j.state,'directional');self.j.append('r','reserve',p,1000)
        self.assertEqual(portfolio(self.j.state,self.c)['cost_basis_equity'],10000)

    def test_configuration_rejects_cumulative_stop_below_daily_limit(self):
        self.open()
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'c.json';path.write_text(json.dumps({**config(),'cumulative_loss':'50'}))
            with self.assertRaisesRegex(ValueError,'cumulative'):config(path)


class SchedulingAndScoringTests(unittest.TestCase):
    def test_pending_fill_defers_discovery_and_resolution(self):
        import worker
        with tempfile.TemporaryDirectory() as parent:
            s=worker.Study(Path(parent)/'s','test',c={**config(),'minimum_free_bytes':1},start_feeds=False,clock=lambda:1000.)
            try:
                self.assertFalse(s.attempt_due_soon(1000))
                s.journal.state['positions']['x']={'finished':False,'attempts':{},'created_at':999,'budget':'25'}
                self.assertTrue(s.attempt_due_soon(1000))
                calls=[];s.discover=lambda now:calls.append('discover');s.resolve=lambda now:calls.append('resolve');s.attempts=lambda now:None
                s.tick();self.assertEqual(calls,[])
                s.journal.state['positions']={};s.tick();self.assertEqual(calls,['discover','resolve'])
            finally:s.close()

    def test_model_and_market_scored_on_identical_observation(self):
        from worker import connect_index
        from report import build
        c=config()
        with tempfile.TemporaryDirectory() as root:
            path=Path(root);j=Ledger(path/'ledger.sqlite3',c,'bundle',0.);db=connect_index(path/'index.sqlite3')
            base={'asset':'btc','condition':'k','start':300,'end':600,'split':'train','decisions':{}}
            early={**base,'observed_at':310,'market_probability':.5,'model_prediction':None}
            later={**base,'observed_at':325,'market_probability':.7,'model_prediction':{'p_up':.9}}
            for i,o in enumerate((early,later)):db.execute('INSERT INTO observations VALUES(?,?,?,?)',('k',i,canonical(o),digest(o)))
            out={'winner':'Up','confirmed_at':700};db.execute('INSERT INTO outcomes VALUES(?,?,?)',('k',canonical(out),digest(out)));db.commit();db.close()
            r=build(path,now=800);same=r['model_vs_market_same_observation']
            self.assertEqual(r['scores']['market']['brier'],.25)
            self.assertAlmostEqual(same['market']['brier'],.09);self.assertAlmostEqual(same['baseline']['brier'],.01)
            self.assertLess(same['brier_difference_model_minus_market'],0);j.close()

    def test_training_builder_reads_only_train_and_calibration_rows_with_input_times(self):
        from worker import connect_index
        import training
        c=config()
        with tempfile.TemporaryDirectory() as root:
            path=Path(root);j=Ledger(path/'ledger.sqlite3',c,'bundle',0.);db=connect_index(path/'index.sqlite3')
            def obs(start,key):
                return {'asset':'btc','condition':key,'start':start,'end':start+300,'observed_at':start+100,'split':'x','decisions':{},
                    'market_probability':.5,'model_prediction':{'p_up':.6,'features':[.1,.5,0.,0.]},'input_max_received_at':start+99,'input_max_source_at':start+98}
            rows=[(0,'a'),(0,'a2'),(7*86400,'b'),(12*86400,'sel'),(20*86400,'fin')]
            for i,(start,key) in enumerate(rows):
                o=obs(start,key);db.execute('INSERT INTO observations VALUES(?,?,?,?)',(key,i,canonical(o),digest(o)))
                out={'winner':'Up','confirmed_at':start+400};db.execute('INSERT INTO outcomes VALUES(?,?,?)',(key,canonical(out),digest(out)))
            db.commit();db.close()
            data=training.rows(path,c,training.genesis(path)['started_at'])
            self.assertEqual([r['condition'] for r in data],['a','b'])
            self.assertTrue(all(r['input_max_received_at']<=r['observed_at']<r['outcome_available_at'] for r in data));j.close()


if __name__=='__main__':unittest.main()
