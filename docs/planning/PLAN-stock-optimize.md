# Implementation Plan - 股票盯盘系统优化

> 按 superpowers methodology：每个任务 2-5 分钟，精确文件路径，TDD

## Task 1: 修复测试用例（test_web_ui.py）
- **文件**: `tests/test_web_ui.py`
- **问题**: 引用已删除的 backtest/fundamental/analysis/kline 页面
- **修复**: 更新测试用例，移除对已删除路由的断言，只测试 `/` 和 `/api/*` 路由
- **验证**: `pytest tests/test_web_ui.py` 全部通过
- **耗时**: 2 分钟

## Task 2: 修复 SSE 端点 app 未定义（stock_routes.py）
- **文件**: `routes/stock_routes.py`
- **问题**: `_register_frontend_routes` 中 SSE 端点引用 `app.config`，`app` 不在作用域
- **修复**: 使用 Flask `current_app` 或将 config 作为参数传入
- **验证**: SSE 端点返回 200，Content-Type 为 text/event-stream
- **耗时**: 3 分钟

## Task 3: 统一回测模块 DB 路径（backtest/api.py）
- **文件**: `backtest/api.py`
- **问题**: 硬编码 `DB_PATH`，与其他模块不一致
- **修复**: 使用 config.py 中的 DB_PATH
- **验证**: 回测 API 正常返回数据
- **耗时**: 2 分钟

## Task 4: 清理 sectors.js 死代码
- **文件**: `static/js/sectors.js`
- **问题**: 删除了 sectors tab 但 JS 保留了完整组件代码
- **修复**: 保留需要的 stock detail 逻辑，移除无用的 tab 渲染和路由跳转
- **验证**: 页面无 JS 错误
- **耗时**: 3 分钟

## Task 5: 补充单元测试（策略扫描 + K线计算）
- **文件**: `tests/test_strategy_scan.py`（新建）
- **目标**: 测试策略扫描逻辑、K线 MA/RSI 计算
- **验证**: 新增 ≥20 个测试用例通过
- **耗时**: 5 分钟

## 完成标准
- [ ] `pytest tests/` 全部通过（0 errors）
- [ ] `curl localhost:3001` 返回 200
- [ ] SSE 端点正常工作
- [ ] 无 JS 控制台错误
