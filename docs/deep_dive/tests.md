# Tests — 测试套件

## 职责

Tests 模块为项目提供自动化测试覆盖，包括单元测试、集成测试和 Web UI 测试。所有测试使用 pytest 框架，通过 Flask app factory 模式注入测试配置，实现与生产代码的隔离。

---

## 关键文件

| 文件 | 作用 |
|------|------|
| `tests/conftest.py` | pytest 配置 + 所有共享 fixtures（app、db、services、mock 数据） |
| `tests/test_api.py` | API 端点测试（策略增删改、指数获取等） |
| `tests/test_strategies.py` | 策略评估逻辑测试 |
| `tests/test_stock_service.py` | StockService 单元测试 |
| `tests/test_strategy_service.py` | StrategyService 单元测试 |
| `tests/test_market_service.py` | MarketService 单元测试 |
| `tests/test_backtest_service.py` | BacktestService 单元测试 |
| `tests/test_backtest_engine.py` | 回测引擎核心逻辑测试 |
| `tests/test_feishu_service.py` | 飞书服务 Mock 测试 |
| `tests/test_background_service.py` | 后台服务线程测试 |
| `tests/test_utils.py` | 工具函数测试（`is_trading_time`、`normalize_symbol`） |
| `tests/test_optimization.py` | 策略优化相关测试 |
| `tests/test_web_ui.py` | Web 前端 UI 测试 |

---

## 对外接口（Fixtures）

`conftest.py` 提供的 fixtures 可在任何测试文件中直接使用：

```python
import pytest

# 临时数据库（session 级，共用）
def test_something(temp_db_path):
    ...

# 每个测试函数独立数据库连接
def test_alerts(db_connection):
    cursor = db_connection.cursor()
    cursor.execute('SELECT * FROM alerts')
    ...

# 测试配置（覆盖 DB_PATH 等）
def test_service(test_config):
    ...

# 测试 Flask App（含 socketio、bg_service）
def test_endpoints(test_app):
    app, socketio, bg_service, services = test_app
    ...

# HTTP 测试客户端
def test_health(client):
    response = client.get('/api/v1/health')
    assert response.status_code == 200

# 真实 StockService（带临时 DB）
def test_stock_service(stock_service):
    stock_service.init_db()
    ...

# 策略 Service（使用临时 strategies.json）
def test_strategy(strategy_service):
    ...

# Mock 飞书服务
def test_feishu(mock_feishu_service):
    mock_feishu_service.send_stock_alert(...)
    ...

# 示例数据
def test_with_sample_data(sample_stock_data, sample_strategy, sample_kline_data):
    ...
```

---

## 测试配置

```python
# conftest.py 自动将项目根目录加入 sys.path
# 测试使用的 DB 路径由 test_config 提供，指向 temp_db_path
# 测试不使用真实 API（飞书、腾讯等均 mock）
```

---

## 运行方式

```bash
# 运行所有测试
./run_tests.sh

# 指定文件
pytest tests/test_utils.py -v

# 带覆盖率
pytest tests/ --cov=. --cov-report=term-missing

# 仅快速测试（跳过慢回测）
pytest tests/ -m "not slow"
```

---

## 注意事项

- 测试隔离：每个测试函数使用独立的 `db_connection` fixture（但 DB 文件在 session 内共享）
- Mock 策略：外部 API（腾讯、飞书）均使用 `MagicMock`，不发起真实网络请求
- `sample_kline_data` fixture 生成 30 天模拟 K 线数据
- `test_app` fixture 会自动清理：`bg_service.stop()`
- 测试不使用 `.env` 配置，所有关键参数通过 `test_config` fixture 注入
