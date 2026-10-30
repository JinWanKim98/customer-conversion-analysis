"""Chapter 07: read-only, anchor-attributed descriptive conversion diagnostics."""
import csv
import json
import re
import sqlite3
from datetime import datetime,timezone
from pathlib import Path

from intake import file_hash,read_sql
from reproducibility import verify_sources

ROOT=Path(__file__).resolve().parents[1]
SETUP=ROOT/'analysis.sql'
QUERY=ROOT/'analysis.sql'
PLAN=ROOT/'docs/07_diagnostic_plan.json'


def percent(num,den):
    return 100*num/den if den else None


def decorate(row,thresholds):
    r=dict(row)
    n,c,p=r['eligible_groups'],r['cart_groups'],r['ordered_purchase_groups']
    r.update(view_to_cart_pct=percent(c,n),ordered_purchase_pct=percent(p,n),
             cart_to_ordered_purchase_pct=percent(p,c),
             no_qualifying_cart_groups=n-c,no_ordered_purchase_after_cart_groups=c-p,
             below_presentation_threshold=any(r[k]<v for k,v in thresholds.items()))
    return r


def collect(conn,plan):
    conn.row_factory=sqlite3.Row
    conn.execute('PRAGMA temp_store=MEMORY')
    conn.executescript(read_sql('07_diagnostic_cohorts.sql'))
    try:
        parts=re.split(r'^-- name: (\w+)\s*$',read_sql('07_conversion_diagnostics.sql'),flags=re.MULTILINE)
        profiles={parts[i]:[dict(r) for r in conn.execute(parts[i+1])]
                  for i in range(1,len(parts),2)}
    finally:
        conn.execute('DROP TABLE diagnostic_view_groups')
    thresholds=plan['presentation_support_thresholds']
    for name in ['overall','category','price_band']:
        profiles[name]=[decorate(r,thresholds) for r in profiles[name]]
    baseline={r['cohort']:r for r in profiles['overall']}
    for name in ['category','price_band']:
        for r in profiles[name]:
            b=baseline[r['cohort']]
            r['ordered_purchase_gap_to_overall_pp']=r['ordered_purchase_pct']-b['ordered_purchase_pct']
    profiles['snapshot_metrics']=[dict(r) for r in conn.execute(read_sql('05_metric_queries.sql'))][0]
    return profiles


def verify(profiles):
    m=profiles['snapshot_metrics']
    expected={'pair_7d':(m['view7_den'],m['view_cart7_num'],m['view_cart_purchase7_num']),
              'session_30':(m['session_product_den'],m['session_product_cart_num'],m['session_product_purchase_num'])}
    keys=['eligible_groups','cart_groups','ordered_purchase_groups']
    overall={r['cohort']:r for r in profiles['overall']}
    for cohort,values in expected.items():
        assert tuple(overall[cohort][k] for k in keys)==values,(cohort,'reference mismatch')
        for name in ['category','price_band']:
            rows=[r for r in profiles[name] if r['cohort']==cohort]
            assert tuple(sum(r[k] for r in rows) for k in keys)==values,(cohort,name,'segment reconciliation')
            assert all(0<=r['ordered_purchase_groups']<=r['cart_groups']<=r['eligible_groups'] for r in rows)
    assert all(v==0 for v in profiles['key_validation'][0].values()),'nonunique/non-nested group'
    ordered=next((r['purchase_containing_groups'] for r in profiles['purchase_path_coverage'] if r['path_status']=='eligible_ordered_path'),0)
    assert ordered==m['session_product_purchase_num'],'purchase coverage'
    return {'all_cohorts_match_chapter05':True,'all_segment_counts_reconcile':True,
            'one_row_per_group_and_nested_stages':True,'ordered_path_coverage_reconciles':True}


def main():
    model=ROOT/'data/processed/project01.sqlite'
    sha=file_hash(model)
    verify_sources()
    raw={name:file_hash(ROOT/name) for name in ['data/raw/rees46/events.csv','data/raw/hillstrom/hillstrom.csv.gz']}
    prior=json.loads((ROOT/'reports/06_eda_results.json').read_text())
    assert raw==prior['source_hashes'],'source snapshot differs'
    plan=json.loads(PLAN.read_text())
    with sqlite3.connect(model.as_uri()+'?mode=ro',uri=True) as conn:
        profiles=collect(conn,plan)
        total_purchase_events=conn.execute("SELECT COUNT(*) FROM fact_event WHERE event_type='purchase'").fetchone()[0]
    checks=verify(profiles)
    assert sum(r['purchase_events'] for r in profiles['purchase_path_coverage'])==total_purchase_events
    assert file_hash(model)==sha
    assert all(file_hash(ROOT/name)==h for name,h in raw.items())
    payload={'chapter':'07','created_at_utc':datetime.now(timezone.utc).isoformat(),
             'data_kind':'actual_full_REES46_curated_model','model_sha256':sha,'source_hashes':raw,
             'model_read_only':True,'raw_unchanged':True,'time_zone':'UTC','plan':plan,
             'checks':checks,'profiles':profiles,'purchase_events_reconciled':total_purchase_events,
             'confidence_intervals_computed':False,'causal_effects_computed':False,
             'code_hashes':{str(p.relative_to(ROOT)):file_hash(p) for p in [Path(__file__),SETUP,QUERY,PLAN]}}
    (ROOT/'reports/07_conversion_results.json').write_text(json.dumps(payload,indent=2)+'\n')
    for name in ['overall','category','price_band','exclusions','purchase_path_coverage','anchor_tie_audit']:
        rows=profiles[name]
        if rows:
            with (ROOT/f'reports/07_{name}.csv').open('w',newline='') as stream:
                writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    print(json.dumps({k:profiles[k] for k in ['overall','exclusions','purchase_path_coverage','anchor_tie_audit']},indent=2))
    print('Full-model reconciliation passed; raw and persistent model unchanged.')


if __name__=='__main__':main()
