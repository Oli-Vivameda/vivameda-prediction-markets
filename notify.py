"""Owner-authorized Telegram research candidates. No order API or credentials in logs."""
import argparse, json, os, re, sqlite3, time
from pathlib import Path
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler
from urllib.parse import urlencode
import scanner as s

CREDS = Path('/opt/vivameda-prediction-scanner/telegram_credentials.json')

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError('Telegram redirect refused')

def send(text, credentials=CREDS):
    if len(text.encode('utf-16-le'))//2 > 3900:
        raise ValueError('Telegram message too long; refuse to truncate links')
    c=json.loads(Path(credentials).read_text())
    token=c.get('bot_token'); chat=c.get('chat_id')
    if not isinstance(token,str) or not re.fullmatch(r'[0-9]+:[A-Za-z0-9_-]+',token) or not chat:
        raise ValueError('Configured Telegram destination required')
    body=urlencode({'chat_id':str(chat),'text':text,
                    'disable_web_page_preview':'true'}).encode()
    req=Request('https://api.telegram.org/bot'+token+'/sendMessage',data=body,method='POST')
    opener=build_opener(ProxyHandler({}),NoRedirect())
    with opener.open(req,timeout=12) as response:
        raw=response.read(100000)
    result=json.loads(raw)
    if result.get('ok') is not True:raise ValueError('Telegram delivery rejected')
    return True

def market_link(m):
    """Construct first-party links from bounded identifiers, never market text URLs."""
    def identifier(value):
        return isinstance(value,str) and len(value)<=200 and re.fullmatch(r'[A-Za-z0-9_-]+',value)
    if m.get('venue')=='polymarket' and identifier(m.get('slug')):
        event=m.get('event_slug') or m['slug']
        if identifier(event):
            return 'https://polymarket.com/event/'+event+'?'+urlencode({'marketSlug':m['slug']})
    if m.get('venue')=='kalshi' and identifier(m.get('id')) and identifier(m.get('event_id')):
        series=m['event_id'].split('-')[0]
        return 'https://kalshi.com/markets/'+series.lower()+'?'+urlencode({'marketTicker':m['id']})
    return None

def eligible(root, scan, research, now):
    if not 0<=now-scan.get('generated_at',0)<=900:
        raise ValueError('Fresh scan required')
    groups={}
    with s.connection(root) as db:
        reports={r['market_id']:r for r in research.get('reports',[])}
        for c in scan.get('shortlist',[]):
            m=c['market']; lane=c['routing']['lane']
            if c.get('blockers') or not m.get('open') or s.timestamp(m.get('close_at')) is None or s.timestamp(m['close_at'])<=now:
                continue
            if scan['feeds'].get(m['venue'],{}).get('error') is not None:continue
            if not 0<=now-m.get('observed_at',0)<=900:continue
            price=s.probability(m.get('yes_price_reference'))
            if price is None or market_link(m) is None:continue
            ref=reports.get(m['id'])
            if not ref:continue
            row=db.execute('SELECT at,body FROM evidence WHERE id=?',(ref.get('evidence_id'),)).fetchone()
            if not row or not 0<=now-row[0]<=86400:continue
            packet=json.loads(row[1])['report']
            if lane=='company_research':
                if packet.get('status')!='RETAINED_COMPANY_CONTEXT':continue
                names=c['routing']['companies']
                if len(names)!=1:continue
                events=[e for e in s.COMPANY_EVENTS if s.contains(m['question'].lower(),e)]
                family='ipo' if 'ipo' in events else (events[0] if events else 'company_event')
                key=s.digest(['company',names[0],family])
                heading=names[0]+' / '+family
            elif lane=='crypto_research':
                if packet.get('status')!='EXACT_MINT_OBSERVATION' or not packet.get('cases'):continue
                key=s.digest(['crypto',sorted(x['mint'] for x in packet['cases'])])
                heading='Solana exact-token observation'
            else:continue
            g=groups.setdefault(key,{'heading':heading,'items':[]})
            g['items'].append({'market':m,'evidence_id':ref['evidence_id'],'price':price})
    return groups

def bounded_text(value, units):
    return value.encode('utf-16-le')[:units*2].decode('utf-16-le',errors='ignore')

def message(group):
    items=group['items']
    lines=['VIVAMEDA | Prediction-market research candidate',
           bounded_text(group['heading'],150),str(len(items))+' related contract(s).',
           'Evidence match found; betting advantage NOT established.']
    for item in items[:3]:
        m=item['market']
        lines += ['',bounded_text(m['question'],250),
                  'Venue: '+m['venue']+' | ID: '+str(m['id'])[:120],
                  'YES reference: '+format(item['price']*100,'.1f')+'% (not an executable quote)',
                  'Platform deadline: '+m['close_at'][:50],
                  'Retained evidence: '+item['evidence_id'][:16]]
        link=market_link(m)
        if not link:raise ValueError('Direct market link required')
        lines.append('Open market: '+link)
    if len(items)>3:lines.append('Additional related contracts: '+str(len(items)-3))
    lines += ['', 'Review required: exact identity, settlement rules, fresh evidence, depth and costs.',
              'Our probability: not assessed. Live betting: disabled.']
    return '\n'.join(lines)

def dispatch(root, scan, research, sender=send, now=None):
    now=time.time() if now is None else now
    groups=eligible(root,scan,research,now)
    sent=failed=skipped=0
    with s.connection(root) as db:
        db.execute('CREATE TABLE IF NOT EXISTS telegram_notifications(key TEXT PRIMARY KEY, fingerprint TEXT, at REAL)')
        for key,g in groups.items():
            fingerprint=s.digest(sorted((i['market']['venue'],i['market']['id'],s.digest(i['market']['rules'])) for i in g['items']))
            row=db.execute('SELECT fingerprint,at FROM telegram_notifications WHERE key=?',(key,)).fetchone()
            if row and (row[0]==fingerprint or now-row[1]<3600):
                skipped+=1;continue
            if sent>=3:break
            try:
                if sender(message(g)) is not True:raise ValueError('Delivery not confirmed')
            except Exception:
                failed+=1;continue # Never log HTTP exception: token is embedded in the Telegram URL.
            db.execute('INSERT OR REPLACE INTO telegram_notifications VALUES (?,?,?)',(key,fingerprint,now))
            db.commit();sent+=1
    result={'sent':sent,'failed':failed,'deduplicated':skipped,'eligible_groups':len(groups),
            'generated_at':now,'live_execution':False,
            'scope':'Research candidates; no validated probability or profitable edge',
            'delivery_limit':'Ambiguous network failure can cause a duplicate on a later retry'}
    s.write_json(root,'telegram_latest.json',result)
    return result

def startup(root, sender=send):
    marker=Path(root)/'telegram_startup.json'
    if marker.exists():return {'startup_sent':False,'already_confirmed':True}
    if sender('VIVAMEDA prediction-market scanner activated.\nScans every hour on Hetzner, independently of your laptop.\nTelegram alerts: evidence-supported research candidates, grouped and deduplicated.\nLive betting disabled; no demonstrated betting advantage.') is not True:
        raise ValueError('Startup delivery not confirmed')
    s.write_json(root,'telegram_startup.json',{'confirmed_at':time.time(),'startup_sent':True})
    return {'startup_sent':True}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('command',choices=['startup']);p.add_argument('--state',type=Path,default=s.STATE)
    a=p.parse_args()
    try:print(json.dumps(startup(a.state)))
    except Exception:raise SystemExit('Telegram delivery failed; check server configuration without exposing credentials')
