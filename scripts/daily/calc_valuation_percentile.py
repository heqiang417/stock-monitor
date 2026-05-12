#!/usr/bin/env python3
"""
计算估值分位数特征
- pe_pct_252
- pb_pct_252
"""
import argparse, os, sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '../..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from db import DatabaseManager

DB_TARGET = os.getenv('POSTGRES_DSN') or os.getenv('PG_DSN') or os.getenv('DATABASE_URL') or os.getenv('DB_DSN') or os.getenv('STOCK_DB', os.path.join(PROJECT_ROOT, 'data', 'stock_data.db'))
IS_POSTGRES = DB_TARGET.startswith(('postgres://', 'postgresql://'))


def percentile_rank(vals, current):
    vals = [v for v in vals if v is not None]
    if not vals or current is None:
        return None
    less_equal = sum(1 for v in vals if v <= current)
    return round(less_equal / len(vals), 4)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--days', type=int, default=5)
    args = parser.parse_args()
    db = DatabaseManager(DB_TARGET)

    cols = [r['column_name'] for r in db.fetch_all(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = 'kline_daily'
        """
    )] if IS_POSTGRES else [r['name'] for r in db.fetch_all("PRAGMA table_info(kline_daily)")]
    for col in ['pe_pct_252', 'pb_pct_252']:
        if col not in cols:
            db.execute(f"ALTER TABLE kline_daily ADD COLUMN {col} REAL")

    dates = {r['trade_date'] for r in db.fetch_all("SELECT DISTINCT trade_date FROM kline_daily ORDER BY trade_date DESC LIMIT ?", (args.days,))}
    syms = [r['symbol'] for r in db.fetch_all("SELECT DISTINCT symbol FROM daily_valuation")]
    updated = 0
    with db.get_connection() as conn:
        for i, sym in enumerate(syms):
            rows = db.fetch_all("SELECT trade_date, pe_ttm, pb FROM daily_valuation WHERE symbol=? ORDER BY trade_date ASC", (sym,))
            for idx, row in enumerate(rows):
                date, pe, pb = row['trade_date'], row['pe_ttm'], row['pb']
                if date not in dates:
                    continue
                start = max(0, idx - 251)
                hist = rows[start:idx+1]
                pe_rank = percentile_rank([r['pe_ttm'] for r in hist], pe)
                pb_rank = percentile_rank([r['pb'] for r in hist], pb)
                cur = conn.cursor()
                cur.execute(
                    "UPDATE kline_daily SET pe_pct_252=?, pb_pct_252=? WHERE symbol=? AND trade_date=?".replace('?', '%s') if IS_POSTGRES else "UPDATE kline_daily SET pe_pct_252=?, pb_pct_252=? WHERE symbol=? AND trade_date=?",
                    (pe_rank, pb_rank, sym, date)
                )
                updated += 1
            if (i + 1) % 500 == 0:
                print(f"进度: {i+1}/{len(syms)}")
    print(f"完成: {updated}")


if __name__ == '__main__':
    main()
