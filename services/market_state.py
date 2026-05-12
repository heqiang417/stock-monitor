"""
市场状态分析模块 - 三段式复盘（借鉴 daily_stock_analysis）
每天输出：进攻 / 均衡 / 防守，映射到仓位管理
"""
import numpy as np
from dataclasses import dataclass
from enum import Enum
from typing import List
from datetime import datetime
from db import DatabaseManager


class MarketRegime(Enum):
    OFFENSIVE = "进攻"
    BALANCED = "均衡"
    DEFENSIVE = "防守"


@dataclass
class MarketSignal:
    name: str
    value: str
    detail: str
    score: float


@dataclass
class MarketState:
    regime: MarketRegime
    signals: List[MarketSignal]
    score: float
    position_hint: str
    date: str


class MarketStateAnalyzer:
    def __init__(self, db_path: str):
        self.db = DatabaseManager(db_path)

    def analyze(self, date: str = None) -> MarketState:
        if date is None:
            date = datetime.now().strftime('%Y-%m-%d')
        signals = [
            self._check_index_trend(date),
            self._check_volume(date),
            self._check_breadth(date),
            self._check_sector_rotation(date),
            self._check_northbound(date),
        ]
        score = np.mean([s.score for s in signals if s.score is not None])
        if score >= 0.3:
            regime = MarketRegime.OFFENSIVE
            position = '可积极操作，仓位70-100%'
        elif score <= -0.3:
            regime = MarketRegime.DEFENSIVE
            position = '控制风险，仓位0-30%'
        else:
            regime = MarketRegime.BALANCED
            position = '谨慎操作，仓位30-70%'
        return MarketState(regime=regime, signals=signals, score=round(score, 2), position_hint=position, date=date)

    def _check_index_trend(self, date) -> MarketSignal:
        indices = ['sh000001', 'sz399001', 'sz399006']
        trends = []
        for idx in indices:
            rows = self.db.fetch_all("""
                SELECT close, ma5, ma20 FROM kline_daily
                WHERE symbol = %s AND trade_date <= %s
                ORDER BY trade_date DESC LIMIT 5
            """, (idx, date))
            if len(rows) >= 5:
                closes = [r['close'] for r in rows]
                pct5 = (closes[0] - closes[4]) / closes[4] * 100
                trends.append(pct5)
        if len(trends) == 3:
            avg_pct = np.mean(trends)
            if all(t > 0 for t in trends):
                return MarketSignal('指数趋势', '看多', f"三大指数齐涨，5日均涨{avg_pct:.1f}%", min(1.0, avg_pct / 5))
            if all(t < 0 for t in trends):
                return MarketSignal('指数趋势', '看空', f"三大指数齐跌，5日均跌{avg_pct:.1f}%", max(-1.0, avg_pct / 5))
            return MarketSignal('指数趋势', '中性', f"指数分化，5日涨跌: {'/'.join([f'{t:.1f}%' for t in trends])}", 0.0)
        return MarketSignal('指数趋势', '中性', '数据不足', 0.0)

    def _check_volume(self, date) -> MarketSignal:
        rows = self.db.fetch_all("""
            SELECT trade_date, amount FROM kline_daily
            WHERE symbol = 'sh000001' AND trade_date <= %s
            ORDER BY trade_date DESC LIMIT 20
        """, (date,))
        if len(rows) < 10:
            return MarketSignal('量能', '中性', '数据不足', 0.0)
        amounts = [r['amount'] for r in rows if r['amount'] and r['amount'] > 0]
        if len(amounts) < 5:
            return MarketSignal('量能', '中性', '成交额数据缺失', 0.0)
        today_amt = amounts[0]
        avg5 = np.mean(amounts[1:6])
        ratio = today_amt / avg5 if avg5 > 0 else 1.0
        if ratio > 1.3:
            return MarketSignal('量能', '看多', f"放量{ratio:.1f}倍（今日{today_amt/1e8:.0f}亿 vs 5日均{avg5/1e8:.0f}亿）", min(1.0, (ratio - 1) / 2))
        if ratio < 0.7:
            return MarketSignal('量能', '看空', f"缩量{ratio:.1f}倍（今日{today_amt/1e8:.0f}亿 vs 5日均{avg5/1e8:.0f}亿）", max(-1.0, (ratio - 1) / 2))
        return MarketSignal('量能', '中性', f"量能平稳（今日{today_amt/1e8:.0f}亿 vs 5日均{avg5/1e8:.0f}亿）", 0.0)

    def _check_breadth(self, date) -> MarketSignal:
        rows = self.db.fetch_all('SELECT chg_pct FROM kline_daily WHERE trade_date = %s AND chg_pct IS NOT NULL', (date,))
        if not rows:
            rows = self.db.fetch_all("""
                SELECT chg_pct FROM kline_daily
                WHERE trade_date = (SELECT MAX(trade_date) FROM kline_daily WHERE trade_date <= %s)
                AND chg_pct IS NOT NULL
            """, (date,))
        if not rows:
            return MarketSignal('涨跌比', '中性', '数据不足', 0.0)
        chg = [r['chg_pct'] for r in rows]
        up = sum(1 for c in chg if c > 0)
        down = sum(1 for c in chg if c < 0)
        limit_up = sum(1 for c in chg if c >= 9.9)
        limit_down = sum(1 for c in chg if c <= -9.9)
        total = len(chg)
        ratio = up / total if total > 0 else 0.5
        if ratio > 0.7:
            return MarketSignal('涨跌比', '看多', f'上涨{up}只({ratio:.0%})，涨停{limit_up}只', min(1.0, (ratio - 0.5) * 2))
        if ratio < 0.3:
            return MarketSignal('涨跌比', '看空', f'上涨{up}只({ratio:.0%})，跌停{limit_down}只', max(-1.0, (ratio - 0.5) * 2))
        return MarketSignal('涨跌比', '中性', f'涨跌参半，上涨{up}只/下跌{down}只，涨停{limit_up}跌停{limit_down}', (ratio - 0.5) * 2)

    def _check_sector_rotation(self, date) -> MarketSignal:
        rows = self.db.fetch_all("""
            SELECT si.industry, AVG(k.chg_pct) as avg_chg
            FROM kline_daily k
            JOIN stock_industry si ON k.symbol = si.symbol
            WHERE k.trade_date = (SELECT MAX(trade_date) FROM kline_daily WHERE trade_date <= %s)
            AND k.chg_pct IS NOT NULL AND si.industry IS NOT NULL
            GROUP BY si.industry
            HAVING COUNT(*) >= 5
            ORDER BY avg_chg DESC
        """, (date,))
        if len(rows) < 5:
            return MarketSignal('板块', '中性', '板块数据不足', 0.0)
        top3 = rows[:3]
        avg_top = np.mean([r['avg_chg'] for r in top3])
        if avg_top > 2:
            return MarketSignal('板块', '看多', f"主线明确，领涨板块均涨{avg_top:.1f}%", min(1.0, avg_top / 5))
        if avg_top < -2:
            return MarketSignal('板块', '看空', f"板块普跌，领涨板块也仅{avg_top:.1f}%", max(-1.0, avg_top / 5))
        return MarketSignal('板块', '中性', f"板块轮动一般，头部均涨{avg_top:.1f}%", 0.0)

    def _check_northbound(self, date) -> MarketSignal:
        rows = self.db.fetch_all("""
            SELECT net_buy FROM northbound_flow
            WHERE date <= %s
            ORDER BY date DESC LIMIT 5
        """, (date,))
        if not rows:
            return MarketSignal('北向资金', '中性', '北向数据不足', 0.0)
        latest = rows[0]['net_buy']
        if latest is None:
            return MarketSignal('北向资金', '中性', '北向数据缺失', 0.0)
        if latest > 20e8:
            return MarketSignal('北向资金', '看多', f'北向大幅净流入{latest/1e8:.0f}亿', 0.8)
        if latest < -20e8:
            return MarketSignal('北向资金', '看空', f'北向大幅净流出{abs(latest)/1e8:.0f}亿', -0.8)
        return MarketSignal('北向资金', '中性', f'北向小幅{("流入" if latest > 0 else "流出")}{abs(latest)/1e8:.0f}亿', 0.0)
