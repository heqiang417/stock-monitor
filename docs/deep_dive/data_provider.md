# Data Provider — 多数据源架构

## 职责

Data Provider 是应用的数据获取层，实现了多数据源按优先级自动切换的机制。当一个数据源失败或不可用时，自动切换到下一个优先级更高的数据源。对上层屏蔽了数据来源细节。

当前支持的数据源：腾讯财经（Tencent）、AKShare、EFinance、Baostock、Tushare。

---

## 关键文件

| 文件 | 作用 |
|------|------|
| `data_provider/__init__.py` | 导出 `DataFetcherManager`、`BaseFetcher`、工具函数 |
| `data_provider/manager.py` | `DataFetcherManager`：多数据源统一调度，按优先级尝试，失败自动切换 |
| `data_provider/base.py` | `BaseFetcher` 抽象基类 + 标准化工具函数（`normalize_symbol`、`symbol_to_code`、`normalize_columns`） |
| `data_provider/tencent_fetcher.py` | 腾讯财经实时行情 + 历史K线获取 |
| `data_provider/akshare_fetcher.py` | AKShare 日线/分钟线/实时行情 |
| `data_provider/efinance_fetcher.py` | EFinance 日线/分钟线/实时行情 |
| `data_provider/baostock_fetcher.py` | Baostock 日线/实时行情 |
| `data_provider/tushare_fetcher.py` | Tushare 行情（需要 Token，目前可用） |

---

## 对外接口

### DataFetcherManager

```python
from data_provider import DataFetcherManager
from data_provider.tencent_fetcher import TencentFetcher
from data_provider.akshare_fetcher import AkshareFetcher

manager = DataFetcherManager()
manager.register(TencentFetcher(priority=0))   # 优先级 0（最高）
manager.register(AkshareFetcher(priority=1))    # 优先级 1（次高）

# 获取日K线
df = manager.get_daily_data('sz002149', '20250101', '20260325')

# 获取任意周期K线
df = manager.get_period_data('sz002149', '20250101', '20260325', period='daily')

# 获取实时行情
quotes = manager.get_realtime_quote(['sz002149', 'sh600519'])

# 查看可用数据源
available = manager.list_available()  # -> List[str]
```

### BaseFetcher 抽象接口

```python
class BaseFetcher(ABC):
    priority: int      # 优先级（越小越高）
    name: str          # 数据源名称

    @abstractmethod
    def get_daily_data(self, symbol, start_date, end_date) -> pd.DataFrame:
        """返回标准列 DataFrame: date, open, high, low, close, volume, amount, chg_pct"""

    @abstractmethod
    def get_realtime_quote(self, symbols: List[str]) -> List[Dict]:
        """返回实时行情列表"""

    @abstractmethod
    def is_available(self) -> bool:
        """检查数据源是否可用（网络/API key等）"""
```

### 标准化工具函数

```python
from data_provider.base import normalize_symbol, symbol_to_code, normalize_columns

normalize_symbol('002149')     # -> 'sz002149'
symbol_to_code('sz002149')     # -> '002149'
normalize_columns(df, source)  # -> 列名标准化的 DataFrame
```

---

## 数据源优先级

优先级由 `register()` 调用顺序决定，或显式指定 `priority` 参数：

| 数据源 | 类型 | 说明 |
|--------|------|------|
| TencentFetcher | 实时行情 + 日K | 优先级高，速度快，免费 |
| AkshareFetcher | 日K + 分钟K | 备用，数据全 |
| EFinanceFetcher | 日K + 分钟K | 备用 |
| BaostockFetcher | 日K | 备用 |
| TushareFetcher | 实时 + 日K | 需要 Token |

---

## 注意事项

- `DataFetcherManager` 使用**短路策略**：优先源成功即返回，不再尝试后续
- 各 fetcher 的 `get_daily_data` 返回标准列名格式（统一由 `normalize_columns` 处理）
- `is_available()` 检查网络可达性或 API key 有效性
- symbol 格式统一使用 `sz/sh/bj` 前缀（如 `sz002149`）
- 如需新增数据源，继承 `BaseFetcher` 并实现三个抽象方法，然后 `manager.register()`
