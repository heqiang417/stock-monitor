"""
市场状态分析模块 - 三段式复盘（借鉴 daily_stock_analysis）
每天输出：进攻 / 均衡 / 防守，映射到仓位管理
"""
import sqlite3
import numpy as np
from dataclasses import dataclass
from enum import Enum
from typing import List, Dict, Optional, Tuple
from datetime import datetime, timedelta


class MarketRegime(Enum):
    """市场状态"""
    OFFENSIVE = "进攻"    # 指数共振上行 + 成交额放大 + 主线强化
    BALANCED = "均衡"     # 指数分化或缩量震荡
    DEFENSIVE = "防守"    # 指数转弱 + 领跌扩散


@dataclass
class MarketSignal:
    """单一信号"""
    name: str
    value: str  # "看多"/"中性"/"看空"
    detail: str
    score: float  # -1.0 ~ 1.0


@dataclass
class MarketState:
    """市场状态结果"""
    regime: MarketRegime
    signals: List[MarketSignal]
    score: float  # 综合得分 -1.0~1.0
    position_hint: str  # 仓位建议
    date: str


class MarketStateAnalyzer:
    """市场状态分析器"""

    def __init__(self, db_path: str):
        self.db_path = db_path

    def analyze(self, date: str = None) -> MarketState:
        """分析指定日期的市场状态"""
        if date is None:
            date = datetime.now().strftime('%Y-%m-%d')

        conn = sqlite3.connect(self.db_path)
        signals = []

        # 1. 趋势结构：三大指数是否同向上
        signals.append(self._check_index_trend(conn, date))

        # 2. 量能结构：成交额是否放大
        signals.append(self._check_volume(conn, date))

        # 3. 涨跌家数：市场广度
        signals.append(self._check_breadth(conn, date))

        # 4. 板块轮动：主线是否明确
        signals.append(self._check_sector_rotation(conn, date))

        # 5. 北向资金
        signals.append(self._check_northbound(conn, date))

        conn.close()

        # 综合评分
        score = np.mean([s.score for s in signals if s.score is not None])

        # 判断状态
        if score >= 0.3:
            regime = MarketRegime.OFFENSIVE
            position = "可积极操作，仓位70-100%"
        elif score <= -0.3:
            regime = MarketRegime.DEFENSIVE
            position = "控制风险，仓位0-30%"
        else:
            regime = MarketRegime.BALANCED
            position = "谨慎操作，仓位30-70%"

        return MarketState(
            regime=regime,
            signals=signals,
            score=round(score, 2),
            position_hint=position,
            date=date
        )

    def _check_index_trend(self, conn, date) -> MarketSignal:
        """检查三大指数趋势"""
        indices = ['sh000001', 'sz399001', 'sz399006']  # 上证/深证/创业板
        trends = []
        for idx in indices:
            rows = conn.execute("""
                SELECT close, ma5, ma20 FROM kline_daily
                WHERE symbol = ? AND trade_date <= ?
                ORDER BY trade_date DESC LIMIT 5
            """, (idx, date)).fetchall()
            if len(rows) >= 5:
                closes = [r[0] for r in rows]
                # 5日涨跌幅
                pct5 = (closes[0] - closes[4]) / closes[4] * 100
                trends.append(pct5)

        if len(trends) == 3:
            avg_pct = np.mean(trends)
            if all(t > 0 for t in trends):
                detail = f"三大指数齐涨，5日均涨{avg_pct:.1f}%"
                score = min(1.0, avg_pct / 5)
                value = "看多"
            elif all(t < 0 for t in trends):
                detail = f"三大指数齐跌，5日均跌{avg_pct:.1f}%"
                score = max(-1.0, avg_pct / 5)
                value = "看空"
            else:
                detail = f"指数分化，5日涨跌: {'/'.join([f'{t:.1f}%' for t in trends])}"
                score = 0.0
                value = "中性"
        else:
            detail = "数据不足"
            score = 0.0
            value = "中性"

        return MarketSignal("指数趋势", value, detail, score)

    def _check_volume(self, conn, date) -> MarketSignal:
        """检查量能结构"""
        rows = conn.execute("""
            SELECT trade_date, amount FROM kline_daily
            WHERE symbol = 'sh000001' AND trade_date <= ?
            ORDER BY trade_date DESC LIMIT 20
        """, (date,)).fetchall()
        if len(rows) < 10:
            return MarketSignal("量能", "中性", "数据不足", 0.0)

        amounts = [r[1] for r in rows if r[1] and r[1] > 0]
        if len(amounts) < 5:
            return MarketSignal("量能", "中性", "成交额数据缺失", 0.0)

        today_amt = amounts[0]
        avg5 = np.mean(amounts[1:6])
        avg20 = np.mean(amounts) if len(amounts) >= 20 else avg5

        ratio = today_amt / avg5 if avg5 > 0 else 1.0
        if ratio > 1.3:
            detail = f"放量{ratio:.1f}倍（今日{today_amt/1e8:.0f}亿 vs 5日均{avg5/1e8:.0f}亿）"
            score = min(1.0, (ratio - 1) / 2)
            value = "看多"
        elif ratio < 0.7:
            detail = f"缩量{ratio:.1f}倍（今日{today_amt/1e8:.0f}亿 vs 5日均{avg5/1e8:.0f}亿）"
            score = max(-1.0, (ratio - 1) / 2)
            value = "看空"
        else:
            detail = f"量能平稳（今日{today_amt/1e8:.0f}亿 vs 5日均{avg5/1e8:.0f}亿）"
            score = 0.0
            value = "中性"

        return MarketSignal("量能", value, detail, score)

    def _check_breadth(self, conn, date) -> MarketSignal:
        """检查涨跌家数"""
        # 用当日涨跌幅判断
        rows = conn.execute("""
            SELECT chg_pct FROM kline_daily
            WHERE trade_date = ? AND chg_pct IS NOT NULL
        """, (date,)).fetchall()

        if not rows:
            # 找最近的交易日
            rows2 = conn.execute("""
                SELECT chg_pct FROM kline_daily
                WHERE trade_date = (SELECT MAX(trade_date) FROM kline_daily WHERE trade_date <= ?)
                AND chg_pct IS NOT NULL
            """, (date,)).fetchall()
            rows = rows2

        if not rows:
            return MarketSignal("涨跌比", "中性", "数据不足", 0.0)

        chg = [r[0] for r in rows]
        up = sum(1 for c in chg if c > 0)
        down = sum(1 for c in chg if c < 0)
        limit_up = sum(1 for c in chg if c >= 9.9)
        limit_down = sum(1 for c in chg if c <= -9.9)
        total = len(chg)

        ratio = up / total if total > 0 else 0.5
        if ratio > 0.7:
            detail = f"上涨{up}只({ratio:.0%})，涨停{limit_up}只"
            score = min(1.0, (ratio - 0.5) * 2)
            value = "看多"
        elif ratio < 0.3:
            detail = f"上涨{up}只({ratio:.0%})，跌停{limit_down}只"
            score = max(-1.0, (ratio - 0.5) * 2)
            value = "看空"
        else:
            detail = f"涨跌参半，上涨{up}只/下跌{down}只，涨停{limit_up}跌停{limit_down}"
            score = (ratio - 0.5) * 2
            value = "中性"

        return MarketSignal("涨跌比", value, detail, score)

    def _check_sector_rotation(self, conn, date) -> MarketSignal:
        """检查板块轮动"""
        rows = conn.execute("""
            SELECT si.industry, AVG(k.chg_pct) as avg_chg
            FROM kline_daily k
            JOIN stock_industry si ON k.symbol = si.symbol
            WHERE k.trade_date = (SELECT MAX(trade_date) FROM kline_daily WHERE trade_date <= ?)
            AND k.chg_pct IS NOT NULL AND si.industry IS NOT NULL
            GROUP BY si.industry
            HAVING COUNT(*) >= 5
            ORDER BY avg_chg DESC
        """, (date,)).fetchall()

        if len(rows) < 5:
            return MarketSignal("板块", "中性", "板块数据不足", 0.0)

        top3 = rows[:3]
        bottom3 = rows[-3:]
        top_avg = np.mean([r[1] for r in top3])
        bottom_avg = np.mean([r[1] for r in bottom3])

        if top_avg > 2 and bottom_avg > -1:
            detail = f"领涨: {', '.join([r[0] for r in top3])}(+{top_avg:.1f}%)"
            score = min(1.0, top_avg / 5)
            value = "看多"
        elif bottom_avg < -2:
            detail = f"领跌: {', '.join([r[0] for r in bottom3])}({bottom_avg:.1f}%)"
            score = max(-1.0, bottom_avg / 5)
            value = "看空"
        else:
            detail = f"板块分化，领涨+{top_avg:.1f}%，领跌{bottom_avg:.1f}%"
            score = 0.0
            value = "中性"

        return MarketSignal("板块轮动", value, detail, score)

    def _check_northbound(self, conn, date) -> MarketSignal:
        """检查北向资金"""
        rows = conn.execute("""
            SELECT date, net_buy FROM northbound_flow
            WHERE date <= ?
            ORDER BY date DESC LIMIT 5
        """, (date,)).fetchall()

        if not rows:
            return MarketSignal("北向", "中性", "北向数据暂无", 0.0)

        net_flows = [r[1] for r in rows if r[1] is not None]
        if not net_flows:
            return MarketSignal("北向", "中性", "北向数据缺失", 0.0)

        today_flow = net_flows[0] if net_flows else 0
        avg5 = np.mean(net_flows) if net_flows else 0

        if today_flow > 0 and avg5 > 0:
            detail = f"北向净流入{today_flow/1e8:.1f}亿，5日均{avg5/1e8:.1f}亿"
            score = min(1.0, today_flow / 1e10)  # 100亿为满分
            value = "看多"
        elif today_flow < 0 and avg5 < 0:
            detail = f"北向净流出{abs(today_flow)/1e8:.1f}亿"
            score = max(-1.0, today_flow / 1e10)
            value = "看空"
        else:
            detail = f"北向{today_flow/1e8:+.1f}亿，方向不明"
            score = 0.0
            value = "中性"

        return MarketSignal("北向资金", value, detail, score)

    def to_text(self, state: MarketState) -> str:
        """格式化为文本"""
        lines = [
            f"📊 市场状态：{state.regime.value} | 综合评分 {state.score:+.2f}",
            f"仓位建议：{state.position_hint}",
            "",
        ]
        for s in state.signals:
            icon = {"看多": "🟢", "中性": "⚪", "看空": "🔴"}.get(s.value, "⚪")
            lines.append(f"{icon} {s.name}：{s.value} — {s.detail}")
        return "\n".join(lines)
