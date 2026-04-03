# 28 项股票策略评估指标

## 基础指标（7）
| 指标 | 说明 | 格式 |
|------|------|------|
| hit_stock_count | 命中股票数 | 整数 |
| total_trades | 总交易笔数 | 整数 |
| positive_rate | 正收益率（盈利笔数/总笔数×100） | 百分比 |
| avg_return | 平均收益率 | 百分比 |
| median_return | 中位数收益率 | 百分比 |
| max_return | 最高单笔收益率 | 百分比 |
| min_return | 最低单笔收益率 | 百分比 |

## 风险指标（5）
| 指标 | 说明 | 格式 |
|------|------|------|
| sharpe_ratio | 夏普比率 = mean(日超额收益) / std(日收益) × √252，无风险利率3%/年 | 小数 |
| max_drawdown | 最大回撤（累计收益曲线峰谷最大跌幅） | 百分比 |
| volatility | 年化波动率 = std(日收益) × √252 | 百分比 |
| downside_volatility | 下行波动率 = std(负日收益) × √252，正收益视作0 | 百分比 |
| sortino_ratio | 索提诺比率 = mean(日超额收益) / std(负日收益) × √252 | 小数 |

## 交易质量（8）
| 指标 | 说明 | 格式 |
|------|------|------|
| win_rate | 胜率 | 百分比 |
| profit_loss_ratio | 盈亏比（平均盈利/平均亏损） | 小数 |
| avg_win_amount | 平均盈利金额 | 百分比 |
| avg_loss_amount | 平均亏损金额 | 百分比 |
| max_single_win | 最大单笔盈利 | 百分比 |
| max_single_loss | 最大单笔亏损 | 百分比 |
| max_consec_wins | 最大连续盈利次数 | 整数 |
| max_consec_losses | 最大连续亏损次数 | 整数 |

## 效率指标（5）
| 指标 | 说明 | 格式 |
|------|------|------|
| annual_return | 年化收益率 | 百分比 |
| calmar_ratio | 卡尔马比率（年化/最大回撤） | 小数 |
| recovery_factor | 恢复因子 = (累计总收益-1) × 100 / 最大回撤 | 小数 |
| breakeven_win_rate | 盈亏平衡胜率 | 百分比 |
| expectancy | 期望值（每笔预期收益） | 百分比 |

## 稳定性（3）
| 指标 | 说明 | 格式 |
|------|------|------|
| train_test_ratio | 训练/测试收益比 | 小数 |
| stage_consistency | 三阶段一致性：三阶段胜率同正或同负=1，否则=0 | 小数 |
| avg_hold_days | 平均持仓天数 | 整数 |
