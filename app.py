#!/usr/bin/env python3
"""
Stock Monitor Web App - Flask Application Factory
=================================================
Uses the app factory pattern for testability and clean architecture.
Background services extracted to services/background_service.py.
"""

import os
import sys
import time
import secrets
import logging

from flask import Flask, render_template, jsonify, request
from flask_cors import CORS
from flask_socketio import SocketIO

logger = logging.getLogger(__name__)


def create_app(config=None):
    """Create and configure the Flask application.
    
    Args:
        config: Configuration class or object. If None, uses default from config.py.
                Can also be a dict with configuration values.
    
    Returns:
        Tuple of (Flask app, SocketIO instance, BackgroundService instance)
    """
    # ---- Configuration ----
    if config is None:
        from config import Config as DefaultConfig
        config = DefaultConfig
    elif isinstance(config, dict):
        # Allow passing a dict of config values
        from config import BaseConfig
        config = type('DynamicConfig', (BaseConfig,), config)
    
    # Validate config
    issues = config.validate()
    for issue in issues:
        if issue.startswith('CRITICAL'):
            logger.error(issue)
        else:
            logger.warning(issue)
    
    # ---- Setup Logging ----
    config.setup_logging()
    
    logger.info("=" * 60)
    logger.info("Stock Monitor App - Factory Version Starting")
    logger.info("=" * 60)
    
    # ---- Create Flask App ----
    app = Flask(__name__)
    
    _secret_key = os.getenv('SECRET_KEY') or getattr(config, 'SECRET_KEY', None)
    if not _secret_key:
        _secret_key_file = os.path.join(os.path.dirname(__file__), '.secret_key')
        try:
            with open(_secret_key_file, 'r') as f:
                _secret_key = f.read().strip()
            if _secret_key:
                logger.warning("SECRET_KEY loaded from .secret_key file — prefer setting SECRET_KEY env var for production")
        except FileNotFoundError:
            pass
        if not _secret_key:
            _secret_key = secrets.token_hex(32)
            logger.warning("SECRET_KEY not set, using ephemeral random key (not persisted)")
    app.config['SECRET_KEY'] = _secret_key
    
    # Store config on app for access in routes
    app.config['APP_CONFIG'] = config
    
    # ---- CORS ----
    if config.CORS_ORIGINS == ['*']:
        CORS(app)
        logger.warning("CORS: allowing all origins - not recommended for production")
    else:
        CORS(app, origins=config.CORS_ORIGINS)
        logger.info(f"CORS: restricted to {config.CORS_ORIGINS}")
    
    # ---- Socket.IO ----
    socketio = SocketIO(
        app,
        cors_allowed_origins=config.CORS_ORIGINS,
        async_mode='eventlet',
        ping_timeout=60,
        ping_interval=25
    )
    
    # ---- API Key Authentication ----
    _register_auth_middleware(app, config)
    
    # ---- Initialize Services ----
    stock_service, strategy_service, feishu_service, backtest_service = _init_services(config)
    
    # ---- Initialize Background Service ----
    from services.background_service import BackgroundService
    bg_service = BackgroundService(
        stock_service=stock_service,
        strategy_service=strategy_service,
        feishu_service=feishu_service,
        config=config
    )
    bg_service.set_socketio(socketio)
    
    # ---- Register Blueprints ----
    _register_blueprints(app, stock_service, strategy_service, backtest_service)
    
    # ---- Error Handlers ----
    _register_error_handlers(app)
    
    # ---- Security Headers ----
    @app.after_request
    def add_security_headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        response.headers['X-XSS-Protection'] = '1; mode=block'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        return response
    
    # ---- Frontend Routes ----
    _register_frontend_routes(app)
    
    # ---- Health Check ----
    _register_health_check(app)
    
    # ---- WebSocket Handlers ----
    _register_websocket_handlers(socketio, bg_service, stock_service, config)
    
    logger.info("Application factory complete")
    
    return app, socketio, bg_service, {
        'stock_service': stock_service,
        'strategy_service': strategy_service,
        'feishu_service': feishu_service,
        'backtest_service': backtest_service,
    }


# ===================== Private Helpers =====================

def _register_auth_middleware(app, config):
    """Register API key authentication middleware with rate limiting."""
    import functools
    
    auth_enabled = os.getenv('AUTH_ENABLED', 'true').lower() != 'false'
    api_key = getattr(config, 'API_KEY', None) or os.getenv('API_KEY')
    
    if auth_enabled and not api_key:
        logger.warning(
            "⚠️  SECURITY: AUTH_ENABLED=true but API_KEY is not set! "
            "API endpoints are unprotected. Set API_KEY or use AUTH_ENABLED=false for development."
        )
    
    # Simple rate limiter: track requests per IP
    _rate_limit_window = 60  # 1 minute window
    _rate_limit_max = 200    # max requests per window
    _request_counts = {}
    _last_cleanup = 0
    _CLEANUP_INTERVAL = 300  # cleanup stale IPs every 5 minutes
    _MAX_TRACKED_IPS = 10000  # cap on tracked IPs
    
    @app.before_request
    def check_api_key():
        """Global API key check + rate limiting for API routes."""
        # Rate limiting
        if request.path.startswith('/api/'):
            now = time.time()
            ip = request.remote_addr or 'unknown'
            
            # Periodic cleanup of stale IP entries
            nonlocal _last_cleanup
            if now - _last_cleanup > _CLEANUP_INTERVAL:
                stale_ips = [k for k, v in _request_counts.items() if not v or (now - v[-1]) > _rate_limit_window]
                for k in stale_ips:
                    del _request_counts[k]
                _last_cleanup = now
                # Emergency eviction if still too many IPs
                if len(_request_counts) > _MAX_TRACKED_IPS:
                    sorted_ips = sorted(_request_counts.items(), key=lambda x: x[1][-1] if x[1] else 0)
                    for k, _ in sorted_ips[:len(sorted_ips) // 2]:
                        del _request_counts[k]
            
            # Clean old entries for this IP
            if ip not in _request_counts:
                _request_counts[ip] = []
            _request_counts[ip] = [t for t in _request_counts[ip] if now - t < _rate_limit_window]
            if len(_request_counts[ip]) >= _rate_limit_max:
                logger.warning(f"Rate limit exceeded for {ip}")
                return jsonify({'success': False, 'error': 'Rate limit exceeded'}), 429
            _request_counts[ip].append(now)
        
        if not auth_enabled:
            return None
        
        current_api_key = getattr(config, 'API_KEY', None) or os.getenv('API_KEY')
        if not current_api_key:
            return None
        
        path = request.path
        # Skip auth for frontend pages, health check, and static files
        if path == '/' or path.startswith('/static/'):
            return None
        if path in ('/api/v1/health', '/api/health'):
            return None
        if not path.startswith('/api/'):
            return None
        
        provided_key = None
        auth_header = request.headers.get('Authorization', '')
        if auth_header.startswith('Bearer '):
            provided_key = auth_header[7:]
        else:
            provided_key = request.headers.get('X-API-Key')
        if provided_key != current_api_key:
            return jsonify({'success': False, 'error': 'Unauthorized: invalid or missing API key'}), 401


def _init_services(config):
    """Initialize all service instances."""
    from services.stock_service import StockService
    from services.strategy_service import StrategyService
    from services.backtest_service import BacktestService
    from services.feishu_service import FeishuService
    
    logger.info("Initializing services...")
    
    stock_service = StockService(db_path=config.DB_PATH, config=config)
    stock_service.init_db()
    
    strategy_service = StrategyService(
        stock_service=stock_service,
        strategies_file=getattr(config, 'STRATEGIES_FILE', 'strategies.json')
    )
    
    feishu_service = FeishuService(
        app_id=getattr(config, 'FEISHU_APP_ID', ''),
        app_secret=getattr(config, 'FEISHU_APP_SECRET', ''),
        default_chat_id=getattr(config, 'FEISHU_DEFAULT_RECEIVER', '')
    )
    logger.info(f"Feishu service initialized (app_id={'set' if feishu_service.app_id else 'not set'})")
    
    backtest_service = BacktestService()
    
    logger.info("Services initialized successfully")
    return stock_service, strategy_service, feishu_service, backtest_service


def _register_blueprints(app, stock_service, strategy_service, backtest_service):
    """Register all route blueprints."""
    from routes.stock_routes import create_stock_routes
    from routes.strategy_routes import create_strategy_routes
    from routes.backtest_routes import create_backtest_routes
    from routes.alert_routes import create_alert_routes
    from routes.kline_routes import create_kline_routes
    from routes.fundamental_routes import create_fundamental_routes
    from routes.analysis_routes import create_analysis_routes
    from routes.dashboard_routes import create_dashboard_routes
    from routes.db_routes import create_db_routes
    
    logger.info("Registering route blueprints...")
    
    app.register_blueprint(create_stock_routes(stock_service, strategy_service))
    app.register_blueprint(create_strategy_routes(strategy_service, stock_service))
    app.register_blueprint(create_backtest_routes(backtest_service))
    app.register_blueprint(create_alert_routes(strategy_service, stock_service))
    app.register_blueprint(create_kline_routes(stock_service))
    app.register_blueprint(create_fundamental_routes(app.config.get('DB_PATH', 'data/stock_data.db')))
    app.register_blueprint(create_analysis_routes(app.config.get('DB_PATH', 'data/stock_data.db')))
    app.register_blueprint(create_dashboard_routes(app.config.get('DB_PATH', 'data/stock_data.db')))
    app.register_blueprint(create_db_routes(stock_service))
    
    # Legacy backtest blueprint
    try:
        from backtest.api import bp as legacy_backtest_bp
        app.register_blueprint(legacy_backtest_bp)
        logger.info("Legacy backtest API registered at /api/backtest/*")
    except ImportError as e:
        logger.warning(f"Legacy backtest module not available: {e}")
    
    logger.info("All blueprints registered successfully")


def _register_error_handlers(app):
    """Register structured error handlers."""
    
    @app.errorhandler(404)
    def not_found(e):
        return jsonify({
            'success': False,
            'error': 'Resource not found',
            'timestamp': int(time.time() * 1000)
        }), 404
    
    @app.errorhandler(405)
    def method_not_allowed(e):
        return jsonify({
            'success': False,
            'error': 'Method not allowed',
            'timestamp': int(time.time() * 1000)
        }), 405
    
    @app.errorhandler(500)
    def internal_error(e):
        logger.exception('Internal server error')
        return jsonify({
            'success': False,
            'error': 'Internal server error',
            'timestamp': int(time.time() * 1000)
        }), 500


def _register_frontend_routes(app):
    """Register HTML page routes."""
    
    @app.route('/')
    def index():
        return render_template('index.html')


def _register_health_check(app):
    """Register health check endpoints (minimal info, no auth required)."""
    
    @app.route('/api/v1/health', methods=['GET'])
    def health_check():
        return jsonify({
            'success': True,
            'status': 'healthy',
            'timestamp': int(time.time() * 1000)
        })
    
    @app.route('/api/health', methods=['GET'])
    def legacy_health_check():
        return health_check()


def _register_websocket_handlers(socketio, bg_service, stock_service, config):
    """Register WebSocket event handlers with authentication."""
    from utils import is_trading_time
    
    MAX_WS_CLIENTS = 100
    
    @socketio.on('connect')
    def handle_connect():
        # Check connection limit
        if bg_service.connected_clients_count >= MAX_WS_CLIENTS:
            logger.warning(f"WebSocket connection rejected: max clients ({MAX_WS_CLIENTS}) reached")
            return False
        
        # Authenticate if API key is configured
        api_key = getattr(config, 'API_KEY', None) or os.getenv('API_KEY')
        if api_key:
            provided_key = request.args.get('api_key') or request.headers.get('X-API-Key')
            auth_header = request.headers.get('Authorization', '')
            if auth_header.startswith('Bearer '):
                provided_key = auth_header[7:]
            if provided_key != api_key:
                logger.warning(f"WebSocket connection rejected: invalid API key from {request.sid}")
                return False
        
        bg_service.add_client(request.sid)
        socketio.emit('market_status', {
            'trading': is_trading_time(),
            'connected_clients': bg_service.connected_clients_count,
            'timestamp': int(time.time() * 1000)
        }, room=request.sid)
    
    @socketio.on('disconnect')
    def handle_disconnect():
        bg_service.remove_client(request.sid)
    
    @socketio.on('subscribe_price')
    def handle_subscribe_price(data):
        symbols = data.get('symbols', [])
        if isinstance(symbols, str):
            symbols = [symbols]
        logger.info(f"Client {request.sid} subscribed to price updates: {symbols}")
        socketio.emit('subscription_confirmed', {'symbols': symbols}, room=request.sid)
    
    @socketio.on('unsubscribe_price')
    def handle_unsubscribe_price(data):
        symbols = data.get('symbols', [])
        logger.info(f"Client {request.sid} unsubscribed from price updates: {symbols}")
        socketio.emit('unsubscription_confirmed', {'symbols': symbols}, room=request.sid)
    
    @socketio.on('ping')
    def handle_ping():
        socketio.emit('pong', {'timestamp': int(time.time() * 1000)}, room=request.sid)


# ===================== Main Entry Point =====================

if __name__ == '__main__':
    from config import Config
    
    app, socketio, bg_service, services = create_app(Config)
    
    logger.info(f"Starting Stock Monitor App on http://0.0.0.0:{Config.PORT}")
    logger.info(f"Configuration: DB={Config.DB_PATH}, Symbol={Config.STOCK_SYMBOL}")
    logger.info(f"Log Level: {Config.LOG_LEVEL}, Workers: {Config.MAX_WORKERS}")
    
    # Start background threads via BackgroundService
    bg_service.start()
    
    # Run Flask-SocketIO
    logger.info("Starting Flask-SocketIO server with WebSocket support...")
    try:
        socketio.run(
            app,
            host='0.0.0.0',
            port=Config.PORT,
            debug=Config.DEBUG,
            use_reloader=False,
            log_output=True
        )
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received, shutting down...")
    finally:
        bg_service.stop()
        logger.info("Application shutdown complete")
