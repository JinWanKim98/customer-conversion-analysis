"""Chapter 08 sensitivity, fixed populations, and private cluster count vectors."""

from intake import read_sql
import csv
import gc
import json
import sqlite3
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path

from contract_metrics import Event,python_counts
from intake import file_hash,timestamp

ROOT=Path(__file__).resolve().parents[1]
PLAN=ROOT/'docs/08_robustness_plan.json'
SETUP=ROOT/'analysis.sql'
TARGETS=[('TV',"category_code='electronics.video.tv'"),
         ('Video cards',"category_code='computers.components.videocards'"),
         ('Unknown category',"trim(category_code)=''"),('Price 1000+',"price_value>=1000")]


def counts_sql(group,source='robust_segment_paths',include_cart=True):
    if group not in ['scenario','user_id','product_id']:raise ValueError(group)
    fields=['COUNT(*) AS n','SUM(purchase) AS y']
    if include_cart:fields.append('SUM(cart) AS c')
    for i,(_,condition) in enumerate(TARGETS):
        fields.extend([f'SUM({condition}) AS n{i}',f'SUM(CASE WHEN {condition} THEN purchase ELSE 0 END) AS y{i}'])
        if include_cart:fields.append(f'SUM(CASE WHEN {condition} THEN cart ELSE 0 END) AS c{i}')
    prefix='scenario,' if group=='scenario' else ''
    return f'SELECT {prefix}'+','.join(fields)+f' FROM {source} GROUP BY {group} ORDER BY {group}'


def rates(row):
    r=dict(row);n,c,y=r['eligible_groups'],r.get('cart_groups'),r['purchase_groups']
    r['ordered_purchase_pct']=100*y/n if n else None
    if c is not None:
        r['view_to_cart_pct']=100*c/n if n else None
        r['cart_to_purchase_pct']=100*y/c if c else None
    return r


def collect(conn):
    conn.row_factory=sqlite3.Row
    conn.execute('PRAGMA temp_store=MEMORY')
    conn.executescript(read_sql('07_diagnostic_cohorts.sql'))
    conn.executescript(read_sql('08_robustness_setup.sql'))
    scenarios=[]
    for row in conn.execute(counts_sql('scenario')):
        for i,name in [(-1,'Overall')]+list(enumerate(t[0] for t in TARGETS)):
            suffix='' if i==-1 else str(i)
            scenarios.append(rates({'scenario':row['scenario'],'target':name,'eligible_groups':row['n'+suffix],
                'cart_groups':row['c'+suffix],'purchase_groups':row['y'+suffix]}))
    def window_rows(table,include_cart):
        lookup={(r['population'],r['days']):dict(r) for r in conn.execute(f'SELECT * FROM {table}')}
        result=[]
        for population in ['matched_7day','native']:
            for days in [1,3,7]:
                empty={'population':population,'days':days,'eligible_groups':0,'purchase_groups':0}
                if include_cart:empty['cart_groups']=0
                result.append(rates(lookup.get((population,days),empty)))
        return result
    windows=window_rows('robust_windows',True)
    carts=window_rows('robust_cart_windows',False)
    sessions=[]
    for gap in [30,60]:
        row=conn.execute(f'SELECT COUNT(*) AS denominator,SUM(purchase_events>0) AS numerator,SUM(closed_in_snapshot=0) AS open_sessions FROM fact_session_{gap}').fetchone()
        sessions.append({'gap_minutes':gap,**dict(row),'percent':100*row['numerator']/row['denominator'] if row['denominator'] else None})
    violations=conn.execute('SELECT COUNT(*) FROM robust_fixed_anchors WHERE (cart60_ts IS NOT NULL)<cart_reached OR (purchase60_ts IS NOT NULL)<ordered_purchase_reached').fetchone()[0]
    assert violations==0,'Larger containing session must retain every fixed-anchor path'
    return {'scenarios':scenarios,'view_windows':windows,'cart_windows':carts,
            'native_session_snapshots':sessions,'fixed_anchor_monotonicity_violations':violations}


def verify(p,base):
    overall={r['scenario']:r for r in p['scenarios'] if r['target']=='Overall'}
    r=overall['native_30']
    assert (r['eligible_groups'],r['cart_groups'],r['purchase_groups'])==(base['session_product_den'],base['session_product_cart_num'],base['session_product_purchase_num'])
    matched=[r for r in p['view_windows'] if r['population']=='matched_7day']
    assert len({r['eligible_groups'] for r in matched})==1
    for kind in ['view_windows','cart_windows']:
        rows=[r for r in p[kind] if r['population']=='matched_7day']
        assert [r['purchase_groups'] for r in rows]==sorted(r['purchase_groups'] for r in rows)
        native7=next(r for r in p[kind] if r['population']=='native' and r['days']==7)
        assert native7['eligible_groups']==rows[-1]['eligible_groups'] and native7['purchase_groups']==rows[-1]['purchase_groups']
    assert matched[-1]['eligible_groups']==base['view7_den'] and matched[-1]['purchase_groups']==base['view_cart_purchase7_num']
    a,b=overall['fixed_anchor_30'],overall['fixed_anchor_60']
    assert a['eligible_groups']==b['eligible_groups']
    assert a['purchase_groups']<=b['purchase_groups'] and a['cart_groups']<=b['cart_groups']
    for r in p['scenarios']:assert 0<=r['purchase_groups']<=r['cart_groups']<=r['eligible_groups']
    return {'primary_counts_match_chapter05':True,'window_population_and_nesting':True,
            'fixed_anchor_population_and_nesting':True,'all_stage_counts_nested':True}


def raw_reference(path,end):
    events=[];mix=Counter()
    with path.open(encoding='utf-8-sig',newline='') as stream:
        for i,row in enumerate(csv.DictReader(stream),1):
            events.append(Event(i,row['user_id'],row['product_id'],row['event_type'],int(timestamp(row['event_time']).timestamp())))
            mix[row['event_type']]+=1
    output={str(gap):python_counts(events,end,gap*60,7*86400) for gap in [30,60]}
    return {'event_rows':len(events),'event_mix':dict(mix),'counts_by_gap_minutes':output}


def save_csv(path,rows):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)


def main():
    model=ROOT/'data/processed/project01.sqlite';before=file_hash(model)
    from reproducibility import verify_sources
    verify_sources()
    prior={'model_sha256':before,'source_hashes':{name:file_hash(ROOT/name) for name in ['data/raw/rees46/events.csv','data/raw/hillstrom/hillstrom.csv.gz']}}
    contract=json.loads((ROOT/'docs/04_metric_contract.json').read_text())
    end=int(datetime.fromisoformat(contract['rees46']['observation_end_utc']).timestamp())
    print('Re-reading all raw rows for independent 30/60-minute counts...',flush=True)
    raw=raw_reference(ROOT/'data/raw/rees46/events.csv',end);gc.collect()
    print('Building read-only temporary sensitivity cohorts...',flush=True)
    vectors=[]
    with sqlite3.connect(model.as_uri()+'?mode=ro',uri=True) as conn:
        p=collect(conn)
        base=dict(conn.execute(read_sql('05_metric_queries.sql')).fetchone())
        checks=verify(p,base)
        expected60=dict(base)
        sixty=next(r for r in p['scenarios'] if r['scenario']=='native_60' and r['target']=='Overall')
        snapshot60=p['native_session_snapshots'][1]
        expected60.update(session_den=snapshot60['denominator'],session_num=snapshot60['numerator'],
            session_product_den=sixty['eligible_groups'],session_product_cart_num=sixty['cart_groups'],
            session_product_purchase_num=sixty['purchase_groups'],excluded_open_session_groups=snapshot60['open_sessions'])
        assert raw['counts_by_gap_minutes']['30']==base
        assert raw['counts_by_gap_minutes']['60']==expected60
        raw['all_raw_canonical_contracted_counts_equal_at_both_gaps']=True
        print('Raw/canonical counts and all sensitivity cohort checks passed.',flush=True)
        source="(SELECT *,ordered_purchase_reached AS purchase FROM diagnostic_view_groups WHERE cohort='session_30')"
        for cluster in ['user_id','product_id']:
            query=counts_sql(cluster,source,include_cart=False)
            path=ROOT/f'data/work/08_{cluster}_counts.csv'
            rows=list(conn.execute(query))
            save_csv(path,[dict(row) for row in rows])
            assert sum(row['n'] for row in rows)==base['session_product_den']
            assert sum(row['y'] for row in rows)==base['session_product_purchase_num']
            vectors.append({'cluster':cluster,'clusters':len(rows),'path':str(path.relative_to(ROOT)),
                            'sha256':file_hash(path),'columns':list(rows[0].keys())})
        canonical_mix={r[0]:r[1] for r in conn.execute('SELECT event_type,COUNT(*) FROM fact_event GROUP BY event_type')}
    assert file_hash(model)==before
    assert all(file_hash(ROOT/name)==sha for name,sha in prior['source_hashes'].items())
    payload={'chapter':'08','created_at_utc':datetime.now(timezone.utc).isoformat(),
        'data_kind':'actual_full_REES46_curated_and_preserved_raw','model_sha256':before,
        'source_hashes':prior['source_hashes'],'model_read_only':True,'raw_unchanged':True,
        'plan':json.loads(PLAN.read_text()),'profiles':p,'checks':checks,'raw_sensitivity':raw,
        'canonical_event_mix':canonical_mix,'private_cluster_vectors':vectors,
        'code_hashes':{str(path.relative_to(ROOT)):file_hash(path) for path in [Path(__file__),SETUP,PLAN,ROOT/'analysis.sql',ROOT/'src/contract_metrics.py']}}
    (ROOT/'reports/08_robustness_results.json').write_text(json.dumps(payload,indent=2)+'\n')
    for name in ['scenarios','view_windows','cart_windows','native_session_snapshots']:
        save_csv(ROOT/f'reports/08_{name}.csv',p[name])
    print(json.dumps(p,indent=2))


if __name__=='__main__':main()
