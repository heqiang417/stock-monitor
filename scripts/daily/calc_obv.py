#!/usr/bin/env python3
"""
计算 OBV（On-Balance Volume，能量潮）

用途：
- 量价配合判断
- 资金流向趋势
- 背离信号

OBV 计算：
- 今日收盘 > 昨日收盘：OBV = 昨日OBV + 今日成交量
- 今日收盘 < 昨日收盘：OBV = 昨日OBV - 今日成交量
- 今日收盘 = 昨日收盘：OBV = 昨日OBV

用法:
  python calc_obv.py --days 30   # 计算最近30天
  python calc_obv.py --days 0    # 全量计算
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
        return [r['column_name'] for r in db.fetch_all("""
            SELECT column_name FROM information_schema.columns WHERE table_name = 'kline_daily'
        """)]
    return [r['name'] for r in db.fetch_all('PRAGMA table_info(kline_daily)')]


def calc_obv_for_symbol(db, symbol):
    rows = db.fetch_all("""
        SELECT trade_date, close, volume
        FROM kline_daily
        WHERE symbol = ?
        ORDER BY trade_date ASC
    """, (symbol,))
    if len(rows) < 2:
        return []

    obv_data = []
    obv = 0
    prev_close = rows[0]['close']
    for i, row in enumerate(rows):
        date = row['trade_date']
        close = row['close']
        volume = row['volume']
        if i == 0:
            obv = volume if volume else 0
        else:
            if close > prev_close:
                obv += volume if volume else 0
            elif close < prev_close:
                obv -= volume if volume else 0
        obv_data.append((symbol, date, round(obv, 2)))
        prev_close = close
    return obv_data


def main():
    parser = argparse.ArgumentParser(description='计算 OBV')
    parser.add_argument('--days', type=int, default=30, help='计算最近N天（0=全量）')
    args = parser.parse_args()

    db = DatabaseManager(DB_TARGET)
    columns = fetch_columns(db)
    if 'obv' not in columns:
        print('添加 obv 字段...')
        db.execute('ALTER TABLE kline_daily ADD COLUMN obv REAL')

    if args.days == 0:
        symbols = [row['symbol'] for row in db.fetch_all('SELECT DISTINCT symbol FROM kline_daily ORDER BY symbol')]
        print(f'全量模式: 共 {len(symbols)} 只股票')
    else:
        symbols = [row['symbol'] for row in db.fetch_all("""
            SELECT DISTINCT symbol FROM kline_daily
            WHERE trade_date >= (
                SELECT DISTINCT trade_date FROM kline_daily
                ORDER BY trade_date DESC LIMIT 1 OFFSET ?
            )
            ORDER BY symbol
        """, (args.days - 1,))]
        print(f'计算最近 {args.days} 天，涉及 {len(symbols)} 只股票')

    if not symbols:
        print('无数据')
        return

    updated = 0
    with db.get_connection() as conn:
        for i, symbol in enumerate(symbols):
            obv_data = calc_obv_for_symbol(db, symbol)
            if obv_data:
                cur = conn.cursor()
                sql = 'UPDATE kline_daily SET obv = ? WHERE symbol = ? AND trade_date = ?'
                sql = sql.replace('?', '%s') if IS_POSTGRES else sql
                cur.executemany(sql, [(obv, sym, date) for sym, date, obv in obv_data])
                updated += len(obv_data)
            if (i + 1) % 500 == 0:
                print(f'  进度: {i+1}/{len(symbols)}')

    print(f'完成: 更新 {updated} 条记录')


if __name__ == '__main__':
    main()
