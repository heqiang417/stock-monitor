"""
Unit Tests for StrategyService
Tests strategy evaluation, persistence, scanning, and action formatting.
"""
import pytest
import json
import os
import time
from datetime import datetime
from unittest.mock import patch, MagicMock, PropertyMock


# ============ Fixtures ============

@pytest.fixture
def stock_service_mock():
    """Create a mock StockService."""
    svc = MagicMock()
    svc.get_watchlist.return_value = []
    svc.fetch_tencent_data.return_value = []
    svc.scan_market_concurrent.return_value = []
    svc.insert_stock_history = MagicMock()
    svc.cleanup_old_data = MagicMock()
    svc.fetch_kline_data.return_value = []
    svc.save_kline_daily = MagicMock()
    return svc


@pytest.fixture
def strategy_service(stock_service_mock, tmp_path):
    """Create a StrategyService with temp file."""
    from services.strategy_service import StrategyService
    strategies_file = str(tmp_path / 'test_strategies.json')
    return StrategyService(stock_service=stock_service_mock, strategies_file=strategies_file)


@pytest.fixture
def sample_data():
    """Sample stock data."""
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
def complex_strategy():
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
            {'type': 'notify_feishu', 'message': '🚀 价格涨到 {price}！'},
            {'type': 'alert_web', 'level': 'high'}
        ],
        'lastTriggered': None,
        'triggerCount': 0
    }


# ============ Initialization Tests ============

class TestStrategyServiceInit:
    """Test StrategyService initialization."""

    def test_init_creates_simple_strategies(self, strategy_service):
        """Test that simple strategies are initialized."""
        assert 'price_up' in strategy_service.simple_strategies
        assert 'price_down' in strategy_service.simple_strategies
        assert 'chg_pct_up' in strategy_service.simple_strategies
        assert 'chg_pct_down' in strategy_service.simple_strategies
        assert 'volume_surge' in strategy_service.simple_strategies
        assert 'resistance' in strategy_service.simple_strategies
        assert 'support' in strategy_service.simple_strategies
        assert 'target_price' in strategy_service.simple_strategies
        assert 'stop_loss' in strategy_service.simple_strategies

    def test_init_simple_strategy_defaults(self, strategy_service):
        """Test default values of simple strategies."""
        assert strategy_service.simple_strategies['price_up']['enabled'] is True
        assert strategy_service.simple_strategies['price_up']['value'] == 50.0
        assert strategy_service.simple_strategies['volume_surge']['enabled'] is False

    def test_init_loads_default_strategies_when_no_file(self, strategy_service):
        """Test loading default strategies when file doesn't exist."""
        assert isinstance(strategy_service.complex_strategies, list)
        assert len(strategy_service.complex_strategies) > 0


# ============ Load/Save Tests ============

class TestStrategyPersistence:
    """Test strategy load and save."""

    def test_save_and_load_strategies(self, stock_service_mock, tmp_path):
        """Test saving and loading strategies."""
        from services.strategy_service import StrategyService
        strategies_file = str(tmp_path / 'test_save.json')

        svc = StrategyService(stock_service=stock_service_mock, strategies_file=strategies_file)
        test_strategies = [
            {'id': 's1', 'name': '策略1', 'enabled': True, 'logic': 'AND', 'conditions': [], 'actions': []},
            {'id': 's2', 'name': '策略2', 'enabled': False, 'logic': 'OR', 'conditions': [], 'actions': []},
        ]
        result = svc.save_complex_strategies(test_strategies)
        assert result is True
        assert os.path.exists(strategies_file)

        # Create new instance to load
        svc2 = StrategyService(stock_service=stock_service_mock, strategies_file=strategies_file)
        assert len(svc2.complex_strategies) == 2
        assert svc2.complex_strategies[0]['id'] == 's1'

    def test_load_invalid_json_returns_defaults(self, stock_service_mock, tmp_path):
        """Test that invalid JSON file returns defaults."""
        from services.strategy_service import StrategyService
        strategies_file = str(tmp_path / 'invalid.json')
        with open(strategies_file, 'w') as f:
            f.write('{invalid json content')

        svc = StrategyService(stock_service=stock_service_mock, strategies_file=strategies_file)
        # Should fall back to defaults
        assert isinstance(svc.complex_strategies, list)
        assert len(svc.complex_strategies) > 0

    def test_load_empty_json_array_returns_defaults(self, stock_service_mock, tmp_path):
        """Test that empty JSON array returns defaults."""
        from services.strategy_service import StrategyService
        from models.alert import DEFAULT_COMPLEX_STRATEGIES
        strategies_file = str(tmp_path / 'empty.json')
        with open(strategies_file, 'w') as f:
            json.dump([], f)

        svc = StrategyService(stock_service=stock_service_mock, strategies_file=strategies_file)
        assert len(svc.complex_strategies) == len(DEFAULT_COMPLEX_STRATEGIES)

    def test_load_non_list_returns_defaults(self, stock_service_mock, tmp_path):
        """Test that non-list JSON returns defaults."""
        from services.strategy_service import StrategyService
        strategies_file = str(tmp_path / 'nonlist.json')
        with open(strategies_file, 'w') as f:
            json.dump({"not": "a list"}, f)

        svc = StrategyService(stock_service=stock_service_mock, strategies_file=strategies_file)
        assert isinstance(svc.complex_strategies, list)
        assert len(svc.complex_strategies) > 0

    def test_save_handles_write_error(self, strategy_service, tmp_path):
        """Test save handles write errors gracefully."""
        # Point to a directory instead of a file
        bad_path = str(tmp_path / 'subdir')
        os.makedirs(bad_path)
        result = strategy_service.save_complex_strategies([])
        # Should still work (writes to strategies_file which is a valid path)
        # The failure case: write to an invalid path
        strategy_service.strategies_file = '/dev/null/invalid.json'
        result = strategy_service.save_complex_strategies([])
        assert result is False


# ============ Strategy CRUD Tests ============

class TestStrategyCRUD:
    """Test get, update, delete strategies."""

    def test_get_strategies(self, strategy_service):
        """Test getting all strategies."""
        result = strategy_service.get_strategies()
        assert 'simple' in result
        assert 'complex' in result
        assert 'condition_types' in result
        assert 'action_types' in result

    def test_update_simple_strategy(self, strategy_service):
        """Test updating a simple strategy."""
        result = strategy_service.update_simple_strategy('price_up', {'value': 60.0})
        assert result is True
        assert strategy_service.simple_strategies['price_up']['value'] == 60.0

    def test_update_simple_strategy_not_found(self, strategy_service):
        """Test updating non-existent simple strategy."""
        result = strategy_service.update_simple_strategy('nonexistent', {'value': 60.0})
        assert result is False

    def test_delete_simple_strategy(self, strategy_service):
        """Test deleting a simple strategy."""
        result = strategy_service.delete_simple_strategy('price_up')
        assert result is True
        assert 'price_up' not in strategy_service.simple_strategies

    def test_delete_simple_strategy_not_found(self, strategy_service):
        """Test deleting non-existent simple strategy."""
        result = strategy_service.delete_simple_strategy('nonexistent')
        assert result is False

    def test_add_complex_strategy(self, strategy_service):
        """Test adding a new complex strategy."""
        new_strategy = {
            'id': 'new_s1',
            'name': '新策略',
            'enabled': True,
            'logic': 'AND',
            'conditions': [{'type': 'price', 'operator': '>', 'value': 100}],
            'actions': [{'type': 'log', 'message': 'test'}]
        }
        result = strategy_service.update_complex_strategy(new_strategy)
        assert result is True
        ids = [s['id'] for s in strategy_service.complex_strategies]
        assert 'new_s1' in ids

    def test_update_existing_complex_strategy(self, strategy_service, complex_strategy):
        """Test updating an existing complex strategy."""
        strategy_service.complex_strategies = [complex_strategy]
        strategy_service.complex_strategies[0]['triggerCount'] = 5

        updated = dict(complex_strategy)
        updated['name'] = '修改后的策略'
        updated['triggerCount'] = 10

        result = strategy_service.update_complex_strategy(updated)
        assert result is True
        assert strategy_service.complex_strategies[0]['name'] == '修改后的策略'
        assert strategy_service.complex_strategies[0]['triggerCount'] == 10

    def test_delete_complex_strategy(self, strategy_service, complex_strategy):
        """Test deleting a complex strategy."""
        strategy_service.complex_strategies = [complex_strategy]
        result = strategy_service.delete_complex_strategy('test_strategy')
        assert result is True
        assert len(strategy_service.complex_strategies) == 0

    def test_delete_complex_strategy_not_found(self, strategy_service, complex_strategy):
        """Test deleting non-existent complex strategy."""
        strategy_service.complex_strategies = [complex_strategy]
        result = strategy_service.delete_complex_strategy('nonexistent')
        assert result is True  # Still returns True, just no change
        assert len(strategy_service.complex_strategies) == 1


# ============ Condition Evaluation Tests ============

class TestConditionEvaluation:
    """Test the evaluate_condition method."""

    def test_price_greater_than(self, strategy_service, sample_data):
        """Test price > condition."""
        cond = {'type': 'price', 'operator': '>', 'value': 50}
        assert strategy_service.evaluate_condition(cond, sample_data) is True
        cond = {'type': 'price', 'operator': '>', 'value': 60}
        assert strategy_service.evaluate_condition(cond, sample_data) is False

    def test_price_greater_equal(self, strategy_service, sample_data):
        """Test price >= condition."""
        cond = {'type': 'price', 'operator': '>=', 'value': 55.0}
        assert strategy_service.evaluate_condition(cond, sample_data) is True

    def test_price_less_than(self, strategy_service, sample_data):
        """Test price < condition."""
        cond = {'type': 'price', 'operator': '<', 'value': 60}
        assert strategy_service.evaluate_condition(cond, sample_data) is True
        cond = {'type': 'price', 'operator': '<', 'value': 50}
        assert strategy_service.evaluate_condition(cond, sample_data) is False

    def test_price_less_equal(self, strategy_service, sample_data):
        """Test price <= condition."""
        cond = {'type': 'price', 'operator': '<=', 'value': 55.0}
        assert strategy_service.evaluate_condition(cond, sample_data) is True

    def test_price_equal(self, strategy_service, sample_data):
        """Test price == condition."""
        cond = {'type': 'price', 'operator': '==', 'value': 55.0}
        assert strategy_service.evaluate_condition(cond, sample_data) is True
        cond = {'type': 'price', 'operator': '==', 'value': 56.0}
        assert strategy_service.evaluate_condition(cond, sample_data) is False

    def test_price_between(self, strategy_service, sample_data):
        """Test price between condition."""
        cond = {'type': 'price', 'operator': 'between', 'value': [50, 60]}
        assert strategy_service.evaluate_condition(cond, sample_data) is True
        cond = {'type': 'price', 'operator': 'between', 'value': [56, 60]}
        assert strategy_service.evaluate_condition(cond, sample_data) is False

    def test_change_pct(self, strategy_service, sample_data):
        """Test change_pct conditions."""
        cond = {'type': 'change_pct', 'operator': '>', 'value': 1.0}
        assert strategy_service.evaluate_condition(cond, sample_data) is True
        cond = {'type': 'change_pct', 'operator': '<', 'value': 1.0}
        assert strategy_service.evaluate_condition(cond, sample_data) is False

    def test_volume_condition(self, strategy_service, sample_data):
        """Test volume conditions."""
        cond = {'type': 'volume', 'operator': '>', 'value': 1000000}
        assert strategy_service.evaluate_condition(cond, sample_data) is True

    def test_volume_surge_condition(self, strategy_service, sample_data):
        """Test volume_surge conditions."""
        cond = {'type': 'volume_surge', 'operator': '>=', 'value': 30}
        assert strategy_service.evaluate_condition(cond, sample_data) is True
        cond = {'type': 'volume_surge', 'operator': '>=', 'value': 100}
        assert strategy_service.evaluate_condition(cond, sample_data) is False

    def test_high_condition(self, strategy_service, sample_data):
        """Test high price condition."""
        cond = {'type': 'high', 'operator': '>=', 'value': 55}
        assert strategy_service.evaluate_condition(cond, sample_data) is True

    def test_low_condition(self, strategy_service, sample_data):
        """Test low price condition."""
        cond = {'type': 'low', 'operator': '<=', 'value': 54}
        assert strategy_service.evaluate_condition(cond, sample_data) is True

    def test_unknown_type_returns_false(self, strategy_service, sample_data):
        """Test unknown condition type returns False."""
        cond = {'type': 'unknown', 'operator': '>', 'value': 0}
        assert strategy_service.evaluate_condition(cond, sample_data) is False

    def test_missing_data_returns_false(self, strategy_service):
        """Test missing data fields returns False."""
        cond = {'type': 'price', 'operator': '>', 'value': 10}
        assert strategy_service.evaluate_condition(cond, {}) is False

    def test_invalid_operator_returns_false(self, strategy_service, sample_data):
        """Test invalid operator returns False."""
        cond = {'type': 'price', 'operator': 'invalid', 'value': 10}
        assert strategy_service.evaluate_condition(cond, sample_data) is False

    def test_time_condition_between(self, strategy_service, sample_data):
        """Test time between condition."""
        now = datetime.now()
        start = f"{max(0, now.hour - 1):02d}:00"
        end = f"{min(23, now.hour + 1):02d}:59"
        cond = {'type': 'time', 'operator': 'between', 'value': [start, end]}
        result = strategy_service.evaluate_condition(cond, sample_data)
        # Should be True since current time is within range
        assert result is True

    def test_time_condition_non_between(self, strategy_service, sample_data):
        """Test time condition with non-between operator returns False."""
        cond = {'type': 'time', 'operator': '>', 'value': '12:00'}
        assert strategy_service.evaluate_condition(cond, sample_data) is False

    def test_day_of_week_in(self, strategy_service, sample_data):
        """Test day_of_week in condition."""
        today = datetime.now().weekday()
        cond = {'type': 'day_of_week', 'operator': 'in', 'value': [today]}
        assert strategy_service.evaluate_condition(cond, sample_data) is True

    def test_day_of_week_not_in(self, strategy_service, sample_data):
        """Test day_of_week not_in condition."""
        today = datetime.now().weekday()
        cond = {'type': 'day_of_week', 'operator': 'not_in', 'value': [today]}
        assert strategy_service.evaluate_condition(cond, sample_data) is False

    def test_day_of_week_invalid_operator(self, strategy_service, sample_data):
        """Test day_of_week with invalid operator."""
        cond = {'type': 'day_of_week', 'operator': '>', 'value': [0, 1]}
        assert strategy_service.evaluate_condition(cond, sample_data) is False


# ============ Strategy Evaluation Tests ============

class TestStrategyEvaluation:
    """Test the evaluate_strategy method."""

    def test_and_all_pass(self, strategy_service, sample_data):
        """Test AND strategy where all conditions pass."""
        strategy = {
            'enabled': True,
            'logic': 'AND',
            'conditions': [
                {'type': 'price', 'operator': '>=', 'value': 50},
                {'type': 'change_pct', 'operator': '>=', 'value': 0}
            ]
        }
        assert strategy_service.evaluate_strategy(strategy, sample_data) is True

    def test_and_one_fails(self, strategy_service, sample_data):
        """Test AND strategy where one condition fails."""
        strategy = {
            'enabled': True,
            'logic': 'AND',
            'conditions': [
                {'type': 'price', 'operator': '>=', 'value': 50},
                {'type': 'change_pct', 'operator': '>=', 'value': 10}  # fails
            ]
        }
        assert strategy_service.evaluate_strategy(strategy, sample_data) is False

    def test_or_one_passes(self, strategy_service, sample_data):
        """Test OR strategy where one passes."""
        strategy = {
            'enabled': True,
            'logic': 'OR',
            'conditions': [
                {'type': 'price', 'operator': '>=', 'value': 100},  # fails
                {'type': 'change_pct', 'operator': '>=', 'value': 0}  # passes
            ]
        }
        assert strategy_service.evaluate_strategy(strategy, sample_data) is True

    def test_or_all_fail(self, strategy_service, sample_data):
        """Test OR strategy where all fail."""
        strategy = {
            'enabled': True,
            'logic': 'OR',
            'conditions': [
                {'type': 'price', 'operator': '>=', 'value': 100},
                {'type': 'change_pct', 'operator': '>=', 'value': 10}
            ]
        }
        assert strategy_service.evaluate_strategy(strategy, sample_data) is False

    def test_disabled_returns_false(self, strategy_service, sample_data):
        """Test disabled strategy returns False."""
        strategy = {
            'enabled': False,
            'logic': 'AND',
            'conditions': [{'type': 'price', 'operator': '>=', 'value': 0}]
        }
        assert strategy_service.evaluate_strategy(strategy, sample_data) is False

    def test_empty_conditions(self, strategy_service, sample_data):
        """Test strategy with empty conditions."""
        strategy = {'enabled': True, 'logic': 'AND', 'conditions': []}
        # all([]) returns True for AND
        assert strategy_service.evaluate_strategy(strategy, sample_data) is True

    def test_default_logic_is_and(self, strategy_service, sample_data):
        """Test that default logic is AND."""
        strategy = {
            'enabled': True,
            'conditions': [
                {'type': 'price', 'operator': '>=', 'value': 50},
                {'type': 'change_pct', 'operator': '>=', 'value': 0}
            ]
        }
        assert strategy_service.evaluate_strategy(strategy, sample_data) is True


# ============ Check All Strategies Tests ============

class TestCheckAllStrategies:
    """Test the check_all_strategies method."""

    def test_triggered_strategy(self, strategy_service, sample_data, complex_strategy):
        """Test that a matching strategy is triggered."""
        strategy_service.complex_strategies = [complex_strategy]
        results = strategy_service.check_all_strategies(sample_data)
        assert len(results) == 1
        assert results[0]['strategy'] == '测试策略'
        assert results[0]['id'] == 'test_strategy'

    def test_non_matching_strategy(self, strategy_service, sample_data, complex_strategy):
        """Test that non-matching strategy is not triggered."""
        complex_strategy['conditions'] = [
            {'type': 'price', 'operator': '>=', 'value': 100}  # won't match
        ]
        strategy_service.complex_strategies = [complex_strategy]
        results = strategy_service.check_all_strategies(sample_data)
        assert len(results) == 0

    def test_disabled_strategy_not_triggered(self, strategy_service, sample_data, complex_strategy):
        """Test that disabled strategy is not triggered."""
        complex_strategy['enabled'] = False
        strategy_service.complex_strategies = [complex_strategy]
        results = strategy_service.check_all_strategies(sample_data)
        assert len(results) == 0

    def test_cooldown_prevents_retrigger(self, strategy_service, sample_data, complex_strategy):
        """Test that cooldown prevents re-triggering."""
        complex_strategy['lastTriggered'] = int(time.time() * 1000)  # just now
        strategy_service.complex_strategies = [complex_strategy]
        results = strategy_service.check_all_strategies(sample_data)
        assert len(results) == 0

    def test_trigger_count_incremented(self, strategy_service, sample_data, complex_strategy):
        """Test that trigger count is incremented."""
        strategy_service.complex_strategies = [complex_strategy]
        strategy_service.check_all_strategies(sample_data)
        assert strategy_service.complex_strategies[0]['triggerCount'] == 1

    def test_trigger_result_has_actions(self, strategy_service, sample_data, complex_strategy):
        """Test that trigger result has formatted actions."""
        strategy_service.complex_strategies = [complex_strategy]
        results = strategy_service.check_all_strategies(sample_data)
        assert len(results) == 1
        assert 'actions' in results[0]
        assert len(results[0]['actions']) == 2
        assert 'formattedMessage' in results[0]['actions'][0]

    def test_trigger_result_has_data(self, strategy_service, sample_data, complex_strategy):
        """Test that trigger result has data."""
        strategy_service.complex_strategies = [complex_strategy]
        results = strategy_service.check_all_strategies(sample_data)
        assert 'data' in results[0]
        assert results[0]['data']['price'] == 55.0


# ============ Feishu Notification in Strategy Tests ============

class TestFeishuNotificationInStrategy:
    """Test _send_feishu_notification in strategy service."""

    def test_send_feishu_notification_success(self, strategy_service, sample_data, complex_strategy):
        """Test successful Feishu notification."""
        with patch('services.strategy_service._get_feishu_service') as mock_get:
            mock_feishu = MagicMock()
            mock_feishu.send_stock_alert.return_value = {'success': True}
            mock_get.return_value = mock_feishu

            strategy_service._send_feishu_notification(complex_strategy, sample_data)
            mock_feishu.send_stock_alert.assert_called_once()

    def test_send_feishu_notification_no_service(self, strategy_service, sample_data, complex_strategy):
        """Test when Feishu service is not available."""
        with patch('services.strategy_service._get_feishu_service', return_value=None):
            # Should not raise, just log a warning
            strategy_service._send_feishu_notification(complex_strategy, sample_data)

    def test_send_feishu_notification_exception(self, strategy_service, sample_data, complex_strategy):
        """Test exception handling in Feishu notification."""
        with patch('services.strategy_service._get_feishu_service', side_effect=Exception("Connection error")):
            strategy_service._send_feishu_notification(complex_strategy, sample_data)

    def test_send_feishu_high_level_detection(self, strategy_service, sample_data):
        """Test that high level is detected from conditions."""
        with patch('services.strategy_service._get_feishu_service') as mock_get:
            mock_feishu = MagicMock()
            mock_feishu.send_stock_alert.return_value = {'success': True}
            mock_get.return_value = mock_feishu

            strategy = {
                'id': 's1', 'name': 'Test',
                'conditions': [{'type': 'price', 'operator': '>', 'value': 100}],
                'actions': [{'type': 'notify_feishu'}]
            }
            strategy_service._send_feishu_notification(strategy, sample_data)
            call_kwargs = mock_feishu.send_stock_alert.call_args
            # Should detect high level
            assert call_kwargs is not None

    def test_send_feishu_notification_in_check_all(self, strategy_service, sample_data):
        """Test that check_all_strategies triggers Feishu notification."""
        strategy = {
            'id': 'feishu_test', 'name': '飞书测试', 'enabled': True,
            'logic': 'AND',
            'conditions': [{'type': 'price', 'operator': '>=', 'value': 50}],
            'actions': [{'type': 'notify_feishu', 'message': '测试'}],
            'lastTriggered': None, 'triggerCount': 0
        }
        strategy_service.complex_strategies = [strategy]

        with patch('services.strategy_service._get_feishu_service') as mock_get:
            mock_feishu = MagicMock()
            mock_feishu.send_stock_alert.return_value = {'success': True}
            mock_get.return_value = mock_feishu

            results = strategy_service.check_all_strategies(sample_data)
            assert len(results) == 1


# ============ Format Action Tests ============

class TestFormatAction:
    """Test format_action method."""

    def test_format_with_placeholders(self, strategy_service, sample_data):
        """Test formatting with data placeholders."""
        action = {'message': '价格: {price}, 涨幅: {change_pct}%'}
        result = strategy_service.format_action(action, sample_data)
        assert '55' in result
        assert '1.85' in result

    def test_format_missing_placeholder_replaced(self, strategy_service, sample_data):
        """Test that missing placeholders are replaced with N/A."""
        action = {'message': '高: {high}, 低: {low}, 放量: {volume_surge}'}
        result = strategy_service.format_action(action, sample_data)
        assert '56.0' in result  # high
        assert '53.5' in result  # low
        assert '50.0' in result  # volume_surge

    def test_format_no_placeholders(self, strategy_service, sample_data):
        """Test formatting without placeholders."""
        action = {'message': '静态消息'}
        result = strategy_service.format_action(action, sample_data)
        assert result == '静态消息'

    def test_format_empty_message(self, strategy_service, sample_data):
        """Test formatting with empty message."""
        action = {'message': ''}
        result = strategy_service.format_action(action, sample_data)
        assert result == ''


# ============ Scan By Strategy Tests ============

class TestScanByStrategy:
    """Test scan_by_strategy method."""

    def test_scan_finds_matches(self, strategy_service):
        """Test that scan finds matching stocks."""
        strategy = {
            'id': 'scan_test', 'name': '扫描测试',
            'enabled': True, 'logic': 'AND',
            'conditions': [{'type': 'price', 'operator': '>=', 'value': 50}],
            'actions': []
        }
        stocks = [
            {'symbol': 's1', 'price': 55, 'prev_close': 54, 'volume': 100},
            {'symbol': 's2', 'price': 45, 'prev_close': 50, 'volume': 200},
            {'symbol': 's3', 'price': 60, 'prev_close': 58, 'volume': 300},
        ]
        matches = strategy_service.scan_by_strategy(strategy, stocks)
        assert len(matches) == 2
        symbols = [m['symbol'] for m in matches]
        assert 's1' in symbols
        assert 's3' in symbols

    def test_scan_derived_fields(self, strategy_service):
        """Test that scan adds derived fields."""
        strategy = {
            'id': 'scan_test', 'name': '扫描测试',
            'enabled': True, 'logic': 'AND',
            'conditions': [{'type': 'change_pct', 'operator': '>', 'value': 0}],
            'actions': []
        }
        stocks = [{'symbol': 's1', 'price': 55, 'prev_close': 50, 'volume': 100}]
        matches = strategy_service.scan_by_strategy(strategy, stocks)
        assert len(matches) == 1
        assert 'chg' in matches[0]
        assert 'chg_pct' in matches[0]
        assert matches[0]['chg'] == 5.0

    def test_scan_zero_prev_close(self, strategy_service):
        """Test scan handles zero prev_close."""
        strategy = {
            'id': 'scan_test', 'name': '扫描测试',
            'enabled': True, 'logic': 'AND',
            'conditions': [{'type': 'price', 'operator': '>', 'value': 0}],
            'actions': []
        }
        stocks = [{'symbol': 's1', 'price': 55, 'prev_close': 0, 'volume': 100}]
        matches = strategy_service.scan_by_strategy(strategy, stocks)
        assert len(matches) == 1
        assert matches[0]['chg_pct'] == 0

    def test_scan_empty_stocks(self, strategy_service):
        """Test scan with empty stocks list."""
        strategy = {
            'id': 'scan_test', 'name': '扫描测试',
            'enabled': True, 'logic': 'AND',
            'conditions': [{'type': 'price', 'operator': '>', 'value': 0}],
            'actions': []
        }
        matches = strategy_service.scan_by_strategy(strategy, [])
        assert len(matches) == 0


# ============ Quick Scan Tests ============

class TestQuickScan:
    """Test quick_scan method."""

    def test_price_breakout(self, strategy_service, stock_service_mock):
        """Test price_breakout quick scan."""
        stock_service_mock.scan_market_concurrent.return_value = [{'symbol': 's1'}]
        results = strategy_service.quick_scan('price_breakout')
        assert len(results) == 1
        stock_service_mock.scan_market_concurrent.assert_called_once()

    def test_volume_surge(self, strategy_service, stock_service_mock):
        """Test volume_surge quick scan."""
        stock_service_mock.scan_market_concurrent.return_value = []
        results = strategy_service.quick_scan('volume_surge')
        assert isinstance(results, list)

    def test_oversold(self, strategy_service, stock_service_mock):
        """Test oversold quick scan."""
        stock_service_mock.scan_market_concurrent.return_value = []
        results = strategy_service.quick_scan('oversold')
        assert isinstance(results, list)

    def test_hot(self, strategy_service, stock_service_mock):
        """Test hot quick scan."""
        stock_service_mock.scan_market_concurrent.return_value = []
        results = strategy_service.quick_scan('hot')
        assert isinstance(results, list)

    def test_unknown_scan_type_raises(self, strategy_service):
        """Test unknown scan type raises ValueError."""
        with pytest.raises(ValueError, match="Unknown scan type"):
            strategy_service.quick_scan('unknown_type')


# ============ Market Scan Tests ============

class TestMarketScan:
    """Test market_scan method."""

    def test_market_scan(self, strategy_service, stock_service_mock):
        """Test market_scan delegates to stock_service."""
        stock_service_mock.scan_market_concurrent.return_value = [{'symbol': 's1'}]
        strategy = {'enabled': True, 'conditions': []}
        results = strategy_service.market_scan(strategy)
        assert len(results) == 1
        stock_service_mock.scan_market_concurrent.assert_called_once_with(strategy, 30)

    def test_market_scan_custom_batch(self, strategy_service, stock_service_mock):
        """Test market_scan with custom batch size."""
        stock_service_mock.scan_market_concurrent.return_value = []
        strategy = {'enabled': True, 'conditions': []}
        strategy_service.market_scan(strategy, batch_size=50)
        stock_service_mock.scan_market_concurrent.assert_called_once_with(strategy, 50)


# ============ Scan Watchlist Tests ============

class TestScanWatchlist:
    """Test scan_watchlist_by_strategy method."""

    def test_scan_watchlist_with_stocks(self, strategy_service, stock_service_mock):
        """Test scanning watchlist with stocks."""
        from models.stock import WatchlistItem
        mock_items = [
            WatchlistItem(symbol='sz002149', name='西部材料'),
            WatchlistItem(symbol='sh601398', name='工商银行'),
        ]
        stock_service_mock.get_watchlist.return_value = mock_items
        stock_service_mock.fetch_tencent_data.return_value = [
            {'symbol': 'sz002149', 'price': 55, 'prev_close': 54, 'volume': 100},
            {'symbol': 'sh601398', 'price': 5, 'prev_close': 5.1, 'volume': 200},
        ]

        strategy = {
            'id': 'test', 'name': '测试', 'enabled': True, 'logic': 'AND',
            'conditions': [{'type': 'price', 'operator': '>=', 'value': 50}],
            'actions': []
        }
        matches = strategy_service.scan_watchlist_by_strategy(strategy)
        assert len(matches) == 1
        assert matches[0]['symbol'] == 'sz002149'

    def test_scan_watchlist_empty(self, strategy_service, stock_service_mock):
        """Test scanning empty watchlist."""
        stock_service_mock.get_watchlist.return_value = []
        strategy = {'enabled': True, 'conditions': []}
        matches = strategy_service.scan_watchlist_by_strategy(strategy)
        assert len(matches) == 0
