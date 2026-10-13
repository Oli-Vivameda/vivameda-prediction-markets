"""Prospective measurement and public account observation. No order execution."""
import hashlib
import json
import math
import re
import time
import urllib.parse

POLICY = 'btc5m-locked-manual-v2'


def market_baseline(books):
    mids = {}
    for side in ('Up', 'Down'):
        b = books[side]
        bid = max(float(x['price']) for x in b['bids'] if float(x['size']) > 0)
        ask = min(float(x['price']) for x in b['asks'] if float(x['size']) > 0)
        if not 0 < bid <= ask < 1:
            raise ValueError('Invalid or crossed benchmark book')
        mids[side] = (bid + ask) / 2
    return mids['Up'] / sum(mids.values())


def scores(p, y):
    p = min(1-1e-8, max(1e-8, float(p)))
    return (p-y)**2, -(y*math.log(p)+(1-y)*math.log(1-p))


def report(rows):
    outcomes = {r['condition_id']: r for r in rows if r['kind'] == 'market_resolution'}
    # One first eligible, pre-outcome observation per market, independently of trades.
    first = {}
    for r in rows:
        if r['kind'] != 'assessment' or r.get('policy') != POLICY:
            continue
        if not r.get('prediction') or r.get('market_probability_up') is None:
            continue
        if r['recorded_at'] >= r.get('end_epoch', 0):
            continue
        first.setdefault(r['condition_id'], r)
    totals = {s: [0., 0.] for s in ('model', 'market', 'momentum')}
    days = set()
    n = 0
    for condition, r in first.items():
        o = outcomes.get(condition)
        if not o or o['recorded_at'] <= r['recorded_at']:
            continue
        y = int(o['winner'] == 'Up')
        probabilities = {'model': r['prediction']['p_up'], 'market': r['market_probability_up'],
                         'momentum': .75 if r['prediction']['momentum_up'] else .25}
        for name, p in probabilities.items():
            b, l = scores(p, y)
            totals[name][0] += b
            totals[name][1] += l
        n += 1
        days.add(time.strftime('%Y-%m-%d', time.gmtime(r['recorded_at'])))
    return {'eligible_markets': len(first), 'resolved_markets': n, 'observed_days': len(days),
            'metrics': {s: {'brier': v[0]/n if n else None, 'log_loss': v[1]/n if n else None}
                        for s, v in totals.items()},
            'edge_validated': False, 'model_promoted': False,
            'note': 'Descriptive monitoring only. One first eligible observation per market; '
                    'market/day dependence and untouched chronological validation remain required.'}


class Research:
    def __init__(self, journal):
        self.journal = journal
        self.last_resolve = 0
        self.last_watch = 0
        self.wallet = None
        self.wallet_error = None
        for r in journal.rows():
            if r['kind'] == 'watch_wallet':
                self.wallet = r['wallet']

    def enrich(self, a, books):
        a['policy'] = POLICY
        a['live_execution'] = False
        a['market_probability_up'] = None
        if a.get('prediction'):
            try:
                a['market_probability_up'] = market_baseline(books)
            except (ValueError, KeyError, TypeError):
                pass
        positions = [t for t in self.journal.portfolio()['trades'] if t['slug'] == a.get('slug')]
        a['live_action'] = a['action']
        a['locked_position'] = None
        if positions:
            t = positions[0]
            a['locked_position'] = {'trade_id': t['id'], 'side': t['side'], 'entry': t['fill'],
                'entry_probability': t['assessment'].get('prediction', {}).get('p_up'),
                'entry_reason': t['assessment']['reason'], 'plan': 'Hold to official resolution',
                'settled': bool(t['settlement'])}
            a['manual_available'] = False
            a['action'] = 'HOLD ' + t['side'].upper()
        return a

    def resolve(self, get_json):
        rows = self.journal.rows()
        resolved = {r['condition_id'] for r in rows if r['kind'] == 'market_resolution'}
        pending = {}
        for r in rows:
            if r['kind'] in ('assessment','shadow_decision') and r.get('condition_id') and r.get('end_epoch', float('inf')) < time.time():
                if r['condition_id'] not in resolved:
                    pending.setdefault(r['condition_id'], r)
        # Bounded fair rotation; one failed/unresolved market cannot starve the rest.
        keys = sorted(pending)
        offset = int(time.time() // 30) * 8 % max(1, len(keys))
        keys = keys[offset:] + keys[:offset]
        for condition in keys[:8]:
            try:
                m = get_json('https://clob.polymarket.com/markets/' + condition)
                winners = [t for t in m.get('tokens', []) if t.get('winner') is True]
                if m.get('condition_id') != condition or not m.get('closed') or len(winners) != 1:
                    continue
                winner = winners[0]['outcome']
                if winner not in ('Up', 'Down'):
                    continue
                self.journal.append('market_resolution', {'condition_id': condition, 'winner': winner,
                    'source': 'CLOB explicit winning token', 'slug': pending[condition]['slug']})
            except Exception:
                continue

    def watch(self, wallet):
        if not isinstance(wallet, str) or not re.fullmatch(r'0x[0-9a-fA-F]{40}', wallet):
            raise ValueError('Use the public Polymarket account wallet address: 0x plus 40 hex characters')
        wallet = wallet.lower()
        with self.journal.lock:
            if wallet != self.wallet:
                self.journal.append('watch_wallet', {'wallet': wallet, 'read_only': True})
                self.wallet = wallet
                self.wallet_error = None
        return {'watching': wallet, 'read_only': True, 'live_execution': False}

    def poll_wallet(self, get_json):
        wallet = self.wallet
        if not wallet:
            return
        rows = self.journal.rows()
        seen = {r['event_key'] for r in rows if r['kind'] == 'account_activity'}
        assessments = [r for r in rows if r['kind'] == 'assessment' and r.get('policy') == POLICY]
        try:
            # Legacy documented public endpoint; bounded coverage, explicitly not full history.
            activity = get_json('https://data-api.polymarket.com/activity?' +
                                urllib.parse.urlencode({'user': wallet, 'limit': 100,
                                                        'sortBy': 'TIMESTAMP', 'sortDirection': 'DESC'}))
            if not isinstance(activity, list):
                raise ValueError('Unsupported account response')
            for r in reversed(activity):
                if r.get('proxyWallet', '').lower() != wallet:
                    raise ValueError('Account wallet identity mismatch')
                canonical = {k: r.get(k) for k in ('transactionHash', 'timestamp', 'conditionId',
                            'type', 'asset', 'side', 'size', 'usdcSize', 'price', 'outcome')}
                key = hashlib.sha256(json.dumps(canonical, sort_keys=True).encode()).hexdigest()
                if key in seen:
                    continue
                stamp = float(r.get('timestamp', 0))
                prior = [a for a in assessments if r.get('type') == 'TRADE' and a.get('condition_id') == r.get('conditionId')
                         and a.get('prediction') and a['recorded_at'] <= stamp < a.get('end_epoch', 0)
                         and 0 <= stamp-a['recorded_at'] <= 35]
                match = max(prior, key=lambda a: a['recorded_at']) if prior else None
                self.journal.append('account_activity', {'wallet': wallet, 'event_key': key,
                    'activity': canonical, 'slug': r.get('slug'),
                    'pre_trade_assessment_id': match['id'] if match else None,
                    'learning_context': 'prospective_match' if match else 'historical_or_unmatched',
                    'fees': None, 'net_profit': None, 'execution': 'observed_real_account',
                    'costs_reconciled': False})
                seen.add(key)
            self.wallet_error = None
        except Exception as exc:
            self.wallet_error = type(exc).__name__ + ': account observation unavailable'

    def state(self):
        rows = self.journal.rows()
        events = [r for r in rows if r['kind'] == 'account_activity' and r['wallet'] == self.wallet]
        return {'evaluation': report(rows), 'account': {'wallet': self.wallet, 'read_only': True,
            'captured_events': len(events), 'matched_events': sum(bool(r['pre_trade_assessment_id']) for r in events),
            'error': self.wallet_error, 'net_profit': None,
            'coverage': 'Latest 100 activities per poll; complete history and costs not certified'},
            'policy': POLICY, 'live_execution': False}
