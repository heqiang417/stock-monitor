"""
Backtest engine package.
Provides backtesting framework, classic strategies, and risk metrics.
"""

from .engine import (
    BacktestEngine,
    ClassicStrategies,
    RiskMetrics,
    Signal,
    Trade,
    BacktestResult,
    generate_report,
)

__all__ = [
    'BacktestEngine',
    'ClassicStrategies',
    'RiskMetrics',
    'Signal',
    'Trade',
    'BacktestResult',
    'generate_report',
]
