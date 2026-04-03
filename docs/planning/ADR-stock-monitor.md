# Architecture Decision Record - 股票盯盘系统

## ADR-001: 前端架构

**决策**: 单页应用（SPA），原生 JS 模块化，无框架
**理由**: 轻量、无构建步骤、移动端性能好
**权衡**: 无虚拟 DOM，手动管理状态，但对本项目规模够用

```mermaid
graph TB
    subgraph "Client Layer"
        Browser[浏览器 / PWA]
    end

    subgraph "Frontend (单页应用)"
        index[index.html<br/>4 Tab 容器]
        app[app.js<br/>状态管理 + API + WebSocket]
        dashboard[dashboard.js<br/>大盘 + 摘要]
        watchlist[watchlist.js<br/>自选 + K线弹窗]
        strategies[strategies.js<br/>策略 + 回测]
        alerts[alerts.js<br/>告警历史]
    end

    subgraph "Backend (Flask)"
        flask[app.py<br/>应用工厂]
        stock_bp[stock_v1<br/>股票/搜索/SSE]
        strategy_bp[strategy_v1<br/>策略/扫描]
        alert_bp[alert_v1<br/>告警/飞书]
        kline_bp[kline_v1<br/>K线/指标]
        backtest_bp[backtest<br/>回测引擎]
        fundamental_bp[fundamental_v1<br/>基本面]
        analysis_bp[analysis<br/>Walk-Forward]
    end

    subgraph "Service Layer"
        stock_svc[StockService<br/>数据获取+扫描]
        strategy_svc[StrategyService<br/>策略评估]
        bg_svc[BackgroundService<br/>定时任务+推送]
        quote_svc[QuoteService<br/>行情API]
    end

    subgraph "Data Layer"
        sqlite[(SQLite<br/>WAL模式)]
        json_files[JSON 文件<br/>策略/结果]
    end

    subgraph "External"
        tencent[腾讯财经 API]
        feishu[飞书 API]
    end

    Browser --> index
    index --> app
    app --> dashboard & watchlist & strategies & alerts
    app --> flask
    flask --> stock_bp & strategy_bp & alert_bp & kline_bp & backtest_bp & fundamental_bp & analysis_bp
    stock_bp & strategy_bp & alert_bp & kline_bp --> stock_svc & strategy_svc
    bg_svc --> stock_svc & strategy_svc & quote_svc
    stock_svc & strategy_svc & bg_svc --> sqlite
    quote_svc --> tencent
    bg_svc --> feishu
    backtest_bp --> sqlite
    fundamental_bp & analysis_bp --> sqlite
```

## ADR-002: 数据库访问

**问题**: `fundamental_routes.py`、`analysis_routes.py`、`alert_routes.py` 使用 raw `sqlite3.connect()` 而非 `DatabaseManager`
**决策**: 统一使用 `DatabaseManager`，消除连接管理分散
**状态**: ✅ 已修复

## ADR-003: API 路由命名

**问题**: v1 和 legacy 路由混用，部分重复
**决策**: 新接口用 `/api/v1/`，保留 legacy 兼容路由指向 v1 实现
**状态**: ✅ 已统一
