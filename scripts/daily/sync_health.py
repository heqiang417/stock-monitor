#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import os
from datetime import datetime

MIN_STOCKS_DEFAULT = 4000
VALID_LOOKBACK_DAYS_DEFAULT = 10
SYNC_STATUS_FILE = '/tmp/stock_sync_status.json'


def _is_postgres_target(db_target: str) -> bool:
    return str(db_target or '').strip().lower().startswith('postgres')


def _placeholder_sql(sql: str, db_target: str) -> str:
    if not _is_postgres_target(db_target):
        return sql
    return sql.replace('?', '%s')


def _fetchone(result):
    if result is None:
        return None
    if hasattr(result, 'fetchone'):
        return result.fetchone()
    return result


def assess_trade_date_health(exec_fn, fetchone_fn, today, target_date, min_stocks=MIN_STOCKS_DEFAULT, db_target=''):
    total = fetchone_fn(exec_fn(
        _placeholder_sql('SELECT COUNT(*) FROM kline_daily WHERE trade_date=?', db_target),
        (target_date,)
    ))[0]
    has_rsi = fetchone_fn(exec_fn(
        _placeholder_sql('SELECT COUNT(*) FROM kline_daily WHERE trade_date=? AND rsi14 IS NOT NULL', db_target),
        (target_date,)
    ))[0]
    has_ma20 = fetchone_fn(exec_fn(
        _placeholder_sql('SELECT COUNT(*) FROM kline_daily WHERE trade_date=? AND ma20 IS NOT NULL', db_target),
        (target_date,)
    ))[0]
    has_bb = fetchone_fn(exec_fn(
        _placeholder_sql('SELECT COUNT(*) FROM kline_daily WHERE trade_date=? AND boll_lower IS NOT NULL', db_target),
        (target_date,)
    ))[0]

    prev = fetchone_fn(exec_fn(
        _placeholder_sql('''
        SELECT trade_date, COUNT(*) AS cnt
        FROM kline_daily
        WHERE trade_date < ?
        GROUP BY trade_date
        HAVING COUNT(*) >= ?
        ORDER BY trade_date DESC
        LIMIT 1
        ''', db_target),
        (target_date, min_stocks)
    ))

    errors = []
    warnings = []
    if total < min_stocks:
        errors.append(f'K线不足: {target_date} {total}只（需≥{min_stocks}）')
    if total > 0 and has_rsi < total * 0.8:
        errors.append(f'RSI未覆盖: {target_date} {has_rsi}/{total}只')
    if total > 0 and has_ma20 < total * 0.8:
        errors.append(f'MA20未覆盖: {target_date} {has_ma20}/{total}只')
    if total > 0 and has_bb < total * 0.8:
        warnings.append(f'布林带未覆盖: {target_date} {has_bb}/{total}只')
    if prev and total < prev[1] * 0.9:
        warnings.append(f'数据量骤降: {target_date} {total}只 vs 上日{prev[0]} {prev[1]}只')

    if target_date == today:
        sh_cnt = fetchone_fn(exec_fn(
            _placeholder_sql("SELECT COUNT(*) FROM kline_daily WHERE trade_date=? AND symbol LIKE 'sh%%'", db_target),
            (target_date,)
        ))[0]
        sz_cnt = fetchone_fn(exec_fn(
            _placeholder_sql("SELECT COUNT(*) FROM kline_daily WHERE trade_date=? AND symbol LIKE 'sz%%'", db_target),
            (target_date,)
        ))[0]
        if sh_cnt < 1500:
            warnings.append(f'沪市覆盖异常偏低: {sh_cnt}只')
        if sz_cnt < 2500:
            warnings.append(f'深市覆盖异常偏低: {sz_cnt}只')
    else:
        sh_cnt = None
        sz_cnt = None

    valuation_count = fetchone_fn(exec_fn(
        _placeholder_sql('SELECT COUNT(*) FROM daily_valuation WHERE trade_date=?', db_target),
        (target_date,)
    ))[0]

    return {
        'target_date': target_date,
        'today': today,
        'total': total,
        'rsi': has_rsi,
        'ma20': has_ma20,
        'bb': has_bb,
        'valuation': valuation_count,
        'sh_count': sh_cnt,
        'sz_count': sz_cnt,
        'errors': errors,
        'warnings': warnings,
        'ok': len(errors) == 0,
    }


def find_best_trade_date(exec_fn, fetchone_fn, today, db_target='', min_stocks=MIN_STOCKS_DEFAULT, lookback_days=VALID_LOOKBACK_DAYS_DEFAULT):
    if _is_postgres_target(db_target):
        row = fetchone_fn(exec_fn(
            '''
            SELECT trade_date, COUNT(*) AS cnt
            FROM kline_daily
            WHERE trade_date >= (%s::date - (%s || ' day')::interval)
            GROUP BY trade_date
            HAVING COUNT(*) >= %s
            ORDER BY trade_date DESC
            LIMIT 1
            ''',
            (today, lookback_days, min_stocks)
        ))
    else:
        row = fetchone_fn(exec_fn(
            f'''
            SELECT trade_date, COUNT(*) AS cnt
            FROM kline_daily
            WHERE trade_date >= date('{today}', '-{lookback_days} day')
            GROUP BY trade_date
            HAVING cnt >= {min_stocks}
            ORDER BY trade_date DESC
            LIMIT 1
            ''',
            None
        ))
    return row[0] if row else None


def write_sync_status(payload, path=SYNC_STATUS_FILE):
    data = dict(payload or {})
    data['updated_at'] = datetime.now().isoformat(timespec='seconds')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def read_sync_status(path=SYNC_STATUS_FILE):
    if not os.path.exists(path):
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None
