# Runtime / 运行时说明

> 本文件只回答一件事：**这个项目在当前机器上如何真实运行。**

更新日期：2026-04-08

---

## 1. 本地仓库与远端

- 本地目录：`/home/heqiang/.openclaw/workspace/stock-monitor-app-py`
- GitHub 远端：`https://github.com/heqiang417/stock-monitor.git`
- 默认分支：`main`

---

## 2. 核心运行依赖

### Python
- 运行方式：系统 `python3`
- 项目内存在 `venv/`，但当前定时任务以系统 Python 为主

### 数据库
- 主数据库：`/home/heqiang/.openclaw/workspace/stock-monitor-app-py/data/stock_data.db`
- 环境变量名：`STOCK_DB`

### 日志
- `update_tencent`：`/tmp/update_tencent.log`
- `daily_sync`：`/tmp/stock_daily_sync.log`
- `daily_pick_combined`：`/tmp/daily-pick-combined.log`
- ready flag：`/tmp/stock_data_ready.flag`

---

## 3. 当前 cron 主链路

### 收盘后同步
1. `17:00` → `scripts/daily/update_tencent.py --no-weekly --no-monthly`
2. `17:05` → `scripts/daily/calc_bollinger.py`
3. `17:30` → `scripts/daily/daily_sync.py --northbound --margin --shareholder --news --review --chip --limit --index --lhb --block --flow --industry`
4. `20:30` → `scripts/daily/daily_pick_combined.py --push --wait`

### 周期任务
- 周日 `03:00`：`daily_sync.py --fund`

---

## 4. 当前环境变量口径

### `STOCK_DB`
用于显式指定数据库路径。

正确写法示例：

```bash
STOCK_DB=/home/heqiang/.openclaw/workspace/stock-monitor-app-py/data/stock_data.db \
/usr/bin/python3 -u scripts/daily/daily_sync.py --fund
```

### 注意
- 环境变量必须放在命令最前面
- **不能**写成：

```bash
/usr/bin/nice -n 19 STOCK_DB=... /usr/bin/python3 ...
```

否则 shell 会把 `STOCK_DB=...` 当成命令执行，导致：
- `nice: STOCK_DB=...: No such file or directory`
- 或数据库路径失效

---

## 5. 当前唯一官方生产入口

### 生产数据链路
- `scripts/daily/update_tencent.py`
- `scripts/daily/calc_bollinger.py`
- `scripts/daily/daily_sync.py`

### 生产选股入口
- `scripts/daily/daily_pick_combined.py`

### 非官方/历史入口
以下脚本仍保留，但**不是当前官方生产入口**：
- `scripts/daily/daily_pick_v10.py`
- `scripts/daily/daily_pick_bb099.py`
- `scripts/daily/daily_pick_bb100.py`

---

## 6. 当前运行原则

- 生产任务以 cron 为准，不以历史 README 示例为准
- 选股推送以 `daily_pick_combined.py` 为准
- 路径、环境变量、ready flag 写法必须与 cron 口径一致
- 若文档与真实运行不一致，应以真实运行修正文档，而不是反过来
