#!/usr/bin/env python3
"""
计算资金流入强度特征

特征：
- main_inflow_strength = main_net_inflow / amount
- main_inflow_3d = 连续3日主力净流入天数
"""
import argparse, os, sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '../..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from db import DatabaseManager

DB_TARGET = os.getenv('POSTGRES_DSN') or os.getenv('PG_DSN') or os.getenv('DATABASE_URL') or os.getenv('DB_DSN') or os.getenv('STOCK_DB', os.path.join(PROJECT_ROOT, 'data', 'stock_data.db'))
IS_POSTGRES = DB_TARGET.startswith(('postgres://', 'postgresql://'))


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
    for col in ['main_inflow_strength', 'main_inflow_3d_days']:
        if col not in cols:
            db.execute(f"ALTER TABLE kline_daily ADD COLUMN {col} REAL")

    dates = [r['trade_date'] for r in db.fetch_all("SELECT DISTINCT trade_date FROM kline_daily ORDER BY trade_date DESC LIMIT ?", (args.days,))]
    for date in dates:
        db.execute("""
            UPDATE kline_daily
            SET main_inflow_strength = (
                SELECT CASE WHEN kline_daily.amount > 0 THEN ROUND(cf.main_net_inflow / kline_daily.amount, 6) END
                FROM capital_flow cf
                WHERE cf.symbol = kline_daily.symbol AND cf.trade_date = kline_daily.trade_date
            )
            WHERE trade_date = ?
        """, (date,))

    syms = [r['symbol'] for r in db.fetch_all("SELECT DISTINCT symbol FROM capital_flow")]
    updated = 0
    with db.get_connection() as conn:
        for i, sym in enumerate(syms):
            rows = db.fetch_all("SELECT trade_date, main_net_inflow FROM capital_flow WHERE symbol=? ORDER BY trade_date ASC", (sym,))
            streak = 0
            for row in rows:
                date = row['trade_date']
                inflow = row['main_net_inflow']
                streak = streak + 1 if inflow is not None and inflow > 0 else 0
                cur = conn.cursor()
                cur.execute(
                    "UPDATE kline_daily SET main_inflow_3d_days=? WHERE symbol=? AND trade_date=?".replace('?', '%s') if IS_POSTGRES else "UPDATE kline_daily SET main_inflow_3d_days=? WHERE symbol=? AND trade_date=?",
                    (streak, sym, date)
                )
                updated += 1
            if (i + 1) % 500 == 0:
                print(f"进度: {i+1}/{len(syms)}")
    print(f"完成: {updated}")


if __name__ == '__main__':
    main()
