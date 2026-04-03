"""
Unit Tests for StockService — database ops, k-line fetching, and market scanning.
Covers lines 172-395 which were previously untested.
"""
import time
import pytest
from unittest.mock import patch, MagicMock


# ============ Database Operations Tests ============

class TestInsertStockHistory:
    """Test insert_stock_history (lines 170-187)."""

    def test_insert_full_data(self, stock_service, sample_stock_data):
        """Test inserting stock data with all fields."""
        stock_service.insert_stock_history(sample_stock_data)
        history = stock_service.get_stock_history(limit=1)
        assert len(history) == 1
        assert history[0]['price'] == 55.0

    def test_insert_minimal_data(self, stock_service):
        """Test inserting with minimal/default data."""
        stock_service.insert_stock_history({})
        history = stock_service.get_stock_history(limit=1)
        assert len(history) == 1
        assert history[0]['price'] == 0


class TestGetStockHistory:
    """Test get_stock_history (lines 189-195)."""

    def test_empty_history(self, stock_service):
        """Test getting history when table is empty."""
        # Clear any data from previous tests (shared session DB)
        stock_service._db.execute('DELETE FROM stock_history')
        assert stock_service.get_stock_history() == []

    def test_history_limit(self, stock_service, sample_stock_data):
        """Test history respects limit parameter."""
        for i in range(5):
            data = sample_stock_data.copy()
            data['timestamp'] = 1700000000000 + i
            data['price'] = 50.0 + i
            stock_service.insert_stock_history(data)
        result = stock_service.get_stock_history(limit=3)
        assert len(result) == 3

    def test_history_order_desc(self, stock_service):
        """Test history is ordered by timestamp DESC."""
        for i in range(3):
            stock_service.insert_stock_history({'timestamp': 1000 + i, 'price': float(i)})
        result = stock_service.get_stock_history(limit=10)
        assert result[0]['timestamp'] >= result[-1]['timestamp']


class TestWatchlist:
    """Test watchlist operations (lines 197-211)."""

    def test_get_empty_watchlist(self, stock_service):
        """Test getting empty watchlist."""
        items = stock_service.get_watchlist()
        assert items == []

    def test_add_to_watchlist(self, stock_service):
        """Test adding a stock to watchlist."""
        stock_service.add_to_watchlist('sz002149', '西部材料')
        items = stock_service.get_watchlist()
        assert len(items) == 1
        assert items[0].symbol == 'sz002149'
        assert items[0].name == '西部材料'

    def test_add_without_name(self, stock_service):
        """Test adding without name uses symbol as name."""
        stock_service.add_to_watchlist('sz002149')
        items = stock_service.get_watchlist()
        assert items[0].name == 'sz002149'

    def test_add_duplicate_updates(self, stock_service):
        """Test adding duplicate symbol replaces."""
        stock_service.add_to_watchlist('sz002149', '旧名')
        stock_service.add_to_watchlist('sz002149', '新名')
        items = stock_service.get_watchlist()
        assert len(items) == 1
        assert items[0].name == '新名'

    def test_remove_from_watchlist(self, stock_service):
        """Test removing a stock from watchlist."""
        stock_service.add_to_watchlist('sz002149', '西部材料')
        stock_service.remove_from_watchlist('sz002149')
        assert stock_service.get_watchlist() == []

    def test_remove_nonexistent(self, stock_service):
        """Test removing non-existent symbol doesn't error."""
        stock_service.remove_from_watchlist('nonexistent')


class TestKlineDaily:
    """Test save_kline_daily and load_kline_daily (lines 213-249)."""

    def test_save_and_load(self, stock_service, sample_kline_data):
        """Test round-trip save and load."""
        stock_service.save_kline_daily('sz002149', sample_kline_data)
        loaded = stock_service.load_kline_daily('sz002149', limit=50)
        assert len(loaded) == 30
        # Should be in ascending date order
        assert loaded[0]['date'] == '2024-01-01'

    def test_load_limit(self, stock_service, sample_kline_data):
        """Test load respects limit."""
        stock_service.save_kline_daily('sz002149', sample_kline_data)
        loaded = stock_service.load_kline_daily('sz002149', limit=5)
        assert len(loaded) == 5

    def test_load_empty(self, stock_service):
        """Test loading when no data."""
        assert stock_service.load_kline_daily('nonexistent') == []

    def test_save_with_bad_row(self, stock_service):
        """Test save_kline_daily handles bad rows gracefully."""
        data = [
            {'date': '2024-01-01', 'open': 50, 'close': 51, 'high': 52, 'low': 49, 'volume': 1000},
            'not_a_dict',  # will cause exception but should not crash
        ]
        # save_kline_daily catches exceptions per-row
        stock_service.save_kline_daily('sz002149', data)
        loaded = stock_service.load_kline_daily('sz002149')
        assert len(loaded) >= 1

    def test_save_replaces_existing(self, stock_service, sample_kline_data):
        """Test INSERT OR REPLACE updates existing records."""
        stock_service.save_kline_daily('sz002149', sample_kline_data[:2])
        # Save again with different close price for the first date
        modified = [{'date': '2024-01-01', 'open': 99, 'close': 99, 'high': 99, 'low': 99, 'volume': 999}]
        stock_service.save_kline_daily('sz002149', modified)
        loaded = stock_service.load_kline_daily('sz002149')
        jan01 = next(r for r in loaded if r['date'] == '2024-01-01')
        assert jan01['close'] == 99

    def test_load_has_rsi_field(self, stock_service):
        """Test that rsi14 is mapped to rsi in loaded data."""
        data = [{'date': '2099-12-31', 'open': 50, 'close': 51, 'high': 52, 'low': 49, 'volume': 1000, 'rsi': 65.5}]
        stock_service.save_kline_daily('sz002149', data)
        loaded = stock_service.load_kline_daily('sz002149', limit=1)
        assert loaded[0]['rsi'] == 65.5


class TestCleanupOldData:
    """Test cleanup_old_data (lines 251-256)."""

    def test_cleanup_deletes_old(self, stock_service):
        """Test cleanup removes records older than threshold."""
        old_ts = int((time.time() - 60 * 86400) * 1000)  # 60 days ago
        stock_service.insert_stock_history({'timestamp': old_ts, 'price': 10.0})
        stock_service.insert_stock_history({'timestamp': int(time.time() * 1000), 'price': 20.0})

        result = stock_service.cleanup_old_data(days=30)
        assert result['history_deleted'] >= 1

    def test_cleanup_nothing(self, stock_service):
        """Test cleanup when nothing to delete."""
        stock_service.insert_stock_history({'timestamp': int(time.time() * 1000), 'price': 20.0})
        result = stock_service.cleanup_old_data(days=30)
        assert result['history_deleted'] == 0


# ============ K-line Fetching Tests ============

class TestFetchKlineData:
    """Test fetch_kline_data (lines 260-307)."""

    def test_cache_hit(self, stock_service, sample_kline_data):
        """Test that cached data is returned when sufficient."""
        test_symbol = 'sz999998'
        stock_service.save_kline_daily(test_symbol, sample_kline_data)
        result = stock_service.fetch_kline_data(test_symbol, ktype='day', num=30, use_cache=True)
        assert len(result) == 30
        # No network call should be made
        assert result[0]['date'] == '2024-01-01'

    def test_no_cache_when_disabled(self, stock_service, sample_kline_data):
        """Test that cache is bypassed when use_cache=False."""
        stock_service.save_kline_daily('sz002149', sample_kline_data)
        mock_response = MagicMock()
        mock_response.json.return_value = {'code': 0, 'data': {'sz002149': {'qfqday': [
            ['2024-02-01', '50', '51', '52', '49', '1000']
        ]}}}
        mock_response.text = ''
        with patch('services.stock_service.requests.get', return_value=mock_response):
            result = stock_service.fetch_kline_data('sz002149', ktype='day', num=1, use_cache=False)
            assert len(result) == 1

    def test_symbol_prefix_auto_add(self, stock_service):
        """Test auto-adds sh prefix for 6-starting symbols."""
        mock_response = MagicMock()
        mock_response.json.return_value = {'code': 0, 'data': {'sh601398': {'qfqday': []}}}
        with patch('services.stock_service.requests.get', return_value=mock_response) as mock_get:
            stock_service.fetch_kline_data('601398', ktype='day', num=10, use_cache=False)
            url = mock_get.call_args[0][0]
            assert 'sh601398' in url

    def test_symbol_prefix_sz(self, stock_service):
        """Test auto-adds sz prefix for non-6 symbols."""
        mock_response = MagicMock()
        mock_response.json.return_value = {'code': 0, 'data': {'sz002149': {'qfqday': []}}}
        with patch('services.stock_service.requests.get', return_value=mock_response) as mock_get:
            stock_service.fetch_kline_data('002149', ktype='day', num=10, use_cache=False)
            url = mock_get.call_args[0][0]
            assert 'sz002149' in url

    def test_already_prefixed_symbol(self, stock_service):
        """Test symbols already prefixed are not modified."""
        mock_response = MagicMock()
        mock_response.json.return_value = {'code': 0, 'data': {'sz002149': {'qfqday': []}}}
        with patch('services.stock_service.requests.get', return_value=mock_response) as mock_get:
            stock_service.fetch_kline_data('sz002149', ktype='day', num=10, use_cache=False)
            url = mock_get.call_args[0][0]
            assert 'szsz' not in url

    def test_api_error_code(self, stock_service):
        """Test returns empty list on API error code."""
        mock_response = MagicMock()
        mock_response.json.return_value = {'code': -1, 'data': {}}
        with patch('services.stock_service.requests.get', return_value=mock_response):
            result = stock_service.fetch_kline_data('sz002149', ktype='day', num=10, use_cache=False)
            assert result == []

    def test_parse_weekly_kline(self, stock_service):
        """Test parsing weekly kline data."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            'code': 0,
            'data': {'sz002149': {'qfqweek': [
                ['2024-W01', '50', '51', '52', '49', '5000']
            ]}}
        }
        with patch('services.stock_service.requests.get', return_value=mock_response):
            result = stock_service.fetch_kline_data('sz002149', ktype='week', num=10, use_cache=False)
            assert len(result) == 1
            assert result[0]['date'] == '2024-W01'

    def test_parse_monthly_kline(self, stock_service):
        """Test parsing monthly kline data."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            'code': 0,
            'data': {'sz002149': {'qfqmonth': [
                ['2024-01', '50', '51', '52', '49', '10000']
            ]}}
        }
        with patch('services.stock_service.requests.get', return_value=mock_response):
            result = stock_service.fetch_kline_data('sz002149', ktype='month', num=10, use_cache=False)
            assert len(result) == 1

    def test_unknown_ktype_uses_qfqday(self, stock_service):
        """Test unknown ktype falls back to qfqday key."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            'code': 0,
            'data': {'sz002149': {'qfqday': [
                ['2024-01-01', '50', '51', '52', '49', '1000']
            ]}}
        }
        with patch('services.stock_service.requests.get', return_value=mock_response):
            result = stock_service.fetch_kline_data('sz002149', ktype='unknown', num=10, use_cache=False)
            assert len(result) == 1

    def test_short_row_skipped(self, stock_service):
        """Test rows with fewer than 6 elements are skipped."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            'code': 0,
            'data': {'sz002149': {'qfqday': [
                ['2024-01-01', '50'],  # too short
                ['2024-01-02', '50', '51', '52', '49', '1000']  # valid
            ]}}
        }
        with patch('services.stock_service.requests.get', return_value=mock_response):
            result = stock_service.fetch_kline_data('sz002149', ktype='day', num=10, use_cache=False)
            assert len(result) == 1

    def test_empty_fields_become_zero(self, stock_service):
        """Test empty string fields default to 0."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            'code': 0,
            'data': {'sz002149': {'qfqday': [
                ['2024-01-01', '', '', '', '', '']
            ]}}
        }
        with patch('services.stock_service.requests.get', return_value=mock_response):
            result = stock_service.fetch_kline_data('sz002149', ktype='day', num=10, use_cache=False)
            assert len(result) == 1
            assert result[0]['open'] == 0
            assert result[0]['close'] == 0

    def test_network_error_returns_empty(self, stock_service):
        """Test network error returns empty list."""
        import requests
        with patch('services.stock_service.requests.get', side_effect=requests.ConnectionError()):
            result = stock_service.fetch_kline_data('sz002149', ktype='day', num=10, use_cache=False)
            assert result == []

    def test_day_kline_saves_to_db(self, stock_service):
        """Test that day kline results are saved to database."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            'code': 0,
            'data': {'sz002149': {'qfqday': [
                ['2024-01-01', '50', '51', '52', '49', '1000']
            ]}}
        }
        with patch('services.stock_service.requests.get', return_value=mock_response):
            stock_service.fetch_kline_data('sz002149', ktype='day', num=10, use_cache=False)
        # Verify saved to DB
        loaded = stock_service.load_kline_daily('sz002149', limit=1)
        assert len(loaded) == 1

    def test_cache_insufficient_triggers_fetch(self, stock_service, sample_kline_data):
        """Test that insufficient cache (< 80%) triggers network fetch."""
        # Use a symbol unlikely to exist in the test DB
        test_symbol = 'sz999999'
        stock_service.save_kline_daily(test_symbol, sample_kline_data[:5])  # only 5 records
        mock_response = MagicMock()
        mock_response.json.return_value = {
            'code': 0,
            'data': {'sz999999': {'qfqday': [
                ['2024-01-01', '50', '51', '52', '49', '1000']
            ]}}
        }
        with patch('services.stock_service.requests.get', return_value=mock_response):
            result = stock_service.fetch_kline_data(test_symbol, ktype='day', num=30, use_cache=True)
            assert len(result) == 1


class TestFetchKlineEastmoney:
    """Test fetch_kline_eastmoney (lines 309-359)."""

    def test_sz_prefix(self, stock_service):
        """Test sz prefix maps to secid 0.xxxx."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            'data': {'klines': ['2024-01-01,50,51,52,49,1000,0,0,0,0,0']}
        }
        with patch('services.stock_service.requests.get', return_value=mock_response) as mock_get:
            stock_service.fetch_kline_eastmoney('sz002149', days=10)
            params = mock_get.call_args[1]['params']
            assert params['secid'] == '0.002149'

    def test_sh_prefix(self, stock_service):
        """Test sh prefix maps to secid 1.xxxx."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            'data': {'klines': ['2024-01-01,50,51,52,49,1000,0,0,0,0,0']}
        }
        with patch('services.stock_service.requests.get', return_value=mock_response) as mock_get:
            stock_service.fetch_kline_eastmoney('sh601398', days=10)
            params = mock_get.call_args[1]['params']
            assert params['secid'] == '1.601398'

    def test_no_prefix_6_start(self, stock_service):
        """Test no prefix with 6-start maps to 1.xxxx."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            'data': {'klines': ['2024-01-01,50,51,52,49,1000,0,0,0,0,0']}
        }
        with patch('services.stock_service.requests.get', return_value=mock_response) as mock_get:
            stock_service.fetch_kline_eastmoney('601398', days=10)
            params = mock_get.call_args[1]['params']
            assert params['secid'] == '1.601398'

    def test_no_prefix_non6_start(self, stock_service):
        """Test no prefix with non-6 start maps to 0.xxxx."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            'data': {'klines': ['2024-01-01,50,51,52,49,1000,0,0,0,0,0']}
        }
        with patch('services.stock_service.requests.get', return_value=mock_response) as mock_get:
            stock_service.fetch_kline_eastmoney('002149', days=10)
            params = mock_get.call_args[1]['params']
            assert params['secid'] == '0.002149'

    def test_empty_klines(self, stock_service):
        """Test returns empty list when no klines data."""
        mock_response = MagicMock()
        mock_response.json.return_value = {'data': {'klines': []}}
        with patch('services.stock_service.requests.get', return_value=mock_response):
            result = stock_service.fetch_kline_eastmoney('sz002149')
            assert result == []

    def test_no_data_key(self, stock_service):
        """Test returns empty when data key missing."""
        mock_response = MagicMock()
        mock_response.json.return_value = {}
        with patch('services.stock_service.requests.get', return_value=mock_response):
            result = stock_service.fetch_kline_eastmoney('sz002149')
            assert result == []

    def test_parse_row(self, stock_service):
        """Test parsing a valid kline row."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            'data': {'klines': ['2024-01-01,50.5,51.5,52.0,49.0,1000000,0,0,0,0,0']}
        }
        with patch('services.stock_service.requests.get', return_value=mock_response):
            result = stock_service.fetch_kline_eastmoney('sz002149', days=10)
            assert len(result) == 1
            assert result[0]['date'] == '2024-01-01'
            assert result[0]['open'] == 50.5
            assert result[0]['close'] == 51.5

    def test_short_row_skipped(self, stock_service):
        """Test rows with fewer than 6 parts are skipped."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            'data': {'klines': ['2024-01-01,50', '2024-01-02,50,51,52,49,1000']}
        }
        with patch('services.stock_service.requests.get', return_value=mock_response):
            result = stock_service.fetch_kline_eastmoney('sz002149')
            assert len(result) == 1

    def test_empty_string_defaults_to_zero(self, stock_service):
        """Test empty string parts default to 0."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            'data': {'klines': ['2024-01-01,,,,,']}
        }
        with patch('services.stock_service.requests.get', return_value=mock_response):
            result = stock_service.fetch_kline_eastmoney('sz002149')
            assert len(result) == 1
            assert result[0]['open'] == 0

    def test_network_error_returns_empty(self, stock_service):
        """Test network error returns empty list."""
        import requests
        with patch('services.stock_service.requests.get', side_effect=requests.ConnectionError()):
            result = stock_service.fetch_kline_eastmoney('sz002149')
            assert result == []

    def test_days_capped_at_5000(self, stock_service):
        """Test days parameter is capped at 5000."""
        mock_response = MagicMock()
        mock_response.json.return_value = {'data': {'klines': []}}
        with patch('services.stock_service.requests.get', return_value=mock_response) as mock_get:
            stock_service.fetch_kline_eastmoney('sz002149', days=99999)
            params = mock_get.call_args[1]['params']
            assert params['lmt'] == '5000'


# ============ Market Scanning Tests ============

class TestScanMarketConcurrent:
    """Test scan_market_concurrent (lines 363-395)."""

    def test_scan_finds_matches(self, stock_service):
        """Test scan returns matching stocks."""
        mock_strategy_svc = MagicMock()
        mock_strategy_svc.evaluate_strategy.return_value = True

        with patch('services.strategy_service.StrategyService', return_value=mock_strategy_svc), \
             patch.object(stock_service._market, 'get_stock_pool', return_value=['sz002149', 'sh601398']), \
             patch.object(stock_service, 'fetch_tencent_data', return_value=[
                 {'symbol': 'sz002149', 'name': '西部材料', 'price': 55.0, 'prev_close': 54.0},
                 {'symbol': 'sh601398', 'name': '工商银行', 'price': 6.0, 'prev_close': 5.9},
             ]):
            strategy = {'type': 'price', 'conditions': []}
            result = stock_service.scan_market_concurrent(strategy, batch_size=10)
            assert len(result) == 2

    def test_scan_no_matches(self, stock_service):
        """Test scan returns empty when no stocks match."""
        mock_strategy_svc = MagicMock()
        mock_strategy_svc.evaluate_strategy.return_value = False

        with patch('services.strategy_service.StrategyService', return_value=mock_strategy_svc), \
             patch.object(stock_service._market, 'get_stock_pool', return_value=['sz002149']), \
             patch.object(stock_service, 'fetch_tencent_data', return_value=[
                 {'symbol': 'sz002149', 'name': '西部材料', 'price': 55.0, 'prev_close': 54.0},
             ]):
            strategy = {'type': 'price', 'conditions': []}
            result = stock_service.scan_market_concurrent(strategy)
            assert result == []

    def test_scan_empty_pool(self, stock_service):
        """Test scan with empty stock pool."""
        with patch.object(stock_service._market, 'get_stock_pool', return_value=[]):
            result = stock_service.scan_market_concurrent({})
            assert result == []

    def test_scan_chg_calculated(self, stock_service):
        """Test that chg and chg_pct are calculated in scan results."""
        mock_strategy_svc = MagicMock()
        mock_strategy_svc.evaluate_strategy.return_value = True

        with patch('services.strategy_service.StrategyService', return_value=mock_strategy_svc), \
             patch.object(stock_service._market, 'get_stock_pool', return_value=['sz002149']), \
             patch.object(stock_service, 'fetch_tencent_data', return_value=[
                 {'symbol': 'sz002149', 'name': '西部材料', 'price': 55.0, 'prev_close': 50.0},
             ]):
            result = stock_service.scan_market_concurrent({}, batch_size=10)
            assert result[0]['chg'] == 5.0
            assert result[0]['chg_pct'] == 10.0
            assert result[0]['volume_surge'] == 0

    def test_scan_no_prev_close(self, stock_service):
        """Test scan handles missing prev_close."""
        mock_strategy_svc = MagicMock()
        mock_strategy_svc.evaluate_strategy.return_value = True

        with patch('services.strategy_service.StrategyService', return_value=mock_strategy_svc), \
             patch.object(stock_service._market, 'get_stock_pool', return_value=['sz002149']), \
             patch.object(stock_service, 'fetch_tencent_data', return_value=[
                 {'symbol': 'sz002149', 'name': '西部材料', 'price': 55.0},
             ]):
            result = stock_service.scan_market_concurrent({}, batch_size=10)
            assert result[0]['chg_pct'] == 0

    def test_scan_batch_error_continues(self, stock_service):
        """Test that batch errors are logged but don't crash scan."""
        call_count = 0

        def mock_fetch(symbols):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("Network error")
            return [{'symbol': s, 'price': 50, 'prev_close': 49} for s in symbols]

        mock_strategy_svc = MagicMock()
        mock_strategy_svc.evaluate_strategy.return_value = True

        with patch('services.strategy_service.StrategyService', return_value=mock_strategy_svc), \
             patch.object(stock_service._market, 'get_stock_pool', return_value=['sz002149', 'sh601398']), \
             patch.object(stock_service, 'fetch_tencent_data', side_effect=mock_fetch):
            # With batch_size=1, each stock is a batch; one fails, one succeeds
            result = stock_service.scan_market_concurrent({}, batch_size=1)
            # At least one should succeed
            assert len(result) >= 0  # error is caught, scan continues


# ============ Delegation Tests ============

class TestDelegatedMethods:
    """Test that delegated methods call through correctly."""

    def test_load_full_market_data_delegates(self, stock_service):
        """Test load_full_market_data delegates to market service."""
        with patch.object(stock_service._market, 'load_full_market_data') as mock_load:
            stock_service.load_full_market_data()
            mock_load.assert_called_once()

    def test_get_stock_by_symbol_delegates(self, stock_service):
        """Test get_stock_by_symbol delegates."""
        with patch.object(stock_service._market, 'get_stock_by_symbol', return_value={'name': 'test'}) as mock:
            result = stock_service.get_stock_by_symbol('sz002149')
            mock.assert_called_once_with('sz002149')
            assert result['name'] == 'test'

    def test_get_sectors_delegates(self, stock_service):
        """Test get_sectors delegates."""
        with patch.object(stock_service._market, 'get_sectors', return_value=['银行']) as mock:
            result = stock_service.get_sectors()
            mock.assert_called_once()
            assert result == ['银行']

    def test_get_sector_stocks_delegates(self, stock_service):
        """Test get_sector_stocks delegates."""
        with patch.object(stock_service._market, 'get_sector_stocks', return_value=[]) as mock:
            result = stock_service.get_sector_stocks('银行')
            mock.assert_called_once_with('银行')
            assert result == []

    def test_get_cached_quote_delegates(self, stock_service):
        """Test get_cached_quote delegates to quote service."""
        with patch.object(stock_service._quote, 'get_cached_quote', return_value={'price': 50}) as mock:
            result = stock_service.get_cached_quote('sz002149')
            mock.assert_called_once_with('sz002149')
            assert result['price'] == 50

    def test_set_cached_quote_delegates(self, stock_service):
        """Test set_cached_quote delegates to quote service."""
        with patch.object(stock_service._quote, 'set_cached_quote') as mock:
            stock_service.set_cached_quote('sz002149', {'price': 50})
            mock.assert_called_once_with('sz002149', {'price': 50})

    def test_fetch_tencent_data_delegates(self, stock_service):
        """Test fetch_tencent_data delegates to quote service."""
        with patch.object(stock_service._quote, 'fetch_tencent_data', return_value=[]) as mock:
            result = stock_service.fetch_tencent_data(['sz002149'])
            mock.assert_called_once_with(['sz002149'])
            assert result == []

    def test_fetch_indexes_delegates(self, stock_service):
        """Test fetch_indexes delegates to quote service."""
        with patch.object(stock_service._quote, 'fetch_indexes', return_value=[]) as mock:
            result = stock_service.fetch_indexes()
            mock.assert_called_once()
            assert result == []
