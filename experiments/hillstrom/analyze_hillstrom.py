"""Separate historical randomized-email experiment, frozen ITT analysis."""

import csv
import gzip
import json
import math
import sqlite3
import sys
from collections import Counter
from datetime import datetime,timezone
from decimal import Decimal
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src'))
from intake import HILL,file_hash,read_sql
from reproducibility import verify_sources
from hillstrom_stats import compare_binary,holm,smd,bootstrap_spend_means,percentile_interval

ARMS=['No E-Mail','Mens E-Mail','Womens E-Mail']
PLAN=ROOT/'experiments/hillstrom/09_analysis_plan.json'
QUERY=ROOT/'analysis.sql'
RAW=ROOT/'data/raw/hillstrom/hillstrom.csv.gz'


def load_rows(path):
    rows=[]
    with gzip.open(path,'rt',encoding='utf-8-sig',newline='') as stream:
        reader=csv.DictReader(stream)
        if len(reader.fieldnames)!=len(HILL) or set(reader.fieldnames)!=set(HILL):raise ValueError('Unexpected schema.')
        for source_row,row in enumerate(reader,1):
            if None in row or any(v is None or not v.strip() for v in row.values()):raise ValueError('Missing/malformed field.')
            if row['segment'] not in ARMS:raise ValueError('Unexpected arm.')
            out=dict(row,source_row=source_row)
            for name in ['mens','womens','newbie','visit','conversion']:
                if row[name] not in ['0','1']:raise ValueError('Invalid binary.')
                out[name]=int(row[name])
            if not row['recency'].isdigit() or not 1<=int(row['recency'])<=12:raise ValueError('Invalid recency.')
            out['recency']=int(row['recency'])
            for name in ['history','spend']:
                value=Decimal(row[name])
                if not value.is_finite() or value<0:raise ValueError('Invalid monetary value.')
                if name=='spend':
                    cents=value*100
                    if cents!=cents.to_integral_value():raise ValueError('More than two spend decimals; review instead of rounding.')
                    out['spend_cents']=int(cents)
                out[name]=float(value)
            if out['conversion']>out['visit'] or (out['spend_cents']>0)!=bool(out['conversion']):raise ValueError('Outcome inconsistency.')
            rows.append(out)
    return rows


def arm_summary(rows):
    with sqlite3.connect(':memory:') as conn:
        conn.row_factory=sqlite3.Row
        conn.execute('CREATE TABLE assigned_customers(source_row INTEGER PRIMARY KEY,segment TEXT,conversion INTEGER,visit INTEGER,spend_cents INTEGER)')
        conn.executemany('INSERT INTO assigned_customers VALUES(?,?,?,?,?)',
            [(r['source_row'],r['segment'],r['conversion'],r['visit'],r['spend_cents']) for r in rows])
        sql=[dict(r) for r in conn.execute(read_sql('09_hillstrom_summary.sql'))]
    for r in sql:
        arm=[x for x in rows if x['segment']==r['segment']]
        independent={'segment':r['segment'],'assigned_n':len(arm),'purchasers':sum(x['conversion'] for x in arm),
            'visitors':sum(x['visit'] for x in arm),'spend_cents_total':sum(x['spend_cents'] for x in arm),
            'zero_spend_n':sum(x['spend_cents']==0 for x in arm),'maximum_spend_cents':max(x['spend_cents'] for x in arm)}
        assert independent==r,'Independent integer aggregation differs'
        r.update(purchase_pct=100*r['purchasers']/r['assigned_n'],visit_pct=100*r['visitors']/r['assigned_n'],
                 mean_spend_dollars=r['spend_cents_total']/(100*r['assigned_n']),zero_spend_pct=100*r['zero_spend_n']/r['assigned_n'])
    return sorted(sql,key=lambda r:ARMS.index(r['segment']))


def baseline_balance(rows,plan):
    import numpy as np
    grouped={arm:[r for r in rows if r['segment']==arm] for arm in ARMS}
    features=[(name,None) for name in plan['numeric']+plan['binary']]
    for name in plan['categorical']:
        features.extend((name,level) for level in sorted({r[name] for r in rows}))
    result=[]
    for name,level in features:
        arrays={arm:np.array([r[name] if level is None else int(r[name]==level) for r in group],dtype=float)
                for arm,group in grouped.items()}
        for arm in ARMS[1:]:
            a,c=arrays[arm],arrays[ARMS[0]]
            value=smd(float(a.mean()),float(a.var(ddof=1)),float(c.mean()),float(c.var(ddof=1)))
            result.append({'treatment':arm,'feature':name,'level':level,'treatment_n':len(a),'control_n':len(c),
                'treatment_mean':float(a.mean()),'control_mean':float(c.mean()),'smd':value,
                'abs_smd_above_point1':abs(value)>.1 if value is not None else None})
    return result


def analyze(rows,plan):
    import numpy as np
    from scipy.stats import chisquare
    from statsmodels.stats.proportion import confint_proportions_2indep,proportions_ztest
    from statsmodels.stats.multitest import multipletests
    summaries=arm_summary(rows);byarm={r['segment']:r for r in summaries};control=byarm[ARMS[0]]
    outcomes=[]
    for metric,key in [('purchase','purchasers'),('visit','visitors')]:
        for arm in ARMS[1:]:
            t=byarm[arm];r={'metric':metric,'treatment':arm,**compare_binary(t[key],t['assigned_n'],control[key],control['assigned_n'])}
            ci=confint_proportions_2indep(t[key],t['assigned_n'],control[key],control['assigned_n'],method='newcomb',compare='diff',alpha=.05)
            p=proportions_ztest([t[key],control[key]],[t['assigned_n'],control['assigned_n']],alternative='two-sided')[1]
            np.testing.assert_allclose([r['ci_low_pp'],r['ci_high_pp']],100*np.array(ci),rtol=1e-10,atol=1e-12)
            np.testing.assert_allclose(r['p_raw'],p,rtol=1e-10,atol=1e-15)
            r['primary_family']=metric=='purchase';outcomes.append(r)
    primary=[r for r in outcomes if r['primary_family']];adjusted=holm([r['p_raw'] for r in primary])
    verified=multipletests([r['p_raw'] for r in primary],alpha=.05,method='holm')
    np.testing.assert_allclose(adjusted,verified[1],rtol=1e-10)
    for r,p in zip(primary,adjusted):r.update(p_holm=p,reject_holm_005=p<=.05)
    cents={arm:np.array([r['spend_cents'] for r in rows if r['segment']==arm],dtype=np.int64) for arm in ARMS}
    boot=bootstrap_spend_means(cents,plan['spend_bootstrap']['replicates'],plan['spend_bootstrap']['seed'])
    spend=[]
    for arm in ARMS[1:]:
        dist=boot[arm]-boot[ARMS[0]];ci=percentile_interval(dist)
        spend.append({'treatment':arm,'treatment_n':byarm[arm]['assigned_n'],'control_n':control['assigned_n'],
            'treatment_mean_dollars':byarm[arm]['mean_spend_dollars'],'control_mean_dollars':control['mean_spend_dollars'],
            'difference_dollars_per_assigned_customer':byarm[arm]['mean_spend_dollars']-control['mean_spend_dollars'],
            'ci_low_dollars':ci[0],'ci_high_dollars':ci[1],'replicates':len(dist),'secondary_exploratory':True})
    head=[]
    for metric,key in [('purchase','purchasers'),('visit','visitors')]:
        m,w=byarm[ARMS[1]],byarm[ARMS[2]]
        r={'metric':metric,'comparison':'Mens minus Womens (exploratory)',**compare_binary(m[key],m['assigned_n'],w[key],w['assigned_n'])}
        r.pop('p_raw');head.append(r)
    direct=boot[ARMS[1]]-boot[ARMS[2]];ci=percentile_interval(direct)
    head.append({'metric':'spend','comparison':'Mens minus Womens (exploratory)',
                 'difference_dollars_per_assigned_customer':byarm[ARMS[1]]['mean_spend_dollars']-byarm[ARMS[2]]['mean_spend_dollars'],
                 'ci_low_dollars':ci[0],'ci_high_dollars':ci[1]})
    counts=[byarm[a]['assigned_n'] for a in ARMS];expected=sum(counts)/3
    chi=sum((n-expected)**2/expected for n in counts);p_srm=math.exp(-chi/2)
    np.testing.assert_allclose([chi,p_srm],chisquare(counts),rtol=1e-10)
    allocation={'nominal_ratio':'1:1:1','chi_square':chi,'df':2,'p_value':p_srm,'flag_at_point001':p_srm<.001}
    return {'arm_summary':summaries,'binary_effects':outcomes,'spend_effects':spend,'exploratory_head_to_head':head,
            'allocation':allocation,'baseline_balance':baseline_balance(rows,plan['baseline_balance'])},boot


def save_csv(path,rows):
    fields=list(dict.fromkeys(k for r in rows for k in r))
    with path.open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader();writer.writerows(rows)


def main():
    from importlib.metadata import version
    import numpy as np
    plan=json.loads(PLAN.read_text());prior=json.loads((ROOT/'reports/08_robustness_results.json').read_text())
    snapshots={**prior['source_hashes'],'data/processed/project01.sqlite':prior['model_sha256'],
               'docs/04_metric_contract.json':file_hash(ROOT/'docs/04_metric_contract.json')}
    for name,sha in snapshots.items():assert file_hash(ROOT/name)==sha
    verify_sources()
    rows=load_rows(RAW);assert len(rows)==64000
    print('All 64,000 assigned rows retained; analyzing separate randomized experiment...',flush=True)
    profiles,boot=analyze(rows,plan)
    assert {r['segment']:r['assigned_n'] for r in profiles['arm_summary']}=={'No E-Mail':21306,'Mens E-Mail':21307,'Womens E-Mail':21387}
    assert sum(r['assigned_n'] for r in profiles['arm_summary'])==len(rows)
    for name,sha in snapshots.items():assert file_hash(ROOT/name)==sha
    private=ROOT/'data/work/09_spend_bootstrap_means.npz';np.savez_compressed(private,**boot)
    output={'chapter':'09','created_at_utc':datetime.now(timezone.utc).isoformat(),
        'data_kind':'actual_Hillstrom_randomized_experiment_2008','source_sha256':file_hash(RAW),
        'all_assigned_rows_retained':True,'n':len(rows),'plan':plan,'profiles':profiles,
        'snapshots_unchanged':snapshots,'rees46_joined':False,
        'checks':{'sql_python_integer_aggregation_equal':True,'custom_stats_match_statsmodels_scipy':True,
                  'all_assigned_rows_in_denominators':True,'source_and_rees46_model_unchanged':True},
        'versions':{name:version(name) for name in ['numpy','pandas','scipy','statsmodels']},
        'code_hashes':{str(p.relative_to(ROOT)):file_hash(p) for p in [Path(__file__),ROOT/'src/hillstrom_stats.py',PLAN,QUERY]},
        'private_bootstrap':{'path':str(private.relative_to(ROOT)),'sha256':file_hash(private)}}
    (ROOT/'reports/09_ab_results.json').write_text(json.dumps(output,indent=2,allow_nan=False)+'\n')
    for name in ['arm_summary','binary_effects','spend_effects','baseline_balance','exploratory_head_to_head']:
        save_csv(ROOT/f'reports/09_{name}.csv',profiles[name])
    print(json.dumps({k:profiles[k] for k in ['arm_summary','binary_effects','spend_effects','allocation','exploratory_head_to_head']},indent=2))


if __name__=='__main__':main()
