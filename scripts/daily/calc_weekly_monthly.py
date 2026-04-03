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

import sqlite3, argparse
from datetime import datetime, timedelta
from collections import defaultdict

DB_PATH = '/home/heqiang/.openclaw/workspace/stock-monitor-app-py/data/stock_data.db'

def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=60)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA synchronous=NORMAL')
    return conn

def get_week_start(date_str):
    """返回日期所在周的周一日期 'YYYY-MM-DD'"""
    d = datetime.strptime(date_str, '%Y-%m-%d')
    monday = d - timedelta(days=d.weekday())
    return monday.strftime('%Y-%m-%d')

def calc_weekly(conn, weeks_back=52):
    """从日K聚合生成周K"""
    max_date = conn.execute("SELECT MAX(trade_date) FROM kline_daily").fetchone()[0]
    if not max_date:
        print("日K数据为空，跳过周K计算")
        return 0

    # 查最近N周涉及的所有日期范围
    min_date = (datetime.strptime(max_date, '%Y-%m-%d') - timedelta(weeks=weeks_back)).strftime('%Y-%m-%d')

    # 查出所有symbol+周的开/收/高/低/量
    sql = """
    SELECT 
        symbol,
        trade_date,
        open,
        close,
        high,
        low,
        volume,
        amount
    FROM kline_daily
    WHERE trade_date >= ?
    ORDER BY symbol, trade_date
    """
    rows = conn.execute(sql, (min_date,)).fetchall()
    print(f"读取日K: {len(rows)} 条 (从 {min_date} 起)")

    # 按(symbol, 周一)聚合
    buckets = defaultdict(list)
    for r in rows:
        if len(r) != 8:
            print(f"  WARN: row len={len(r)} r={r}")
            continue
        symbol, trade_date, open_, close, high, low, volume, amount = r
        week_start = get_week_start(trade_date)
        buckets[(symbol, week_start)].append((trade_date, open_, close, high, low, volume, amount))

    # 生成周K
    # bucket每条: (trade_date, open_, close, high, low, volume, amount)
    # 索引:         0           1      2      3    4      5      6
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

    print(f"生成周K: {len(week_data)} 条")
    
    # 写入（REPLACE）
    conn.execute("DELETE FROM kline_weekly WHERE trade_week >= ?", (min_date,))
    conn.executemany("""
        INSERT INTO kline_weekly 
        (symbol, trade_week, open, close, high, low, volume, amount, chg, chg_pct, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
    """, week_data)
    conn.commit()
    print(f"周K写入完成: {len(week_data)} 条")
    return len(week_data)

def calc_monthly(conn, months_back=24):
    """从日K聚合生成月K"""
    max_date = conn.execute("SELECT MAX(trade_date) FROM kline_daily").fetchone()[0]
    if not max_date:
        print("日K数据为空，跳过月K计算")
        return 0

    min_date = (datetime.strptime(max_date, '%Y-%m-%d') - timedelta(days=months_back * 31)).strftime('%Y-%m-%d')

    sql = """
    SELECT symbol, trade_date, open, close, high, low, volume, amount
    FROM kline_daily
    WHERE trade_date >= ?
    ORDER BY symbol, trade_date
    """
    rows = conn.execute(sql, (min_date,)).fetchall()
    print(f"读取日K(月K用): {len(rows)} 条")

    # 按(symbol, 月份)聚合
    buckets = defaultdict(list)
    for r in rows:
        symbol, trade_date, open_, close, high, low, volume, amount = r
        month_start = trade_date[:7] + '-01'
        buckets[(symbol, month_start)].append((trade_date, open_, close, high, low, volume, amount))

    month_data = []
    # bucket每条: (trade_date, open_, close, high, low, volume, amount)
    # 索引:         0           1      2      3    4      5      6
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

    print(f"生成月K: {len(month_data)} 条")
    
    conn.execute("DELETE FROM kline_monthly WHERE trade_month >= ?", (min_date[:7],))
    conn.executemany("""
        INSERT INTO kline_monthly 
        (symbol, trade_month, open, close, high, low, volume, amount, chg, chg_pct, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
    """, month_data)
    conn.commit()
    print(f"月K写入完成: {len(month_data)} 条")
    return len(month_data)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--weeks', type=int, default=52)
    parser.add_argument('--months', type=int, default=24)
    parser.add_argument('--weekly-only', action='store_true')
    parser.add_argument('--monthly-only', action='store_true')
    args = parser.parse_args()

    conn = get_db()
    if not args.monthly_only:
        calc_weekly(conn, args.weeks)
    if not args.weekly_only:
        calc_monthly(conn, args.months)
    conn.close()
    print("完成")
