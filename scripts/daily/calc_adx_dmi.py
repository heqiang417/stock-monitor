#!/usr/bin/env python3
"""
计算 ADX / DMI 特征

特征：
- plus_di14
- minus_di14
- adx14
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
        return [r['column_name'] for r in db.fetch_all("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'kline_daily'
        """)]
    return [r['name'] for r in db.fetch_all('PRAGMA table_info(kline_daily)')]


def sql_in_dates(dates):
    return '(' + ','.join("'" + str(d).replace("'", "''") + "'" for d in dates) + ')'


def calc_for_symbol(db, symbol, trade_date, period=14):
    rows = db.fetch_all("""
        SELECT trade_date, high, low, close
        FROM kline_daily
        WHERE symbol=? AND trade_date<=?
        ORDER BY trade_date DESC
        LIMIT ?
    """, (symbol, trade_date, period * 3))
    if len(rows) < period + 1:
        return None, None, None
    rows = list(reversed(rows))

    tr_list, pdm_list, mdm_list = [], [], []
    for i in range(1, len(rows)):
        high = rows[i]['high']
        low = rows[i]['low']
        prev_high = rows[i-1]['high']
        prev_low = rows[i-1]['low']
        prev_close = rows[i-1]['close']
        up_move = high - prev_high
        down_move = prev_low - low
        pdm = up_move if up_move > down_move and up_move > 0 else 0
        mdm = down_move if down_move > up_move and down_move > 0 else 0
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        tr_list.append(tr)
        pdm_list.append(pdm)
        mdm_list.append(mdm)

    if len(tr_list) < period:
        return None, None, None

    dx_list = []
    for i in range(period - 1, len(tr_list)):
        tr14 = sum(tr_list[i-period+1:i+1])
        pdm14 = sum(pdm_list[i-period+1:i+1])
        mdm14 = sum(mdm_list[i-period+1:i+1])
        if tr14 == 0:
            continue
        pdi = 100 * pdm14 / tr14
        mdi = 100 * mdm14 / tr14
        dx = 0 if (pdi + mdi) == 0 else 100 * abs(pdi - mdi) / (pdi + mdi)
        dx_list.append((pdi, mdi, dx))

    if len(dx_list) < period:
        pdi, mdi, dx = dx_list[-1] if dx_list else (None, None, None)
        return round(pdi, 4) if pdi is not None else None, round(mdi, 4) if mdi is not None else None, None

    pdi, mdi, _ = dx_list[-1]
    adx = sum(d[2] for d in dx_list[-period:]) / period
    return round(pdi, 4), round(mdi, 4), round(adx, 4)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--days', type=int, default=5)
    args = parser.parse_args()
    db = DatabaseManager(DB_TARGET)

    cols = fetch_columns(db)
    for col in ['plus_di14', 'minus_di14', 'adx14']:
        if col not in cols:
            db.execute(f'ALTER TABLE kline_daily ADD COLUMN {col} REAL')

    dates = [r['trade_date'] for r in db.fetch_all('SELECT DISTINCT trade_date FROM kline_daily ORDER BY trade_date DESC LIMIT ?', (args.days,))]
    syms = [r['symbol'] for r in db.fetch_all(f'SELECT DISTINCT symbol FROM kline_daily WHERE trade_date IN {sql_in_dates(dates)}')]
    updated = 0
    with db.get_connection() as conn:
        for i, sym in enumerate(syms):
            for date in dates:
                pdi, mdi, adx = calc_for_symbol(db, sym, date)
                if pdi is not None:
                    cur = conn.cursor()
                    cur.execute(
                        'UPDATE kline_daily SET plus_di14=?, minus_di14=?, adx14=? WHERE symbol=? AND trade_date=?'.replace('?', '%s') if IS_POSTGRES else 'UPDATE kline_daily SET plus_di14=?, minus_di14=?, adx14=? WHERE symbol=? AND trade_date=?',
                        (pdi, mdi, adx, sym, date)
                    )
                    updated += 1
            if (i + 1) % 500 == 0:
                print(f'进度: {i+1}/{len(syms)}')
    print(f'完成: {updated}')


if __name__ == '__main__':
    main()
