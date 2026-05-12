#!/usr/bin/env python3
"""
计算成交量突增特征

用途：
- 捕捉异动
- 资金关注度
- 突破信号

特征：
- volume_avg20: 20日平均成交量
- volume_spike: 当日成交量 / 20日平均（突增倍数）

用法:
  python calc_turnover_spike.py --days 5
  python calc_turnover_spike.py --days 0  # 全量
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


def sql_in_dates(dates):
    return '(' + ','.join("'" + str(d).replace("'", "''") + "'" for d in dates) + ')'


def calc_turnover_spike(db, symbol, trade_date, period=20):
    rows = db.fetch_all("""
        SELECT trade_date, volume
        FROM kline_daily
        WHERE symbol = ? AND trade_date <= ?
        ORDER BY trade_date DESC
        LIMIT ?
    """, (symbol, trade_date, period + 1))

    if len(rows) < period:
        return None, None

    current_volume = rows[0]['volume']
    if current_volume is None or current_volume == 0:
        return None, None

    past_volumes = [r['volume'] for r in rows[1:period+1] if r['volume'] is not None and r['volume'] > 0]
    if len(past_volumes) < period * 0.7:
        return None, None

    avg_volume = sum(past_volumes) / len(past_volumes)
    if avg_volume == 0:
        return None, None

    spike = current_volume / avg_volume
    return round(avg_volume, 2), round(spike, 4)


def main():
    parser = argparse.ArgumentParser(description='计算换手率突增')
    parser.add_argument('--days', type=int, default=5, help='计算最近N天（0=全量）')
    args = parser.parse_args()

    db = DatabaseManager(DB_TARGET)
    columns = fetch_columns(db)
    if 'volume_avg20' not in columns:
        print('添加 volume_avg20 字段...')
        db.execute('ALTER TABLE kline_daily ADD COLUMN volume_avg20 REAL')
    if 'volume_spike' not in columns:
        print('添加 volume_spike 字段...')
        db.execute('ALTER TABLE kline_daily ADD COLUMN volume_spike REAL')

    if args.days == 0:
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
                avg, spike = calc_turnover_spike(db, symbol, date)
                if avg is not None:
                    cur = conn.cursor()
                    cur.execute(
                        'UPDATE kline_daily SET volume_avg20 = ?, volume_spike = ? WHERE symbol = ? AND trade_date = ?'.replace('?', '%s') if IS_POSTGRES else 'UPDATE kline_daily SET volume_avg20 = ?, volume_spike = ? WHERE symbol = ? AND trade_date = ?',
                        (avg, spike, symbol, date)
                    )
                    updated += 1
            if (i + 1) % 500 == 0:
                print(f'  进度: {i+1}/{len(symbols)}')

    print(f'完成: 更新 {updated} 条记录')


if __name__ == '__main__':
    main()
