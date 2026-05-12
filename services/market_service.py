"""
Market data service.
Handles full A-share market data loading, sector management, and stock pool.
"""

import json
import logging
import os
from typing import List, Optional, Dict
from db import DatabaseManager

logger = logging.getLogger(__name__)


class MarketDataService:
    def __init__(self, data_file: Optional[str] = None, db_target: Optional[str] = None):
        if data_file is None:
            data_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'stock_data_full.json')
        self._data_file = data_file
        self._db_target = db_target or os.getenv('POSTGRES_DSN') or os.getenv('PG_DSN') or os.getenv('DATABASE_URL') or os.getenv('DB_DSN') or os.getenv('STOCK_DB', os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'stock_data.db'))
        self._full_stock_data: List[dict] = []
        self._symbol_index: Dict[str, dict] = {}
        self._sectors_cache: Dict[str, List[dict]] = {}
        self.load_full_market_data()

    def load_full_market_data(self):
        if os.path.exists(self._data_file):
            try:
                with open(self._data_file, 'r') as f:
                    data = json.load(f)
                    self._full_stock_data = data.get('stocks', [])
                    self._sectors_cache.clear()
                    self._symbol_index.clear()
                    for stock in self._full_stock_data:
                        sym = stock.get('symbol', '')
                        if sym:
                            self._symbol_index[sym] = stock
                        sector = stock.get('sector', '其他')
                        self._sectors_cache.setdefault(sector, []).append(stock)
                    logger.info(f"Loaded {len(self._full_stock_data)} stocks, {len(self._sectors_cache)} market board sectors")
            except Exception as e:
                logger.error(f"Failed to load market data: {e}", exc_info=True)
                self._full_stock_data = []
                self._symbol_index = {}
                self._sectors_cache = {}
        else:
            logger.warning('Full market data file not found')
            self._full_stock_data = []
            self._sectors_cache = {}
        self._load_industry_sectors()

    def _load_industry_sectors(self):
        try:
            db = DatabaseManager(self._db_target)
            rows = db.fetch_all("SELECT symbol, industry FROM stock_industry WHERE industry != ''")
            name_lookup = {}
            for sym, info in self._symbol_index.items():
                bare = sym[2:] if sym.startswith(('sh', 'sz')) else sym
                name_lookup[bare] = info
                name_lookup[sym] = info
            industry_map = {}
            for row in rows:
                db_symbol = row['symbol']
                industry = row['industry']
                bare = db_symbol[2:] if db_symbol.startswith(('sh', 'sz')) else db_symbol
                info = name_lookup.get(bare) or name_lookup.get(db_symbol)
                stock = dict(info) if info else {'symbol': db_symbol, 'name': ''}
                industry_map.setdefault(industry, []).append(stock)
            for industry, stocks in industry_map.items():
                if stocks:
                    self._sectors_cache[industry] = stocks
            logger.info(f"Loaded {len(industry_map)} industry sectors from DB, total sectors now: {len(self._sectors_cache)}")
        except Exception as e:
            logger.error(f"Failed to load industry sectors: {e}", exc_info=True)

    def get_stock_by_symbol(self, symbol: str) -> Optional[dict]:
        return self._symbol_index.get(symbol)

    def get_sectors(self) -> List[str]:
        return sorted(self._sectors_cache.keys())

    def get_sector_stocks(self, sector_name: str) -> List[dict]:
        return self._sectors_cache.get(sector_name, [])

    @property
    def total_stocks(self) -> int:
        return len(self._full_stock_data)

    @property
    def total_sectors(self) -> int:
        return len(self._sectors_cache)

    def get_stock_pool(self) -> List[str]:
        if self._sectors_cache:
            all_symbols = set()
            for _, stocks in self._sectors_cache.items():
                for s in stocks:
                    sym = s['symbol']
                    if not sym.startswith('sh') and not sym.startswith('sz'):
                        sym = f'sh{sym}' if sym.startswith('6') else f'sz{sym}'
                    all_symbols.add(sym)
            symbols = list(all_symbols)
            logger.info(f"Loaded {len(symbols)} stocks from full market data for scanning")
            return symbols
        logger.warning('Falling back to default stock pool')
        return ['sz002149','sh601398','sh601939','sh601288','sh601988','sh600036','sz000858','sh600519','sz002304','sh600809','sz002415','sz300750','sz000002','sz000333','sh601318','sz000001','sh601688','sh601601','sz002594','sz002466','sz002460','sz000538','sh600276','sz300122','sz000625','sz002475','sz002714','sz300498']
