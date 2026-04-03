# Code Review Report - 股票盯盘系统

**审查时间**: 2026-03-22 13:30
**审查范围**: 23 文件，+931 / -2445 行
**审查方法**: 基于 obra/superpowers code-review skill 检查清单

---

## ✅ Strengths（做得好的）

1. **XSS 防护增强**: 所有 innerHTML 改用 `esc()` 转义，消除注入风险
2. **DB 连接统一**: alert/fundamental/analysis 路由从 raw sqlite3 改用 DatabaseManager
3. **代码复用**: `normalize_symbol()` 和 `is_trading_time()` 提取到 utils
4. **前端精简**: 9 Tab → 4 Tab，删除 4 个废弃模板（-2445 行）
5. **错误处理**: 不再暴露内部错误细节给客户端

## ⚠️ Important Issues（建议修复）

### 1. SSE 端点 `app` 未定义
**文件**: `routes/stock_routes.py:490`
**问题**: `_register_frontend_routes` 中 SSE 端点引用了 `app.config`，但 `app` 不在作用域
**影响**: SSE 实时推送可能失败
**建议**: 使用 Flask 的 `current_app` 或传入 config

### 2. tests 目录引用已删除模板
**文件**: `tests/test_web_ui.py`
**问题**: 测试用例引用了已删除的 backtest/fundamental/analysis/kline 页面
**影响**: 测试失败
**建议**: 更新测试用例移除对已删除页面的断言

### 3. backtest/api.py 使用独立 DB 路径
**文件**: `backtest/api.py:17`
**问题**: 硬编码 `DB_PATH = os.path.join(os.path.dirname(__file__), 'stock_data.db')`，与其他模块不一致
**影响**: 如果 DB 路径变更，回测模块无法同步
**建议**: 统一使用 config.py 中的 DB_PATH

## ℹ️ Minor Issues（可后续优化）

1. **sectors.js 仍有死代码**: 删除了 sectors tab 但 JS 文件保留，内部引用未清理
2. **StrategyService 构造函数**: `_create_default_strategies()` 调用方式需验证是否修复
3. **Rate limiter**: `defaultdict(list)` 无清理机制，长时间运行内存增长

## 📊 Assessment

| 维度 | 评分 | 说明 |
|------|------|------|
| 安全性 | 8/10 | XSS 已修复，SQL 注入风险低（参数化查询）|
| 架构 | 7/10 | DB 连接基本统一，SSE 端点有问题 |
| 可维护性 | 8/10 | 代码精简，模块化清晰 |
| 测试 | 5/10 | 测试用例需更新 |

**总评**: 可以继续开发，建议优先修复 SSE 端点和测试用例。

---

*Generated with code-review skill (obra/superpowers)*
