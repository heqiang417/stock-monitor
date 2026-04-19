# 定时任务 (Crontab)

> L2 运维：了解什么时候跑什么

---

## 当前运行表

```cron
# 盘后完整数据同步（工作日 17:00）
0 17 * * 1-5 /usr/bin/ionice -c3 /usr/bin/nice -n 19 /usr/bin/python3 -u /home/heqiang/.openclaw/workspace/stock-monitor-app-py/scripts/daily/update_tencent.py --no-weekly --no-monthly >> /tmp/update_tencent.log 2>&1

# 扩展数据同步（工作日 17:30，日更口径）
30 17 * * 1-5 STOCK_DB=/home/heqiang/.openclaw/workspace/stock-monitor-app-py/data/stock_data.db /usr/bin/ionice -c3 /usr/bin/nice -n 19 /usr/bin/python3 -u /home/heqiang/.openclaw/workspace/stock-monitor-app-py/scripts/daily/daily_sync.py --northbound --margin --limit --index --flow --industry >> /tmp/stock_daily_sync.log 2>&1

# 周六重数据同步（周更口径）
0 2 * * 6 STOCK_DB=/home/heqiang/.openclaw/workspace/stock-monitor-app-py/data/stock_data.db /usr/bin/ionice -c3 /usr/bin/nice -n 19 /usr/bin/python3 -u /home/heqiang/.openclaw/workspace/stock-monitor-app-py/scripts/daily/daily_sync.py --shareholder --news --review --chip --lhb --block --industry --shareholder-limit 1000 >> /tmp/stock_daily_sync_weekly.log 2>&1

# 周日全量重算 + 财务指标
0 2 * * 0 /usr/bin/ionice -c3 /usr/bin/nice -n 19 /usr/bin/python3 -u /home/heqiang/.openclaw/workspace/stock-monitor-app-py/scripts/daily/update_tencent.py --full >> /tmp/update_tencent_weekly.log 2>&1
0 3 * * 0 STOCK_DB=/home/heqiang/.openclaw/workspace/stock-monitor-app-py/data/stock_data.db /usr/bin/ionice -c3 /usr/bin/nice -n 19 /usr/bin/python3 -u /home/heqiang/.openclaw/workspace/stock-monitor-app-py/scripts/daily/daily_sync.py --fund >> /tmp/stock_daily_sync.log 2>&1

# 每日选股推送（工作日 20:30）
30 20 * * 1-5 STOCK_DB=/home/heqiang/.openclaw/workspace/stock-monitor-app-py/data/stock_data.db /usr/bin/python3 -u /home/heqiang/.openclaw/workspace/stock-monitor-app-py/scripts/daily/daily_pick_combined.py --push --wait >> /tmp/daily-pick-combined.log 2>&1
```

### 运行说明（已和当前逻辑对齐）

- 推送形式：**飞书文本消息**，失败时自动回退或告警。
- `update_tencent.py`（17:00）在**日更模式**下采用**当天增量补算**：
  - 拉当天 K 线 + **指数K线**（上证/深证/创业板/科创50/沪深300/中证500/中证1000）
  - 只对**当天有K线的股票**补 `MA/RSI`
  - 增量补当天 `BB`（布林带）
  - 同步当天 **PE/PB**（腾讯实时）
- `daily_sync.py`（17:30）工作日日更（扩展数据），日更口径：
  - 北向资金
  - 融资融券
  - 涨跌停
  - 资金流
  - 行业板块
  - 指数K线
- **周六 02:00 周更**：股东数据、新闻、大盘复盘、筹码分布、龙虎榜、大宗交易
- **周日 02:00 周更**：全量 K 线重算（update_tencent --full）
- **周日 03:00 周更**：财务指标（daily_sync --fund）
- `--wait`：20:30 任务等待 `READY_FLAG`，超时则自动触发**双阶段补齐**（基础+扩展），补齐后再校验。
- `daily_pick_combined.py` 内置**兜底补齐**：若当天数据不完整，先触发 `update_tencent`（Step1）再触发 `daily_sync`（Step2），补齐后重验。
- 若补齐后当天仍不完整，**自动回退到最近有效交易日**，避免空推或直接失败。
- **全量重算**只保留给 `update_tencent.py --full`（周末/修复场景），不再作为日常盘后默认流程。

---

## 流程图

```
17:00 update_tencent.py（日K线 / 指数K线 / MA+RSI+BB / PE+PB）
  → 技术指标重算（MA/RSI 增量补今天）
  → 布林带增量补算
  → 同步当天 PE/PB 估值
  → 写入 READY_FLAG

        ↓ (17:30)

17:30 daily_sync.py（日更扩展数据）
  → 北向资金
  → 融资融券
  → 涨跌停
  → 资金流
  → 行业板块
  → 指数K线

        ↓ (20:30)

20:30 daily_pick_combined.py --push --wait
  → 检查 READY_FLAG
  → 超时未就绪 → 触发双阶段补齐（兜底）
  → 扩展数据选股前校验（⚠️ 告警，非阻塞）
  → 校验通过后执行选股策略
  → 飞书文本推送
```

### 周末/周期任务

```
周六 02:00 daily_sync.py --shareholder --news --review --chip --lhb --block --industry
  → 股东数据（前1000只）
  → 新闻
  → 大盘复盘
  → 筹码分布
  → 龙虎榜
  → 大宗交易

周日 02:00 update_tencent.py --full（全量K线重算）

周日 03:00 daily_sync.py --fund（财务指标）
```

---

## 定时任务对应策略

| 策略 | 脚本 | 触发时间 | 买卖规则 | 手册 |
|------|------|---------|---------|------|
| **BB1.00** | daily_pick_combined.py | 工作日 20:30 | 次一交易日开盘买入；固定持有7个交易日，于第8个交易日收盘卖出 | [手册](../strategy/BB1.00/README.md) |
| **BB1.02+KDJ** | daily_pick_combined.py | 工作日 20:30 | 次一交易日开盘买入；固定持有7个交易日，于第8个交易日收盘卖出 | [手册](../strategy/BB_KDJ_Weak/README.md) |
| **策略A** | daily_pick_combined.py | 工作日 20:30 | 次一交易日开盘买入；T+2起按收盘检查 SL3.5% / TP4.0%，最长 H5，到期第6个交易日收盘卖出 | [手册](../strategy/STRATEGY_INDEX.md) |
| **TP4.5** | daily_pick_combined.py | 工作日 20:30 | 次一交易日开盘买入；T+2起按收盘检查 SL3.5% / TP4.5%，最长 H5，到期第6个交易日收盘卖出 | [手册](../strategy/STRATEGY_INDEX.md) |

> 注：Fstop3_pt5 v10 已降级为历史/对照策略，不再属于正式每日策略池。

---

## 日志文件

| 日志 | 路径 |
|------|------|
| K线+指数更新 | `/tmp/update_tencent.log` |
| 扩展数据同步 | `/tmp/daily_sync_ext.log` |
| 每日选股 | `/tmp/daily-pick-combined.log` |
| 数据就绪信号 | `/tmp/stock_data_ready.flag`（内容为日期） |

---

## 查看运行状态

```bash
# 看K线同步日志
tail -20 /tmp/update_tencent.log

# 看扩展数据同步日志
tail -20 /tmp/daily_sync_ext.log

# 看选股日志
tail -20 /tmp/daily-pick-combined.log

# 看 crontab 是否正常
crontab -l

# 看数据就绪信号
cat /tmp/stock_data_ready.flag
```
