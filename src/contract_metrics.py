"""Chapter 04 reference metrics on clearly labelled synthetic examples only."""
from __future__ import annotations

from intake import read_sql

import argparse
import json
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from intake import file_hash

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT/'docs/04_metric_contract.json'
SQL = ROOT/'analysis.sql'


@dataclass(frozen=True)
class Event:
    source_row: int
    user_id: str
    product_id: str
    event_type: str
    ts: int


def settings():
    return json.loads(CONTRACT.read_text())['parameters']


def validate(events, observed_end):
    if len({e.source_row for e in events}) != len(events):
        raise ValueError('Source-row ordinals must be unique.')
    for e in events:
        if not e.user_id.strip() or not e.product_id.strip():
            raise ValueError('Missing user/product identity requires review, not silent deletion.')
        if e.event_type not in {'view','cart','purchase'} or not isinstance(e.ts,int):
            raise ValueError('Invalid event type or timestamp.')
        if e.ts>observed_end:
            raise ValueError('Event lies outside the declared observation window.')


def python_counts(events, observed_end, gap_seconds=1800, horizon_seconds=604800):
    validate(events,observed_end)
    by_user=defaultdict(list)
    pairs=defaultdict(list)
    sessions=defaultdict(list)
    sp=defaultdict(list)
    for e in events:
        by_user[e.user_id].append(e)
        pairs[(e.user_id,e.product_id)].append(e)
    for user,rows in by_user.items():
        previous=None
        ordinal=0
        for e in sorted(rows,key=lambda e:(e.ts,e.source_row)):
            if previous is None or e.ts-previous>gap_seconds:
                ordinal+=1
            sessions[(user,ordinal)].append(e)
            sp[(user,ordinal,e.product_id)].append(e)
            previous=e.ts
    out=dict.fromkeys(['user_den','user_num','session_den','session_num','view7_den',
                      'view_cart7_num','view_cart_purchase7_num','cart7_den','cart_purchase7_num',
                      'session_product_den','session_product_cart_num','session_product_purchase_num',
                      'excluded_late_view_anchors','excluded_late_cart_anchors','excluded_open_session_groups'],0)
    out['user_den']=len(by_user)
    out['user_num']=sum(any(e.event_type=='purchase' for e in rows) for rows in by_user.values())
    out['session_den']=len(sessions)
    out['session_num']=sum(any(e.event_type=='purchase' for e in rows) for rows in sessions.values())

    def first(rows,kind,after=None,upper=None):
        values=[e.ts for e in rows if e.event_type==kind and (after is None or e.ts>after)
                and (upper is None or e.ts<=upper)]
        return min(values) if values else None

    for rows in pairs.values():
        view=first(rows,'view')
        cart=first(rows,'cart')
        if view is not None:
            if view+horizon_seconds<=observed_end:
                out['view7_den']+=1
                qualifying_cart=first(rows,'cart',view,view+horizon_seconds)
                if qualifying_cart is not None:
                    out['view_cart7_num']+=1
                    out['view_cart_purchase7_num']+=first(rows,'purchase',qualifying_cart,view+horizon_seconds) is not None
            else:
                out['excluded_late_view_anchors']+=1
        if cart is not None:
            if cart+horizon_seconds<=observed_end:
                out['cart7_den']+=1
                out['cart_purchase7_num']+=first(rows,'purchase',cart,cart+horizon_seconds) is not None
            else:
                out['excluded_late_cart_anchors']+=1
    closed={key for key,rows in sessions.items() if max(e.ts for e in rows)+gap_seconds<=observed_end}
    out['excluded_open_session_groups']=len(sessions)-len(closed)
    for (user,session,product),rows in sp.items():
        if (user,session) not in closed:
            continue
        view=first(rows,'view')
        if view is None:
            continue
        out['session_product_den']+=1
        cart=first(rows,'cart',view)
        if cart is not None:
            out['session_product_cart_num']+=1
            out['session_product_purchase_num']+=first(rows,'purchase',cart) is not None
    return out


def sql_counts(events,observed_end,gap_seconds=1800,horizon_seconds=604800):
    validate(events,observed_end)
    with sqlite3.connect(':memory:') as conn:
        conn.row_factory=sqlite3.Row
        conn.execute('CREATE TABLE canonical_events(source_row INTEGER PRIMARY KEY,user_id TEXT,product_id TEXT,event_type TEXT,ts INTEGER)')
        conn.executemany('INSERT INTO canonical_events VALUES(?,?,?,?,?)',
                         [(e.source_row,e.user_id,e.product_id,e.event_type,e.ts) for e in events])
        return dict(conn.execute(read_sql('04_reference_metrics.sql'),{'gap_seconds':gap_seconds,
                    'horizon_seconds':horizon_seconds,'observed_end':observed_end}).fetchone())


METRICS={'U01':('user_num','user_den'),'S01':('session_num','session_den'),
         'P01':('view_cart7_num','view7_den'),'P02':('view_cart_purchase7_num','view7_den'),
         'P03':('cart_purchase7_num','cart7_den'),
         'F01':('session_product_cart_num','session_product_den'),
         'F02':('session_product_purchase_num','session_product_den'),
         'F03':('session_product_purchase_num','session_product_cart_num')}


def metric_values(counts):
    return {key:{'numerator':counts[n],'denominator':counts[d],
                 'percent':100*counts[n]/counts[d] if counts[d] else None}
            for key,(n,d) in METRICS.items()}


def example_events():
    # Toy record for one user/product: elapsed minutes 0,20,55,70.
    return [Event(1,'Example A','Example product','view',0),
            Event(2,'Example A','Example product','cart',1200),
            Event(3,'Example A','Example product','purchase',3300),
            Event(4,'Example A','Example product','view',4200)]


def reference_validation():
    config=settings()
    end=8*86400
    output=[]
    for gap in [config['primary_session_gap_seconds'],config['sensitivity_session_gap_seconds']]:
        py=python_counts(example_events(),end,gap,config['primary_followup_seconds'])
        sql=sql_counts(example_events(),end,gap,config['primary_followup_seconds'])
        assert py==sql,(py,sql)
        assert py['session_den']==(2 if gap==1800 else 1)
        assert py['view_cart_purchase7_num']==1
        assert py['session_product_purchase_num']==(0 if gap==1800 else 1)
        output.append({'gap_seconds':gap,'counts':py,'metrics':metric_values(py)})
    return {'data_kind':'synthetic_teaching_example_not_REES46_results',
            'purpose':'validate definitions before production modelling',
            'sql_python_equal':True,'contract_sha256':file_hash(CONTRACT),
            'reference_sql_sha256':file_hash(SQL),'reference_python_sha256':file_hash(Path(__file__)),
            'examples':output,'hillstrom_effects_computed':False}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--validate',action='store_true',help='Save the synthetic contract-validation evidence.')
    args=parser.parse_args()
    result=reference_validation()
    if args.validate:
        (ROOT/'reports/04_contract_validation.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))


if __name__=='__main__':
    main()
