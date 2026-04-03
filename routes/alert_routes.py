"""
Alert routes.
API endpoints for alert history, feishu notifications, and alert management.
"""
import os
import logging
import json
from datetime import datetime
from flask import Blueprint, jsonify, request

logger = logging.getLogger(__name__)


def create_alert_routes(strategy_service, stock_service):
    """Create and return the alert routes blueprint."""
    
    bp = Blueprint('alert_v1', __name__)
    
    from db import DatabaseManager
    _db = DatabaseManager(stock_service.db_path)
    
    @bp.route('/api/v1/alerts/history', methods=['GET'])
    def get_alert_history():
        """Get paginated alert history."""
        try:
            page = request.args.get('page', 1, type=int)
            page_size = min(request.args.get('pageSize', 20, type=int), 100)
            level = request.args.get('level')  # Optional filter by level
            is_read = request.args.get('isRead', type=int)  # 0 or 1
            strategy_id = request.args.get('strategyId')
            
            offset = (page - 1) * page_size
            
            # Build query with filters
            query = "SELECT * FROM alerts WHERE 1=1"
            params = []
            
            if level:
                query += " AND level = ?"
                params.append(level)
            
            if is_read is not None:
                query += " AND is_read = ?"
                params.append(is_read)
            
            if strategy_id:
                query += " AND strategy_id = ?"
                params.append(strategy_id)
            
            # Get total count
            count_query = f"SELECT COUNT(*) as total FROM ({query})"
            total_row = _db.fetch_one(count_query, tuple(params))
            total = total_row['total'] if total_row else 0
            
            # Get paginated results
            query += " ORDER BY timestamp DESC LIMIT ? OFFSET ?"
            params.extend([page_size, offset])
            
            rows = _db.fetch_all(query, tuple(params))
            
            alerts = []
            for row in rows:
                ts = row['timestamp']
                # Handle different timestamp formats (seconds, milliseconds, microseconds)
                if ts:
                    if ts > 9999999999:  # milliseconds
                        ts = ts / 1000
                    if ts > 999999999999:  # microseconds
                        ts = ts / 1000000
                    try:
                        dt_str = datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S')
                    except (ValueError, OSError):
                        dt_str = None
                else:
                    dt_str = None
                
                alerts.append({
                    'id': row['id'],
                    'timestamp': row['timestamp'],
                    'datetime': dt_str,
                    'strategy_id': row['strategy_id'],
                    'message': row['message'],
                    'level': row['level'],
                    'stock': row['stock'],
                    'trigger_condition': row['trigger_condition'],
                    'price': row['price'],
                    'is_read': bool(row['is_read'])
                })
            
            total_pages = (total + page_size - 1) // page_size
            
            return jsonify({
                'success': True,
                'alerts': alerts,
                'pagination': {
                    'page': page,
                    'pageSize': page_size,
                    'total': total,
                    'totalPages': total_pages,
                    'hasNext': page < total_pages,
                    'hasPrev': page > 1
                }
            })
            
        except Exception as e:
            logger.error(f"获取告警历史失败: {e}")
            return jsonify({'success': False, 'error': 'Internal server error'}), 500
    
    @bp.route('/api/v1/alerts/mark_read', methods=['POST'])
    def mark_alerts_read():
        """Mark alerts as read."""
        try:
            data = request.get_json()
            alert_ids = data.get('alertIds', [])
            mark_all = data.get('markAll', False)
            
            if mark_all:
                affected = _db.execute("UPDATE alerts SET is_read = 1 WHERE is_read = 0")
            elif alert_ids:
                placeholders = ','.join('?' for _ in alert_ids)
                affected = _db.execute(f"UPDATE alerts SET is_read = 1 WHERE id IN ({placeholders})", tuple(alert_ids))
            else:
                affected = 0
            
            return jsonify({
                'success': True,
                'updated': affected
            })
            
        except Exception as e:
            logger.error(f"标记已读失败: {e}")
            return jsonify({'success': False, 'error': 'Internal server error'}), 500
    
    @bp.route('/api/v1/alerts/unread_count', methods=['GET'])
    def get_unread_count():
        """Get count of unread alerts."""
        try:
            result = _db.fetch_one("SELECT COUNT(*) as count FROM alerts WHERE is_read = 0")
            count = result['count'] if result else 0
            
            return jsonify({
                'success': True,
                'unreadCount': count
            })
            
        except Exception as e:
            logger.error(f"获取未读数量失败: {e}")
            return jsonify({'success': False, 'error': 'Internal server error'}), 500
    
    @bp.route('/api/v1/alerts/feishu/send', methods=['POST'])
    def send_feishu_alert():
        """Send a test feishu alert."""
        try:
            from services.feishu_service import FeishuService
            
            data = request.get_json() or {}
            receive_id = data.get('receiveId')
            
            feishu = FeishuService()
            result = feishu.send_test_message(receive_id=receive_id)
            
            return jsonify(result)
            
        except Exception as e:
            logger.error(f"飞书消息发送失败: {e}")
            return jsonify({'success': False, 'error': 'Internal server error'}), 500
    
    @bp.route('/api/v1/alerts/feishu/config', methods=['POST'])
    def configure_feishu():
        """Configure feishu app credentials."""
        try:
            data = request.get_json()
            app_id = data.get('appId', '').strip()
            app_secret = data.get('appSecret', '').strip()
            receive_id = data.get('receiveId', '').strip()
            
            # Validate format
            if not app_id or not app_id.startswith('cli_'):
                return jsonify({'success': False, 'error': 'Invalid appId format'}), 400
            if not app_secret or len(app_secret) < 10:
                return jsonify({'success': False, 'error': 'Invalid appSecret'}), 400
            if not receive_id:
                return jsonify({'success': False, 'error': 'receiveId is required'}), 400
            
            # Save to config file (restrict path traversal)
            config_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
            config_path = os.path.join(config_dir, 'feishu_config.json')
            config = {
                'app_id': app_id,
                'app_secret': app_secret,
                'receive_id': receive_id,
                'updated_at': datetime.now().isoformat()
            }
            
            with open(config_path, 'w') as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
            
            return jsonify({
                'success': True,
                'message': '飞书配置已保存'
            })
            
        except Exception as e:
            logger.error(f"飞书配置保存失败: {e}")
            return jsonify({'success': False, 'error': 'Internal server error'}), 500
    
    # Legacy endpoints
    @bp.route('/api/alerts/pending', methods=['GET'])
    def legacy_get_pending():
        """Legacy: redirect to v1."""
        return get_alert_history()
    
    @bp.route('/api/alerts/history', methods=['GET'])
    def legacy_get_history():
        """Legacy: redirect to v1."""
        return get_alert_history()
    
    @bp.route('/api/alerts/mark_read', methods=['POST'])
    def legacy_mark_read():
        """Legacy: redirect to v1."""
        return mark_alerts_read()
    
    @bp.route('/api/alerts/feishu/send', methods=['POST'])
    def legacy_send_feishu():
        """Legacy: redirect to v1."""
        return send_feishu_alert()
    
    @bp.route('/api/alerts/multi', methods=['GET', 'POST'])
    def legacy_multi():
        """Legacy: redirect to v1."""
        if request.method == 'GET':
            return get_alert_history()
        else:
            return mark_alerts_read()
    
    return bp
