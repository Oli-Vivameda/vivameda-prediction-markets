"""Persistent conservative pilot reservations. No network or signing."""
from decimal import Decimal
import hashlib,json,sqlite3,time
from pathlib import Path

CAP=Decimal('10');RESERVATION=Decimal('3');ORDER_TARGET=Decimal('2.75')
ACTIVE=('reserved','submitting','accepted','confirmed','unknown')

def money(x):
    v=Decimal(str(x))
    if not v.is_finite() or v<0:raise ValueError('Invalid money')
    return v

class Ledger:
    def __init__(self,path):
        self.path=Path(path)
        self.path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS intents (condition TEXT PRIMARY KEY, plan TEXT NOT NULL, reserved TEXT NOT NULL, state TEXT NOT NULL, order_id TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY,body TEXT NOT NULL,digest TEXT NOT NULL)')
        self.path.chmod(0o600);self.verify()
    def connect(self):return sqlite3.connect(self.path,timeout=10)
    def verify(self):
        with self.connect() as db:
            prior='';projection={}
            for body,digest in db.execute('SELECT body,digest FROM events ORDER BY id'):
                if hashlib.sha256((prior+body).encode()).hexdigest()!=digest:raise ValueError('Pilot journal differs')
                prior=digest
                event=json.loads(body);condition=event['condition']
                if event['kind']=='locked_plan':
                    projection[condition]={'plan':json.dumps(event['plan'],sort_keys=True,allow_nan=False),'reserved':event['reserved'],'state':'reserved','order_id':None}
                else:
                    if condition not in projection:raise ValueError('Event has no locked plan')
                    projection[condition]['state']=event['kind'];projection[condition]['order_id']=event.get('order_id')
            actual={c:{'plan':p,'reserved':r,'state':st,'order_id':o} for c,p,r,st,o in db.execute('SELECT * FROM intents')}
            if actual!=projection:raise ValueError('Pilot state differs from immutable journal')
    @staticmethod
    def event(db,kind,body):
        raw=json.dumps({'kind':kind,'time':time.time(),**body},sort_keys=True,allow_nan=False)
        prev=db.execute('SELECT digest FROM events ORDER BY id DESC LIMIT 1').fetchone()
        digest=hashlib.sha256(((prev[0] if prev else '')+raw).encode()).hexdigest()
        db.execute('INSERT INTO events(body,digest) VALUES (?,?)',(raw,digest))
    def rows(self):
        with self.connect() as db:return [dict(zip(('condition','plan','reserved','state','order_id'),r)) for r in db.execute('SELECT * FROM intents')]
    def reserve(self,plan,balance):
        if money(balance)<RESERVATION or money(balance)>CAP:raise ValueError('Dedicated balance must be between $3 and $10')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            rows=db.execute('SELECT condition,reserved,state FROM intents').fetchall()
            if any(state in ACTIVE for _,_,state in rows):raise ValueError('Position or submission unresolved')
            if sum((money(r) for _,r,_ in rows),Decimal(0))+RESERVATION>CAP:raise ValueError('Lifetime pilot budget exhausted')
            raw=json.dumps(plan,sort_keys=True,allow_nan=False)
            db.execute('INSERT INTO intents VALUES (?,?,?,?,NULL)',(plan['condition_id'],raw,str(RESERVATION),'reserved'))
            self.event(db,'locked_plan',{'condition':plan['condition_id'],'plan':plan,'reserved':str(RESERVATION)})
    def transition(self,condition,state,details=None,order_id=None):
        allowed={'reserved':{'submitting','aborted'},'submitting':{'accepted','rejected','unknown'},'accepted':{'confirmed','unknown'},'confirmed':{'resolved'},'unknown':set(),'rejected':set(),'aborted':set(),'resolved':set()}
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT state,order_id FROM intents WHERE condition=?',(condition,)).fetchone()
            if not row or state not in allowed[row[0]]:raise ValueError('Invalid pilot state transition')
            db.execute('UPDATE intents SET state=?,order_id=? WHERE condition=?',(state,order_id or row[1],condition))
            self.event(db,state,{'condition':condition,'details':details or {},'order_id':order_id or row[1]})
    def state(self):
        rows=self.rows();spent=sum((money(r['reserved']) for r in rows),Decimal(0))
        return {'reserved_lifetime':str(spent),'remaining_reservation_budget':str(CAP-spent),'intents':len(rows),'unresolved':sum(r['state'] in ACTIVE for r in rows),'activation_managed_by_owner':True}
