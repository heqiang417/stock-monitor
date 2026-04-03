"""
Shared utilities for Stock Monitor App.
"""

from datetime import datetime


def is_trading_time() -> bool:
    """Check if current time is within A-share trading hours.

    Trading: Mon-Fri, 9:30-11:30 and 13:00-15:00 (Beijing time).
    """
    now = datetime.now()
    if now.weekday() >= 5:
        return False
    total_mins = now.hour * 60 + now.minute
    return (570 <= total_mins <= 690) or (780 <= total_mins <= 900)


def normalize_symbol(symbol: str) -> str:
    """Normalize stock symbol to include exchange prefix (sz/sh).
    
    If the symbol already has a prefix (sz, sh, bj), returns as-is.
    Otherwise, adds 'sh' prefix for Shanghai (starts with 6) or 'sz' for Shenzhen.
    
    Examples:
        '002149' -> 'sz002149'
        '600000' -> 'sh600000'
        'sz002149' -> 'sz002149'
    """
    if not symbol:
        return symbol
    symbol = symbol.strip().lower()
    if symbol.startswith(('sz', 'sh', 'bj')):
        return symbol
    if symbol.isdigit():
        return f'sh{symbol}' if symbol.startswith('6') else f'sz{symbol}'
    return symbol
