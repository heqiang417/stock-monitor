#!/usr/bin/env python3
"""
计算相对强弱（个股 vs 指数）

用途：
- 判断个股是否跑赢大盘
- 相对动量
- 板块轮动

特征：
- rel_strength_5d: 5日相对强度（个股5日涨幅 - 沪深300 5日涨幅）
- rel_strength_10d: 10日相对强度
- rel_strength_20d: 20日相对强度

用法:
  python calc_relative_strength.py --days 5
  python calc_relative_strength.py --days 0  # 全量
"""
import argparse
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '../..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from db import DatabaseManager

DB_TARGET = os.getenv('POSTGRES_DSN') or os.getenv('PG_DSN') or os.getenv('DATABASE_URL') or os.getenv('DB_DSN') or os.getenv('STOCK_DB', os.path.join(PROJECT_ROOT, 'data', 'stock_data.db'))
IS_POSTGRES = DB_TARGET.startswith(('postgres://', 'postgresql://'))


def fetch_columns(db):
    if IS_POSTGRES:
        return [r['column_name'] for r in db.fetch_all("SELECT column_name FROM information_schema.columns WHERE table_name = 'kline_daily'")]
    return [r['name'] for r in db.fetch_all('PRAGMA table_info(kline_daily)')]


def sql_in_dates(dates):
    return '(' + ','.join("'" + str(d).replace("'", "''") + "'" for d in dates) + ')'


def get_index_return(db, index_code, trade_date, period):
    rows = db.fetch_all("""
        SELECT close
        FROM kline_daily_index
        WHERE symbol = ? AND trade_date <= ?
        ORDER BY trade_date DESC
        LIMIT ?
    """, (index_code, trade_date, period + 1))
    if len(rows) < period + 1:
        return None
    current_close = rows[0]['close']
    past_close = rows[period]['close']
    if past_close == 0:
        return None
    return (current_close - past_close) / past_close * 100


def get_stock_return(db, symbol, trade_date, period):
    rows = db.fetch_all("""
        SELECT close
        FROM kline_daily
        WHERE symbol = ? AND trade_date <= ?
        ORDER BY trade_date DESC
        LIMIT ?
    """, (symbol, trade_date, period + 1))
    if len(rows) < period + 1:
        return None
    current_close = rows[0]['close']
    past_close = rows[period]['close']
    if past_close == 0:
        return None
    return (current_close - past_close) / past_close * 100


def main():
    parser = argparse.ArgumentParser(description='计算相对强弱')
    parser.add_argument('--days', type=int, default=5, help='计算最近N天（0=全量）')
    parser.add_argument('--index', type=str, default='000300', help='基准指数代码（默认沪深300）')
    args = parser.parse_args()

    db = DatabaseManager(DB_TARGET)
    columns = fetch_columns(db)
    for col in ['rel_strength_5d', 'rel_strength_10d', 'rel_strength_20d']:
        if col not in columns:
            print(f'添加 {col} 字段...')
            db.execute(f'ALTER TABLE kline_daily ADD COLUMN {col} REAL')

    if args.days == 0:
        dates = [row['trade_date'] for row in db.fetch_all('SELECT DISTINCT trade_date FROM kline_daily ORDER BY trade_date DESC')]
        print(f'全量模式: 共 {len(dates)} 个交易日')
    else:
        dates = [row['trade_date'] for row in db.fetch_all('SELECT DISTINCT trade_date FROM kline_daily ORDER BY trade_date DESC LIMIT ?', (args.days,))]

    if not dates:
        print('无数据')
        return

    print(f"计算日期: {dates[0]} {'...' if len(dates) > 1 else ''}")
    print(f'基准指数: {args.index}')
    symbols = [row['symbol'] for row in db.fetch_all(f"SELECT DISTINCT symbol FROM kline_daily WHERE trade_date IN {sql_in_dates(dates)}")]
    print(f'股票数: {len(symbols)}')

    updated = 0
    with db.get_connection() as conn:
        for i, symbol in enumerate(symbols):
            for date in dates:
                for period, col in [(5, 'rel_strength_5d'), (10, 'rel_strength_10d'), (20, 'rel_strength_20d')]:
                    stock_ret = get_stock_return(db, symbol, date, period)
                    index_ret = get_index_return(db, args.index, date, period)
                    if stock_ret is not None and index_ret is not None:
                        rel_strength = round(stock_ret - index_ret, 4)
                        cur = conn.cursor()
                        sql = f'UPDATE kline_daily SET {col} = ? WHERE symbol = ? AND trade_date = ?'
                        sql = sql.replace('?', '%s') if IS_POSTGRES else sql
                        cur.execute(sql, (rel_strength, symbol, date))
                        updated += 1
            if (i + 1) % 500 == 0:
                print(f'  进度: {i+1}/{len(symbols)}')

    print(f'完成: 更新 {updated} 条记录')


if __name__ == '__main__':
    main()
