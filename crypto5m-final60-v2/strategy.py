"""Frozen decisions. No live client, model promotion or Kelly allocation."""
from common import D,number,digest,Q,ROUND_DOWN
import market
from ledger import consumption,terms


def check(m,books,now,c):
    if not m['active'] or m['closed'] or not m['accepting'] or not m['rules_verified']:raise ValueError('market_not_tradeable')
    if not m['start']<=now<m['end']-c['minimum_remaining_seconds']:raise ValueError('entry_window')
    for side in ('Up','Down'):market.fresh(books[side],m,now,c)

def plan(m,books,prediction,now,c,state,strategy):
    check(m,books,now,c)
    if prediction is None:raise ValueError('required_contractual_feed_unavailable')
    if prediction['version']!='final-minute-partial-twap.v1' or not 0<=now-prediction['observed_at']<=3:
        raise ValueError('stale_or_unknown_prediction')
    consumed=consumption(state)
    if strategy not in c['strategies']:raise ValueError('strategy_disabled')
    if strategy=='directional':
        candidates=[];budget=c['directional_cap']
        for side in ('Up','Down'):
            try:
                market.executable_buy(books[side],c)
                fill=market.execute_depth(books[side],m,budget,consumed=consumed,additional=c['additional_cost_per_share'])
                p=number(prediction['p_up']) if side=='Up' else 1-number(prediction['p_up'])
                if not 0<=p<=1:raise ValueError('invalid_probability')
                if number(fill['shares'])>0 and p-number(fill['unit_cost'])>=number(c['uncertainty_edge']):
                    candidates.append((p-number(fill['unit_cost']),side,fill,p))
            except ValueError:continue
        if not candidates:raise ValueError('no_directional_cost_adjusted_edge')
        _,side,fill,p=max(candidates,key=lambda x:(x[0],x[1]))
        legs=[{'side':side,'quantity':fill['shares'],'limit':str(min(D('.999999'),number(fill['levels'][-1][0])+number(books[side]['tick']))),
               'maximum_unit_cost':str(p-number(c['uncertainty_edge']))}]
    elif strategy=='paired':
        budget=c['pair_cap'];lo=D(0);hi=D(100000)
        for _ in range(50):
            quantity=((lo+hi)/2).quantize(Q,rounding=ROUND_DOWN)
            if quantity<=0:break
            try:
                fills=[market.execute_depth(books[s],m,budget,quantity,consumed,additional=c['additional_cost_per_share'],check_minimum=False) for s in ('Up','Down')]
                valid=all(number(f['shares'])==quantity for f in fills) and sum((number(f['total']) for f in fills),D(0))<=number(budget)
            except ValueError:valid=False
            if valid:lo=quantity
            else:hi=quantity
        if lo<=0:raise ValueError('no_paired_minimum_depth')
        fills=[market.execute_depth(books[s],m,budget,lo,consumed,additional=c['additional_cost_per_share']) for s in ('Up','Down')]
        if sum((number(f['unit_cost']) for f in fills),D(0))>1-number(c['pair_min_profit_per_share']):raise ValueError('no_paired_cost_advantage')
        legs=[{'side':side,'quantity':str(lo),'limit':str(min(D('.999999'),number(f['levels'][-1][0])+number(books[side]['tick']))),
               'maximum_unit_cost':str(number(f['unit_cost'])+D('.005'))} for side,f in zip(('Up','Down'),fills)]
    else:raise ValueError('unknown_strategy')
    return {'id':digest([c['version'],m['condition'],strategy]),'strategy':strategy,'market':m,'budget':budget,
        'plans':legs,'input_books':books,'required_feeds_verified':True,'prediction':prediction,'market_terms_sha256':terms(m),
        'generation':{s:books[s]['generation'] for s in ('Up','Down')}}
