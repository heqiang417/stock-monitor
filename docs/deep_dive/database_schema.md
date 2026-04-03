# 数据库结构

> L3 深处：调试 / 数据验证 / 理解底层存储

---

## 主要表

### `kline_daily` — 日线K线（核心表）

```sql
CREATE TABLE kline_daily (
    id              INTEGER PRIMARY KEY,
    symbol          TEXT NOT NULL,          -- e.g. 'sh600519', 'sz002095'
    trade_date      TEXT NOT NULL,         -- e.g. '2026-03-31'
    open            REAL NOT NULL,
    close           REAL NOT NULL,
    high            REAL NOT NULL,
    low             REAL NOT NULL,
    volume          REAL,                  -- 成交量（手）
    amount          REAL,                  -- 成交额（元）
    chg             REAL,                  -- 涨跌额
    chg_pct         REAL,                  -- 涨跌幅（%）
    
    -- 技术指标
    ma5             REAL,
    ma10            REAL,
    ma20            REAL,
    ma60            REAL,
    rsi14           REAL,                  -- 14日RSI
    macd_dif        REAL,
    macd_dea        REAL,
    macd_hist       REAL,
    boll_upper      REAL,                  -- 布林上轨
    boll_mid        REAL,                  -- 布林中轨（=MA20）
    boll_lower      REAL,                  -- 布林下轨
    kdj_k           REAL,
    kdj_d           REAL,
    kdj_j           REAL,
    adx             REAL,
    plus_di         REAL,
    minus_di        REAL,
    atr             REAL,

    UNIQUE(symbol, trade_date)
);
```

**常用查询：**
```sql
-- 查某只股票最新数据
SELECT * FROM kline_daily 
WHERE symbol='sz002149' 
ORDER BY trade_date DESC LIMIT 5;

-- 查今日RSI<20的股票
SELECT symbol, close, rsi14, boll_lower 
FROM kline_daily 
WHERE trade_date='2026-03-31' 
  AND rsi14 < 20 
  AND boll_lower IS NOT NULL;

-- 统计今日数据完整性
SELECT COUNT(*) total,
       SUM(CASE WHEN rsi14 IS NOT NULL THEN 1 END) has_rsi,
       SUM(CASE WHEN boll_lower IS NOT NULL THEN 1 END) has_bb
FROM kline_daily WHERE trade_date='2026-03-31';
```

### `financial_indicators` — 财务指标

```sql
CREATE TABLE financial_indicators (
    symbol          TEXT,
    report_date     TEXT,          -- 财报期
    roe             REAL,          -- 净资产收益率
    revenue_growth  REAL,          -- 营收增长率
    profit_growth   REAL,          -- 净利润增长率
    gross_margin    REAL,          -- 毛利率
    debt_ratio      REAL,          -- 资产负债率
    -- ...
);
```

### `money_flow` — 资金流向

```sql
CREATE TABLE money_flow (
    symbol      TEXT,
    trade_date  TEXT,
    amount       REAL,            -- 成交额
    chg_pct     REAL,            -- 涨跌幅
    data_source TEXT,            -- 'api'=东方财富 / 'computed'=K线估算
    -- ...
);
```

---

## 数据量

| 表 | 记录数 | 说明 |
|---|--------|------|
| kline_daily | ~632万行 | 2007年至今 |
| financial_indicators | ~12万行 | 最新财报 |
| money_flow | ~430万行 | 部分为估算 |

---

## 数据文件

- **SQLite**: `stock-monitor-app-py/data/stock_data.db`（~3.0GB）
- **每日备份**: `stock_data.db` 由 update 脚本实时写入，WAL 模式
