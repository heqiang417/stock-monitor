# scripts/ — 操作脚本目录

> 本目录包含所有可执行的 Python 脚本，按用途分为四类。
> 所有策略评估必须参考 [EVAL_FRAMEWORK.md](../docs/EVAL_FRAMEWORK.md)。

---

## 目录结构

```
scripts/
├── daily/            ← 每日运营（crontab 触发）
├── evaluation/       ← 策略评估（跑 28 项指标）
├── backtest_legacy/  ← 历史探索脚本（已归档）
├── README.md         ← 本文件
└── update_tencent.py
```

---

## daily/ — 每日运营脚本

> crontab 触发，每日自动运行

| 脚本 | crontab | 说明 |
|------|---------|------|
| **`daily_pick_combined.py`** | 20:30 工作日 | **当前唯一在用**。整合 Fstop3 v10 + BB1.00 + BB0.99 三个策略，输出飞书卡片 |
| `daily_pick_v10.py` | — | 历史版本（2026-04-02 前使用） |
| `daily_pick_bb099.py` | — | 历史版本 |
| `daily_pick_bb100.py` | — | 历史版本 |
| `daily_sync.py` | 17:30 工作日 | 同步 K 线 + RSI + 布林带数据到 stock_data.db |
| `calc_bollinger.py` | 17:35 工作日 | 重算布林带指标（在 daily_sync.py 之后） |

**手动触发：**
```bash
# 当前每日选股（推送飞书）
python3 daily/daily_pick_combined.py --push --wait

# 指定日期
python3 daily/daily_pick_combined.py --push --date 2026-04-01

# 数据同步
python3 daily/daily_sync.py --fund
```

---

## evaluation/ — 策略评估脚本

> 跑 28 项指标评估。**推荐用 `evaluate_strategy.py`**（框架官方 CLI）

### ✅ 推荐流程

```
回测 → 生成 trades JSON（{train/val/test: [{symbol, buy_date, sell_date, return_pct}]}）
     ↓
python3 evaluate_strategy.py trades.json --name "策略名" --position-size 0.1
     ↓
输出 28 项指标到标准输出 + evaluate_result.json
```

**evaluate_strategy.py**（框架官方评估）是共享技能，位于：
```
~/.openclaw/workspace/skills/stock-strategy-evaluator/scripts/evaluate_strategy.py
```

### 本地评估脚本（供参考/定制）

| 脚本 | 说明 |
|------|------|
| `strategy_evaluator.py` | StrategyEvaluator 类，支持自定义信号函数做回测 |
| `eval_fstop3.py` | ⚠️ 有 MDD 聚合 bug，请勿用于正式评估 |
| `eval_bb099_bb100.py` | BB099/BB100 策略独立评估 |
| `eval_v4_28metrics.py` | v4 框架评估（历史版本） |
| `evaluate_backtest.py` | 通用回测评估 |

**示例（用本地 StrategyEvaluator）：**
```python
from evaluation.strategy_evaluator import StrategyEvaluator

ev = StrategyEvaluator()
ev.load_data()
result = ev.evaluate(signal_fn=my_signal, hold_days=10, sell_mode='stop_profit')
ev.print_28_metrics(result)
```

---

## exploration/ — 策略探索脚本

> 参数网格搜索，寻找合格策略组合。**探索结果需人工确认后才能上线。**

| 脚本 | 说明 |
|------|------|
| `bb_kdj_rsi_weak_explore.py` | BB + KDJ Oversold + RSI + 弱市 width70 参数对比 |
| `bb098_099_100_explore.py` | BB 乘数 0.98/0.99/1.00 对比 |
| `bb_kdj_rsi_explore.py` | BB + KDJ RSI 组合探索 |
| `explore_3directions.py` | 三方向探索（趋势/逆趋势/突破） |
| `explore_strategies.py` | 综合策略搜索 |

**探索 → 评估标准流程：**
```
1. 探索脚本输出 JSON（如 weak_filter_compare.json）
2. 人工分析哪些参数组合合格
3. 用 agent_backtest.py 生成 trades JSON
4. 用 evaluate_strategy.py 跑 28 项指标
5. 合格 → 写 backtest_report.md → 更新 STRATEGY_INDEX.md
6. 强哥确认 → 上线 crontab
```

---

## backtest_legacy/ — 历史探索脚本（归档）

> 早期探索用脚本，已被 exploration/ 目录下的新脚本取代，保留供参考。

| 脚本 | 说明 |
|------|------|
| `quick_explore.py` | 快速探索（历史） |
| `explore_v3.py` | 策略搜索 v3（历史） |

---

## 其他

| 脚本 | 说明 |
|------|------|
| `update_tencent.py` | 全量/增量同步 K 线（高级用户用） |

---

## 数据流

```
腾讯 API
  ↓ daily_sync.py (17:30)
stock_data.db (K线 + RSI + BB)
  ↓ daily_pick_combined.py (20:30)
飞书卡片推送
  ↓
trades JSON（由 backtest/agent_backtest.py 生成）
  ↓ evaluate_strategy.py
28 项指标报告
  ↓ 写入 docs/strategy/[策略名]/backtest_report.md
```
