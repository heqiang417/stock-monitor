"""
Stock service.
Handles stock data fetching, caching, database operations, and market scanning.
Composes QuoteService and MarketDataService for focused responsibilities.
"""

import time
import logging
import os
import requests
from datetime import datetime
from collections import deque
from typing import List, Optional, Dict, Any, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

from models.stock import StockQuote, StockHistory, KlineData, WatchlistItem, Sector, MarketIndex
from db import DatabaseManager, _is_postgres_target
from services.market_service import MarketDataService
from services.quote_service import QuoteService

logger = logging.getLogger(__name__)


class StockService:
    """Service for stock data operations. Composes MarketData + Quote services."""
    
    def __init__(self, db_path: str, config: Any):
        self.db_path = db_path
        self.config = config
        
        # Compose focused services
        self._market = MarketDataService()
        self._quote = QuoteService(
            api_url=getattr(config, 'TENCENT_API', 'https://qt.gtimg.cn/q='),
            cache_ttl=getattr(config, 'QUOTE_CACHE_TTL', 10)
        )
        
        # Database
        self._db = DatabaseManager(db_path)
        
        # History for SSE
        self._history = deque(maxlen=100)
        
        # Thread pool
        self._max_workers = getattr(config, 'MAX_WORKERS', 4)

    # ==================== Delegated: Market Data ====================
    
    def load_full_market_data(self):
        """Reload full A-share market data."""
        self._market.load_full_market_data()
    
    def get_stock_by_symbol(self, symbol: str) -> Optional[dict]:
        """Get stock info by symbol from full market data."""
        return self._market.get_stock_by_symbol(symbol)
    
    def get_sectors(self) -> List[str]:
        """Get list of all sector names."""
        return self._market.get_sectors()
    
    def get_sector_stocks(self, sector_name: str) -> List[dict]:
        """Get stocks in a specific sector."""
        return self._market.get_sector_stocks(sector_name)

    # ==================== Delegated: Quote Fetching ====================
    
    def get_cached_quote(self, symbol: str) -> Optional[dict]:
        """Get cached quote if still valid."""
        return self._quote.get_cached_quote(symbol)
    
    def set_cached_quote(self, symbol: str, data: dict):
        """Store quote in cache."""
        self._quote.set_cached_quote(symbol, data)
    
    def fetch_tencent_data(self, symbols: List[str]) -> List[dict]:
        """Fetch stock data from Tencent Finance API."""
        return self._quote.fetch_tencent_data(symbols)
    
    def fetch_indexes(self) -> List[MarketIndex]:
        """Fetch major market indexes."""
        return self._quote.fetch_indexes()

    # ==================== Database Operations ====================
    
    def init_db(self):
        """Initialize application-owned tables required by the app."""
        ddl_statements = []

        if _is_postgres_target(self.db_path):
            ddl_statements = [
                '''
                CREATE TABLE IF NOT EXISTS stock_history (
                    id BIGSERIAL PRIMARY KEY,
                    timestamp BIGINT NOT NULL,
                    price DOUBLE PRECISION NOT NULL,
                    open DOUBLE PRECISION,
                    high DOUBLE PRECISION,
                    low DOUBLE PRECISION,
                    volume BIGINT,
                    amount DOUBLE PRECISION,
                    chg DOUBLE PRECISION,
                    chg_pct DOUBLE PRECISION,
                    bid1_price DOUBLE PRECISION,
                    bid1_vol BIGINT,
                    ask1_price DOUBLE PRECISION,
                    ask1_vol BIGINT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                ''',
                '''
                CREATE TABLE IF NOT EXISTS watchlist (
                    symbol TEXT PRIMARY KEY,
                    name TEXT,
                    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                ''',
                '''
                CREATE TABLE IF NOT EXISTS kline_weekly (
                    id BIGSERIAL PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    trade_week TEXT NOT NULL,
                    open DOUBLE PRECISION NOT NULL,
                    close DOUBLE PRECISION NOT NULL,
                    high DOUBLE PRECISION NOT NULL,
                    low DOUBLE PRECISION NOT NULL,
                    volume DOUBLE PRECISION,
                    amount DOUBLE PRECISION,
                    chg DOUBLE PRECISION,
                    chg_pct DOUBLE PRECISION,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(symbol, trade_week)
                )
                ''',
                '''
                CREATE TABLE IF NOT EXISTS kline_monthly (
                    id BIGSERIAL PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    trade_month TEXT NOT NULL,
                    open DOUBLE PRECISION NOT NULL,
                    close DOUBLE PRECISION NOT NULL,
                    high DOUBLE PRECISION NOT NULL,
                    low DOUBLE PRECISION NOT NULL,
                    volume DOUBLE PRECISION,
                    amount DOUBLE PRECISION,
                    chg DOUBLE PRECISION,
                    chg_pct DOUBLE PRECISION,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(symbol, trade_month)
                )
                ''',
                'CREATE INDEX IF NOT EXISTS idx_kline_weekly_symbol ON kline_weekly(symbol)',
                'CREATE INDEX IF NOT EXISTS idx_kline_monthly_symbol ON kline_monthly(symbol)',
                'CREATE INDEX IF NOT EXISTS idx_stock_history_ts ON stock_history(timestamp)',
            ]
        else:
            ddl_statements = [
                '''
                CREATE TABLE IF NOT EXISTS stock_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp INTEGER NOT NULL,
                    price REAL NOT NULL,
                    open REAL, high REAL, low REAL,
                    volume INTEGER, amount REAL,
                    chg REAL, chg_pct REAL,
                    bid1_price REAL, bid1_vol INTEGER,
                    ask1_price REAL, ask1_vol INTEGER,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                ''',
                '''
                CREATE TABLE IF NOT EXISTS watchlist (
                    symbol TEXT PRIMARY KEY,
                    name TEXT,
                    added_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                ''',
                '''
                CREATE TABLE IF NOT EXISTS kline_daily (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    trade_date TEXT NOT NULL,
                    open REAL NOT NULL, close REAL NOT NULL,
                    high REAL NOT NULL, low REAL NOT NULL,
                    volume REAL, amount REAL,
                    chg REAL, chg_pct REAL,
                    ma5 REAL, ma10 REAL, ma20 REAL, ma60 REAL,
                    rsi14 REAL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(symbol, trade_date)
                )
                ''',
                '''
                CREATE TABLE IF NOT EXISTS kline_weekly (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    trade_week TEXT NOT NULL,
                    open REAL NOT NULL, close REAL NOT NULL,
                    high REAL NOT NULL, low REAL NOT NULL,
                    volume REAL, amount REAL,
                    chg REAL, chg_pct REAL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(symbol, trade_week)
                )
                ''',
                '''
                CREATE TABLE IF NOT EXISTS kline_monthly (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    trade_month TEXT NOT NULL,
                    open REAL NOT NULL, close REAL NOT NULL,
                    high REAL NOT NULL, low REAL NOT NULL,
                    volume REAL, amount REAL,
                    chg REAL, chg_pct REAL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(symbol, trade_month)
                )
                ''',
                'CREATE INDEX IF NOT EXISTS idx_kline_daily_symbol ON kline_daily(symbol)',
                'CREATE INDEX IF NOT EXISTS idx_kline_daily_date ON kline_daily(trade_date)',
                'CREATE INDEX IF NOT EXISTS idx_kline_weekly_symbol ON kline_weekly(symbol)',
                'CREATE INDEX IF NOT EXISTS idx_kline_monthly_symbol ON kline_monthly(symbol)',
                'CREATE INDEX IF NOT EXISTS idx_stock_history_ts ON stock_history(timestamp)',
                'CREATE INDEX IF NOT EXISTS idx_kline_daily_symbol_date ON kline_daily(symbol, trade_date)',
            ]

        with self._db.get_connection() as conn:
            c = conn.cursor()
            for sql in ddl_statements:
                c.execute(sql)

        logger.info(f"Database initialized at {self.db_path}")
    
    def insert_stock_history(self, data: dict):
        """Insert a stock data record into the database."""
        self._db.execute('''
            INSERT INTO stock_history 
            (timestamp, price, open, high, low, volume, amount, chg, chg_pct, 
             bid1_price, bid1_vol, ask1_price, ask1_vol)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            data.get('timestamp', int(time.time() * 1000)),
            data.get('price', 0), data.get('open', 0),
            data.get('high', 0), data.get('low', 0),
            data.get('volume', 0), data.get('amount', 0),
            data.get('chg', 0), data.get('chg_pct', 0),
            data.get('bid1_price', 0), data.get('bid1_vol', 0),
            data.get('ask1_price', 0), data.get('ask1_vol', 0)
        ))
    
    def get_stock_history(self, limit: int = 100) -> List[dict]:
        """Get recent stock history from database."""
        return self._db.fetch_all('''
            SELECT timestamp, price, open, high, low, volume, amount, chg, chg_pct,
                   bid1_price, bid1_vol, ask1_price, ask1_vol
            FROM stock_history ORDER BY timestamp DESC LIMIT ?
        ''', (limit,))
    
    def get_watchlist(self) -> List[WatchlistItem]:
        """Get all stocks in the watchlist."""
        rows = self._db.fetch_all('SELECT symbol, name, added_at FROM watchlist ORDER BY added_at DESC')
        return [WatchlistItem(symbol=row['symbol'], name=row['name'], added_at=row['added_at']) for row in rows]
    
    def add_to_watchlist(self, symbol: str, name: Optional[str] = None):
        """Add a stock to the watchlist."""
        if _is_postgres_target(self.db_path):
            self._db.execute(
                '''INSERT INTO watchlist (symbol, name, added_at)
                   VALUES (?, ?, CURRENT_TIMESTAMP)
                   ON CONFLICT (symbol) DO UPDATE SET
                     name = EXCLUDED.name,
                     added_at = CURRENT_TIMESTAMP''',
                (symbol, name or symbol)
            )
        else:
            self._db.execute('INSERT OR REPLACE INTO watchlist (symbol, name, added_at) VALUES (?, ?, CURRENT_TIMESTAMP)',
                             (symbol, name or symbol))
        logger.info(f"Added {symbol} to watchlist")
    
    def remove_from_watchlist(self, symbol: str):
        """Remove a stock from the watchlist."""
        self._db.execute('DELETE FROM watchlist WHERE symbol = ?', (symbol,))
        logger.info(f"Removed {symbol} from watchlist")
    
    def save_kline_daily(self, symbol: str, kline_data: List[dict]):
        """Save daily K-line data to database."""
        for row in kline_data:
            try:
                if _is_postgres_target(self.db_path):
                    self._db.execute('''
                        INSERT INTO kline_daily 
                        (symbol, trade_date, open, close, high, low, volume, amount, chg, chg_pct, ma5, ma10, ma20, ma60, rsi14)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT (symbol, trade_date) DO UPDATE SET
                            open = EXCLUDED.open,
                            close = EXCLUDED.close,
                            high = EXCLUDED.high,
                            low = EXCLUDED.low,
                            volume = EXCLUDED.volume,
                            amount = EXCLUDED.amount,
                            chg = EXCLUDED.chg,
                            chg_pct = EXCLUDED.chg_pct,
                            ma5 = EXCLUDED.ma5,
                            ma10 = EXCLUDED.ma10,
                            ma20 = EXCLUDED.ma20,
                            ma60 = EXCLUDED.ma60,
                            rsi14 = EXCLUDED.rsi14
                    ''', (
                        symbol, row.get('date'), row.get('open'), row.get('close'),
                        row.get('high'), row.get('low'), row.get('volume'), row.get('amount', 0),
                        row.get('chg', 0), row.get('chg_pct', 0),
                        row.get('ma5'), row.get('ma10'), row.get('ma20'), row.get('ma60'), row.get('rsi')
                    ))
                else:
                    self._db.execute('''
                        INSERT OR REPLACE INTO kline_daily 
                        (symbol, trade_date, open, close, high, low, volume, amount, chg, chg_pct, ma5, ma10, ma20, ma60, rsi14)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        symbol, row.get('date'), row.get('open'), row.get('close'),
                        row.get('high'), row.get('low'), row.get('volume'), row.get('amount', 0),
                        row.get('chg', 0), row.get('chg_pct', 0),
                        row.get('ma5'), row.get('ma10'), row.get('ma20'), row.get('ma60'), row.get('rsi')
                    ))
            except Exception as e:
                logger.error(f"Error saving kline: {e}")
        logger.info(f"Saved {len(kline_data)} daily K-line records for {symbol}")
    
    def load_kline_daily(self, symbol: str, limit: int = 365) -> List[dict]:
        """Load daily K-line data from database."""
        rows = self._db.fetch_all('''
            SELECT trade_date, open, close, high, low, volume, amount, chg, chg_pct, ma5, ma10, ma20, ma60, rsi14
            FROM kline_daily WHERE symbol = ? ORDER BY trade_date DESC LIMIT ?
        ''', (symbol, limit))
        
        result = []
        for row in reversed(rows):
            result.append({
                'date': row['trade_date'], 'open': row['open'], 'close': row['close'],
                'high': row['high'], 'low': row['low'], 'volume': row['volume'],
                'amount': row['amount'], 'chg': row['chg'], 'chg_pct': row['chg_pct'],
                'ma5': row['ma5'], 'ma10': row['ma10'], 'ma20': row['ma20'],
                'ma60': row['ma60'], 'rsi': row['rsi14']
            })
        return result
    
    def cleanup_old_data(self, days: int = 30) -> dict:
        """Clean up old data from stock_history table."""
        cutoff = int((time.time() - days * 86400) * 1000)
        deleted = self._db.execute('DELETE FROM stock_history WHERE timestamp < ?', (cutoff,))
        logger.info(f"Cleanup: deleted {deleted} history records older than {days} days")
        return {'history_deleted': deleted}

    # ==================== K-line Fetching ====================
    
    def fetch_kline_data(self, symbol: str, ktype: str = 'day', num: int = 60, use_cache: bool = True) -> List[dict]:
        """Fetch K-line data from Tencent API or database."""
        from utils import normalize_symbol
        symbol = normalize_symbol(symbol)
        
        if use_cache and ktype == 'day':
            cached = self.load_kline_daily(symbol, limit=num)
            if len(cached) >= num * 0.8:
                logger.info(f"Using cached K-line data for {symbol}: {len(cached)} records")
                return cached
        
        url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get%sparam={symbol},{ktype},,,{num},qfq"
        headers = {
            'Referer': 'https://finance.qq.com',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        try:
            resp = requests.get(url, headers=headers, timeout=10)
            resp.encoding = 'utf-8'
            data = resp.json()
            
            if data.get('code') != 0:
                return []
            
            kline_key = f'qfq{ktype}' if ktype in ['day', 'week', 'month'] else 'qfqday'
            raw = data.get('data', {}).get(symbol, {}).get(kline_key, [])
            
            result = []
            for row in raw:
                if len(row) >= 6:
                    result.append({
                        'date': row[0],
                        'open': float(row[1]) if row[1] else 0,
                        'close': float(row[2]) if row[2] else 0,
                        'high': float(row[3]) if row[3] else 0,
                        'low': float(row[4]) if row[4] else 0,
                        'volume': float(row[5]) if row[5] else 0
                    })
            
            if ktype == 'day' and result:
                self.save_kline_daily(symbol, result)
            
            return result
        except Exception as e:
            logger.error(f"K-line fetch error: {e}", exc_info=True)
            return []
    
    def fetch_kline_eastmoney(self, symbol: str, days: int = 1250) -> List[dict]:
        """Fetch historical daily K-line data from Eastmoney API."""
        if symbol.startswith('sz'):
            secid = f"0.{symbol[2:]}"
        elif symbol.startswith('sh'):
            secid = f"1.{symbol[2:]}"
        else:
            secid = f"1.{symbol}" if symbol.startswith('6') else f"0.{symbol}"
        
        url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
        params = {
            'secid': secid,
            'fields1': 'f1,f2,f3,f4,f5,f6',
            'fields2': 'f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61',
            'klt': '101', 'fqt': '1', 'beg': '0', 'end': '20500101',
            'lmt': str(min(days, 5000))
        }
        headers = {
            'Referer': 'https://stock.eastmoney.com',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=15)
            resp.encoding = 'utf-8'
            data = resp.json()
            
            klines = data.get('data', {}).get('klines', [])
            if not klines:
                logger.warning(f"Eastmoney API returned no data for {symbol}")
                return []
            
            result = []
            for row in klines:
                parts = row.split(',')
                if len(parts) >= 6:
                    result.append({
                        'date': parts[0],
                        'open': float(parts[1]) if parts[1] else 0,
                        'close': float(parts[2]) if parts[2] else 0,
                        'high': float(parts[3]) if parts[3] else 0,
                        'low': float(parts[4]) if parts[4] else 0,
                        'volume': float(parts[5]) if parts[5] else 0
                    })
            
            logger.info(f"Eastmoney: fetched {len(result)} daily records for {symbol}")
            return result
        
        except Exception as e:
            logger.error(f"Eastmoney K-line fetch error for {symbol}: {e}")
            return []

    # ==================== Market Scanning ====================
    
    def enrich_stock_data(self, stock: dict) -> dict:
        """Enrich stock data with K-line indicators and fundamentals from database."""
        symbol = stock.get('symbol', '')
        if not symbol:
            return stock
        
        try:
            # Get latest K-line data with indicators
            row = self._db.fetch_all(
                '''SELECT ma5, ma10, ma20, ma60, rsi14, volume 
                   FROM kline_daily WHERE symbol=? ORDER BY trade_date DESC LIMIT 2''',
                (symbol,)
            )

            if len(row) >= 1:
                latest = row[0]
                stock['ma5'] = latest['ma5']
                stock['ma10'] = latest['ma10']
                stock['ma20'] = latest['ma20']
                stock['ma60'] = latest['ma60']
                stock['rsi14'] = latest['rsi14']

            if len(row) >= 2:
                prev = row[1]
                stock['ma5_prev'] = prev['ma5']
                stock['ma20_prev'] = prev['ma20']

            # Get latest financial indicators
            fi = self._db.fetch_one(
                '''SELECT roe, eps, profit_growth, revenue_growth, debt_ratio, net_margin
                   FROM financial_indicators WHERE symbol=? ORDER BY report_date DESC LIMIT 1''',
                (symbol,)
            )

            if fi:
                stock['roe'] = fi['roe']
                stock['eps'] = fi['eps']
                stock['profit_growth'] = fi['profit_growth']
                stock['revenue_growth'] = fi['revenue_growth']
                stock['debt_ratio'] = fi['debt_ratio']
                stock['net_margin'] = fi['net_margin']

            # Get latest capital flow
            cf = self._db.fetch_one(
                '''SELECT main_net_inflow, super_large_net_inflow FROM capital_flow 
                   WHERE symbol=? ORDER BY trade_date DESC LIMIT 1''',
                (symbol,)
            )

            if cf:
                stock['main_net_inflow'] = cf['main_net_inflow'] / 10000 if cf['main_net_inflow'] else None
                stock['super_large_net_inflow'] = cf['super_large_net_inflow'] / 10000 if cf['super_large_net_inflow'] else None

            # 量比：当前成交量 / 30日均量
            avg_vol = self._db.fetch_one(
                '''SELECT AVG(volume) AS avg_volume FROM (
                     SELECT volume FROM kline_daily WHERE symbol=? 
                     ORDER BY trade_date DESC LIMIT 30
                   )''',
                (symbol,)
            )
            current_vol = stock.get('volume')
            if avg_vol and avg_vol['avg_volume'] and current_vol:
                stock['volume_ratio'] = round(current_vol / avg_vol['avg_volume'], 2)
        except Exception as e:
            logger.debug(f"Enrich failed for {symbol}: {e}")
        
        return stock

    def scan_market_concurrent(self, strategy: dict, batch_size: int = 30) -> List[dict]:
        """Full market scan using ThreadPoolExecutor for concurrent fetching."""
        from services.strategy_service import StrategyService
        
        strategy_svc = StrategyService(
            stock_service=self,
            strategies_file=getattr(self.config, 'STRATEGIES_FILE', 'strategies.json')
        )
        matches = []
        symbols = self._market.get_stock_pool()
        
        def scan_batch(batch):
            stocks = self.fetch_tencent_data(batch)
            batch_matches = []
            for stock in stocks:
                stock['chg'] = round(stock.get('price', 0) - stock.get('prev_close', 0), 2)
                stock['chg_pct'] = round((stock['chg'] / stock.get('prev_close', 1)) * 100, 2) if stock.get('prev_close') else 0
                stock['volume_surge'] = 0
                # Enrich with K-line indicators and fundamentals
                stock = self.enrich_stock_data(stock)
                if strategy_svc.evaluate_strategy(strategy, stock):
                    batch_matches.append(stock)
            return batch_matches
        
        with ThreadPoolExecutor(max_workers=self._max_workers) as executor:
            futures = []
            for i in range(0, len(symbols), batch_size):
                batch = symbols[i:i + batch_size]
                futures.append(executor.submit(scan_batch, batch))
            
            for future in as_completed(futures):
                try:
                    matches.extend(future.result())
                except Exception as e:
                    logger.error(f"Batch scan error: {e}", exc_info=True)
        
        logger.info(f"Concurrent scan complete: {len(matches)} matches from {len(symbols)} stocks")
        return matches
