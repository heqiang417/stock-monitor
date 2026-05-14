# 股票盯盘系统

> A 股选股辅助系统：负责基础/扩展行情同步、策略评估、盘后选股与飞书文本推送。

---

## 1. 当前生产主链路

每天真实运行的主线：

1. `17:00` `scripts/daily/update_tencent.py`
   - 同步日 K、指数 K、MA、RSI、BB、PE/PB 等基础数据
2. `17:30` `scripts/daily/daily_sync.py`
   - 同步北向、两融、涨跌停、资金流、行业等扩展数据
3. `20:30` `scripts/daily/daily_pick_combined.py --push --wait`
   - 校验数据完整性
   - 执行正式策略
   - 发送飞书纯文本推送

当前正式策略：
- `BB1.00`
- `BB1.02+KDJ`
- `TP4.5`

策略配置统一放在：
- `configs/strategy/bb100.yaml`
- `configs/strategy/bb102_kdj.yaml`
- `configs/strategy/tp45.yaml`

统一加载入口：`configs/strategy_loader.py`

---

## 2. 根目录每个文件 / 文件夹用途

| 路径 | 类型 | 作用 |
|---|---|---|
| `app.py` | 文件 | Flask 应用主入口，负责创建 app、初始化服务、注册蓝图和 websocket |
| `config.py` | 文件 | 全局配置定义，包含数据库、日志、认证、运行参数 |
| `requirements.txt` | 文件 | Python 依赖列表 |
| `pyproject.toml` | 文件 | Python 项目元数据与开发工具配置 |
| `Makefile` | 文件 | 常用命令入口，如 `make pick / sync / eval / test / lint / run` |
| `Dockerfile` | 文件 | Docker 镜像构建配置 |
| `docker-compose.yml` | 文件 | 本地/部署环境编排配置 |
| `package_for_review.sh` | 文件 | 打包项目用于审阅/归档的辅助脚本 |
| `.env.example` | 文件 | 环境变量模板 |
| `.env` | 文件 | 本地环境变量文件 |
| `.gitignore` | 文件 | Git 忽略规则 |
| `.dockerignore` | 文件 | Docker 构建忽略规则 |
| `.coveragerc` | 文件 | 测试覆盖率配置 |
| `.coverage` | 文件 | 本地测试覆盖率产物，不属于业务源码 |
| `.secret_key` | 文件 | 本地 secret key 文件 |
| `feishu_config.json` | 文件 | 飞书推送配置 |
| `stock_data.db` | 文件 | 根目录 SQLite 数据库，当前仍被部分回测/服务旧代码引用 |
| `stock_data_full.json` | 文件 | 历史全量股票 JSON 数据文件，当前仍被 `services/market_service.py` 默认读取 |
| `stocks.db` | 文件 | 额外数据库文件，当前未发现明确代码引用，偏历史残留 |
| `backtest/` | 目录 | 回测引擎、回测 API 与部分历史回测产物 |
| `configs/` | 目录 | 配置代码与策略 YAML |
| `data/` | 目录 | 当前主数据目录，包含 `data/stock_data.db` 等真实运行数据资产 |
| `data_provider/` | 目录 | 数据抓取层，封装 Tencent/Akshare/Baostock/Tushare 等来源 |
| `db/` | 目录 | 数据库辅助模块与历史数据库文件 |
| `docs/` | 目录 | 文档中心：策略、评估、运维、结构、迁移审计 |
| `models/` | 目录 | 数据模型定义 |
| `reports/` | 目录 | 运行过程中的输出/失败记录目录 |
| `routes/` | 目录 | Flask API 路由层 |
| `run_tests.sh` | 文件 | 测试执行辅助脚本 |
| `scripts/` | 目录 | 生产、评估、迁移、报表相关脚本 |
| `services/` | 目录 | 业务服务层 |
| `static/` | 目录 | Web 静态资源 |
| `templates/` | 目录 | Flask HTML 模板 |
| `tests/` | 目录 | 自动化测试 |
| `utils/` | 目录 | 通用工具模块，目前内容较少 |
| `.venv/` | 目录 | Hermes 当前使用的本地虚拟环境/工具环境，不属于业务代码 |
| `venv/` | 目录 | 旧本地虚拟环境，已尝试清理，但仍被 FUSE 占用残留阻塞完全删除 |
| `__pycache__/` | 目录 | Python 字节码缓存，不属于源码 |

---

## 3. 逐目录说明（按阅读优先级）

### 3.1 `scripts/` —— 你最该先看的目录

#### `scripts/daily/`
生产主链路目录。

关键文件：
- `update_tencent.py`：基础日线/指标同步入口
- `daily_sync.py`：扩展数据同步入口
- `daily_pick_combined.py`：正式每日选股入口
- `sync_health.py`：同步健康检查
- `check_strategy_consistency.py`：策略口径一致性检查
- `calc_*.py`：各类指标/特征补算脚本，如 ATR、ADX、OBV、BB 宽度等

#### `scripts/evaluation/`
- `strategy_evaluator.py`：统一策略评估入口

#### `scripts/migration/`
- `sqlite_to_postgres.py`：SQLite → PostgreSQL 迁移脚本
- `postgres_schema.sql`：PostgreSQL schema
- `postgres_schema_partitioned.sql`：分区版 schema
- `README_postgres_migration.md`：迁移说明

#### `scripts/reports/`
- `daily_picks/*.json`：历史每日推送结果留痕

#### `scripts/README.md`
- 脚本分层说明文档

---

### 3.2 `services/` —— 业务逻辑核心层

关键文件：
- `stock_service.py`：股票数据查询与主业务服务
- `market_service.py`：市场数据装载与行业/市场信息服务
- `strategy_service.py`：策略管理与执行协调
- `background_service.py`：后台任务与推送调度
- `feishu_service.py`：飞书消息发送
- `backtest_service.py`：回测服务封装
- `quote_service.py`：行情报价相关服务
- `market_state.py`：市场状态判断
- `signal_standardizer.py`：策略信号标准化
- `dashboard_formatter.py`：面板输出格式化
- `news_sentiment.py`：新闻情绪相关处理

---

### 3.3 `routes/` —— Flask API 路由层

关键文件：
- `routes/__init__.py`：蓝图注册入口
- `stock_routes.py`：股票相关接口
- `strategy_routes.py`：策略相关接口
- `analysis_routes.py`：分析类接口
- `dashboard_routes.py`：仪表盘接口
- `kline_routes.py`：K 线接口
- `fundamental_routes.py`：基本面接口
- `alert_routes.py`：预警接口
- `db_routes.py`：数据库相关接口
- `backtest_routes.py`：回测接口

---

### 3.4 `backtest/` —— 回测代码与历史产物

关键文件：
- `engine.py`：回测引擎核心
- `api.py`：回测 API/辅助接口
- `agent_backtest.py`：脚本化回测入口
- `trades_v10_Fstop3_pt5.json`：历史交易明细产物

说明：
- 当前这里还存在“代码”和“历史产物”混放的问题
- 且有旧代码仍默认引用根目录 `stock_data.db`

---

### 3.5 `configs/` —— 统一配置层

关键文件：
- `strategy_loader.py`：策略 YAML 统一加载器
- `strategy/bb100.yaml`：BB1.00 配置
- `strategy/bb102_kdj.yaml`：BB1.02+KDJ 配置
- `strategy/tp45.yaml`：TP4.5 配置

---

### 3.6 `data/` —— 当前真实数据目录

你现在的运行主链路主要依赖这里，而不是根目录那些历史数据文件。

关键内容：
- `data/stock_data.db`：当前主 SQLite 数据库
- `data/stock_data_ro.db`：只读/辅助数据库
- `data/results/`：部分结果数据
- `failed_*.txt`：同步失败记录
- 若干 `*.json`：中间数据与统计结果

---

### 3.7 `docs/` —— 文档中心

建议优先阅读：
- `docs/strategy/STRATEGY_INDEX.md`：策略总览
- `docs/EVAL_FRAMEWORK.md`：统一评估框架
- `docs/ops/crontab.md`：生产 cron 说明
- `docs/PROJECT_STRUCTURE.md`：结构说明
- `docs/ops/runtime.md`：运行时说明
- `docs/pg-migration-audit-2026-04-27.md`：PG 迁移审计记录

---

### 3.8 `data_provider/` —— 数据源封装层

关键文件：
- `manager.py`：数据源管理
- `base.py`：抽象基类
- `tencent_fetcher.py`
- `akshare_fetcher.py`
- `baostock_fetcher.py`
- `efinance_fetcher.py`
- `tushare_fetcher.py`

---

### 3.9 `models/`
关键文件：
- `stock.py`
- `strategy.py`
- `alert.py`

---

### 3.10 `tests/`
关键文件：
- `test_daily_pick_yaml_integration.py`：策略 YAML 集成测试
- `test_web_ui.py`：Web UI 测试（Playwright 可选依赖）
- `test_api.py`：API 测试
- `test_backtest_engine.py`：回测引擎测试
- `test_backtest_service.py`：回测服务测试
- `test_stock_service.py`：股票服务测试
- `test_market_service.py`：市场服务测试
- `test_strategy_service.py`：策略服务测试
- `test_background_service.py`：后台服务测试
- `test_feishu_service.py`：飞书服务测试
- `test_strategies.py`：策略逻辑测试
- `test_utils.py`：工具测试
- `conftest.py`：pytest 公共 fixture

---

### 3.11 `static/` 和 `templates/`
- `templates/index.html`：前端页面模板
- `static/js/`、`static/css/`、`static/icons/`：前端静态资源
- `static/manifest.json`、`service-worker.js`：PWA 相关资源

说明：
- 我已经删除了 `static/stock-monitor-app-py.tar.gz`，因为它是打包产物，不应该放在这里

---

## 4. 这次新增清理结果

### 第一轮已删
- `.pytest_cache/`
- `logs/`
- `results/`
- `app.log`
- `app.log.1`
- `backtest/agent_backtest.py.subagent_broken`

### 第二轮已删
- `.gstack/`
- `.hermes/`
- `.fuse_hidden0000033b0000032b`（根目录残留）
- `static/stock-monitor-app-py.tar.gz`

---

## 5. 目前还没直接删、但已经确认值得继续处理的对象

### `stocks.db`
- 目前没搜到明确代码引用
- 很像历史残留
- **倾向后续删除**

### `venv/`
- 我已经尝试删除
- 但内部不断生成 `.fuse_hidden*` 残留，说明仍有进程占用
- 这属于你这个环境里之前提到过的 FUSE/pycache 类问题
- **需要等占用进程退出后再删**

### `__pycache__/`
- 仍是缓存目录
- 可以清，但最好在确认无进程占用时统一删

### 根目录 `stock_data.db`
- 暂时不能删
- 因为 `services/backtest_service.py` 与 `backtest/engine.py` 仍直接默认引用它

### 根目录 `stock_data_full.json`
- 暂时不能删
- 因为 `services/market_service.py` 默认仍从这里读取

---

## 6. 目前仓库里最值得继续优化的结构问题

1. **历史路径仍混用**
   - 生产主链路多数已经走 `data/stock_data.db`
   - 但回测/市场服务仍有部分旧代码引用根目录 `stock_data.db` 和 `stock_data_full.json`

2. **回测目录混放**
   - `backtest/` 同时放代码和历史交易 JSON

3. **本地环境残留未完全去除**
   - `venv/`
   - `__pycache__/`
   - 新生成的 `.fuse_hidden*`

---

## 7. 快速阅读顺序

如果你要快速理解这个项目，建议按这个顺序看：

1. `README.md`
2. `docs/strategy/STRATEGY_INDEX.md`
3. `docs/EVAL_FRAMEWORK.md`
4. `docs/ops/crontab.md`
5. `scripts/daily/daily_pick_combined.py`
6. `configs/strategy/*.yaml`
7. `services/stock_service.py`

---

## 8. 当前结论

这次已经把 README 从“抽象结构说明”升级成了：
- 根目录逐项说明
- 关键目录逐项说明
- 关键文件点名说明
- 已清理内容明确落表
- 仍有技术债的对象明确标记

如果继续收拾，下一步最值得做的是：
1. 改代码，把根目录 `stock_data.db` / `stock_data_full.json` 的旧引用迁到 `data/`
2. 然后删除 `stocks.db`
3. 等占用进程结束后彻底删除 `venv/` 与缓存残留
