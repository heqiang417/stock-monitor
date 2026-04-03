"""
Pytest configuration and shared fixtures for stock-monitor-app tests.
Provides app factory fixtures, temp databases, and mock services.
"""
import pytest
import os
import sys
import tempfile
import sqlite3
from unittest.mock import MagicMock, patch

# Ensure app directory is in path
app_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if app_dir not in sys.path:
    sys.path.insert(0, app_dir)


@pytest.fixture(scope='session')
def temp_db_path():
    """Create a temporary database file for the test session."""
    fd, db_path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    yield db_path
    try:
        os.unlink(db_path)
    except OSError:
        pass


@pytest.fixture
def db_connection(temp_db_path):
    """Create a fresh database connection with schema for each test."""
    conn = sqlite3.connect(temp_db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    
    cursor = conn.cursor()
    
    # Create all tables
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS stock_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp INTEGER NOT NULL,
            price REAL NOT NULL,
            open REAL, high REAL, low REAL,
            volume INTEGER, amount REAL,
            chg REAL, chg_pct REAL,
            bid1_price REAL, bid1_vol INTEGER,
            ask1_price REAL, ask1_vol INTEGER,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS watchlist (
            symbol TEXT PRIMARY KEY,
            name TEXT,
            added_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS kline_daily (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            trade_date TEXT NOT NULL,
            open REAL NOT NULL, close REAL NOT NULL,
            high REAL NOT NULL, low REAL NOT NULL,
            volume REAL, amount REAL,
            chg REAL, chg_pct REAL,
            ma5 REAL, ma10 REAL, ma20 REAL, ma60 REAL,
            rsi14 REAL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(symbol, trade_date)
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp INTEGER NOT NULL,
            strategy_id TEXT, message TEXT,
            level TEXT DEFAULT 'info',
            stock TEXT, trigger_condition TEXT, price REAL,
            is_read INTEGER DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS alert_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp INTEGER NOT NULL,
            stock TEXT, price REAL, chg_pct REAL,
            strategy_id TEXT, strategy_name TEXT,
            trigger_condition TEXT, message TEXT,
            level TEXT DEFAULT 'info',
            feishu_sent INTEGER DEFAULT 0,
            is_read INTEGER DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    conn.commit()
    yield conn
    conn.close()


@pytest.fixture
def test_config(temp_db_path):
    """Create a test configuration class."""
    from config import TestingConfig
    # Override DB_PATH for this test
    config = type('TestConfig', (TestingConfig,), {
        'DB_PATH': temp_db_path,
        'STOCK_SYMBOL': 'sz002149',
        'FETCH_INTERVAL': 999999,
    })
    return config


@pytest.fixture
def test_app(test_config):
    """Create a test Flask app using the factory pattern."""
    from app import create_app
    app, socketio, bg_service, services = create_app(test_config)
    app.config['TESTING'] = True
    
    yield app, socketio, bg_service, services
    
    # Cleanup
    bg_service.stop()


@pytest.fixture
def client(test_app):
    """Create a test HTTP client."""
    app, _, _, _ = test_app
    return app.test_client()


@pytest.fixture
def stock_service(test_config):
    """Create a StockService with test database."""
    from services.stock_service import StockService
    svc = StockService(db_path=test_config.DB_PATH, config=test_config)
    svc.init_db()
    return svc


@pytest.fixture
def strategy_service(stock_service, tmp_path):
    """Create a StrategyService with temp strategies file."""
    from services.strategy_service import StrategyService
    strategies_file = str(tmp_path / 'test_strategies.json')
    return StrategyService(stock_service=stock_service, strategies_file=strategies_file)


@pytest.fixture
def mock_feishu_service():
    """Create a mock FeishuService."""
    svc = MagicMock()
    svc.app_id = 'test_app_id'
    svc.app_secret = 'test_secret'
    svc.default_chat_id = 'test_chat'
    svc.send_stock_alert.return_value = {'success': True}
    svc.send_alert.return_value = {'success': True}
    svc.send_message.return_value = {'success': True}
    return svc


@pytest.fixture
def sample_stock_data():
    """Sample stock data for testing."""
    return {
        'symbol': 'sz002149',
        'name': '西部材料',
        'price': 55.0,
        'prev_close': 54.0,
        'open': 54.5,
        'high': 56.0,
        'low': 53.5,
        'volume': 1500000,
        'amount': 82500000,
        'chg': 1.0,
        'chg_pct': 1.85,
        'volume_surge': 50.0,
        'bid1_price': 54.9,
        'bid1_vol': 1000,
        'ask1_price': 55.1,
        'ask1_vol': 800,
        'timestamp': 1700000000000,
    }


@pytest.fixture
def sample_strategy():
    """Sample complex strategy."""
    return {
        'id': 'test_strategy',
        'name': '测试策略',
        'enabled': True,
        'logic': 'AND',
        'conditions': [
            {'type': 'price', 'operator': '>=', 'value': 50},
            {'type': 'change_pct', 'operator': '>=', 'value': 0}
        ],
        'actions': [
            {'type': 'notify_feishu', 'message': '🚀 股票 {name} 涨到 {price}！'},
            {'type': 'alert_web', 'level': 'high'}
        ],
        'lastTriggered': None,
        'triggerCount': 0
    }


@pytest.fixture
def sample_kline_data():
    """Generate 30 days of sample K-line data."""
    data = []
    for i in range(30):
        data.append({
            'date': f'2024-01-{i+1:02d}',
            'open': 50.0 + i * 0.1,
            'close': 50.0 + i * 0.1 + 0.5,
            'high': 50.0 + i * 0.1 + 1.0,
            'low': 50.0 + i * 0.1 - 0.5,
            'volume': 1000000 + i * 10000,
        })
    return data
