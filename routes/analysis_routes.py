"""
Strategy analysis API routes.
Exposes walk-forward results, strategy comparisons, and financial deep data.
"""
import json
import os
import logging
from flask import Blueprint, jsonify, request

logger = logging.getLogger(__name__)


def create_analysis_routes(db_path: str):
    """Create analysis blueprint with walk-forward and strategy data."""
    bp = Blueprint('analysis', __name__)
    
    # Resolve data paths relative to project root
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    @bp.route('/api/v1/analysis/walkforward', methods=['GET'])
    def get_walkforward_results():
        """Get walk-forward strategy ranking results."""
        try:
            wf_path = os.path.join(project_root, 'walkforward_results.json')
            if not os.path.exists(wf_path):
                return jsonify({'success': False, 'error': 'Walk-forward results not found'}), 404
            with open(wf_path, 'r') as f:
                data = json.load(f)
            return jsonify({'success': True, 'data': data})
        except Exception as e:
            logger.error(f"Walk-forward load error: {e}", exc_info=True)
            return jsonify({'success': False, 'error': 'Internal server error'}), 500
    
    @bp.route('/api/v1/analysis/walkforward/report', methods=['GET'])
    def get_walkforward_report():
        """Get walk-forward report as markdown."""
        try:
            report_path = os.path.join(project_root, 'walkforward_report.md')
            if not os.path.exists(report_path):
                return jsonify({'success': False, 'error': 'Report not found'}), 404
            with open(report_path, 'r') as f:
                content = f.read()
            return jsonify({'success': True, 'report': content})
        except Exception as e:
            return jsonify({'success': False, 'error': 'Internal server error'}), 500
    
    @bp.route('/api/v1/analysis/capital-flow/<symbol>', methods=['GET'])
    def get_capital_flow(symbol: str):
        """Get capital flow data for a stock."""
        try:
            limit = min(request.args.get('limit', 30, type=int), 200)
            from db import DatabaseManager
            db = DatabaseManager(db_path)
            rows = db.fetch_all(
                '''SELECT trade_date, main_net_inflow, super_large_net_inflow, 
                   large_net_inflow, medium_net_inflow, small_net_inflow
                   FROM capital_flow WHERE symbol = ? ORDER BY trade_date DESC LIMIT ?''',
                (symbol, limit)
            )
            return jsonify({'success': True, 'data': [dict(r) for r in rows]})
        except Exception as e:
            logger.error(f"Capital flow error: {e}", exc_info=True)
            return jsonify({'success': False, 'error': 'Internal server error'}), 500
    
    @bp.route('/api/v1/analysis/northbound/<symbol>', methods=['GET'])
    def get_northbound(symbol: str):
        """Get northbound holdings for a stock."""
        try:
            limit = min(request.args.get('limit', 30, type=int), 200)
            # Strip prefix (sz/sh) for database query
            clean_symbol = symbol
            if symbol.startswith(('sz', 'sh', 'bj')):
                clean_symbol = symbol[2:]
            from db import DatabaseManager
            db = DatabaseManager(db_path)
            rows = db.fetch_all(
                '''SELECT trade_date, hold_shares, hold_pct 
                   FROM northbound_holdings WHERE symbol = ? ORDER BY trade_date DESC LIMIT ?''',
                (clean_symbol, limit)
            )
            return jsonify({'success': True, 'data': [dict(r) for r in rows]})
        except Exception as e:
            logger.error(f"Northbound error: {e}", exc_info=True)
            return jsonify({'success': False, 'error': 'Internal server error'}), 500

    @bp.route('/api/v1/analysis/northbound-flow', methods=['GET'])
    def get_northbound_flow():
        """Get global northbound (北向) net buy flow data."""
        try:
            limit = min(request.args.get('limit', 90, type=int), 365)
            from db import DatabaseManager
            db = DatabaseManager(db_path)
            rows = db.fetch_all(
                '''SELECT trade_date, total_net_buy, sh_net_buy, sz_net_buy
                   FROM northbound_flow ORDER BY trade_date DESC LIMIT ?''',
                (limit,)
            )
            return jsonify({'success': True, 'data': [dict(r) for r in rows]})
        except Exception as e:
            logger.error(f"Northbound flow error: {e}", exc_info=True)
            return jsonify({'success': False, 'error': 'Internal server error'}), 500

    @bp.route('/api/v1/analysis/data-overview', methods=['GET'])
    def get_data_overview():
        """Get database statistics overview."""
        try:
            from db import DatabaseManager
            db = DatabaseManager(db_path)
            tables_info = {
                'kline_daily': {'date_col': 'trade_date', 'symbol_col': 'symbol'},
                'kline_weekly': {'date_col': 'trade_week', 'symbol_col': 'symbol'},
                'kline_monthly': {'date_col': 'trade_month', 'symbol_col': 'symbol'},
                'daily_valuation': {'date_col': 'trade_date', 'symbol_col': 'symbol'},
                'capital_flow': {'date_col': 'trade_date', 'symbol_col': 'symbol'},
                'margin_data': {'date_col': 'trade_date', 'symbol_col': 'symbol'},
                'shareholder_data': {'date_col': 'report_date', 'symbol_col': 'symbol'},
                'northbound_flow': {'date_col': 'trade_date', 'symbol_col': None},
                'northbound_holdings': {'date_col': 'trade_date', 'symbol_col': 'symbol'},
                'stock_industry': {'date_col': None, 'symbol_col': 'symbol'},
                'financial_indicators': {'date_col': 'report_date', 'symbol_col': 'symbol'},
            }
            result = {}
            for table, info in tables_info.items():
                try:
                    count = db.fetch_one(f'SELECT COUNT(*) as cnt FROM {table}')
                    total = count['cnt'] if count else 0
                    symbols = 0
                    if info['symbol_col']:
                        sc = db.fetch_one(f'SELECT COUNT(DISTINCT {info["symbol_col"]}) as cnt FROM {table}')
                        symbols = sc['cnt'] if sc else 0
                    date_range = {}
                    if info['date_col'] and total > 0:
                        mn = db.fetch_one(f'SELECT MIN({info["date_col"]}) as d FROM {table}')
                        mx = db.fetch_one(f'SELECT MAX({info["date_col"]}) as d FROM {table}')
                        date_range = {'min': mn['d'] if mn else None, 'max': mx['d'] if mx else None}
                    result[table] = {'total_rows': total, 'stocks': symbols, 'date_range': date_range}
                except Exception as te:
                    result[table] = {'total_rows': 0, 'stocks': 0, 'date_range': {}, 'error': str(te)}
            return jsonify({'success': True, 'data': result})
        except Exception as e:
            logger.error(f"Data overview error: {e}", exc_info=True)
            return jsonify({'success': False, 'error': 'Internal server error'}), 500
    
    @bp.route('/api/v1/analysis/margin/<symbol>', methods=['GET'])
    def get_margin(symbol: str):
        """Get margin trading data for a stock."""
        try:
            limit = min(request.args.get('limit', 30, type=int), 200)
            # Strip prefix (sz/sh) for database query
            clean_symbol = symbol
            if symbol.startswith(('sz', 'sh', 'bj')):
                clean_symbol = symbol[2:]
            from db import DatabaseManager
            db = DatabaseManager(db_path)
            rows = db.fetch_all(
                '''SELECT trade_date, margin_buy, margin_sell, margin_balance, short_balance
                   FROM margin_data WHERE symbol = ? ORDER BY trade_date DESC LIMIT ?''',
                (clean_symbol, limit)
            )
            return jsonify({'success': True, 'data': [dict(r) for r in rows]})
        except Exception as e:
            logger.error(f"Margin error: {e}", exc_info=True)
            return jsonify({'success': False, 'error': 'Internal server error'}), 500
    
    @bp.route('/api/v1/analysis/shareholders/<symbol>', methods=['GET'])
    def get_shareholders(symbol: str):
        """Get shareholder data for a stock."""
        try:
            limit = min(request.args.get('limit', 10, type=int), 50)
            from db import DatabaseManager
            db = DatabaseManager(db_path)
            rows = db.fetch_all(
                '''SELECT report_date, total_shareholders, change_pct, avg_holdings, top10_pct
                   FROM shareholder_data WHERE symbol = ? ORDER BY report_date DESC LIMIT ?''',
                (symbol, limit)
            )
            return jsonify({'success': True, 'data': [dict(r) for r in rows]})
        except Exception as e:
            logger.error(f"Shareholder error: {e}", exc_info=True)
            return jsonify({'success': False, 'error': 'Internal server error'}), 500
    
    @bp.route('/api/v1/analysis/valuation/<symbol>', methods=['GET'])
    def get_valuation(symbol: str):
        """Get PE/PB/PS valuation history."""
        try:
            limit = min(request.args.get('limit', 60, type=int), 365)
            from db import DatabaseManager
            db = DatabaseManager(db_path)
            rows = db.fetch_all(
                '''SELECT trade_date, pe_ttm, pb, ps_ttm
                   FROM daily_valuation WHERE symbol = ? ORDER BY trade_date DESC LIMIT ?''',
                (symbol, limit)
            )
            return jsonify({'success': True, 'data': [dict(r) for r in rows]})
        except Exception as e:
            logger.error(f"Valuation error: {e}", exc_info=True)
            return jsonify({'success': False, 'error': 'Internal server error'}), 500
    
    @bp.route('/api/v1/analysis/strategies/compare', methods=['GET'])
    def compare_strategies():
        """Get all available strategy backtest results for comparison."""
        try:
            results = {}
            for fname in ['walkforward_results.json', 'strategy_evaluation_results.json',
                          'pit_results_v2.json', 'backtest_full_results.json']:
                fpath = os.path.join(project_root, fname)
                if os.path.exists(fpath):
                    with open(fpath, 'r') as f:
                        results[fname.replace('.json', '')] = json.load(f)
            return jsonify({'success': True, 'data': results})
        except Exception as e:
            logger.error(f"Strategy compare error: {e}", exc_info=True)
            return jsonify({'success': False, 'error': 'Internal server error'}), 500
    
    return bp
