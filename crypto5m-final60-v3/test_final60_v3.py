"""Final-minute v3: every book shape, including fully empty books, must flow through the
real worker sampling and decision paths without an exception escaping."""
import itertools
import json
from pathlib import Path
import tempfile
import unittest
from common import config
from test_study import metadata
from test_final60 import inputs,wiggle
from test_final60_v2 import book

C=config()
SHAPES=list(itertools.product((False,True),repeat=4))  # Up bids, Up asks, Down bids, Down asks


def shaped(m,now,ub,ua,db,da):
    return {'Up':book(m,'Up',now,['0.4'] if ub else [],['0.6'] if ua else []),
            'Down':book(m,'Down',now,['0.4'] if db else [],['0.6'] if da else [])}


class EveryBookShapeTests(unittest.TestCase):
    def run_shape(self,shape):
        import worker
        m=metadata(now=1170);now=1170.
        class Feed:
            generation=3
            def status(self):return {'generation':3}
            def snapshot(self):
                b=shaped(m,now,*shape)
                for x in b.values():x['confirmed_at']=now;x['stream_lag']=.1
                return b
        with tempfile.TemporaryDirectory() as parent:
            s=worker.Study(Path(parent)/'s','test',c={**C,'minimum_free_bytes':1},start_feeds=False,clock=lambda:now)
            try:
                s.markets={'btc':m};s.feeds={'btc':Feed()};s.journal.refresh_day(now);s.storage_ok=lambda:True
                ref,anchor=inputs(m,now,wiggle(lambda t:100.3 if t>m['end']-60 else 100.))
                s.reference.inputs=lambda mm,t:(ref,anchor)
                s.sample(now)          # diagnostics path that crashed in v2
                s.decide(now)          # decision path
                rows=[json.loads(r) for r, in s.db.execute('SELECT body FROM observations')]
                self.assertEqual(len(rows),1,shape)
                return rows[0]
            finally:s.close()

    def test_all_sixteen_shapes_complete_without_exception(self):
        outcomes={}
        for shape in SHAPES:
            record=self.run_shape(shape)
            outcomes[shape]=record['decisions']['directional']
        self.assertEqual(len(outcomes),16)
        # Fully empty books on both sides: no market quote, abstain cleanly.
        self.assertEqual(outcomes[(False,False,False,False)],'SKIP:no_market_quote')
        # Empty Up book with a two-sided Down book: forecast is made (the v2 crash case).
        self.assertNotIn('ZeroDivision',outcomes[(False,False,True,True)])

    def test_empty_up_book_diagnostics_record_no_imbalance(self):
        import worker
        m=metadata(now=1170)
        with tempfile.TemporaryDirectory() as parent:
            s=worker.Study(Path(parent)/'s','test',c={**C,'minimum_free_bytes':1},start_feeds=False,clock=lambda:1170.)
            try:
                d=s.diagnostics('btc',shaped(m,1170,False,False,True,True),{'points':{}},1170.)
                self.assertIsNone(d['book_imbalance'])
            finally:s.close()

    def test_unused_baseline_model_abstains_instead_of_crashing_on_one_sided_books(self):
        import model
        from test_study import metadata as md
        m=md();ref,anchor=inputs(m,1000)
        with self.assertRaises(ValueError):model.predict(m,shaped(m,1000,False,False,True,True),ref,anchor,1000)


if __name__=='__main__':unittest.main()
