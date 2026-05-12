#!/usr/bin/env python3
"""
计算布林带宽度（Bollinger Band Width）

用途：
- 判断波动收敛/扩张
- 波动率突破信号
- 震荡/趋势判断

BBW = (upper - lower) / mid

用法:
  python calc_bb_width.py --days 2    # 计算最近2天
  python calc_bb_width.py --today     # 只计算今天
  python calc_bb_width.py --days 0    # 全量计算
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
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'kline_daily'
        """)]
    return [r['name'] for r in db.fetch_all('PRAGMA table_info(kline_daily)')]


def main():
    parser = argparse.ArgumentParser(description='计算布林带宽度')
    parser.add_argument('--today', action='store_true', help='只计算今天')
    parser.add_argument('--days', type=int, default=1, help='计算最近N天（0=全量）')
    args = parser.parse_args()

    db = DatabaseManager(DB_TARGET)
    columns = fetch_columns(db)
    if 'bb_width' not in columns:
        print('添加 bb_width 字段...')
        db.execute('ALTER TABLE kline_daily ADD COLUMN bb_width REAL')

    if args.today:
        row = db.fetch_one('SELECT MAX(trade_date) AS trade_date FROM kline_daily')
        dates = [row['trade_date']] if row and row['trade_date'] else []
    elif args.days == 0:
        dates = [row['trade_date'] for row in db.fetch_all('SELECT DISTINCT trade_date FROM kline_daily ORDER BY trade_date DESC')]
        print(f'全量模式: 共 {len(dates)} 个交易日')
    else:
        dates = [row['trade_date'] for row in db.fetch_all('SELECT DISTINCT trade_date FROM kline_daily ORDER BY trade_date DESC LIMIT ?', (args.days,))]

    if not dates:
        print('无数据')
        return

    print(f"计算日期: {dates[0]} {'...' if len(dates) > 1 else ''}")
    for date in dates:
        affected = db.execute("""
            UPDATE kline_daily
            SET bb_width = CASE
                WHEN boll_mid > 0 AND boll_upper IS NOT NULL AND boll_lower IS NOT NULL
                THEN ROUND((boll_upper - boll_lower) / boll_mid, 4)
                ELSE NULL
            END
            WHERE trade_date = ?
        """, (date,))
        print(f'  {date}: 更新 {affected} 条')

    print('完成')


if __name__ == '__main__':
    main()
