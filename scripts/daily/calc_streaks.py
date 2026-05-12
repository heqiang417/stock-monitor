#!/usr/bin/env python3
"""
计算连续涨跌天数
- up_streak
- down_streak
"""
import argparse, os, sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '../..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from db import DatabaseManager

DB_TARGET = os.getenv('POSTGRES_DSN') or os.getenv('PG_DSN') or os.getenv('DATABASE_URL') or os.getenv('DB_DSN') or os.getenv('STOCK_DB', os.path.join(PROJECT_ROOT, 'data', 'stock_data.db'))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--days', type=int, default=20)
    args = parser.parse_args()
    _ = args  # 保留兼容参数

    db = DatabaseManager(DB_TARGET)
    cols = [r['column_name'] for r in db.fetch_all(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = 'kline_daily'
        """
    )] if DB_TARGET.startswith(('postgres://', 'postgresql://')) else [r['name'] for r in db.fetch_all("PRAGMA table_info(kline_daily)")]

    for col in ['up_streak', 'down_streak']:
        if col not in cols:
            db.execute(f"ALTER TABLE kline_daily ADD COLUMN {col} REAL")

    syms = [r['symbol'] for r in db.fetch_all("SELECT DISTINCT symbol FROM kline_daily")]
    updated = 0
    with db.get_connection() as conn:
        for i, sym in enumerate(syms):
            rows = db.fetch_all("SELECT trade_date, close FROM kline_daily WHERE symbol=? ORDER BY trade_date ASC", (sym,))
            up = down = 0
            prev = None
            for row in rows:
                date = row['trade_date']
                close = row['close']
                if prev is None or close is None:
                    up = down = 0
                else:
                    if close > prev:
                        up += 1
                        down = 0
                    elif close < prev:
                        down += 1
                        up = 0
                    else:
                        up = down = 0
                cur = conn.cursor()
                cur.execute(
                    "UPDATE kline_daily SET up_streak=?, down_streak=? WHERE symbol=? AND trade_date=?".replace('?', '%s') if DB_TARGET.startswith(('postgres://', 'postgresql://')) else "UPDATE kline_daily SET up_streak=?, down_streak=? WHERE symbol=? AND trade_date=?",
                    (up, down, sym, date)
                )
                prev = close
                updated += 1
            if (i + 1) % 500 == 0:
                print(f"进度: {i+1}/{len(syms)}")
    print(f"完成: {updated}")


if __name__ == '__main__':
    main()
