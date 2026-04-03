# API 调用日志

> L3 深处：调试网络问题 / 排查数据缺失 / 查看外部依赖

---

## 数据源

| 数据源 | 用途 | 稳定性 |
|--------|------|--------|
| 腾讯行情 API (203.205.235.28) | K线 + 技术指标 | ✅ 主力 |
| 东方财富 API | 财务指标、资金流 | ⚠️ 偶发限流 |

---

## 已知问题

### DNS 劫持
- **现象**: eastmoney / 腾讯域名解析到 28.0.0.x 假IP
- **解决**: `/etc/hosts` 硬绑定真实IP
  ```
  43.154.254.185  web.ifzq.com
  203.205.235.28  qt.gtimg.cn
  ```

### 系统代理拦截
- **现象**: `clash` (127.0.0.1:7890) 拦截HTTPS，导致 SSL EOF
- **解决**: `requests` 需设置 `trust_env=False` + `proxies={"http":"","https":""}`

### 东方财富限流
- **现象**: 返回空响应
- **解决**: 改用 K线成交量估算 (`amount × chg_pct / 100`)，标记 `data_source='computed'`

---

## 日志文件

```bash
# 数据同步详细日志（含API响应）
/tmp/stock_daily_sync.log

# 网络请求日志（DEBUG级别）
/home/heqiang/.openclaw/workspace/stock-monitor-app-py/logs/

# daily_pick_v10 详细执行日志
/tmp/daily-pick-v10.log
```

---

## 排查流程

```
数据不更新？
  → tail /tmp/stock_daily_sync.log  看 API 响应
  → 检查 /tmp/stock_data_ready.flag  是否存在

推送没收到？
  → tail /tmp/daily-pick-v10.log  看飞书API返回 code
  → code=0 ✅ 成功，code≠0 → 看错误信息

技术指标缺失（RSI=0/NaN）？
  → SELECT COUNT(*) FROM kline_daily WHERE trade_date='2026-03-31' AND rsi14 IS NULL;
  → 重算: python3 scripts/calc_bollinger.py
```
