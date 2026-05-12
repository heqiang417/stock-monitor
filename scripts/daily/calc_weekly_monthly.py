#!/usr/bin/env python3
"""
从日K线聚合生成周K线和月K线
用法:
  python3 calc_weekly_monthly.py              # 全量重算（最近52周+24月）
  python3 calc_weekly_monthly.py --weeks 4    # 只算最近4周
  python3 calc_weekly_monthly.py --months 3   # 只算最近3个月
  python3 calc_weekly_monthly.py --weekly-only
  python3 calc_weekly_monthly.py --monthly-only
"""

import os, sys, argparse
from datetime import datetime, timedelta
from collections import defaultdict

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from db import DatabaseManager, _is_postgres_target

DEFAULT_DB_PATH = '/home/heqiang/.openclaw/workspace/stock-monitor-app-py/data/stock_data.db'
DB_TARGET = os.environ.get('POSTGRES_DSN') or os.environ.get('PG_DSN') or os.environ.get('DATABASE_URL') or os.environ.get('DB_DSN') or os.environ.get('STOCK_DB') or DEFAULT_DB_PATH
DB_IS_POSTGRES = _is_postgres_target(DB_TARGET)

db = DatabaseManager(DB_TARGET)


def get_week_start(date_str):
    d = datetime.strptime(date_str, '%Y-%m-%d')
    monday = d - timedelta(days=d.weekday())
    return monday.strftime('%Y-%m-%d')


def execmany_raw(conn, sql, params_list):
    cur = conn.cursor()
    cur.executemany(sql.replace('?', '%s') if DB_IS_POSTGRES else sql, params_list)
    return cur


def calc_weekly(weeks_back=52):
    row = db.fetch_one('SELECT MAX(trade_date) AS max_date FROM kline_daily')
    max_date = row['max_date'] if row else None
    if not max_date:
        print('日K数据为空，跳过周K计算')
        return 0

    max_date = str(max_date)
    min_date = (datetime.strptime(max_date[:10], '%Y-%m-%d') - timedelta(weeks=weeks_back)).strftime('%Y-%m-%d')
    rows = db.fetch_all("""
        SELECT symbol, trade_date, open, close, high, low, volume, amount
        FROM kline_daily
        WHERE trade_date >= ?
        ORDER BY symbol, trade_date
    """, (min_date,))
    print(f'读取日K: {len(rows)} 条 (从 {min_date} 起)')

    buckets = defaultdict(list)
    for r in rows:
        symbol = r['symbol']
        trade_date = r['trade_date']
        open_ = r['open']
        close = r['close']
        high = r['high']
        low = r['low']
        volume = r['volume']
        amount = r['amount']
        week_start = get_week_start(str(trade_date)[:10])
        buckets[(symbol, week_start)].append((str(trade_date)[:10], open_, close, high, low, volume, amount))

    week_data = []
    for (symbol, week_start), days in buckets.items():
        days.sort(key=lambda x: x[0])
        first_open = days[0][1]
        last_close = days[-1][2]
        high = max(d[3] for d in days)
        low = min(d[4] for d in days)
        volume = sum(d[5] for d in days)
        amount = sum(d[6] for d in days)
        chg = last_close - first_open
        chg_pct = (chg / first_open * 100) if first_open else 0
        week_data.append((symbol, week_start, first_open, last_close, high, low, volume, amount, chg, chg_pct))

    print(f'生成周K: {len(week_data)} 条')
    with db.get_connection() as conn:
        cur = conn.cursor()
        cur.execute(('DELETE FROM kline_weekly WHERE trade_week >= ?').replace('?', '%s') if DB_IS_POSTGRES else 'DELETE FROM kline_weekly WHERE trade_week >= ?', (min_date,))
        execmany_raw(conn, """
            INSERT INTO kline_weekly
            (symbol, trade_week, open, close, high, low, volume, amount, chg, chg_pct, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """, week_data)
    print(f'周K写入完成: {len(week_data)} 条')
    return len(week_data)


def calc_monthly(months_back=24):
    row = db.fetch_one('SELECT MAX(trade_date) AS max_date FROM kline_daily')
    max_date = row['max_date'] if row else None
    if not max_date:
        print('日K数据为空，跳过月K计算')
        return 0

    max_date = str(max_date)
    min_date = (datetime.strptime(max_date[:10], '%Y-%m-%d') - timedelta(days=months_back * 31)).strftime('%Y-%m-%d')
    rows = db.fetch_all("""
        SELECT symbol, trade_date, open, close, high, low, volume, amount
        FROM kline_daily
        WHERE trade_date >= ?
        ORDER BY symbol, trade_date
    """, (min_date,))
    print(f'读取日K(月K用): {len(rows)} 条')

    buckets = defaultdict(list)
    for r in rows:
        symbol = r['symbol']
        trade_date = str(r['trade_date'])[:10]
        month_start = trade_date[:7] + '-01'
        buckets[(symbol, month_start)].append((trade_date, r['open'], r['close'], r['high'], r['low'], r['volume'], r['amount']))

    month_data = []
    for (symbol, month_start), days in buckets.items():
        days.sort(key=lambda x: x[0])
        first_open = days[0][1]
        last_close = days[-1][2]
        high = max(d[3] for d in days)
        low = min(d[4] for d in days)
        volume = sum(d[5] for d in days)
        amount = sum(d[6] for d in days)
        chg = last_close - first_open
        chg_pct = (chg / first_open * 100) if first_open else 0
        month_data.append((symbol, month_start[:7], first_open, last_close, high, low, volume, amount, chg, chg_pct))

    print(f'生成月K: {len(month_data)} 条')
    with db.get_connection() as conn:
        cur = conn.cursor()
        cur.execute(('DELETE FROM kline_monthly WHERE trade_month >= ?').replace('?', '%s') if DB_IS_POSTGRES else 'DELETE FROM kline_monthly WHERE trade_month >= ?', (min_date[:7],))
        execmany_raw(conn, """
            INSERT INTO kline_monthly
            (symbol, trade_month, open, close, high, low, volume, amount, chg, chg_pct, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """, month_data)
    print(f'月K写入完成: {len(month_data)} 条')
    return len(month_data)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--weeks', type=int, default=52)
    parser.add_argument('--months', type=int, default=24)
    parser.add_argument('--weekly-only', action='store_true')
    parser.add_argument('--monthly-only', action='store_true')
    args = parser.parse_args()

    if not args.monthly_only:
        calc_weekly(args.weeks)
    if not args.weekly_only:
        calc_monthly(args.months)
    print('完成')
