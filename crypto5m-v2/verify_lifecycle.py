"""Synthetic integration only: real worker/model/reference/ledger, no network."""
import json
from pathlib import Path
import tempfile
from unittest.mock import patch
from common import config,number
from reference import Reference
from test_study import metadata,books,raw_book,proof
from worker import Study
from ledger import portfolio


def verify():
    clock=[1001.];c=config();c['minimum_free_bytes']=1
    with tempfile.TemporaryDirectory() as parent:
        study=Study(Path(parent)/'synthetic','synthetic-only',c,start_feeds=False,clock=lambda:clock[0])
        try:
            m=metadata();r=Reference()
            rows=[{'timestamp':t*1000,'value':str(100+(t-900)*.01+(.02 if t%2 else 0))} for t in range(900,1001)]
            r.handle({'topic':'crypto_prices','type':'subscribe','timestamp':1000500,'payload':{'symbol':'btc/usd','data':rows}},1000.6)
            r.handle({'topic':'crypto_prices_twap_sixty','type':'subscribe','timestamp':1000500,'payload':{'symbol':'btc/usd','window_s':60,
                'data':[{'timestamp':t*1000,'full_accuracy_value':'100000000000000000000','value':'100'} for t in (900,999,1000)]}},1000.6)
            class Feed:
                generation=3
                def snapshot(self):
                    b=books(m,clock[0]);b['Down']=books(m,clock[0],ask='.55')['Down'];return b
            study.reference=r;study.markets={'btc':m};study.feeds={'btc':Feed()};study.store('markets',m['condition'],m)
            study.journal.refresh_day(clock[0])
            with patch.object(study,'storage_ok',return_value=True):
                study.decide(clock[0]);assert len(study.journal.state['positions'])==1,list(study.db.execute('select body from observations'))
                p=next(iter(study.journal.state['positions'].values()));assert p['prediction']['reference_at']==1000
                clock[0]=1003.
                side=p['plans'][0]['side']
                with patch('market.discover',return_value=({},m)),patch('market.get',return_value=raw_book(m,side,clock[0])):
                    study.attempts(clock[0])
                p=next(iter(study.journal.state['positions'].values()));fill=p['attempts']['0']['fill'];assert fill is not None
                assert p['finished'];assert portfolio(study.journal.state,c)['cash']<10000
                clock[0]=1262.
                with patch('market.resolution',return_value=proof(m,1201,side)):study.resolve(clock[0])
                assert len(study.journal.state['credits'])==1
                cash=portfolio(study.journal.state,c)['cash'];assert cash>10000
                study.resolve(clock[0]);assert portfolio(study.journal.state,c)['cash']==cash
                print(json.dumps({'synthetic_integration_passed':True,'reference_to_forecast_to_reservation':True,'delayed_fill':True,'official_resolution_fixture_credit_once':True,'live_network_calls':0,'prospective_trade':False}))
        finally:study.close()

if __name__=='__main__':verify()
