"""
data_provider/baostock_fetcher.py — baostock 数据源实现（备用）
"""

import logging
from typing import List, Dict

import pandas as pd

from .base import BaseFetcher, symbol_to_code, normalize_columns, STANDARD_COLUMNS

logger = logging.getLogger(__name__)


class BaostockFetcher(BaseFetcher):
    """baostock 数据源。使用 baostock.query_history_k_data_plus 获取日K线。"""

    def __init__(self, priority: int = 2):
        super().__init__(priority, 'baostock')

    def is_available(self) -> bool:
        try:
            import baostock
            return True
        except ImportError:
            return False

    def _symbol_to_bs_code(self, symbol: str) -> str:
        """sz002149 -> sz.002149, sh600519 -> sh.600519"""
        code = symbol_to_code(symbol)
        prefix = 'sz' if symbol.startswith('sz') else 'sh'
        return f"{prefix}.{code}"

    def get_daily_data(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        import baostock as bs

        bs_code = self._symbol_to_bs_code(symbol)

        # 格式化日期: YYYYMMDD -> YYYY-MM-DD
        start = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:8]}"
        end = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:8]}"

        try:
            rs = bs.query_history_k_data_plus(
                bs_code,
                "date,open,high,low,close,volume,amount,pctChg",
                start_date=start,
                end_date=end,
                frequency="d",
                adjustflag="2"  # 前复权
            )

            if rs.error_code != '0':
                logger.warning(f"[baostock] {symbol} 查询失败: {rs.error_msg}")
                return pd.DataFrame()

            rows = []
            while rs.next():
                rows.append(rs.get_row_data())

            if not rows:
                return pd.DataFrame()

            df = pd.DataFrame(rows, columns=rs.fields)
            df = normalize_columns(df)
            return df
        except Exception as e:
            logger.warning(f"[baostock] {symbol} 获取失败: {e}")
            return pd.DataFrame()

    def get_realtime_quote(self, symbols: List[str]) -> List[Dict]:
        # baostock 不支持实时行情，返回空
        logger.debug("[baostock] 不支持实时行情")
        return []
