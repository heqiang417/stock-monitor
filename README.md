# 股票盯盘系统

> 渐进式披露：先看 L1，用完想深入再进 L2/L3

---

## 🎯 每日操作 (L1)

**入口命令：** 无——每天 20:30 自动推送飞书卡片

### 今天买什么？
→ `python3 scripts/daily_pick_v10.py --push`（手动触发）

### 查看历史推送
→ 查看 `reports/daily_picks/` 目录（按日期命名的推送记录）

### 大盘状态速览
→ 数据库实时查询（MA20弱市比例、RSI分布）

---

## 📐 策略研究 (L2)

**入口：** 想调参数 / 想理解策略逻辑 / 想看回测数据

### 当前策略：Fstop3_pt5
- 📄 [策略手册](docs/strategy/Fstop3_pt5_v10.md) — 完整参数 + 条件单设置
- 📊 [28项指标回测报告](docs/backtesting/reports/Fstop3_pt5_v10.md)
- 📉 [评估框架说明](docs/EVAL_FRAMEWORK.md)

### 历史策略
- V4（已下线）：7天固定持有
- [更多回测报告](docs/backtesting/reports/)

### 如何修改策略
1. 读策略手册理解参数含义
2. 用 `scripts/exploration/strategy_search_v4_pit.py` 探索新参数
3. 用 `scripts/evaluation/strategy_evaluator.py` 跑回测
4. 评估达标后更新 `daily_pick_v10.py`

---

## ⚙️ 系统深处 (L3)

**入口：** 调试 / 改代码 / 看原始数据

### 脚本索引
- [scripts/README.md](scripts/README.md) — 所有脚本职责速查

### 定时任务
- crontab 运行时间表 → [docs/ops/crontab.md](docs/ops/crontab.md)

### 数据与调试
- [docs/deep_dive/database_schema.md](docs/deep_dive/database_schema.md) — 数据库表结构
- [docs/deep_dive/api_logs.md](docs/deep_dive/api_logs.md) — 外部API调用日志

### 部署
- [docs/DEPLOY.md](docs/DEPLOY.md) — 服务部署与重启

---

## 📁 目录结构

```
stock-monitor-app-py/
├── scripts/
│   ├── daily/              ← L1 每日运行（crontab 调用）
│   │   ├── daily_pick_v10.py
│   │   └── daily_sync.py
│   ├── evaluation/         ← L2 评估运行
│   │   └── strategy_evaluator.py
│   ├── exploration/        ← L2 策略探索
│   │   └── strategy_search_v4_pit.py
│   └── tools/             ← L3 辅助工具
│       ├── update_tencent.py
│       ├── calc_bollinger.py
│       └── write_feishu_doc.py
├── docs/
│   ├── strategy/          ← L2 策略文档
│   ├── backtesting/       ← L2 回测报告
│   ├── ops/              ← L2 运维文档
│   └── deep_dive/        ← L3 深处文档
├── backtest/             ← L2 回测结果（trades JSON + eval JSON）
└── reports/daily_picks/  ← L1 历史推送记录
```

---

**原则：** 不需要同时看所有层。按需展开，逐层深入。
