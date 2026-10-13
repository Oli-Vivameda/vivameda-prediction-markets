"""Use a frozen paper decision; reprice its same side with current live depth."""
from decimal import Decimal,ROUND_DOWN
import hashlib,json,math,time
from risk import ORDER_TARGET

D=Decimal

def plan(decision,book,now=None):
    now=time.time() if now is None else now
    if decision.get('strategy')!='btc5m-fixed180-delay-v3' or decision.get('side') not in ('Up','Down'):raise ValueError('No frozen directional decision')
    if not 2<=now-decision['decision_time']<=5:raise ValueError('Outside two-second execution window')
    if now>=decision['end_epoch']-60:raise ValueError('Contract entry deadline passed')
    side=decision['side'];asset=decision['books'][side]['asset_id']
    if str(book.asset_id)!=asset or str(book.market)!=decision['condition_id']:raise ValueError('Live book identity differs')
    if book.timestamp is None or not -1<=now-book.timestamp.timestamp()<=3:raise ValueError('Live book stale')
    tick=D(str(book.tick_size));minimum=D(str(book.min_order_size))
    if not 0<tick<1 or minimum<=0:raise ValueError('Unknown venue minimums')
    q=decision['quotes'][side];p=D(str(decision['prediction']['p_up'] if side=='Up' else 1-decision['prediction']['p_up']))
    rate=D(str(decision['fee_rate']));exponent=D(str(decision['fee_exponent']))
    if not 0<=rate<=D('.10') or not 0<=exponent<=4:raise ValueError('Unsupported fee schedule')
    # Conservative same-side cap: original break-even + 2 points, or model - 5 points.
    cap=min(D('.99'),D(str(q['break_even_probability']))+D('.02'),p-D('.05'))
    cap=(cap/tick).to_integral_value(rounding=ROUND_DOWN)*tick
    cost=shares=fees=D(0);worst=None
    for level in sorted(book.asks,key=lambda x:x.price):
        price,size=D(str(level.price)),D(str(level.size))
        if not price.is_finite() or not size.is_finite() or price<=0 or price>=1 or size<=0:continue
        if price>cap:break
        per_fee=rate*(price*(1-price))**exponent
        quantity=min(size,(ORDER_TARGET-cost-fees)/(price+per_fee))
        if quantity<=0:break
        cost+=quantity*price;fees+=quantity*per_fee;shares+=quantity;worst=price
        if cost+fees>=ORDER_TARGET-D('.000001'):break
    if shares<minimum or cost+fees<ORDER_TARGET-D('.000001'):raise ValueError('Minimum size or full depth does not fit $2.75 target')
    break_even=(cost+fees)/shares
    if p-break_even<D('.05') or break_even>D(str(q['break_even_probability']))+D('.02'):raise ValueError('Net edge or adverse-price limit failed')
    result={'condition_id':decision['condition_id'],'slug':decision['slug'],'side':side,'asset_id':asset,
        'decision_id':decision['id'],'decision_time':decision['decision_time'],'end_epoch':decision['end_epoch'],
        'rule_hash':decision['rule_hash'],'order_target':str(ORDER_TARGET),'reservation':'3',
        'max_price':str(cap),'estimated_shares':str(shares),'estimated_fees':str(fees),
        'estimated_break_even':str(break_even),'minimum_size':str(minimum),'plan':'Hold to official resolution',
        'model_validated':False,'order_type':'FOK','created_at':now}
    result['plan_sha256']=hashlib.sha256(json.dumps(result,sort_keys=True).encode()).hexdigest()
    return result
