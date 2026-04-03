"""
Unit Tests for Backtest Engine
Tests backtest strategies, signal calculation, and metrics computation.
"""
import pytest
import sqlite3
import os
import tempfile
from datetime import datetime, timedelta
from backtest import (
    BacktestEngine, ClassicStrategies, Signal, BacktestResult,
    Trade, RiskMetrics, generate_report
)


# ============ Fixtures ============

@pytest.fixture
def temp_db():
    """Create a temporary SQLite database with test K-line data."""
    fd, db_path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Create kline_daily table
    cursor.execute('''
        CREATE TABLE kline_daily (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            trade_date TEXT NOT NULL,
            open REAL NOT NULL,
            close REAL NOT NULL,
            high REAL NOT NULL,
            low REAL NOT NULL,
            volume REAL,
            amount REAL,
            chg REAL,
            chg_pct REAL,
            ma5 REAL,
            ma10 REAL,
            ma20 REAL,
            ma60 REAL,
            rsi14 REAL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(symbol, trade_date)
        )
    ''')
    
    # Generate 100 days of test data (uptrend with noise)
    base_price = 50.0
    for i in range(100):
        date = (datetime(2024, 1, 1) + timedelta(days=i)).strftime('%Y-%m-%d')
        daily_change = (i % 7 - 3) * 0.5  # some variation
        close_price = base_price + i * 0.3 + daily_change
        open_price = close_price - daily_change * 0.5
        high_price = max(close_price, open_price) + abs(daily_change) * 0.3
        low_price = min(close_price, open_price) - abs(daily_change) * 0.3
        volume = 1000000 + i * 10000 + (i % 5) * 50000
        chg = daily_change
        chg_pct = (chg / (close_price - chg)) * 100 if (close_price - chg) > 0 else 0
        
        # Calculate MA values
        ma5 = close_price if i < 4 else sum([base_price + (i-j) * 0.3 for j in range(5)]) / 5
        ma10 = close_price if i < 9 else sum([base_price + (i-j) * 0.3 for j in range(10)]) / 10
        ma20 = close_price if i < 19 else sum([base_price + (i-j) * 0.3 for j in range(20)]) / 20
        ma60 = close_price if i < 59 else sum([base_price + (i-j) * 0.3 for j in range(60)]) / 60
        
        # RSI (simplified)
        rsi14 = 50 + (i % 30 - 15)
        
        cursor.execute('''
            INSERT INTO kline_daily 
            (symbol, trade_date, open, close, high, low, volume, amount, chg, chg_pct, ma5, ma10, ma20, ma60, rsi14)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', ('sz002149', date, open_price, close_price, high_price, low_price,
              volume, volume * close_price, chg, chg_pct, ma5, ma10, ma20, ma60, rsi14))
    
    conn.commit()
    conn.close()
    
    yield db_path
    
    # Cleanup
    os.unlink(db_path)


@pytest.fixture
def engine(temp_db):
    """Create a BacktestEngine instance with test database."""
    return BacktestEngine(temp_db)


@pytest.fixture
def sample_data():
    """Generate sample data for signal calculation tests."""
    data = []
    for i in range(50):
        data.append({
            'trade_date': f'2024-{(i//30)+1:02d}-{(i%30)+1:02d}',
            'close': 50.0 + i * 0.5,
            'volume': 1000000 + i * 10000,
            'chg_pct': (i % 7 - 3) * 0.5,
            'ma5': 50.0 + (i - 2) * 0.5 if i >= 4 else 50.0 + i * 0.5,
            'ma10': 50.0 + (i - 5) * 0.5 if i >= 9 else 50.0 + i * 0.5,
            'ma20': 50.0 + (i - 10) * 0.5 if i >= 19 else 50.0 + i * 0.5,
            'rsi14': 30 + (i % 50),
        })
    return data


# ============ Signal Calculation Tests ============

class TestSignalCalculation:
    """Test signal generation methods."""
    
    def test_ma_cross_signals_golden_cross(self, sample_data):
        """Test MA golden cross generates BUY signal."""
        # Modify data to create a golden cross
        data = sample_data[:25]
        # Force ma5 to cross above ma20
        for i in range(20, 25):
            data[i]['ma5'] = data[i]['ma20'] + 1.0
        
        engine = BacktestEngine("")
        signals = engine.calculate_ma_signals(data, fast_period=5, slow_period=20)
        
        # Should have signals for each day after first
        assert len(signals) == len(data)
        
        # Check there's at least one BUY signal around the cross
        buy_signals = [s for s in signals if s['signal'] == Signal.BUY]
        assert len(buy_signals) > 0
    
    def test_ma_cross_signals_death_cross(self, sample_data):
        """Test MA death cross generates SELL signal."""
        data = sample_data[:25]
        # Force ma5 to cross below ma20
        for i in range(20):
            data[i]['ma5'] = data[i]['ma20'] + 2.0
        for i in range(20, 25):
            data[i]['ma5'] = data[i]['ma20'] - 1.0
        
        engine = BacktestEngine("")
        signals = engine.calculate_ma_signals(data, fast_period=5, slow_period=20)
        
        sell_signals = [s for s in signals if s['signal'] == Signal.SELL]
        assert len(sell_signals) > 0
    
    def test_rsi_signals_oversold(self, sample_data):
        """Test RSI oversold generates BUY signal."""
        data = sample_data[:25]
        # Create oversold condition
        for i in range(20, 25):
            data[i]['rsi14'] = 25  # below 30
        for i in range(19, 20):
            data[i]['rsi14'] = 35  # above 30
        
        engine = BacktestEngine("")
        signals = engine.calculate_rsi_signals(data, oversold=30, overbought=70)
        
        buy_signals = [s for s in signals if s['signal'] == Signal.BUY]
        assert len(buy_signals) > 0
    
    def test_rsi_signals_overbought(self, sample_data):
        """Test RSI overbought generates SELL signal."""
        data = sample_data[:25]
        # RSI needs to cross from above 70 to below 70 for SELL
        # Set up: prev_rsi >= 70, curr_rsi < 70
        for i in range(18, 20):
            data[i]['rsi14'] = 75  # above 70 (prev)
        data[20]['rsi14'] = 65  # below 70 (curr, triggers SELL)
        for i in range(21, 25):
            data[i]['rsi14'] = 75  # back above
        
        engine = BacktestEngine("")
        signals = engine.calculate_rsi_signals(data, oversold=30, overbought=70)
        
        sell_signals = [s for s in signals if s['signal'] == Signal.SELL]
        # Should have a SELL signal at the crossover point
        assert len(sell_signals) > 0
    
    def test_bollinger_signals_bounce(self, sample_data):
        """Test Bollinger bounce generates BUY signal at lower band."""
        data = sample_data[:30]
        # Create consistent prices then a drop
        for i in range(20):
            data[i]['close'] = 50.0
        data[20]['close'] = 45.0  # below lower band
        
        engine = BacktestEngine("")
        signals = engine.calculate_bollinger_signals(data, period=20, std_dev=2.0)
        
        buy_signals = [s for s in signals if s['signal'] == Signal.BUY]
        assert len(buy_signals) > 0
    
    def test_macd_signals(self, sample_data):
        """Test MACD generates signals on crossover."""
        # Need enough data for MACD calculation
        data = sample_data[:50]
        engine = BacktestEngine("")
        signals = engine.calculate_macd_signals(data)
        
        assert len(signals) == len(data) - 1  # non-vectorized MACD starts from index 1
        # Should have some signals (HOLD or otherwise)
        assert all('signal' in s for s in signals)
    
    def test_volume_breakout_signals(self, sample_data):
        """Test volume breakout generates BUY on high volume up."""
        data = sample_data[:30]
        # Create normal volume then a spike
        for i in range(20):
            data[i]['volume'] = 1000000
        data[20]['volume'] = 3000000  # 3x volume
        data[20]['chg_pct'] = 5.0  # positive change
        
        engine = BacktestEngine("")
        signals = engine.calculate_volume_breakout_signals(data, volume_mult=2.0)
        
        buy_signals = [s for s in signals if s['signal'] == Signal.BUY]
        assert len(buy_signals) > 0


# ============ Backtest Engine Tests ============

class TestBacktestEngine:
    """Test the main backtest engine."""
    
    def test_get_kline_data(self, engine):
        """Test fetching K-line data from database."""
        data = engine.get_kline_data('sz002149')
        assert len(data) == 100
        assert all('trade_date' in d for d in data)
        assert all('close' in d for d in data)
    
    def test_get_kline_data_with_dates(self, engine):
        """Test fetching K-line data with date range."""
        data = engine.get_kline_data('sz002149', start_date='2024-01-15', end_date='2024-01-25')
        assert len(data) == 11  # 15-25 inclusive
        assert data[0]['trade_date'] == '2024-01-15'
        assert data[-1]['trade_date'] == '2024-01-25'
    
    def test_normalize_symbol(self, engine):
        """Test symbol normalization."""
        assert engine.normalize_symbol('002149') == 'sz002149'
        assert engine.normalize_symbol('601398') == 'sh601398'
        assert engine.normalize_symbol('sh600036') == 'sh600036'
        assert engine.normalize_symbol('sz000858') == 'sz000858'
    
    def test_run_backtest_basic(self, engine):
        """Test running a basic backtest."""
        result = engine.run_backtest(
            symbol='sz002149',
            strategy_func=ClassicStrategies.ma_cross,
            strategy_name='MA Cross',
            initial_capital=100000.0
        )
        
        assert isinstance(result, BacktestResult)
        assert result.symbol == 'sz002149'
        assert result.strategy_name == 'MA Cross'
        assert result.initial_capital == 100000.0
        assert result.total_trades >= 0
        assert len(result.equity_curve) > 0
        assert len(result.signals) > 0
    
    def test_run_backtest_with_dates(self, engine):
        """Test backtest with specific date range."""
        result = engine.run_backtest(
            symbol='sz002149',
            strategy_func=ClassicStrategies.rsi_mean_reversion,
            strategy_name='RSI Reversion',
            start_date='2024-01-20',
            end_date='2024-03-01',
            initial_capital=50000.0
        )
        
        assert result.start_date == '2024-01-20'
        assert result.end_date == '2024-03-01'
    
    def test_run_backtest_insufficient_data(self, engine):
        """Test backtest raises error with insufficient data."""
        with pytest.raises(ValueError, match="数据不足"):
            engine.run_backtest(
                symbol='sz002149',
                strategy_func=ClassicStrategies.ma_cross,
                strategy_name='MA Cross',
                start_date='2024-01-01',
                end_date='2024-01-10',  # Only 10 days
                initial_capital=100000.0
            )
    
    def test_max_drawdown_calculation(self, engine):
        """Test maximum drawdown calculation."""
        equity_curve = [
            {'equity': 100000},
            {'equity': 110000},
            {'equity': 105000},
            {'equity': 95000},
            {'equity': 100000},
            {'equity': 120000},
        ]
        
        max_dd, max_dd_pct = engine._calculate_max_drawdown(equity_curve)
        # Peak was 110k, trough was 95k, drawdown = 15k
        assert abs(max_dd - 15000) < 1
        assert abs(max_dd_pct - (15000/110000*100)) < 0.1
    
    def test_sharpe_ratio_calculation(self, engine):
        """Test Sharpe ratio calculation."""
        returns = [0.01, -0.005, 0.02, 0.01, -0.01, 0.015, 0.005]
        sharpe = engine._calculate_sharpe(returns, risk_free_rate=0.0001)
        
        # Sharpe should be a reasonable positive number for this data
        assert sharpe > 0
        assert sharpe < 10  # Sanity check
    
    def test_sortino_ratio_calculation(self, engine):
        """Test Sortino ratio calculation."""
        returns = [0.01, -0.005, 0.02, 0.01, -0.01, 0.015, 0.005]
        sortino = engine._calculate_sortino(returns, risk_free_rate=0.0001)
        
        assert sortino > 0


# ============ Classic Strategies Tests ============

class TestClassicStrategies:
    """Test the classic strategy implementations."""
    
    def test_ma_cross(self, sample_data):
        """Test MA cross strategy."""
        signals = ClassicStrategies.ma_cross(sample_data, fast=5, slow=20)
        assert len(signals) == len(sample_data)
        assert all('signal' in s for s in signals)
        assert all('price' in s for s in signals)
    
    def test_rsi_mean_reversion(self, sample_data):
        """Test RSI mean reversion strategy."""
        signals = ClassicStrategies.rsi_mean_reversion(sample_data, oversold=30, overbought=70)
        assert len(signals) == len(sample_data) - 1
    
    def test_macd_crossover(self, sample_data):
        """Test MACD crossover strategy."""
        signals = ClassicStrategies.macd_crossover(sample_data)
        assert len(signals) == len(sample_data) - 1
    
    def test_bollinger_bounce(self, sample_data):
        """Test Bollinger bounce strategy."""
        signals = ClassicStrategies.bollinger_bounce(sample_data, period=20, std=2.0)
        assert len(signals) == len(sample_data)
    
    def test_volume_breakout(self, sample_data):
        """Test volume breakout strategy."""
        signals = ClassicStrategies.volume_breakout(sample_data, mult=2.0)
        assert len(signals) == len(sample_data)
    
    def test_dual_ma_trend(self, sample_data):
        """Test dual MA trend strategy."""
        signals = ClassicStrategies.dual_ma_trend(sample_data, short=10, long=60)
        assert len(signals) == len(sample_data)
    
    def test_golden_cross(self, sample_data):
        """Test golden cross strategy."""
        signals = ClassicStrategies.golden_cross(sample_data)
        assert len(signals) == len(sample_data)


# ============ Risk Metrics Tests ============

class TestRiskMetrics:
    """Test risk metric calculations."""
    
    def test_calculate_var(self):
        """Test VaR calculation."""
        returns = [-0.02, -0.01, 0.01, 0.02, -0.005, 0.005, -0.015, 0.01]
        var_95 = RiskMetrics.calculate_var(returns, 0.95)
        var_99 = RiskMetrics.calculate_var(returns, 0.99)
        
        # VaR 99 should be more negative than VaR 95
        assert var_99 <= var_95
        # VaR should be negative (loss)
        assert var_95 < 0
    
    def test_calculate_cvar(self):
        """Test CVaR (Expected Shortfall) calculation."""
        returns = [-0.02, -0.01, 0.01, 0.02, -0.005, 0.005, -0.015, 0.01]
        cvar_95 = RiskMetrics.calculate_cvar(returns, 0.95)
        var_95 = RiskMetrics.calculate_var(returns, 0.95)
        
        # CVaR should be more extreme than VaR
        assert cvar_95 <= var_95
    
    def test_calculate_volatility(self):
        """Test volatility calculation."""
        returns = [0.01, -0.005, 0.02, 0.01, -0.01, 0.015, 0.005]
        vol_annual = RiskMetrics.calculate_volatility(returns, annualize=True)
        vol_daily = RiskMetrics.calculate_volatility(returns, annualize=False)
        
        # Annualized should be higher
        assert vol_annual > vol_daily
        assert vol_daily > 0
    
    def test_calculate_max_drawdown_returns(self):
        """Test max drawdown from equity curve."""
        equity_curve = [
            {'equity': 100000},
            {'equity': 105000},
            {'equity': 103000},
            {'equity': 100000},
            {'equity': 104000},
            {'equity': 103000},
        ]
        engine = BacktestEngine("")
        max_dd, max_dd_pct = engine._calculate_max_drawdown(equity_curve)
        
        assert max_dd >= 0
        assert max_dd_pct >= 0


# ============ Report Generation Tests ============

class TestReportGeneration:
    """Test report generation."""
    
    def test_generate_report(self, engine):
        """Test generating a backtest report."""
        result = engine.run_backtest(
            symbol='sz002149',
            strategy_func=ClassicStrategies.ma_cross,
            strategy_name='MA Cross Test',
            initial_capital=100000.0
        )
        
        report = generate_report(result)
        
        assert isinstance(report, str)
        assert 'MA Cross Test' in report
        assert 'sz002149' in report
        assert '总收益' in report
        assert '胜率' in report


# ============ Edge Cases ============

class TestEdgeCases:
    """Test edge cases and error handling."""
    
    def test_empty_data(self, engine):
        """Test behavior with empty data."""
        # Insert a stock with no data
        conn = sqlite3.connect(engine.db_path)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM kline_daily WHERE symbol = 'sz002149'")
        conn.commit()
        conn.close()
        
        with pytest.raises(ValueError):
            engine.run_backtest(
                symbol='sz002149',
                strategy_func=ClassicStrategies.ma_cross,
                strategy_name='Empty',
                initial_capital=100000.0
            )
    
    def test_all_hold_signals(self):
        """Test when strategy only generates HOLD signals."""
        data = []
        for i in range(30):
            data.append({
                'trade_date': f'2024-01-{i+1:02d}',
                'close': 50.0,
                'volume': 1000000,
                'chg_pct': 0.0,
                'ma5': 50.0,
                'ma10': 50.0,
                'ma20': 50.0,
                'rsi14': 50.0,
            })
        
        engine = BacktestEngine("")
        signals = engine.calculate_ma_signals(data, fast_period=5, slow_period=20)
        
        # All should be HOLD since no crossovers
        hold_count = sum(1 for s in signals if s['signal'] == Signal.HOLD)
        assert hold_count == len(signals)
    
    def test_initial_capital_zero(self, engine):
        """Test with zero initial capital - raises division error."""
        # With zero capital, the metrics calculation will fail
        with pytest.raises(ZeroDivisionError):
            engine.run_backtest(
                symbol='sz002149',
                strategy_func=ClassicStrategies.ma_cross,
                strategy_name='Zero Capital',
                initial_capital=0.0
            )


# ============ Vectorization Verification (PERF-002) ============

class TestVectorizationCorrectness:
    """Verify vectorized methods produce identical results to loop versions."""

    def test_ema_vectorized_matches_loop(self):
        """EMA vectorized output matches Python loop version."""
        import numpy as np
        np.random.seed(42)
        prices = np.cumsum(np.random.randn(200) * 0.5) + 100

        # Loop version
        def ema_loop(p, period):
            k = 2 / (period + 1)
            result = [p[0]]
            for v in p[1:]:
                result.append(v * k + result[-1] * (1 - k))
            return np.array(result)

        engine = BacktestEngine("")
        vec = engine._ema_vectorized(prices, 12)
        loop = ema_loop(list(prices), 12)

        np.testing.assert_allclose(vec, loop, atol=1e-12)

    def test_rsi_vectorized_matches_loop(self):
        """RSI vectorized output matches Python loop version."""
        import numpy as np
        np.random.seed(42)
        prices = np.cumsum(np.random.randn(200) * 0.5) + 100

        # Loop version (same as engine's original logic)
        def rsi_loop(prices_list, period=14):
            n = len(prices_list)
            if n < period + 1:
                return [float('nan')] * n
            gains, losses = [], []
            for i in range(1, n):
                d = prices_list[i] - prices_list[i-1]
                gains.append(max(d, 0))
                losses.append(max(-d, 0))
            avg_gain = sum(gains[:period]) / period
            avg_loss = sum(losses[:period]) / period
            rsi = [float('nan')] * n
            if avg_loss == 0:
                rsi[period] = 100.0 if avg_gain > 0 else 50.0
            else:
                rsi[period] = 100.0 - (100.0 / (1.0 + avg_gain / avg_loss))
            alpha = 1.0 / period
            coeff = 1.0 - alpha
            for i in range(period, n - 1):
                avg_gain = alpha * gains[i] + coeff * avg_gain
                avg_loss = alpha * losses[i] + coeff * avg_loss
                if avg_loss == 0:
                    rsi[i + 1] = 100.0 if avg_gain > 0 else 50.0
                else:
                    rsi[i + 1] = 100.0 - (100.0 / (1.0 + avg_gain / avg_loss))
            return rsi

        engine = BacktestEngine("")
        vec = engine._rsi_vectorized(prices, 14)
        loop = np.array(rsi_loop(list(prices), 14))

        mask = ~np.isnan(vec) & ~np.isnan(loop)
        np.testing.assert_allclose(vec[mask], loop[mask], atol=1e-10)

    def test_bollinger_vectorized_matches_loop(self):
        """Bollinger Bands vectorized output matches Python loop version."""
        import numpy as np, math
        np.random.seed(42)
        prices = np.cumsum(np.random.randn(200) * 0.5) + 100

        def bollinger_loop(plist, period=20, std_dev=2.0):
            n = len(plist)
            u, m, l = [float('nan')]*n, [float('nan')]*n, [float('nan')]*n
            for i in range(period, n):
                w = plist[i-period:i+1]
                mn = sum(w) / len(w)
                v = sum((x-mn)**2 for x in w) / len(w)
                s = math.sqrt(v)
                u[i], m[i], l[i] = mn + std_dev*s, mn, mn - std_dev*s
            return np.array(u), np.array(m), np.array(l)

        engine = BacktestEngine("")
        uv, mv, lv = engine._bollinger_bands_vectorized(prices, 20, 2.0)
        uo, mo, lo = bollinger_loop(list(prices), 20, 2.0)

        for name, v, o in [("upper", uv, uo), ("middle", mv, mo), ("lower", lv, lo)]:
            mask = ~np.isnan(v) & ~np.isnan(o)
            np.testing.assert_allclose(
                v[mask], o[mask], atol=1e-6,
                err_msg=f"Bollinger {name} differs"
            )

    def test_macd_vectorized_matches_loop(self):
        """MACD vectorized signals match original loop version."""
        import numpy as np
        np.random.seed(42)
        prices = np.cumsum(np.random.randn(100) * 0.5) + 100
        data = []
        for i, p in enumerate(prices):
            data.append({
                'trade_date': f'2024-{(i//30)+1:02d}-{(i%30)+1:02d}',
                'close': float(p),
                'volume': 1000000,
                'chg_pct': 0.0,
            })

        engine = BacktestEngine("")
        loop_signals = engine.calculate_macd_signals(data)
        vec_signals = engine.calculate_macd_signals_vectorized(data)

        assert len(loop_signals) == len(vec_signals)
        for ls, vs in zip(loop_signals, vec_signals):
            assert ls['signal'] == vs['signal'], (
                f"Signal mismatch at {ls['date']}: loop={ls['signal']} vec={vs['signal']}"
            )

    def test_rsi_vectorized_signals_match_loop(self):
        """RSI vectorized signals match original loop version."""
        import numpy as np
        np.random.seed(42)
        prices = np.cumsum(np.random.randn(100) * 0.5) + 100
        data = []
        for i, p in enumerate(prices):
            data.append({
                'trade_date': f'2024-{(i//30)+1:02d}-{(i%30)+1:02d}',
                'close': float(p),
                'volume': 1000000,
                'chg_pct': 0.0,
                'rsi14': None,  # will be computed from close
            })

        engine = BacktestEngine("")
        # For RSI loop version, we need rsi14 field
        rsi_vals = engine._rsi_vectorized(np.array([d['close'] for d in data]), 14)
        for i, d in enumerate(data):
            d['rsi14'] = float(rsi_vals[i]) if not np.isnan(rsi_vals[i]) else None

        loop_signals = engine.calculate_rsi_signals(data, oversold=30, overbought=70)
        vec_signals = engine.calculate_rsi_signals_vectorized(data, oversold=30, overbought=70)

        assert len(loop_signals) == len(vec_signals)
        for ls, vs in zip(loop_signals, vec_signals):
            assert ls['signal'] == vs['signal'], (
                f"Signal mismatch at {ls['date']}: loop={ls['signal']} vec={vs['signal']}"
            )

    def test_bollinger_vectorized_signals_match_loop(self):
        """Bollinger vectorized signals match original loop version."""
        import numpy as np
        np.random.seed(42)
        prices = np.cumsum(np.random.randn(100) * 0.5) + 100
        data = []
        for i, p in enumerate(prices):
            data.append({
                'trade_date': f'2024-{(i//30)+1:02d}-{(i%30)+1:02d}',
                'close': float(p),
                'volume': 1000000,
                'chg_pct': 0.0,
            })

        engine = BacktestEngine("")
        loop_signals = engine.calculate_bollinger_signals(data, period=20, std_dev=2.0)
        vec_signals = engine.calculate_bollinger_signals_vectorized(data, period=20, std_dev=2.0)

        assert len(loop_signals) == len(vec_signals)
        for ls, vs in zip(loop_signals, vec_signals):
            assert ls['signal'] == vs['signal'], (
                f"Signal mismatch at {ls['date']}: loop={ls['signal']} vec={vs['signal']}"
            )


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
