"""
Stock Monitor App Configuration
Environment-based configuration for production safety.
Supports dev/test/prod environments with validation.
"""
import os
import sys
import sqlite3
import threading
import logging
from queue import Queue
from typing import List, Optional


def _load_env_file():
    """Load environment variables from .env file using python-dotenv if available, else manual."""
    try:
        from dotenv import load_dotenv
        env_file = os.path.join(os.path.dirname(__file__), '.env')
        if os.path.exists(env_file):
            load_dotenv(env_file)
    except ImportError:
        # Fallback: manual .env loading
        env_file = os.path.join(os.path.dirname(__file__), '.env')
        if os.path.exists(env_file):
            try:
                with open(env_file, 'r') as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith('#') and '=' in line:
                            key, value = line.split('=', 1)
                            key = key.strip()
                            value = value.strip().strip('"').strip("'")
                            if key and key not in os.environ:
                                os.environ[key] = value
            except Exception as e:
                print(f"Warning: Failed to load .env file: {e}")


# Load .env on module import
_load_env_file()


class ConnectionPool:
    """Thread-safe SQLite connection pool with WAL mode optimization.
    
    Pre-creates a fixed number of connections and reuses them,
    reducing per-operation overhead from ~5ms to ~0.5ms.
    
    Usage:
        pool = ConnectionPool('data.db', max_connections=5)
        conn = pool.get_connection()
        try:
            conn.execute(...)
            conn.commit()
        finally:
            pool.return_connection(conn)
        pool.close_all()
    """
    
    def __init__(self, db_path: str, max_connections: int = 5):
        self.db_path = db_path
        self._pool = Queue(max_connections)
        self._lock = threading.Lock()
        for _ in range(max_connections):
            conn = sqlite3.connect(db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA mmap_size=268435456")   # 256MB 内存映射
            conn.execute("PRAGMA cache_size=-65536")     # 64MB 缓存
            self._pool.put(conn)
    
    def get_connection(self):
        """Get a connection from the pool (blocks if all in use)."""
        return self._pool.get()
    
    def return_connection(self, conn):
        """Return a connection to the pool."""
        self._pool.put(conn)
    
    def close_all(self):
        """Close all connections in the pool."""
        while not self._pool.empty():
            conn = self._pool.get()
            conn.close()


class BaseConfig:
    """Base configuration with common settings."""
    
    # Server
    PORT = int(os.getenv('PORT', 3001))
    DEBUG = False
    TESTING = False
    
    # Database
    DB_PATH = os.getenv('DB_PATH', os.path.join(os.path.dirname(__file__), 'data', 'stock_data.db'))
    
    # Stock
    STOCK_SYMBOL = os.getenv('STOCK_SYMBOL', 'sz002149')
    
    # APIs
    TENCENT_API = os.getenv('TENCENT_API', 'https://qt.gtimg.cn/q=')
    EASTMONEY_API = os.getenv('EASTMONEY_API', 'https://push2his.eastmoney.com/api/qt/stock/kline/get')
    
    # Cache
    QUOTE_CACHE_TTL = int(os.getenv('QUOTE_CACHE_TTL', 10))
    KLINE_CACHE_DAYS = int(os.getenv('KLINE_CACHE_DAYS', 7))
    
    # Background
    FETCH_INTERVAL = int(os.getenv('FETCH_INTERVAL', 30))
    CLEANUP_DAYS = int(os.getenv('CLEANUP_DAYS', 30))
    
    # Security
    CORS_ORIGINS = os.getenv('CORS_ORIGINS', 'http://localhost:3000').split(',')
    API_KEY = os.getenv('API_KEY', None)
    SECRET_KEY = os.getenv('SECRET_KEY', None)
    
    # Paths
    STRATEGIES_FILE = os.getenv('STRATEGIES_FILE', os.path.join(os.path.dirname(__file__), 'strategies.json'))
    LOG_FILE = os.getenv('LOG_FILE', os.path.join(os.path.dirname(__file__), 'app.log'))
    
    # Feishu (Lark)
    FEISHU_APP_ID = os.getenv('FEISHU_APP_ID', '')
    FEISHU_APP_SECRET = os.getenv('FEISHU_APP_SECRET', '')
    FEISHU_DEFAULT_RECEIVER = os.getenv('FEISHU_DEFAULT_RECEIVER', '')
    FEISHU_WEBHOOK_URL = os.getenv('FEISHU_WEBHOOK_URL', '')
    
    # Logging
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO').upper()
    LOG_FORMAT = os.getenv('LOG_FORMAT', '%(asctime)s [%(levelname)s] %(name)s: %(message)s')
    LOG_DATE_FORMAT = os.getenv('LOG_DATE_FORMAT', '%Y-%m-%d %H:%M:%S')
    LOG_MAX_BYTES = int(os.getenv('LOG_MAX_BYTES', 10 * 1024 * 1024))
    LOG_BACKUP_COUNT = int(os.getenv('LOG_BACKUP_COUNT', 7))
    
    # Thread pool
    MAX_WORKERS = int(os.getenv('MAX_WORKERS', 4))

    # 止损配置
    STOP_LOSS_PCT = float(os.getenv('STOP_LOSS_PCT', '8.0'))  # 止损百分比,默认8%

    # 仓位管理配置
    MAX_POSITION_PCT = float(os.getenv('MAX_POSITION_PCT', '20.0'))  # 单股最大仓位百分比,默认20%
    INITIAL_CAPITAL = float(os.getenv('INITIAL_CAPITAL', '100000'))  # 初始资金,默认10万
    
    @classmethod
    def validate(cls) -> List[str]:
        """Validate configuration. Returns list of warnings/errors."""
        issues = []
        
        if not cls.DB_PATH:
            issues.append("CRITICAL: DB_PATH is not set")
        
        if not cls.STOCK_SYMBOL:
            issues.append("WARNING: STOCK_SYMBOL is not set, using default 'sz002149'")
        
        if cls.CORS_ORIGINS == ['*']:
            issues.append("WARNING: CORS allows all origins - not recommended for production")
        
        if not cls.SECRET_KEY:
            issues.append("WARNING: SECRET_KEY not set, using random key (sessions won't persist)")
        
        if cls.LOG_LEVEL not in ('DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'):
            issues.append(f"WARNING: Invalid LOG_LEVEL '{cls.LOG_LEVEL}', defaulting to INFO")
        
        return issues
    
    @classmethod
    def setup_logging(cls):
        """Configure logging with rotation and levels."""
        from logging.handlers import RotatingFileHandler
        
        log_level = getattr(logging, cls.LOG_LEVEL, logging.INFO)
        
        file_formatter = logging.Formatter(
            fmt='%(asctime)s [%(levelname)s] %(name)s: %(funcName)s:%(lineno)d - %(message)s',
            datefmt=cls.LOG_DATE_FORMAT
        )
        console_formatter = logging.Formatter(
            fmt=cls.LOG_FORMAT,
            datefmt=cls.LOG_DATE_FORMAT
        )
        
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.DEBUG)
        root_logger.handlers.clear()
        
        # Console
        console_handler = logging.StreamHandler()
        console_handler.setLevel(log_level)
        console_handler.setFormatter(console_formatter)
        root_logger.addHandler(console_handler)
        
        # File with rotation
        try:
            file_handler = RotatingFileHandler(
                cls.LOG_FILE,
                maxBytes=cls.LOG_MAX_BYTES,
                backupCount=cls.LOG_BACKUP_COUNT
            )
            file_handler.setLevel(logging.DEBUG)
            file_handler.setFormatter(file_formatter)
            root_logger.addHandler(file_handler)
        except Exception as e:
            console_handler.setLevel(logging.WARNING)
            root_logger.warning(f"File logging disabled: {e}")
        
        # Suppress noisy loggers
        for name in ('urllib3', 'requests', 'werkzeug', 'engineio', 'socketio'):
            logging.getLogger(name).setLevel(logging.WARNING)
        
        logger = logging.getLogger(__name__)
        logger.info(f"Logging configured: console={cls.LOG_LEVEL}, file=DEBUG, log_file={cls.LOG_FILE}")


class DevelopmentConfig(BaseConfig):
    """Development configuration."""
    DEBUG = True
    LOG_LEVEL = 'DEBUG'
    CORS_ORIGINS = ['*']


class TestingConfig(BaseConfig):
    """Testing configuration."""
    TESTING = True
    DEBUG = True
    DB_PATH = ':memory:'  # In-memory database for tests
    LOG_LEVEL = 'WARNING'
    FETCH_INTERVAL = 999999  # Effectively disable background fetching
    CORS_ORIGINS = ['*']


class ProductionConfig(BaseConfig):
    """Production configuration."""
    DEBUG = False
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO').upper()
    
    @classmethod
    def validate(cls) -> List[str]:
        issues = super().validate()
        if cls.CORS_ORIGINS == ['*']:
            issues.append("CRITICAL: Production should not allow all CORS origins")
        if not cls.API_KEY:
            issues.append("CRITICAL: Production API_KEY must be set")
        return issues


# Config registry
_config_map = {
    'development': DevelopmentConfig,
    'dev': DevelopmentConfig,
    'testing': TestingConfig,
    'test': TestingConfig,
    'production': ProductionConfig,
    'prod': ProductionConfig,
}


def get_config(env: Optional[str] = None) -> type[BaseConfig]:
    """Get configuration class for the given environment.
    
    Args:
        env: Environment name. If None, reads from FLASK_ENV or APP_ENV env var.
             Defaults to 'development'.
    
    Returns:
        Configuration class (not instance).
    """
    if env is None:
        env = os.getenv('FLASK_ENV', os.getenv('APP_ENV', 'development'))
    
    config_class = _config_map.get(env.lower(), DevelopmentConfig)
    return config_class


# Default Config for backward compatibility
Config = get_config()
