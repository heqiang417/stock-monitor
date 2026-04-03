"""
data_provider/manager.py — DataFetcherManager
多数据源管理器，按优先级自动切换。
"""

import logging
from typing import List, Dict, Optional

import pandas as pd

from .base import BaseFetcher

logger = logging.getLogger(__name__)


class DataFetcherManager:
    """多数据源管理器。按优先级排序，失败自动切换下一个。"""

    def __init__(self):
        self.fetchers: List[BaseFetcher] = []

    def register(self, fetcher: BaseFetcher):
        """注册数据源，按优先级排序。"""
        self.fetchers.append(fetcher)
        self.fetchers.sort(key=lambda f: f.priority)
        logger.info(f"[DataFetcherManager] 已注册 {fetcher.name} (优先级 {fetcher.priority})")

    def get_daily_data(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        """按优先级尝试获取日K线数据，失败自动切换下一个。"""
        return self.get_period_data(symbol, start_date, end_date, period='daily')

    def get_period_data(self, symbol: str, start_date: str, end_date: str,
                        period: str = 'daily') -> pd.DataFrame:
        """按优先级尝试获取指定周期K线数据（daily/weekly/monthly）。"""
        for fetcher in self.fetchers:
            if not fetcher.is_available():
                logger.debug(f"[DataFetcherManager] {fetcher.name} 不可用，跳过")
                continue
            try:
                data = fetcher.get_period_data(symbol, start_date, end_date, period=period)
                if data is not None and not data.empty:
                    logger.info(f"[{fetcher.name}] {symbol} {period}获取成功 ({len(data)} 条)")
                    return data
            except Exception as e:
                logger.warning(f"[{fetcher.name}] {symbol} {period}失败: {e}")
                continue

        logger.error(f"[DataFetcherManager] 所有数据源均失败: {symbol} ({period})")
        return pd.DataFrame()

    def get_realtime_quote(self, symbols: List[str]) -> List[Dict]:
        """按优先级尝试获取实时行情。"""
        for fetcher in self.fetchers:
            if not fetcher.is_available():
                continue
            try:
                data = fetcher.get_realtime_quote(symbols)
                if data:
                    logger.info(f"[{fetcher.name}] 实时行情获取成功 ({len(data)} 只)")
                    return data
            except Exception as e:
                logger.warning(f"[{fetcher.name}] 实时行情失败: {e}")
                continue

        logger.error("[DataFetcherManager] 所有数据源实时行情均失败")
        return []

    def list_available(self) -> List[str]:
        """列出所有可用的数据源名称。"""
        return [f.name for f in self.fetchers if f.is_available()]
