# Models — 数据模型

## 职责

Models 定义应用中所有的数据结构，全部为 Python `dataclass`。分为三类：
1. **数据类**：行情、K线、历史行情（业务数据）
2. **策略类**：策略、条件的结构化表示
3. **告警类**：告警记录、配置、飞书通知结构

所有 Model 不包含业务逻辑，只负责序列化/反序列化。

---

## 关键文件

| 文件 | 包含 |
|------|------|
| `models/__init__.py` | 导出所有 model 类 |
| `models/stock.py` | `StockQuote`、`StockHistory`、`KlineData`、`WatchlistItem`、`Sector`、`MarketIndex` |
| `models/strategy.py` | `SimpleStrategy`、`Condition`、`Action`、`ComplexStrategy`、`StrategyMatch`、`CONDITION_TYPES`、`ACTION_TYPES` |
| `models/alert.py` | `Alert`、`MultiLevelAlert`、`AlertLog`、`FeishuAlert`、`AlertConfig`、`DEFAULT_COMPLEX_STRATEGIES` |

---

## 对外接口

### 行情数据模型

```python
from models.stock import StockQuote, StockHistory, KlineData, WatchlistItem, Sector, MarketIndex

# 实时行情
quote = StockQuote(
    symbol='sz002149', name='西部材料',
    price=55.0, prev_close=54.0, chg=1.0, chg_pct=1.85,
    volume=1500000, amount=82500000,
    volume_surge=50.0,  # 派生字段：量比
    ...
)
quote.to_dict()   # -> dict
quote.from_dict(data)  # -> StockQuote

# 历史行情
history = StockHistory(symbol='sz002149', ...)  # DataFrame-based

# K 线
kline = KlineData(symbol='sz002149', period='daily', ...)
```

### 策略数据模型

```python
from models.strategy import (
    SimpleStrategy, ComplexStrategy, Condition, Action,
    CONDITION_TYPES, ACTION_TYPES
)

# 简单策略（阈值型）
simple = SimpleStrategy(id='volume_surge', label='量比>3', enabled=True, value=3.0)

# 复杂策略（多条件）
strategy = ComplexStrategy(
    id='fstop3_pt5_v10',
    name='Fstop3_pt5 策略',
    enabled=True,
    logic='AND',   # AND / OR
    conditions=[
        {'type': 'change_pct', 'operator': '>=', 'value': 5},
        {'type': 'volume_surge', 'operator': '>', 'value': 2},
    ],
    actions=[
        {'type': 'notify_feishu', 'message': '🚀 {name} 涨幅 {chg_pct}%'},
        {'type': 'alert_web', 'level': 'high'},
    ],
    last_triggered=None,
    trigger_count=0
)

# 条件类型（CONDITION_TYPES）和动作类型（ACTION_TYPES）定义了有效值
```

### 告警数据模型

```python
from models.alert import Alert, MultiLevelAlert, AlertLog, FeishuAlert, AlertConfig

# 单条告警
alert = Alert(
    id=1, timestamp=1700000000000,
    strategy_id='fstop3_pt5_v10',
    message='...', level='high',
    symbol='sz002149'
)

# 多级告警配置
config = AlertConfig(
    symbol='sz002149',
    levels=[MultiLevelAlert(...), ...]
)
```

---

## 注意事项

- 所有 `dataclass` 提供 `to_dict()` 方法用于 JSON 序列化
- `StrategyMatch` 用于封装策略匹配结果
- `DEFAULT_COMPLEX_STRATEGIES` 包含预置策略定义，是应用默认配置
- Model 层不直接访问数据库，序列化结果由 Service 层写入 DB 或返回给 Routes
