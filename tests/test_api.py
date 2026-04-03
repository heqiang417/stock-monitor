"""
Unit Tests for API Endpoints
Tests Flask routes using the app factory pattern.
"""
import pytest
import json
import os
import sqlite3
from unittest.mock import patch, MagicMock


# ============ Fixtures ============

@pytest.fixture
def app(tmp_path):
    """Create a test Flask app using the app factory (isolated DB per test)."""
    from config import TestingConfig

    db_path = str(tmp_path / 'test_stock.db')

    # Override DB_PATH for test
    TestingConfig.DB_PATH = db_path
    TestingConfig.STOCK_SYMBOL = 'sz002149'
    TestingConfig.FETCH_INTERVAL = 999999

    # Initialize test database BEFORE app grabs it
    _init_test_db(db_path)

    from app import create_app
    flask_app, socketio, bg_service, services = create_app(TestingConfig)
    flask_app.config['TESTING'] = True

    yield flask_app

    # Cleanup
    try:
        bg_service.stop()
    except Exception:
        pass


@pytest.fixture
def client(app):
    """Create a test client."""
    return app.test_client()


def _init_test_db(db_path):
    """Initialize test database with schema and sample data."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS stock_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp INTEGER NOT NULL,
            price REAL NOT NULL, open REAL, high REAL, low REAL,
            volume INTEGER, amount REAL, chg REAL, chg_pct REAL,
            bid1_price REAL, bid1_vol INTEGER, ask1_price REAL, ask1_vol INTEGER,
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
            symbol TEXT NOT NULL, trade_date TEXT NOT NULL,
            open REAL NOT NULL, close REAL NOT NULL,
            high REAL NOT NULL, low REAL NOT NULL,
            volume REAL, amount REAL, chg REAL, chg_pct REAL,
            ma5 REAL, ma10 REAL, ma20 REAL, ma60 REAL, rsi14 REAL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(symbol, trade_date)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS strategies (
            id TEXT PRIMARY KEY, name TEXT, enabled INTEGER,
            logic TEXT, conditions TEXT, actions TEXT,
            last_triggered DATETIME, trigger_count INTEGER DEFAULT 0
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp INTEGER NOT NULL, strategy_id TEXT, message TEXT,
            level TEXT DEFAULT 'info', stock TEXT, trigger_condition TEXT, price REAL,
            is_read INTEGER DEFAULT 0, created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Insert test data
    for i in range(30):
        cursor.execute('''
            INSERT INTO kline_daily (symbol, trade_date, open, close, high, low, volume, amount, chg, chg_pct, ma5, ma10, ma20, rsi14)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', ('sz002149', f'2024-01-{i+1:02d}',
              50.0 + i * 0.1, 50.0 + i * 0.1 + 0.5,
              50.0 + i * 0.1 + 1.0, 50.0 + i * 0.1 - 0.5,
              1000000 + i * 10000, (50.0 + i * 0.1) * (1000000 + i * 10000),
              0.5, 1.0, 50.0 + i * 0.1, 50.0 + i * 0.1, 50.0 + i * 0.1, 50 + (i % 30)))

    cursor.execute("INSERT INTO watchlist (symbol, name) VALUES ('sz002149', '西部材料')")
    cursor.execute("INSERT INTO watchlist (symbol, name) VALUES ('sh601398', '工商银行')")

    cursor.execute("""
        INSERT INTO strategies (id, name, enabled, logic, conditions, actions)
        VALUES ('ma_cross', 'MA交叉策略', 1, 'AND', '[]', '[]')
    """)

    conn.commit()
    conn.close()


# ============ Basic Route Tests ============

class TestBasicRoutes:
    """Test basic page routes."""

    def test_index_page(self, client):
        """Test the main index page loads."""
        response = client.get('/')
        assert response.status_code == 200


# ============ Health Check ============

class TestHealthCheck:
    """Test health check endpoint."""

    def test_health_check_v1(self, client):
        """Test health check at /api/v1/health."""
        response = client.get('/api/v1/health')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['success'] is True
        assert data['status'] == 'healthy'

    def test_health_check_legacy(self, client):
        """Test legacy health check at /api/health."""
        response = client.get('/api/health')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['success'] is True


# ============ Stock API Tests ============

class TestStockAPI:
    """Test stock-related API endpoints."""

    def test_get_stock_history(self, client):
        """Test GET /api/v1/history returns history."""
        response = client.get('/api/v1/history?limit=10')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['success'] is True

    def test_get_stock_history_default_limit(self, client):
        """Test history with default limit."""
        response = client.get('/api/v1/history')
        assert response.status_code == 200

    def test_get_watchlist(self, client):
        """Test GET /api/v1/watchlist."""
        response = client.get('/api/v1/watchlist')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['success'] is True
        assert isinstance(data.get('watchlist', []), list)

    def test_add_to_watchlist(self, client):
        """Test POST /api/v1/watchlist adds a stock."""
        response = client.post('/api/v1/watchlist',
            json={'symbol': 'sh600036', 'name': '招商银行'})
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['success'] is True

    def test_add_watchlist_missing_symbol(self, client):
        """Test adding to watchlist without symbol fails."""
        response = client.post('/api/v1/watchlist', json={})
        assert response.status_code in [400, 422]

    def test_remove_from_watchlist(self, client):
        """Test DELETE /api/v1/watchlist removes a stock."""
        # First add it
        client.post('/api/v1/watchlist',
            json={'symbol': 'sh600036', 'name': '招商银行'})
        # Then remove it
        response = client.delete('/api/v1/watchlist?symbol=sh600036')
        assert response.status_code == 200


# ============ K-line API Tests ============

class TestKlineAPI:
    """Test K-line chart API endpoints."""

    def test_get_kline_default(self, client):
        """Test GET /api/v1/kline/<symbol> returns K-line data."""
        response = client.get('/api/v1/kline/sz002149')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['success'] is True

    def test_get_kline_with_period(self, client):
        """Test K-line with period parameter."""
        response = client.get('/api/v1/kline/sz002149?period=daily&limit=5')
        assert response.status_code == 200

    def test_get_kline_invalid_symbol(self, client):
        """Test K-line with invalid symbol."""
        response = client.get('/api/v1/kline/NONEXISTENT')
        # Should return 200 with empty data, or 404
        assert response.status_code in [200, 404]


# ============ Strategy API Tests ============

class TestStrategyAPI:
    """Test strategy API endpoints."""

    def test_get_strategies(self, client):
        """Test GET /api/v1/strategies."""
        response = client.get('/api/v1/strategies')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['success'] is True

    def test_get_complex_strategies(self, client):
        """Test GET /api/v1/strategies/complex."""
        response = client.get('/api/v1/strategies/complex')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['success'] is True
        assert isinstance(data.get('strategies', []), list)

    def test_create_strategy(self, client):
        """Test POST /api/v1/strategies creates a new strategy."""
        strategy = {
            'name': '测试策略',
            'conditions': [
                {'type': 'price', 'operator': '>', 'value': 50}
            ],
            'actions': [
                {'type': 'notify', 'message': 'Price above 50'}
            ]
        }
        response = client.post('/api/v1/strategies', json=strategy)
        assert response.status_code in [200, 201]

    def test_delete_strategy(self, client):
        """Test DELETE /api/v1/strategies/<id>."""
        response = client.delete('/api/v1/strategies/ma_cross')
        assert response.status_code in [200, 404]


# ============ Backtest API Tests ============

class TestBacktestAPI:
    """Test backtest API endpoints."""

    def test_backtest_strategies_list(self, client):
        """Test GET /api/backtest/strategies."""
        response = client.get('/api/backtest/strategies')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert 'strategies' in data
        assert isinstance(data['strategies'], list)

    def test_run_backtest(self, client):
        """Test POST /api/backtest/run."""
        response = client.post('/api/backtest/run', json={
            'symbol': 'sz002149',
            'strategy': 'ma_cross',
            'initial_capital': 100000
        })
        assert response.status_code in [200, 400]

    def test_run_backtest_missing_params(self, client):
        """Test backtest with missing parameters."""
        response = client.post('/api/backtest/run', json={})
        assert response.status_code in [400, 422]


# ============ Error Handling ============

class TestErrorHandling:
    """Test API error handling."""

    def test_404_page(self, client):
        """Test 404 for non-existent endpoint."""
        response = client.get('/api/v1/nonexistent')
        assert response.status_code == 404
        data = json.loads(response.data)
        assert data['success'] is False

    def test_method_not_allowed(self, client):
        """Test 405 for wrong HTTP method."""
        response = client.put('/api/v1/health')
        assert response.status_code == 405


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
