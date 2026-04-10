# scripts/ — 脚本分层说明（重建版）

> 这一版的目标不是列出所有脚本，而是明确：**哪些脚本属于生产、哪些属于评估、哪些属于探索、哪些属于历史归档。**

---

## 一、官方分层

```text
scripts/
├── daily/               # Production：每日真实运行入口
├── evaluation/          # Evaluation：标准评估入口
├── exploration/         # Exploration：参数搜索 / 新方向实验
├── backtest_legacy/     # Archive：旧脚本归档
└── README.md            # 当前文件
```

---

## 二、Production：生产运行层

> 这层的脚本会直接影响每天的数据同步、选股与推送。

目录：`scripts/daily/`

### 当前主入口

| 脚本 | 角色 | 状态 |
|------|------|------|
| `update_tencent.py` | 主数据同步入口（股票K线 + 指数K线 + MA/RSI/BB + PE/PB） | 在用 |
| `calc_bollinger.py` | 布林带计算 | 在用 |
| `daily_sync.py` | 扩展数据补充入口（北向/两融/股东/新闻/复盘/筹码/涨跌停/龙虎榜/大宗/资金流/行业） | 在用 |
| `daily_pick_combined.py` | **当前唯一在用的每日选股入口**（含双阶段补齐 + 扩展数据告警校验） | 在用 |

### 历史生产脚本（仍保留，但不是当前官方入口）

| 脚本 | 状态 |
|------|------|
| `daily_pick_v10.py` | 历史版本 |
| `daily_pick_bb099.py` | 历史版本 |
| `daily_pick_bb100.py` | 历史版本 |

### 辅助检查

| 脚本 | 作用 |
|------|------|
| `check_strategy_consistency.py` | 检查策略口径一致性 |
| `calc_weekly_monthly.py` | 周/月级指标辅助计算 |

---

## 三、Evaluation：标准评估层

> 这层负责回答：一个策略到底合不合格。

目录：`scripts/evaluation/`

| 脚本 | 作用 |
|------|------|
| `strategy_evaluator.py` | 统一评估器 / 核心评估能力 |
| `eval_fstop3.py` | Fstop3 评估入口 |
| `generate_fstop3_report.py` | Fstop3 报告生成 |
| `eval_bb099_bb100.py` | BB099/BB100 评估 |
| `eval_v4_28metrics.py` | 历史 V4 评估 |
| `evaluate_backtest.py` | 通用回测评估 |

### 原则
- 评估层不直接负责上线
- 评估结果应优先成为文档和日报的统一真源

---

## 四、Exploration：策略探索层

> 这层负责试新东西，不直接决定生产上线。

目录：`scripts/exploration/`

### 当前值得关注的探索链

| 脚本 | 作用 |
|------|------|
| `explore_3directions.py` | 三方向搜索（已完成收口） |
| `explore_direction_4_expand_test_samples.py` | 扩测试样本 |
| `explore_direction_5_fine_tune_train_winrate.py` | 在样本基础上精修 |
| `explore_direction_6_sample_first.py` | **样本优先搜索的统一入口** |

### 其他探索脚本

| 脚本 | 作用 |
|------|------|
| `bb098_099_100_explore.py` | BB 多阈值探索 |
| `bb_kdj_rsi_explore.py` | BB + KDJ + RSI 探索 |
| `bb_kdj_rsi_weak_explore.py` | 弱市过滤探索 |
| `explore_strategies.py` | 综合探索 |
| `strategy_search_v4_pit.py` | 历史 PIT 搜索入口 |

### 原则
- 探索结果先看样本与稳定性
- 不允许直接把探索结果当生产结论

---

## 五、Archive：历史归档层

目录：`scripts/backtest_legacy/`

| 脚本 | 状态 |
|------|------|
| `quick_explore.py` | 历史归档 |
| `explore_v3.py` | 历史归档 |

---

## 六、当前推荐工作流

```text
探索脚本（exploration）
  ↓
标准评估（evaluation）
  ↓
更新策略文档 / 报告（docs/strategy + docs/backtesting/reports）
  ↓
强哥确认
  ↓
进入生产层（daily_pick_combined.py / cron）

当前生产真实链路：
- **17:00** `update_tencent.py`
- **17:30** `daily_sync.py`
- **20:30** `daily_pick_combined.py --push --wait`
- 若数据不完整：`daily_pick_combined.py` 会触发**基础 + 扩展双阶段兜底补齐**
```

---

## 七、当前结构结论

- `daily/` = 真正影响每天产出的地方
- `evaluation/` = 统一口径的地方
- `exploration/` = 可以大胆试，但不能越权上线
- `backtest_legacy/` = 留历史，不干扰主线

如果以后继续重构，优先顺序应该是：
1. 进一步压缩历史生产脚本
2. 把一次性维护脚本移出 `daily/`
3. 给 exploration 结果建立更统一的产出规范
