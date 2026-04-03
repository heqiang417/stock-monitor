"""
信号标准化模块 - 将回测结果转化为标准买卖信号
借鉴 daily_stock_analysis 的 BuySignal 枚举
"""
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional
import numpy as np


class Signal(Enum):
    """标准信号"""
    STRONG_BUY = "强烈买入"
    BUY = "买入"
    HOLD = "持有"
    WAIT = "观望"
    SELL = "卖出"
    STRONG_SELL = "强烈卖出"


class Trend(Enum):
    """趋势状态"""
    STRONG_BULL = "强势多头"
    BULL = "多头排列"
    WEAK_BULL = "弱势多头"
    CONSOLIDATION = "盘整"
    WEAK_BEAR = "弱势空头"
    BEAR = "空头排列"
    STRONG_BEAR = "强势空头"


@dataclass
class StandardizedSignal:
    """标准化信号输出"""
    symbol: str
    signal: Signal
    trend: Trend
    confidence: float  # 0-1

    # 技术指标
    rsi: Optional[float] = None
    ma5: Optional[float] = None
    ma10: Optional[float] = None
    ma20: Optional[float] = None
    ma60: Optional[float] = None
    macd_dif: Optional[float] = None
    macd_dea: Optional[float] = None

    # 买卖点位
    buy_price: Optional[float] = None
    stop_loss: Optional[float] = None
    target_price: Optional[float] = None

    # 理由
    reasons: List[str] = None

    # 市场状态影响
    market_adjusted: bool = False
    original_signal: Optional[Signal] = None

    def to_dict(self) -> Dict:
        return {
            'symbol': self.symbol,
            'signal': self.signal.value,
            'trend': self.trend.value,
            'confidence': round(self.confidence, 2),
            'rsi': self.rsi,
            'buy_price': self.buy_price,
            'stop_loss': self.stop_loss,
            'target_price': self.target_price,
            'reasons': self.reasons or [],
            'market_adjusted': self.market_adjusted,
        }

    def to_text(self) -> str:
        """格式化为文本"""
        icon = {
            Signal.STRONG_BUY: "🟢🟢",
            Signal.BUY: "🟢",
            Signal.HOLD: "⚪",
            Signal.WAIT: "🟡",
            Signal.SELL: "🔴",
            Signal.STRONG_SELL: "🔴🔴",
        }.get(self.signal, "⚪")

        lines = [f"{icon} {self.symbol} → {self.signal.value}（信心{self.confidence:.0%}）"]
        lines.append(f"   趋势: {self.trend.value}")

        if self.buy_price:
            lines.append(f"   买入价: {self.buy_price:.2f}")
        if self.stop_loss:
            lines.append(f"   止损价: {self.stop_loss:.2f}")
        if self.target_price:
            lines.append(f"   目标价: {self.target_price:.2f}")

        if self.reasons:
            for r in self.reasons[:3]:
                lines.append(f"   • {r}")

        if self.market_adjusted:
            lines.append(f"   ⚠️ 受市场状态影响: {self.original_signal.value} → {self.signal.value}")

        return "\n".join(lines)


class SignalStandardizer:
    """信号标准化器"""

    def __init__(self, db_path: str):
        self.db_path = db_path

    def analyze_stock(self, symbol: str, current_price: float = None,
                      market_regime: str = None) -> StandardizedSignal:
        """分析单只股票，输出标准化信号"""
        import sqlite3
        conn = sqlite3.connect(self.db_path)

        # 获取最近数据
        rows = conn.execute("""
            SELECT close, ma5, ma10, ma20, ma60, rsi14, chg_pct
            FROM kline_daily WHERE symbol = ?
            ORDER BY trade_date DESC LIMIT 60
        """, (symbol,)).fetchall()
        conn.close()

        if not rows:
            return StandardizedSignal(
                symbol=symbol, signal=Signal.WAIT,
                trend=Trend.CONSOLIDATION, confidence=0,
                reasons=["数据不足"]
            )

        close = rows[0][0]
        ma5 = rows[0][1]
        ma10 = rows[0][2]
        ma20 = rows[0][3]
        ma60 = rows[0][4]
        rsi = rows[0][5]
        chg_pct = rows[0][6]

        if current_price:
            close = current_price

        reasons = []
        score = 0  # -5 到 +5

        # 1. 趋势判断
        trend = self._judge_trend(ma5, ma10, ma20, ma60)
        if trend in (Trend.STRONG_BULL, Trend.BULL):
            score += 2
            reasons.append(f"{trend.value}")
        elif trend in (Trend.STRONG_BEAR, Trend.BEAR):
            score -= 2
            reasons.append(f"{trend.value}")

        # 2. RSI判断
        if rsi is not None:
            if rsi < 20:
                score += 2
                reasons.append(f"RSI{rsi:.0f}严重超卖")
            elif rsi < 30:
                score += 1
                reasons.append(f"RSI{rsi:.0f}超卖")
            elif rsi > 80:
                score -= 2
                reasons.append(f"RSI{rsi:.0f}严重超买")
            elif rsi > 70:
                score -= 1
                reasons.append(f"RSI{rsi:.0f}超买")

        # 3. 乖离率（不追高）
        if ma5 and close:
            bias = (close - ma5) / ma5 * 100
            if bias > 5:
                score -= 1
                reasons.append(f"乖离率{bias:.1f}%超阈值，不追高")
            elif -2 < bias < 2:
                reasons.append(f"乖离率{bias:.1f}%合理")

        # 4. 近期涨跌
        if len(rows) >= 5:
            pct5 = sum(r[6] for r in rows[:5] if r[6]) / 5
            if pct5 > 5:
                score -= 1
                reasons.append(f"5日均涨{pct5:.1f}%，短期过热")
            elif pct5 < -5:
                score += 1
                reasons.append(f"5日均跌{pct5:.1f}%，超跌反弹")

        # 转为信号
        signal = self._score_to_signal(score)

        # 市场状态调整
        original_signal = signal
        if market_regime:
            signal = self._adjust_by_market(signal, market_regime)
            if signal != original_signal:
                pass  # market_adjusted 标记在下面

        # 计算买卖点
        buy_price = ma5 if ma5 else close
        stop_loss = buy_price * 0.95  # 5%止损
        target_price = buy_price * 1.10  # 10%止盈

        confidence = min(1.0, abs(score) / 5 * 0.5 + 0.3)

        return StandardizedSignal(
            symbol=symbol,
            signal=signal,
            trend=trend,
            confidence=confidence,
            rsi=rsi,
            ma5=ma5, ma10=ma10, ma20=ma20, ma60=ma60,
            buy_price=round(buy_price, 2) if buy_price else None,
            stop_loss=round(stop_loss, 2) if stop_loss else None,
            target_price=round(target_price, 2) if target_price else None,
            reasons=reasons,
            market_adjusted=(signal != original_signal),
            original_signal=original_signal if signal != original_signal else None,
        )

    def _judge_trend(self, ma5, ma10, ma20, ma60) -> Trend:
        """判断趋势"""
        if not all([ma5, ma10, ma20]):
            return Trend.CONSOLIDATION

        if ma5 > ma10 > ma20:
            if ma60 and ma20 > ma60:
                return Trend.STRONG_BULL
            return Trend.BULL
        elif ma5 < ma10 < ma20:
            if ma60 and ma20 < ma60:
                return Trend.STRONG_BEAR
            return Trend.BEAR
        elif ma5 > ma10:
            return Trend.WEAK_BULL
        elif ma5 < ma10:
            return Trend.WEAK_BEAR
        return Trend.CONSOLIDATION

    def _score_to_signal(self, score: int) -> Signal:
        """分数转信号"""
        if score >= 3:
            return Signal.STRONG_BUY
        elif score >= 1:
            return Signal.BUY
        elif score <= -3:
            return Signal.STRONG_SELL
        elif score <= -1:
            return Signal.SELL
        return Signal.HOLD

    def _adjust_by_market(self, signal: Signal, regime: str) -> Signal:
        """根据市场状态调整信号"""
        if regime == "防守":
            # 防守时降级买入信号
            if signal == Signal.STRONG_BUY:
                return Signal.BUY
            elif signal == Signal.BUY:
                return Signal.WAIT
        elif regime == "进攻":
            # 进攻时升级买入信号
            if signal == Signal.HOLD:
                return Signal.BUY
        return signal
