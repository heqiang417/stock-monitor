#!/usr/bin/env python3
import argparse
import datetime as dt
import os
import sqlite3
import sys
from pathlib import Path

BATCH_SIZE = 5000
DATE_COLUMNS = {
    'kline_daily': {'trade_date'},
    'daily_valuation': {'trade_date'},
    'capital_flow': {'trade_date'},
    'northbound_holdings': {'trade_date'},
    'margin_data': {'date'},
    'financial_daily': {'trade_date'},
    'kline_daily_index': {'trade_date'},
    'northbound_flow': {'date'},
}
PARTITIONED_TABLES = set(DATE_COLUMNS)


def qident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def get_pg_conn(dsn: str):
    try:
        import psycopg
        return psycopg.connect(dsn)
    except ImportError:
        import psycopg2
        return psycopg2.connect(dsn)


def list_tables_sqlite(conn):
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")
    return [r[0] for r in cur.fetchall()]


def get_columns_sqlite(conn, table):
    cur = conn.execute(f'PRAGMA table_info({qident(table)})')
    return [r[1] for r in cur.fetchall()]


def get_sqlite_column_types(conn, table):
    cur = conn.execute(f'PRAGMA table_info({qident(table)})')
    return {r[1]: (r[2] or '').upper() for r in cur.fetchall()}


def iter_rows_sqlite(conn, table, columns, batch_size=BATCH_SIZE):
    col_sql = ', '.join(qident(c) for c in columns)
    cur = conn.execute(f'SELECT {col_sql} FROM {qident(table)}')
    while True:
        rows = cur.fetchmany(batch_size)
        if not rows:
            break
        yield rows


def ensure_schema(pg_conn, schema_sql_path: Path):
    sql = schema_sql_path.read_text(encoding='utf-8')
    with pg_conn.cursor() as cur:
        cur.execute(sql)
    pg_conn.commit()


def is_numeric_sqlite_type(type_name: str) -> bool:
    t = (type_name or '').upper()
    numeric_tokens = ('INT', 'REAL', 'FLOA', 'DOUB', 'NUM', 'DEC', 'BOOL')
    return any(tok in t for tok in numeric_tokens)


def parse_date(value):
    if value in (None, ''):
        return None
    if isinstance(value, dt.date):
        return value
    s = str(value).strip()
    if not s:
        return None
    return dt.date.fromisoformat(s[:10])


def month_bounds(d: dt.date):
    start = d.replace(day=1)
    if start.month == 12:
        end = dt.date(start.year + 1, 1, 1)
    else:
        end = dt.date(start.year, start.month + 1, 1)
    return start, end


def ensure_month_partition(pg_conn, table: str, date_value: dt.date):
    start, end = month_bounds(date_value)
    part_name = f'{table}_{start.strftime("%Y%m")}'
    sql = (
        f'CREATE TABLE IF NOT EXISTS public.{qident(part_name)} '
        f'PARTITION OF public.{qident(table)} '
        f"FOR VALUES FROM ('{start.isoformat()}') TO ('{end.isoformat()}')"
    )
    with pg_conn.cursor() as cur:
        cur.execute(sql)
    pg_conn.commit()


def ensure_partitions_for_batch(pg_conn, table, batch, columns):
    if table not in PARTITIONED_TABLES:
        return
    date_cols = DATE_COLUMNS[table]
    idxs = [i for i, c in enumerate(columns) if c in date_cols]
    seen = set()
    for row in batch:
        for idx in idxs:
            d = parse_date(row[idx])
            if d is not None:
                seen.add(d.replace(day=1))
    for month_start in sorted(seen):
        ensure_month_partition(pg_conn, table, month_start)


def normalize_value(table: str, column: str, value, sqlite_type: str):
    if isinstance(value, str) and value == '' and is_numeric_sqlite_type(sqlite_type):
        return None
    if column in DATE_COLUMNS.get(table, set()):
        return parse_date(value)
    if column == 'created_at' and isinstance(value, str) and value == '':
        return None
    return value


def normalize_batch(table, batch, columns, col_types):
    normalized = []
    for row in batch:
        normalized.append(tuple(normalize_value(table, col, v, col_types.get(col, '')) for col, v in zip(columns, row)))
    return normalized


def copy_table(sqlite_conn, pg_conn, table, truncate=False):
    columns = get_columns_sqlite(sqlite_conn, table)
    if not columns:
        print(f'[skip] {table}: no columns or table not found in sqlite', flush=True)
        return 0
    col_types = get_sqlite_column_types(sqlite_conn, table)
    col_sql = ', '.join(qident(c) for c in columns)
    placeholders = ', '.join(['%s'] * len(columns))
    insert_sql = f'INSERT INTO public.{qident(table)} ({col_sql}) VALUES ({placeholders})'

    copied = 0
    skip_rows = 0
    with pg_conn.cursor() as cur:
        if truncate:
            cur.execute(f'TRUNCATE TABLE public.{qident(table)} CASCADE')
        else:
            cur.execute(f'SELECT COUNT(*) FROM public.{qident(table)}')
            skip_rows = cur.fetchone()[0]
            if skip_rows:
                print(f'[resume] {table}: starting from existing {skip_rows}', flush=True)
    pg_conn.commit()

    remaining_to_skip = skip_rows
    with pg_conn.cursor() as cur:
        for batch in iter_rows_sqlite(sqlite_conn, table, columns):
            if remaining_to_skip:
                if remaining_to_skip >= len(batch):
                    remaining_to_skip -= len(batch)
                    continue
                batch = batch[remaining_to_skip:]
                remaining_to_skip = 0
            ensure_partitions_for_batch(pg_conn, table, batch, columns)
            batch = normalize_batch(table, batch, columns, col_types)
            cur.executemany(insert_sql, batch)
            copied += len(batch)
            print(f'[{table}] copied {skip_rows + copied}', flush=True)
    pg_conn.commit()
    return skip_rows + copied


def verify_counts(sqlite_conn, pg_conn, tables):
    ok = True
    with pg_conn.cursor() as cur:
        for table in tables:
            sqlite_count = sqlite_conn.execute(f'SELECT COUNT(*) FROM {qident(table)}').fetchone()[0]
            cur.execute(f'SELECT COUNT(*) FROM public.{qident(table)}')
            pg_count = cur.fetchone()[0]
            mark = 'OK' if sqlite_count == pg_count else 'MISMATCH'
            print(f'[verify] {table}: sqlite={sqlite_count} pg={pg_count} {mark}')
            if sqlite_count != pg_count:
                ok = False
    return ok


def main():
    ap = argparse.ArgumentParser(description='Migrate SQLite data to PostgreSQL')
    ap.add_argument('--sqlite-path', default='data/stock_data.db')
    ap.add_argument('--pg-dsn', default=os.getenv('POSTGRES_DSN', ''))
    ap.add_argument('--schema-sql', default='scripts/migration/postgres_schema_partitioned.sql')
    ap.add_argument('--tables', nargs='*', help='Only migrate selected tables')
    ap.add_argument('--skip-schema', action='store_true')
    ap.add_argument('--truncate', action='store_true')
    ap.add_argument('--verify-only', action='store_true')
    args = ap.parse_args()

    if not args.pg_dsn:
        print('ERROR: missing --pg-dsn or POSTGRES_DSN', file=sys.stderr)
        sys.exit(2)

    sqlite_conn = sqlite3.connect(args.sqlite_path)
    pg_conn = get_pg_conn(args.pg_dsn)

    try:
        tables = args.tables or list_tables_sqlite(sqlite_conn)
        if not args.verify_only and not args.skip_schema:
            ensure_schema(pg_conn, Path(args.schema_sql))
        if not args.verify_only:
            for table in tables:
                total = copy_table(sqlite_conn, pg_conn, table, truncate=args.truncate)
                print(f'[done] {table}: {total}')
        ok = verify_counts(sqlite_conn, pg_conn, tables)
        if not ok:
            sys.exit(1)
    finally:
        sqlite_conn.close()
        pg_conn.close()


if __name__ == '__main__':
    main()
