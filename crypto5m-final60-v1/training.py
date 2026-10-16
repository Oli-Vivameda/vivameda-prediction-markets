"""Offline, read-only training-row builder and explicit fit command.

Never run by the service. Reads the index and ledger genesis read-only, emits only
train and calibration rows (selection and final targets are never read into fitting),
and prints the artifact. Nothing is promoted: the worker never loads a fitted model.
"""
import argparse
import json
import sqlite3
import time
from pathlib import Path
from common import digest
import model

SPLITS=('train','calibration')


def genesis(state):
    with sqlite3.connect('file:'+str(Path(state)/'ledger.sqlite3')+'?mode=ro',uri=True) as db:
        row=db.execute("SELECT body FROM events WHERE kind='genesis'").fetchone()
    if row is None:raise ValueError('missing_genesis')
    return json.loads(row[0])


def rows(state,c,started):
    """One row per asset window: the first observation that carried a model forecast."""
    outcomes={};chosen={}
    with sqlite3.connect('file:'+str(Path(state)/'index.sqlite3')+'?mode=ro',uri=True) as db:
        for condition,raw,sha in db.execute('SELECT condition,body,sha FROM outcomes'):
            v=json.loads(raw)
            if digest(v)!=sha:raise ValueError('outcome_integrity')
            outcomes[condition]=v
        for raw,sha in db.execute('SELECT body,sha FROM observations ORDER BY rowid'):
            v=json.loads(raw)
            if digest(v)!=sha:raise ValueError('observation_integrity')
            if model.partition(v['start'],started,c) not in SPLITS:continue
            if v.get('model_prediction') is None or 'input_max_received_at' not in v:continue
            chosen.setdefault((v['asset'],v['start']),v)
    out=[]
    for (asset,start),v in sorted(chosen.items()):
        o=outcomes.get(v['condition'])
        if o is None or o['winner'] not in ('Up','Down'):continue
        out.append({'asset':asset,'start':start,'end':v['end'],'observed_at':v['observed_at'],
            'outcome_available_at':o['confirmed_at'],'input_max_received_at':v['input_max_received_at'],
            'input_max_source_at':v['input_max_source_at'],'features':v['model_prediction']['features'],
            'y':int(o['winner']=='Up'),'condition':v['condition']})
    return out


def main():
    p=argparse.ArgumentParser();p.add_argument('--state',required=True);p.add_argument('--asset',required=True,choices=('btc','eth','sol'))
    p.add_argument('--rows-only',action='store_true');a=p.parse_args()
    g=genesis(a.state);c=g['config'];data=rows(a.state,c,g['started_at'])
    if a.rows_only:
        counts={}
        for r in data:
            k=r['asset']+':'+model.partition(r['start'],g['started_at'],c);counts[k]=counts.get(k,0)+1
        print(json.dumps({'rows':counts,'minimum_train_per_asset':c['minimum_training_windows_per_asset'],'minimum_calibration_per_asset':100},sort_keys=True,indent=2));return
    artifact=model.fit(data,a.asset,g['started_at'],c,time.time())
    print(json.dumps({**artifact,'promoted':False,'note':'Offline artifact only; the service never loads it.'},sort_keys=True,indent=2))

if __name__=='__main__':main()
