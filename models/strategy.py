"""
Strategy data models.
Defines data structures for simple and complex trading strategies.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any
from datetime import datetime


@dataclass
class SimpleStrategy:
    """Simple threshold-based strategy."""
    id: str
    label: str
    enabled: bool = True
    value: float = 0.0
    
    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'label': self.label,
            'enabled': self.enabled,
            'value': self.value
        }


@dataclass
class Condition:
    """Strategy condition."""
    type: str  # price, change_pct, volume, volume_surge, high, low, etc.
    operator: str  # >, >=, <, <=, ==, between
    value: Any  # scalar or list for 'between'
    
    def to_dict(self) -> dict:
        return {
            'type': self.type,
            'operator': self.operator,
            'value': self.value
        }


@dataclass
class Action:
    """Strategy action."""
    type: str  # notify_feishu, alert_web, log, sound
    message: str = ""
    level: str = "info"
    params: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> dict:
        result = {
            'type': self.type,
            'message': self.message,
            'level': self.level
        }
        result.update(self.params)
        return result


@dataclass
class ComplexStrategy:
    """Complex multi-condition strategy."""
    id: str
    name: str
    enabled: bool = True
    logic: str = "AND"  # AND, OR
    conditions: List[Dict] = field(default_factory=list)
    actions: List[Dict] = field(default_factory=list)
    last_triggered: Optional[int] = None
    trigger_count: int = 0
    
    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'name': self.name,
            'enabled': self.enabled,
            'logic': self.logic,
            'conditions': self.conditions,
            'actions': self.actions,
            'lastTriggered': self.last_triggered,
            'triggerCount': self.trigger_count
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'ComplexStrategy':
        return cls(
            id=data.get('id', ''),
            name=data.get('name', ''),
            enabled=data.get('enabled', True),
            logic=data.get('logic', 'AND'),
            conditions=data.get('conditions', []),
            actions=data.get('actions', []),
            last_triggered=data.get('lastTriggered'),
            trigger_count=data.get('triggerCount', 0)
        )


@dataclass
class StrategyMatch:
    """Result of a strategy evaluation match."""
    strategy_id: str
    strategy_name: str
    stock_symbol: str
    stock_name: str = ""
    price: float = 0.0
    chg_pct: float = 0.0
    data: Dict[str, Any] = field(default_factory=dict)
    actions: List[Dict] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        return {
            'strategy': self.strategy_name,
            'id': self.strategy_id,
            'symbol': self.stock_symbol,
            'name': self.stock_name,
            'price': self.price,
            'chg_pct': self.chg_pct,
            'data': self.data,
            'actions': self.actions
        }


# Predefined condition types for UI
CONDITION_TYPES = {
    # 基础行情
    'price': {'label': '价格', 'unit': '元', 'operators': ['>', '>=', '<', '<=', '==', 'between']},
    'change_pct': {'label': '涨跌幅', 'unit': '%', 'operators': ['>', '>=', '<', '<=', '==']},
    'volume_surge': {'label': '成交量放大', 'unit': '%', 'operators': ['>', '>=', '<', '<=']},
    'volume': {'label': '成交量', 'unit': '手', 'operators': ['>', '>=', '<', '<=']},
    'high': {'label': '最高价', 'unit': '元', 'operators': ['>', '>=', '<', '<=']},
    'low': {'label': '最低价', 'unit': '元', 'operators': ['>', '>=', '<', '<=']},
    'bid_ask_spread': {'label': '买卖价差', 'unit': '元', 'operators': ['>', '>=', '<', '<=']},
    'time': {'label': '时间', 'unit': '', 'operators': ['between', 'after', 'before']},
    'day_of_week': {'label': '星期', 'unit': '', 'operators': ['in', 'not_in']},
    # 技术指标
    'ma5': {'label': 'MA5', 'unit': '元', 'operators': ['>', '>=', '<', '<=']},
    'ma10': {'label': 'MA10', 'unit': '元', 'operators': ['>', '>=', '<', '<=']},
    'ma20': {'label': 'MA20', 'unit': '元', 'operators': ['>', '>=', '<', '<=']},
    'ma60': {'label': 'MA60', 'unit': '元', 'operators': ['>', '>=', '<', '<=']},
    'rsi14': {'label': 'RSI14', 'unit': '', 'operators': ['>', '>=', '<', '<=']},
    'ma_cross': {'label': 'MA交叉', 'unit': '', 'operators': ['golden_cross', 'death_cross']},
    # 资金面
    'main_net_inflow': {'label': '主力净流入', 'unit': '万元', 'operators': ['>', '>=', '<', '<=']},
    'main_net_inflow_pct': {'label': '主力净流入占比', 'unit': '%', 'operators': ['>', '>=', '<', '<=']},
    'super_large_net_inflow': {'label': '超大单净流入', 'unit': '万元', 'operators': ['>', '>=', '<', '<=']},
    # 量价
    'volume_ratio': {'label': '量比（vs30日均量）', 'unit': '倍', 'operators': ['>', '>=', '<', '<=']},
    'ma_arrangement': {'label': '均线排列', 'unit': '', 'operators': ['bullish', 'bearish']},
    # 基本面
    'roe': {'label': 'ROE', 'unit': '%', 'operators': ['>', '>=', '<', '<=']},
    'eps': {'label': 'EPS', 'unit': '元', 'operators': ['>', '>=', '<', '<=']},
    'profit_growth': {'label': '净利润增长', 'unit': '%', 'operators': ['>', '>=', '<', '<=']},
    'revenue_growth': {'label': '营收增长', 'unit': '%', 'operators': ['>', '>=', '<', '<=']},
    'debt_ratio': {'label': '负债率', 'unit': '%', 'operators': ['>', '>=', '<', '<=']},
    'net_margin': {'label': '净利率', 'unit': '%', 'operators': ['>', '>=', '<', '<=']},
}

ACTION_TYPES = {
    'notify_feishu': {'label': '飞书通知', 'params': ['message']},
    'alert_web': {'label': '网页告警', 'params': ['level']},
    'log': {'label': '记录日志', 'params': ['message']},
    'sound': {'label': '声音提醒', 'params': ['type']}
}
