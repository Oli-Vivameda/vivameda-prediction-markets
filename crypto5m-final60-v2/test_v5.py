"""Version 5: transient crossed books are tolerated (never tradeable) and resynchronized
only when they persist; crossing evidence is recorded; repeat entries get a clear label."""
from pathlib import Path
import tempfile
import unittest
from common import config
import market
import strategy
from feeds import Books
from test_study import metadata,raw_book,books,prediction


def live(m=None,grace=2):
    m=m or metadata();rest={s:raw_book(m,s) for s in ('Up','Down')};f=Books(m,rest,crossed_grace=grace)
    for s in ('Up','Down'):f.handle({**rest[s],'event_type':'book'},1000)
    f.alive(1000);return m,f

def change(m,ts,side,price,size,token='Up'):
    return {'event_type':'price_change','market':m['condition'],'timestamp':ts,
        'price_changes':[{'asset_id':m['tokens'][token],'side':side,'price':price,'size':size}]}


class CrossingTests(unittest.TestCase):
    def test_transient_cross_resolved_by_next_event_keeps_connection(self):
        # raw_book: bid .45 / ask .46. A buy at .47 crosses until the .46 ask is removed.
        m,f=live();f.handle(change(m,1000.5,'SELL','.48','10'),1000.5);g=f.generation
        f.handle(change(m,1001,'BUY','.47','10'),1001.0)
        self.assertEqual(f.crossing_episodes,1);self.assertEqual(f.status()['crossed_now'],['Up'])
        with self.assertRaisesRegex(ValueError,'crossed'):f.snapshot()
        f.handle(change(m,1001.01,'SELL','.46','0'),1001.01)
        self.assertEqual(f.generation,g);self.assertEqual(f.crossings_resolved,1);self.assertEqual(f.status()['crossed_now'],[])
        self.assertAlmostEqual(f.crossing_max_seconds,.01,places=6)
        b=f.snapshot()['Up'];self.assertEqual(b['bids'][0][0],'0.47');market.healthy(b,m,1001.2,config())

    def test_persistent_cross_forces_resync_after_grace(self):
        m,f=live(grace=2)
        f.handle(change(m,1001,'BUY','.47','10'),1001)
        f.handle(change(m,1002,'BUY','.30','5'),1002)
        with self.assertRaisesRegex(ValueError,'persistent_crossed_book'):f.handle(change(m,1003.5,'BUY','.31','5'),1003.5)

    def test_persistent_cross_is_caught_even_without_further_events(self):
        m,f=live(grace=2);f.handle(change(m,1001,'BUY','.47','10'),1001)
        f.check_crossing(1002.9)
        with self.assertRaisesRegex(ValueError,'persistent_crossed_book'):f.check_crossing(1003.1)

    def test_fresh_snapshot_resolves_a_crossing(self):
        m,f=live();f.handle(change(m,1001,'BUY','.47','10'),1001)
        f.handle({**raw_book(m,'Up',1001.5),'event_type':'book'},1001.5)
        self.assertEqual(f.crossings_resolved,1);self.assertEqual(f.status()['crossed_now'],[])

    def test_crossed_full_snapshot_is_still_fatal(self):
        m,f=live();bad={**raw_book(m,'Up',1001),'event_type':'book'};bad['bids']=[{'price':'.50','size':'1'}]
        with self.assertRaisesRegex(ValueError,'crossed'):f.handle(bad,1001)

    def test_crossed_book_can_never_reach_a_decision(self):
        m,f=live();f.handle(change(m,1001,'BUY','.47','10'),1001)
        with self.assertRaises(ValueError):f.snapshot()

    def test_reconnect_clears_crossing_state(self):
        m,f=live();f.handle(change(m,1001,'BUY','.47','10'),1001);f.clear('reconnecting')
        self.assertEqual(f.status()['crossed_now'],[])

    def test_configuration_bounds_crossing_grace(self):
        import json
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'c.json';p.write_text(json.dumps({**config(),'crossed_grace_seconds':10}))
            with self.assertRaisesRegex(ValueError,'grace'):config(p)


class EntryLabelTests(unittest.TestCase):
    def test_second_decision_in_same_window_is_labelled_not_invalid(self):
        import worker,model,json
        m=metadata(now=1170);now=1170.
        class Feed:
            generation=3
            def snapshot(self):
                b=books(m,now)
                for x in b.values():x['confirmed_at']=now;x['stream_lag']=.1
                return b
        with tempfile.TemporaryDirectory() as parent:
            s=worker.Study(Path(parent)/'s','test',c={**config(),'minimum_free_bytes':1},start_feeds=False,clock=lambda:now)
            try:
                s.markets={'btc':m};s.feeds={'btc':Feed()};s.journal.refresh_day(now)
                p=strategy.plan(m,books(m,now),prediction(now),now,s.config,s.journal.state,'directional')
                s.journal.append('reserve:'+p['id'],'reserve',p,now)
                s.storage_ok=lambda:True
                s.reference.inputs=lambda m,t:({'points':[{'received_at':1169,'source_at':1169}]},{'received_at':900,'source_at':900})
                original=model.predict_final;model.predict_final=lambda *a:prediction(now)
                try:s.decide(now)
                finally:model.predict_final=original
                record=json.loads(s.db.execute('SELECT body FROM observations').fetchone()[0])
                self.assertEqual(record['decisions']['directional'],'SKIP:already_entered_this_window')
            finally:s.close()


if __name__=='__main__':unittest.main()
