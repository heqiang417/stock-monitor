"""
Background service for Stock Monitor App.
Handles periodic data fetching, strategy checking, alert sending,
and WebSocket price pushing in managed background threads.
"""

import time
import logging
import threading
from collections import deque
from typing import Set, Dict, Any, Optional, List
from concurrent.futures import ThreadPoolExecutor

from db import DatabaseManager

logger = logging.getLogger(__name__)


class BackgroundService:
    """Manages background threads for data fetching, alert checking, and WebSocket pushing.
    
    Features:
    - Periodic stock data fetching during trading hours
    - Strategy evaluation and alert triggering
    - Feishu notification with cooldown
    - WebSocket price pushing to connected clients
    - K-line data collection
    - Daily data cleanup
    - Graceful start/stop lifecycle
    """
    
    def __init__(self, stock_service, strategy_service, feishu_service, config):
        self.stock_service = stock_service
        self.strategy_service = strategy_service
        self.feishu_service = feishu_service
        self.config = config
        
        self._db = DatabaseManager(config.DB_PATH)
        self._stop_event = threading.Event()
        self._threads: List[threading.Thread] = []
        
        # WebSocket state
        self._connected_clients: Set[str] = set()
        self._socketio = None
        
        # Alert cooldown tracking
        self._feishu_cooldown: Dict[str, float] = {}
        self._last_kline_fetch: Dict[str, float] = {}
        self._last_cleanup = 0.0
        self._last_volume = 0
        
        # History for volume surge calculation
        self._history = deque(maxlen=100)
        
        # Initialize alert tables on startup
        self._init_alert_tables()
    
    def set_socketio(self, socketio):
        """Set the SocketIO instance for WebSocket broadcasting."""
        self._socketio = socketio
    
    # ===================== Client Tracking =====================
    
    def add_client(self, sid: str):
        """Register a connected WebSocket client."""
        self._connected_clients.add(sid)
        logger.info(f"WebSocket client connected: {sid} (total: {len(self._connected_clients)})")
    
    def remove_client(self, sid: str):
        """Unregister a disconnected WebSocket client."""
        self._connected_clients.discard(sid)
        logger.info(f"WebSocket client disconnected: {sid} (total: {len(self._connected_clients)})")
    
    @property
    def connected_clients_count(self) -> int:
        return len(self._connected_clients)
    
    # ===================== Database Init =====================
    
    def _init_alert_tables(self):
        """Create alert tables at startup instead of on every insert."""
        try:
            with self._db.get_connection() as conn:
                c = conn.cursor()
                c.execute('''CREATE TABLE IF NOT EXISTS alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp INTEGER NOT NULL,
                    strategy_id TEXT,
                    message TEXT,
                    level TEXT DEFAULT 'info',
                    stock TEXT,
                    trigger_condition TEXT,
                    price REAL,
                    is_read INTEGER DEFAULT 0,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )''')
                c.execute('CREATE INDEX IF NOT EXISTS idx_alerts_ts ON alerts(timestamp)')
                c.execute('CREATE INDEX IF NOT EXISTS idx_alerts_level_read ON alerts(level, is_read)')
                c.execute('''CREATE TABLE IF NOT EXISTS alert_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp INTEGER NOT NULL,
                    stock TEXT,
                    price REAL,
                    chg_pct REAL,
                    strategy_id TEXT,
                    strategy_name TEXT,
                    trigger_condition TEXT,
                    message TEXT,
                    level TEXT DEFAULT 'info',
                    feishu_sent INTEGER DEFAULT 0,
                    is_read INTEGER DEFAULT 0,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )''')
                c.execute('CREATE INDEX IF NOT EXISTS idx_alert_history_stock_ts ON alert_history(stock, timestamp)')
                c.execute('CREATE INDEX IF NOT EXISTS idx_alert_history_level_read ON alert_history(level, is_read)')
            logger.info("Alert tables initialized")
        except Exception as e:
            logger.error(f"Failed to init alert tables: {e}", exc_info=True)
    
    # ===================== WebSocket Broadcasting =====================
    
    def broadcast_price_update(self, symbols=None, data=None):
        """Broadcast price updates to all connected clients."""
        if not self._connected_clients or not self._socketio:
            return
        payload = {
            'symbols': symbols or [],
            'data': data or {},
            'timestamp': int(time.time() * 1000)
        }
        self._socketio.emit('price_update', payload)
    
    def broadcast_alert(self, alert_data: dict):
        """Broadcast alert notification to all connected clients."""
        if not self._connected_clients or not self._socketio:
            return
        self._socketio.emit('alert', {
            'type': alert_data.get('type', 'info'),
            'message': alert_data.get('message', ''),
            'level': alert_data.get('level', 'info'),
            'symbol': alert_data.get('symbol', ''),
            'strategy': alert_data.get('strategy', ''),
            'timestamp': int(time.time() * 1000)
        })
    
    def broadcast_market_status(self):
        """Broadcast current market status to all connected clients."""
        if not self._connected_clients or not self._socketio:
            return
        from utils import is_trading_time
        self._socketio.emit('market_status', {
            'trading': is_trading_time(),
            'connected_clients': len(self._connected_clients),
            'timestamp': int(time.time() * 1000)
        })
    
    # ===================== WebSocket Price Pusher =====================
    
    def websocket_price_pusher(self):
        """Background thread that pushes real-time prices via WebSocket every 3 seconds."""
        logger.info("WebSocket price pusher thread started")
        while not self._stop_event.is_set():
            if self._connected_clients:
                try:
                    watchlist = self.stock_service.get_watchlist()
                    symbols = [w.symbol for w in watchlist] if watchlist else [self.config.STOCK_SYMBOL]
                    if self.config.STOCK_SYMBOL not in symbols:
                        symbols.insert(0, self.config.STOCK_SYMBOL)
                    
                    quotes = self.stock_service.fetch_tencent_data(symbols)
                    quote_map = {q['symbol']: q for q in quotes}
                    
                    price_data = {}
                    for sym in symbols:
                        q = quote_map.get(sym)
                        if q:
                            price_data[sym] = {
                                'symbol': sym,
                                'name': q.get('name', sym),
                                'price': q.get('price', 0),
                                'prev_close': q.get('prev_close', 0),
                                'chg': round(q.get('price', 0) - q.get('prev_close', 0), 2),
                                'chg_pct': q.get('chg_pct', 0),
                                'volume': q.get('volume', 0),
                                'high': q.get('high', 0),
                                'low': q.get('low', 0),
                                'bid1_price': q.get('bid1_price', 0),
                                'ask1_price': q.get('ask1_price', 0)
                            }
                    
                    if price_data:
                        self.broadcast_price_update(symbols=symbols, data=price_data)
                        logger.debug(f"Pushed price update for {len(price_data)} stocks to {len(self._connected_clients)} clients")
                
                except Exception as e:
                    logger.error(f"Price pusher error: {e}", exc_info=True)
            
            # Wait 3 seconds, but check stop event every 0.5s for responsiveness
            self._stop_event.wait(timeout=3)
        
        logger.info("WebSocket price pusher thread stopped")
    
    def push_strategy_alert(self, strategy: dict, triggered_data: dict):
        """Push a strategy alert via WebSocket."""
        alert_payload = {
            'type': 'strategy_alert',
            'message': f"策略 '{strategy.get('name', 'Unknown')}' 已触发",
            'level': 'high',
            'symbol': triggered_data.get('symbol', self.config.STOCK_SYMBOL),
            'strategy': strategy.get('id', ''),
            'data': {
                'price': triggered_data.get('price'),
                'chg_pct': triggered_data.get('chg_pct'),
                'conditions': strategy.get('conditions', [])
            }
        }
        self.broadcast_alert(alert_payload)
        logger.info(f"WebSocket alert broadcast: {alert_payload['message']}")
    
    # ===================== Background Fetcher =====================
    
    def _insert_alert_db(self, strategy_id: str, message: str, level: str = 'info'):
        """Insert alert into database."""
        try:
            with self._db.get_connection() as conn:
                c = conn.cursor()
                # Lazy init: create table if it doesn't exist
                c.execute('''CREATE TABLE IF NOT EXISTS alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp INTEGER NOT NULL, strategy_id TEXT, message TEXT,
                    level TEXT DEFAULT 'info', stock TEXT, trigger_condition TEXT,
                    price REAL, is_read INTEGER DEFAULT 0,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP)''')
                c.execute('''INSERT INTO alerts (timestamp, strategy_id, message, level, stock, trigger_condition, price)
                    VALUES (?, ?, ?, ?, ?, ?, ?)''',
                    (int(time.time() * 1000), strategy_id, message, level,
                      self.config.STOCK_SYMBOL, message, 0))
        except Exception as e:
            logger.error(f"Failed to insert alert: {e}", exc_info=True)
    
    def _send_feishu_notification(self, message: str, alert_level: str = 'info',
                                  stock: str = '', price: float = 0, chg_pct: float = 0,
                                  strategy_name: str = '', trigger_condition: str = ''):
        """Send notification to Feishu and record in alert history."""
        try:
            result = self.feishu_service.send_stock_alert(
                stock=stock or self.config.STOCK_SYMBOL,
                price=price,
                chg_pct=chg_pct,
                strategy_name=strategy_name or 'Strategy Alert',
                trigger_condition=trigger_condition or message,
                level=alert_level
            )
            
            # Record in alert history
            try:
                with self._db.get_connection() as conn:
                    c = conn.cursor()
                    c.execute('''INSERT INTO alert_history 
                        (timestamp, stock, price, chg_pct, strategy_id, strategy_name, 
                         trigger_condition, message, level, feishu_sent)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                        (int(time.time() * 1000),
                         stock or self.config.STOCK_SYMBOL,
                         price, chg_pct, '',
                         strategy_name or '', trigger_condition or '',
                         message, alert_level,
                         1 if result.get('success') else 0))
            except Exception as e:
                logger.error(f"Failed to record alert history: {e}", exc_info=True)
            
            if result.get('success'):
                logger.info(f"Feishu notification sent: {message}")
            else:
                logger.warning(f"Feishu notification queued/failed: {result.get('error', 'Unknown')}")
            
            return result.get('success', False)
        except Exception as e:
            logger.error(f"Feishu notification error: {e}", exc_info=True)
            return False
    
    def _check_multi_level_alert(self, symbol: str, data: dict, alert_config: dict) -> List[dict]:
        """Check multi-level alerts for a stock."""
        triggers = []
        price = data.get('price', 0)
        chg_pct = data.get('chg_pct', 0)
        
        for level in alert_config.get('price_levels', []):
            threshold = level.get('value', 0)
            direction = level.get('direction', 'above')
            alert_level = level.get('level', 'medium')
            
            if direction == 'above' and price > threshold:
                triggers.append({
                    'type': 'price', 'symbol': symbol,
                    'message': f'🔔 {symbol} 价格 ¥{price} 突破 ¥{threshold}',
                    'level': alert_level, 'value': price, 'threshold': threshold
                })
            elif direction == 'below' and price < threshold:
                triggers.append({
                    'type': 'price', 'symbol': symbol,
                    'message': f'⚠️ {symbol} 价格 ¥{price} 跌破 ¥{threshold}',
                    'level': alert_level, 'value': price, 'threshold': threshold
                })
        
        for level in alert_config.get('chg_pct_levels', []):
            threshold = level.get('value', 0)
            direction = level.get('direction', 'above')
            alert_level = level.get('level', 'medium')
            
            if direction == 'above' and chg_pct > threshold:
                triggers.append({
                    'type': 'chg_pct', 'symbol': symbol,
                    'message': f'📈 {symbol} 涨幅 {chg_pct:.2f}% 超过 {threshold}%',
                    'level': alert_level, 'value': chg_pct, 'threshold': threshold
                })
            elif direction == 'below' and chg_pct < threshold:
                triggers.append({
                    'type': 'chg_pct', 'symbol': symbol,
                    'message': f'📉 {symbol} 跌幅 {abs(chg_pct):.2f}% 超过 {abs(threshold)}%',
                    'level': alert_level, 'value': chg_pct, 'threshold': threshold
                })
        
        return triggers
    
    def background_fetch(self):
        """Background thread for periodic data fetching during trading hours."""
        logger.info("Background fetcher thread started")
        from utils import is_trading_time
        
        while not self._stop_event.is_set():
            if is_trading_time():
                try:
                    stocks = self.stock_service.fetch_tencent_data([self.config.STOCK_SYMBOL])
                    if stocks:
                        data = stocks[0]
                        data['chg'] = round(data['price'] - data['prev_close'], 2)
                        data['chg_pct'] = round((data['chg'] / data['prev_close']) * 100, 2) if data['prev_close'] else 0
                        data['volume_surge'] = round(
                            ((data['volume'] - self._last_volume) / self._last_volume * 100), 2
                        ) if self._last_volume > 0 else 0
                        
                        self._history.append({
                            'time': data['timestamp'],
                            'price': data['price'],
                            'chg_pct': data['chg_pct']
                        })
                        
                        logger.info(f"Background: {self.config.STOCK_SYMBOL} = ¥{data['price']} ({data['chg_pct']}%)")
                        
                        # Store in database
                        try:
                            self.stock_service.insert_stock_history(data)
                        except Exception as e:
                            logger.error(f"Database insert failed: {e}", exc_info=True)
                        
                        # Check multi-level alerts
                        for strategy in self.strategy_service.complex_strategies:
                            if not strategy.get('enabled'):
                                continue
                            
                            alert_config = {'price_levels': [], 'chg_pct_levels': [], 'volume_levels': []}
                            for cond in strategy.get('conditions', []):
                                if cond['type'] == 'price':
                                    alert_config['price_levels'].append({
                                        'value': cond['value'],
                                        'direction': '>=' if cond['operator'] in ['>=', '>'] else '<=',
                                        'level': 'high'
                                    })
                                elif cond['type'] == 'change_pct':
                                    alert_config['chg_pct_levels'].append({
                                        'value': cond['value'],
                                        'direction': '>=' if cond['operator'] in ['>=', '>'] else '<=',
                                        'level': 'medium'
                                    })
                            
                            triggers = self._check_multi_level_alert(self.config.STOCK_SYMBOL, data, alert_config)
                            
                            for trigger in triggers:
                                alert_key = f"{trigger['type']}_{trigger['threshold']}"
                                now = time.time()
                                if alert_key in self._feishu_cooldown and now - self._feishu_cooldown[alert_key] < 300:
                                    continue
                                
                                self._feishu_cooldown[alert_key] = now
                                self._send_feishu_notification(
                                    message=trigger['message'],
                                    alert_level=trigger['level'],
                                    stock=trigger.get('symbol', self.config.STOCK_SYMBOL),
                                    price=trigger.get('value', data.get('price', 0)),
                                    chg_pct=data.get('chg_pct', 0),
                                    strategy_name=strategy.get('name', 'Unknown'),
                                    trigger_condition=trigger['message']
                                )
                                self._insert_alert_db(strategy['id'], trigger['message'], trigger['level'])
                                logger.info(f"Alert triggered: {trigger['message']}")
                                self.push_strategy_alert(strategy, {
                                    'symbol': trigger.get('symbol', self.config.STOCK_SYMBOL),
                                    'price': trigger.get('value'),
                                    'chg_pct': trigger.get('value') if trigger.get('type') == 'chg_pct' else None
                                })
                        
                        # Collect K-line data every 30 minutes
                        now = time.time()
                        try:
                            watchlist = self.stock_service.get_watchlist()
                            symbols = [w.symbol for w in watchlist] if watchlist else [self.config.STOCK_SYMBOL]
                        except Exception:
                            symbols = [self.config.STOCK_SYMBOL]
                        
                        for sym in symbols:
                            last_fetch = self._last_kline_fetch.get(sym, 0)
                            if now - last_fetch > 1800:
                                try:
                                    kline = self.stock_service.fetch_kline_data(sym, 'day', 5, use_cache=False)
                                    if kline:
                                        self.stock_service.save_kline_daily(sym, kline)
                                        self._last_kline_fetch[sym] = now
                                        logger.info(f"K-line collected for {sym}: {len(kline)} days")
                                except Exception as e:
                                    logger.error(f"K-line collection error for {sym}: {e}", exc_info=True)
                        
                        self._last_volume = data['volume']
                
                except Exception as e:
                    logger.error(f"Background fetch error: {e}", exc_info=True)
            
            # Daily cleanup
            now = time.time()
            if now - self._last_cleanup > 86400:
                try:
                    self.stock_service.cleanup_old_data(days=self.config.CLEANUP_DAYS)
                    self._last_cleanup = now
                except Exception as e:
                    logger.error(f"Cleanup error: {e}", exc_info=True)
            
            # Wait for interval or stop
            self._stop_event.wait(timeout=self.config.FETCH_INTERVAL)
        
        logger.info("Background fetcher thread stopped")
    
    # ===================== Thread Lifecycle =====================
    
    def start(self):
        """Start all background threads."""
        if self._threads:
            logger.warning("Background threads already running, ignoring start()")
            return
        
        self._stop_event.clear()
        
        # Start background fetcher
        fetcher = threading.Thread(target=self.background_fetch, daemon=True, name="bg-fetcher")
        fetcher.start()
        self._threads.append(fetcher)
        
        # Start WebSocket price pusher
        pusher = threading.Thread(target=self.websocket_price_pusher, daemon=True, name="ws-pusher")
        pusher.start()
        self._threads.append(pusher)
        
        logger.info(f"Started {len(self._threads)} background threads")
    
    def stop(self, timeout: float = 5.0):
        """Gracefully stop all background threads."""
        logger.info("Stopping background threads...")
        self._stop_event.set()
        
        for thread in self._threads:
            thread.join(timeout=timeout)
            if thread.is_alive():
                logger.warning(f"Thread {thread.name} did not stop within {timeout}s")
        
        self._threads.clear()
        logger.info("All background threads stopped")
