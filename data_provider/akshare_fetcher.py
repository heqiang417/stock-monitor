"""
data_provider/akshare_fetcher.py — akshare 数据源实现（优先级最高）
"""

import time
import random
import logging
from typing import List, Dict

import pandas as pd

from .base import BaseFetcher, symbol_to_code, normalize_columns

logger = logging.getLogger(__name__)


class AkshareFetcher(BaseFetcher):
    """akshare 数据源。使用 ak.stock_zh_a_hist 获取日K线。"""

    def __init__(self, priority: int = 0):
        super().__init__(priority, 'akshare')

    def is_available(self) -> bool:
        try:
            import akshare
            return True
        except ImportError:
            return False

    def get_daily_data(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        return self.get_period_data(symbol, start_date, end_date, period='daily')

    def get_period_data(self, symbol: str, start_date: str, end_date: str,
                        period: str = 'daily') -> pd.DataFrame:
        import akshare as ak

        code = symbol_to_code(symbol)
        period_map = {'daily': 'daily', 'weekly': 'weekly', 'monthly': 'monthly'}
        ak_period = period_map.get(period, 'daily')

        # 防封禁：随机 sleep
        time.sleep(random.uniform(0.5, 2.0))

        df = ak.stock_zh_a_hist(
            symbol=code,
            period=ak_period,
            start_date=start_date,
            end_date=end_date,
            adjust='qfq'
        )

        if df is None or df.empty:
            return pd.DataFrame()

        df = normalize_columns(df)
        return df

    def get_realtime_quote(self, symbols: List[str]) -> List[Dict]:
        try:
            import akshare as ak

            results = []
            for sym in symbols:
                code = symbol_to_code(sym)
                try:
                    df = ak.stock_zh_a_spot_em()
                    if df is not None and not df.empty:
                        row = df[df['代码'] == code]
                        if not row.empty:
                            row = row.iloc[0]
                            results.append({
                                'symbol': sym,
                                'name': str(row.get('名称', '')),
                                'price': float(row.get('最新价', 0)),
                                'chg_pct': float(row.get('涨跌幅', 0)),
                                'volume': float(row.get('成交量', 0)),
                                'amount': float(row.get('成交额', 0)),
                            })
                except Exception as e:
                    logger.debug(f"[akshare] 实时行情 {sym} 失败: {e}")
                    continue

            return results
        except Exception as e:
            logger.warning(f"[akshare] 实时行情批量获取失败: {e}")
            return []
