# 股票策略评测框架文档

> 版本：v1.6 | 更新：2026-04-03 | 作者：OpenClaw

---

## 1. 项目目标

通过数据体系，寻找优秀的股票购买策略。**必须遵守以下要求：**

1. **训练集选策略，验证/测试只做样本外检验** — 不允许用验证/测试集调参
2. **所用数据必须在购买股票前可用** — PIT (Point-in-Time) 合规
3. **A股 T+1 规则** — T+1 开盘买入；最早 T+2（次日）可设置条件单（止损/止盈）决定卖出
4. **三个数据集正收益率 >55%** — 任一阶段不达标即不合格
5. **28 项评价指标** 分训练/验证/测试分别计算

---

## 2. 数据阶段划分

| 阶段 | 时间范围 | 用途 |
|------|---------|------|
| 训练集 | 2021-01-01 ~ 2024-06-30 | 策略开发、参数调优 |
| 验证集 | 2024-07-01 ~ 2025-07-01 | 样本外检验、策略筛选 |
| 测试集 | 2025-07-02 ~ 2026-03-27 | 最终评估、不可用于调参 |

**注意：** 测试集截止日期取最近一个完整交易日（K 线数据完整的日期）。

---

## 3. 交易规则

### 买入

```
信号触发日（T）→ T+1 开盘价买入
```

### 卖出模式（sell_mode）

**模式一：止损/止盈退出（`sell_mode='stop_profit'`，默认）**

- T+2 起每日检查止损/止盈，触发即卖，最多持有 N 天
- 止损（默认 3%）：当日收盘跌幅 ≥ 3% → 当日收盘价卖出
- 止盈（默认 5%）：当日收盘涨幅 ≥ 5% → 当日收盘价卖出
- 未触发：持有满 N 天后次日收盘价卖出
- **最少持仓 1 天**（T+2 之前不可卖）

**模式二：固定持有（`sell_mode='fixed_hold'`）**

- T+1+N 收盘价固定卖出，N = hold_days

### 通用规则

```
成本：0.15% 单边 × 2 = 0.30% 总成本
收益 = (卖出价 - 买入价) / 买入价 × 100% - 0.30%
持仓冷却：同一股票买入后 N 天内不重复触发（i += N + 1）
         不同股票之间允许持仓重叠（即允许同时持有 N 只股票）
TOP N / 基本面过滤：非框架强制要求，为策略超参数，由策略自己定义
```

---

## 4. 选股范围

### 基本面 TOP N（月度 PIT 滚动筛选）

打分公式：ROE(30分) + 营收增速(20分) + 利润增速(20分) + 毛利率(15分) + 负债率(15分) = 满分 100

- **每月初**重新计算 TOP N 名单
- N 为可选超参数：100 / 200 / 300 / 500 或不限

### 弱市过滤（可选）

- 判断标准：全市场 >70% 个股收盘价 < MA20
- 阈值可调：60% / 70% / 80%
- 弱市日才触发交易（避开系统性下跌期的"接飞刀"）

> ⚠️ TOP N 和弱市过滤均为**策略超参数**，不是框架强制要求。

---

## 5. PIT 延迟规则

回测时必须确保**选股所用数据在买入前已经公开**，否则就是"偷看答案"。

| 财报类型 | 报告期 | PIT 延迟 | 实际可用日示例 |
|----------|--------|----------|---------------|
| 一季报 | 03-31 | 30天 | 2025-Q1 → 2025-04-30 |
| 半年报 | 06-30 | 62天 | 2025-H1 → 2025-08-31 |
| 三季报 | 09-30 | 31天 | 2025-Q3 → 2025-10-31 |
| 年报 | 12-31 | 120天 | 2025年报 → 2026-04-30 |

```
PIT可用日 = 报告期日期 + PIT延迟天数
```

---

## 6. 28 项指标

### 基础指标（7项）

| 指标 | 字段名 | 含义 |
|------|--------|------|
| 总交易次数 | `total_trades` | 策略触发的交易总次数 |
| 正收益率% | `positive_rate` | 盈利次数/总次数×100% |
| 平均收益率% | `avg_return` | 所有交易的平均收益 |
| 中位数收益率% | `median_return` | 收益中位数，比平均值更抗极端值 |
| 最大单笔收益% | `max_return` | 最高单次盈利 |
| 最大单笔亏损% | `min_return` | 最大单次亏损（绝对值） |
| 命中股票数 | `hit_stocks` | 满足策略条件的唯一股票数 |

### 风险指标（5项）

| 指标 | 字段名 | 计算方式 | 参考值 |
|------|--------|---------|--------|
| 夏普比率 | `sharpe` | (年化收益-3%) / 年化波动率 | >1 良好, >2 优秀 |
| 最大回撤% | `max_drawdown` | 累计对数收益的峰谷最大跌幅 | <30% 优秀 |
| 年化波动率% | `volatility` | 收益标准差 × √(252/持有天数) | 越低越稳定 |
| 下行波动率% | `downside_volatility` | 仅负收益的标准差 | 越低越好 |
| 索提诺比率 | `sortino` | (年化收益-3%) / 下行波动率 | >2 优秀 |

### 交易质量（8项）

| 指标 | 字段名 | 含义 |
|------|--------|------|
| 胜率% | `win_rate` | = positive_rate |
| 盈亏比 | `profit_loss_ratio` | 平均盈利/平均亏损，>1 赚多亏少 |
| 平均盈利% | `avg_win` | 盈利交易的平均收益 |
| 平均亏损% | `avg_loss` | 亏损交易的平均亏损（绝对值） |
| 最大单笔盈利% | `max_win` | 单笔最大盈利 |
| 最大单笔亏损% | `max_loss` | 单笔最大亏损（绝对值） |
| 最大连续盈利 | `max_consec_win` | 最长连胜次数 |
| 最大连续亏损 | `max_consec_loss` | 最长连败次数 |

### 效率指标（5项）

| 指标 | 字段名 | 含义 |
|------|--------|------|
| 年化收益率% | `annual_return` | 平均收益 × 252 / 持有天数 |
| 卡尔马比率 | `calmar` | 年化收益 / 最大回撤，>1 良好 |
| 恢复因子 | `recovery_factor` | 总收益 / 最大回撤 |
| 盈亏平衡胜率% | `break_even_wr` | = 1/(1+盈亏比)×100% |
| 期望值% | `expectancy` | 胜率×平均盈利 + (1-胜率)×平均亏损 |

### 稳定性（3项）

| 指标 | 字段名 | 含义 |
|------|--------|------|
| 训练/测试收益比 | `train_test_ratio` | 越接近1过拟合风险越低 |
| 三阶段一致性 | `three_phase_consistency` | 三阶段收益方向一致=1，否则=0 |
| 平均持仓天数 | `avg_hold_days` | 所有交易的平均实际持仓天数 |

---

## 7. 框架用法

### 核心调用

```python
from scripts.strategy_evaluator import StrategyEvaluator

ev = StrategyEvaluator()
ev.load_data()

# 止损/止盈模式（默认）
result = ev.evaluate(
    signal_fn=ev.signal_rsi,
    hold_days=10,
    params={'rsi_thresh': 20},
    use_weak=True,
    weak_threshold=0.7,
    top_n=200,
    stop_loss=3.0,
    take_profit=5.0,
    sell_mode='stop_profit',
)

# 固定持有模式
result_fixed = ev.evaluate(
    signal_fn=ev.signal_rsi,
    hold_days=10,
    params={'rsi_thresh': 20},
    use_weak=True,
    sell_mode='fixed_hold',
)

ev.print_28_metrics(result)
ev.save(result, 'my_strategy')
```

### 批量搜索

```python
results = ev.search([
    ('RSI<20',        ev.signal_rsi,      {'rsi_thresh': 20}),
    ('RSI<20+BB',     ev.signal_rsi_bb,   {'rsi_thresh': 20}),
    ('RSI<20+MACD',   ev.signal_rsi_macd, {'rsi_thresh': 20}),
], hold_days=10)

best = results[0]
print(f"最佳: {best['name']}, 测试夏普={best['phases']['test']['sharpe']}")
```

### 信号函数签名

```python
def my_signal(stock_data: dict, index: int, params: dict) -> bool:
    """
    stock_data 包含: dates, open, close, high, low, rsi,
                     bb_lower, bb_upper, ma5, ma10, ma20,
                     macd_hist, volume（均为 ndarray）
    index: 当天在 dates 中的索引
    params: 参数字典
    """
    rsi = stock_data['rsi'][index]
    return not np.isnan(rsi) and rsi < params.get('rsi_thresh', 20)
```

---

## 8. 合格标准

### 三阶段均需满足

| 指标 | 最低要求 | 理想值 |
|------|---------|--------|
| 胜率 | >55% | >65% |
| 夏普比率 | >1.0 | >2.0 |
| 索提诺比率 | >2.0 | >5.0 |
| 最大回撤 | <50% | <25% |
| 盈亏比 | >1.0 | >1.5 |
| 测试笔数 | >30 | >100 |

> ⚠️ **盈亏比 >1.0 是硬门槛**，它反映策略的核心盈利能力。

### 夏普比率行业参考

| 范围 | 评价 |
|------|------|
| 0~0.99 | 低风险调整表现 |
| **1.0~1.99** | **良好**（框架最低要求） |
| **2.0~2.99** | **很好**（对冲基金级别） |
| ≥3.0 | 优秀（top 1% 顶级机构） |

### 过拟合信号

- 训练正率远高于验证/测试
- `train_test_ratio` 偏离 1 太远
- 三阶段不一致（有的正有的负）
- 测试笔数 < 30（样本不足）

---

## 9. 常见错误

### 数据泄露（PIT 未延迟）

```python
# ❌ 错误：财报直接可用
sym_scores[sym] = [(report_date, score)]

# ✅ 正确：加 PIT 延迟
pit_date = report_date + timedelta(days=pit_delay_days(report_date))
sym_scores[sym] = [(pit_date, score)]
```

### 成本计算错误

```python
# ❌ 错误：只算单边
ret = (sell - buy) / buy * 100 - 0.15

# ✅ 正确：双边
ret = (sell - buy) / buy * 100 - 0.30
```

### T+1 约束违反

```python
# ❌ 错误：信号日当天买入
buy_price = close[i]

# ❌ 错误：T+1 之前就想卖
sell_price = close[i + 1]

# ✅ 正确：T+1 开盘买，最少持有一天
buy_price = open[i + 1]
# 卖出逻辑见第3节
```

### 持仓期重复买入

```python
# ❌ 错误：买入后每天检查
i += 1

# ✅ 正确：跳过整个持仓期
if signal_triggered:
    i += hold_days + 1
else:
    i += 1
```

### 弱市判断用个股而非全市场

```python
# ❌ 错误
weak = close[i] < ma20[i]

# ✅ 正确：全市场 >70% 个股
below = sum(1 for all stocks if close < ma20)
weak = (below / total > 0.7)
```

---

## 10. 条件显式声明铁律

**只要策略用了某个条件，就必须在脚本中显式写出，不依赖默认值。**

```python
# ❌ 错误：不可审计
result = ev.evaluate(ev.signal_rsi_bb, hold_days=7, top_n=300)

# ✅ 正确：所有条件一目了然
result = ev.evaluate(
    ev.signal_rsi_bb,
    hold_days=7,
    params={'rsi_thresh': 20},
    top_n=300,
    use_weak=True,
    weak_threshold=0.7,
    top_n_per_day=0,
    sell_mode='stop_profit',
    stop_loss=3.0,
    take_profit=5.0,
)
```

---

## 附录：文件位置

| 文件 | 说明 |
|------|------|
| `scripts/strategy_evaluator.py` | 评测框架（核心） |
| `scripts/daily_pick.py` | 实盘选股脚本 |
| `data/stock_data.db` | 核心数据库 |
| `data/results/` | 评测结果目录 |

## 附录：修改记录

| 日期 | 版本 | 变更 |
|------|------|------|
| 2026-03-30 | v1.0 | 初始版本，动态PIT延迟，28项指标，T+1约束 |
| 2026-03-30 | v1.1 | 新增 top_n_per_day 每日选股排序功能 |
| 2026-03-31 | v1.2 | 新增条件显式声明铁律 |
| 2026-04-01 | v1.3 | 明确 TOP N、弱市过滤为策略超参数 |
| 2026-04-02 | v1.4 | 卖出规则改为 T+2 起止损/止盈退出，新增 sell_mode 参数 |
| 2026-04-02 | v1.5 | 精简文档，移除冗余的代码API表格，聚焦规则与概念 |
