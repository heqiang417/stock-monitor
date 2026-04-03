"""
Alert data models.
Defines data structures for alerts and notifications.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from datetime import datetime


@dataclass
class Alert:
    """Single alert record."""
    id: Optional[int] = None
    timestamp: int = 0
    strategy_id: str = ""
    message: str = ""
    level: str = "info"  # info, medium, high
    symbol: str = ""
    created_at: str = ""
    
    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'timestamp': self.timestamp,
            'strategy_id': self.strategy_id,
            'message': self.message,
            'level': self.level,
            'symbol': self.symbol,
            'created_at': self.created_at
        }


@dataclass
class MultiLevelAlert:
    """Multi-level alert configuration."""
    type: str  # price, chg_pct, volume
    symbol: str = ""
    message: str = ""
    level: str = "medium"  # low, medium, high
    value: float = 0.0
    threshold: float = 0.0
    
    def to_dict(self) -> dict:
        return {
            'type': self.type,
            'symbol': self.symbol,
            'message': self.message,
            'level': self.level,
            'value': self.value,
            'threshold': self.threshold
        }


@dataclass
class AlertLog:
    """Alert log entry for history."""
    time: str
    strategy: str
    count: int = 0
    stocks: List[Dict] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        return {
            'time': self.time,
            'strategy': self.strategy,
            'count': self.count,
            'stocks': self.stocks
        }


@dataclass
class FeishuAlert:
    """Feishu notification alert."""
    message: str
    level: str = "info"
    timestamp: str = ""
    sent: bool = False
    
    def to_dict(self) -> dict:
        return {
            'message': self.message,
            'level': self.level,
            'timestamp': self.timestamp,
            'sent': self.sent
        }
    
    def format_message(self) -> str:
        """Format message with level emoji."""
        level_emoji = {'high': '🔴', 'medium': '🟡', 'low': '🔵'}.get(self.level, '⚪')
        return f"{level_emoji} 【股票盯盘告警】\n{self.message}\n时间: {self.timestamp}"


@dataclass
class AlertConfig:
    """Alert configuration for a strategy."""
    price_levels: List[Dict] = field(default_factory=list)
    chg_pct_levels: List[Dict] = field(default_factory=list)
    volume_levels: List[Dict] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        return {
            'price_levels': self.price_levels,
            'chg_pct_levels': self.chg_pct_levels,
            'volume_levels': self.volume_levels
        }


# Default complex strategies
DEFAULT_COMPLEX_STRATEGIES = [
    {
        'id': 'price_breakout',
        'name': '价格突破策略',
        'enabled': True,
        'logic': 'AND',
        'conditions': [
            {'type': 'price', 'operator': '>=', 'value': 50},
            {'type': 'change_pct', 'operator': '>=', 'value': 0}
        ],
        'actions': [
            {'type': 'notify_feishu', 'message': '🚀 002149 价格突破 ¥{price}！当前价格: {price}，涨幅: {change_pct}%'},
            {'type': 'alert_web', 'level': 'high'}
        ],
        'lastTriggered': None,
        'triggerCount': 0
    },
    {
        'id': 'price_drop',
        'name': '价格跌破策略',
        'enabled': True,
        'logic': 'AND',
        'conditions': [
            {'type': 'price', 'operator': '<=', 'value': 45},
            {'type': 'change_pct', 'operator': '<=', 'value': 0}
        ],
        'actions': [
            {'type': 'notify_feishu', 'message': '⚠️ 002149 价格跌破 ¥45！当前价格: {price}，跌幅: {change_pct}%'},
            {'type': 'alert_web', 'level': 'high'}
        ],
        'lastTriggered': None,
        'triggerCount': 0
    },
    {
        'id': 'volume_surge_alert',
        'name': '成交量放量提醒',
        'enabled': False,
        'logic': 'AND',
        'conditions': [
            {'type': 'volume_surge', 'operator': '>=', 'value': 200}
        ],
        'actions': [
            {'type': 'notify_feishu', 'message': '📊 002149 成交量放大 {volume_surge}%！注意异动'},
            {'type': 'alert_web', 'level': 'medium'}
        ],
        'lastTriggered': None,
        'triggerCount': 0
    },
    # ========== 高级策略（利用K线+财务+资金数据） ==========
    {
        'id': 'ma_golden_cross',
        'name': '📈 MA金叉（5上穿20）',
        'enabled': False,
        'logic': 'AND',
        'conditions': [
            {'type': 'ma_cross', 'operator': 'golden_cross', 'value': None}
        ],
        'actions': [
            {'type': 'notify_feishu', 'message': '📈 {symbol} MA5 上穿 MA20 金叉！价格 ¥{price}'},
            {'type': 'alert_web', 'level': 'high'}
        ],
        'lastTriggered': None,
        'triggerCount': 0
    },
    {
        'id': 'rsi_oversold',
        'name': '🔄 RSI超卖（<30）+ 放量',
        'enabled': False,
        'logic': 'AND',
        'conditions': [
            {'type': 'rsi14', 'operator': '<', 'value': 30},
            {'type': 'volume_surge', 'operator': '>=', 'value': 150}
        ],
        'actions': [
            {'type': 'notify_feishu', 'message': '🔄 {symbol} RSI={rsi14} 超卖+放量！可能见底，价格 ¥{price}'},
            {'type': 'alert_web', 'level': 'high'}
        ],
        'lastTriggered': None,
        'triggerCount': 0
    },
    {
        'id': 'rsi_overbought',
        'name': '⚠️ RSI超买（>70）',
        'enabled': False,
        'logic': 'AND',
        'conditions': [
            {'type': 'rsi14', 'operator': '>', 'value': 70}
        ],
        'actions': [
            {'type': 'notify_feishu', 'message': '⚠️ {symbol} RSI={rsi14} 超买！注意回调风险，价格 ¥{price}'},
            {'type': 'alert_web', 'level': 'medium'}
        ],
        'lastTriggered': None,
        'triggerCount': 0
    },
    {
        'id': 'value_investing',
        'name': '💰 价值投资（ROE>15%+低PE+低负债）',
        'enabled': False,
        'logic': 'AND',
        'conditions': [
            {'type': 'roe', 'operator': '>', 'value': 15},
            {'type': 'profit_growth', 'operator': '>', 'value': 10},
            {'type': 'debt_ratio', 'operator': '<', 'value': 50}
        ],
        'actions': [
            {'type': 'notify_feishu', 'message': '💰 {symbol} 价值标的！ROE={roe}% 利润增长={profit_growth}% 负债率={debt_ratio}%' },
            {'type': 'alert_web', 'level': 'medium'}
        ],
        'lastTriggered': None,
        'triggerCount': 0
    },
    {
        'id': 'high_risk_warning',
        'name': '💀 高风险预警（利润暴跌+高负债）',
        'enabled': False,
        'logic': 'AND',
        'conditions': [
            {'type': 'profit_growth', 'operator': '<', 'value': -30},
            {'type': 'debt_ratio', 'operator': '>', 'value': 70}
        ],
        'actions': [
            {'type': 'notify_feishu', 'message': '💀 {symbol} 高风险！利润增长={profit_growth}% 负债率={debt_ratio}%' },
            {'type': 'alert_web', 'level': 'high'}
        ],
        'lastTriggered': None,
        'triggerCount': 0
    },
    {
        'id': 'main_capital_inflow',
        'name': '🐂 主力资金净流入',
        'enabled': False,
        'logic': 'AND',
        'conditions': [
            {'type': 'main_net_inflow', 'operator': '>', 'value': 5000},
            {'type': 'change_pct', 'operator': '>', 'value': 1}
        ],
        'actions': [
            {'type': 'notify_feishu', 'message': '🐂 {symbol} 主力净流入 {main_net_inflow}万！涨幅 {change_pct}%' },
            {'type': 'alert_web', 'level': 'medium'}
        ],
        'lastTriggered': None,
        'triggerCount': 0
    },
    {
        'id': 'good_stock_pullback',
        'name': '🎯 好股回调（ROE>15%+RSI<40）',
        'enabled': False,
        'logic': 'AND',
        'conditions': [
            {'type': 'roe', 'operator': '>', 'value': 15},
            {'type': 'rsi14', 'operator': '<', 'value': 40},
            {'type': 'change_pct', 'operator': '<', 'value': 0}
        ],
        'actions': [
            {'type': 'notify_feishu', 'message': '🎯 {symbol} 好股回调！ROE={roe}% RSI={rsi14} 跌幅{change_pct}%' },
            {'type': 'alert_web', 'level': 'high'}
        ],
        'lastTriggered': None,
        'triggerCount': 0
    },
    # ========== 量价配合 ==========
    {
        'id': 'shrink_decline',
        'name': '📉 缩量下跌（阴跌预警）',
        'enabled': False,
        'logic': 'AND',
        'conditions': [
            {'type': 'volume_ratio', 'operator': '<', 'value': 0.6},
            {'type': 'change_pct', 'operator': '<', 'value': -2}
        ],
        'actions': [
            {'type': 'notify_feishu', 'message': '📉 {symbol} 缩量下跌！量比{volume_ratio}x 跌幅{change_pct}%，可能加速下探'},
            {'type': 'alert_web', 'level': 'medium'}
        ],
        'lastTriggered': None,
        'triggerCount': 0
    },
    {
        'id': 'surge_up',
        'name': '🔥 放量上涨（主力介入）',
        'enabled': False,
        'logic': 'AND',
        'conditions': [
            {'type': 'volume_ratio', 'operator': '>', 'value': 1.5},
            {'type': 'change_pct', 'operator': '>', 'value': 3}
        ],
        'actions': [
            {'type': 'notify_feishu', 'message': '🔥 {symbol} 放量上涨！量比{volume_ratio}x 涨幅{change_pct}%，可能主力介入'},
            {'type': 'alert_web', 'level': 'high'}
        ],
        'lastTriggered': None,
        'triggerCount': 0
    },
    # ========== 均线系统 ==========
    {
        'id': 'ma_bullish',
        'name': '📈 均线多头排列',
        'enabled': False,
        'logic': 'AND',
        'conditions': [
            {'type': 'ma_arrangement', 'operator': 'bullish', 'value': None}
        ],
        'actions': [
            {'type': 'notify_feishu', 'message': '📈 {symbol} 均线多头排列！MA5>{ma5} MA10>{ma10} MA20>{ma20} MA60>{ma60}'},
            {'type': 'alert_web', 'level': 'medium'}
        ],
        'lastTriggered': None,
        'triggerCount': 0
    },
    {
        'id': 'ma20_support',
        'name': '🔄 回踩MA20支撑（买点）',
        'enabled': False,
        'logic': 'AND',
        'conditions': [
            {'type': 'low', 'operator': '<=', 'value': 0},  # placeholder, enriched
            {'type': 'price', 'operator': '>', 'value': 0},  # placeholder
            {'type': 'rsi14', 'operator': '<', 'value': 50}
        ],
        'actions': [
            {'type': 'notify_feishu', 'message': '🔄 {symbol} 回踩MA20后拉起！低点触MA20，收盘在其上，RSI={rsi14}'},
            {'type': 'alert_web', 'level': 'high'}
        ],
        'lastTriggered': None,
        'triggerCount': 0
    },
    # ========== 基本面+技术面组合 ==========
    {
        'id': 'white_horse_pullback',
        'name': '🐴 白马回调（ROE>20%+RSI<35）',
        'enabled': False,
        'logic': 'AND',
        'conditions': [
            {'type': 'roe', 'operator': '>', 'value': 20},
            {'type': 'rsi14', 'operator': '<', 'value': 35},
            {'type': 'change_pct', 'operator': '<', 'value': 0}
        ],
        'actions': [
            {'type': 'notify_feishu', 'message': '🐴 {symbol} 白马超跌！ROE={roe}% RSI={rsi14} 跌幅{change_pct}%' },
            {'type': 'alert_web', 'level': 'high'}
        ],
        'lastTriggered': None,
        'triggerCount': 0
    },
    {
        'id': 'growth_acceleration',
        'name': '🚀 成长股加速（营收>30%+趋势向上）',
        'enabled': False,
        'logic': 'AND',
        'conditions': [
            {'type': 'revenue_growth', 'operator': '>', 'value': 30},
            {'type': 'ma5', 'operator': '>', 'value': 0},  # enriched, MA5>MA20 check via ma_cross
            {'type': 'change_pct', 'operator': '>', 'value': 2}
        ],
        'actions': [
            {'type': 'notify_feishu', 'message': '🚀 {symbol} 成长加速！营收增长{revenue_growth}% 涨幅{change_pct}%' },
            {'type': 'alert_web', 'level': 'high'}
        ],
        'lastTriggered': None,
        'triggerCount': 0
    },
    # ========== 避雷/资金 ==========
    {
        'id': 'thunder_warning',
        'name': '⚡ 雷暴预警（利润暴跌+放量下跌）',
        'enabled': False,
        'logic': 'AND',
        'conditions': [
            {'type': 'profit_growth', 'operator': '<', 'value': -50},
            {'type': 'volume_ratio', 'operator': '>', 'value': 1.5},
            {'type': 'change_pct', 'operator': '<', 'value': -2}
        ],
        'actions': [
            {'type': 'notify_feishu', 'message': '⚡ {symbol} 雷暴预警！利润增长{profit_growth}% 放量跌{change_pct}%' },
            {'type': 'alert_web', 'level': 'high'}
        ],
        'lastTriggered': None,
        'triggerCount': 0
    },
    {
        'id': 'big_money_escape',
        'name': '🏃 超大单出逃（机构砸盘）',
        'enabled': False,
        'logic': 'AND',
        'conditions': [
            {'type': 'super_large_net_inflow', 'operator': '<', 'value': -10000},
            {'type': 'change_pct', 'operator': '<', 'value': -2}
        ],
        'actions': [
            {'type': 'notify_feishu', 'message': '🏃 {symbol} 机构砸盘！超大单净流出{super_large_net_inflow}万 跌幅{change_pct}%' },
            {'type': 'alert_web', 'level': 'high'}
        ],
        'lastTriggered': None,
        'triggerCount': 0
    }
]
