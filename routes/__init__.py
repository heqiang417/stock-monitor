"""
Routes package.
Contains Flask blueprints for API endpoints.
All routes are versioned with /api/v1/ prefix and maintain backward compatibility.
"""

from .stock_routes import create_stock_routes
from .strategy_routes import create_strategy_routes
from .backtest_routes import create_backtest_routes
from .alert_routes import create_alert_routes
from .kline_routes import create_kline_routes
from .dashboard_routes import create_dashboard_routes

__all__ = [
    'create_stock_routes',
    'create_strategy_routes',
    'create_backtest_routes',
    'create_alert_routes',
    'create_kline_routes',
    'create_dashboard_routes'
]
