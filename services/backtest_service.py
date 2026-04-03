"""
Backtest service.
Handles backtesting operations using the existing backtest_engine.
"""

import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class BacktestService:
    """Service for backtest operations."""
    
    def __init__(self):
        """Initialize backtest service."""
        self._engine = None
    
    def get_engine(self):
        """Get or create the backtest engine instance."""
        if self._engine is None:
            try:
                from backtest import BacktestEngine
                import os
                db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'stock_data.db')
                self._engine = BacktestEngine(db_path)
                logger.info("Backtest engine initialized")
            except ImportError as e:
                logger.error(f"Failed to import backtest_engine: {e}")
                raise
        return self._engine
    
    def run_backtest(self, config: dict) -> dict:
        """
        Run a backtest with the given configuration.
        
        Args:
            config: Backtest configuration dict with:
                - symbol: Stock symbol
                - start_date: Start date string
                - end_date: End date string
                - strategy: Strategy config dict
                - initial_capital: Starting capital
                - stop_loss_pct: Stop loss percentage (optional, from config)
                - max_position_pct: Max position percentage (optional, from config)
        
        Returns:
            Backtest results dict
        """
        try:
            engine = self.get_engine()
            # Import strategy functions
            from backtest import ClassicStrategies
            import config as app_config
            symbol = config.get('symbol', '002149')
            strategy_id = config.get('strategy', 'ma_cross')
            start_date = config.get('start_date')
            end_date = config.get('end_date')
            initial_capital = config.get('initial_capital', app_config.Config.INITIAL_CAPITAL)
            
            # STRAT-001/002: 从配置读取止损和仓位管理参数
            stop_loss_pct = config.get('stop_loss_pct', app_config.Config.STOP_LOSS_PCT)
            max_position_pct = config.get('max_position_pct', app_config.Config.MAX_POSITION_PCT)
            
            # Map strategy ID to function
            strategy_map = {
                'ma_cross': ClassicStrategies.ma_cross,
                'rsi_mean_reversion': ClassicStrategies.rsi_mean_reversion,
                'macd_crossover': ClassicStrategies.macd_crossover,
                'bollinger_bounce': ClassicStrategies.bollinger_bounce,
                'volume_breakout': ClassicStrategies.volume_breakout,
                'dual_ma_trend': ClassicStrategies.dual_ma_trend,
                'golden_cross': ClassicStrategies.golden_cross,
            }
            
            strategy_func = strategy_map.get(strategy_id, ClassicStrategies.ma_cross)
            strategy_name = strategy_id
            
            result = engine.run_backtest(
                symbol=symbol,
                strategy_func=strategy_func,
                strategy_name=strategy_name,
                start_date=start_date,
                end_date=end_date,
                initial_capital=initial_capital,
                stop_loss_pct=stop_loss_pct,
                max_position_pct=max_position_pct
            )
            logger.info(f"Backtest completed for {symbol} (stop_loss={stop_loss_pct}%, max_position={max_position_pct}%)")
            
            # Convert result to dict with Signal enum values as strings
            from backtest import Signal
            result_dict = {
                'strategy_name': result.strategy_name,
                'symbol': result.symbol,
                'start_date': result.start_date,
                'end_date': result.end_date,
                'initial_capital': result.initial_capital,
                'final_capital': result.final_capital,
                'total_return': result.total_return,
                'total_return_pct': result.total_return_pct,
                'annual_return': result.annual_return,
                'max_drawdown': result.max_drawdown,
                'max_drawdown_pct': result.max_drawdown_pct,
                'sharpe_ratio': result.sharpe_ratio,
                'sortino_ratio': result.sortino_ratio,
                'win_rate': result.win_rate,
                'profit_factor': result.profit_factor,
                'total_trades': result.total_trades,
                'winning_trades': result.winning_trades,
                'losing_trades': result.losing_trades,
                'avg_win': result.avg_win,
                'avg_loss': result.avg_loss,
                'largest_win': result.largest_win,
                'largest_loss': result.largest_loss,
                'avg_hold_days': result.avg_hold_days,
                'trades': result.trades,
                'equity_curve': result.equity_curve,
                # STRAT-001: 止损统计
                'stop_loss_count': result.stop_loss_count,
                'stop_loss_pct': result.stop_loss_pct,
                # STRAT-002: 仓位管理
                'position_management': result.position_management,
            }
            return result_dict
        except Exception as e:
            logger.error(f"Backtest error: {e}")
            raise
    
    def get_backtest_history(self, limit: int = 50) -> list:
        """Get historical backtest results."""
        try:
            engine = self.get_engine()
            return engine.get_history(limit) if hasattr(engine, 'get_history') else []
        except Exception as e:
            logger.error(f"Failed to get backtest history: {e}")
            return []
    
    def validate_config(self, config: dict) -> tuple[bool, str]:
        """
        Validate backtest configuration.
        
        Returns:
            (is_valid, error_message)
        """
        if not config.get('symbol'):
            return False, "Missing symbol"
        
        # Accept strategy as string (ID) or dict
        strategy = config.get('strategy')
        if not strategy:
            return False, "Missing strategy configuration"
        
        start_date = config.get('start_date')
        end_date = config.get('end_date')
        
        if not start_date or not end_date:
            return False, "Missing date range"
        
        # Validate date format
        try:
            from datetime import datetime
            datetime.strptime(start_date, '%Y-%m-%d')
            datetime.strptime(end_date, '%Y-%m-%d')
        except ValueError:
            return False, "Invalid date format (use YYYY-MM-DD)"
        
        return True, ""
