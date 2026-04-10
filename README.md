# 股票盯盘系统（重建版结构入口）

> 这是一个**研究驱动的实盘辅助系统**：白天同步数据，盘后筛选策略，输出每日选股与研究结论。
> 当前仓库已经完成第一轮结构重建：先明确主线、分层和归档边界，再逐步继续代码层重构。

---

## 1. 这个项目现在到底干什么

核心主线现在是五步：

1. **17:00 基础同步（K线 / 指数K线 / MA / RSI / BB / PEPB）**
2. **17:30 扩展同步（北向 / 两融 / 股东 / 新闻 / 复盘 / 筹码 / 涨跌停 / 龙虎榜 / 大宗 / 资金流 / 行业）**
3. **选股前补齐 / 校验数据可用性**
4. **运行当前在用策略**
5. **推送每日选股结果到飞书**

所以它不是一个泛化量化平台，而是一个：

> **面向 A 股日常选股、策略迭代、盘后推送的辅助系统**

---

## 2. 当前唯一应该优先理解的入口

### 生产运行层（每天真实在跑）

| 入口 | 作用 |
|------|------|
| `scripts/daily/update_tencent.py` | 收盘后主数据同步（含指数K线 + 当天增量补算） |
| `scripts/daily/calc_bollinger.py` | 计算/补齐布林带 |
| `scripts/daily/daily_sync.py` | 扩展数据同步（北向/两融/股东/新闻/复盘/筹码/涨跌停/龙虎榜/大宗/资金流/行业） |
| `scripts/daily/daily_pick_combined.py` | **当前唯一在用的每日选股入口**（选股前先校验，必要时自动补齐） |
| `docs/ops/crontab.md` | 当前定时任务运行说明 |

### 当前在用策略

- `BB1.00`
- `BB1.02+KDJ`

历史/对照策略：
- `Fstop3_pt5 v10`（已降级，不再属于正式每日策略池）

策略总览：
- `docs/strategy/STRATEGY_INDEX.md`

---

## 3. 项目分层（重建后的官方口径）

### A. Production / 生产运行层
负责每日真实执行。

目录 / 文件：
- `scripts/daily/`
- `docs/ops/`
- `reports/daily_picks/`（运行结果，本地留痕，不作为核心源码资产）

特点：
- 只有这一层可以直接影响每日推送
- 变更要谨慎，优先稳定性

---

### B. Evaluation / 标准评估层
负责统一评估策略，不直接上线。

目录：
- `scripts/evaluation/`
- `docs/EVAL_FRAMEWORK.md`
- `docs/backtesting/reports/`（当前主线评估报告）

特点：
- 这里的目标是统一口径
- 所有“策略是否合格”的结论，都应尽量从这一层产出

---

### C. Exploration / 策略探索层
负责试新方向、扩样本、调参数。

目录：
- `scripts/exploration/`

当前重点脚本：
- `explore_direction_4_expand_test_samples.py`
- `explore_direction_5_fine_tune_train_winrate.py`
- `explore_direction_6_sample_first.py`

特点：
- **探索不等于上线**
- 任何探索结果都必须经过评估层确认，再进入生产层

---

### D. Archive / 历史归档层
负责存放旧报告、旧方案、旧链条。

目录：
- `docs/backtesting/archive/`
- `scripts/backtest_legacy/`

特点：
- 保留历史价值
- 但不参与当前主线决策

---

## 4. 当前目录结构（按职责理解）

```text
stock-monitor-app-py/
├── scripts/
│   ├── daily/                 # 生产运行入口（cron 真正在调）
│   ├── evaluation/            # 标准评估入口
│   ├── exploration/           # 策略探索 / 参数搜索
│   ├── backtest_legacy/       # 历史脚本归档
│   └── README.md              # 脚本分层说明
│
├── docs/
│   ├── ops/                   # 运维 / crontab / 部署说明
│   ├── strategy/              # 当前策略手册与总览
│   ├── backtesting/
│   │   ├── reports/           # 当前主线报告
│   │   └── archive/           # 历史报告归档
│   └── EVAL_FRAMEWORK.md      # 统一评估框架
│
├── reports/daily_picks/       # 每日推送留痕（运行产物）
├── data/                      # 数据库 / 中间结果
├── backtest/                  # 回测产出 / trades / 中间资产
└── README.md                  # 当前文件
```

---

## 5. 现在的结构结论

当前仓库已经从“研究脚本堆积”进入到：

> **主线明确，但仍在从研究型仓库向稳定产品型仓库过渡。**

已经完成的重建：
- 报告从主目录与历史目录分离
- 生产 / 评估 / 探索 三层职责更清楚
- 当前策略状态、crontab 说明、daily_sync 修复已同步到文档与代码
- Fstop3 已明确降级为历史/对照策略，正式每日策略池收敛为 `BB1.00 + BB1.02+KDJ`

仍建议后续继续做的重建：
1. 把一次性维护脚本继续从主脚本目录中分离
2. 给环境变量 / 运行依赖补正式 runtime 文档
3. 逐步收缩历史生产脚本（如 `daily_pick_v10.py` / `daily_pick_bb099.py` / `daily_pick_bb100.py`）
4. 最终把“当前唯一官方入口”收得更硬

---

## 6. 如果你只看三个文件

请先看：

1. `docs/strategy/STRATEGY_INDEX.md`
2. `docs/ops/crontab.md`
3. `scripts/README.md`

如果你只想知道“今天系统到底怎么跑”：

- 看 `scripts/daily/`
- 看 `docs/ops/crontab.md`
- 看 `daily_pick_combined.py`
- 当前真实顺序是：
  **17:00 基础同步 → 17:30 扩展同步 → 20:30 选股推送 → 异常时双阶段兜底补齐**

---

## 7. 当前原则

- **生产脚本优先稳定，不随探索结果直接改。**
- **探索脚本先求样本与稳定性，不追漂亮但低样本的指标。**
- **正式每日策略池当前为 `BB1.00 + BB1.02+KDJ`，Fstop3 仅作历史/对照。**
- **历史报告保留，但不干扰当前主线。**
- **文档必须反映真实运行状态。**
