"""Database helpers for PostgreSQL runtime and optional SQLite test utilities."""

import logging
import sqlite3
from contextlib import contextmanager
from typing import Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


def _is_postgres_target(target: str) -> bool:
    return isinstance(target, str) and target.startswith(('postgresql://', 'postgres://'))


def _postgres_connect_kwargs(target: str) -> dict:
    parsed = urlparse(target)
    return {
        'host': parsed.hostname or '127.0.0.1',
        'port': parsed.port or 5432,
        'user': parsed.username,
        'password': parsed.password,
        'dbname': parsed.path.lstrip('/'),
        'connect_timeout': 10,
    }


def _sqlite_placeholders_to_pyformat(sql: str) -> str:
    pieces = sql.split('?')
    if len(pieces) == 1:
        return sql
    return '%s'.join(pieces)


class DatabaseManager:
    def __init__(self, db_target: str):
        if not db_target:
            raise RuntimeError('DatabaseManager requires POSTGRES_DSN/PG_DSN/DATABASE_URL/DB_DSN')
        self.db_target = db_target
        self._is_postgres = _is_postgres_target(db_target)

    def _connect(self):
        if self._is_postgres:
            import psycopg2
            from psycopg2.extras import RealDictCursor
            conn = psycopg2.connect(cursor_factory=RealDictCursor, **_postgres_connect_kwargs(self.db_target))
            conn.autocommit = False
            return conn
        conn = sqlite3.connect(self.db_target)
        conn.row_factory = sqlite3.Row
        return conn

    @contextmanager
    def get_connection(self):
        conn = self._connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @contextmanager
    def get_cursor(self, row_factory: bool = True):
        with self.get_connection() as conn:
            if self._is_postgres:
                if row_factory:
                    from psycopg2.extras import RealDictCursor
                    cursor = conn.cursor(cursor_factory=RealDictCursor)
                else:
                    cursor = conn.cursor()
            else:
                if row_factory:
                    conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
            yield cursor

    def execute(self, sql: str, params: tuple = ()) -> int:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(_sqlite_placeholders_to_pyformat(sql) if self._is_postgres else sql, params)
            return cursor.rowcount

    def fetch_one(self, sql: str, params: tuple = ()) -> Optional[dict]:
        with self.get_cursor() as cursor:
            cursor.execute(_sqlite_placeholders_to_pyformat(sql) if self._is_postgres else sql, params)
            row = cursor.fetchone()
            return dict(row) if row else None

    def fetch_all(self, sql: str, params: tuple = ()) -> list:
        with self.get_cursor() as cursor:
            cursor.execute(_sqlite_placeholders_to_pyformat(sql) if self._is_postgres else sql, params)
            return [dict(row) for row in cursor.fetchall()]

    def execute_many(self, sql: str, params_list: list) -> int:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.executemany(_sqlite_placeholders_to_pyformat(sql) if self._is_postgres else sql, params_list)
            return cursor.rowcount

    def close_pool(self):
        return None


def connect_db(db_path: str):
    if _is_postgres_target(db_path):
        import psycopg2
        from psycopg2.extras import RealDictCursor
        conn = psycopg2.connect(cursor_factory=RealDictCursor, **_postgres_connect_kwargs(db_path))
        conn.autocommit = False
        return conn
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn
