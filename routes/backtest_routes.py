"""
Backtest routes.
API endpoints for backtesting operations.
"""

import logging
from flask import Blueprint, jsonify, request

logger = logging.getLogger(__name__)


def create_backtest_routes(backtest_service):
    """Create and return the backtest routes blueprint."""
    
    bp = Blueprint('backtest_v1', __name__)
    
    # ===================== V1 API Routes =====================
    
    @bp.route('/api/v1/backtest/run', methods=['POST'])
    def api_backtest_run_v1():
        """Run a backtest."""
        try:
            config = request.get_json()
            is_valid, error = backtest_service.validate_config(config)
            if not is_valid:
                return jsonify({'success': False, 'error': error, 'version': 'v1'}), 400
            
            result = backtest_service.run_backtest(config)
            return jsonify({'success': True, 'result': result, 'version': 'v1'})
        except Exception as e:
            logger.error(f"Backtest run error: {e}")
            return jsonify({'success': False, 'error': 'Internal server error', 'version': 'v1'}), 500
    
    @bp.route('/api/v1/backtest/history', methods=['GET'])
    def api_backtest_history_v1():
        """Get backtest history."""
        try:
            limit = request.args.get('limit', 50, type=int)
            history = backtest_service.get_backtest_history(limit)
            return jsonify({'success': True, 'history': history, 'version': 'v1'})
        except Exception as e:
            return jsonify({'success': False, 'error': 'Internal server error', 'version': 'v1'}), 500
    
    # ===================== Legacy Routes (Backward Compatibility) =====================
    
    @bp.route('/api/backtest/run', methods=['POST'])
    def api_backtest_run():
        """Legacy: redirect to v1."""
        return api_backtest_run_v1()
    
    @bp.route('/api/backtest/history', methods=['GET'])
    def api_backtest_history():
        """Legacy: redirect to v1."""
        return api_backtest_history_v1()
    
    return bp
