# DB — 数据库层

## 职责

DB 模块提供 SQLite 数据库的统一访问接口。核心是 `DatabaseManager`（线程安全连接池）和 `connect_db()` 兼容函数。数据库文件路径由 `config.DB_PATH` 指定（默认 `data/stock_data.db`）。

数据库使用 **WAL 模式**（Write-Ahead Logging），提升并发读写性能。

---

## 关键文件

| 文件 | 作用 |
|------|------|
| `db/__init__.py` | 导出 `DatabaseManager`、`connect_db()` |
| `db/stock_data.db` | SQLite 数据库文件（数据持久化） |

---

## 对外接口

### DatabaseManager（推荐）

```python
from db import DatabaseManager

db = DatabaseManager('data/stock_data.db', pool_size=5)

# 上下文管理器（自动归还连接）
with db.get_connection() as conn:
    conn.execute('INSERT INTO alerts ...', (values,))

# 带 row_factory 的游标（dict-like access）
with db.get_cursor() as cursor:
    cursor.execute('SELECT * FROM alerts WHERE id=?', (1,))
    row = cursor.fetchone()
    print(row['message'])   # sqlite3.Row 支持索引访问

# 便捷查询
row = db.fetch_one('SELECT * FROM alerts WHERE id=?', (1,))     # -> dict | None
rows = db.fetch_all('SELECT * FROM alerts WHERE is_read=0')      # -> List[dict]
count = db.execute('UPDATE alerts SET is_read=1 WHERE id=?', (1,))  # -> rowcount

# 批量写入
db.execute_many('INSERT INTO kline_daily VALUES (?,?,?,?,?,?,?,?,?)', rows_list)

# 关闭连接池
db.close_pool()
```

### connect_db()（兼容旧代码）

```python
from db import connect_db

conn = connect_db('data/stock_data.db')
# 返回原始 sqlite3.Connection，配置了 WAL + 性能优化 PRAGMA
# 不推荐在新代码中使用，仅保留向后兼容
```

---

## 数据库 Schema

主要表：

| 表名 | 用途 |
|------|------|
| `stock_history` | 分时历史行情（高频写入） |
| `watchlist` | 自选股列表 |
| `kline_daily` | 日K线数据（含均线、RSI 等技术指标） |
| `alerts` | 告警记录（当前会话） |
| `alert_history` | 告警历史（持久化） |

详细 schema 见 [database_schema.md](./database_schema.md)。

---

## 连接池原理

`DatabaseManager` 内部使用 `config.ConnectionPool`：

```
ConnectionPool
├── Queue(max_connections=5)   # 预创建 5 个连接，复用减少开销
├── WAL mode + busy_timeout    # 并发安全
└── mmap_size=256MB            # 内存映射，加速大查询
```

每次 `get_connection()` 从 Queue 获取，用完通过 `return_connection()` 归还。

---

## 注意事项

- `DatabaseManager` 是线程安全的，可在 BackgroundService 的多个线程中使用
- 使用上下文管理器 `with db.get_connection()` 确保连接归还，避免泄漏
- `fetch_one/fetch_all` 自动设置 `row_factory = sqlite3.Row`，返回 dict
- 数据库文件在 `data/stock_data.db`，如需迁移注意同时迁移 WAL/shm 文件
