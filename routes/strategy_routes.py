"""
Strategy routes.
API endpoints for strategy management and scanning.
"""

import logging
from flask import Blueprint, jsonify, request

logger = logging.getLogger(__name__)


def create_strategy_routes(strategy_service, stock_service):
    """Create and return the strategy routes blueprint."""
    
    bp = Blueprint('strategy_v1', __name__)
    
    # ===================== V1 API Routes =====================
    
    @bp.route('/api/v1/strategies', methods=['GET'])
    def api_get_strategies_v1():
        """Get all strategies (simple + complex)."""
        strategies = strategy_service.get_strategies()
        return jsonify({
            'success': True,
            'strategies': strategies['simple'],
            'complex': strategies['complex'],
            'conditions': strategies['condition_types'],
            'actions': strategies['action_types'],
            'version': 'v1'
        })
    
    @bp.route('/api/v1/strategies', methods=['POST'])
    def api_update_strategies_v1():
        """Update simple strategies."""
        try:
            updates = request.get_json()
            for key, val in updates.items():
                strategy_service.update_simple_strategy(key, val)
            return jsonify({'success': True, 'strategies': strategy_service.simple_strategies, 'version': 'v1'})
        except Exception as e:
            return jsonify({'success': False, 'error': 'Internal server error', 'version': 'v1'}), 400
    
    @bp.route('/api/v1/strategies/<strategy_id>', methods=['PUT'])
    def api_update_strategy_v1(strategy_id):
        """Update a single strategy."""
        try:
            data = request.get_json()
            if strategy_id in strategy_service.simple_strategies:
                strategy_service.update_simple_strategy(strategy_id, data)
                return jsonify({'success': True, 'strategy': strategy_service.simple_strategies[strategy_id], 'version': 'v1'})
            return jsonify({'success': False, 'error': 'Strategy not found', 'version': 'v1'}), 404
        except Exception as e:
            return jsonify({'success': False, 'error': 'Internal server error', 'version': 'v1'}), 400
    
    @bp.route('/api/v1/strategies/<strategy_id>', methods=['DELETE'])
    def api_delete_strategy_v1(strategy_id):
        """Delete a strategy."""
        try:
            if strategy_service.delete_simple_strategy(strategy_id):
                return jsonify({'success': True, 'version': 'v1'})
            return jsonify({'success': False, 'error': 'Strategy not found', 'version': 'v1'}), 404
        except Exception as e:
            return jsonify({'success': False, 'error': 'Internal server error', 'version': 'v1'}), 400
    
    @bp.route('/api/v1/strategies/complex', methods=['GET'])
    def api_get_complex_strategies_v1():
        """Get complex strategies."""
        return jsonify({
            'success': True,
            'strategies': strategy_service.complex_strategies,
            'conditions': strategy_service.get_strategies()['condition_types'],
            'actions': strategy_service.get_strategies()['action_types'],
            'version': 'v1'
        })
    
    @bp.route('/api/v1/strategies/complex', methods=['POST'])
    def api_update_complex_strategy_v1():
        """Add or update a complex strategy."""
        try:
            strategy = request.get_json()
            strategy_service.update_complex_strategy(strategy)
            return jsonify({'success': True, 'strategies': strategy_service.complex_strategies, 'version': 'v1'})
        except Exception as e:
            return jsonify({'success': False, 'error': 'Internal server error', 'version': 'v1'}), 400
    
    @bp.route('/api/v1/strategies/complex', methods=['DELETE'])
    def api_delete_complex_strategy_v1():
        """Delete a complex strategy."""
        strategy_id = request.args.get('id')
        if not strategy_id:
            return jsonify({'success': False, 'error': 'Missing id', 'version': 'v1'}), 400
        
        strategy_service.delete_complex_strategy(strategy_id)
        return jsonify({'success': True, 'strategies': strategy_service.complex_strategies, 'version': 'v1'})
    
    @bp.route('/api/v1/scan', methods=['GET'])
    def api_scan_v1():
        """Quick scan endpoint."""
        scan_type = request.args.get('type', 'price_breakout')
        try:
            matches = strategy_service.quick_scan(scan_type)
            return jsonify({'success': True, 'count': len(matches), 'stocks': matches, 'version': 'v1'})
        except Exception as e:
            return jsonify({'success': False, 'error': 'Internal server error', 'version': 'v1'}), 500
    
    @bp.route('/api/v1/scan/custom', methods=['POST'])
    def api_scan_custom_v1():
        """Custom strategy scan."""
        try:
            strategy = request.get_json()
            matches = strategy_service.market_scan(strategy)
            return jsonify({'success': True, 'count': len(matches), 'stocks': matches, 'version': 'v1'})
        except Exception as e:
            return jsonify({'success': False, 'error': 'Internal server error', 'version': 'v1'}), 500
    
    # Note: /api/v1/market/scan is handled by stock_routes blueprint (concurrent scan)
    # This avoids the duplicate route conflict
    
    # ===================== Legacy Routes (Backward Compatibility) =====================
    
    @bp.route('/api/strategies', methods=['GET'])
    def api_get_strategies():
        """Legacy: redirect to v1."""
        return api_get_strategies_v1()
    
    @bp.route('/api/strategies', methods=['POST'])
    def api_update_strategies():
        """Legacy: redirect to v1."""
        return api_update_strategies_v1()
    
    @bp.route('/api/strategies/<strategy_id>', methods=['PUT'])
    def api_update_strategy(strategy_id):
        """Legacy: redirect to v1."""
        return api_update_strategy_v1(strategy_id)
    
    @bp.route('/api/strategies/<strategy_id>', methods=['DELETE'])
    def api_delete_strategy(strategy_id):
        """Legacy: redirect to v1."""
        return api_delete_strategy_v1(strategy_id)
    
    @bp.route('/api/strategies/complex', methods=['GET'])
    def api_get_complex_strategies():
        """Legacy: redirect to v1."""
        return api_get_complex_strategies_v1()
    
    @bp.route('/api/strategies/complex', methods=['POST'])
    def api_update_complex_strategy():
        """Legacy: redirect to v1."""
        return api_update_complex_strategy_v1()
    
    @bp.route('/api/strategies/complex', methods=['DELETE'])
    def api_delete_complex_strategy():
        """Legacy: redirect to v1."""
        return api_delete_complex_strategy_v1()
    
    @bp.route('/api/scan', methods=['GET'])
    def api_scan():
        """Legacy: redirect to v1."""
        return api_scan_v1()
    
    @bp.route('/api/scan/custom', methods=['POST'])
    def api_scan_custom():
        """Legacy: redirect to v1."""
        return api_scan_custom_v1()
    
    # Note: /api/market/scan legacy route is handled by stock_routes blueprint
    
    return bp
