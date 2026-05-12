#!/usr/bin/env python3
"""
计算北向持仓特征

特征：
- north_hold_pct
- north_hold_change
- north_buy_streak
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--days', type=int, default=20)
    _ = parser.parse_args()
    db = DatabaseManager(DB_TARGET)

    cols = fetch_columns(db)
    for col in ['north_hold_pct', 'north_hold_change', 'north_buy_streak']:
        if col not in cols:
            db.execute(f'ALTER TABLE kline_daily ADD COLUMN {col} REAL')

    syms = [r['symbol'] for r in db.fetch_all('SELECT DISTINCT symbol FROM northbound_holdings')]
    updated = 0
    with db.get_connection() as conn:
        for i, sym in enumerate(syms):
            rows = db.fetch_all('SELECT trade_date, hold_shares, hold_pct FROM northbound_holdings WHERE symbol=? ORDER BY trade_date ASC', (sym,))
            prev = None
            streak = 0
            for row in rows:
                date = row['trade_date']
                shares = row['hold_shares']
                pct = row['hold_pct']
                change = None
                if prev is not None and shares is not None:
                    change = shares - prev
                    streak = streak + 1 if change > 0 else 0
                else:
                    streak = 0
                cur = conn.cursor()
                sql = 'UPDATE kline_daily SET north_hold_pct=?, north_hold_change=?, north_buy_streak=? WHERE symbol=? AND trade_date=?'
                sql = sql.replace('?', '%s') if IS_POSTGRES else sql
                cur.execute(sql, (pct, change, streak, sym, date))
                prev = shares
                updated += 1
            if (i + 1) % 500 == 0:
                print(f'进度: {i+1}/{len(syms)}')

    print(f'完成: {updated}')


if __name__ == '__main__':
    main()
