"""
Strategy service.
Handles strategy evaluation, persistence, and scanning.
"""

import json
import os
import time
import logging
from typing import List, Dict, Optional, Any
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

from models.strategy import ComplexStrategy, CONDITION_TYPES, ACTION_TYPES
from models.alert import DEFAULT_COMPLEX_STRATEGIES

logger = logging.getLogger(__name__)


def _get_feishu_service():
    """Lazy import to avoid circular dependency."""
    try:
        from services.feishu_service import get_feishu_service as _get
        return _get()
    except ImportError:
        return None


class StrategyService:
    """Service for strategy operations."""
    
    def __init__(self, stock_service: Any, strategies_file: str = 'strategies.json'):
        self.stock_service = stock_service
        self.strategies_file = strategies_file
        self.complex_strategies = self.load_complex_strategies()
        
        # Simple strategies
        self.simple_strategies = {
            'price_up': {'enabled': True, 'value': 50.0, 'label': '价格突破上限'},
            'price_down': {'enabled': True, 'value': 45.0, 'label': '价格跌破下限'},
            'chg_pct_up': {'enabled': True, 'value': 5.0, 'label': '涨幅超过阈值'},
            'chg_pct_down': {'enabled': True, 'value': -5.0, 'label': '跌幅超过阈值'},
            'volume_surge': {'enabled': False, 'value': 150, 'label': '成交量放大(%)'},
            'resistance': {'enabled': False, 'value': 52.0, 'label': '阻力位提醒'},
            'support': {'enabled': False, 'value': 43.0, 'label': '支撑位提醒'},
            'target_price': {'enabled': False, 'value': 55.0, 'label': '目标价位'},
            'stop_loss': {'enabled': False, 'value': 42.0, 'label': '止损价位'}
        }
    
    def load_complex_strategies(self) -> List[dict]:
        """Load complex strategies from file, or use defaults."""
        try:
            if os.path.exists(self.strategies_file):
                with open(self.strategies_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if isinstance(data, list) and len(data) > 0:
                        logger.info(f"Loaded {len(data)} strategies from {self.strategies_file}")
                        return data
        except Exception as e:
            logger.error(f"Failed to load strategies: {e}")
        return DEFAULT_COMPLEX_STRATEGIES.copy()
    
    def save_complex_strategies(self, strategies: List[dict]) -> bool:
        """Save complex strategies to file."""
        try:
            with open(self.strategies_file, 'w', encoding='utf-8') as f:
                json.dump(strategies, f, ensure_ascii=False, indent=2)
            logger.info(f"Saved {len(strategies)} strategies to {self.strategies_file}")
            return True
        except Exception as e:
            logger.error(f"Failed to save strategies: {e}")
            return False
    
    def get_strategies(self) -> dict:
        """Get all strategies (simple + complex)."""
        return {
            'simple': self.simple_strategies,
            'complex': self.complex_strategies,
            'condition_types': CONDITION_TYPES,
            'action_types': ACTION_TYPES
        }
    
    def update_simple_strategy(self, strategy_id: str, updates: dict) -> bool:
        """Update a simple strategy."""
        if strategy_id in self.simple_strategies:
            self.simple_strategies[strategy_id].update(updates)
            return True
        return False
    
    def delete_simple_strategy(self, strategy_id: str) -> bool:
        """Delete a simple strategy."""
        if strategy_id in self.simple_strategies:
            del self.simple_strategies[strategy_id]
            return True
        return False
    
    def update_complex_strategy(self, strategy: dict) -> bool:
        """Add or update a complex strategy."""
        strategy_id = strategy.get('id')
        for i, s in enumerate(self.complex_strategies):
            if s['id'] == strategy_id:
                self.complex_strategies[i] = {**s, **strategy}
                self.save_complex_strategies(self.complex_strategies)
                return True
        # New strategy
        self.complex_strategies.append(strategy)
        self.save_complex_strategies(self.complex_strategies)
        return True
    
    def delete_complex_strategy(self, strategy_id: str) -> bool:
        """Delete a complex strategy."""
        self.complex_strategies = [s for s in self.complex_strategies if s['id'] != strategy_id]
        self.save_complex_strategies(self.complex_strategies)
        return True
    
    # Strategy evaluation
    
    def evaluate_condition(self, condition: dict, data: dict) -> bool:
        """Evaluate a single condition against stock data."""
        ctype = condition.get('type')
        operator = condition.get('operator')
        value = condition.get('value')
        
        data_value = None
        if ctype == 'price':
            data_value = data.get('price')
        elif ctype == 'change_pct':
            data_value = data.get('chg_pct')
        elif ctype == 'volume':
            data_value = data.get('volume')
        elif ctype == 'volume_surge':
            data_value = data.get('volume_surge', 0)
        elif ctype == 'high':
            data_value = data.get('high')
        elif ctype == 'low':
            data_value = data.get('low')
        elif ctype in ('ma5', 'ma10', 'ma20', 'ma60'):
            data_value = data.get(ctype)
        elif ctype == 'rsi14':
            data_value = data.get('rsi14')
        elif ctype == 'ma_cross':
            # MA交叉：需要当前和前一天的MA数据
            ma5_prev = data.get('ma5_prev')
            ma20_prev = data.get('ma20_prev')
            ma5_now = data.get('ma5')
            ma20_now = data.get('ma20')
            if None in (ma5_prev, ma20_prev, ma5_now, ma20_now):
                return False
            if operator == 'golden_cross':
                return ma5_prev <= ma20_prev and ma5_now > ma20_now
            elif operator == 'death_cross':
                return ma5_prev >= ma20_prev and ma5_now < ma20_now
            return False
        elif ctype == 'main_net_inflow':
            data_value = data.get('main_net_inflow')
        elif ctype == 'main_net_inflow_pct':
            data_value = data.get('main_net_inflow_pct')
        elif ctype == 'super_large_net_inflow':
            data_value = data.get('super_large_net_inflow')
        elif ctype == 'volume_ratio':
            data_value = data.get('volume_ratio')
        elif ctype == 'ma_arrangement':
            ma5 = data.get('ma5')
            ma10 = data.get('ma10')
            ma20 = data.get('ma20')
            ma60 = data.get('ma60')
            if None in (ma5, ma10, ma20, ma60):
                return False
            if operator == 'bullish':
                return ma5 > ma10 > ma20 > ma60
            elif operator == 'bearish':
                return ma5 < ma10 < ma20 < ma60
            return False
        elif ctype in ('roe', 'eps', 'profit_growth', 'revenue_growth', 'debt_ratio', 'net_margin'):
            data_value = data.get(ctype)
        elif ctype == 'time':
            now = datetime.now()
            current_time = f"{now.hour:02d}:{now.minute:02d}"
            if operator == 'between':
                return value[0] <= current_time <= value[1]
            elif operator == 'after':
                return current_time >= value
            elif operator == 'before':
                return current_time <= value
            return False
        elif ctype == 'day_of_week':
            day = datetime.now().weekday()
            if operator == 'in':
                return day in value
            elif operator == 'not_in':
                return day not in value
            return False
        
        if data_value is None:
            return False
        
        if operator == '>':
            return data_value > value
        elif operator == '>=':
            return data_value >= value
        elif operator == '<':
            return data_value < value
        elif operator == '<=':
            return data_value <= value
        elif operator == '==':
            return data_value == value
        elif operator == 'between':
            return value[0] <= data_value <= value[1]
        
        return False
    
    def evaluate_strategy(self, strategy: dict, data: dict) -> bool:
        """Evaluate a complete strategy against stock data."""
        if not strategy.get('enabled'):
            return False
        
        conditions = strategy.get('conditions', [])
        logic = strategy.get('logic', 'AND')
        
        results = [self.evaluate_condition(c, data) for c in conditions]
        
        if logic == 'AND':
            return all(results)
        elif logic == 'OR':
            return any(results)
        return False
    
    def check_all_strategies(self, data: dict) -> List[dict]:
        """Check all complex strategies against data."""
        triggered = []
        now = int(time.time() * 1000)
        
        for strategy in self.complex_strategies:
            if self.evaluate_strategy(strategy, data):
                # Avoid re-triggering within 5 minutes
                last = strategy.get('lastTriggered')
                if last and (now - last < 5 * 60 * 1000):
                    continue
                
                strategy['lastTriggered'] = now
                strategy['triggerCount'] = strategy.get('triggerCount', 0) + 1
                
                formatted_actions = []
                for action in strategy.get('actions', []):
                    formatted = dict(action)
                    formatted['formattedMessage'] = self.format_action(action, data)
                    formatted_actions.append(formatted)
                
                trigger_result = {
                    'strategy': strategy['name'],
                    'id': strategy['id'],
                    'actions': formatted_actions,
                    'data': {'price': data['price'], 'chg_pct': data['chg_pct']}
                }
                
                # Send Feishu notification if configured
                feishu_actions = [a for a in strategy.get('actions', []) if a.get('type') == 'notify_feishu']
                if feishu_actions:
                    self._send_feishu_notification(strategy, data)
                
                triggered.append(trigger_result)
        
        return triggered
    
    def _send_feishu_notification(self, strategy: dict, data: dict):
        """Send Feishu notification for triggered strategy."""
        try:
            feishu = _get_feishu_service()
            if not feishu:
                logger.warning("Feishu service not available, skipping notification")
                return
            
            stock = data.get('symbol', data.get('name', 'Unknown'))
            price = data.get('price', 0)
            chg_pct = data.get('chg_pct', 0)
            
            # Determine alert level from conditions
            level = 'medium'
            for cond in strategy.get('conditions', []):
                ctype = cond.get('type')
                if ctype == 'price' and abs(cond.get('value', 0)) > 50:
                    level = 'high'
                elif ctype == 'change_pct' and abs(cond.get('value', 0)) > 5:
                    level = 'high'
            
            # Build trigger condition string
            conditions = strategy.get('conditions', [])
            cond_parts = []
            for c in conditions:
                ctype = c.get('type')
                op = c.get('operator')
                val = c.get('value')
                if ctype == 'price':
                    cond_parts.append(f"价格 {op} ¥{val}")
                elif ctype == 'change_pct':
                    cond_parts.append(f"涨跌 {op} {val}%")
                elif ctype == 'volume':
                    cond_parts.append(f"成交量 {op} {val}")
                else:
                    cond_parts.append(f"{ctype} {op} {val}")
            trigger_condition = ' AND '.join(cond_parts) if cond_parts else '策略触发'
            
            # Send notification
            result = feishu.send_stock_alert(
                stock=stock,
                price=price,
                chg_pct=chg_pct,
                strategy_name=strategy.get('name', 'Unknown'),
                trigger_condition=trigger_condition,
                level=level
            )
            
            if result.get('success'):
                logger.info(f"Feishu notification sent for strategy '{strategy.get('name')}'")
            else:
                logger.warning(f"Feishu notification failed: {result.get('error', 'Unknown')}")
                
        except Exception as e:
            logger.error(f"Failed to send Feishu notification: {e}")
    
    def format_action(self, action: dict, data: dict) -> str:
        """Format action message with data placeholders."""
        msg = action.get('message', '')
        msg = msg.replace('{price}', str(data.get('price', 'N/A')))
        msg = msg.replace('{change_pct}', f"{data.get('chg_pct', 0):.2f}")
        msg = msg.replace('{volume_surge}', str(data.get('volume_surge', 'N/A')))
        msg = msg.replace('{high}', str(data.get('high', 'N/A')))
        msg = msg.replace('{low}', str(data.get('low', 'N/A')))
        return msg
    
    def scan_by_strategy(self, strategy: dict, stocks: List[dict]) -> List[dict]:
        """Scan stocks against a strategy."""
        # Force enabled for scanning
        strategy = dict(strategy)
        strategy['enabled'] = True
        
        matches = []
        for stock in stocks:
            # Add derived fields
            stock['chg'] = round(stock.get('price', 0) - stock.get('prev_close', 0), 2)
            stock['chg_pct'] = round((stock['chg'] / stock.get('prev_close', 1)) * 100, 2) if stock.get('prev_close') else 0
            stock['volume_surge'] = 0
            if self.evaluate_strategy(strategy, stock):
                matches.append(stock)
        return matches
    
    def quick_scan(self, scan_type: str) -> List[dict]:
        """Perform a quick scan with predefined strategies."""
        strategy_templates = {
            'price_breakout': {
                'logic': 'AND',
                'conditions': [
                    {'type': 'change_pct', 'operator': '>', 'value': 0},
                    {'type': 'change_pct', 'operator': '<', 'value': 8},
                    {'type': 'price', 'operator': '>', 'value': 5}
                ]
            },
            'volume_surge': {
                'logic': 'AND',
                'conditions': [
                    {'type': 'change_pct', 'operator': '>', 'value': 2},
                    {'type': 'volume_surge', 'operator': '>', 'value': 5}
                ]
            },
            'oversold': {
                'logic': 'AND',
                'conditions': [
                    {'type': 'change_pct', 'operator': '<', 'value': -3},
                    {'type': 'change_pct', 'operator': '>', 'value': -8}
                ]
            },
            'hot': {
                'logic': 'AND',
                'conditions': [
                    {'type': 'volume', 'operator': '>', 'value': 100000},
                    {'type': 'change_pct', 'operator': '>', 'value': 0}
                ]
            }
        }
        
        if scan_type not in strategy_templates:
            raise ValueError(f"Unknown scan type: {scan_type}")
        
        strategy = strategy_templates[scan_type]
        return self.stock_service.scan_market_concurrent(strategy)
    
    def market_scan(self, strategy: dict, batch_size: int = 30) -> List[dict]:
        """Full market scan."""
        return self.stock_service.scan_market_concurrent(strategy, batch_size)
    
    def scan_watchlist_by_strategy(self, strategy: dict) -> List[dict]:
        """Scan all watchlist stocks against a strategy."""
        watchlist = self.stock_service.get_watchlist()
        if not watchlist:
            return []
        symbols = [w.symbol for w in watchlist]
        stocks = self.stock_service.fetch_tencent_data(symbols)
        matches = []
        strategy = dict(strategy)
        strategy['enabled'] = True
        for stock in stocks:
            stock['chg'] = round(stock.get('price', 0) - stock.get('prev_close', 0), 2)
            stock['chg_pct'] = round((stock['chg'] / stock.get('prev_close', 1)) * 100, 2) if stock.get('prev_close') else 0
            stock['volume_surge'] = 0
            if self.evaluate_strategy(strategy, stock):
                matches.append(stock)
        return matches
