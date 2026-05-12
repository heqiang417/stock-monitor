#!/usr/bin/env python3
"""补算布林带指标到 kline_daily 表（支持全量/今日增量）"""
import argparse
import os
import sys
import time
import numpy as np
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '../..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from db import DatabaseManager

DB_TARGET = os.getenv('POSTGRES_DSN') or os.getenv('PG_DSN') or os.getenv('DATABASE_URL') or os.getenv('DB_DSN') or os.getenv('STOCK_DB', os.path.join(PROJECT_ROOT, 'data', 'stock_data.db'))
IS_POSTGRES = DB_TARGET.startswith(('postgres://', 'postgresql://'))
TODAY = datetime.now().strftime('%Y-%m-%d')


def fetch_columns(db):
    if IS_POSTGRES:
        return [r['column_name'] for r in db.fetch_all("SELECT column_name FROM information_schema.columns WHERE table_name = 'kline_daily'")]
    return [r['name'] for r in db.fetch_all('PRAGMA table_info(kline_daily)')]


parser = argparse.ArgumentParser()
parser.add_argument('--today', action='store_true', help='只计算今天的布林带（增量，快）')
parser.add_argument('--days', type=int, default=0, help='计算最近N天（0=全量）')
args = parser.parse_args()

db = DatabaseManager(DB_TARGET)
cols = fetch_columns(db)
for col in ['boll_lower', 'boll_upper']:
    if col not in cols:
        db.execute(f'ALTER TABLE kline_daily ADD COLUMN {col} REAL')

t0 = time.time()

if args.today:
    symbols = [r['symbol'] for r in db.fetch_all(
        'SELECT DISTINCT symbol FROM kline_daily WHERE trade_date=?',
        (TODAY,)
    )]
    print(f'增量模式: 今天 {TODAY} 有 {len(symbols)} 只股票')
    lookback = 25
else:
    lookback = 20 + args.days
    symbols = [r['symbol'] for r in db.fetch_all('SELECT DISTINCT symbol FROM kline_daily')]
    print(f'全量模式: 共 {len(symbols)} 只股票，窗口 {lookback} 天')

updated = 0
total = len(symbols)

with db.get_connection() as conn:
    for idx, sym in enumerate(symbols):
        rows = db.fetch_all(
            'SELECT trade_date, close FROM kline_daily WHERE symbol=? ORDER BY trade_date DESC LIMIT ?',
            (sym, lookback)
        )
        rows.reverse()
        if len(rows) < 20:
            continue

        closes = [r['close'] for r in rows]
        dates = [r['trade_date'] for r in rows]
        updates = []
        for i in range(19, len(closes)):
            window = closes[i-19:i+1]
            ma20 = np.mean(window)
            std20 = np.std(window, ddof=1)
            upper = ma20 + 2 * std20
            lower = ma20 - 2 * std20
            updates.append((round(upper, 4), round(lower, 4), sym, dates[i]))

        if updates:
            cur = conn.cursor()
            sql = 'UPDATE kline_daily SET boll_upper=?, boll_lower=? WHERE symbol=? AND trade_date=?'
            sql = sql.replace('?', '%s') if IS_POSTGRES else sql
            cur.executemany(sql, updates)
            updated += 1

        if (idx + 1) % 500 == 0:
            elapsed = time.time() - t0
            print(f'  {idx+1}/{total} ({elapsed:.1f}s)')

elapsed = time.time() - t0
print(f'完成: {updated} 只股票更新, 耗时 {elapsed:.1f}s')
