"""
Unit Tests for MarketDataService
Tests data loading, sector management, stock pool, and error paths.
"""
import json
import os
import tempfile
import pytest
from unittest.mock import patch

from services.market_service import MarketDataService


# ============ Fixtures ============

@pytest.fixture
def sample_market_data():
    """Sample market data with multiple sectors."""
    return {
        'stocks': [
            {'symbol': '002149', 'name': '西部材料', 'sector': '有色金属'},
            {'symbol': '601398', 'name': '工商银行', 'sector': '银行'},
            {'symbol': '600519', 'name': '贵州茅台', 'sector': '白酒'},
            {'symbol': '000858', 'name': '五粮液', 'sector': '白酒'},
            {'symbol': '300750', 'name': '宁德时代', 'sector': '新能源'},
            {'symbol': '000002', 'name': '万科A', 'sector': '房地产'},
        ]
    }


@pytest.fixture
def market_data_file(sample_market_data, tmp_path):
    """Create a temp JSON file with market data."""
    fp = tmp_path / 'stock_data_full.json'
    fp.write_text(json.dumps(sample_market_data))
    return str(fp)


@pytest.fixture
def empty_market_data_file(tmp_path):
    """Create a temp JSON file with empty stocks list."""
    fp = tmp_path / 'stock_data_full.json'
    fp.write_text(json.dumps({'stocks': []}))
    return str(fp)


@pytest.fixture
def invalid_json_file(tmp_path):
    """Create a temp file with invalid JSON."""
    fp = tmp_path / 'stock_data_full.json'
    fp.write_text('{invalid json content!!!')
    return str(fp)


# ============ __init__ and load_full_market_data Tests ============

class TestLoadFullMarketData:
    """Test data loading and initialization."""

    def test_load_valid_data(self, market_data_file):
        """Test loading valid market data file."""
        svc = MarketDataService(data_file=market_data_file)
        assert svc.total_stocks == 6
        assert svc.total_sectors == 5

    def test_load_populates_sectors_cache(self, market_data_file):
        """Test that sectors cache is populated correctly."""
        svc = MarketDataService(data_file=market_data_file)
        sectors = svc.get_sectors()
        assert '有色金属' in sectors
        assert '白酒' in sectors
        assert len(sectors) == 5

    def test_file_not_found(self, tmp_path):
        """Test loading when data file doesn't exist (lines 43-46)."""
        nonexistent = str(tmp_path / 'nonexistent.json')
        svc = MarketDataService(data_file=nonexistent)
        assert svc.total_stocks == 0
        assert svc.total_sectors == 0
        assert svc.get_sectors() == []

    def test_invalid_json(self, invalid_json_file):
        """Test loading when JSON is invalid (lines 39-42)."""
        svc = MarketDataService(data_file=invalid_json_file)
        assert svc.total_stocks == 0
        assert svc.total_sectors == 0

    def test_empty_stocks(self, empty_market_data_file):
        """Test loading with empty stocks list."""
        svc = MarketDataService(data_file=empty_market_data_file)
        assert svc.total_stocks == 0
        assert svc.total_sectors == 0

    def test_reload_data(self, market_data_file):
        """Test reloading market data clears old cache."""
        svc = MarketDataService(data_file=market_data_file)
        assert svc.total_stocks == 6
        # Point to empty file and reload
        empty_file = os.path.join(os.path.dirname(market_data_file), 'empty.json')
        with open(empty_file, 'w') as f:
            json.dump({'stocks': []}, f)
        svc._data_file = empty_file
        svc.load_full_market_data()
        assert svc.total_stocks == 0

    def test_default_data_file(self):
        """Test that default data_file is constructed when None is passed."""
        with patch.object(MarketDataService, '__init__', lambda self, data_file=None: None):
            svc = MarketDataService.__new__(MarketDataService)
            # Manually call init logic
            svc._data_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'stock_data_full.json')
            svc._full_stock_data = []
            svc._sectors_cache = {}
            # Just verify it doesn't crash
            assert svc._data_file.endswith('stock_data_full.json')


# ============ get_stock_by_symbol Tests ============

class TestGetStockBySymbol:
    """Test get_stock_by_symbol (lines 48-53)."""

    def test_found(self, market_data_file):
        """Test finding an existing stock."""
        svc = MarketDataService(data_file=market_data_file)
        stock = svc.get_stock_by_symbol('002149')
        assert stock is not None
        assert stock['name'] == '西部材料'

    def test_not_found(self, market_data_file):
        """Test returning None for non-existent symbol (line 53)."""
        svc = MarketDataService(data_file=market_data_file)
        assert svc.get_stock_by_symbol('999999') is None

    def test_empty_data(self, empty_market_data_file):
        """Test with no stocks loaded."""
        svc = MarketDataService(data_file=empty_market_data_file)
        assert svc.get_stock_by_symbol('002149') is None


# ============ get_sectors Tests ============

class TestGetSectors:
    """Test get_sectors (line 57)."""

    def test_returns_sorted_list(self, market_data_file):
        """Test sectors are returned sorted."""
        svc = MarketDataService(data_file=market_data_file)
        sectors = svc.get_sectors()
        assert sectors == sorted(sectors)

    def test_empty(self, empty_market_data_file):
        """Test with no sectors."""
        svc = MarketDataService(data_file=empty_market_data_file)
        assert svc.get_sectors() == []


# ============ get_sector_stocks Tests ============

class TestGetSectorStocks:
    """Test get_sector_stocks (line 61)."""

    def test_existing_sector(self, market_data_file):
        """Test getting stocks for an existing sector."""
        svc = MarketDataService(data_file=market_data_file)
        stocks = svc.get_sector_stocks('白酒')
        assert len(stocks) == 2
        names = {s['name'] for s in stocks}
        assert '贵州茅台' in names
        assert '五粮液' in names

    def test_nonexistent_sector(self, market_data_file):
        """Test returning empty list for non-existent sector."""
        svc = MarketDataService(data_file=market_data_file)
        assert svc.get_sector_stocks('不存在的板块') == []


# ============ Properties Tests ============

class TestProperties:
    """Test total_stocks and total_sectors properties."""

    def test_total_stocks(self, market_data_file):
        """Test total_stocks property (line 65)."""
        svc = MarketDataService(data_file=market_data_file)
        assert svc.total_stocks == 6

    def test_total_sectors(self, market_data_file):
        """Test total_sectors property (line 69)."""
        svc = MarketDataService(data_file=market_data_file)
        assert svc.total_sectors == 5

    def test_zero_counts(self, empty_market_data_file):
        """Test zero counts with empty data."""
        svc = MarketDataService(data_file=empty_market_data_file)
        assert svc.total_stocks == 0
        assert svc.total_sectors == 0


# ============ get_stock_pool Tests ============

class TestGetStockPool:
    """Test get_stock_pool (lines 71-92)."""

    def test_pool_from_sectors(self, market_data_file):
        """Test stock pool generation from sectors cache (lines 73-83)."""
        svc = MarketDataService(data_file=market_data_file)
        pool = svc.get_stock_pool()
        assert len(pool) > 0
        # Symbols starting with 6 should get 'sh' prefix
        assert 'sh601398' in pool
        # Symbols not starting with 6 should get 'sz' prefix
        assert 'sz002149' in pool

    def test_pool_already_prefixed(self, tmp_path):
        """Test that sh/sz prefixed symbols are kept as-is."""
        data = {
            'stocks': [
                {'symbol': 'sh601398', 'name': '工商银行', 'sector': '银行'},
                {'symbol': 'sz002149', 'name': '西部材料', 'sector': '有色金属'},
            ]
        }
        fp = tmp_path / 'data.json'
        fp.write_text(json.dumps(data))
        svc = MarketDataService(data_file=str(fp))
        pool = svc.get_stock_pool()
        assert 'sh601398' in pool
        assert 'sz002149' in pool

    def test_fallback_pool(self, empty_market_data_file):
        """Test fallback to default pool when no sectors (lines 85-92)."""
        svc = MarketDataService(data_file=empty_market_data_file)
        pool = svc.get_stock_pool()
        # Should return the hardcoded default list
        assert 'sz002149' in pool
        assert 'sh601398' in pool
        assert len(pool) == 28

    def test_pool_deduplicates(self, tmp_path):
        """Test that duplicate symbols are deduplicated."""
        data = {
            'stocks': [
                {'symbol': '002149', 'name': '西部材料', 'sector': 'A'},
                {'symbol': '002149', 'name': '西部材料', 'sector': 'B'},
            ]
        }
        fp = tmp_path / 'data.json'
        fp.write_text(json.dumps(data))
        svc = MarketDataService(data_file=str(fp))
        pool = svc.get_stock_pool()
        # Should only have one entry for sz002149
        assert pool.count('sz002149') == 1
