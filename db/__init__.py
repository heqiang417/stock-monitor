"""
Database connection manager for Stock Monitor App.
Provides a single, consistent way to access SQLite with proper
WAL mode, busy timeout, and connection lifecycle management.
Uses ConnectionPool for efficient connection reuse.
"""

import sqlite3
import threading
import logging
from contextlib import contextmanager
from typing import Optional

logger = logging.getLogger(__name__)


class DatabaseManager:
    """Thread-safe SQLite connection manager with connection pooling.
    
    Usage:
        db = DatabaseManager('stock_data.db')
        
        # Context manager (auto-return to pool)
        with db.get_connection() as conn:
            conn.execute(...)
        
        # Raw connection (caller must release)
        conn = db.get_connection()
        try:
            conn.execute(...)
        finally:
            db.release_connection(conn)
    """
    
    def __init__(self, db_path: str, pool_size: int = 5):
        self.db_path = db_path
        self._pool_size = pool_size
        self._pool = None
        self._lock = threading.Lock()
    
    def _get_pool(self):
        """Lazy-initialize the connection pool."""
        if self._pool is None:
            with self._lock:
                if self._pool is None:
                    from config import ConnectionPool
                    self._pool = ConnectionPool(self.db_path, self._pool_size)
                    logger.info(f"Connection pool created: {self.db_path}, size={self._pool_size}")
        return self._pool
    
    @contextmanager
    def get_connection(self):
        """Get a pooled connection as a context manager (auto-returns to pool on exit)."""
        pool = self._get_pool()
        conn = pool.get_connection()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            pool.return_connection(conn)
    
    def release_connection(self, conn):
        """Return a connection to the pool."""
        pool = self._get_pool()
        pool.return_connection(conn)
    
    @contextmanager
    def get_cursor(self, row_factory: bool = True):
        """Get a cursor as a context manager.
        
        Args:
            row_factory: If True, set row_factory to sqlite3.Row for dict-like access.
        """
        pool = self._get_pool()
        conn = pool.get_connection()
        original_factory = conn.row_factory
        if row_factory:
            conn.row_factory = sqlite3.Row
        try:
            cursor = conn.cursor()
            yield cursor
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.row_factory = original_factory
            pool.return_connection(conn)
    
    def execute(self, sql: str, params: tuple = ()) -> int:
        """Execute a single statement and return rowcount."""
        with self.get_connection() as conn:
            cursor = conn.execute(sql, params)
            return cursor.rowcount
    
    def fetch_one(self, sql: str, params: tuple = ()) -> Optional[dict]:
        """Fetch a single row as a dict."""
        with self.get_cursor() as cursor:
            cursor.execute(sql, params)
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def fetch_all(self, sql: str, params: tuple = ()) -> list:
        """Fetch all rows as list of dicts."""
        with self.get_cursor() as cursor:
            cursor.execute(sql, params)
            return [dict(row) for row in cursor.fetchall()]
    
    def execute_many(self, sql: str, params_list: list) -> int:
        """Execute a statement for multiple parameter sets."""
        with self.get_connection() as conn:
            cursor = conn.executemany(sql, params_list)
            return cursor.rowcount
    
    def close_pool(self):
        """Close all connections in the pool."""
        if self._pool:
            self._pool.close_all()
            self._pool = None
            logger.info("Connection pool closed")


# Backward-compatible function for existing code
def connect_db(db_path: str) -> sqlite3.Connection:
    """Create a SQLite connection with performance optimizations.
    
    DEPRECATED: Use DatabaseManager instead.
    Kept for backward compatibility with existing code.
    """
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA mmap_size=268435456")   # 256MB 内存映射
    conn.execute("PRAGMA cache_size=-65536")     # 64MB 缓存
    return conn
