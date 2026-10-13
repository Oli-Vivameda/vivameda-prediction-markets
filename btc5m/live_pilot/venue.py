"""Official SDK boundary. Instantiated only by the owner's explicit live command."""
from decimal import Decimal
import hashlib,importlib.metadata,json,os,stat
from pathlib import Path

SDK_VERSION='0.13.0'

def load_secret(path):
    p=Path(path);s=p.lstat()
    if not stat.S_ISREG(s.st_mode) or s.st_uid!=os.geteuid() or s.st_mode&0o077:raise ValueError('Secret must be an owned regular 0600 file')
    data=json.loads(p.read_text())
    if set(data)!={'wallet','private_key'}:raise ValueError('Unexpected secret schema')
    return data

def validate_market(m,d):
    if m.version=='v2':raise ValueError('Position-based V2 markets excluded from this first pilot')
    if str(m.condition_id)!=d['condition_id'] or m.slug!=d['slug']:raise ValueError('Market identity differs')
    if not m.state.accepting_orders or m.state.closed or not m.state.end_date:raise ValueError('Market is not open')
    if abs(m.state.end_date.timestamp()-d['end_epoch'])>1:raise ValueError('Resolution deadline differs')
    if hashlib.sha256((m.description or '').encode()).hexdigest()!=d['rule_hash']:raise ValueError('Contract rules changed')
    if m.trading.seconds_delay not in (None,0):raise ValueError('Venue matching delay unsupported')
    outcomes=[m.outcomes.yes,m.outcomes.no]
    labels={o.label for o in outcomes}
    if labels!={'Up','Down'}:raise ValueError('Outcome labels differ')
    chosen=next(o for o in outcomes if o.label==d['side'])
    if str(chosen.token_id)!=d['books'][d['side']]['asset_id']:raise ValueError('Outcome asset differs')
    f=m.trading.fee_schedule
    if m.trading.fees_enabled:
        if f is None or Decimal(str(f.rate))!=Decimal(str(d['fee_rate'])) or Decimal(str(f.exponent))!=Decimal(str(d['fee_exponent'])):raise ValueError('Fee schedule changed')
    elif Decimal(str(d['fee_rate']))!=0:raise ValueError('Fee flags differ')

class Venue:
    def __init__(self,secret):
        if importlib.metadata.version('polymarket-client')!=SDK_VERSION:raise ValueError('SDK version differs from reviewed pilot')
        from polymarket import SecureClient
        self.client=SecureClient.create(private_key=secret['private_key'],wallet=secret['wallet'])
    def close(self):self.client.close()
    def balance(self):
        b=self.client.get_balance_allowance(asset_type='COLLATERAL')
        if not b.allowances or min(b.allowances.values())<3000000:raise ValueError('Collateral allowances require owner setup')
        return Decimal(b.balance)/1000000
    def empty_account(self):
        if self.client.list_open_orders().first_page().items:raise ValueError('Dedicated wallet has open orders')
        if self.client.list_positions().first_page().items:raise ValueError('Dedicated wallet already has positions')
    def market(self,d):
        m=self.client.get_market(slug=d['slug']);validate_market(m,d);return m
    def book(self,asset):return self.client.get_order_book(asset_id=asset)
    def sign(self,p):
        signed=self.client.create_market_order(asset_id=p['asset_id'],side='BUY',amount=p['order_target'],max_spend=p['order_target'],max_price=p['max_price'],order_type='FOK')
        if signed.order_type!='FOK' or signed.side!='BUY' or str(signed.token_id)!=p['asset_id']:raise ValueError('Signed order identity differs')
        if signed.maker_amount<=0 or signed.maker_amount>2750000 or signed.taker_amount<Decimal(p['minimum_size'])*1000000:raise ValueError('Signed order fails pilot amount/minimum guard')
        # SDK provides tick-grid price protection, checked by its own signing pipeline.
        return signed
    def post(self,signed):return self.client.post_order(signed)
    def confirm(self,response,plan):
        if response.status!='matched' or not response.trade_ids:raise ValueError('Order not immediately matched')
        hashes=self.client.wait_for_order_fill_settlement(response,timeout_s=30)
        if not hashes:raise ValueError('No confirmed settlement')
        positions=self.client.list_positions(market=[plan['condition_id']]).first_page().items
        position=next((p for p in positions if str(p.asset_id)==plan['asset_id'] and p.size>0),None)
        if position is None:raise ValueError('Filled position not reconciled')
        return {'shares':str(position.size),'transaction_count':len(hashes),'spend_observation':str(response.making_amount),'onchain_fill_confirmed':True,'market_outcome_resolved':False}
