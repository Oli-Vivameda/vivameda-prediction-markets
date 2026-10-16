"""Version 4: in-place book updates (throughput), REST tick/minimum refresh on every
(re)connection, invalid-level diagnostics, processing instrumentation and unit limits."""
import random
import time
import unittest
from pathlib import Path
import tempfile
from unittest.mock import patch
from common import D,config,number
import market
from feeds import Books
from test_study import metadata,raw_book


def deep_book(m,side,now=1000,tick='0.01'):
    return {'asset_id':m['tokens'][side],'market':m['condition'],'timestamp':now,'min_order_size':'5','tick_size':tick,
        'bids':[{'price':f'{i*0.01:.2f}','size':str(10+i)} for i in range(1,46)],
        'asks':[{'price':f'{i*0.01:.2f}','size':str(10+i)} for i in range(52,97)]}

def feed_with(m,books_raw,now=1000,refresh=None):
    f=Books(m,books_raw,refresh=refresh)
    for side in ('Up','Down'):f.handle({**books_raw[side],'event_type':'book'},now)
    f.alive(now);return f

def random_events(m,count,seed=11,start=1000):
    rng=random.Random(seed);out=[]
    for i in range(count):
        rows=[]
        for _ in range(rng.choice((1,1,2,4))):
            side=rng.choice(('Up','Down'));buy=rng.random()<.5
            p=f'{rng.randint(1,45)*0.01:.2f}' if buy else f'{rng.randint(52,96)*0.01:.2f}'
            rows.append({'asset_id':m['tokens'][side],'side':'BUY' if buy else 'SELL','price':p,'size':str(rng.randint(0,500))})
        out.append({'event_type':'price_change','market':m['condition'],'timestamp':start+(i+1)*0.001,'price_changes':rows})
    return out


class ThroughputAndEquivalenceTests(unittest.TestCase):
    def test_in_place_updates_match_naive_full_reconstruction(self):
        m=metadata();raw={s:deep_book(m,s) for s in ('Up','Down')};f=feed_with(m,raw)
        naive={s:{k:{number(r['price']):number(r['size']) for r in raw[s][k]} for k in ('bids','asks')} for s in ('Up','Down')}
        events=random_events(m,2000)
        for i,e in enumerate(events):
            f.handle(e,1000.5+i*0.001)
            for r in e['price_changes']:
                s=next(k for k,t in m['tokens'].items() if t==r['asset_id']);lvl=naive[s]['bids' if r['side']=='BUY' else 'asks']
                p,n=number(r['price']),number(r['size'])
                if n:lvl[p]=n
                else:lvl.pop(p,None)
        f.alive(1003);snap=f.snapshot()
        for s in ('Up','Down'):
            for k,rev in (('bids',True),('asks',False)):
                expected=[[format(p.normalize(),'f'),str(n)] for p,n in sorted(naive[s][k].items(),reverse=rev)][:20]
                self.assertEqual(snap[s][k],expected)
            self.assertEqual(snap[s]['snapshot_id'],market.book({'asset_id':m['tokens'][s],'market':m['condition'],'timestamp':snap[s]['source_at'],
                'min_order_size':'5','tick_size':'0.01',**{k:[{'price':format(p.normalize(),'f'),'size':str(n)} for p,n in naive[s][k].items()] for k in ('bids','asks')}},
                m['tokens'][s],m['condition'],snap[s]['received_at'],f.generation,allow_empty=True,check_age=False)['snapshot_id'])

    def test_delta_processing_is_fast_enough_for_observed_venue_rates(self):
        # v3 measured ~0.7 ms per event and saturated a core at ~700 events/s on the server.
        m=metadata();f=feed_with(m,{s:deep_book(m,s) for s in ('Up','Down')});events=random_events(m,3000,seed=3)
        started=time.perf_counter()
        for i,e in enumerate(events):
            f.handle(e,1000.5+i*0.001)
            if i%300==0:f.alive(1000.5+i*0.001);f.snapshot()
        per_event=(time.perf_counter()-started)/len(events)
        self.assertLess(per_event,0.00015,f'{per_event*1e6:.0f} us per event')

    def test_snapshot_is_a_copy_not_a_live_view(self):
        m=metadata();f=feed_with(m,{s:raw_book(m,s) for s in ('Up','Down')});snap=f.snapshot()
        f.handle({'event_type':'price_change','market':m['condition'],'timestamp':1001,
            'price_changes':[{'asset_id':m['tokens']['Up'],'side':'BUY','price':'.44','size':'7'}]},1001)
        self.assertNotIn(['0.44','7'],snap['Up']['bids'])


class RuleRefreshTests(unittest.TestCase):
    def test_reconnect_refreshes_tick_and_minimum_from_rest(self):
        m=metadata();rest={s:raw_book(m,s) for s in ('Up','Down')}
        fresh={s:{**raw_book(m,s),'tick_size':'0.001','min_order_size':'6'} for s in ('Up','Down')}
        f=Books(m,rest,refresh=lambda token:fresh['Up' if token==m['tokens']['Up'] else 'Down'])
        f.refresh_rules()
        self.assertEqual(f.ticks,{'Up':'0.001','Down':'0.001'});self.assertEqual(f.minimums['Up'],'6');self.assertEqual(f.rule_refreshes,1)
        f.handle({**raw_book(m,'Up'),'event_type':'book','asks':[{'price':'.465','size':'10'}]},1000)

    def test_refresh_rejects_wrong_identity_or_invalid_rules(self):
        m=metadata();rest={s:raw_book(m,s) for s in ('Up','Down')}
        for bad in ({'market':'0xother'},{'tick_size':'1'},{'min_order_size':'0'}):
            f=Books(m,rest,refresh=lambda token,bad=bad:{**raw_book(m,'Up' if token==m['tokens']['Up'] else 'Down'),**bad})
            with self.assertRaises(ValueError):f.refresh_rules()
            self.assertEqual(f.ticks['Up'],rest['Up']['tick_size'])

    def test_stale_tick_loop_is_broken_by_refresh(self):
        m=metadata();rest={s:raw_book(m,s) for s in ('Up','Down')};f=Books(m,rest)
        finer={**raw_book(m,'Up'),'event_type':'book','asks':[{'price':'.465','size':'10'}]}
        with self.assertRaisesRegex(ValueError,'invalid_book_level'):f.handle(finer,1000)
        self.assertEqual(f.last_invalid['why'],'off_tick');self.assertEqual(f.last_invalid['price'],'0.465');self.assertEqual(f.last_invalid['tick'],'0.01')
        f.set_rules({s:{**raw_book(m,s),'tick_size':'0.001'} for s in ('Up','Down')});f.handle(finer,1000)

    def test_off_tick_delta_is_diagnosed_and_forces_resync(self):
        m=metadata();f=feed_with(m,{s:raw_book(m,s) for s in ('Up','Down')})
        with self.assertRaisesRegex(ValueError,'invalid_book_level'):
            f.handle({'event_type':'price_change','market':m['condition'],'timestamp':1001,
                'price_changes':[{'asset_id':m['tokens']['Down'],'side':'SELL','price':'.555','size':'3'}]},1001)
        self.assertEqual(f.last_invalid,{'side':'Down','book_side':'asks','price':'0.555','size':'3','tick':'0.01','why':'off_tick'})


class OperationsTests(unittest.TestCase):
    def test_status_reports_processing_rules_and_invalid_details(self):
        m=metadata();s=Books(m,{x:raw_book(m,x) for x in ('Up','Down')}).status()
        for key in ('frames','processing_seconds_total','processing_seconds_max_frame','last_invalid_level','rule_refreshes','rule_refresh_errors'):self.assertIn(key,s)

    def test_worker_wires_rest_refresh_into_book_feeds(self):
        import worker
        m=metadata(now=1000)
        with tempfile.TemporaryDirectory() as parent:
            s=worker.Study(Path(parent)/'s','test',c={**config(),'minimum_free_bytes':1},start_feeds=False,clock=lambda:1000.)
            try:
                with patch('market.discover',return_value=({},m)),patch('market.get',side_effect=lambda url:raw_book(m,'Up' if url.endswith(m['tokens']['Up']) else 'Down')):
                    s.discover(1000)
                self.assertIsNotNone(s.feeds['btc'].refresh_source)
            finally:s.close()

    def test_unit_is_current_version_with_one_core_quota(self):
        import install
        body=install.definition(Path('/tmp/v4-state'),123,'a'*64)
        self.assertIn('CPUQuota=100%',body);self.assertIn('/opt/vivameda-crypto5m-study-v5/worker.py',body)
        self.assertEqual(install.UNIT,'vivameda-crypto5m-study-v5.service')


if __name__=='__main__':unittest.main()
