"""
Database connection manager for Stock Monitor App.
Provides a single, consistent way to access SQLite and PostgreSQL
with proper connection lifecycle management.
"""

import sqlite3
import threading
import logging
from contextlib import contextmanager
from typing import Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


def _is_postgres_target(target: str) -> bool:
    return isinstance(target, str) and target.startswith(('postgresql://', 'postgres://'))


def _sqlite_placeholders_to_pyformat(sql: str) -> str:
    """Convert SQLite qmark placeholders to psycopg2 pyformat placeholders.

    Escapes literal % outside quoted strings, and only replaces standalone ?
    tokens outside quoted strings so SQL text remains intact.
    """
    result = []
    in_single = False
    in_double = False
    i = 0
    while i < len(sql):
        ch = sql[i]
        if ch == "'" and not in_double:
            result.append(ch)
            if in_single and i + 1 < len(sql) and sql[i + 1] == "'":
                result.append(sql[i + 1])
                i += 2
                continue
            in_single = not in_single
        elif ch == '"' and not in_single:
            result.append(ch)
            if in_double and i + 1 < len(sql) and sql[i + 1] == '"':
                result.append(sql[i + 1])
                i += 2
                continue
            in_double = not in_double
        elif ch == '%' and not in_single and not in_double:
            result.append('%%')
        elif ch == '?' and not in_single and not in_double:
            result.append('%s')
        else:
            result.append(ch)
        i += 1
    return ''.join(result)


def _postgres_connect_kwargs(target: str) -> dict:
    parsed = urlparse(target)
    if parsed.scheme not in ('postgresql', 'postgres'):
        raise ValueError(f'Unsupported PostgreSQL DSN: {target}')
    return {
        'host': parsed.hostname or '127.0.0.1',
        'port': parsed.port or 5432,
        'user': parsed.username,
        'password': parsed.password,
        'dbname': parsed.path.lstrip('/'),
        'connect_timeout': 5,
    }


class DatabaseManager:
    """Thread-safe database connection manager with connection pooling.

    Supports both SQLite paths and PostgreSQL DSNs.
    """

    def __init__(self, db_path: str, pool_size: int = 5):
        self.db_path = db_path
        self._pool_size = pool_size
        self._pool = None
        self._lock = threading.Lock()
        self._is_postgres = _is_postgres_target(db_path)

    def _get_pool(self):
        """Lazy-initialize the connection pool."""
        if self._pool is None:
            with self._lock:
                if self._pool is None:
                    if self._is_postgres:
                        from psycopg2.pool import ThreadedConnectionPool
                        self._pool = ThreadedConnectionPool(self._pool_size, self._pool_size, **_postgres_connect_kwargs(self.db_path))
                    else:
                        from config import ConnectionPool
                        self._pool = ConnectionPool(self.db_path, self._pool_size)
                    logger.info(f"Connection pool created: {self.db_path}, size={self._pool_size}")
        return self._pool

    def _get_connection(self):
        pool = self._get_pool()
        if self._is_postgres:
            conn = pool.getconn()
            conn.autocommit = False
            return conn
        return pool.get_connection()

    def _return_connection(self, conn, close: bool = False):
        pool = self._get_pool()
        if self._is_postgres:
            pool.putconn(conn, close=close)
        else:
            pool.return_connection(conn)

    @contextmanager
    def get_connection(self):
        """Get a pooled connection as a context manager (auto-returns to pool on exit)."""
        conn = self._get_connection()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            self._return_connection(conn)

    def release_connection(self, conn):
        """Return a connection to the pool."""
        self._return_connection(conn)

    @contextmanager
    def get_cursor(self, row_factory: bool = True):
        """Get a cursor as a context manager."""
        conn = self._get_connection()
        original_factory = getattr(conn, 'row_factory', None)
        try:
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
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            if not self._is_postgres and row_factory:
                conn.row_factory = original_factory
            self._return_connection(conn)

    def execute(self, sql: str, params: tuple = ()) -> int:
        """Execute a single statement and return rowcount."""
        with self.get_connection() as conn:
            if self._is_postgres:
                cursor = conn.cursor()
                cursor.execute(_sqlite_placeholders_to_pyformat(sql), params)
            else:
                cursor = conn.execute(sql, params)
            return cursor.rowcount

    def fetch_one(self, sql: str, params: tuple = ()) -> Optional[dict]:
        """Fetch a single row as a dict."""
        with self.get_cursor() as cursor:
            cursor.execute(sql if not self._is_postgres else _sqlite_placeholders_to_pyformat(sql), params)
            row = cursor.fetchone()
            return dict(row) if row else None

    def fetch_all(self, sql: str, params: tuple = ()) -> list:
        """Fetch all rows as list of dicts."""
        with self.get_cursor() as cursor:
            cursor.execute(sql if not self._is_postgres else _sqlite_placeholders_to_pyformat(sql), params)
            return [dict(row) for row in cursor.fetchall()]

    def execute_many(self, sql: str, params_list: list) -> int:
        """Execute a statement for multiple parameter sets."""
        with self.get_connection() as conn:
            if self._is_postgres:
                cursor = conn.cursor()
                cursor.executemany(_sqlite_placeholders_to_pyformat(sql), params_list)
            else:
                cursor = conn.executemany(sql, params_list)
            return cursor.rowcount

    def close_pool(self):
        """Close all connections in the pool."""
        if self._pool:
            if self._is_postgres:
                self._pool.closeall()
            else:
                self._pool.close_all()
            self._pool = None
            logger.info("Connection pool closed")


# Backward-compatible function for existing code
def connect_db(db_path: str):
    """Create a raw database connection.

    DEPRECATED: Use DatabaseManager instead.
    Kept for backward compatibility with existing code.
    """
    if _is_postgres_target(db_path):
        import psycopg2
        from psycopg2.extras import RealDictCursor
        conn = psycopg2.connect(cursor_factory=RealDictCursor, **_postgres_connect_kwargs(db_path))
        conn.autocommit = False
        return conn

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA mmap_size=268435456")   # 256MB 内存映射
    conn.execute("PRAGMA cache_size=-65536")     # 64MB 缓存
    return conn
