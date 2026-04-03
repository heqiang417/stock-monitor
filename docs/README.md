# 股票盯盘系统 - 文档导航

> 项目入口 | 向下索引 L2 策略研究 / L3 运维 / L3 系统深处

---

## L2 策略研究

**入口**：[策略总览 INDEX](strategy/INDEX.md)

| 层级 | 内容 |
|------|------|
| **L2** | [策略总览 INDEX](strategy/INDEX.md) — 所有策略一张表 |
| **L3** | [Fstop3_pt5 v10 手册](strategy/Fstop3_pt5_v10/) — 实盘策略 |
| **L3** | [BB+KDJ 候选策略](strategy/BB_KDJ_Weak/) — 待上线 |

---

## L2 框架 & 指标

| 文档 | 内容 |
|------|------|
| [EVAL_FRAMEWORK.md](EVAL_FRAMEWORK.md) | 评测框架（基准，每次评估前必读） |
| [metrics_definitions.md](backtesting/metrics_definitions.md) | 28项指标定义 |

---

## L3 运维

| 文档 | 内容 |
|------|------|
| [crontab.md](ops/crontab.md) | 定时任务（每日20:30选股推送） |
| [DEPLOY.md](DEPLOY.md) | 部署说明 |

---

## L3 系统深处

| 文档 | 内容 |
|------|------|
| [database_schema.md](deep_dive/database_schema.md) | 数据库结构 |
| [data_provider.md](deep_dive/data_provider.md) | 数据源 |
| [routes.md](deep_dive/routes.md) | 路由 |
| [services.md](deep_dive/services.md) | 服务层 |
| [models.md](deep_dive/models.md) | 数据模型 |
| [tests.md](deep_dive/tests.md) | 测试 |

---

## L2 项目规划

| 文档 | 内容 |
|------|------|
| [planning/README.md](planning/README.md) | 规划入口 |
| [PRD-stock-monitor.md](planning/PRD-stock-monitor.md) | 产品需求 |
| [PLAN-stock-optimize.md](planning/PLAN-stock-optimize.md) | 优化计划 |

---

## 快速导航

```
项目入口 (L1)
├── 策略总览 INDEX (L2) ──────────────────→ STRATEGY_INDEX.md
│   ├── Fstop3_pt5 v10 (L3) ──────────→ Fstop3_pt5_v10/README.md
│   │                            backtest_report.md
│   └── BB+KDJ 候选 (L3)  ────────────→ BB_KDJ_Weak/README.md
│                               backtest_report.md
│
├── EVAL_FRAMEWORK.md (L2) ─────────────→ 评测基准
├── metrics_definitions.md (L2) ────────→ 28项指标
│
├── crontab.md (L3) ────────────────────→ 定时任务
├── DEPLOY.md (L3) ─────────────────────→ 部署
│
└── deep_dive/ (L3) ───────────────────→ 系统深处
    ├── database_schema.md
    ├── data_provider.md
    └── ...
```
