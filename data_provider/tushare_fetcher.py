"""
data_provider/tushare_fetcher.py — tushare 数据源实现（备用，需要 token）
"""

import os
import logging
from typing import List, Dict

import pandas as pd

from .base import BaseFetcher, symbol_to_code, normalize_columns

logger = logging.getLogger(__name__)

# tushare pro API 全局实例（懒加载）
_pro = None


def _get_pro():
    global _pro
    if _pro is None:
        import tushare as ts
        token = os.environ.get('TUSHARE_TOKEN', '')
        if not token:
            logger.warning("[tushare] TUSHARE_TOKEN 环境变量未设置")
            return None
        ts.set_token(token)
        _pro = ts.pro_api()
    return _pro


class TushareFetcher(BaseFetcher):
    """tushare 数据源。使用 pro.daily 获取日K线，需要 TUSHARE_TOKEN 环境变量。"""

    def __init__(self, priority: int = 3):
        super().__init__(priority, 'tushare')

    def is_available(self) -> bool:
        try:
            import tushare
            token = os.environ.get('TUSHARE_TOKEN', '')
            return bool(token)
        except ImportError:
            return False

    def _symbol_to_ts_code(self, symbol: str) -> str:
        """sz002149 -> 002149.SZ"""
        code = symbol_to_code(symbol)
        suffix = 'SZ' if symbol.startswith('sz') else 'SH'
        return f"{code}.{suffix}"

    def get_daily_data(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        pro = _get_pro()
        if pro is None:
            return pd.DataFrame()

        ts_code = self._symbol_to_ts_code(symbol)

        try:
            df = pro.daily(
                ts_code=ts_code,
                start_date=start_date,
                end_date=end_date
            )

            if df is None or df.empty:
                return pd.DataFrame()

            # tushare 返回: ts_code, trade_date, open, high, low, close, pre_close, change, pct_chg, vol, amount
            # 需要重命名
            df = df.rename(columns={
                'trade_date': 'date',
                'vol': 'volume',
                'pct_chg': 'chg_pct',
            })

            df = normalize_columns(df)
            return df
        except Exception as e:
            logger.warning(f"[tushare] {symbol} 获取失败: {e}")
            return pd.DataFrame()

    def get_realtime_quote(self, symbols: List[str]) -> List[Dict]:
        # tushare pro 不直接支持实时行情（需要积分），返回空
        logger.debug("[tushare] 实时行情需要积分权限")
        return []
