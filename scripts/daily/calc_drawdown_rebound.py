#!/usr/bin/env python3
"""
计算回撤/反弹幅度特征
- drawdown_20d
- rebound_from_low_20d
"""
import argparse, os, sys

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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--days', type=int, default=5)
    args = parser.parse_args()
    db = DatabaseManager(DB_TARGET)

    cols = fetch_columns(db)
    for col in ['drawdown_20d', 'rebound_from_low_20d']:
        if col not in cols:
            db.execute(f'ALTER TABLE kline_daily ADD COLUMN {col} REAL')

    dates = [r['trade_date'] for r in db.fetch_all('SELECT DISTINCT trade_date FROM kline_daily ORDER BY trade_date DESC LIMIT ?', (args.days,))]
    syms = [r['symbol'] for r in db.fetch_all(f'SELECT DISTINCT symbol FROM kline_daily WHERE trade_date IN {sql_in_dates(dates)}')]
    updated = 0
    with db.get_connection() as conn:
        for i, sym in enumerate(syms):
            for date in dates:
                rows = db.fetch_all('SELECT high, low, close FROM kline_daily WHERE symbol=? AND trade_date<=? ORDER BY trade_date DESC LIMIT 20', (sym, date))
                if len(rows) < 5:
                    continue
                highs = [r['high'] for r in rows if r['high'] is not None]
                lows = [r['low'] for r in rows if r['low'] is not None]
                close = rows[0]['close']
                if not highs or not lows or close is None:
                    continue
                max_high = max(highs)
                min_low = min(lows)
                dd = round((close - max_high) / max_high * 100, 4) if max_high else None
                rb = round((close - min_low) / min_low * 100, 4) if min_low else None
                cur = conn.cursor()
                sql = 'UPDATE kline_daily SET drawdown_20d=?, rebound_from_low_20d=? WHERE symbol=? AND trade_date=?'
                sql = sql.replace('?', '%s') if IS_POSTGRES else sql
                cur.execute(sql, (dd, rb, sym, date))
                updated += 1
            if (i + 1) % 500 == 0:
                print(f'进度: {i+1}/{len(syms)}')

    print(f'完成: {updated}')


if __name__ == '__main__':
    main()
