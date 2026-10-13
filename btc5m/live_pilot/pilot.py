"""Owner-operated $10 software pilot. Default preview; assistant never activates it."""
import dataclasses
import argparse,fcntl,getpass,hashlib,json,os,re,time,urllib.request
from datetime import datetime,timezone
from pathlib import Path
from decimal import Decimal
from risk import Ledger
from planning import plan
from venue import Venue,load_secret

FEED='http://127.0.0.1:8765/api/state'
GEO='https://polymarket.com/api/geoblock'

def read_json(url):
    with urllib.request.urlopen(url,timeout=10) as r:return json.load(r)

def eligibility():
    try:
        r=read_json(GEO)
        if r.get('blocked') is not False or not r.get('country'):raise ValueError('Not verified eligible')
        return {'eligible':True,'country':r['country'],'checked_at':time.time()}
    except Exception:return {'eligible':False,'reason':'venue_eligibility_unverified_or_blocked','checked_at':time.time()}

def active_guard(state,now):
    h=(state.get('operations') or {}).get('health') or {}
    if h.get('mode')!='healthy' or not h.get('shadow_allowed') or not 0<=now-h.get('checked_at',0)<=10:raise ValueError('Paper feed health unavailable')
    c=state.get('capture') or {}
    if not c.get('healthy') or c.get('dropped',0):raise ValueError('Recording unavailable')
    d=(state.get('shadow') or {}).get('latest_decision')
    if not d or d.get('side') is None:raise ValueError('No locked trade candidate')
    if not 2<=now-d['decision_time']<=5:raise ValueError('Wait for next eligible decision')
    return d

def execute(ledger,venue,p,stop,clock=time.time,deadline=float('inf')):
    condition=p['condition_id']
    if stop.exists() or clock()>=deadline:raise ValueError('STOP flag or window deadline')
    balance=venue.balance();ledger.reserve(p,balance)
    try:
        signed=venue.sign(p)
        if stop.exists() or clock()>=deadline or clock()-p['decision_time']>5:raise ValueError('Entry stopped or expired before submission')
    except Exception:
        ledger.transition(condition,'aborted',{'reason':'pre_submission_guard'});raise
    digest=hashlib.sha256(json.dumps(dataclasses.asdict(signed) if dataclasses.is_dataclass(signed) else vars(signed),sort_keys=True).encode()).hexdigest()
    ledger.transition(condition,'submitting',{'signed_order_digest':digest,'signed_maker_amount':signed.maker_amount,'signed_taker_amount':signed.taker_amount})
    try:
        response=venue.post(signed)
    except Exception:
        ledger.transition(condition,'unknown',{'reason':'submission_response_uncertain'});raise RuntimeError('Submission unknown; no retries, reconcile privately') from None
    if not response.ok:
        ledger.transition(condition,'rejected',{'reason':'venue_rejected'});raise RuntimeError('Venue rejected pilot order; pilot stopped')
    ledger.transition(condition,'accepted',{'venue_status':response.status},str(response.order_id))
    try:
        details=venue.confirm(response,p)
        after=venue.balance()
        debit=balance-after
        if debit<0 or debit>Decimal('3'):raise ValueError('Balance debit outside reserved bounds')
        details['observed_collateral_debit']=str(debit)
        ledger.transition(condition,'confirmed',details)
    except Exception:
        ledger.transition(condition,'unknown',{'reason':'fill_or_cost_reconciliation_incomplete'});raise RuntimeError('Fill reconciliation incomplete; pilot stopped') from None

def resolve(ledger):
    for r in ledger.rows():
        if r['state']!='confirmed':continue
        p=json.loads(r['plan']);m=read_json('https://clob.polymarket.com/markets/'+p['condition_id'])
        winners=[t for t in m.get('tokens',[]) if t.get('winner') is True]
        if m.get('condition_id')==p['condition_id'] and m.get('closed') and len(winners)==1:
            ledger.transition(r['condition'],'resolved',{'winner':winners[0]['outcome'],'cash_redeemed':False})

def configure(path):
    if os.geteuid()==0:raise ValueError('Configure privately as the intended non-root owner')
    p=Path(path)
    if p.exists():raise ValueError('Existing secret preserved')
    p.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    if p.parent.is_symlink() or p.parent.stat().st_uid!=os.geteuid() or p.parent.stat().st_mode&0o077:raise ValueError('Use an owned 0700 directory')
    wallet=input('Dedicated Polymarket wallet address: ').strip()
    if not re.fullmatch(r'0x[0-9a-fA-F]{40}',wallet):raise ValueError('Invalid wallet address')
    key=getpass.getpass('Dedicated signer private key (hidden; never paste in chat): ').strip()
    if not re.fullmatch(r'(0x)?[0-9a-fA-F]{64}',key):raise ValueError('Invalid signer key')
    fd=os.open(p,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    with os.fdopen(fd,'w') as out:json.dump({'wallet':wallet,'private_key':key},out)
    print(json.dumps({'configured':True,'orders_submitted':0}))

def main():
    ap=argparse.ArgumentParser();sub=ap.add_subparsers(dest='command',required=True)
    sub.add_parser('preview')
    c=sub.add_parser('configure');c.add_argument('--secret-file',required=True)
    c=sub.add_parser('status');c.add_argument('--state-dir',required=True)
    c=sub.add_parser('run');c.add_argument('--state-dir',required=True);c.add_argument('--secret-file',required=True);c.add_argument('--live',action='store_true');c.add_argument('--not-before',required=True);c.add_argument('--until',required=True)
    args=ap.parse_args()
    if args.command=='configure':configure(args.secret_file);return
    if args.command=='preview':
        print(json.dumps({'mode':'preview','eligibility':eligibility(),'capital_limit':'10','reservation_per_attempt':'3','order_target':'2.75','orders_submitted':0}));return
    root=Path(args.state_dir)
    if not root.is_absolute() or root.is_symlink():raise ValueError('Use an absolute private state directory')
    root.mkdir(parents=True,exist_ok=True,mode=0o700)
    if root.stat().st_uid!=os.geteuid() or root.stat().st_mode&0o077:raise ValueError('State directory must be owned 0700')
    ledger=Ledger(root/'pilot-ledger.sqlite3')
    if args.command=='status':print(json.dumps(ledger.state()));return
    if not args.live or os.geteuid()==0:raise ValueError('Owner must explicitly select --live as a non-root user')
    begin=datetime.fromisoformat(args.not_before).timestamp();end=datetime.fromisoformat(args.until).timestamp()
    if any(datetime.fromisoformat(x).tzinfo is None for x in (args.not_before,args.until)) or not begin<end<=begin+86400:raise ValueError('Require timezone-aware live window of at most 24 hours')
    if ledger.state()['unresolved']:raise ValueError('Prior intent needs reconciliation; automatic restart refused')
    guard=open(root/'pilot.lock','a');fcntl.flock(guard,fcntl.LOCK_EX|fcntl.LOCK_NB)
    while time.time()<begin:
        if (root/'STOP').exists():return
        time.sleep(min(1,begin-time.time()))
    if time.time()>=end:return
    if not eligibility()['eligible']:raise ValueError('Trading eligibility check failed; no bypass')
    if (root/'STOP').exists():return
    venue=Venue(load_secret(args.secret_file))
    try:
        if not ledger.rows():venue.empty_account()
        seen={r['condition'] for r in ledger.rows()};last_balance=venue.balance();last_geo=time.time()
        while time.time()<end and not (root/'STOP').exists():
            if time.time()-last_geo>=30:
                if not eligibility()['eligible']:raise ValueError('Eligibility lost; pilot stopped')
                last_geo=time.time()
            resolve(ledger)
            if ledger.state()['unresolved']:time.sleep(5);continue
            if Decimal(ledger.state()['remaining_reservation_budget'])<3:return
            balance=venue.balance()
            if balance>last_balance+Decimal('.000001'):raise ValueError('New funding/proceeds detected; recycling disabled')
            last_balance=balance
            try:
                state=read_json(FEED);d=active_guard(state,time.time())
                if d['condition_id'] in seen:raise ValueError('Already attempted this market')
                venue.market(d);book=venue.book(d['books'][d['side']]['asset_id']);p=plan(d,book)
            except (ValueError,KeyError):time.sleep(.25);continue
            execute(ledger,venue,p,root/'STOP',deadline=end);seen.add(d['condition_id']);last_balance=venue.balance()
            print(json.dumps({'event':'position_confirmed','reserved_lifetime':ledger.state()['reserved_lifetime']}))
            time.sleep(.25)
    finally:venue.close()

if __name__=='__main__':
    try:main()
    except Exception as exc:
        # SDK exceptions can contain sensitive request data; suppress raw messages.
        print(json.dumps({'stopped':True,'error_category':type(exc).__name__,'orders_not_retried':True}));raise SystemExit(1)
