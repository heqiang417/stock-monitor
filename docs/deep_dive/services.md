# Services — 业务服务层

## 职责

Services 是应用的核心业务逻辑层，封装数据获取、策略评估、回测执行、通知推送等具体功能。每个 Service 专注单一职责，通过组合（composition）为 Routes 层提供业务接口。

---

## 关键文件

| 文件 | 作用 |
|------|------|
| `services/stock_service.py` | **组合层**：封装 `MarketDataService` + `QuoteService`，统一提供行情、数据库、K线等操作 |
| `services/market_service.py` | 加载全市场 A 股数据，提供板块、个股信息查询 |
| `services/quote_service.py` | 腾讯财经 API 实时行情获取，带内存缓存（TTL 10s） |
| `services/strategy_service.py` | 策略加载、评估、触发；支持简单阈值策略和复杂多条件策略 |
| `services/backtest_service.py` | 回测执行，封装 `backtest.BacktestEngine` |
| `services/feishu_service.py` | 飞书消息推送（获取 access_token、发送卡片/文本消息） |
| `services/background_service.py` | **后台线程管理器**：定时拉取数据、检查策略、推送 WebSocket、发飞书通知 |
| `services/market_state.py` | 三段式市场状态判断（进攻/均衡/防守） |
| `services/news_sentiment.py` | 新闻舆情搜索与情绪判断 |
| `services/signal_standardizer.py` | 信号标准化输出 |
| `services/dashboard_formatter.py` | 仪表盘数据格式化 |
| `services/__init__.py` | 无实际代码（模块注释说明） |

---

## 对外接口

### StockService（主服务，Routes 层直接使用）

```python
from services.stock_service import StockService

stock_service = StockService(db_path, config)
stock_service.init_db()

# 行情
stock_service.fetch_tencent_data(['sz002149', 'sh600519'])  # -> List[dict]
stock_service.fetch_indexes()                               # -> List[MarketIndex]
stock_service.get_cached_quote(symbol)                      # -> dict | None

# 市场数据
stock_service.get_stock_by_symbol(symbol)                   # -> dict
stock_service.get_sectors()                                 # -> List[str]
stock_service.get_sector_stocks(sector_name)                # -> List[dict]

# 数据库
stock_service.get_history(symbol, days)                     # -> pd.DataFrame
stock_service.get_watchlist()                               # -> List[WatchlistItem]
stock_service.add_to_watchlist(symbol, name)               # -> bool

# K 线
stock_service.get_kline_data(symbol, period, adjust)        # -> pd.DataFrame
stock_service.fetch_kline_history(symbol, days)             # -> bool
```

### StrategyService

```python
from services.strategy_service import StrategyService

strategy_service = StrategyService(stock_service, strategies_file)

strategy_service.get_strategies()               # -> 所有策略
strategy_service.evaluate_all(symbol, quote)   # -> List[triggered_alerts]
strategy_service.update_simple_strategy(k, v)  # -> None
strategy_service.save_strategies()              # -> None
```

### FeishuService

```python
from services.feishu_service import FeishuService

feishu = FeishuService(app_id, app_secret, default_chat_id)
feishu.send_message(receive_id, msg_type, content)   # -> dict
feishu.send_card(receive_id, card_content)            # -> dict
feishu.send_stock_alert(alert_data)                   # -> dict
```

### BackgroundService

```python
from services.background_service import BackgroundService

bg = BackgroundService(stock_service, strategy_service, feishu_service, config)
bg.set_socketio(socketio)   # 注入 SocketIO 用于 WebSocket 广播
bg.start()                  # 启动所有后台线程
bg.stop()                   # 优雅停止

# WebSocket 客户端管理
bg.add_client(sid)
bg.remove_client(sid)
bg.connected_clients_count  # -> int
```

---

## 后台线程（BackgroundService）

BackgroundService 管理的线程包括：

| 线程 | 职责 | 触发频率 |
|------|------|----------|
| 数据拉取 | 交易时间内定期获取股票数据 | FETCH_INTERVAL（默认30s） |
| 策略检查 | 评估所有启用的策略是否触发 | 随数据拉取 |
| WebSocket推送 | 推送实时价格到连接受控客户端 | 随数据拉取 |
| 飞书通知 | 触发策略后发飞书消息（带冷却期） | 策略触发时 |
| K线收集 | 定时保存分时K线数据 | 每5分钟 |
| 日清理 | 每日收盘后清理过期数据 | 收盘后一次 |

---

## 注意事项

- `stock_service` 是组合服务，实际调用 `MarketDataService` 和 `QuoteService`
- `BackgroundService` 通过 `set_socketio()` 注入 SocketIO 实例，不在构造函数中依赖
- 飞书通知有冷却机制（`feishu_cooldown` dict），避免同一策略重复推送
- 所有 Service 共享同一个 `DatabaseManager` 实例
