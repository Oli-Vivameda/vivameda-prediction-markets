"""Private health events and daily reporting. No external delivery or real orders."""
from datetime import datetime, time as daytime, timedelta, timezone
import json
import os
from pathlib import Path
import threading
import time
from zoneinfo import ZoneInfo

TZ = ZoneInfo('Asia/Nicosia')


def atomic_json(path, data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_name('.'+path.name+'.tmp')
    fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    with os.fdopen(fd,'w') as out:
        json.dump(data,out,sort_keys=True,allow_nan=False);out.write('\n')
    os.replace(temporary,path)


def assess_health(snapshot, now, started):
    reasons=[];restart=False;blocked=False
    capture=snapshot.get('capture') or {}
    if not capture.get('healthy'):
        reasons.append(capture.get('error') or 'capture_not_ready')
        error=capture.get('error') or ''
        blocked='storage limit' in error.lower() or 'volume' in error.lower()
        restart=bool(error) and not blocked
    age=snapshot.get('reference_age')
    if age is None or not -1<=age<=3:reasons.append('reference_stale_or_missing')
    if snapshot.get('stream_error'):reasons.append('outcome_stream_unavailable')
    if not snapshot.get('stream_fresh'):reasons.append('outcome_books_stale_or_missing')
    if snapshot.get('shadow_error'):
        reasons.append('shadow_worker_stopped');restart=True
    if now-snapshot.get('engine_heartbeat',started)>90:
        reasons.append('market_collector_stalled');restart=True
    if now-started<120 and reasons:
        mode='warming';restart=False
    else:mode='healthy' if not reasons else 'blocked' if blocked else 'degraded'
    return {'mode':mode,'reasons':reasons,'shadow_allowed':mode=='healthy',
            'restart_requested':restart,'operator_action_required':blocked,'checked_at':now}


def day_bounds(day):
    start=datetime.combine(day,daytime.min,TZ)
    end=datetime.combine(day+timedelta(days=1),daytime.min,TZ)
    return start.timestamp(),end.timestamp()


def daily_report(rows, day, now=None):
    now=time.time() if now is None else now
    start,end=day_bounds(day)
    within=lambda r:start<=r.get('recorded_at',0)<end
    decisions=[r for r in rows if r['kind']=='shadow_decision' and within(r)]
    attempts=[r for r in rows if r['kind']=='shadow_attempt' and within(r)]
    all_attempts={r['id']:r for r in rows if r['kind']=='shadow_attempt'}
    settled=[r for r in rows if r['kind']=='shadow_result' and within(r)]
    arms={}
    for delay in (.25,2.):
        trades=[r for r in attempts if r.get('delay_seconds')==delay]
        fills=[r for r in trades if r.get('filled')]
        results=[r for r in settled if all_attempts.get(r['attempt_id'],{}).get('delay_seconds')==delay]
        reasons={}
        for r in trades:
            if not r.get('filled'):reasons[r['status']]=reasons.get(r['status'],0)+1
        arms[str(delay)]={'attempts':len(trades),'fills':len(fills),'missed_fills':len(trades)-len(fills),
            'fees_on_entries':sum(r['fill']['fees'] for r in fills),
            'stake_on_entries':sum(r['fill']['total'] for r in fills),
            'settlements_today':len(results),'realized_net_profit':sum(r['net_profit'] for r in results),
            'missed_fill_reasons':reasons}
    pauses=[r for r in rows if r['kind']=='ops_health' and within(r) and r.get('mode') not in ('healthy','warming')]
    heartbeats=[r for r in rows if r['kind']=='ops_health' and within(r)]
    sizes=[r.get('capture_bytes',0) for r in heartbeats]
    expected=int((end-start)//300)
    observed=len({r['condition_id'] for r in decisions})
    return {'day':day.isoformat(),'timezone':'Asia/Nicosia','period_start':start,'period_end':end,
        'final':now>=end,'expected_five_minute_slots':expected,'recorded_decision_markets':observed,
        'decision_coverage_fraction':observed/expected,'decisions':len(decisions),
        'skips':sum(r.get('side') is None for r in decisions),'resolved_markets_today':len({
            r['condition_id'] for r in rows if r['kind']=='market_resolution' and within(r)}),
        'arms':arms,'health_observations':len(heartbeats),'unhealthy_observations':len(pauses),
        'restarts':sum(r['kind']=='ops_restart' and within(r) for r in rows),
        'capture_size_first':sizes[0] if sizes else None,'capture_size_last':sizes[-1] if sizes else None,
        'capture_growth_observed':max(0,sizes[-1]-sizes[0]) if sizes else None,
        'full_day_verified':now>=end and observed>=.95*expected and len(heartbeats)>=1000 and not pauses,
        'live_execution':False,'edge_validated':False,
        'note':'Entry costs counted on entry date; net P&L counted on official settlement date. '
               'UTC-day risk limits remain separate. Missing slots are gaps, not assumed no-trade decisions.'}


class Operations:
    def __init__(self,journal,snapshot):
        self.journal,self.snapshot=journal,snapshot
        self.data=Path(journal.path).parent
        self.stop=threading.Event();self.started=time.time();self.last_log=0
        self.health={'mode':'warming','shadow_allowed':False,'restart_requested':False,'reasons':['starting']}
        self.latest_report=None;self.last_day=None;self.error=None

    def run(self):
        while not self.stop.is_set():
            try:
                now=time.time();snap=self.snapshot()
                h=assess_health(snap,now,self.started)
                changed=h['mode']!=self.health['mode'] or h['reasons']!=self.health['reasons']
                self.health=h
                atomic_json(self.data/'ops-heartbeat.json',{'pid':os.getpid(),'timestamp':now,
                    'health':h,'capture':snap.get('capture'),'live_execution':False})
                if changed or now-self.last_log>=60:
                    self.journal.append('ops_health',{**h,'capture_bytes':(snap.get('capture') or {}).get('bytes',0)})
                    self.last_log=now
                today=datetime.fromtimestamp(now,TZ).date()
                if self.last_day!=today:
                    report=daily_report(self.journal.rows(),today-timedelta(days=1),now)
                    atomic_json(self.data/'reports'/('daily-'+report['day']+'.json'),report)
                    atomic_json(self.data/'reports'/'latest-daily.json',report)
                    self.latest_report=report;self.last_day=today
                self.error=None
            except Exception as exc:
                self.error=type(exc).__name__+': monitoring unavailable'
                self.health={'mode':'blocked','shadow_allowed':False,'restart_requested':True,
                             'reasons':['monitoring_failed'],'checked_at':time.time()}
            self.stop.wait(5)

    def state(self):
        from training import PLAN, PLAN_SHA
        return {'training_plan':PLAN,'training_plan_sha256':PLAN_SHA,'health':self.health,'latest_daily_report':self.latest_report,'error':self.error,
                'live_execution':False}
