"""Stock Monitor App Configuration (PostgreSQL-only runtime)."""

import logging
import os
from typing import List, Optional
from urllib.parse import urlparse


def _load_env_file():
    env_file = os.path.join(os.path.dirname(__file__), '.env')
    if not os.path.exists(env_file):
        return
    try:
        try:
            from dotenv import load_dotenv
            load_dotenv(env_file)
        except ImportError:
            pass
        with open(env_file, 'r', encoding='utf-8') as f:
            for raw_line in f:
                line = raw_line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                key, value = line.split('=', 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and (key not in os.environ or not os.environ.get(key)):
                    os.environ[key] = value
    except Exception as exc:
        print(f'Warning: Failed to load .env file: {exc}')


_load_env_file()


def is_postgres_url(value: Optional[str]) -> bool:
    if not value:
        return False
    parsed = urlparse(value)
    return parsed.scheme in ('postgres', 'postgresql')


class ConnectionPool:
    def __init__(self, db_path: str, max_connections: int = 5):
        raise RuntimeError(
            'ConnectionPool has been removed because runtime now supports PostgreSQL only. '
            'Use db.DatabaseManager instead.'
        )


class BaseConfig:
    PORT = int(os.getenv('PORT', '3001'))
    DEBUG = False
    TESTING = False

    POSTGRES_DSN = os.getenv('POSTGRES_DSN') or os.getenv('PG_DSN') or os.getenv('DATABASE_URL') or os.getenv('DB_DSN') or ''
    DB_URL = POSTGRES_DSN
    DB_PATH = DB_URL
    DB_IS_POSTGRES = is_postgres_url(DB_URL)

    STOCK_SYMBOL = os.getenv('STOCK_SYMBOL', 'sz002149')
    TENCENT_API = os.getenv('TENCENT_API', 'https://qt.gtimg.cn/q=')
    EASTMONEY_API = os.getenv('EASTMONEY_API', 'https://push2his.eastmoney.com/api/qt/stock/kline/get')

    QUOTE_CACHE_TTL = int(os.getenv('QUOTE_CACHE_TTL', '10'))
    KLINE_CACHE_DAYS = int(os.getenv('KLINE_CACHE_DAYS', '7'))
    FETCH_INTERVAL = int(os.getenv('FETCH_INTERVAL', '30'))
    CLEANUP_DAYS = int(os.getenv('CLEANUP_DAYS', '30'))

    CORS_ORIGINS = [item.strip() for item in os.getenv('CORS_ORIGINS', 'http://localhost:3000').split(',') if item.strip()]
    API_KEY = os.getenv('API_KEY')
    SECRET_KEY = os.getenv('SECRET_KEY')

    STRATEGIES_FILE = os.getenv('STRATEGIES_FILE', os.path.join(os.path.dirname(__file__), 'strategies.json'))
    LOG_FILE = os.getenv('LOG_FILE', os.path.join(os.path.dirname(__file__), 'app.log'))

    FEISHU_APP_ID = os.getenv('FEISHU_APP_ID', '')
    FEISHU_APP_SECRET = os.getenv('FEISHU_APP_SECRET', '')
    FEISHU_DEFAULT_RECEIVER = os.getenv('FEISHU_DEFAULT_RECEIVER', '')
    FEISHU_WEBHOOK_URL = os.getenv('FEISHU_WEBHOOK_URL', '')

    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO').upper()
    LOG_FORMAT = os.getenv('LOG_FORMAT', '%(asctime)s [%(levelname)s] %(name)s: %(message)s')
    LOG_DATE_FORMAT = os.getenv('LOG_DATE_FORMAT', '%Y-%m-%d %H:%M:%S')
    LOG_MAX_BYTES = int(os.getenv('LOG_MAX_BYTES', str(10 * 1024 * 1024)))
    LOG_BACKUP_COUNT = int(os.getenv('LOG_BACKUP_COUNT', '7'))
    MAX_WORKERS = int(os.getenv('MAX_WORKERS', '4'))

    STOP_LOSS_PCT = float(os.getenv('STOP_LOSS_PCT', '8.0'))
    MAX_POSITION_PCT = float(os.getenv('MAX_POSITION_PCT', '20.0'))
    INITIAL_CAPITAL = float(os.getenv('INITIAL_CAPITAL', '100000'))

    @classmethod
    def validate(cls) -> List[str]:
        issues = []
        if not cls.DB_URL:
            issues.append('CRITICAL: POSTGRES_DSN/PG_DSN/DATABASE_URL is not set')
        elif not cls.DB_IS_POSTGRES:
            issues.append(f'CRITICAL: DB_URL must be a PostgreSQL DSN, got {cls.DB_URL!r}')
        if not cls.STOCK_SYMBOL:
            issues.append("WARNING: STOCK_SYMBOL is not set, using default 'sz002149'")
        if cls.CORS_ORIGINS == ['*']:
            issues.append('WARNING: CORS allows all origins - not recommended for production')
        if not cls.SECRET_KEY:
            issues.append("WARNING: SECRET_KEY not set, using random key (sessions won't persist)")
        if cls.LOG_LEVEL not in ('DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'):
            issues.append(f"WARNING: Invalid LOG_LEVEL '{cls.LOG_LEVEL}', defaulting to INFO")
        return issues

    @classmethod
    def setup_logging(cls):
        from logging.handlers import RotatingFileHandler
        log_level = getattr(logging, cls.LOG_LEVEL, logging.INFO)
        file_formatter = logging.Formatter(
            fmt='%(asctime)s [%(levelname)s] %(name)s: %(funcName)s:%(lineno)d - %(message)s',
            datefmt=cls.LOG_DATE_FORMAT,
        )
        console_formatter = logging.Formatter(fmt=cls.LOG_FORMAT, datefmt=cls.LOG_DATE_FORMAT)
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.DEBUG)
        root_logger.handlers.clear()
        console_handler = logging.StreamHandler()
        console_handler.setLevel(log_level)
        console_handler.setFormatter(console_formatter)
        root_logger.addHandler(console_handler)
        try:
            file_handler = RotatingFileHandler(
                cls.LOG_FILE,
                maxBytes=cls.LOG_MAX_BYTES,
                backupCount=cls.LOG_BACKUP_COUNT,
            )
            file_handler.setLevel(logging.DEBUG)
            file_handler.setFormatter(file_formatter)
            root_logger.addHandler(file_handler)
        except Exception as exc:
            root_logger.warning('Failed to initialize file logging: %s', exc)


class DevelopmentConfig(BaseConfig):
    DEBUG = True
    LOG_LEVEL = 'DEBUG'
    CORS_ORIGINS = ['*']


class TestingConfig(BaseConfig):
    TESTING = True
    DEBUG = True
    DB_URL = os.getenv('TEST_POSTGRES_DSN', BaseConfig.POSTGRES_DSN)
    DB_PATH = DB_URL
    DB_IS_POSTGRES = is_postgres_url(DB_URL)
    LOG_LEVEL = 'WARNING'
    FETCH_INTERVAL = 999999
    CORS_ORIGINS = ['*']


class ProductionConfig(BaseConfig):
    DEBUG = False

    @classmethod
    def validate(cls) -> List[str]:
        issues = super().validate()
        if cls.CORS_ORIGINS == ['*']:
            issues.append('CRITICAL: Production should not allow all CORS origins')
        return issues


Config = DevelopmentConfig if os.getenv('FLASK_ENV') == 'development' else ProductionConfig
