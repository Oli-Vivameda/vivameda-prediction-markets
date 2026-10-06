"""Exploratory paper ledger. No live order API, signing or fabricated fills."""
import json, math, time
import scanner as s

def vwap(levels, units):
    units=s.number(units)
    if units is None or units<=0 or units>1000:raise ValueError('Units must be in (0,1000]')
    remain=units;cost=0
    for price,size in sorted(levels):
        price=s.probability(price);size=s.number(size)
        if price is None or price<=0 or size is None or size<=0:raise ValueError('Invalid book level')
        take=min(remain,size);cost+=take*price;remain-=take
        if remain<=1e-9:return cost/units
    raise ValueError('Insufficient observed depth; no assumed fill')

def enter(root, record, now=None):
    now=time.time() if now is None else now
    required={'forecast_id','quote_request_id','side','units','fees_per_share',
              'slippage_per_share','cost_source','cost_reviewed','reviewer'}
    if set(record)!=required:raise ValueError('Explicit paper-entry schema required')
    if record['side'] not in ('yes','no') or record['cost_reviewed'] is not True or not record['reviewer'] or not record['cost_source']:
        raise ValueError('Side and reviewed cost provenance required')
    costs=[s.number(record[k]) for k in ('fees_per_share','slippage_per_share')]
    if any(x is None or x<0 for x in costs):raise ValueError('Unknown costs cannot become zero')
    units=s.number(record['units'])
    if units is None or not 0<units<=1000:raise ValueError('Invalid units')
    with s.connection(root) as db:
        db.execute('CREATE TABLE IF NOT EXISTS paper_positions(id TEXT PRIMARY KEY, at REAL, body TEXT)')
        frow=db.execute('SELECT at,body FROM forecasts WHERE id=?',(record['forecast_id'],)).fetchone()
        qrow=db.execute('SELECT body FROM requests WHERE id=?',(record['quote_request_id'],)).fetchone()
        if not frow or not qrow:raise ValueError('Frozen forecast and observed quote required')
        f=json.loads(frow[1]);q=json.loads(qrow[0]);book=q.get('book') or {}
        if not 0<=now-frow[0]<=900 or not 0<=now-book.get('observed_at',0)<=60:
            raise ValueError('Fresh forecast and quote required')
        if s.timestamp(f['market']['close_at'])<=now:raise ValueError('Market deadline passed')
        if (q['market']['venue'],q['market']['id'],s.digest(q['market']['rules']))!=(f['market']['venue'],f['market']['id'],f['rules_hash']):
            raise ValueError('Quote contract/rules mismatch')
        side=record['side']
        if book.get('status')=='AVAILABLE':
            price=vwap(book['asks'].get(side,[]),units)
        elif book.get('status')=='TOP_OF_BOOK_ONLY':
            price=s.probability(book.get(side+'_ask'));size=s.number(book.get(side+'_ask_size'))
            if price is None or size is None or size<units:raise ValueError('Insufficient known top-of-book size')
        else:raise ValueError('Unsupported or missing book')
        all_in=price+sum(costs)
        conservative=f['p_low'] if side=='yes' else 1-f['p_high']
        if all_in>=1 or conservative<=all_in:raise ValueError('No positive conservative paper edge after costs')
        # One position per frozen forecast avoids replayed paper entries.
        pid=s.digest(['paper',record['forecast_id']])
        body=dict(record,entered_at=now,entry_vwap=price,all_in_per_share=all_in,
                  conservative_edge=conservative-all_in,live_execution=False,
                  assumption='Simulated taker fill against observed depth; not an actual execution',
                  calibration_status='UNVALIDATED_RESEARCHER_FORECAST')
        db.execute('INSERT INTO paper_positions VALUES (?,?,?)',(pid,now,s.packed(body)))
    return {'paper_position_id':pid,**body}

def report(root):
    with s.connection(root) as db:
        db.execute('CREATE TABLE IF NOT EXISTS paper_positions(id TEXT PRIMARY KEY, at REAL, body TEXT)')
        rows=db.execute('SELECT p.id,p.body,o.body FROM paper_positions p LEFT JOIN outcomes o ON o.forecast_id=json_extract(p.body, "$.forecast_id")').fetchall()
    results=[]
    for pid,pbody,obody in rows:
        p=json.loads(pbody);out=json.loads(obody) if obody else None
        pnl=None
        if out:
            payout=out['yes_payout'] if p['side']=='yes' else 1-out['yes_payout']
            pnl=p['units']*(payout-p['all_in_per_share'])
        results.append({'id':pid,'settled':out is not None,'simulated_pnl':pnl})
    return {'positions':results,'simulated_pnl':sum(r['simulated_pnl'] for r in results if r['simulated_pnl'] is not None),
            'live_execution':False,'scope':'Paper results under declared depth/cost assumptions; no realized profit'}
if __name__=='__main__':
    import argparse
    from pathlib import Path
    p=argparse.ArgumentParser();p.add_argument('command',choices=['enter','report'])
    p.add_argument('--state',type=Path,default=s.STATE);p.add_argument('--record',type=Path);a=p.parse_args()
    if a.command=='enter':
        if not a.record or a.record.stat().st_size>100000:raise ValueError('Bounded record required')
        result=enter(a.state,json.loads(a.record.read_text()))
    else:result=report(a.state)
    print(json.dumps(result,indent=2))
