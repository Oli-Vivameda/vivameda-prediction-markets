import json, tempfile, time, unittest
from pathlib import Path
from unittest.mock import patch
import scanner as s, bridge, notify
from test_scanner import fixture

class Notifications(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)/'state'
        self.scan=s.scan(self.root,1,fixture,2)
        self.research=bridge.enrich(self.root,2,company_call=lambda name,archive:{'evidence':'synthetic'})
        self.messages=[]
        for c in self.scan['shortlist']:
            c['market'].update(slug='adobe-layoffs',event_slug='adobe-event',event_id='KXADOBE-26')
    def tearDown(self):self.tmp.cleanup()
    def sender(self,text):self.messages.append(text);return True
    def test_candidate_sent(self):
        r=notify.dispatch(self.root,self.scan,self.research,self.sender)
        self.assertEqual(r['sent'],1)
        self.assertIn('NOT established',self.messages[0])
        self.assertIn('Live betting: disabled',self.messages[0])
    def test_every_rendered_contract_has_link(self):
        group=next(iter(notify.eligible(self.root,self.scan,self.research,time.time()).values()))
        rendered=notify.message(group)
        self.assertEqual(rendered.count('Open market: '),len(group['items']))
        self.assertIn('https://polymarket.com/event/adobe-event?marketSlug=adobe-layoffs',rendered)
    def test_kalshi_link(self):
        self.assertEqual(notify.market_link({'venue':'kalshi','id':'KXIPO-26-OPENAI','event_id':'KXIPO-26'}),
                         'https://kalshi.com/markets/kxipo?marketTicker=KXIPO-26-OPENAI')
    def test_missing_or_hostile_links_withheld(self):
        for c in self.scan['shortlist']:
            c['market'].update(slug='../bad',event_id='https://evil.example')
        self.assertEqual(notify.dispatch(self.root,self.scan,self.research,self.sender)['sent'],0)
    def test_long_group_keeps_complete_links(self):
        item={'market':{'venue':'polymarket','id':'1','slug':'s'*200,'event_slug':'e'*200,
                       'question':'😀'*1000,'close_at':'2099-01-01T00:00:00Z'},
              'price':.4,'evidence_id':'a'*64}
        text=notify.message({'heading':'h'*1000,'items':[item]*4})
        self.assertLessEqual(len(text.encode('utf-16-le'))//2,3900)
        self.assertEqual(text.count(notify.market_link(item['market'])),3)
    def test_sender_refuses_truncation_before_credentials(self):
        with self.assertRaisesRegex(ValueError,'too long'):
            notify.send('😀'*2000,credentials='/does/not/exist')
    def test_event_slug_retained(self):
        from test_scanner import poly
        self.assertEqual(s.normalize_poly(poly(slug='contract',events=[{'slug':'parent'}]),1)['event_slug'],'parent')
    def test_correlated_contracts_grouped(self):
        self.assertEqual(len(notify.eligible(self.root,self.scan,self.research,time.time())),1)
    def test_no_duplicate(self):
        notify.dispatch(self.root,self.scan,self.research,self.sender)
        r=notify.dispatch(self.root,self.scan,self.research,self.sender)
        self.assertEqual(len(self.messages),1);self.assertEqual(r['deduplicated'],1)
    def test_no_evidence_no_alert(self):
        r=notify.dispatch(self.root,self.scan,{'reports':[]},self.sender)
        self.assertEqual(r['sent'],0)
    def test_stale_scan_refused(self):
        with self.assertRaises(ValueError):
            notify.dispatch(self.root,self.scan,self.research,self.sender,now=time.time()+901)
    def test_blockers_withhold(self):
        for c in self.scan['shortlist']:c['blockers']=['unresolved_company']
        self.assertEqual(notify.dispatch(self.root,self.scan,self.research,self.sender)['sent'],0)
    def test_missing_price_withholds_contract(self):
        for c in self.scan['shortlist']:c['market']['yes_price_reference']=None
        self.assertEqual(notify.dispatch(self.root,self.scan,self.research,self.sender)['sent'],0)
    def test_failed_delivery_not_marked_sent(self):
        def fail(text):raise TimeoutError('secret URL not logged')
        r=notify.dispatch(self.root,self.scan,self.research,fail)
        self.assertEqual(r['failed'],1)
        self.assertNotIn('secret',json.dumps(r))
        self.assertEqual(notify.dispatch(self.root,self.scan,self.research,self.sender)['sent'],1)
    def test_closed_withholds(self):
        for c in self.scan['shortlist']:c['market']['open']=False
        self.assertEqual(notify.dispatch(self.root,self.scan,self.research,self.sender)['sent'],0)
    def test_failed_feed_withholds(self):
        for f in self.scan['feeds'].values():f['error']='TimeoutError'
        self.assertEqual(notify.dispatch(self.root,self.scan,self.research,self.sender)['sent'],0)
    def test_startup_once(self):
        notify.startup(self.root,self.sender);notify.startup(self.root,self.sender)
        self.assertEqual(len(self.messages),1)
    def test_unknown_crypto_not_alerted(self):
        for c in self.scan['shortlist']:c['routing']['lane']='crypto_coverage_gap'
        self.assertEqual(notify.dispatch(self.root,self.scan,self.research,self.sender)['sent'],0)

if __name__=='__main__':unittest.main()
