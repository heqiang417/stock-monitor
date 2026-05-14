# PostgreSQL Migration Notes

## Files
- `scripts/migration/postgres_schema.sql`: PostgreSQL schema generated from current SQLite database
- `scripts/migration/postgres_schema_partitioned.sql`: PostgreSQL **monthly partitioned** schema for big date-based tables
- `scripts/migration/sqlite_to_postgres.py`: copy data from SQLite into PostgreSQL and verify row counts

## Prerequisites
1. PostgreSQL service is running
2. Target database and user exist
3. Python env has `psycopg[binary]` or `psycopg2-binary`

## Suggested DSN
```bash
export POSTGRES_DSN='postgresql://stock_user:change_me@127.0.0.1:5432/stock_monitor'
```

## Run migration
```bash
python3 scripts/migration/sqlite_to_postgres.py \
  --sqlite-path data/stock_data.db \
  --pg-dsn "$POSTGRES_DSN"
```

> Default schema is now `scripts/migration/postgres_schema_partitioned.sql`.
> To use the non-partitioned schema explicitly, add `--schema-sql scripts/migration/postgres_schema.sql`.

## Verify only
```bash
python3 scripts/migration/sqlite_to_postgres.py \
  --sqlite-path data/stock_data.db \
  --pg-dsn "$POSTGRES_DSN" \
  --verify-only
```

## Partial migration example
```bash
python3 scripts/migration/sqlite_to_postgres.py \
  --sqlite-path data/stock_data.db \
  --pg-dsn "$POSTGRES_DSN" \
  --tables strategies watchlist alerts kline_daily
```

## Partitioned migration notes
- `kline_daily`, `daily_valuation`, `capital_flow`, `northbound_holdings`, `financial_daily`, `margin_data`, `kline_daily_index`, `northbound_flow` use DATE columns in PostgreSQL.
- The migration script auto-creates monthly partitions before inserting each batch.
- SQLite empty strings in numeric columns are normalized to `NULL` during migration.
- `postgres_schema_partitioned.sql` is now idempotent (`CREATE TABLE IF NOT EXISTS` / `CREATE INDEX IF NOT EXISTS`) and no longer drops partitioned tables on repeated schema execution.
- If you really need a clean rebuild, explicitly clear the target tables/database first; do not rely on rerunning schema SQL during staged migrations.

## Current blocker in this session
- local PostgreSQL is listening on `127.0.0.1:5432`
- current Linux user `heqiang` cannot log in directly because role `heqiang` does not exist
- Python package `psycopg` / `psycopg2` is not installed yet

## Next step
Create DB/user + install driver, then run the migration script.
