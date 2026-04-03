"""
data_provider/tencent_fetcher.py — 腾讯财经数据源（稳定可靠，不依赖 eastmoney）

使用腾讯财经 web API：
- 日/周/月K线: web.ifzq.gtimg.cn/appstock/app/fqkline/get
- 实时行情+PE/PB: qt.gtimg.cn/q=...

优点：不限 IP、不需要登录、不要 token、响应快
缺点：无历史资金流向、无龙虎榜等深度数据
"""

import logging
from typing import List, Dict

import pandas as pd
import requests

from .base import BaseFetcher, symbol_to_code, STANDARD_COLUMNS

logger = logging.getLogger(__name__)


class TencentFetcher(BaseFetcher):
    """腾讯财经数据源。优先级最高（最稳定）。"""

    def __init__(self, priority: int = 0):
        super().__init__(priority, 'tencent')
        self._session = None

    def _get_session(self) -> requests.Session:
        if self._session is None:
            self._session = requests.Session()
            self._session.trust_env = False  # 忽略代理环境变量
            self._session.headers.update({
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Referer': 'https://stockapp.finance.qq.com/',
            })
        return self._session

    def is_available(self) -> bool:
        try:
            s = self._get_session()
            r = s.get('https://qt.gtimg.cn/q=sh000001', timeout=5)
            return r.status_code == 200
        except Exception:
            return False

    def _to_tencent_sym(self, symbol: str) -> str:
        """sz002149 -> sz002149, sh600519 -> sh600519"""
        if symbol.startswith(('sz', 'sh')):
            return symbol
        code = symbol_to_code(symbol)
        if code.startswith(('0', '3', '2')):
            return f'sz{code}'
        return f'sh{code}'

    def get_daily_data(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        return self.get_period_data(symbol, start_date, end_date, period='daily')

    def get_period_data(self, symbol: str, start_date: str, end_date: str,
                        period: str = 'daily') -> pd.DataFrame:
        tsym = self._to_tencent_sym(symbol)
        session = self._get_session()

        period_map = {'daily': 'day', 'weekly': 'week', 'monthly': 'month'}
        t_period = period_map.get(period, 'day')

        # 格式化日期: YYYYMMDD -> YYYY-MM-DD
        def fmt_date(d):
            d = d.replace('-', '')
            if len(d) == 8:
                return f"{d[:4]}-{d[4:6]}-{d[6:8]}"
            return d

        beg = fmt_date(start_date)
        end = fmt_date(end_date)

        try:
            r = session.get(
                'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get',
                params={'param': f'{tsym},{t_period},{beg},{end},320,qfq'},
                timeout=10
            )
            d = r.json()
            data = d.get('data', {}).get(tsym, {})

            # 尝试多个可能的 key
            rows = data.get(t_period, []) or data.get(f'qfq{t_period}', [])

            if not rows:
                return pd.DataFrame()

            records = []
            prev_close = None
            for row in rows:
                if len(row) >= 6:
                    close = float(row[2])
                    chg_pct = round((close - prev_close) / prev_close * 100, 2) if prev_close else 0
                    records.append({
                        'date': str(row[0]),
                        'open': float(row[1]),
                        'close': close,
                        'high': float(row[3]),
                        'low': float(row[4]),
                        'volume': float(row[5]),
                        'amount': float(row[6]) if len(row) > 6 else 0,
                        'chg_pct': float(row[8]) if len(row) > 8 else chg_pct,
                    })
                    prev_close = close

            if not records:
                return pd.DataFrame()

            df = pd.DataFrame(records, columns=STANDARD_COLUMNS)
            return df
        except Exception as e:
            logger.warning(f"[tencent] {symbol} {period} 获取失败: {e}")
            return pd.DataFrame()

    def get_realtime_quote(self, symbols: List[str]) -> List[Dict]:
        if not symbols:
            return []

        session = self._get_session()
        # 批量查询（逗号分隔，上限约 80 只）
        batch_size = 50
        results = []

        for i in range(0, len(symbols), batch_size):
            batch = symbols[i:i + batch_size]
            t_syms = [self._to_tencent_sym(s) for s in batch]
            query = ','.join(t_syms)

            try:
                r = session.get(f'https://qt.gtimg.cn/q={query}', timeout=10)
                lines = r.text.strip().split('\n')

                for line, sym in zip(lines, batch):
                    line = line.strip()
                    if not line or '=' not in line:
                        continue
                    eq_pos = line.index('=')
                    fields = line[eq_pos + 2:-1].split('~')  # 去引号
                    if len(fields) >= 47:
                        results.append({
                            'symbol': sym,
                            'name': str(fields[1]),
                            'price': float(fields[3]) if fields[3] else 0,
                            'chg_pct': float(fields[32]) if fields[32] else 0,
                            'volume': float(fields[6]) if fields[6] else 0,
                            'amount': float(fields[37]) if fields[37] else 0,
                            'pe': float(fields[39]) if fields[39] and fields[39] != '' else None,
                            'pb': float(fields[46]) if fields[46] and fields[46] != '' else None,
                        })
            except Exception as e:
                logger.debug(f"[tencent] 实时行情批次 {i} 失败: {e}")
                continue

        return results
