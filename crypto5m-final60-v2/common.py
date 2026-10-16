"""Finite decimal accounting and deterministic serialization."""
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_DOWN
import hashlib
import json
from pathlib import Path

D=Decimal
Q=D('.000001')
F=D('.00001')

def canonical(x):return json.dumps(x,sort_keys=True,separators=(',',':'),allow_nan=False)
def digest(x):return hashlib.sha256(canonical(x).encode()).hexdigest()
def number(x):
    if isinstance(x,bool):raise ValueError('boolean_number')
    try:n=D(str(x))
    except (InvalidOperation,ValueError):raise ValueError('invalid_number') from None
    if not n.is_finite():raise ValueError('nonfinite_number')
    return n

def config(path=None):
    c=json.loads((Path(path) if path else Path(__file__).with_name('config.json')).read_text())
    if (c['version']!='crypto5m-final60.v2' or c['assets']!=['btc','eth','sol'] or c['paper_only'] is not True
        or c['kelly_enabled'] is not False or c['passive_execution'] is not False
        or c['automatic_model_promotion'] is not False or c['reference_adapter']!='public_chainlink_rtds_snapshots'):
        raise ValueError('unsupported_study_configuration')
    for key in ('starting_cash','directional_cap','pair_cap','window_cap','daily_loss','cumulative_loss','uncertainty_edge',
                'additional_cost_per_share','pair_min_profit_per_share','maximum_spread','shadow_sigma_multiplier'):
        if number(c[key])<=0:raise ValueError('nonpositive_configuration')
    for key in ('delay_seconds','pair_leg_delay_seconds','maximum_lateness_seconds','minimum_remaining_seconds',
                'feed_max_age_seconds','decision_seconds','capture_seconds','redemption_delay_seconds','capture_cap_bytes',
                'ledger_cap_bytes','minimum_free_bytes','train_days','calibration_days','selection_days','final_days',
                'minimum_training_windows_per_asset','book_liveness_seconds','crossed_grace_seconds',
                'final_minute_decision_seconds','final_minute_min_remaining','final_minute_max_remaining','reconstruction_max_step_seconds','discovery_seconds'):
        if type(c[key]) is not int or c[key]<=0:raise ValueError('invalid_configuration_integer')
    if number(c['cumulative_loss'])<number(c['daily_loss']):raise ValueError('cumulative_stop_below_daily_limit')
    if c['book_liveness_seconds']>c['feed_max_age_seconds']:raise ValueError('liveness_looser_than_freshness')
    if c['crossed_grace_seconds']>5:raise ValueError('crossed_grace_too_long')
    if c['strategies']!=['directional']:raise ValueError('final60_is_directional_only')
    if not c['minimum_remaining_seconds']<c['final_minute_min_remaining']<c['final_minute_max_remaining']<=60:raise ValueError('invalid_final_minute_window')
    if c['discovery_seconds']>=30 or c['reconstruction_max_step_seconds']>5:raise ValueError('invalid_final_minute_timing')
    return c
