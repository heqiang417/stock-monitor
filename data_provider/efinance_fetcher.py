"""
data_provider/efinance_fetcher.py — efinance 数据源实现（备用）
"""

import logging
from typing import List, Dict

import pandas as pd

from .base import BaseFetcher, symbol_to_code, symbol_to_market, normalize_columns

logger = logging.getLogger(__name__)


class EfinanceFetcher(BaseFetcher):
    """efinance 数据源。使用 efinance.stock.get_quote_history 获取日K线。"""

    def __init__(self, priority: int = 1):
        super().__init__(priority, 'efinance')

    def is_available(self) -> bool:
        try:
            import efinance
            return True
        except ImportError:
            return False

    def get_daily_data(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        import efinance.stock as ef_stock

        code = symbol_to_code(symbol)
        market = symbol_to_market(symbol)

        try:
            df = ef_stock.get_quote_history(
                code,
                beg=start_date.replace('-', ''),
                end=end_date.replace('-', ''),
                klt=101,  # 日K
                fqt=1    # 前复权
            )

            if df is None or df.empty:
                return pd.DataFrame()

            # efinance 返回列: 日期, 开盘, 收盘, 最高, 最低, 成交量, 成交额, 振幅, 涨跌幅, 涨跌额, 换手率
            df = normalize_columns(df)
            return df
        except Exception as e:
            logger.warning(f"[efinance] {symbol} 获取失败: {e}")
            return pd.DataFrame()

    def get_realtime_quote(self, symbols: List[str]) -> List[Dict]:
        try:
            import efinance.stock as ef_stock

            codes = [symbol_to_code(s) for s in symbols]
            df = ef_stock.get_realtime_quotes()

            if df is None or df.empty:
                return []

            results = []
            for sym, code in zip(symbols, codes):
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

            return results
        except Exception as e:
            logger.warning(f"[efinance] 实时行情获取失败: {e}")
            return []
