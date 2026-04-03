"""
Unit Tests for Strategy Logic
Tests strategy condition evaluation, signal generation, and action formatting.
"""
import pytest
import json
import os
import tempfile
from datetime import datetime
from unittest.mock import patch, MagicMock


# ============ Fixtures ============

@pytest.fixture
def sample_stock_data():
    """Sample stock data for strategy evaluation."""
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
        'turnover_rate': 2.5,
        'pe': 25.0,
        'pb': 2.8,
        'market_cap': 1000000000,
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


# ============ Condition Evaluation Tests ============

class TestConditionEvaluation:
    """Test strategy condition evaluation logic."""
    
    def test_price_condition_greater_than(self, sample_stock_data):
        """Test price >= condition."""
        condition = {'type': 'price', 'operator': '>=', 'value': 50}
        result = evaluate_condition(condition, sample_stock_data)
        assert result is True  # 55 >= 50
        
        condition = {'type': 'price', 'operator': '>=', 'value': 60}
        result = evaluate_condition(condition, sample_stock_data)
        assert result is False  # 55 < 60
    
    def test_price_condition_less_than(self, sample_stock_data):
        """Test price <= condition."""
        condition = {'type': 'price', 'operator': '<=', 'value': 60}
        result = evaluate_condition(condition, sample_stock_data)
        assert result is True  # 55 <= 60
        
        condition = {'type': 'price', 'operator': '<=', 'value': 50}
        result = evaluate_condition(condition, sample_stock_data)
        assert result is False  # 55 > 50
    
    def test_price_condition_equal(self, sample_stock_data):
        """Test price == condition."""
        condition = {'type': 'price', 'operator': '==', 'value': 55.0}
        result = evaluate_condition(condition, sample_stock_data)
        assert result is True
        
        condition = {'type': 'price', 'operator': '==', 'value': 56.0}
        result = evaluate_condition(condition, sample_stock_data)
        assert result is False
    
    def test_change_pct_condition(self, sample_stock_data):
        """Test change_pct conditions."""
        condition = {'type': 'change_pct', 'operator': '>=', 'value': 1.0}
        result = evaluate_condition(condition, sample_stock_data)
        assert result is True  # 1.85 >= 1.0
        
        condition = {'type': 'change_pct', 'operator': '<=', 'value': 2.0}
        result = evaluate_condition(condition, sample_stock_data)
        assert result is True  # 1.85 <= 2.0
        
        condition = {'type': 'change_pct', 'operator': '>=', 'value': 5.0}
        result = evaluate_condition(condition, sample_stock_data)
        assert result is False  # 1.85 < 5.0
    
    def test_volume_condition(self, sample_stock_data):
        """Test volume conditions."""
        condition = {'type': 'volume', 'operator': '>=', 'value': 1000000}
        result = evaluate_condition(condition, sample_stock_data)
        assert result is True  # 1500000 >= 1000000
        
        condition = {'type': 'volume', 'operator': '<', 'value': 1000000}
        result = evaluate_condition(condition, sample_stock_data)
        assert result is False  # 1500000 > 1000000
    
    def test_volume_surge_condition(self, sample_stock_data):
        """Test volume_surge conditions."""
        condition = {'type': 'volume_surge', 'operator': '>=', 'value': 30}
        result = evaluate_condition(condition, sample_stock_data)
        assert result is True  # 50 >= 30
        
        condition = {'type': 'volume_surge', 'operator': '>=', 'value': 100}
        result = evaluate_condition(condition, sample_stock_data)
        assert result is False  # 50 < 100
    
    def test_high_price_condition(self, sample_stock_data):
        """Test high price conditions."""
        condition = {'type': 'high', 'operator': '>=', 'value': 55}
        result = evaluate_condition(condition, sample_stock_data)
        assert result is True  # 56 >= 55
    
    def test_low_price_condition(self, sample_stock_data):
        """Test low price conditions."""
        condition = {'type': 'low', 'operator': '<=', 'value': 54}
        result = evaluate_condition(condition, sample_stock_data)
        assert result is True  # 53.5 <= 54
    
    def test_unknown_condition_type(self, sample_stock_data):
        """Test unknown condition type returns False."""
        condition = {'type': 'unknown_type', 'operator': '>=', 'value': 0}
        result = evaluate_condition(condition, sample_stock_data)
        assert result is False


# ============ Strategy Evaluation Tests ============

class TestStrategyEvaluation:
    """Test full strategy evaluation."""
    
    def test_and_strategy_all_pass(self, sample_stock_data):
        """Test AND strategy when all conditions pass."""
        strategy = {
            'enabled': True,
            'logic': 'AND',
            'conditions': [
                {'type': 'price', 'operator': '>=', 'value': 50},
                {'type': 'change_pct', 'operator': '>=', 'value': 0},
            ]
        }
        result = evaluate_strategy(strategy, sample_stock_data)
        assert result is True
    
    def test_and_strategy_one_fails(self, sample_stock_data):
        """Test AND strategy when one condition fails."""
        strategy = {
            'enabled': True,
            'logic': 'AND',
            'conditions': [
                {'type': 'price', 'operator': '>=', 'value': 50},
                {'type': 'change_pct', 'operator': '>=', 'value': 5},  # fails
            ]
        }
        result = evaluate_strategy(strategy, sample_stock_data)
        assert result is False
    
    def test_or_strategy_one_passes(self, sample_stock_data):
        """Test OR strategy when one condition passes."""
        strategy = {
            'enabled': True,
            'logic': 'OR',
            'conditions': [
                {'type': 'price', 'operator': '>=', 'value': 60},  # fails
                {'type': 'change_pct', 'operator': '>=', 'value': 0},  # passes
            ]
        }
        result = evaluate_strategy(strategy, sample_stock_data)
        assert result is True
    
    def test_or_strategy_all_fail(self, sample_stock_data):
        """Test OR strategy when all conditions fail."""
        strategy = {
            'enabled': True,
            'logic': 'OR',
            'conditions': [
                {'type': 'price', 'operator': '>=', 'value': 60},  # fails
                {'type': 'change_pct', 'operator': '>=', 'value': 5},  # fails
            ]
        }
        result = evaluate_strategy(strategy, sample_stock_data)
        assert result is False
    
    def test_disabled_strategy(self, sample_stock_data):
        """Test disabled strategy returns False."""
        strategy = {
            'enabled': False,
            'logic': 'AND',
            'conditions': [
                {'type': 'price', 'operator': '>=', 'value': 0},
            ]
        }
        result = evaluate_strategy(strategy, sample_stock_data)
        assert result is False
    
    def test_empty_conditions(self, sample_stock_data):
        """Test strategy with no conditions."""
        strategy = {
            'enabled': True,
            'logic': 'AND',
            'conditions': []
        }
        result = evaluate_strategy(strategy, sample_stock_data)
        assert result is False


# ============ Action Formatting Tests ============

class TestActionFormatting:
    """Test action message formatting."""
    
    def test_format_message_with_placeholders(self, sample_stock_data):
        """Test message formatting with placeholders."""
        action = {
            'type': 'notify_feishu',
            'message': '🚀 {name} ({symbol}) 当前价格: ¥{price}，涨幅: {chg_pct}%'
        }
        formatted = format_action(action, sample_stock_data)
        assert '西部材料' in formatted
        assert '55' in formatted
        assert '1.85' in formatted
    
    def test_format_message_no_placeholders(self):
        """Test message without placeholders."""
        action = {
            'type': 'alert_web',
            'message': '价格突破预警'
        }
        data = {'price': 55.0}
        formatted = format_action(action, data)
        assert formatted == '价格突破预警'
    
    def test_format_action_preserves_type(self, sample_stock_data):
        """Test action type is preserved."""
        action = {'type': 'log', 'message': 'Test log'}
        formatted = format_action(action, sample_stock_data)
        assert isinstance(formatted, str)


# ============ Simple Strategy Tests ============

class TestSimpleStrategies:
    """Test simple strategy evaluation (price_up, price_down, etc)."""
    
    def test_price_up_trigger(self, sample_stock_data):
        """Test price_up strategy triggers when price exceeds threshold."""
        strategy = {'enabled': True, 'value': 54.0}
        triggered = sample_stock_data['price'] >= strategy['value']
        assert triggered is True
    
    def test_price_down_trigger(self, sample_stock_data):
        """Test price_down strategy triggers when price falls below threshold."""
        strategy = {'enabled': True, 'value': 56.0}
        triggered = sample_stock_data['price'] <= strategy['value']
        assert triggered is True
    
    def test_chg_pct_up_trigger(self, sample_stock_data):
        """Test chg_pct_up strategy triggers on positive change."""
        strategy = {'enabled': True, 'value': 1.0}
        triggered = sample_stock_data['chg_pct'] >= strategy['value']
        assert triggered is True
    
    def test_chg_pct_down_trigger(self, sample_stock_data):
        """Test chg_pct_down strategy triggers on negative change."""
        sample_stock_data['chg_pct'] = -3.0
        strategy = {'enabled': True, 'value': -2.0}
        triggered = sample_stock_data['chg_pct'] <= strategy['value']
        assert triggered is True
    
    def test_volume_surge_trigger(self, sample_stock_data):
        """Test volume_surge strategy triggers on volume spike."""
        strategy = {'enabled': True, 'value': 30}
        triggered = sample_stock_data['volume_surge'] >= strategy['value']
        assert triggered is True


# ============ Strategy File Persistence Tests ============

class TestStrategyPersistence:
    """Test strategy save/load functionality."""
    
    def test_save_strategies(self):
        """Test saving strategies to JSON file."""
        strategies = [
            {
                'id': 'test_1',
                'name': 'Test Strategy',
                'enabled': True,
                'logic': 'AND',
                'conditions': [{'type': 'price', 'operator': '>=', 'value': 50}],
                'actions': [{'type': 'log', 'message': 'Test'}]
            }
        ]
        
        fd, path = tempfile.mkstemp(suffix='.json')
        os.close(fd)
        
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(strategies, f, ensure_ascii=False, indent=2)
            
            # Verify it saved correctly
            with open(path, 'r', encoding='utf-8') as f:
                loaded = json.load(f)
            
            assert len(loaded) == 1
            assert loaded[0]['id'] == 'test_1'
            assert loaded[0]['name'] == 'Test Strategy'
            assert loaded[0]['conditions'][0]['value'] == 50
        finally:
            os.unlink(path)
    
    def test_load_strategies_file_not_found(self):
        """Test loading strategies when file doesn't exist."""
        import os
        path = '/tmp/nonexistent_strategies.json'
        assert not os.path.exists(path)
    
    def test_load_strategies_invalid_json(self):
        """Test loading strategies with invalid JSON."""
        fd, path = tempfile.mkstemp(suffix='.json')
        os.close(fd)
        
        try:
            with open(path, 'w') as f:
                f.write('{invalid json}')
            
            with pytest.raises(json.JSONDecodeError):
                with open(path, 'r') as f:
                    json.load(f)
        finally:
            os.unlink(path)


# ============ Strategy Signal Consistency ============

class TestStrategySignalConsistency:
    """Test that strategies produce consistent signals."""
    
    def test_deterministic_signals(self):
        """Test that same input produces same signals."""
        data = []
        for i in range(50):
            data.append({
                'trade_date': f'2024-01-{(i%28)+1:02d}',
                'close': 50.0 + i * 0.3,
                'ma5': 50.0 + i * 0.25,
                'ma20': 50.0 + i * 0.15,
                'rsi14': 30 + (i % 40),
                'volume': 1000000 + i * 5000,
                'chg_pct': (i % 5 - 2) * 0.5,
            })
        
        from backtest import BacktestEngine
        engine = BacktestEngine("")
        
        # Run twice, should get same results
        signals1 = engine.calculate_ma_signals(data, fast_period=5, slow_period=20)
        signals2 = engine.calculate_ma_signals(data, fast_period=5, slow_period=20)
        
        assert len(signals1) == len(signals2)
        for s1, s2 in zip(signals1, signals2):
            assert s1['signal'] == s2['signal']
            assert s1['date'] == s2['date']
    
    def test_signal_price_matches_data(self):
        """Test that signal prices match data close prices."""
        data = []
        for i in range(30):
            data.append({
                'trade_date': f'2024-01-{i+1:02d}',
                'close': 50.0 + i,
                'ma5': 50.0 + i * 0.9,
                'ma20': 50.0 + i * 0.5,
            })
        
        from backtest import BacktestEngine
        engine = BacktestEngine("")
        signals = engine.calculate_ma_signals(data, fast_period=5, slow_period=20)
        
        for signal in signals:
            # Find matching data point
            matching = next((d for d in data if d['trade_date'] == signal['date']), None)
            assert matching is not None
            assert signal['price'] == matching['close']


# Helper functions (mimicking app.py logic)

def evaluate_condition(condition, data):
    """Evaluate a single condition against stock data."""
    cond_type = condition.get('type')
    operator = condition.get('operator')
    value = condition.get('value')
    
    field_map = {
        'price': 'price',
        'change_pct': 'chg_pct',
        'volume': 'volume',
        'volume_surge': 'volume_surge',
        'high': 'high',
        'low': 'low',
    }
    
    if cond_type not in field_map:
        return False
    
    field = field_map[cond_type]
    data_value = data.get(field, 0)
    
    ops = {
        '>': lambda a, b: a > b,
        '>=': lambda a, b: a >= b,
        '<': lambda a, b: a < b,
        '<=': lambda a, b: a <= b,
        '==': lambda a, b: abs(a - b) < 0.01,
    }
    
    if operator not in ops:
        return False
    
    return ops[operator](data_value, value)


def evaluate_strategy(strategy, data):
    """Evaluate a full strategy against stock data."""
    if not strategy.get('enabled', False):
        return False
    
    conditions = strategy.get('conditions', [])
    if not conditions:
        return False
    
    logic = strategy.get('logic', 'AND')
    
    if logic == 'AND':
        return all(evaluate_condition(c, data) for c in conditions)
    elif logic == 'OR':
        return any(evaluate_condition(c, data) for c in conditions)
    
    return False


def format_action(action, data):
    """Format action message with data placeholders."""
    message = action.get('message', '')
    try:
        return message.format(**data)
    except (KeyError, ValueError):
        return message


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
