# 定时任务 (Crontab)

> L2 运维：了解什么时候跑什么

---

## 当前运行表

```cron
# 数据同步（工作日 17:00）
0 17 * * 1-5 python3 -u /home/heqiang/.openclaw/workspace/stock-monitor-app-py/scripts/daily/update_tencent.py --no-weekly --no-monthly >> /tmp/update_tencent.log 2>&1

# 布林带计算（工作日 17:05）
5 17 * * 1-5 python3 -u /home/heqiang/.openclaw/workspace/stock-monitor-app-py/scripts/daily/calc_bollinger.py >> /tmp/calc_bollinger.log 2>&1

# 每日选股推送（工作日 20:30）
30 20 * * 1-5 cd /home/heqiang/.openclaw/workspace/stock-monitor-app-py && python3 -u scripts/daily/daily_pick_combined.py --push --wait >> /tmp/daily-pick-combined.log 2>&1
```

### 运行说明（已和当前逻辑对齐）
- 推送形式：**飞书文本消息**，不是卡片。
- `--wait`：20:30 任务会等待数据就绪信号。
- 数据就绪信号仅在**有效交易日数据校验通过后**写入 `/tmp/stock_data_ready.flag`。
- 若当天数据不完整，`daily_pick_combined.py` 会**自动回退到最近有效交易日**，避免空推或直接失败。

---

## 流程图

```
17:00 daily/update_tencent.py
  → 腾讯API拉K线（日/周/月）
  → 写入 stock_data.db
  → 技术指标同步

        ↓ (17:05)

17:05 daily/calc_bollinger.py
  → 重算 BB_upper/BB_lower

        ↓ (数据就绪写入 /tmp/stock_data_ready.flag)

20:30 daily/daily_pick_combined.py --push --wait
  → 检查数据就绪信号
  → 若当天数据不足，自动回退到最近有效交易日
  → 读取 db 最新有效交易日数据
  → 执行组合策略筛选：
      1. Fstop3_pt5 v10（RSI<18 + BB触底 + 放量1.5x + 弱市50%）
      2. BB1.00（RSI<20 + BB≤1.00 + 弱市70%）
      3. BB0.99（RSI<20 + BB≤0.99 + 弱市70%）
  → 飞书**文本消息**推送（私聊发给何强本人）
```

---

## 定时任务对应策略

| 策略 | 脚本 | 触发时间 | 持有规则 | 手册 |
|------|------|---------|---------|------|
| **Fstop3_pt5 v10** | daily_pick_combined.py | 工作日 20:30 | 止损3% + 止盈5% | [手册](../strategy/Fstop3_pt5_v10/README.md) |
| BB1.00 | daily_pick_combined.py | 工作日 20:30 | 固定7天 | [手册](../strategy/BB1.00/README.md) |
| BB0.99 | daily_pick_combined.py | 工作日 20:30 | 固定7天 | [手册](../strategy/BB0.99/README.md) |

---

## 日志文件

| 日志 | 路径 |
|------|------|
| K线更新 | `/tmp/update_tencent.log` |
| 布林带 | `/tmp/calc_bollinger.log` |
| 每日选股 | `/tmp/daily-pick-combined.log` |
| 数据就绪信号 | `/tmp/stock_data_ready.flag`（内容为日期） |

---

## 查看运行状态

```bash
# 看最后几条K线同步日志
tail -20 /tmp/update_tencent.log

# 看最后几条选股日志
tail -20 /tmp/daily-pick-combined.log

# 看 crontab 是否正常
crontab -l

# 看数据就绪信号
cat /tmp/stock_data_ready.flag
```
