import copy
import unittest
from common import config,number
from reference import Reference
from test_study import metadata,raw_book
from feeds import Books
import market


def event(twap=False,asset='btc',times=None):
    times=[998,999,1000] if times is None else times
    return {'topic':'crypto_prices_twap_sixty' if twap else 'crypto_prices','type':'subscribe','timestamp':1000500,
        'payload':{'symbol':asset+'/usd',**({'window_s':60} if twap else {}),
                   'data':[{'timestamp':t*1000,'value':'100',**({'full_accuracy_value':'100000000000000000000'} if twap else {})} for t in times]}}

class ReferenceTests(unittest.TestCase):
    def test_snapshot_decimal_units_and_all_asset_mapping(self):
        r=Reference()
        for a in ('btc','eth','sol'):
            r.handle(event(asset=a),1000.6);r.handle(event(True,a),1000.6)
            self.assertEqual(number(r.twaps[a][1000]['price']),100)
            self.assertEqual(number(r.points[a][1000]['price']),100)
    def test_anchor_requires_exact_market_start_never_nearest_point(self):
        r=Reference();r.handle(event(),1000.6);r.handle(event(True),1000.6)
        with self.assertRaisesRegex(ValueError,'exact_opening'):r.inputs(metadata(),1001)
        m=metadata(start=900);m['start']=999
        raw,anchor=r.inputs(m,1001);self.assertEqual(anchor['source_at'],999);self.assertEqual(raw['twap_source'],m['source'])
    def test_no_lookahead_stale_envelope_or_stale_latest(self):
        for mode in ('future','envelope','latest'):
            r=Reference();v=event()
            if mode=='future':v['payload']['data'][-1]['timestamp']=1002000
            if mode=='envelope':v['timestamp']=990000
            if mode=='latest':v['payload']['data']=v['payload']['data'][:1];v['payload']['data'][0]['timestamp']=995000
            with self.assertRaises(ValueError):r.handle(v,1000.6)
    def test_wrong_vendor_symbol_and_twap_window(self):
        for key,value in (('source','pyth'),('symbol','btcusdt'),('window_s',30)):
            v=event(True);v['payload'][key]=value
            with self.assertRaises(ValueError):Reference().handle(v,1000.6)
    def test_revision_rejected_and_original_received_time_retained(self):
        r=Reference();r.handle(event(),1000.6);r.handle(event(),1001)
        self.assertEqual(r.points['btc'][1000]['received_at'],1000.6)
        v=event();v['payload']['data'][-1]['value']='101'
        with self.assertRaisesRegex(ValueError,'revision'):r.handle(v,1001)
        self.assertEqual(number(r.points['btc'][1000]['price']),100)
    def test_reordered_duplicate_nan_and_empty_history_rejected(self):
        for mode in ('order','duplicate','nan','empty'):
            v=event()
            if mode=='order':v['payload']['data'].reverse()
            if mode=='duplicate':v['payload']['data'].append(copy.deepcopy(v['payload']['data'][-1]))
            if mode=='nan':v['payload']['data'][0]['value']='NaN'
            if mode=='empty':v['payload']['data']=[]
            with self.assertRaises(ValueError):Reference().handle(v,1000.6)
    def test_old_merged_points_do_not_gain_new_received_times(self):
        r=Reference();r.handle(event(),1000.6);v=event(times=[999,1000,1001]);v['timestamp']=1001500;r.handle(v,1001.6)
        self.assertEqual(r.points['btc'][1000]['received_at'],1000.6)
        self.assertEqual(r.points['btc'][1001]['received_at'],1001.6)
    def test_stale_snapshot_rejection_preserves_other_assets_without_bypassing_age(self):
        r=Reference();r.handle(event(),1000.6);r.handle(event(True),1000.6)
        r.accept(event(asset='eth'),1005)
        self.assertEqual(r.stale_snapshots_rejected,1);self.assertEqual(r.disconnects,0)
        self.assertEqual(len(r.points['btc']),3);self.assertEqual(r.error,None)
        m=metadata();m['start']=999
        with self.assertRaisesRegex(ValueError,'stale'):r.inputs(m,1005)

    def test_capture_emits_each_point_once_without_repeated_history(self):
        r=Reference();r.handle(event(),1000.6);r.handle(event(True),1000.6)
        first=r.snapshot();self.assertEqual(len(first['raw']['btc']),3)
        second=r.snapshot();self.assertEqual(second['raw']['btc'],[]);self.assertEqual(second['twap60']['btc'],[])

    def test_empty_book_can_be_followed_but_never_used_for_trade(self):
        m=metadata();rest={s:raw_book(m,s) for s in ('Up','Down')};feed=Books(m,rest)
        v={**rest['Up'],'event_type':'book','bids':[]};feed.handle(v,1000)
        feed.handle({**rest['Down'],'event_type':'book'},1000)
        with self.assertRaisesRegex(ValueError,'empty_book'):market.healthy(feed.snapshot()['Up'],m,1000,config())
        feed.handle({'market':m['condition'],'event_type':'price_change','timestamp':1001,
                     'price_changes':[{'asset_id':m['tokens']['Up'],'side':'BUY','price':'.45','size':'100'}]},1001)
        market.healthy(feed.snapshot()['Up'],m,1001,config());self.assertEqual(feed.generation,0)
    def test_crossed_books_still_rejected_even_in_collect_mode(self):
        m=metadata();v=raw_book(m);v['bids'][0]['price']='.50'
        with self.assertRaisesRegex(ValueError,'crossed'):market.book(v,m['tokens']['Up'],m['condition'],1000,allow_empty=True)

if __name__=='__main__':unittest.main()
