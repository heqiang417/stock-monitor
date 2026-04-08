# PROJECT_STRUCTURE.md

> 股票项目结构重建蓝图（2026-04-08）

## 目标
把当前仓库稳定收敛成四层：

1. **Production**：每日运行与推送
2. **Evaluation**：统一评估与报告真源
3. **Exploration**：实验与参数搜索
4. **Archive**：历史脚本与历史报告

---

## 当前映射

### Production
- `scripts/daily/`
- `docs/ops/`
- `reports/daily_picks/`

### Evaluation
- `scripts/evaluation/`
- `docs/EVAL_FRAMEWORK.md`
- `docs/backtesting/reports/`

### Exploration
- `scripts/exploration/`

### Archive
- `docs/backtesting/archive/`
- `scripts/backtest_legacy/`

---

## 下一阶段建议

### P0（已开始）
- [x] 策略报告主线 / 历史归档分离
- [x] README 改成真实入口导向
- [x] scripts/README 改成分层说明
- [x] 当前策略状态 / cron / daily_sync 修复同步入文档

### P1（下一轮可继续）
- [ ] 新增 `docs/ops/runtime.md`，明确环境变量、日志路径、依赖项
- [ ] 给 `reports/daily_picks/` 与 `data/results/` 建立统一产物说明
- [ ] 给历史生产脚本补“deprecated”说明

### P2（代码层重构）
- [ ] 把一次性维护脚本从 `scripts/daily/` 进一步分离
- [ ] 统一 exploration 输出命名
- [ ] 统一评估输出真源路径
- [ ] 逐步压缩重复策略入口

---

## 约束原则

- 不因为“看起来更整齐”就大规模移动仍在运行的生产脚本
- 先让**文档结构、认知结构、归档边界**稳定
- 再做代码层重构

---

## 当前判断

当前仓库已经具备继续演进为“稳定产品型仓库”的条件。
重建策略应采用：

> **先认知重建，再目录重建，最后代码重建。**
