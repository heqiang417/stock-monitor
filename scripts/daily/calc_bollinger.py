#!/usr/bin/env python3
"""补算布林带指标到 kline_daily 表（支持全量/今日增量）"""
import sqlite3, time, argparse
import numpy as np

DB = '/home/heqiang/.openclaw/workspace/stock-monitor-app-py/data/stock_data.db'
TODAY = __import__('datetime').datetime.now().strftime('%Y-%m-%d')

parser = argparse.ArgumentParser()
parser.add_argument('--today', action='store_true', help='只计算今天的布林带（增量，快）')
parser.add_argument('--days', type=int, default=0, help='计算最近N天（0=全量）')
args = parser.parse_args()

db = sqlite3.connect(DB)

# 确保列存在
cols = [c[1] for c in db.execute('PRAGMA table_info(kline_daily)').fetchall()]
for col in ['boll_lower', 'boll_upper']:
    if col not in cols:
        db.execute(f'ALTER TABLE kline_daily ADD COLUMN {col} REAL')
db.commit()

t0 = time.time()

if args.today:
    # 增量：只算今天有数据的股票
    symbols = [r[0] for r in db.execute(
        "SELECT DISTINCT symbol FROM kline_daily WHERE trade_date=?",
        (TODAY,)
    ).fetchall()]
    print(f'增量模式: 今天 {TODAY} 有 {len(symbols)} 只股票')
    # 取最近25天窗口足够
    lookback = 25
else:
    lookback = 20 + args.days
    symbols = [r[0] for r in db.execute('SELECT DISTINCT symbol FROM kline_daily').fetchall()]
    print(f'全量模式: 共 {len(symbols)} 只股票，窗口 {lookback} 天')

updated = 0
total = len(symbols)

for idx, sym in enumerate(symbols):
    # 取最近 lookback 天数据
    rows = db.execute(
        'SELECT trade_date, close FROM kline_daily WHERE symbol=? ORDER BY trade_date DESC LIMIT ?',
        (sym, lookback)
    ).fetchall()
    rows.reverse()  # 按时间正序

    if len(rows) < 20:
        continue

    closes = [r[1] for r in rows]
    dates = [r[0] for r in rows]

    updates = []
    for i in range(19, len(closes)):
        window = closes[i-19:i+1]
        ma20 = np.mean(window)
        std20 = np.std(window, ddof=1)
        upper = ma20 + 2 * std20
        lower = ma20 - 2 * std20
        updates.append((round(upper, 4), round(lower, 4), sym, dates[i]))

    if updates:
        db.executemany(
            'UPDATE kline_daily SET boll_upper=?, boll_lower=? WHERE symbol=? AND trade_date=?',
            updates
        )
        updated += 1

    if (idx + 1) % 500 == 0:
        db.commit()
        elapsed = time.time() - t0
        print(f'  {idx+1}/{total} ({elapsed:.1f}s)')

db.commit()
elapsed = time.time() - t0
print(f'完成: {updated} 只股票更新, 耗时 {elapsed:.1f}s')
