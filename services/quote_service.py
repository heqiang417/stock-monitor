"""
Quote service.
Handles real-time quote fetching from Tencent Finance API with caching.
"""

import time
import re
import requests
import logging
from collections import OrderedDict
from typing import List, Optional, Dict, Any

from models.stock import MarketIndex

logger = logging.getLogger(__name__)


def _retry_api_call(func):
    """Decorator for API calls with exponential backoff retry."""
    import functools
    
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        max_retries = 3
        backoff = 1
        last_exception = None
        
        for attempt in range(max_retries):
            try:
                return func(*args, **kwargs)
            except (requests.exceptions.ConnectionError,
                    requests.exceptions.Timeout,
                    UnicodeDecodeError) as e:
                last_exception = e
                if attempt < max_retries - 1:
                    wait = backoff * (2 ** attempt)
                    logger.warning(f"{func.__name__} attempt {attempt + 1} failed: {e}. Retrying in {wait}s...")
                    time.sleep(wait)
                else:
                    logger.error(f"{func.__name__} failed after {max_retries} attempts: {e}")
            except Exception as e:
                logger.error(f"{func.__name__} non-retryable error: {e}")
                raise
        
        return [] if 'fetch' in func.__name__ else None
    
    return wrapper


class QuoteService:
    """Fetches and caches real-time stock quotes."""
    
    INDEX_CODES = [
        'sh000001',  # 上证指数
        'sz399001',  # 深证成指
        'sz399006',  # 创业板指
        'sh000300',  # 沪深300
        'sh000905',  # 中证500
    ]
    
    def __init__(self, api_url: str = 'https://qt.gtimg.cn/q=', cache_ttl: int = 10, cache_max_size: int = 1000):
        self.api_url = api_url
        self.cache_ttl = cache_ttl
        self._cache_max_size = cache_max_size
        self._quote_cache: OrderedDict[str, Dict[str, Any]] = OrderedDict()
    
    def get_cached_quote(self, symbol: str) -> Optional[dict]:
        """Get cached quote if still valid. LRU-aware."""
        if symbol in self._quote_cache:
            entry = self._quote_cache[symbol]
            if time.time() - entry['ts'] < self.cache_ttl:
                self._quote_cache.move_to_end(symbol)
                return entry['data']
            else:
                del self._quote_cache[symbol]
        return None
    
    def set_cached_quote(self, symbol: str, data: dict):
        """Store quote in cache with LRU eviction."""
        if symbol in self._quote_cache:
            del self._quote_cache[symbol]
        elif len(self._quote_cache) >= self._cache_max_size:
            self._quote_cache.popitem(last=False)  # evict oldest
        self._quote_cache[symbol] = {'ts': time.time(), 'data': data}
    
    def clear_cache(self):
        """Clear all cached quotes."""
        self._quote_cache.clear()
    
    def cleanup_expired(self):
        """Remove expired entries from cache."""
        now = time.time()
        expired = [k for k, v in self._quote_cache.items() if now - v['ts'] >= self.cache_ttl]
        for k in expired:
            del self._quote_cache[k]
        if expired:
            logger.debug(f"Cleaned up {len(expired)} expired cache entries")
    
    @_retry_api_call
    def fetch_tencent_data(self, symbols: List[str]) -> List[dict]:
        """
        Fetch stock data from Tencent Finance API.
        Handles GBK encoding properly. Uses cache for recently fetched symbols.
        """
        if not symbols:
            return []
        
        # Check cache first
        uncached = []
        results = []
        for sym in symbols:
            cached = self.get_cached_quote(sym)
            if cached:
                results.append(cached)
            else:
                uncached.append(sym)
        
        if not uncached:
            return results
        
        # Fetch uncached symbols
        query = ','.join(uncached)
        url = f"{self.api_url}{query}"
        
        headers = {
            'Referer': 'https://finance.qq.com',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        resp = requests.get(url, headers=headers, timeout=10)
        resp.encoding = 'gbk'
        raw_data = resp.text
        
        stocks = []
        for line in raw_data.strip().split('\n'):
            line = line.strip()
            if not line:
                continue
            
            match = re.match(r'v_(\w+)="([^"]+)"', line)
            if not match:
                continue
            
            symbol = match.group(1)
            fields = match.group(2).split('~')
            
            if len(fields) < 50:
                continue
            
            try:
                stock = {
                    'symbol': symbol,
                    'name': fields[1],
                    'open': float(fields[5]) if fields[5] else 0,
                    'prev_close': float(fields[4]) if fields[4] else 0,
                    'price': float(fields[3]) if fields[3] else 0,
                    'high': float(fields[33]) if fields[33] else 0,
                    'low': float(fields[34]) if fields[34] else 0,
                    'volume': int(fields[6]) if fields[6] else 0,
                    'amount': float(fields[37]) if fields[37] else 0,
                    'bid1_price': float(fields[9]) if fields[9] else 0,
                    'bid1_vol': int(fields[10]) if fields[10] else 0,
                    'ask1_price': float(fields[19]) if fields[19] else 0,
                    'ask1_vol': int(fields[20]) if fields[20] else 0,
                    'chg': float(fields[31]) if fields[31] else 0,
                    'chg_pct': float(fields[32]) if fields[32] else 0,
                    'turnover_rate': float(fields[38]) if fields[38] and len(fields) > 38 else 0,
                    'pe': float(fields[39]) if fields[39] and len(fields) > 39 else 0,
                    'pb': float(fields[46]) if fields[46] and len(fields) > 46 else 0,
                    'market_cap': float(fields[45]) if fields[45] and len(fields) > 45 else 0,
                    'date': fields[30] if len(fields) > 30 else '',
                    'time': fields[31] if len(fields) > 31 else '',
                    'timestamp': int(time.time() * 1000)
                }
                self.set_cached_quote(symbol, stock)
                stocks.append(stock)
            except (ValueError, IndexError) as e:
                logger.warning(f"Parse error for {symbol}: {e}")
                continue
        
        return results + stocks
    
    def fetch_indexes(self) -> List[MarketIndex]:
        """Fetch major market indexes."""
        stocks = self.fetch_tencent_data(self.INDEX_CODES)
        return [MarketIndex(
            symbol=s['symbol'],
            name=s['name'],
            price=s['price'],
            chg=s['chg'],
            chg_pct=s['chg_pct'],
            volume=s['volume'],
            amount=s['amount']
        ) for s in stocks]
