"""Read-only evidence routing to installed Vivameda modules. No model or paid calls."""
import importlib.util, json, os, sys, time
from pathlib import Path
import scanner as s

COMPANY_IDS = {'Adobe':'adobe','Microsoft':'microsoft','Alphabet':'google',
               'Amazon':'amazon','Meta':'facebook','NVIDIA':'nvidia','OpenAI':'openai',
               'Anthropic':'anthropic','Tesla':'tesla','Apple':'apple','WeWork':'wework'}

def company_evidence(name, archive):
    # Reuse the reviewed installed workflow; it calls assess(...,allow_paid=False).
    if name not in COMPANY_IDS:
        raise ValueError('Company alias requires explicit mapping')
    sys.path[:0]=['/opt/vivameda-conversations-v2','/opt/vivameda-coresignal']
    from research_workflow import run
    question=('Describe workforce history, current retained observations, financial revenue and earnings, '
              'ownership and corporate events. Separate source dates, reporting entities and workforce '
              'perimeters. Explain missing evidence and why an IPO or valuation forecast is unverified.')
    return run(COMPANY_IDS[name],question,archive)

def crypto_evidence(question):
    path=Path('/opt/vivameda-crypto-agent/crypto_agent.py')
    spec=importlib.util.spec_from_file_location('vivameda_prediction_crypto_read',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    result=module.read_evidence('latest_memory.json')
    if result['status']!='AVAILABLE':return result
    cards=result['data'].get('cases',[])
    # Require an exact mint embedded in the question. Never use unrelated fallback examples.
    matches=[c for c in cards if isinstance(c,dict) and isinstance(c.get('mint'),str)
             and len(c['mint'])>=32 and c['mint'] in question]
    return {'status':'EXACT_MINT_OBSERVATION' if matches else 'NO_EXACT_TOKEN_MATCH',
            'source':result['source'],'sha256':result['sha256'],'cases':matches[:3],
            'generated_at':result['data'].get('generated_at'),
            'limitations':['Solana case observations do not forecast chain-wide price or settlement.',
                           'No exact identity supplied means abstention.'],'live_execution':False}

def enrich(root, limit=2, company_call=company_evidence, crypto_call=crypto_evidence):
    if not 0<=limit<=5:raise ValueError('Bounded research limit exceeded')
    root=Path(root);latest=json.loads((root/'latest.json').read_text())
    if not 0<=time.time()-latest['generated_at']<=900:raise ValueError('Fresh discovery required')
    reports=[];used=0
    with s.connection(root) as db:
        db.execute('CREATE TABLE IF NOT EXISTS evidence(id TEXT PRIMARY KEY, at REAL, body TEXT)')
        for c in latest['shortlist']:
            if used>=limit:break
            if c['blockers']:continue
            lane=c['routing']['lane'];m=c['market']
            names=c['routing']['companies']
            if lane=='company_research' and len(names)==1:
                identity=names[0];key=s.digest(['company',identity,int(time.time()//86400)])
                prior=db.execute('SELECT body FROM evidence WHERE id=?',(key,)).fetchone()
                if prior:
                    reports.append({'market_id':m['id'],'evidence_id':key,'status':'REUSED_DAILY_PACKET',
                                    'probability_range':None});continue
                try:
                    packet=company_call(identity,root/'company-archive')
                    report={'status':'RETAINED_COMPANY_CONTEXT','company':identity,'packet':packet,
                            'entity_membership_verified':False,
                            'scope':'Descriptive context; not an answer or forecast for this contract'}
                except Exception as exc:report={'status':'RESEARCH_UNAVAILABLE','error':type(exc).__name__}
            elif lane=='crypto_research':
                key=s.digest(['crypto',m['id'],latest['run_id']])
                try:report=crypto_call(m['question'])
                except Exception as exc:report={'status':'RESEARCH_UNAVAILABLE','error':type(exc).__name__}
            else:continue
            used+=1
            body={'market_id':m['id'],'snapshot_id':c['snapshot_id'],'report':report,
                  'probability_range':None,'edge':None,'live_execution':False,'paid_provider_requests':0}
            db.execute('INSERT OR IGNORE INTO evidence VALUES (?,?,?)',(key,time.time(),s.packed(body)))
            reports.append({'market_id':m['id'],'evidence_id':key,'status':report['status'],
                            'probability_range':None})
    output={'generated_at':time.time(),'reports':reports,'new_research_packets':used,
            'live_execution':False,'paid_provider_requests':0,
            'scope':'Retained evidence retrieval only; no calibrated event model connected'}
    s.write_json(root,'research_latest.json',output)
    return output

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--state',type=Path,default=s.STATE)
    p.add_argument('--limit',type=int,default=2);a=p.parse_args()
    print(json.dumps(enrich(a.state,a.limit),indent=2))
