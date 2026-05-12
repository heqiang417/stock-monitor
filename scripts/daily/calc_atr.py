#!/usr/bin/env python3
"""
计算 ATR（Average True Range，真实波动幅度）

用途：
- 动态止损/止盈参考
- 波动率判断
- 仓位管理

用法:
  python calc_atr.py --days 2    # 计算最近2天
  python calc_atr.py --today     # 只计算今天
  python calc_atr.py --days 0    # 全量计算
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
    return [r['name'] for r in db.fetch_all("PRAGMA table_info(kline_daily)")]


def sql_in_dates(dates):
    return '(' + ','.join("'" + str(d).replace("'", "''") + "'" for d in dates) + ')'


def calc_atr(db, symbol, trade_date, period=14):
    rows = db.fetch_all("""
        SELECT trade_date, high, low, close
        FROM kline_daily
        WHERE symbol = ? AND trade_date <= ?
        ORDER BY trade_date DESC
        LIMIT ?
    """, (symbol, trade_date, period + 1))

    if len(rows) < period + 1:
        return None

    tr_list = []
    for i in range(len(rows) - 1):
        curr = rows[i]
        prev = rows[i + 1]
        high = curr['high']
        low = curr['low']
        prev_close = prev['close']
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        tr_list.append(tr)

    if len(tr_list) < period:
        return None

    atr = sum(tr_list[:period]) / period
    return round(atr, 4)


def main():
    parser = argparse.ArgumentParser(description='计算 ATR')
    parser.add_argument('--today', action='store_true', help='只计算今天')
    parser.add_argument('--days', type=int, default=1, help='计算最近N天（0=全量）')
    args = parser.parse_args()

    db = DatabaseManager(DB_TARGET)
    columns = fetch_columns(db)
    if 'atr14' not in columns:
        print('添加 atr14 字段...')
        db.execute('ALTER TABLE kline_daily ADD COLUMN atr14 REAL')

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
    symbols = [row['symbol'] for row in db.fetch_all(
        f"SELECT DISTINCT symbol FROM kline_daily WHERE trade_date IN {sql_in_dates(dates)}"
    )]
    print(f'股票数: {len(symbols)}')

    updated = 0
    with db.get_connection() as conn:
        for i, symbol in enumerate(symbols):
            for date in dates:
                atr = calc_atr(db, symbol, date)
                if atr is not None:
                    cur = conn.cursor()
                    cur.execute(
                        'UPDATE kline_daily SET atr14 = ? WHERE symbol = ? AND trade_date = ?'.replace('?', '%s') if IS_POSTGRES else 'UPDATE kline_daily SET atr14 = ? WHERE symbol = ? AND trade_date = ?',
                        (atr, symbol, date)
                    )
                    updated += 1
            if (i + 1) % 500 == 0:
                print(f'  进度: {i+1}/{len(symbols)}')

    print(f'完成: 更新 {updated} 条记录')


if __name__ == '__main__':
    main()
