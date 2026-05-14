#!/usr/bin/env python3
"""Minimal PostgreSQL-only Flask app for stock-monitor-app-py."""

import logging
import os
import secrets
import time

from flask import Flask, jsonify
from flask_cors import CORS

logger = logging.getLogger(__name__)


def create_app(config=None):
    if config is None:
        from config import Config as DefaultConfig
        config = DefaultConfig
    elif isinstance(config, dict):
        from config import BaseConfig
        config = type('DynamicConfig', (BaseConfig,), config)

    config.setup_logging()
    issues = config.validate()
    for issue in issues:
        if issue.startswith('CRITICAL'):
            logger.error(issue)
        else:
            logger.warning(issue)

    app = Flask(__name__)
    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY') or getattr(config, 'SECRET_KEY', None) or secrets.token_hex(32)
    app.config['APP_CONFIG'] = config

    if config.CORS_ORIGINS == ['*']:
        CORS(app)
    else:
        CORS(app, origins=config.CORS_ORIGINS)

    services = _init_services(config)

    @app.after_request
    def add_security_headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        response.headers['X-XSS-Protection'] = '1; mode=block'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        return response

    @app.route('/')
    def index():
        return jsonify({
            'success': True,
            'service': 'stock-monitor-app-pg-core',
            'mode': 'postgres-runtime-only',
            'timestamp': int(time.time() * 1000),
        })

    @app.route('/api/v1/health', methods=['GET'])
    @app.route('/api/health', methods=['GET'])
    def health_check():
        return jsonify({
            'success': True,
            'status': 'healthy',
            'db_url': getattr(config, 'DB_URL', ''),
            'timestamp': int(time.time() * 1000),
        })

    @app.route('/api/v1/runtime', methods=['GET'])
    def runtime_info():
        return jsonify({
            'success': True,
            'runtime': 'postgresql-only',
            'services': sorted(services.keys()),
            'timestamp': int(time.time() * 1000),
        })

    logger.info('Minimal PostgreSQL-only app initialized')
    return app, services


def _init_services(config):
    from services.feishu_service import FeishuService

    services = {
        'feishu_service': FeishuService(
            app_id=getattr(config, 'FEISHU_APP_ID', ''),
            app_secret=getattr(config, 'FEISHU_APP_SECRET', ''),
            default_chat_id=getattr(config, 'FEISHU_DEFAULT_RECEIVER', ''),
        )
    }
    logger.info('Initialized minimal service set: %s', ', '.join(sorted(services.keys())))
    return services


if __name__ == '__main__':
    from config import Config

    app, _services = create_app(Config)
    logger.info('Starting minimal Stock Monitor App on http://0.0.0.0:%s', Config.PORT)
    app.run(host='0.0.0.0', port=Config.PORT, debug=Config.DEBUG)
