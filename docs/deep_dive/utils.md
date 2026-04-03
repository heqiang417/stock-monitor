# Utils — 工具函数

## 职责

Utils 提供跨模块复用的纯函数和常量，不涉及业务逻辑，不持有状态。目前内容精简，聚焦于交易日判断和股票代码规范化两个高频工具函数。

---

## 关键文件

| 文件 | 作用 |
|------|------|
| `utils/__init__.py` | 导出 `is_trading_time()`、`normalize_symbol()`、`datetime` |

---

## 对外接口

### is_trading_time()

```python
from utils import is_trading_time

is_trading_time() -> bool
```

判断当前时间是否在 A 股交易时段：
- 周一至周五（非周末）
- 9:30–11:30（上午）
- 13:00–15:00（下午）

**用途**：BackgroundService 中判断是否执行交易时段逻辑；WebSocket 推送时告知客户端当前是否为交易时间。

---

### normalize_symbol()

```python
from utils import normalize_symbol

normalize_symbol(symbol: str) -> str
```

标准化股票代码，添加交易所有前缀：

| 输入 | 输出 |
|------|------|
| `'002149'` | `'sz002149'`（深交所） |
| `'600000'` | `'sh600000'`（上交所） |
| `'sz002149'` | `'sz002149'`（已规范化，直接返回） |
| `'sh600000'` | `'sh600000'`（已规范化，直接返回） |
| `'9'` / 数字开头 9 | `'bj9...'`（北交所，代码以9开头） |

**规则**：
- 已带 `sz`/`sh`/`bj` 前缀 → 直接返回
- 纯数字 → 以首位判断交易所：6开头=上交所 `sh`，其他=深交所 `sz`

**用途**：所有接收股票代码的入口（routes、services、data_provider）统一先规范化，避免查询失败。

---

## 注意事项

- `utils/` 目前只有这两个函数，后续应保持这个原则：只放**无状态纯函数**
- 如需引入新工具函数，先确认是否已有类似功能，避免重复
- `utils/` 不依赖数据库或网络，可安全在线程中使用
