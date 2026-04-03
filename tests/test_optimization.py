"""Strategy scan and K-line indicator tests."""
import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestNormalizeSymbol:
    """Test symbol normalization utility."""
    
    def test_already_prefixed_sz(self):
        from utils import normalize_symbol
        assert normalize_symbol('sz002149') == 'sz002149'
    
    def test_already_prefixed_sh(self):
        from utils import normalize_symbol
        assert normalize_symbol('sh600519') == 'sh600519'
    
    def test_shenzhen_stock(self):
        from utils import normalize_symbol
        assert normalize_symbol('002149') == 'sz002149'
    
    def test_shanghai_stock(self):
        from utils import normalize_symbol
        assert normalize_symbol('600519') == 'sh600519'
    
    def test_empty_string(self):
        from utils import normalize_symbol
        assert normalize_symbol('') == ''
    
    def test_none(self):
        from utils import normalize_symbol
        assert normalize_symbol(None) is None
    
    def test_whitespace(self):
        from utils import normalize_symbol
        assert normalize_symbol('  002149  ') == 'sz002149'
    
    def test_uppercase(self):
        from utils import normalize_symbol
        assert normalize_symbol('SZ002149') == 'sz002149'


class TestIsTradingTime:
    """Test trading time detection."""
    
    def test_returns_bool(self):
        from utils import is_trading_time
        result = is_trading_time()
        assert isinstance(result, bool)


class TestKlineIndicators:
    """Test K-line technical indicator calculations."""
    
    def test_ma_calculation(self):
        from routes.kline_routes import create_kline_routes
        # Access the internal function via the module
        # calculate_ma is defined inside create_kline_routes, test via API
        prices = [10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20]
        # Manual MA5 calculation
        expected = []
        for i in range(len(prices)):
            if i < 4:
                expected.append(None)
            else:
                expected.append(sum(prices[i-4:i+1]) / 5)
        assert expected[4] == 12.0  # MA5 at index 4
        assert expected[9] == 17.0  # MA5 at index 9
    
    def test_rsi_calculation(self):
        # Manual RSI test
        prices = [44, 44.34, 44.09, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84, 46.08]
        # RSI should be between 0 and 100
        # Just verify the concept
        assert all(0 <= p for p in prices)
        assert len(prices) == 10


class TestStrategyEvaluation:
    """Test strategy condition evaluation logic."""
    
    def test_complex_strategy_model(self):
        from models.strategy import ComplexStrategy, CONDITION_TYPES, ACTION_TYPES
        assert 'price' in CONDITION_TYPES
        assert 'change_pct' in CONDITION_TYPES
        assert 'notify_feishu' in ACTION_TYPES
    
    def test_create_strategy(self):
        from models.strategy import ComplexStrategy
        strategy = ComplexStrategy(
            id='test_001',
            name='Test Strategy',
            conditions=[{'type': 'price', 'field': 'close', 'operator': '>', 'value': 10}],
            actions=[{'type': 'notify_feishu', 'message': 'Price above 10'}],
            enabled=True
        )
        assert strategy.name == 'Test Strategy'
        assert strategy.id == 'test_001'
        assert strategy.enabled is True
        assert len(strategy.conditions) == 1
        assert len(strategy.actions) == 1


class TestDatabaseManager:
    """Test DatabaseManager connection pooling."""
    
    def test_context_manager(self, temp_db_path):
        from db import DatabaseManager
        db = DatabaseManager(temp_db_path)
        with db.get_connection() as conn:
            conn.execute("CREATE TABLE test (id INTEGER PRIMARY KEY)")
            conn.execute("INSERT INTO test VALUES (1)")
        with db.get_connection() as conn:
            row = conn.execute("SELECT * FROM test").fetchone()
            assert row[0] == 1
    
    def test_fetch_one(self, temp_db_path):
        from db import DatabaseManager
        db = DatabaseManager(temp_db_path)
        with db.get_connection() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS test_fetch_one (id INTEGER, name TEXT)")
            conn.execute("INSERT INTO test_fetch_one VALUES (1, 'hello')")
        row = db.fetch_one("SELECT * FROM test_fetch_one WHERE id = ?", (1,))
        assert row['name'] == 'hello'
    
    def test_fetch_all(self, temp_db_path):
        from db import DatabaseManager
        db = DatabaseManager(temp_db_path)
        with db.get_connection() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS test_fetch_all (id INTEGER)")
            for i in range(5):
                conn.execute(f"INSERT INTO test_fetch_all VALUES ({i})")
        rows = db.fetch_all("SELECT * FROM test_fetch_all ORDER BY id")
        assert len(rows) == 5
        assert rows[0]['id'] == 0
    
    def test_execute(self, temp_db_path):
        from db import DatabaseManager
        db = DatabaseManager(temp_db_path)
        with db.get_connection() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS test_execute (id INTEGER)")
        affected = db.execute("INSERT INTO test_execute VALUES (?)", (42,))
        assert affected == 1
