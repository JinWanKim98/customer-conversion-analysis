"""Chapter 05: source-to-curated SQLite build and independent full-source reconciliation."""
from __future__ import annotations

import argparse
import csv
import gc
import hashlib
import json
import math
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from intake import REES, file_hash, number, timestamp, read_sql
from reproducibility import verify_sources
from contract_metrics import Event, metric_values, python_counts

ROOT=Path(__file__).resolve().parents[1]
MODEL_SQL=ROOT/'analysis.sql'
METRIC_SQL=ROOT/'analysis.sql'
CONTRACT=ROOT/'docs/04_metric_contract.json'


def create_model(conn,rows,config,log=lambda message:None):
    conn.execute('PRAGMA foreign_keys=ON')
    conn.execute('PRAGMA temp_store=MEMORY')
    conn.execute('PRAGMA cache_size=-65536')
    conn.execute('CREATE TABLE model_config(id INTEGER PRIMARY KEY CHECK(id=1),gap_seconds INTEGER NOT NULL,sensitivity_gap_seconds INTEGER NOT NULL,horizon_seconds INTEGER NOT NULL,observed_end INTEGER NOT NULL,source_sha256 TEXT NOT NULL,contract_sha256 TEXT NOT NULL)')
    conn.execute('INSERT INTO model_config VALUES(1,?,?,?,?,?,?)',
                 (config['gap_seconds'],config['sensitivity_gap_seconds'],config['horizon_seconds'],
                  config['observed_end'],config.get('source_sha256','fixture'),config.get('contract_sha256','fixture')))
    conn.execute('CREATE TABLE staging_events(source_row INTEGER PRIMARY KEY,'+
                 ','.join(k+' TEXT NOT NULL' for k in REES)+',ts INTEGER NOT NULL,price_value REAL NOT NULL)')
    batch=[]
    n=0
    with conn:
        for n,row in enumerate(rows,1):
            if set(row)!=set(REES) or any(value is None for value in row.values()):
                raise ValueError(f'Malformed source row {n}.')
            moment=timestamp(row['event_time'])
            price=number(row['price'])
            if moment is None or moment.microsecond or int(moment.timestamp())>config['observed_end']:
                raise ValueError(f'Invalid or out-of-window event timestamp at row {n}.')
            if not row['user_id'].strip() or not row['product_id'].strip():
                raise ValueError(f'Missing user/product ID at row {n}.')
            if row['event_type'] not in {'view','cart','purchase'}:
                raise ValueError(f'Unexpected event type at row {n}.')
            if price is None or price<0 or not math.isfinite(float(price)):
                raise ValueError(f'Invalid price at row {n}.')
            batch.append((n,*(row[k] for k in REES),int(moment.timestamp()),float(price)))
            if len(batch)==10000:
                conn.executemany('INSERT INTO staging_events VALUES('+','.join('?' for _ in range(12))+')',batch)
                batch.clear()
        if batch:
            conn.executemany('INSERT INTO staging_events VALUES('+','.join('?' for _ in range(12))+')',batch)
    bounds=conn.execute('SELECT MIN(ts),MAX(ts) FROM staging_events').fetchone()
    if config.get('enforce_source_bounds'):
        if tuple(bounds)!=(config['observed_start'],config['observed_end']):
            raise ValueError('Actual source endpoints differ from the approved contract.')
    log(f'Loaded {n:,} validated source rows.')
    parts=re.split(r'^-- stage: (.+)$',read_sql('05_build_model.sql'),flags=re.MULTILINE)
    for i in range(1,len(parts),2):
        conn.executescript(parts[i+1])
        log('Built '+parts[i].strip()+'.')
    return n


def metric_counts(conn):
    cursor=conn.execute(read_sql('05_metric_queries.sql'))
    row=cursor.fetchone()
    return dict(zip([column[0] for column in cursor.description],row))


def model_checks(conn,raw_rows,expected_events=None):
    names=['dim_user','dim_product','fact_event','event_lineage','bridge_event_session',
           'fact_session_30','fact_session_60','mart_user_product','mart_session_product']
    counts={name:conn.execute(f'SELECT COUNT(*) FROM {name}').fetchone()[0] for name in names}
    if counts['event_lineage']!=raw_rows or counts['fact_event']!=counts['bridge_event_session']:
        raise AssertionError('Lineage/bridge cardinality mismatch.')
    if expected_events is not None and counts['fact_event']!=expected_events:
        raise AssertionError('Canonical events differ from the independent intake/quality audit.')
    if conn.execute('PRAGMA foreign_key_check').fetchall():
        raise AssertionError('Foreign-key violation.')
    integrity=conn.execute('PRAGMA integrity_check').fetchone()[0]
    if integrity!='ok':raise AssertionError(integrity)
    event_total=counts['fact_event']
    for table in ['fact_session_30','fact_session_60']:
        total=conn.execute(f'SELECT COALESCE(SUM(event_count),0) FROM {table}').fetchone()[0]
        if total!=event_total:raise AssertionError('Session groups lose or multiply events.')
    joined=conn.execute('SELECT COUNT(*) FROM event_reporting').fetchone()[0]
    if joined!=event_total:raise AssertionError('Reporting join multiplies events.')
    invalid=conn.execute('''SELECT COUNT(*) FROM mart_user_product WHERE
       (cart_after_view_ts IS NOT NULL AND NOT(cart_after_view_ts>view_ts)) OR
       (purchase_after_view_cart_ts IS NOT NULL AND NOT(purchase_after_view_cart_ts>cart_after_view_ts)) OR
       (purchase_after_cart_ts IS NOT NULL AND NOT(purchase_after_cart_ts>cart_anchor_ts))''').fetchone()[0]
    if invalid:raise AssertionError('Ordered-stage invariant failed.')
    return {'table_counts':counts,'foreign_key_violations':0,'sqlite_integrity':integrity,
            'event_reporting_join_rows':joined,'session_event_totals_reconcile':True,
            'ordered_stage_invariants':True}


def independent_source_counts(raw_path,config):
    # No SQL model rows are read here. Re-read raw CSV, dedup via nine-field
    # SHA-256 fingerprints, then execute the independent Python reference logic.
    seen=set()
    events=[]
    with raw_path.open(encoding='utf-8-sig',newline='') as stream:
        for ordinal,row in enumerate(csv.DictReader(stream),1):
            key=hashlib.sha256(json.dumps([row[k] for k in REES],ensure_ascii=False).encode()).digest()
            if key in seen:continue
            seen.add(key)
            events.append(Event(ordinal,row['user_id'],row['product_id'],row['event_type'],
                                int(timestamp(row['event_time']).timestamp())))
    del seen
    gc.collect()
    result=python_counts(events,config['observed_end'],config['gap_seconds'],config['horizon_seconds'])
    return result,len(events)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'data/processed/project01.sqlite')
    args=parser.parse_args()
    target=args.output.resolve()
    if target.exists():raise FileExistsError('Existing model is preserved. Choose a new --output filename for a rebuild.')
    building=target.with_name(target.name+'.building')
    if building.exists():raise FileExistsError('An incomplete build exists; inspect it or choose a new output filename.')
    contract=json.loads(CONTRACT.read_text())
    raw=ROOT/'data/raw/rees46/events.csv'
    hill=ROOT/'data/raw/hillstrom/hillstrom.csv.gz'
    before={str(p.relative_to(ROOT)):file_hash(p) for p in [raw,hill]}
    verify_sources()
    p=contract['parameters']
    config={'gap_seconds':p['primary_session_gap_seconds'],
            'sensitivity_gap_seconds':p['sensitivity_session_gap_seconds'],
            'horizon_seconds':p['primary_followup_seconds'],
            'observed_start':int(datetime.fromisoformat(contract['rees46']['observation_start_utc']).timestamp()),
            'observed_end':int(datetime.fromisoformat(contract['rees46']['observation_end_utc']).timestamp()),
            'source_sha256':before['data/raw/rees46/events.csv'],'contract_sha256':file_hash(CONTRACT),
            'enforce_source_bounds':True}
    target.parent.mkdir(parents=True,exist_ok=True)
    with sqlite3.connect(building) as conn:
        with raw.open(encoding='utf-8-sig',newline='') as stream:
            raw_rows=create_model(conn,csv.DictReader(stream),config,lambda msg:print(msg,flush=True))
        checks=model_checks(conn,raw_rows)
        sql=metric_counts(conn)
    print('Re-reading raw CSV for independent Python metric reconciliation.',flush=True)
    py,py_events=independent_source_counts(raw,config)
    if sql!=py:
        differences={k:{'sql':sql[k],'python':py[k]} for k in sql if sql[k]!=py[k]}
        raise AssertionError(f'SQL/Python mismatch: {differences}')
    if py_events!=checks['table_counts']['fact_event']:raise AssertionError('Independent event dedup mismatch.')
    after={str(p.relative_to(ROOT)):file_hash(p) for p in [raw,hill]}
    if before!=after:raise RuntimeError('Raw inputs changed.')
    paths=[Path(__file__),ROOT/'src/contract_metrics.py',MODEL_SQL,METRIC_SQL,CONTRACT]
    result={'chapter':'05','created_at_utc':datetime.now(timezone.utc).isoformat(),
            'data_kind':'actual_full_REES46_source','source_hashes_before':before,'source_hashes_after':after,
            'raw_unchanged':True,'model_path':str(target.relative_to(ROOT)),
            'contract_version':contract['version'],'sqlite_version':sqlite3.sqlite_version,
            'raw_rows':raw_rows,'checks':checks,'sql_counts':sql,'independent_python_counts':py,
            'all_metric_counts_equal':True,'metrics':metric_values(sql),
            'code_and_contract_hashes':{str(p.relative_to(ROOT)):file_hash(p) for p in paths},
            'hillstrom_effects_computed':False,'model_validated_before_publication':True}
    building.rename(target)
    result['model_sha256']=file_hash(target)
    (ROOT/'reports/05_model_validation.json').write_text(json.dumps(result,indent=2)+'\n')
    with (ROOT/'reports/05_metric_reconciliation.csv').open('w',newline='') as stream:
        writer=csv.writer(stream)
        writer.writerow(['metric_id','numerator','denominator','percent','sql_python_equal','contract_version'])
        for key,value in result['metrics'].items():
            writer.writerow([key,value['numerator'],value['denominator'],value['percent'],True,contract['version']])
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
