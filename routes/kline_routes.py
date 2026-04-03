"""
K-line (Candlestick) routes.
API endpoints for K-line data fetching and technical indicators.
"""

import time
import logging
from flask import Blueprint, jsonify, request

logger = logging.getLogger(__name__)


def create_kline_routes(stock_service):
    """Create and return the K-line routes blueprint."""
    
    bp = Blueprint('kline_v1', __name__)
    
    def calculate_ma(prices, period):
        """Calculate Moving Average."""
        if len(prices) < period:
            return []
        ma = []
        for i in range(len(prices)):
            if i < period - 1:
                ma.append(None)
            else:
                ma.append(round(sum(prices[i-period+1:i+1]) / period, 2))
        return ma
    
    def calculate_rsi(prices, period=14):
        """Calculate RSI (Relative Strength Index)."""
        if len(prices) < period + 1:
            return []
        
        deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        gains = [d if d > 0 else 0 for d in deltas]
        losses = [-d if d < 0 else 0 for d in deltas]
        
        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period
        
        rsi = [None] * (period)
        
        for i in range(period, len(deltas)):
            if avg_loss == 0:
                rsi_val = 100
            else:
                rs = avg_gain / avg_loss
                rsi_val = round(100 - (100 / (1 + rs)), 2)
            rsi.append(rsi_val)
            
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        
        return rsi
    
    # ===================== V1 API Routes =====================
    
    @bp.route('/api/v1/kline/<symbol>', methods=['GET'])
    def api_kline_v1(symbol):
        """
        Get K-line data with technical indicators.
        Query params: ktype (day/week/month), count (number of periods)
        """
        from utils import normalize_symbol
        symbol = normalize_symbol(symbol)
        ktype = request.args.get('ktype', 'day')
        count = int(request.args.get('count', 60))
        
        kline = stock_service.fetch_kline_data(symbol, ktype, count)
        if not kline:
            return jsonify({'success': False, 'error': 'No data available', 'version': 'v1'}), 404
        
        # Calculate indicators
        closes = [k['close'] for k in kline]
        
        ma5 = calculate_ma(closes, 5)
        ma10 = calculate_ma(closes, 10)
        ma20 = calculate_ma(closes, 20)
        ma60 = calculate_ma(closes, 60)
        rsi = calculate_rsi(closes, 14)
        
        # Attach indicators to kline data
        for i, k in enumerate(kline):
            k['ma5'] = ma5[i] if i < len(ma5) else None
            k['ma10'] = ma10[i] if i < len(ma10) else None
            k['ma20'] = ma20[i] if i < len(ma20) else None
            k['ma60'] = ma60[i] if i < len(ma60) else None
            k['rsi'] = rsi[i] if i < len(rsi) else None
        
        # Latest indicator values
        latest = kline[-1] if kline else {}
        last_rsi = None
        for k in reversed(kline):
            if k.get('rsi') is not None:
                last_rsi = k.get('rsi')
                break
        
        indicators = {
            'ma5': latest.get('ma5'),
            'ma10': latest.get('ma10'),
            'ma20': latest.get('ma20'),
            'ma60': latest.get('ma60'),
            'rsi': last_rsi,
            'rsi_signal': '超买' if (last_rsi or 0) > 70 else ('超卖' if (last_rsi or 0) < 30 else '正常')
        }
        
        return jsonify({
            'success': True,
            'symbol': symbol,
            'ktype': ktype,
            'count': len(kline),
            'data': kline,
            'indicators': indicators,
            'version': 'v1'
        })
    
    @bp.route('/api/v1/kline/download', methods=['POST'])
    def api_kline_download_v1():
        """
        Download historical K-line data for a symbol.
        Body: {symbol, ktype, days}
        Supports up to 5+ years of data via Eastmoney API for periods > 640 days.
        """
        data = request.json or {}
        symbol = data.get('symbol', stock_service.config.STOCK_SYMBOL)
        ktype = data.get('ktype', 'day')
        days = data.get('days', 365)
        use_eastmoney = data.get('use_eastmoney', days > 640)
        
        from utils import normalize_symbol
        symbol = normalize_symbol(symbol)
        
        # For daily data and periods > 640, use Eastmoney API
        if ktype == 'day' and (use_eastmoney or days > 640):
            all_data = stock_service.fetch_kline_eastmoney(symbol, days=days)
        else:
            all_data = []
            remaining = days
            while remaining > 0:
                batch_size = min(remaining, 100)
                kline = stock_service.fetch_kline_data(symbol, ktype, batch_size, use_cache=False)
                if not kline:
                    break
                all_data.extend(kline)
                remaining -= batch_size
                time.sleep(0.3)
        
        # Calculate indicators and save
        if all_data:
            closes = [k['close'] for k in all_data]
            ma5 = calculate_ma(closes, 5)
            ma10 = calculate_ma(closes, 10)
            ma20 = calculate_ma(closes, 20)
            ma60 = calculate_ma(closes, 60)
            rsi = calculate_rsi(closes, 14)
            
            for i, k in enumerate(all_data):
                k['ma5'] = ma5[i] if i < len(ma5) else None
                k['ma10'] = ma10[i] if i < len(ma10) else None
                k['ma20'] = ma20[i] if i < len(ma20) else None
                k['ma60'] = ma60[i] if i < len(ma60) else None
                k['rsi'] = rsi[i] if i < len(rsi) else None
            
            # Save to database
            stock_service.save_kline_daily(symbol, all_data)
        
        # Trim to requested days
        if len(all_data) > days:
            all_data = all_data[-days:]
        
        return jsonify({
            'success': True,
            'symbol': symbol,
            'ktype': ktype,
            'count': len(all_data),
            'source': 'eastmoney' if (ktype == 'day' and (use_eastmoney or days > 640)) else 'tencent',
            'date_range': f"{all_data[0]['date']} ~ {all_data[-1]['date']}" if all_data else 'N/A',
            'message': f'Downloaded {len(all_data)} {ktype} records for {symbol}',
            'version': 'v1'
        })
    
    @bp.route('/api/v1/kline/download_all', methods=['POST'])
    def api_kline_download_all_v1():
        """
        Download historical K-line data for all watchlist stocks.
        Body: {days: 365, use_eastmoney: true}
        """
        data = request.json or {}
        days = data.get('days', 365)
        use_eastmoney = data.get('use_eastmoney', days > 640)
        
        # Get watchlist symbols
        watchlist = stock_service.get_watchlist()
        symbols = [w.symbol for w in watchlist] if watchlist else [stock_service.config.STOCK_SYMBOL]
        
        results = []
        for symbol in symbols:
            try:
                if days > 640 or use_eastmoney:
                    all_data = stock_service.fetch_kline_eastmoney(symbol, days=days)
                else:
                    all_data = []
                    remaining = days
                    while remaining > 0:
                        batch_size = min(remaining, 100)
                        kline = stock_service.fetch_kline_data(symbol, 'day', batch_size, use_cache=False)
                        if not kline:
                            break
                        all_data.extend(kline)
                        remaining -= batch_size
                        time.sleep(0.3)
                
                if len(all_data) > days:
                    all_data = all_data[-days:]
                
                if all_data:
                    closes = [k['close'] for k in all_data]
                    ma5 = calculate_ma(closes, 5)
                    ma10 = calculate_ma(closes, 10)
                    ma20 = calculate_ma(closes, 20)
                    ma60 = calculate_ma(closes, 60)
                    rsi = calculate_rsi(closes, 14)
                    
                    for i, k in enumerate(all_data):
                        k['ma5'] = ma5[i] if i < len(ma5) else None
                        k['ma10'] = ma10[i] if i < len(ma10) else None
                        k['ma20'] = ma20[i] if i < len(ma20) else None
                        k['ma60'] = ma60[i] if i < len(ma60) else None
                        k['rsi'] = rsi[i] if i < len(rsi) else None
                    
                    stock_service.save_kline_daily(symbol, all_data)
                    results.append({
                        'symbol': symbol,
                        'count': len(all_data),
                        'success': True,
                        'date_range': f"{all_data[0]['date']} ~ {all_data[-1]['date']}"
                    })
                else:
                    results.append({'symbol': symbol, 'count': 0, 'success': False})
            except Exception as e:
                results.append({'symbol': symbol, 'error': 'Internal server error', 'success': False})
        
        return jsonify({
            'success': True,
            'total_symbols': len(symbols),
            'days': days,
            'source': 'eastmoney' if use_eastmoney else 'tencent',
            'results': results,
            'message': f'Downloaded data for {len(symbols)} symbols',
            'version': 'v1'
        })
    
    @bp.route('/api/v1/kline/stored/<symbol>', methods=['GET'])
    def api_kline_stored_v1(symbol):
        """
        Get stored K-line data from database.
        Query params: limit (number of records, default 365)
        """
        from utils import normalize_symbol
        symbol = normalize_symbol(symbol)
        limit = int(request.args.get('limit', 365))
        
        kline = stock_service.load_kline_daily(symbol, limit)
        
        if not kline:
            return jsonify({'success': False, 'error': 'No stored data', 'version': 'v1'}), 404
        
        return jsonify({
            'success': True,
            'symbol': symbol,
            'count': len(kline),
            'data': kline,
            'version': 'v1'
        })
    
    # ===================== Legacy Routes (Backward Compatibility) =====================
    
    @bp.route('/api/kline/<symbol>', methods=['GET'])
    def api_kline(symbol):
        """Legacy: redirect to v1."""
        return api_kline_v1(symbol)
    
    @bp.route('/api/kline/download', methods=['POST'])
    def api_kline_download():
        """Legacy: redirect to v1."""
        return api_kline_download_v1()
    
    @bp.route('/api/kline/download_all', methods=['POST'])
    def api_kline_download_all():
        """Legacy: redirect to v1."""
        return api_kline_download_all_v1()
    
    @bp.route('/api/kline/stored/<symbol>', methods=['GET'])
    def api_kline_stored(symbol):
        """Legacy: redirect to v1."""
        return api_kline_stored_v1(symbol)
    
    return bp
