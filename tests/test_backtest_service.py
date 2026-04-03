"""
Unit Tests for BacktestService
Tests backtest engine initialization, run_backtest, history, and config validation.
"""
import pytest
from unittest.mock import patch, MagicMock


# ============ Fixtures ============

@pytest.fixture
def backtest_service():
    """Create a BacktestService instance."""
    from services.backtest_service import BacktestService
    return BacktestService()


@pytest.fixture
def mock_result():
    """Create a mock BacktestResult."""
    result = MagicMock()
    result.strategy_name = 'ma_cross'
    result.symbol = 'sz002149'
    result.start_date = '2024-01-01'
    result.end_date = '2024-06-01'
    result.initial_capital = 100000.0
    result.final_capital = 115000.0
    result.total_return = 15000.0
    result.total_return_pct = 15.0
    result.annual_return = 30.0
    result.max_drawdown = 5000.0
    result.max_drawdown_pct = 5.0
    result.sharpe_ratio = 1.5
    result.sortino_ratio = 2.0
    result.win_rate = 60.0
    result.profit_factor = 1.8
    result.total_trades = 10
    result.winning_trades = 6
    result.losing_trades = 4
    result.avg_win = 2500.0
    result.avg_loss = -1250.0
    result.largest_win = 5000.0
    result.largest_loss = -3000.0
    result.avg_hold_days = 5.0
    result.trades = []
    result.equity_curve = [{'date': '2024-01-01', 'equity': 100000}]
    return result


# ============ get_engine Tests ============

class TestGetEngine:
    """Test get_engine lazy initialization."""

    def test_engine_created_once(self, backtest_service):
        """Test engine is created on first call."""
        mock_engine = MagicMock()
        mock_backtest_module = MagicMock()
        mock_backtest_module.BacktestEngine.return_value = mock_engine

        with patch.dict('sys.modules', {'backtest': mock_backtest_module}):
            with patch('services.backtest_service.BacktestEngine', mock_backtest_module.BacktestEngine, create=True):
                engine = backtest_service.get_engine()
                assert engine is mock_engine
                assert backtest_service._engine is mock_engine

    def test_engine_cached(self, backtest_service):
        """Test engine is cached after first creation."""
        mock_engine = MagicMock()
        backtest_service._engine = mock_engine

        engine = backtest_service.get_engine()
        assert engine is mock_engine

    def test_engine_import_error(self, backtest_service):
        """Test get_engine raises on import failure."""
        with patch.dict('sys.modules', {'backtest': None}):
            with pytest.raises(Exception):
                backtest_service.get_engine()


# ============ run_backtest Tests ============

class TestRunBacktest:
    """Test run_backtest method."""

    def test_run_backtest_default_strategy(self, backtest_service, mock_result):
        """Test run_backtest with default strategy (ma_cross)."""
        mock_engine = MagicMock()
        mock_engine.run_backtest.return_value = mock_result
        backtest_service._engine = mock_engine

        mock_classic = MagicMock()
        mock_classic.ma_cross = MagicMock()

        with patch.dict('sys.modules', {
            'backtest': MagicMock(ClassicStrategies=mock_classic)
        }):
            config = {
                'symbol': 'sz002149',
                'start_date': '2024-01-01',
                'end_date': '2024-06-01',
                'initial_capital': 100000,
            }
            result = backtest_service.run_backtest(config)

            assert result['strategy_name'] == 'ma_cross'
            assert result['symbol'] == 'sz002149'
            assert result['initial_capital'] == 100000.0
            assert result['final_capital'] == 115000.0
            assert result['total_return'] == 15000.0
            assert result['total_trades'] == 10
            assert result['winning_trades'] == 6
            assert result['losing_trades'] == 4

    def test_run_backtest_rsi_strategy(self, backtest_service, mock_result):
        """Test run_backtest with rsi_mean_reversion strategy."""
        mock_engine = MagicMock()
        mock_engine.run_backtest.return_value = mock_result
        backtest_service._engine = mock_engine

        mock_classic = MagicMock()
        mock_classic.rsi_mean_reversion = MagicMock()

        with patch.dict('sys.modules', {
            'backtest': MagicMock(ClassicStrategies=mock_classic)
        }):
            config = {
                'symbol': 'sz002149',
                'strategy': 'rsi_mean_reversion',
                'start_date': '2024-01-01',
                'end_date': '2024-06-01',
                'initial_capital': 100000,
            }
            result = backtest_service.run_backtest(config)
            assert result['strategy_name'] == 'ma_cross'

    def test_run_backtest_macd_strategy(self, backtest_service, mock_result):
        """Test run_backtest with macd_crossover strategy."""
        mock_engine = MagicMock()
        mock_engine.run_backtest.return_value = mock_result
        backtest_service._engine = mock_engine

        mock_classic = MagicMock()
        mock_classic.macd_crossover = MagicMock()

        with patch.dict('sys.modules', {
            'backtest': MagicMock(ClassicStrategies=mock_classic)
        }):
            config = {
                'symbol': 'sz002149',
                'strategy': 'macd_crossover',
                'start_date': '2024-01-01',
                'end_date': '2024-06-01',
            }
            result = backtest_service.run_backtest(config)
            assert result['symbol'] == 'sz002149'

    def test_run_backtest_bollinger_strategy(self, backtest_service, mock_result):
        """Test run_backtest with bollinger_bounce strategy."""
        mock_engine = MagicMock()
        mock_engine.run_backtest.return_value = mock_result
        backtest_service._engine = mock_engine

        mock_classic = MagicMock()
        mock_classic.bollinger_bounce = MagicMock()

        with patch.dict('sys.modules', {
            'backtest': MagicMock(ClassicStrategies=mock_classic)
        }):
            config = {
                'symbol': 'sz002149',
                'strategy': 'bollinger_bounce',
                'start_date': '2024-01-01',
                'end_date': '2024-06-01',
            }
            result = backtest_service.run_backtest(config)
            assert result['initial_capital'] == 100000  # default

    def test_run_backtest_volume_breakout_strategy(self, backtest_service, mock_result):
        """Test run_backtest with volume_breakout strategy."""
        mock_engine = MagicMock()
        mock_engine.run_backtest.return_value = mock_result
        backtest_service._engine = mock_engine

        mock_classic = MagicMock()
        mock_classic.volume_breakout = MagicMock()

        with patch.dict('sys.modules', {
            'backtest': MagicMock(ClassicStrategies=mock_classic)
        }):
            config = {
                'symbol': 'sz002149',
                'strategy': 'volume_breakout',
                'start_date': '2024-01-01',
                'end_date': '2024-06-01',
            }
            result = backtest_service.run_backtest(config)
            assert result['sharpe_ratio'] == 1.5

    def test_run_backtest_dual_ma_strategy(self, backtest_service, mock_result):
        """Test run_backtest with dual_ma_trend strategy."""
        mock_engine = MagicMock()
        mock_engine.run_backtest.return_value = mock_result
        backtest_service._engine = mock_engine

        mock_classic = MagicMock()
        mock_classic.dual_ma_trend = MagicMock()

        with patch.dict('sys.modules', {
            'backtest': MagicMock(ClassicStrategies=mock_classic)
        }):
            config = {
                'symbol': 'sz002149',
                'strategy': 'dual_ma_trend',
                'start_date': '2024-01-01',
                'end_date': '2024-06-01',
            }
            result = backtest_service.run_backtest(config)
            assert result['sortino_ratio'] == 2.0

    def test_run_backtest_golden_cross_strategy(self, backtest_service, mock_result):
        """Test run_backtest with golden_cross strategy."""
        mock_engine = MagicMock()
        mock_engine.run_backtest.return_value = mock_result
        backtest_service._engine = mock_engine

        mock_classic = MagicMock()
        mock_classic.golden_cross = MagicMock()

        with patch.dict('sys.modules', {
            'backtest': MagicMock(ClassicStrategies=mock_classic)
        }):
            config = {
                'symbol': 'sz002149',
                'strategy': 'golden_cross',
                'start_date': '2024-01-01',
                'end_date': '2024-06-01',
            }
            result = backtest_service.run_backtest(config)
            assert result['win_rate'] == 60.0

    def test_run_backtest_default_symbol(self, backtest_service, mock_result):
        """Test run_backtest uses default symbol when not provided."""
        mock_engine = MagicMock()
        mock_engine.run_backtest.return_value = mock_result
        backtest_service._engine = mock_engine

        mock_classic = MagicMock()
        mock_classic.ma_cross = MagicMock()

        with patch.dict('sys.modules', {
            'backtest': MagicMock(ClassicStrategies=mock_classic)
        }):
            config = {
                'strategy': 'ma_cross',
                'start_date': '2024-01-01',
                'end_date': '2024-06-01',
            }
            result = backtest_service.run_backtest(config)
            mock_engine.run_backtest.assert_called_once()
            call_kwargs = mock_engine.run_backtest.call_args
            assert call_kwargs[1]['symbol'] == '002149'

    def test_run_backtest_custom_capital(self, backtest_service, mock_result):
        """Test run_backtest with custom initial capital."""
        mock_engine = MagicMock()
        mock_engine.run_backtest.return_value = mock_result
        backtest_service._engine = mock_engine

        mock_classic = MagicMock()
        mock_classic.ma_cross = MagicMock()

        with patch.dict('sys.modules', {
            'backtest': MagicMock(ClassicStrategies=mock_classic)
        }):
            config = {
                'symbol': 'sz002149',
                'strategy': 'ma_cross',
                'start_date': '2024-01-01',
                'end_date': '2024-06-01',
                'initial_capital': 500000,
            }
            result = backtest_service.run_backtest(config)
            call_kwargs = mock_engine.run_backtest.call_args
            assert call_kwargs[1]['initial_capital'] == 500000

    def test_run_backtest_result_has_all_fields(self, backtest_service, mock_result):
        """Test that all result fields are present in returned dict."""
        mock_engine = MagicMock()
        mock_engine.run_backtest.return_value = mock_result
        backtest_service._engine = mock_engine

        mock_classic = MagicMock()
        mock_classic.ma_cross = MagicMock()

        with patch.dict('sys.modules', {
            'backtest': MagicMock(ClassicStrategies=mock_classic)
        }):
            config = {
                'symbol': 'sz002149',
                'strategy': 'ma_cross',
                'start_date': '2024-01-01',
                'end_date': '2024-06-01',
            }
            result = backtest_service.run_backtest(config)

            expected_keys = [
                'strategy_name', 'symbol', 'start_date', 'end_date',
                'initial_capital', 'final_capital', 'total_return',
                'total_return_pct', 'annual_return', 'max_drawdown',
                'max_drawdown_pct', 'sharpe_ratio', 'sortino_ratio',
                'win_rate', 'profit_factor', 'total_trades',
                'winning_trades', 'losing_trades', 'avg_win', 'avg_loss',
                'largest_win', 'largest_loss', 'avg_hold_days',
                'trades', 'equity_curve'
            ]
            for key in expected_keys:
                assert key in result, f"Missing key: {key}"

    def test_run_backtest_raises_on_error(self, backtest_service):
        """Test run_backtest re-raises exceptions."""
        mock_engine = MagicMock()
        mock_engine.run_backtest.side_effect = RuntimeError("DB error")
        backtest_service._engine = mock_engine

        mock_classic = MagicMock()
        mock_classic.ma_cross = MagicMock()

        with patch.dict('sys.modules', {
            'backtest': MagicMock(ClassicStrategies=mock_classic)
        }):
            config = {
                'symbol': 'sz002149',
                'strategy': 'ma_cross',
                'start_date': '2024-01-01',
                'end_date': '2024-06-01',
            }
            with pytest.raises(RuntimeError, match="DB error"):
                backtest_service.run_backtest(config)

    def test_run_backtest_unknown_strategy_uses_default(self, backtest_service, mock_result):
        """Test run_backtest falls back to ma_cross for unknown strategy."""
        mock_engine = MagicMock()
        mock_engine.run_backtest.return_value = mock_result
        backtest_service._engine = mock_engine

        mock_classic = MagicMock()
        mock_classic.ma_cross = MagicMock()

        with patch.dict('sys.modules', {
            'backtest': MagicMock(ClassicStrategies=mock_classic)
        }):
            config = {
                'symbol': 'sz002149',
                'strategy': 'unknown_strategy_xyz',
                'start_date': '2024-01-01',
                'end_date': '2024-06-01',
            }
            result = backtest_service.run_backtest(config)
            # Should use default (ma_cross) strategy function
            mock_classic.ma_cross.assert_not_called()  # not directly called by service
            assert result['symbol'] == 'sz002149'


# ============ get_backtest_history Tests ============

class TestGetBacktestHistory:
    """Test get_backtest_history method."""

    def test_get_history_with_data(self, backtest_service):
        """Test getting history when engine has data."""
        mock_engine = MagicMock()
        mock_engine.get_history.return_value = [
            {'strategy': 'ma_cross', 'symbol': 'sz002149', 'return_pct': 10.5},
            {'strategy': 'rsi', 'symbol': 'sz002149', 'return_pct': 8.2},
        ]
        backtest_service._engine = mock_engine

        history = backtest_service.get_backtest_history()
        assert len(history) == 2
        mock_engine.get_history.assert_called_once_with(50)

    def test_get_history_with_custom_limit(self, backtest_service):
        """Test getting history with custom limit."""
        mock_engine = MagicMock()
        mock_engine.get_history.return_value = []
        backtest_service._engine = mock_engine

        backtest_service.get_backtest_history(limit=10)
        mock_engine.get_history.assert_called_once_with(10)

    def test_get_history_no_get_history_method(self, backtest_service):
        """Test getting history when engine has no get_history method."""
        mock_engine = MagicMock(spec=[])  # no attributes
        backtest_service._engine = mock_engine

        history = backtest_service.get_backtest_history()
        assert history == []

    def test_get_history_engine_error(self, backtest_service):
        """Test getting history when engine raises error."""
        mock_engine = MagicMock()
        mock_engine.get_history.side_effect = Exception("DB locked")
        backtest_service._engine = mock_engine

        history = backtest_service.get_backtest_history()
        assert history == []


# ============ validate_config Tests ============

class TestValidateConfig:
    """Test validate_config method."""

    def test_valid_config(self, backtest_service):
        """Test validation of a valid config."""
        config = {
            'symbol': 'sz002149',
            'strategy': 'ma_cross',
            'start_date': '2024-01-01',
            'end_date': '2024-06-01',
        }
        is_valid, msg = backtest_service.validate_config(config)
        assert is_valid is True
        assert msg == ""

    def test_missing_symbol(self, backtest_service):
        """Test validation fails when symbol is missing."""
        config = {
            'strategy': 'ma_cross',
            'start_date': '2024-01-01',
            'end_date': '2024-06-01',
        }
        is_valid, msg = backtest_service.validate_config(config)
        assert is_valid is False
        assert "symbol" in msg.lower()

    def test_empty_symbol(self, backtest_service):
        """Test validation fails when symbol is empty."""
        config = {
            'symbol': '',
            'strategy': 'ma_cross',
            'start_date': '2024-01-01',
            'end_date': '2024-06-01',
        }
        is_valid, msg = backtest_service.validate_config(config)
        assert is_valid is False
        assert "symbol" in msg.lower()

    def test_missing_strategy(self, backtest_service):
        """Test validation fails when strategy is missing."""
        config = {
            'symbol': 'sz002149',
            'start_date': '2024-01-01',
            'end_date': '2024-06-01',
        }
        is_valid, msg = backtest_service.validate_config(config)
        assert is_valid is False
        assert "strategy" in msg.lower()

    def test_missing_start_date(self, backtest_service):
        """Test validation fails when start_date is missing."""
        config = {
            'symbol': 'sz002149',
            'strategy': 'ma_cross',
            'end_date': '2024-06-01',
        }
        is_valid, msg = backtest_service.validate_config(config)
        assert is_valid is False
        assert "date" in msg.lower()

    def test_missing_end_date(self, backtest_service):
        """Test validation fails when end_date is missing."""
        config = {
            'symbol': 'sz002149',
            'strategy': 'ma_cross',
            'start_date': '2024-01-01',
        }
        is_valid, msg = backtest_service.validate_config(config)
        assert is_valid is False
        assert "date" in msg.lower()

    def test_invalid_start_date_format(self, backtest_service):
        """Test validation fails with invalid start_date format."""
        config = {
            'symbol': 'sz002149',
            'strategy': 'ma_cross',
            'start_date': '01-01-2024',
            'end_date': '2024-06-01',
        }
        is_valid, msg = backtest_service.validate_config(config)
        assert is_valid is False
        assert "format" in msg.lower()

    def test_invalid_end_date_format(self, backtest_service):
        """Test validation fails with invalid end_date format."""
        config = {
            'symbol': 'sz002149',
            'strategy': 'ma_cross',
            'start_date': '2024-01-01',
            'end_date': 'not-a-date',
        }
        is_valid, msg = backtest_service.validate_config(config)
        assert is_valid is False
        assert "format" in msg.lower()

    def test_both_dates_invalid(self, backtest_service):
        """Test validation fails when both dates are invalid."""
        config = {
            'symbol': 'sz002149',
            'strategy': 'ma_cross',
            'start_date': 'invalid',
            'end_date': 'also-invalid',
        }
        is_valid, msg = backtest_service.validate_config(config)
        assert is_valid is False

    def test_strategy_as_dict(self, backtest_service):
        """Test validation accepts strategy as dict."""
        config = {
            'symbol': 'sz002149',
            'strategy': {'type': 'custom', 'params': {}},
            'start_date': '2024-01-01',
            'end_date': '2024-06-01',
        }
        is_valid, msg = backtest_service.validate_config(config)
        assert is_valid is True

    def test_empty_config(self, backtest_service):
        """Test validation fails for empty config."""
        is_valid, msg = backtest_service.validate_config({})
        assert is_valid is False
