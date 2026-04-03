"""
data_provider/base.py — BaseFetcher 抽象基类
"""

from abc import ABC, abstractmethod
from typing import List, Dict
import pandas as pd


class BaseFetcher(ABC):
    """数据源抽象基类。优先级越小越优先。"""

    def __init__(self, priority: int, name: str):
        self.priority = priority
        self.name = name

    @abstractmethod
    def get_daily_data(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        """
        获取日K线数据。
        返回标准列名 DataFrame: date, open, high, low, close, volume, amount, chg_pct
        symbol 格式: sz002149 / sh600519
        start_date / end_date 格式: YYYYMMDD
        """
        pass

    def get_period_data(self, symbol: str, start_date: str, end_date: str,
                        period: str = 'daily') -> pd.DataFrame:
        """
        获取指定周期的K线数据（daily/weekly/monthly）。
        默认实现调用 get_daily_data，子类可覆盖。
        """
        return self.get_daily_data(symbol, start_date, end_date)

    @abstractmethod
    def get_realtime_quote(self, symbols: List[str]) -> List[Dict]:
        """获取实时行情列表。"""
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """检查数据源是否可用。"""
        pass


# ============================================================
# 标准化工具函数
# ============================================================

# 标准列名映射 (各源列名 -> 标准列名)
COLUMN_MAP = {
    # akshare
    '日期': 'date', '开盘': 'open', '收盘': 'close', '最高': 'high', '最低': 'low',
    '成交量': 'volume', '成交额': 'amount', '涨跌幅': 'chg_pct', '涨跌额': 'chg',
    '换手率': 'turnover',
    # efinance
    'date': 'date', 'open': 'open', 'close': 'close', 'high': 'high', 'low': 'low',
    'volume': 'volume', 'amount': 'amount',
    # baostock
    'close': 'close', 'open': 'open', 'high': 'high', 'low': 'low',
    'volume': 'volume', 'amount': 'amount', 'pctChg': 'chg_pct', 'turn': 'turnover',
    # tushare
    'vol': 'volume', 'pct_chg': 'chg_pct',
}

STANDARD_COLUMNS = ['date', 'open', 'high', 'low', 'close', 'volume', 'amount', 'chg_pct']


def normalize_symbol(code: str) -> str:
    """
    标准化股票代码为 szXXXXXX / shXXXXXX 格式。
    支持输入: 002149, sz002149, 600519, sh600519, SZ002149 等。
    """
    code = code.strip().lower()
    if code.startswith(('sz', 'sh')):
        return code
    # 根据代码前缀判断交易所
    if code.startswith(('0', '3', '2')):
        return f'sz{code}'
    elif code.startswith(('6', '5', '9', '11')):
        return f'sh{code}'
    # 默认深圳
    return f'sz{code}'


def symbol_to_code(symbol: str) -> str:
    """sz002149 -> 002149, sh600519 -> 600519"""
    if symbol.startswith(('sz', 'sh')):
        return symbol[2:]
    return symbol


def symbol_to_market(symbol: str) -> int:
    """sz002149 -> 0 (深圳), sh600519 -> 1 (上海)"""
    if symbol.startswith('sh'):
        return 1
    return 0


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """统一列名为标准格式。"""
    if df is None or df.empty:
        return pd.DataFrame(columns=STANDARD_COLUMNS)

    # 重命名已知列
    rename_map = {}
    for col in df.columns:
        lower = col.lower().strip()
        if lower in COLUMN_MAP:
            rename_map[col] = COLUMN_MAP[lower]
        elif col in COLUMN_MAP:
            rename_map[col] = COLUMN_MAP[col]

    df = df.rename(columns=rename_map)

    # 确保标准列存在
    for col in STANDARD_COLUMNS:
        if col not in df.columns:
            df[col] = 0.0 if col != 'date' else ''

    return df[STANDARD_COLUMNS]
