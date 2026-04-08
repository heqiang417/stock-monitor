# 策略总览

> 维护者：OpenClaw | 更新：2026-04-03 | 参考：[EVAL_FRAMEWORK.md](../EVAL_FRAMEWORK.md)

---

## 合格标准（EVAL_FRAMEWORK.md v1.5）

三阶段**全部**满足：
- 正收益率 >55%（任一阶段不达标即不合格）
- 夏普比率 >1.0
- 索提诺比率 >2.0
- 最大回撤 <50%
- 盈亏比 >1.0
- 测试笔数 >30

---

## 实盘策略

| # | 策略名 | 信号条件 | 持有规则 | 弱市 | 基本面 | 评估日期 | 状态 |
|---|--------|---------|---------|------|--------|---------|------|
| 1 | **BB1.00** | RSI<20 + BB≤1.00 | 固定7天 | ≥70% | TOP300 | 2026-04-07 | 🟢 运行中 |
| 2 | **BB1.02+KDJ** | RSI<20 + BB≤1.02 + KDJ超卖 | 固定7天 | ≥70% | TOP500 | 2026-04-07 | 🟢 运行中 |

> **注**：Fstop3_pt5 v10 已于 2026-04-08 降级为历史/对照策略，不再属于正式每日策略池。原因：train 阶段正率 49.1% < 55%，且 test 样本仅 19 笔，不满足项目上线标准。

---

## 当前搜索状态（2026-04-08）

### 已确认结论
- 三方向搜索（strict market filter / capital flow filter / dynamic position sizing）已完成收口。
- **结论：本轮无可直接上线候选。**
- 主要原因不是收益率先不够，而是**测试集样本远不足 30**：
  - direction1 `strict_market_filter`：train 100 / val 81 / test 1
  - direction2 `capital_flow_filter`：train 116 / val 86 / test 3
  - direction3 `dynamic_position_sizing`：train 83 / val 81 / test 1

### 下一轮方向
- 搜索目标已从“继续增强过滤”调整为：
  1. **样本优先**：train / val / test 都要 >= 30
  2. **三阶段正率优先**：三阶段都 > 55%
  3. **稳定性优先**：优先三阶段 spread 小的方案，最后才看 test Sharpe
- 已新增脚本：`scripts/exploration/explore_direction_6_sample_first.py`
- 当前方向：**宽入口 + 轻过滤 + 稳定性排序**

---

## 待上线候选策略（三阶段全合格）

按测试期胜率排序：

| # | 策略名 | 训练 | 验证 | 测试 | 测试笔数 | 测试夏普 | 弱市类型 | 手册 |
|---|--------|------|------|------|----------|----------|---------|------|
| 1 | **BB1.00** RSI<20 + BB≤1.00 + 弱市70% + TOP300 + 7天 | 57.7% | 74.7% | **69.2%** | 52 | 3.26 | width70 | [手册](BB1.00/README.md) |
| 2 | BB1.02 + KDJ Oversold + RSI<20 + TOP500 + 10天 | 55.0% | 68.3% | **71.3%** | 167 | 2.67 | width70 | [报告](../backtesting/reports/bb_kdj_rsi_weak_report.md) |
| 3 | BB1.02 + KDJ Oversold + RSI<20 + TOP300 + 7天 | 56.2% | 64.9% | **63.6%** | 110 | 2.77 | width70 | [报告](../backtesting/reports/bb_kdj_rsi_weak_report.md) |
| 4 | BB1.02 + KDJ Oversold + RSI<20 + TOP500 + 7天 | 56.9% | 67.0% | **63.6%** | 187 | 2.59 | width70 | [报告](../backtesting/reports/bb_kdj_rsi_weak_report.md) |
| 5 | **BB0.99** RSI<20 + BB≤0.99 + 弱市70% + TOP300 + 7天 | 61.1% | 81.4% | **64.5%** | 31 | 2.67 | width70 | [手册](BB0.99/README.md) |
| 6 | BB1.02 + KDJ Oversold + RSI<20 + TOP200 + 7天 | 56.2% | 66.3% | **60.0%** | 70 | 2.62 | width70 | [报告](../backtesting/reports/bb_kdj_rsi_weak_report.md) |

---

## 历史策略（已废弃或未达标）

| 策略名 | 失败原因 | 备注 |
|--------|---------|------|
| 经典6策略 MACD crossover | 验证期/测试期不合格 | 2026-03-20 |
| 全量6策略 RSI均值回归 | 测试期正率<55% | 2026-03-20 |
| ADX+RSI 前向测试 | 部分阶段不合格 | 2026-03-20 |
| BB Break 28项指标 TOP20 | 测试期-5.9%，过拟合 | 2026-03-22 |
| MACD底背离 | 7日均益 -0.37%，无效 | 2026-04-03 |
| 放量信号(1.5x/2.0x) | 测试期笔数为0 | 2026-04-03 |
| 指数MA20弱市过滤(idx_sh000300) | 信号量为0，完全失败 | 2026-04-03 |

---

## 策略条件对比

| 维度 | Fstop3_pt5 v10 | 候选 TOP500+7天 | 候选 TOP500+10天 |
|------|----------------|----------------|----------------|
| RSI | <18 | <20 | <20 |
| 布林带 | close≤boll_lower | close≤boll_lower×1.02 | close≤boll_lower×1.02 |
| KDJ | 无 | K<20 or J<0 | K<20 or J<0 |
| 放量 | ≥1.5x | 无 | 无 |
| 弱市 | ≥50%个股<MA20 | ≥70%个股<MA20 | ≥70%个股<MA20 |
| 持有 | 止损3%/止盈5% | 固定7天 | 固定10天 |
| TOP N | TOP300 | TOP500 | TOP500 |
| 来源脚本 | daily_pick_combined.py | bb_kdj_rsi_weak_explore.py | bb_kdj_rsi_weak_explore.py |

---

## 弱市过滤说明

| 类型 | 定义 | 效果 |
|------|------|------|
| **width70** | >70%个股收盘价<MA20 | ✅ 唯一有效 |
| idx_ma20 | 沪深300<MA20 | ❌ 信号量为0 |
| 无 | 不加过滤 | ❌ 训练期<55% |

---

## 相关文档

- [Fstop3_pt5 v10 策略手册](Fstop3_pt5_v10/README.md)
- [Fstop3_pt5 v10 回测报告](../backtesting/reports/Fstop3_pt5_v10.md)
- [BB1.00 策略手册](BB1.00/README.md)
- [BB1.00 回测报告](BB1.00/backtest_report.md)
- [BB0.99 策略手册](BB0.99/README.md)
- [BB0.99 回测报告](BB0.99/backtest_report.md)
- [EVAL_FRAMEWORK.md](../EVAL_FRAMEWORK.md)

---

## 更新记录

| 日期 | 动作 |
|------|------|
| 2026-04-08 | Fstop3_pt5 降级为历史/对照策略，正式每日策略池收缩为 BB1.00 + BB1.02+KDJ（2只） |
| 2026-04-08 | 补充当前搜索状态：三方向搜索无上线候选，下一轮改为样本优先搜索 |
| 2026-04-07 | Fstop3 评估 / 报告 / daily_push 指标口径统一 |
| 2026-04-03 | 首次创建，纳入 Fstop3_pt5_v10 + 4个候选策略 |
| 2026-04-03 | 新增 BB1.00 + BB0.99 策略手册和回测报告，纳入候选列表 |
