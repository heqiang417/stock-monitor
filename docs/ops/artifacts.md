# 运行产物说明

> 本文件用于定义：哪些目录是“运行产物”，哪些目录是“正式资产”。

更新日期：2026-04-08

---

## 1. `reports/daily_picks/`

### 定位
- 每日推送留痕
- 主要用于复盘、比对推送结果、排查当日选股输出

### 归类
- **运行产物**，不是核心源码资产
- 默认不应持续进入版本控制

---

## 2. `data/results/`

### 定位
- 探索结果 JSON
- 评估输出 JSON / md
- 搜索中间结果
- 历史实验结果

### 归类
- 绝大多数属于**运行产物 / 中间产物**
- 只有少数被正式引用的结果，才值得长期保留并写入文档

### 原则
- 不把 `data/results/` 当成主文档区
- 结果若要长期保留，应通过：
  - `docs/strategy/`
  - `docs/backtesting/reports/`
  - `backtest/`
 进行沉淀

---

## 3. `backtest/`

### 定位
- 回测引擎与回测产出
- 如 trades JSON、引擎代码、回测 API

### 归类
- **混合区**：既有正式代码，也有正式结果资产

### 原则
- `backtest/*.py` 属于正式代码
- 被正式引用的 trades JSON 可以保留
- 临时试验产出不应无限堆积

---

## 4. `docs/backtesting/reports/`

### 定位
- 当前主线回测报告
- 当前仍被策略索引、README、手册引用的报告

### 归类
- **正式资产**

---

## 5. `docs/backtesting/archive/`

### 定位
- 历史报告归档
- 旧策略、旧搜索链条、重复版本保留区

### 归类
- **正式归档资产**

---

## 6. 一句话规则

- `reports/` → 留痕
- `data/results/` → 中间结果
- `backtest/` → 回测代码 + 正式回测资产
- `docs/backtesting/reports/` → 当前主线报告
- `docs/backtesting/archive/` → 历史归档
