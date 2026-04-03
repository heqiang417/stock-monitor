"""
Stock data models.
Defines data structures for stock information, history, and K-line data.
"""

from dataclasses import dataclass, field
from typing import Optional, List, Dict
from datetime import datetime


@dataclass
class StockQuote:
    """Real-time stock quote data."""
    symbol: str
    name: str
    price: float = 0.0
    prev_close: float = 0.0
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    volume: int = 0
    amount: float = 0.0
    chg: float = 0.0
    chg_pct: float = 0.0
    bid1_price: float = 0.0
    bid1_vol: int = 0
    ask1_price: float = 0.0
    ask1_vol: int = 0
    turnover_rate: float = 0.0
    pe: float = 0.0
    pb: float = 0.0
    market_cap: float = 0.0
    timestamp: int = 0
    date: str = ""
    time: str = ""
    
    # Derived fields
    volume_surge: float = 0.0
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            'symbol': self.symbol,
            'name': self.name,
            'price': self.price,
            'prev_close': self.prev_close,
            'open': self.open,
            'high': self.high,
            'low': self.low,
            'volume': self.volume,
            'amount': self.amount,
            'chg': self.chg,
            'chg_pct': self.chg_pct,
            'bid1_price': self.bid1_price,
            'bid1_vol': self.bid1_vol,
            'ask1_price': self.ask1_price,
            'ask1_vol': self.ask1_vol,
            'turnover_rate': self.turnover_rate,
            'pe': self.pe,
            'pb': self.pb,
            'market_cap': self.market_cap,
            'timestamp': self.timestamp,
            'date': self.date,
            'time': self.time,
            'volume_surge': self.volume_surge
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'StockQuote':
        """Create StockQuote from dictionary."""
        return cls(
            symbol=data.get('symbol', ''),
            name=data.get('name', ''),
            price=data.get('price', 0.0),
            prev_close=data.get('prev_close', 0.0),
            open=data.get('open', 0.0),
            high=data.get('high', 0.0),
            low=data.get('low', 0.0),
            volume=data.get('volume', 0),
            amount=data.get('amount', 0.0),
            chg=data.get('chg', 0.0),
            chg_pct=data.get('chg_pct', 0.0),
            bid1_price=data.get('bid1_price', 0.0),
            bid1_vol=data.get('bid1_vol', 0),
            ask1_price=data.get('ask1_price', 0.0),
            ask1_vol=data.get('ask1_vol', 0),
            turnover_rate=data.get('turnover_rate', 0.0),
            pe=data.get('pe', 0.0),
            pb=data.get('pb', 0.0),
            market_cap=data.get('market_cap', 0.0),
            timestamp=data.get('timestamp', 0),
            date=data.get('date', ''),
            time=data.get('time', ''),
            volume_surge=data.get('volume_surge', 0.0)
        )


@dataclass
class StockHistory:
    """Historical stock data point."""
    timestamp: int
    price: float
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    volume: int = 0
    amount: float = 0.0
    chg: float = 0.0
    chg_pct: float = 0.0
    bid1_price: float = 0.0
    bid1_vol: int = 0
    ask1_price: float = 0.0
    ask1_vol: int = 0
    
    def to_dict(self) -> dict:
        return {
            'timestamp': self.timestamp,
            'price': self.price,
            'open': self.open,
            'high': self.high,
            'low': self.low,
            'volume': self.volume,
            'amount': self.amount,
            'chg': self.chg,
            'chg_pct': self.chg_pct,
            'bid1_price': self.bid1_price,
            'bid1_vol': self.bid1_vol,
            'ask1_price': self.ask1_price,
            'ask1_vol': self.ask1_vol
        }


@dataclass
class KlineData:
    """K-line (candlestick) data point."""
    symbol: str
    date: str
    open: float
    close: float
    high: float
    low: float
    volume: float = 0.0
    amount: float = 0.0
    chg: float = 0.0
    chg_pct: float = 0.0
    # Technical indicators
    ma5: Optional[float] = None
    ma10: Optional[float] = None
    ma20: Optional[float] = None
    ma60: Optional[float] = None
    rsi14: Optional[float] = None
    
    def to_dict(self) -> dict:
        return {
            'symbol': self.symbol,
            'date': self.date,
            'open': self.open,
            'close': self.close,
            'high': self.high,
            'low': self.low,
            'volume': self.volume,
            'amount': self.amount,
            'chg': self.chg,
            'chg_pct': self.chg_pct,
            'ma5': self.ma5,
            'ma10': self.ma10,
            'ma20': self.ma20,
            'ma60': self.ma60,
            'rsi': self.rsi14
        }


@dataclass
class WatchlistItem:
    """Stock in user's watchlist."""
    symbol: str
    name: str = ""
    added_at: str = ""
    # Real-time quote data (enriched)
    price: float = 0.0
    chg: float = 0.0
    chg_pct: float = 0.0
    
    def to_dict(self) -> dict:
        return {
            'symbol': self.symbol,
            'name': self.name,
            'added_at': self.added_at,
            'price': self.price,
            'chg': self.chg,
            'chg_pct': self.chg_pct
        }


@dataclass
class Sector:
    """Market sector data."""
    name: str
    count: int = 0
    stocks: List[dict] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        return {
            'name': self.name,
            'count': self.count,
            'sample': self.stocks[:5] if self.stocks else []
        }


@dataclass
class MarketIndex:
    """Major market index data."""
    symbol: str
    name: str
    price: float = 0.0
    chg: float = 0.0
    chg_pct: float = 0.0
    volume: int = 0
    amount: float = 0.0
    
    def to_dict(self) -> dict:
        return {
            'symbol': self.symbol,
            'name': self.name,
            'price': self.price,
            'chg': self.chg,
            'chg_pct': self.chg_pct,
            'volume': self.volume,
            'amount': self.amount
        }
