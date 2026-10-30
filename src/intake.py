"""Read-only source intake. Standard library only; no conversion-effect analysis."""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

REES = ['event_time', 'event_type', 'product_id', 'category_id', 'category_code',
        'brand', 'price', 'user_id', 'user_session']
HILL = ['recency', 'history_segment', 'history', 'mens', 'womens', 'zip_code',
        'newbie', 'channel', 'segment', 'visit', 'conversion', 'spend']
ARMS = {'Mens E-Mail', 'Womens E-Mail', 'No E-Mail'}


def file_hash(path: Path, algorithm: str = 'sha256') -> str:
    h = hashlib.new(algorithm)
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def number(value: str) -> Decimal | None:
    try:
        result = Decimal(value)
        return result if result.is_finite() else None
    except InvalidOperation:
        return None


def timestamp(value: str) -> datetime | None:
    try:
        result = datetime.fromisoformat(value.replace(' UTC', '+00:00').replace('Z', '+00:00'))
        if result.tzinfo is None:
            return None
        return result.astimezone(timezone.utc)
    except ValueError:
        return None


def audit(path: Path, dataset: str) -> dict:
    if path.name.endswith('.part'):
        raise ValueError('Refusing an incomplete download (.part).')
    expected = REES if dataset == 'rees46' else HILL
    opener = gzip.open if path.suffix == '.gz' else open
    count = malformed = duplicates = 0
    nulls, issues, types, arms = Counter(), Counter(), Counter(), Counter()
    seen, users, shared_sessions = set(), set(), set()
    session_owner, session_bounds = {}, {}
    start = end = None
    with opener(path, 'rt', encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        columns = reader.fieldnames or []
        if len(columns) != len(set(columns)) or set(columns) != set(expected):
            raise ValueError(f'Unexpected {dataset} schema: {columns}')
        for row in reader:
            count += 1
            if None in row or any(v is None for v in row.values()):
                malformed += 1
                continue
            nulls.update(k for k, v in row.items() if not v.strip())
            # Field-exact fingerprint: no trimming or type coercion before hashing.
            encoded = json.dumps([row[k] for k in columns], ensure_ascii=False).encode('utf-8')
            key = hashlib.sha256(encoded).digest()
            duplicates += key in seen
            seen.add(key)
            if dataset == 'rees46':
                types[row['event_type']] += 1
                issues['unknown_event_types'] += row['event_type'] not in {'view', 'cart', 'purchase'}
                moment = timestamp(row['event_time'])
                issues['invalid_or_timezone_missing_timestamps'] += moment is None
                if moment is not None:
                    start = min(start, moment) if start else moment
                    end = max(end, moment) if end else moment
                price = number(row['price'])
                issues['invalid_or_nonfinite_prices'] += price is None
                issues['negative_prices'] += price is not None and price < 0
                user, session = row['user_id'], row['user_session']
                if user.strip():
                    users.add(user)
                # Missing identifiers are counted in nulls and excluded from identity counts.
                if user.strip() and session.strip():
                    if session in session_owner and session_owner[session] != user:
                        shared_sessions.add(session)
                    else:
                        session_owner[session] = user
                    pair = (user, session)
                    if pair not in session_bounds:
                        session_bounds[pair] = [moment, moment]
                    elif moment is not None:
                        lo, hi = session_bounds[pair]
                        session_bounds[pair] = [min(lo, moment) if lo else moment,
                                                max(hi, moment) if hi else moment]
            else:
                arms[row['segment']] += 1
                issues['unknown_arms'] += row['segment'] not in ARMS
                for column in ('mens', 'womens', 'newbie', 'visit', 'conversion'):
                    issues[f'invalid_binary_{column}'] += row[column] not in {'0', '1'}
                for column in ('history', 'spend'):
                    value = number(row[column])
                    issues[f'invalid_or_nonfinite_{column}'] += value is None
                    issues[f'negative_{column}'] += value is not None and value < 0
                recency = number(row['recency'])
                issues['invalid_recency'] += (recency is None or recency != recency.to_integral_value()
                                               or not 1 <= recency <= 12)
                spend = number(row['spend'])
                issues['purchase_without_visit'] += row['conversion'] == '1' and row['visit'] == '0'
                issues['positive_spend_without_purchase'] += (spend is not None and spend > 0
                                                              and row['conversion'] == '0')
                issues['purchase_without_positive_spend'] += (row['conversion'] == '1'
                                                              and spend is not None and spend <= 0)
    result = {
        'dataset': dataset, 'path': str(path),
        'audited_at_utc': datetime.now(timezone.utc).isoformat(),
        'bytes': path.stat().st_size, 'sha256': file_hash(path),
        'columns': columns, 'row_count': count, 'malformed_rows': malformed,
        'missing_or_whitespace_only': {k: nulls[k] for k in columns},
        'field_exact_sha256_duplicate_rows': duplicates,
        'issues': dict(sorted(issues.items())),
        'raw_modified': False,
    }
    if dataset == 'rees46':
        result.update({
            'event_counts': dict(sorted(types.items())),
            'distinct_nonempty_users': len(users),
            'distinct_nonempty_user_session_pairs': len(session_bounds),
            'session_ids_linked_to_multiple_users': len(shared_sessions),
            'user_session_pairs_spanning_over_24h': sum(
                lo is not None and hi is not None and (hi - lo).total_seconds() > 86400
                for lo, hi in session_bounds.values()),
            'observed_start_utc': start.isoformat() if start else None,
            'observed_end_utc': end.isoformat() if end else None,
        })
    else:
        result['arm_sizes'] = dict(sorted(arms.items()))
        result['identity_limit'] = ('No customer ID exists. Identical attribute rows do not '
                                    'prove duplicate customers and must not be auto-dropped.')
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', choices=['rees46', 'hillstrom'], required=True)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.input.resolve() == args.output.resolve():
        parser.error('Output must not replace the raw input.')
    before = file_hash(args.input)
    result = audit(args.input, args.dataset)
    if file_hash(args.input) != before:
        raise RuntimeError('Input changed during intake.')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()


def read_sql(name):
    """Read one named SQL section from analysis.sql."""
    from pathlib import Path
    import re
    path = Path(__file__).resolve().parents[1] / 'analysis.sql'
    sections = re.split(r'^-- BEGIN FILE: (.+)$', path.read_text(), flags=re.MULTILINE)
    queries = {sections[i].strip(): sections[i + 1] for i in range(1, len(sections), 2)}
    if name not in queries:
        raise KeyError('Unknown SQL section: ' + name)
    return queries[name]
