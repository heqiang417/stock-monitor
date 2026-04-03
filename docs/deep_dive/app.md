# App — Flask 主入口

## 职责

`app.py` 是整个 Web 应用的入口和工厂模块，负责：
1. **应用工厂**（`create_app()`）：构建 Flask 实例，注册所有 Blueprint、SocketIO、后台服务
2. **配置加载**：从 `config.py` 加载环境特定配置（Dev/Test/Prod）
3. **认证与限流**：全局 API Key 认证 + IP 级别速率限制
4. **WebSocket 注册**：SocketIO 事件处理器（连接/订阅/心跳）
5. **主程序运行**：`if __name__ == '__main__'` 启动服务器

---

## 关键函数

### create_app(config=None)

```python
from app import create_app
from config import Config

app, socketio, bg_service, services = create_app(Config)
```

**返回**：
- `app`：Flask 实例
- `socketio`：SocketIO 实例（用于 WebSocket 推送）
- `bg_service`：BackgroundService 实例（后台线程管理器）
- `services`：dict，含 `stock_service`、`strategy_service`、`feishu_service`、`backtest_service`

**内部流程**：
1. 配置校验（`config.validate()`）
2. 设置日志（`config.setup_logging()`）
3. 创建 Flask app + 配置 SECRET_KEY
4. CORS 配置
5. SocketIO 初始化（eventlet 模式）
6. 注册认证中间件（API Key + 限流）
7. 初始化所有 Service
8. 注册 BackgroundService 并注入 SocketIO
9. 注册所有 Blueprint
10. 注册错误处理器
11. 注册前端路由（`/`）
12. 注册健康检查（`/api/v1/health`）
13. 注册 WebSocket 事件处理

---

## 认证机制

```
请求 → before_request 拦截
       ├── 限流检查（/api/ 路径，IP 维度的滑动窗口）
       └── API Key 检查（Bearer Token 或 X-API-Key Header）
```

- API Key 来源：`config.API_KEY` 或环境变量 `API_KEY`
- 认证白名单：`/`、`/static/*`、`/api/v1/health`、`/api/health`
- 限流规则：每 IP 每 60s 最多 200 次请求，超限返回 429

---

## WebSocket 事件

由 `_register_websocket_handlers()` 注册：

| 事件 | 方向 | 说明 |
|------|------|------|
| `connect` | Client→Server | 认证+计数上限检查（MAX_WS_CLIENTS=100） |
| `disconnect` | Client→Server | 移除客户端 |
| `subscribe_price` | Client→Server | 订阅价格推送 |
| `unsubscribe_price` | Client→Server | 取消订阅 |
| `ping` | Client→Server | 心跳 |
| `market_status` | Server→Client | 连接成功时推送（交易状态+连接数） |
| `subscription_confirmed` | Server→Client | 订阅确认 |
| `price_update` | Server→Client | BackgroundService 推送实时价格 |
| `pong` | Server→Client | 心跳响应 |

---

## 配置

应用支持三个环境（定义在 `config.py`）：

| 配置 | 来源 | 说明 |
|------|------|------|
| `DB_PATH` | config | SQLite 数据库路径 |
| `API_KEY` | env / config | API 认证密钥 |
| `FEISHU_APP_ID/SECRET` | env / config | 飞书机器人凭证 |
| `CORS_ORIGINS` | config | 跨域白名单 |
| `PORT` | config | 服务端口（默认 3001） |
| `FETCH_INTERVAL` | config | 后台数据拉取间隔 |
| `MAX_WORKERS` | config | 线程池大小 |

---

## 启动方式

```bash
# 直接运行（开发）
python app.py

# gunicorn（生产）
gunicorn -k eventlet -w 1 --bind 0.0.0.0:3001 app:create_app\(\)
```

启动时 BackgroundService 自动调用 `start()` 启动后台线程。

---

## 注意事项

- 应用使用 **app factory 模式**（`create_app`），所有测试通过此接口注入 `TestingConfig`
- `SECRET_KEY` 优先从环境变量 `.env` 文件读取，回退到随机值（重启后失效）
- `bg_service.stop()` 在 `KeyboardInterrupt` 时调用，确保优雅退出
- `socketio.run()` 使用 `use_reloader=False` 避免双重启动
