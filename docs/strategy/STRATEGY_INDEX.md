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
| 1 | **Fstop3_pt5 v10** | RSI<18 + BB触底 + 放量1.5x | 止损3%/止盈5% | ≥50% | TOP300 | 2026-04-02 | 🟢 实盘 |

---

## 待上线候选策略（三阶段全合格）

按测试期胜率排序：

| # | 策略名 | 训练 | 验证 | 测试 | 测试笔数 | 测试夏普 | 弱市类型 | 来源 | 备注 |
|---|--------|------|------|------|----------|----------|---------|------|------|
| 1 | BB1.02 + KDJ Oversold + RSI<20 + TOP500 + 10天 | 55.0% | 68.3% | **71.3%** | 167 | 2.67 | width70 | [报告](../backtesting/reports/bb_kdj_rsi_weak_report.md) | 测试期胜率最高 |
| 2 | BB1.02 + KDJ Oversold + RSI<20 + TOP300 + 7天 | 56.2% | 64.9% | **63.6%** | 110 | 2.77 | width70 | [报告](../backtesting/reports/bb_kdj_rsi_weak_report.md) | TOP300，稳健 |
| 3 | BB1.02 + KDJ Oversold + RSI<20 + TOP500 + 7天 | 56.9% | 67.0% | **63.6%** | 187 | 2.59 | width70 | [报告](../backtesting/reports/bb_kdj_rsi_weak_report.md) | 样本最大 |
| 4 | BB1.02 + KDJ Oversold + RSI<20 + TOP200 + 7天 | 56.2% | 66.3% | **60.0%** | 70 | 2.62 | width70 | [报告](../backtesting/reports/bb_kdj_rsi_weak_report.md) | TOP200，防御型 |

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

- [Fstop3_pt5 v10 策略手册](Fstop3_pt5_v10.md)
- [Fstop3_pt5 v10 回测报告](../backtesting/reports/Fstop3_pt5_v10.md)
- [EVAL_FRAMEWORK.md](../EVAL_FRAMEWORK.md)
- [评估框架说明](../../EVAL_FRAMEWORK.md)
- [scripts/bb_kdj_rsi_weak_explore.py](../../scripts/bb_kdj_rsi_weak_explore.py)

---

## 更新记录

| 日期 | 动作 |
|------|------|
| 2026-04-03 | 首次创建，纳入 Fstop3_pt5_v10 + 4个候选策略 |
