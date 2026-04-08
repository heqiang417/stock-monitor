# 回测报告整理索引

更新日期：2026-04-08

> 目的：先给 `docs/backtesting/reports/` 建立清晰索引，区分“当前有效基线”、“历史归档”、“重复/待清理”。
> 原则：**本次不直接删除历史报告**，先归类，后续再按索引清理。

---

## A. 当前保留基线（建议长期保留）

这些报告仍然和当前项目主线、策略文档或日常运行直接相关，建议保留：

| 文件 | 说明 |
|------|------|
| `Fstop3_pt5_v10.md` | 当前 Fstop3 主策略回测报告 |
| `bb_kdj_rsi_weak_report.md` | BB + KDJ + RSI 弱市系列候选的核心报告 |
| `bb_break_metrics.md` | BB 系列 28 项指标补充说明 |
| `strategy_review.md` | 阶段性策略审查与探索总结 |
| `strategy_search_v5_evaluate.md` | v5 的完整评估版，比纯搜索报告更有保留价值 |
| `README.md` | 当前目录索引说明 |

---

## B. 历史归档（建议保留，但视为旧阶段结果）

这些报告有历史价值，但不应再被当成当前主结论引用：

| 文件 | 说明 |
|------|------|
| `adx_rsi_forward_test_report.md` | 早期 ADX + RSI 方向 |
| `fundamental_strategy_report.md` | 基本面 + 技术面旧方向 |
| `new_strategy_report.md` | 综合搜索历史版本 |
| `strategy_evaluation_report.md` | 大而全评价报告，信息多但不够聚焦 |
| `strategy_search_v3_report.md` | 搜索 v3 |
| `strategy_search_v4_report.md` | 搜索 v4 |
| `strategy_search_v5_report.md` | 搜索 v5（简版） |
| `strategy_search_v6_report.md` | 搜索 v6（简版） |
| `walk_forward_report.md` | walk-forward 早期简版 |
| `walkforward_report.md` | walk-forward 搜索中期版 |
| `walkforward_search_report.md` | walk-forward 搜索详细版 |
| `pit_report.md` | PIT walk-forward 简版 |
| `pit_report_v2.md` | PIT walk-forward v2 |
| `train_val_backtest_report.md` | 训练/验证拆分旧版 |
| `train_val_v2_report.md` | 训练/测试拆分 v2 |
| `train_val_v3_report.md` | 训练/验证拆分 v3 |
| `backtest_full_summary.md` | 全量策略回测汇总 |
| `backtest_summary.md` | 经典策略回测总结 |
| `train_val_summary.md` | 与 train_val_backtest_report 主题接近，建议后续二选一 |

---

## C. 重复/待清理（建议后续重点整理）

这些文件存在命名重叠、版本边界不清、或者主题重复的问题。建议后续做一次真正清理：

| 文件组 | 问题 |
|--------|------|
| `walk_forward_report.md` / `walkforward_report.md` / `walkforward_search_report.md` | 命名不统一，内容层级重复 |
| `pit_report.md` / `pit_report_v2.md` | v1/v2 并存，应明确哪个仍有效 |
| `train_val_backtest_report.md` / `train_val_summary.md` / `train_val_v2_report.md` / `train_val_v3_report.md` | 主题高度相近，版本线混乱 |
| `strategy_search_v3_report.md` ~ `strategy_search_v6_report.md` | 搜索历史链条较长，建议只保留代表版本 |
| `full_pool_strategy_report.md` / `full_pool_v2_report.md` / `full_pool_short_hold_report.md` | 都是全股票池报告，但缺少统一入口说明 |

---

## D. 当前未纳入版本控制但建议手工判断的文件

以下文件当前是未跟踪状态，先不要直接提交，也不要急着删：

| 文件 | 建议 |
|------|------|
| `full_pool_short_hold_report.md` | 先归档判断 |
| `full_pool_strategy_report.md` | 先归档判断 |
| `full_pool_v2_report.md` | 先归档判断 |
| `optimize_report.md` | 若 short_reversal 已脱离主线，可移到历史归档区 |

---

## E. 后续整理建议

建议下一轮按这个顺序做：

1. 先统一命名：`walk_forward` vs `walkforward`
2. 再收缩重复版本：`train_val_*` / `strategy_search_v*`
3. 最后决定哪些历史报告保留在仓库，哪些移到 `docs/backtesting/archive/`

---

## 当前结论

- **当前主线报告不多，完全可以维持精简。**
- 真正乱的是：历史搜索报告、walk-forward 系列、train/val 系列。
- 本次先建立索引，不直接删除，避免误伤仍有参考价值的内容。
