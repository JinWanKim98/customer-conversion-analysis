"""Chapter 06 descriptive EDA: read-only SQL profiles, checked aggregates and reports."""
from __future__ import annotations

from intake import read_sql

import argparse
import calendar
import csv
import json
import math
import re
import sqlite3
from datetime import date,datetime,timedelta,timezone
from pathlib import Path

from intake import file_hash

ROOT=Path(__file__).resolve().parents[1]
QUERY=ROOT/'analysis.sql'


def quantile(sorted_values,p):
    if not sorted_values:return None
    location=(len(sorted_values)-1)*p
    lower=math.floor(location)
    upper=math.ceil(location)
    return sorted_values[lower]+(sorted_values[upper]-sorted_values[lower])*(location-lower)


def monthly_exposure(rows):
    output=[]
    for row in rows:
        item=dict(row)
        year,month=map(int,item['month'].split('-'))
        item['calendar_dates_in_month']=calendar.monthrange(year,month)[1]
        item['partial_calendar_month']=item['represented_dates']!=item['calendar_dates_in_month']
        item['events_per_represented_date']=item['events']/item['represented_dates']
        output.append(item)
    return output


def concentration(distribution,fraction):
    n=sum(r['products'] for r in distribution)
    target=math.ceil(n*fraction)
    remaining=target
    chosen_events=0
    for row in sorted(distribution,key=lambda r:r['events'],reverse=True):
        take=min(remaining,row['products'])
        chosen_events+=take*row['events']
        remaining-=take
        if not remaining:break
    total=sum(r['events']*r['products'] for r in distribution)
    return {'product_fraction_target':fraction,'selected_product_count':target,
            'events_in_selected_products':chosen_events,
            'event_share_pct':100*chosen_events/total if total else None}


def collect(conn):
    conn.row_factory=sqlite3.Row
    parts=re.split(r'^-- name: (\w+)\s*$',read_sql('06_eda_queries.sql'),flags=re.MULTILINE)
    profiles={parts[i]:[dict(r) for r in conn.execute(parts[i+1])]
              for i in range(1,len(parts),2)}
    profiles['monthly_utc']=monthly_exposure(profiles['monthly_utc'])
    prices=[r[0] for r in conn.execute('SELECT price_value FROM fact_event ORDER BY price_value')]
    durations=[r[0] for r in conn.execute('SELECT last_ts-first_ts FROM fact_session_30 ORDER BY last_ts-first_ts')]
    profiles['price_summary']={'weighting':'event-weighted, all retained event types',
        'units':'source-reported price units; currency not assumed',
        'count':len(prices),'minimum':prices[0] if prices else None,
        'median':quantile(prices,0.5),'p95':quantile(prices,0.95),
        'p99':quantile(prices,0.99),'maximum':prices[-1] if prices else None}
    profiles['session_duration_seconds']={'count':len(durations),
        'median':quantile(durations,0.5),'p95':quantile(durations,0.95),
        'p99':quantile(durations,0.99),'maximum':durations[-1] if durations else None,
        'interpretation':'first-to-last recorded event, not active engagement time'}
    bounds=profiles['observation_bounds'][0]
    if bounds['first_ts'] is not None:
        first=datetime.fromtimestamp(bounds['first_ts'],timezone.utc).date()
        last=datetime.fromtimestamp(bounds['last_ts'],timezone.utc).date()
        represented={date.fromisoformat(r['utc_date']) for r in profiles['daily_utc']}
        profiles['date_coverage']={'inclusive_calendar_dates':(last-first).days+1,
            'represented_dates':len(represented),
            'dates_without_events':[str(first+timedelta(days=i)) for i in range((last-first).days+1)
                                    if first+timedelta(days=i) not in represented],
            'limitation':'represented dates do not prove uninterrupted instrumentation'}
    else:profiles['date_coverage']={'inclusive_calendar_dates':0,'represented_dates':0,'dates_without_events':[]}
    profiles['product_concentration']=[concentration(profiles['product_event_distribution'],f) for f in (0.01,0.1)]
    profiles['model_counts']={name:conn.execute(f'SELECT COUNT(*) FROM {name}').fetchone()[0]
                            for name in ['fact_event','dim_user','dim_product','fact_session_30']}
    return profiles


def verify(profiles):
    totals=profiles['model_counts']
    events=totals['fact_event']
    for name in ['event_mix','daily_utc','monthly_utc','hourly_utc','price_bands','category_profile']:
        if sum(r['events'] for r in profiles[name])!=events:raise AssertionError(name+' event total differs')
    if sum(r['users'] for r in profiles['user_event_frequency'])!=totals['dim_user']:raise AssertionError('User buckets')
    if sum(r['events'] for r in profiles['user_event_frequency'])!=events:raise AssertionError('User bucket event totals')
    if sum(r['users'] for r in profiles['user_session_frequency'])!=totals['dim_user']:raise AssertionError('Visit user buckets')
    if sum(r['sessions'] for r in profiles['user_session_frequency'])!=totals['fact_session_30']:raise AssertionError('User visit totals')
    if sum(r['sessions'] for r in profiles['session_event_frequency'])!=totals['fact_session_30']:raise AssertionError('Session buckets')
    if sum(r['events'] for r in profiles['session_event_frequency'])!=events:raise AssertionError('Session event totals')
    if sum(r['products'] for r in profiles['product_event_distribution'])!=totals['dim_product']:raise AssertionError('Product count')
    if sum(r['events']*r['products'] for r in profiles['product_event_distribution'])!=events:raise AssertionError('Product event totals')
    purchases=next((r['events'] for r in profiles['event_mix'] if r['event_type']=='purchase'),0)
    for name in ['daily_utc','monthly_utc','hourly_utc','price_bands','category_profile']:
        if sum(r['purchase_events'] for r in profiles[name])!=purchases:raise AssertionError(name+' purchase total')
    if profiles['price_summary']['count']!=events:raise AssertionError('Price denominator')
    return {'all_event_profiles_reconcile':True,'all_purchase_profiles_reconcile':True,
            'user_session_product_buckets_reconcile':True,'price_population_reconciles':True}


def save_csv(path,rows):
    if not rows:return
    with path.open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]))
        writer.writeheader();writer.writerows(rows)


def render_figures(profiles, output_dir):
    """Regenerate the notebook's two EDA figures from checked model aggregates."""
    import matplotlib
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    import matplotlib.dates as mdates
    from matplotlib.ticker import StrMethodFormatter

    verify(profiles)
    output_dir=Path(output_dir)
    output_dir.mkdir(parents=True,exist_ok=True)
    blue='#275c80'
    with matplotlib.rc_context({'font.family':'DejaVu Sans','font.size':12,
                         'axes.spines.top':False,'axes.spines.right':False}):
        fig=Figure(figsize=(16,12))
        FigureCanvasAgg(fig)
        axes=fig.subplots(2,1)
        fig.suptitle('REES46: observed event volume over time',fontsize=21,weight='bold')
        daily=sorted(profiles['daily_utc'],key=lambda r:r['utc_date'])
        axes[0].plot([date.fromisoformat(r['utc_date']) for r in daily],
                     [r['events'] for r in daily],color=blue)
        axes[0].set(title='Daily retained event records',xlabel='UTC calendar date',ylabel='Events per date')
        axes[0].xaxis.set_major_locator(mdates.MonthLocator())
        axes[0].xaxis.set_major_formatter(mdates.DateFormatter('%b %Y'))
        months=[r for r in profiles['monthly_utc'] if not r['partial_calendar_month']]
        bars=axes[1].bar([r['month'] for r in months],
                         [r['events_per_represented_date'] for r in months],color=blue)
        axes[1].bar_label(bars,labels=[f"{r['events_per_represented_date']:,.0f}" for r in months],padding=6)
        axes[1].set(title='Monthly average per represented UTC date',
                    xlabel='Calendar-complete months in this file',ylabel='Events / represented date')
        axes[1].set_ylim(0,max((r['events_per_represented_date'] for r in months),default=1)*1.2)
        for ax in axes:
            ax.yaxis.set_major_formatter(StrMethodFormatter('{x:,.0f}'))
            ax.grid(axis='y',alpha=.16)
            ax.set_axisbelow(True)
        partial=[f"{r['month']} ({r['represented_dates']} represented dates)"
                 for r in profiles['monthly_utc'] if r['partial_calendar_month']]
        fig.text(.5,.018,'Partial months: '+(', '.join(partial) or 'none')+
                 '. Date coverage does not prove uninterrupted tracking.',ha='center',fontsize=11)
        fig.tight_layout(rect=(0,.04,1,.96),h_pad=2)
        fig.savefig(output_dir/'eda_time.png',dpi=240,facecolor='white')
        fig.clear()

        fig=Figure(figsize=(18,13))
        FigureCanvasAgg(fig)
        axes=fig.subplots(2,2)
        fig.suptitle('REES46: record composition and concentration',fontsize=21,weight='bold')
        mix={r['event_type']:r['events'] for r in profiles['event_mix']}
        labels=[name for name in ['view','cart','purchase'] if name in mix]
        total=profiles['model_counts']['fact_event']
        bars=axes[0,0].barh(labels,[mix[name] for name in labels],color=blue)
        axes[0,0].invert_yaxis()
        axes[0,0].bar_label(bars,labels=[f'{mix[name]:,} ({100*mix[name]/total:.1f}%)' for name in labels],padding=5)
        axes[0,0].set_xlim(0,max(mix.values())*1.45)
        axes[0,0].set(title='Event counts: not an ordered funnel',xlabel='Event records',ylabel='Event type')
        axes[0,0].xaxis.set_major_formatter(StrMethodFormatter('{x:,.0f}'))
        users=profiles['user_event_frequency']
        shares=[100*r['users']/profiles['model_counts']['dim_user'] for r in users]
        bars=axes[0,1].bar([r['event_count_bucket'] for r in users],shares,color=blue)
        axes[0,1].bar_label(bars,labels=[f'{v:.1f}%' for v in shares],padding=6)
        axes[0,1].set(title='Recorded events per observed user',xlabel='Events in the observed file',
                      ylabel='Share of observed users (%)',ylim=(0,100))
        prices=profiles['price_bands']
        axes[1,0].bar([r['price_band'] for r in prices],[r['events'] for r in prices],color=blue)
        axes[1,0].tick_params(axis='x',labelrotation=35)
        axes[1,0].yaxis.set_major_formatter(StrMethodFormatter('{x:,.0f}'))
        axes[1,0].set(title='Event-weighted reported price distribution',
                      xlabel='Source-reported price units (currency not assumed)',ylabel='Event records')
        concentration=profiles['product_concentration']
        bars=axes[1,1].bar([f"Top {100*r['product_fraction_target']:g}%" for r in concentration],
                           [r['event_share_pct'] for r in concentration],color='#a94f23')
        axes[1,1].bar_label(bars,labels=[f"{r['event_share_pct']:.1f}%" for r in concentration],padding=6)
        axes[1,1].set(title='Cumulative event coverage by busiest products',
                      xlabel='Products ranked by recorded event count',ylabel='Share of all event records (%)',ylim=(0,100))
        fig.text(.5,.018,'Descriptive record profiles. Event counts are not users, orders, revenue or causal effects.',
                 ha='center',fontsize=11)
        fig.tight_layout(rect=(0,.04,1,.96),h_pad=2,w_pad=2)
        fig.savefig(output_dir/'eda_behavior.png',dpi=240,facecolor='white')
        fig.clear()
    return [output_dir/'eda_time.png',output_dir/'eda_behavior.png']


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database',type=Path,default=ROOT/'data/processed/project01.sqlite')
    args=parser.parse_args()
    model=args.database.resolve()
    from reproducibility import verify_sources
    verify_sources()
    before=file_hash(model)

    raw_before={str(p.relative_to(ROOT)):file_hash(p) for p in [ROOT/'data/raw/rees46/events.csv',ROOT/'data/raw/hillstrom/hillstrom.csv.gz']}
    with sqlite3.connect(model.as_uri()+'?mode=ro',uri=True) as conn:profiles=collect(conn)
    checks=verify(profiles)
    figures=render_figures(profiles,ROOT/'images')
    if file_hash(model)!=before:raise AssertionError('Model changed during EDA.')
    for path,sha in raw_before.items():
        if file_hash(ROOT/path)!=sha:raise AssertionError('Raw file changed during EDA.')
    payload={'chapter':'06','created_at_utc':datetime.now(timezone.utc).isoformat(),
        'data_kind':'actual_full_REES46_curated_model','model_sha256':before,
        'source_hashes':raw_before,'model_read_only':True,'raw_unchanged':True,
        'time_zone':'UTC','checks':checks,'profiles':profiles,
        'figures':[{ 'path':str(p.relative_to(ROOT)), 'sha256':file_hash(p)} for p in figures],
        'code_hashes':{str(p.relative_to(ROOT)):file_hash(p) for p in [Path(__file__),QUERY]},
        'not_causal':True,'hillstrom_effects_computed':False}
    (ROOT/'reports/06_eda_results.json').write_text(json.dumps(payload,indent=2)+'\n')
    for name in ['event_mix','daily_utc','monthly_utc','hourly_utc','user_event_frequency',
                 'user_session_frequency','session_event_frequency','price_bands','category_profile','product_concentration']:
        save_csv(ROOT/f'reports/06_{name}.csv',profiles[name])
    print(json.dumps({k:profiles[k] for k in ['event_mix','monthly_utc','user_event_frequency',
          'user_session_frequency','session_event_frequency','price_summary','session_duration_seconds',
          'attribute_missingness','product_concentration','date_coverage']},indent=2))
    print('All aggregate reconciliation checks passed. Model and raw inputs unchanged.')


if __name__=='__main__':main()
