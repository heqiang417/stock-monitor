# Routes — Flask 路由层

## 职责

Routes 是 Flask Blueprint 的集合，负责处理所有 HTTP/WebSocket 请求。每个子模块对应一个功能域，提供 REST API 接口供前端或外部调用。

所有 API 统一前缀 `/api/v1/`。

---

## 关键文件

| 文件 | 作用 |
|------|------|
| `routes/__init__.py` | Blueprint 注册入口，导出 6 个 `create_*_routes` 函数 |
| `routes/stock_routes.py` | 股票行情、实时价格、指数、关注列表、搜索 |
| `routes/strategy_routes.py` | 策略管理（CRUD）、扫描接口 |
| `routes/backtest_routes.py` | 回测启动、进度查询、结果获取 |
| `routes/alert_routes.py` | 告警记录查询、已读/删除 |
| `routes/kline_routes.py` | K 线数据获取（分页、前复权/后复权） |
| `routes/dashboard_routes.py` | 仪表盘聚合数据（市场状态、涨跌幅榜等） |
| `routes/fundamental_routes.py` | 基本面数据（财务、估值、股东） |
| `routes/analysis_routes.py` | 技术分析（均线、RSI、MACD、KDJ 等） |
| `routes/db_routes.py` | 数据库直接查询接口 |

---

## 对外接口

### Blueprint 创建函数

每个模块导出 `create_<name>_routes(bp)` 函数，注册到 app：

```python
# 用法（来自 app.py _register_blueprints）
from routes.stock_routes import create_stock_routes
from routes.strategy_routes import create_strategy_routes
app.register_blueprint(create_stock_routes(stock_service, strategy_service))
```

### 路由前缀

| Blueprint | URL 前缀 |
|-----------|----------|
| `stock_v1` | `/api/v1/stocks/*` |
| `strategy_v1` | `/api/v1/strategies/*` |
| `backtest_v1` | `/api/v1/backtest/*` |
| `alert_v1` | `/api/v1/alerts/*` |
| `kline_v1` | `/api/v1/kline/*` |
| `dashboard_v1` | `/api/v1/dashboard/*` |
| `fundamental_v1` | `/api/v1/fundamental/*` |
| `analysis_v1` | `/api/v1/analysis/*` |
| `db_v1` | `/api/v1/db/*` |

---

## 内部机制

- **认证**：由 `app.py` 的 `_register_auth_middleware` 统一处理，检查 `Authorization: Bearer <API_KEY>` 或 `X-API-Key` 请求头
- **限流**：每个 IP 在 1 分钟窗口内最多 200 次请求（`/api/` 路径）
- **缓存**：部分路由（如指数行情）使用内存 stale-while-revalidate 缓存（TTL 10s）
- **SSE 历史**：`stock_routes.py` 内部维护 `deque(maxlen=100)` 推送历史
- **WebSocket**：路由层不直接处理，由 `app.py` 的 `_register_websocket_handlers` 注册

---

## 注意事项

- 所有 Blueprint 由 `app.py` 的 `create_app()` 统一注册
- 每个路由函数接收 `stock_service`、`strategy_service` 等 service 实例
- `db_routes.py` 允许直接 SQL 查询，仅限本地访问（生产环境应限制）
