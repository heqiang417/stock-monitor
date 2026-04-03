"""
data_provider — 多数据源架构
统一的数据获取接口，支持 tencent / akshare / efinance / baostock / tushare 自动切换。

用法:
    from data_provider import DataFetcherManager
    from data_provider.tencent_fetcher import TencentFetcher
    from data_provider.akshare_fetcher import AkshareFetcher

    manager = DataFetcherManager()
    manager.register(TencentFetcher(priority=0))
    manager.register(AkshareFetcher(priority=1))

    df = manager.get_daily_data('sz002149', '20250101', '20260325')
"""

from .manager import DataFetcherManager
from .base import BaseFetcher, normalize_symbol, symbol_to_code, normalize_columns
from .tencent_fetcher import TencentFetcher

__all__ = [
    'DataFetcherManager',
    'BaseFetcher',
    'normalize_symbol',
    'symbol_to_code',
    'normalize_columns',
]
