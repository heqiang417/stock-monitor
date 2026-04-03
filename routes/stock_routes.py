"""
Stock routes.
API endpoints for stock data, market data, watchlist, and K-line operations.
"""

import json
import os
import time
import logging
from datetime import datetime
from flask import Blueprint, jsonify, request, Response
import pandas as pd

logger = logging.getLogger(__name__)


def create_stock_routes(stock_service, strategy_service):
    """Create and return the stock routes blueprint."""
    
    bp = Blueprint('stock_v1', __name__)
    
    # In-memory history for SSE
    from collections import deque
    from utils import is_trading_time
    import threading as _threading
    history = deque(maxlen=100)
    stock_cache = {}
    
    # Stale-while-revalidate cache for market indexes
    _indexes_cache = {'data': None, 'ts': 0, 'refreshing': False}
    _INDEXES_CACHE_TTL = 10  # seconds before considered stale
    _INDEXES_LOCK = _threading.Lock()
    
    def _refresh_indexes_bg():
        """Background thread to refresh indexes cache."""
        with _INDEXES_LOCK:
            if _indexes_cache['refreshing']:
                return
            _indexes_cache['refreshing'] = True
        try:
            indexes = stock_service.fetch_indexes()
            data = [i.to_dict() for i in indexes]
            with _INDEXES_LOCK:
                _indexes_cache['data'] = data
                _indexes_cache['ts'] = time.time()
        except Exception as e:
            logger.error(f"Background indexes refresh failed: {e}")
        finally:
            with _INDEXES_LOCK:
                _indexes_cache['refreshing'] = False
    
    # Use a mutable container for last_volume so inner functions can modify it
    class _State:
        last_volume = 0
    
    state = _State()
    
    def fetch_main_stock():
        """Fetch and process main stock data."""
        from utils import normalize_symbol
        
        stocks = stock_service.fetch_tencent_data([stock_service.config.STOCK_SYMBOL])
        if not stocks:
            raise Exception("Failed to fetch stock data")
        
        data = stocks[0]
        data['chg'] = round(data['price'] - data['prev_close'], 2)
        data['chg_pct'] = round((data['chg'] / data['prev_close']) * 100, 2) if data['prev_close'] else 0
        data['volume_surge'] = round(
            ((data['volume'] - state.last_volume) / state.last_volume * 100), 2
        ) if state.last_volume > 0 else 0
        
        # Check simple strategies
        data['alerts'] = []
        data['strategy_hits'] = []
        for sid, s in strategy_service.simple_strategies.items():
            if not s['enabled']:
                continue
            if sid == 'price_up' and data['price'] >= s['value']:
                data['alerts'].append(f"价格突破 ¥{s['value']}！当前 ¥{data['price']}")
                data['strategy_hits'].append(sid)
            elif sid == 'price_down' and data['price'] <= s['value']:
                data['alerts'].append(f"价格跌破 ¥{s['value']}！当前 ¥{data['price']}")
                data['strategy_hits'].append(sid)
            elif sid == 'chg_pct_up' and data['chg_pct'] >= s['value']:
                data['alerts'].append(f"涨幅超过 {s['value']}%！当前 {data['chg_pct']}%")
                data['strategy_hits'].append(sid)
            elif sid == 'chg_pct_down' and data['chg_pct'] <= s['value']:
                data['alerts'].append(f"跌幅超过 {s['value']}%！当前 {data['chg_pct']}%")
                data['strategy_hits'].append(sid)
            elif sid == 'volume_surge' and state.last_volume > 0:
                vol_change = ((data['volume'] - state.last_volume) / state.last_volume) * 100
                if vol_change >= s['value']:
                    data['alerts'].append(f"成交量放大 {vol_change:.0f}%！")
                    data['strategy_hits'].append(sid)
        
        # Check complex strategies
        complex_triggers = strategy_service.check_all_strategies(data)
        for trigger in complex_triggers:
            for action in trigger.get('actions', []):
                msg = action.get('formattedMessage') or f"{trigger['strategy']} 触发！"
                data['alerts'].append(msg)
            data['strategy_hits'].append(trigger['id'])
        
        data['complex_triggers'] = complex_triggers
        
        # Update last volume
        state.last_volume = data['volume']
        
        # Store in history
        history.append({
            'time': data['timestamp'],
            'price': data['price'],
            'chg_pct': data['chg_pct']
        })
        
        # Store in SQLite database
        try:
            stock_service.insert_stock_history(data)
        except Exception as e:
            logger.error(f"Database insert failed: {e}")
        
        # Cache the result
        nonlocal stock_cache
        stock_cache = data
        stock_cache['history'] = list(history)
        
        return data
    
    # ===================== Dashboard Aggregation API =====================
    
    @bp.route('/api/v1/dashboard', methods=['GET'])
    def api_dashboard_v1():
        """
        Aggregation API: returns all dashboard data in a single request.
        Combines: market_indexes, watchlist, realtime_quote, strategies, market_status.
        """
        import threading as _threading
        from utils import is_trading_time
        
        result = {
            'success': True,
            'market_indexes': [],
            'watchlist': [],
            'watchlist_top': [],
            'realtime_quote': {},
            'strategies': [],
            'market_status': {},
            'timestamp': int(time.time() * 1000),
            'version': 'v1'
        }
        
        # 1. Market indexes + watchlist + default stock - batch into ONE Tencent API call
        index_codes = ['sh000001', 'sz399001', 'sz399006', 'sh000300', 'sh000905']
        default_symbol = 'sz002149'
        
        # Get watchlist from DB (no API call needed)
        watchlist_items = stock_service.get_watchlist()
        watchlist_symbols = [w.symbol for w in watchlist_items]
        
        # Merge all symbols into one batch request
        all_symbols = list(dict.fromkeys(index_codes + watchlist_symbols + [default_symbol]))
        
        try:
            all_quotes = stock_service.fetch_tencent_data(all_symbols)
        except Exception:
            all_quotes = []
        
        quote_map = {q['symbol']: q for q in all_quotes}
        
        # Populate market indexes
        for code in index_codes:
            q = quote_map.get(code)
            if q:
                result['market_indexes'].append({
                    'symbol': q['symbol'],
                    'name': q['name'],
                    'price': q.get('price', 0),
                    'chg': q.get('chg', 0),
                    'chg_pct': q.get('chg_pct', 0),
                    'volume': q.get('volume', 0),
                    'amount': q.get('amount', 0)
                })
        
        # Populate watchlist with live prices
        for w in watchlist_items:
            q = quote_map.get(w.symbol)
            if q:
                w.price = q.get('price', 0)
                chg = round(q.get('price', 0) - q.get('prev_close', 0), 2)
                w.chg = chg
                w.chg_pct = round((chg / q.get('prev_close', 1)) * 100, 2) if q.get('prev_close') else 0
            result['watchlist'].append(w.to_dict())
        
        # watchlist_top: first 7
        result['watchlist_top'] = result['watchlist'][:7]
        
        # Default stock realtime quote (002149)
        dq = quote_map.get(default_symbol)
        if dq:
            dq['chg'] = round(dq.get('price', 0) - dq.get('prev_close', 0), 2)
            dq['chg_pct'] = round((dq['chg'] / dq.get('prev_close', 1)) * 100, 2) if dq.get('prev_close') else 0
            result['realtime_quote'] = dq
        
        # 2. Strategies - no API call needed
        try:
            strat_data = strategy_service.get_strategies()
            complex_list = strat_data.get('complex', [])
            enabled_strategies = []
            for s in complex_list:
                if s.get('enabled'):
                    enabled_strategies.append({
                        'id': s.get('id'),
                        'name': s.get('name'),
                        'enabled': True,
                        'trigger_count': s.get('triggerCount', 0),
                        'logic': s.get('logic', 'AND')
                    })
            result['strategies'] = enabled_strategies
        except Exception:
            result['strategies'] = []
        
        # 3. Market status - no API call needed
        result['market_status'] = {
            'trading': is_trading_time(),
            'timestamp': result['timestamp']
        }
        
        return jsonify(result)
    
    # ===================== V1 API Routes =====================
    
    @bp.route('/api/v1/stock', methods=['GET'])
    def api_stock_v1():
        """Get main stock (002149) real-time data."""
        try:
            data = fetch_main_stock()
            return jsonify({
                'success': True,
                'data': data,
                'history': list(history)[-50:],
                'trading': is_trading_time(),
                'version': 'v1'
            })
        except Exception as e:
            logger.error(f"Stock API error: {e}")
            return jsonify({'success': False, 'error': 'Internal server error', 'version': 'v1'}), 500
    
    @bp.route('/api/v1/history', methods=['GET'])
    def api_history_v1():
        """Get price history from database."""
        limit = request.args.get('limit', 100, type=int)
        try:
            db_history = stock_service.get_stock_history(limit)
            return jsonify({'success': True, 'history': db_history, 'source': 'database', 'version': 'v1'})
        except Exception as e:
            logger.error(f"Database query failed, using in-memory: {e}")
            return jsonify({'success': True, 'history': list(history), 'source': 'memory', 'version': 'v1'})
    
    @bp.route('/api/v1/watchlist', methods=['GET'])
    def api_get_watchlist_v1():
        """Get all stocks in watchlist."""
        try:
            watchlist = stock_service.get_watchlist()
            symbols = [w.symbol for w in watchlist]
            if symbols:
                quotes = stock_service.fetch_tencent_data(symbols)
                quote_map = {q['symbol']: q for q in quotes}
                for w in watchlist:
                    if w.symbol in quote_map:
                        q = quote_map[w.symbol]
                        w.price = q.get('price', 0)
                        w.chg = round(q.get('price', 0) - q.get('prev_close', 0), 2)
                        w.chg_pct = round((w.chg / q.get('prev_close', 1)) * 100, 2) if q.get('prev_close') else 0
            return jsonify({'success': True, 'watchlist': [w.to_dict() for w in watchlist], 'version': 'v1'})
        except Exception as e:
            return jsonify({'success': False, 'error': 'Internal server error', 'version': 'v1'}), 500
    
    @bp.route('/api/v1/watchlist', methods=['POST'])
    def api_add_watchlist_v1():
        """Add a stock to watchlist."""
        try:
            from utils import normalize_symbol
            data = request.get_json()
            symbol = data.get('symbol', '').strip().lower()
            name = data.get('name', '').strip()
            if not symbol:
                return jsonify({'success': False, 'error': 'Symbol required', 'version': 'v1'}), 400
            symbol = normalize_symbol(symbol)
            stock_service.add_to_watchlist(symbol, name)
            return jsonify({'success': True, 'symbol': symbol, 'version': 'v1'})
        except Exception as e:
            return jsonify({'success': False, 'error': 'Internal server error', 'version': 'v1'}), 500
    
    @bp.route('/api/v1/watchlist', methods=['DELETE'])
    def api_remove_watchlist_v1():
        """Remove a stock from watchlist."""
        try:
            symbol = request.args.get('symbol', '').strip().lower()
            if not symbol:
                return jsonify({'success': False, 'error': 'Symbol required', 'version': 'v1'}), 400
            stock_service.remove_from_watchlist(symbol)
            return jsonify({'success': True, 'symbol': symbol, 'version': 'v1'})
        except Exception as e:
            return jsonify({'success': False, 'error': 'Internal server error', 'version': 'v1'}), 500
    
    @bp.route('/api/v1/watchlist/scan', methods=['POST'])
    def api_watchlist_scan_v1():
        """Scan all watchlist stocks against a strategy."""
        try:
            strategy = request.get_json()
            matches = strategy_service.scan_watchlist_by_strategy(strategy)
            return jsonify({'success': True, 'count': len(matches), 'stocks': matches, 'version': 'v1'})
        except Exception as e:
            return jsonify({'success': False, 'error': 'Internal server error', 'version': 'v1'}), 500

    @bp.route('/api/v1/market/scan', methods=['POST'])
    def api_market_scan_v1():
        """
        Full market scan using concurrent ThreadPoolExecutor.
        Request body: {"strategy": {...}, "batch_size": 30}
        Returns: matched stocks with strategy signals.
        """
        try:
            req_data = request.get_json() or {}
            strategy = req_data.get('strategy', {})
            batch_size = req_data.get('batch_size', 30)
            
            if not strategy:
                return jsonify({'success': False, 'error': 'Strategy required', 'version': 'v1'}), 400
            
            logger.info(f"Starting concurrent market scan with strategy: {strategy.get('name', 'unnamed')}")
            matches = stock_service.scan_market_concurrent(strategy, batch_size)
            
            return jsonify({
                'success': True,
                'count': len(matches),
                'matches': matches,
                'scan_mode': 'concurrent',
                'max_workers': stock_service._max_workers,
                'batch_size': batch_size,
                'version': 'v1'
            })
        except Exception as e:
            logger.error(f"Market scan error: {e}")
            return jsonify({'success': False, 'error': 'Internal server error', 'version': 'v1'}), 500
    
    @bp.route('/api/v1/sectors', methods=['GET'])
    def api_sectors_v1():
        """Get all sectors with stock counts."""
        market = stock_service._market
        if not market._sectors_cache:
            market.load_full_market_data()
        sectors = []
        for name, stocks in market._sectors_cache.items():
            sectors.append({
                'name': name,
                'count': len(stocks),
                'sample': stocks[:5] if stocks else []
            })
        return jsonify({'success': True, 'total_stocks': len(market._full_stock_data), 'sectors': sectors, 'version': 'v1'})
    
    @bp.route('/api/v1/sectors/<sector_name>', methods=['GET'])
    def api_sector_stocks_v1(sector_name):
        """Get stocks in a specific sector with real-time quotes, paginated."""
        from utils import normalize_symbol
        market = stock_service._market
        if not market._sectors_cache:
            market.load_full_market_data()
        stocks = market._sectors_cache.get(sector_name, [])
        if not stocks:
            return jsonify({'success': False, 'error': 'Sector not found', 'version': 'v1'}), 404
        
        page = int(request.args.get('page', 1))
        page_size = min(int(request.args.get('pageSize', 30)), 100)
        total = len(stocks)
        total_pages = max(1, (total + page_size - 1) // page_size)
        page = max(1, min(page, total_pages))
        
        start = (page - 1) * page_size
        end = min(start + page_size, total)
        page_stocks = stocks[start:end]
        
        symbols = [normalize_symbol(s['symbol']) for s in page_stocks]
        quotes_map = {}
        for i in range(0, len(symbols), 60):
            batch = symbols[i:i+60]
            quotes = stock_service.fetch_tencent_data(batch)
            for q in quotes:
                quotes_map[q['symbol']] = q
        
        result = []
        for s in page_stocks:
            sym = s['symbol']
            lookup_sym = normalize_symbol(sym)
            q = quotes_map.get(lookup_sym, {})
            chg = q.get('chg', 0)
            chg_pct = q.get('chg_pct', 0)
            result.append({
                'symbol': sym,
                'name': s.get('name', ''),
                'sector': sector_name,
                'price': q.get('price', s.get('price', 0)),
                'chg': round(chg, 2) if chg else 0,
                'chg_pct': round(chg_pct, 2) if chg_pct else 0,
                'volume': q.get('volume', 0),
                'amount': q.get('amount', 0),
                'high': q.get('high', 0),
                'low': q.get('low', 0),
                'open': q.get('open', 0),
                'prev_close': q.get('prev_close', 0),
            })
        
        return jsonify({
            'success': True,
            'sector': sector_name,
            'count': len(result),
            'stocks': result,
            'pagination': {
                'page': page,
                'pageSize': page_size,
                'total': total,
                'totalPages': total_pages,
                'hasNext': page < total_pages,
                'hasPrev': page > 1
            },
            'version': 'v1'
        })
    
    @bp.route('/api/v1/stock/<symbol>', methods=['GET'])
    def api_stock_detail_v1(symbol):
        """Get detailed info for a single stock."""
        from utils import normalize_symbol
        symbol = normalize_symbol(symbol)
        
        quotes = stock_service.fetch_tencent_data([symbol])
        if not quotes:
            return jsonify({'success': False, 'error': 'Stock not found', 'version': 'v1'}), 404
        
        data = quotes[0]
        data['chg'] = round(data.get('price', 0) - data.get('prev_close', 0), 2)
        data['chg_pct'] = round((data['chg'] / data.get('prev_close', 1)) * 100, 2) if data.get('prev_close') else 0
        
        try:
            stock_history = stock_service.get_stock_history(50)
        except Exception as e:
            logger.warning(f"Failed to get stock history: {e}")
            stock_history = []
        
        # Get industry data
        industry_info = {}
        try:
            row = stock_service._db.fetch_one(
                'SELECT industry, industry_code FROM stock_industry WHERE symbol = ?', (symbol,))
            if row:
                industry_info = {'industry': row['industry'], 'industry_code': row['industry_code']}
        except Exception as e:
            logger.warning(f"Failed to get industry for {symbol}: {e}")
        
        # Get latest fundamental data
        fundamentals = []
        try:
            rows = stock_service._db.fetch_all(
                '''SELECT symbol, report_date, eps, roe, revenue_growth, profit_growth,
                          gross_margin, net_margin, debt_ratio, current_ratio, total_assets
                   FROM financial_indicators WHERE symbol = ?
                   ORDER BY report_date DESC LIMIT 8''', (symbol,))
            if rows:
                fundamentals = [dict(r) for r in rows]
        except Exception as e:
            logger.warning(f"Failed to get fundamentals for {symbol}: {e}")
        
        return jsonify({
            'success': True, 'data': data, 'history': stock_history,
            'industry': industry_info, 'fundamentals': fundamentals,
            'trading': is_trading_time(), 'version': 'v1'
        })
    
    @bp.route('/api/v1/market/indexes', methods=['GET'])
    def api_market_indexes_v1():
        """Get major market indexes (stale-while-revalidate)."""
        try:
            # Return stale cache immediately if available
            now = time.time()
            with _INDEXES_LOCK:
                cached_data = _indexes_cache['data']
                cache_age = now - _indexes_cache['ts']
                is_fresh = cache_age < _INDEXES_CACHE_TTL
            
            if cached_data is not None:
                # Return cached data immediately (even if stale)
                # Trigger background refresh if stale
                if not is_fresh and not _indexes_cache['refreshing']:
                    _threading.Thread(target=_refresh_indexes_bg, daemon=True).start()
                return jsonify({'success': True, 'indexes': cached_data, 'version': 'v1', 'cached': True})
            
            # No cache yet - fetch synchronously (first request)
            indexes = stock_service.fetch_indexes()
            data = [i.to_dict() for i in indexes]
            with _INDEXES_LOCK:
                _indexes_cache['data'] = data
                _indexes_cache['ts'] = time.time()
            return jsonify({'success': True, 'indexes': data, 'version': 'v1'})
        except Exception as e:
            return jsonify({'success': False, 'error': 'Internal server error', 'version': 'v1'}), 500
    
    @bp.route('/api/v1/stream')
    def stream_v1():
        """Server-Sent Events endpoint for real-time updates."""
        from flask import current_app
        # SSE token verification (EventSource API cannot set custom headers)
        app_config = current_app.config.get('APP_CONFIG')
        api_key = getattr(app_config, 'API_KEY', None) if app_config else None
        api_key = api_key or os.getenv('API_KEY')
        auth_enabled = os.getenv('AUTH_ENABLED', 'true').lower() != 'false'
        if auth_enabled and api_key:
            token = request.args.get('token')
            if token != api_key:
                return jsonify({'success': False, 'error': 'Unauthorized: invalid or missing token'}), 401
        
        def generate():
            while True:
                try:
                    data = fetch_main_stock()
                    yield f"data: {json.dumps(data)}\n\n"
                except Exception as e:
                    yield f"data: {json.dumps({'error': 'Internal server error'})}\n\n"
                time.sleep(5)
        
        return Response(generate(), mimetype='text/event-stream')
    
    @bp.route('/api/v1/search', methods=['GET'])
    def api_search_v1():
        """Search stocks by code or name from multiple data sources."""
        try:
            query = request.args.get('q', '').strip()
            if not query:
                return jsonify({'success': True, 'results': []})
            
            like = f'%{query}%'
            prefix = f'{query}%'
            
            # Search across multiple tables and merge results
            all_results = {}
            
            # 1. watchlist (highest priority)
            try:
                rows = stock_service._db.fetch_all(
                    'SELECT symbol, name FROM watchlist WHERE symbol LIKE ? OR name LIKE ?',
                    (like, like)
                )
                for r in rows:
                    key = r['symbol']
                    if key not in all_results:
                        all_results[key] = {'symbol': r['symbol'], 'name': r['name'] or '', 'score': 0}
            except Exception:
                pass
            
            # 2. limit_up_down (recent stocks)
            try:
                rows = stock_service._db.fetch_all(
                    'SELECT DISTINCT code as symbol, name FROM limit_up_down WHERE code LIKE ? OR name LIKE ? LIMIT 20',
                    (like, like)
                )
                for r in rows:
                    key = r['symbol']
                    if key not in all_results:
                        all_results[key] = {'symbol': r['symbol'], 'name': r['name'] or '', 'score': 1}
            except Exception:
                pass
            
            # 3. block_trades
            try:
                rows = stock_service._db.fetch_all(
                    'SELECT DISTINCT code as symbol, name FROM block_trades WHERE code LIKE ? OR name LIKE ? LIMIT 20',
                    (like, like)
                )
                for r in rows:
                    key = r['symbol']
                    if key not in all_results:
                        all_results[key] = {'symbol': r['symbol'], 'name': r['name'] or '', 'score': 2}
            except Exception:
                pass
            
            # 4. lhb_detail (龙虎榜)
            try:
                rows = stock_service._db.fetch_all(
                    'SELECT DISTINCT code as symbol, name FROM lhb_detail WHERE code LIKE ? OR name LIKE ? LIMIT 20',
                    (like, like)
                )
                for r in rows:
                    key = r['symbol']
                    if key not in all_results:
                        all_results[key] = {'symbol': r['symbol'], 'name': r['name'] or '', 'score': 3}
            except Exception:
                pass
            
            # 5. stock_industry (all symbols, no names though)
            try:
                rows = stock_service._db.fetch_all(
                    'SELECT DISTINCT symbol FROM stock_industry WHERE symbol LIKE ? LIMIT 20',
                    (like,)
                )
                for r in rows:
                    key = r['symbol']
                    if key not in all_results:
                        all_results[key] = {'symbol': r['symbol'], 'name': '', 'score': 4}
            except Exception:
                pass
            
            # Sort: exact match first, then prefix, then contains
            results = list(all_results.values())
            results.sort(key=lambda x: (
                x['score'],
                0 if x['symbol'] == query else (1 if x['symbol'].startswith(query) else 2)
            ))
            
            return jsonify({'success': True, 'results': results[:30]})
        except Exception as e:
            logger.error(f"Search error: {e}")
            return jsonify({'success': False, 'error': 'Internal server error'}), 500
    
    # ===================== 涨跌停 =====================

    @bp.route('/api/v1/limit-up', methods=['GET'])
    def api_limit_up_v1():
        """Get today's limit-up stocks via akshare."""
        try:
            import akshare as ak
            date_str = request.args.get('date', datetime.now().strftime('%Y%m%d'))
            df = ak.stock_zt_pool_em(date=date_str)
            if df is None or df.empty:
                return jsonify({'success': True, 'date': date_str, 'up': [], 'down': []})
            stocks = []
            for _, row in df.iterrows():
                stocks.append({
                    'code': str(row.get('代码', '')),
                    'name': str(row.get('名称', '')),
                    'chg_pct': float(row.get('涨跌幅', 0)) if pd.notna(row.get('涨跌幅')) else 0,
                    'price': float(row.get('最新价', 0)) if pd.notna(row.get('最新价')) else 0,
                    'amount': float(row.get('成交额', 0)) if pd.notna(row.get('成交额')) else 0,
                    'seal_amount': float(row.get('封板资金', 0)) if pd.notna(row.get('封板资金')) else 0,
                    'first_seal_time': str(row.get('首次封板时间', '')),
                    'break_count': int(row.get('炸板次数', 0)) if pd.notna(row.get('炸板次数')) else 0,
                    'consecutive': int(row.get('连板数', 1)) if pd.notna(row.get('连板数')) else 1,
                    'industry': str(row.get('所属行业', '')),
                })
            return jsonify({'success': True, 'date': date_str, 'up': stocks, 'down': []})
        except Exception as e:
            logger.error(f"Limit-up fetch error: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500

    @bp.route('/api/v1/limit-down', methods=['GET'])
    def api_limit_down_v1():
        """Get today's limit-down stocks via akshare."""
        try:
            import akshare as ak
            date_str = request.args.get('date', datetime.now().strftime('%Y%m%d'))
            df = ak.stock_zt_pool_dtgc_em(date=date_str)
            if df is None or df.empty:
                return jsonify({'success': True, 'date': date_str, 'down': []})
            stocks = []
            for _, row in df.iterrows():
                stocks.append({
                    'code': str(row.get('代码', '')),
                    'name': str(row.get('名称', '')),
                    'chg_pct': float(row.get('涨跌幅', 0)) if pd.notna(row.get('涨跌幅')) else 0,
                    'price': float(row.get('最新价', 0)) if pd.notna(row.get('最新价')) else 0,
                    'amount': float(row.get('成交额', 0)) if pd.notna(row.get('成交额')) else 0,
                    'industry': str(row.get('所属行业', '')),
                })
            return jsonify({'success': True, 'date': date_str, 'down': stocks})
        except Exception as e:
            logger.error(f"Limit-down fetch error: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500

    # ===================== Legacy Routes (Backward Compatibility) =====================
    
    @bp.route('/api/search', methods=['GET'])
    def api_search():
        """Legacy: redirect to v1."""
        return api_search_v1()
    
    @bp.route('/api/market/scan', methods=['POST'])
    def api_market_scan():
        """Legacy: redirect to v1."""
        return api_market_scan_v1()

    @bp.route('/api/stock', methods=['GET'])
    def api_stock():
        """Legacy: redirect to v1."""
        return api_stock_v1()
    
    @bp.route('/api/history', methods=['GET'])
    def api_history():
        """Legacy: redirect to v1."""
        return api_history_v1()
    
    @bp.route('/api/watchlist', methods=['GET'])
    def api_get_watchlist():
        """Legacy: redirect to v1."""
        return api_get_watchlist_v1()
    
    @bp.route('/api/watchlist', methods=['POST'])
    def api_add_watchlist():
        """Legacy: redirect to v1."""
        return api_add_watchlist_v1()
    
    @bp.route('/api/watchlist', methods=['DELETE'])
    def api_remove_watchlist():
        """Legacy: redirect to v1."""
        return api_remove_watchlist_v1()
    
    @bp.route('/api/watchlist/scan', methods=['POST'])
    def api_watchlist_scan():
        """Legacy: redirect to v1."""
        return api_watchlist_scan_v1()
    
    @bp.route('/api/sectors', methods=['GET'])
    def api_sectors():
        """Legacy: redirect to v1."""
        return api_sectors_v1()
    
    @bp.route('/api/sectors/<sector_name>', methods=['GET'])
    def api_sector_stocks(sector_name):
        """Legacy: redirect to v1."""
        return api_sector_stocks_v1(sector_name)
    
    @bp.route('/api/stock/<symbol>', methods=['GET'])
    def api_stock_detail(symbol):
        """Legacy: redirect to v1."""
        return api_stock_detail_v1(symbol)
    
    @bp.route('/api/market/indexes', methods=['GET'])
    def api_market_indexes():
        """Legacy: redirect to v1."""
        return api_market_indexes_v1()
    
    @bp.route('/api/stream')
    def stream():
        """Legacy: redirect to v1."""
        return stream_v1()
    
    return bp
