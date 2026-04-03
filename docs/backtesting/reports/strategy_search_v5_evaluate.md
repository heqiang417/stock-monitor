# 策略 v5 完整评估报告

评估时间: 2026-03-23 13:58:33

评估策略: rsi_macd + 基本面TOP筛选 + 7天持有

三阶段: Train(2021-01-04~2024-06-28) | Val(2024-07-01~2025-07-01) | Test(2025-08-01~2026-03-19)


---
## 策略: rsi_macd_TOP100_7d

### 各阶段概览

| 指标 | 训练期 | 验证期 | 测试期 | 全期 |
|------|--------|--------|--------|------|
| total_trades | 193 | 22 | 3 | 218 |
| positive_rate | 46.11 | 59.09 | 66.67 | 47.71 |
| avg_return | 0.7727 | 3.8666 | -0.5604 | 1.0666 |
| win_rate | 46.11 | 59.09 | 66.67 | 47.71 |

### 完整 28 项指标（全期）

#### 基础指标 (7)
| # | 指标 | 值 |
|---|------|-----|
| 1 | hit_stock_count | 169 |
| 2 | total_trades | 218 |
| 3 | positive_rate | 47.71 |
| 4 | avg_return | 1.0666 |
| 5 | median_return | -0.4013 |
| 6 | max_return | 46.6581 |
| 7 | min_return | -24.1147 |

#### 风险指标 (5)
| # | 指标 | 值 |
|---|------|-----|
| 1 | sharpe_ratio | 0.7678 |
| 2 | max_drawdown | 72.1446 |
| 3 | volatility | 8.2422 |
| 4 | downside_volatility | 3.6507 |
| 5 | sortino_ratio | 1.7334 |

#### 交易质量 (8)
| # | 指标 | 值 |
|---|------|-----|
| 1 | win_rate | 47.71 |
| 2 | profit_loss_ratio | 1.5971 |
| 3 | avg_win_amount | 7.1278 |
| 4 | avg_loss_amount | -4.4629 |
| 5 | max_single_win | 46.6581 |
| 6 | max_single_loss | -24.1147 |
| 7 | max_consec_wins | 11 |
| 8 | max_consec_losses | 12 |

#### 效率指标 (5)
| # | 指标 | 值 |
|---|------|-----|
| 1 | annual_return | 46.5117 |
| 2 | calmar_ratio | 0.6447 |
| 3 | recovery_factor | 0.6447 |
| 4 | breakeven_win_rate | 38.5 |
| 5 | expectancy | 1.0666 |

#### 稳定性 (3)
| # | 指标 | 值 |
|---|------|-----|
| 1 | train_test_ratio | -1.3788 |
| 2 | stage_consistency | 83.02 |
| 3 | avg_hold_days | 7.0 |

---
## 策略: rsi_macd_TOP50_7d

### 各阶段概览

| 指标 | 训练期 | 验证期 | 测试期 | 全期 |
|------|--------|--------|--------|------|
| total_trades | 113 | 13 | 2 | 128 |
| positive_rate | 48.67 | 46.15 | 100.0 | 49.22 |
| avg_return | 0.902 | 1.802 | 2.1767 | 1.0133 |
| win_rate | 48.67 | 46.15 | 100.0 | 49.22 |

### 完整 28 项指标（全期）

#### 基础指标 (7)
| # | 指标 | 值 |
|---|------|-----|
| 1 | hit_stock_count | 102 |
| 2 | total_trades | 128 |
| 3 | positive_rate | 49.22 |
| 4 | avg_return | 1.0133 |
| 5 | median_return | -0.2847 |
| 6 | max_return | 24.8381 |
| 7 | min_return | -24.1147 |

#### 风险指标 (5)
| # | 指标 | 值 |
|---|------|-----|
| 1 | sharpe_ratio | 0.8026 |
| 2 | max_drawdown | 54.1704 |
| 3 | volatility | 7.4865 |
| 4 | downside_volatility | 3.9305 |
| 5 | sortino_ratio | 1.5287 |

#### 交易质量 (8)
| # | 指标 | 值 |
|---|------|-----|
| 1 | win_rate | 49.22 |
| 2 | profit_loss_ratio | 1.4862 |
| 3 | avg_win_amount | 6.7326 |
| 4 | avg_loss_amount | -4.5299 |
| 5 | max_single_win | 24.8381 |
| 6 | max_single_loss | -24.1147 |
| 7 | max_consec_wins | 8 |
| 8 | max_consec_losses | 8 |

#### 效率指标 (5)
| # | 指标 | 值 |
|---|------|-----|
| 1 | annual_return | 43.7587 |
| 2 | calmar_ratio | 0.8078 |
| 3 | recovery_factor | 0.8078 |
| 4 | breakeven_win_rate | 40.22 |
| 5 | expectancy | 1.0133 |

#### 稳定性 (3)
| # | 指标 | 值 |
|---|------|-----|
| 1 | train_test_ratio | 0.4144 |
| 2 | stage_consistency | 50.37 |
| 3 | avg_hold_days | 7.0 |

---
## 两策略对比

| 指标 | TOP100 | TOP50 |
|------|--------|-------|
| hit_stock_count | 169 | 102 |
| total_trades | 218 | 128 |
| positive_rate | 47.71 | 49.22 |
| avg_return | 1.0666 | 1.0133 |
| median_return | -0.4013 | -0.2847 |
| max_return | 46.6581 | 24.8381 |
| min_return | -24.1147 | -24.1147 |
| sharpe_ratio | 0.7678 | 0.8026 |
| max_drawdown | 72.1446 | 54.1704 |
| volatility | 8.2422 | 7.4865 |
| downside_volatility | 3.6507 | 3.9305 |
| sortino_ratio | 1.7334 | 1.5287 |
| win_rate | 47.71 | 49.22 |
| profit_loss_ratio | 1.5971 | 1.4862 |
| avg_win_amount | 7.1278 | 6.7326 |
| avg_loss_amount | -4.4629 | -4.5299 |
| max_single_win | 46.6581 | 24.8381 |
| max_single_loss | -24.1147 | -24.1147 |
| max_consec_wins | 11 | 8 |
| max_consec_losses | 12 | 8 |
| annual_return | 46.5117 | 43.7587 |
| calmar_ratio | 0.6447 | 0.8078 |
| recovery_factor | 0.6447 | 0.8078 |
| breakeven_win_rate | 38.5 | 40.22 |
| expectancy | 1.0666 | 1.0133 |
| train_test_ratio | -1.3788 | 0.4144 |
| stage_consistency | 83.02 | 50.37 |
| avg_hold_days | 7.0 | 7.0 |