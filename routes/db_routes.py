"""
Database query routes.
API endpoints for browsing tables, schemas, and running queries.
"""

import csv
import io
import json
import logging
import os
import time
from flask import Blueprint, jsonify, request, Response

logger = logging.getLogger(__name__)

# Load table metadata
_METADATA_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'table_metadata.json')
_table_meta = {}
if os.path.exists(_METADATA_PATH):
    with open(_METADATA_PATH, 'r', encoding='utf-8') as f:
        _table_meta = json.load(f)

# Cache for table row counts (avoids slow COUNT(*) on huge tables)
_row_count_cache = {'data': None, 'ts': 0}
_CACHE_TTL = 300  # 5 minutes


def create_db_routes(stock_service):
    """Create and return the database query routes blueprint."""

    bp = Blueprint('db_v1', __name__)

    def get_conn():
        return stock_service._db.get_connection()

    def _get_table_counts(conn):
        """Get row counts with caching. Uses sqlite_stat1 when available for speed."""
        now = time.time()
        if _row_count_cache['data'] and (now - _row_count_cache['ts']) < _CACHE_TTL:
            return _row_count_cache['data']

        result = []
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()

        # Try fast path: sqlite_stat1 has pre-computed row estimates
        stat_available = False
        try:
            stat_rows = conn.execute("SELECT tbl, stat FROM sqlite_stat1 WHERE idx IS NULL").fetchall()
            stat_map = {r['tbl']: int(r['stat'].split()[0]) for r in stat_rows if r['stat']}
            stat_available = True
        except Exception:
            stat_map = {}

        for t in tables:
            name = t['name']
            if stat_available and name in stat_map:
                result.append({'name': name, 'rows': stat_map[name]})
            else:
                try:
                    count = conn.execute(f'SELECT COUNT(*) as c FROM "{name}"').fetchone()['c']
                    result.append({'name': name, 'rows': count})
                except Exception:
                    result.append({'name': name, 'rows': -1})

        _row_count_cache['data'] = result
        _row_count_cache['ts'] = now
        return result

    @bp.route('/api/v1/db/tables', methods=['GET'])
    def api_db_tables():
        """List all tables with row counts (cached) and metadata."""
        try:
            with get_conn() as conn:
                result = _get_table_counts(conn)
            # Attach metadata
            for t in result:
                meta = _table_meta.get(t['name'], {})
                t['display_name'] = meta.get('name', '')
                t['desc'] = meta.get('desc', '')
            return jsonify({'success': True, 'tables': result})
        except Exception as e:
            logger.error(f"db tables error: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500

    @bp.route('/api/v1/db/schema/<table>', methods=['GET'])
    def api_db_schema(table):
        """Get table schema with Chinese descriptions."""
        try:
            if not table.replace('_', '').replace('-', '').isalnum():
                return jsonify({'success': False, 'error': 'Invalid table name'}), 400
            with get_conn() as conn:
                cols = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
                col_descs = _table_meta.get(table, {}).get('columns', {})
                schema = [{
                    'name': c['name'],
                    'type': c['type'],
                    'notnull': bool(c['notnull']),
                    'pk': bool(c['pk']),
                    'default': c['dflt_value'],
                    'desc': col_descs.get(c['name'], '')
                } for c in cols]
                indexes = conn.execute(f'PRAGMA index_list("{table}")').fetchall()
                idx_list = [{'name': i['name'], 'unique': bool(i['unique'])} for i in indexes]
            meta = _table_meta.get(table, {})
            return jsonify({
                'success': True, 'table': table,
                'display_name': meta.get('name', ''),
                'table_desc': meta.get('desc', ''),
                'columns': schema, 'indexes': idx_list
            })
        except Exception as e:
            logger.error(f"db schema error: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500

    @bp.route('/api/v1/db/data/<table>', methods=['GET'])
    def api_db_data(table):
        """Get sample data from a table."""
        try:
            if not table.replace('_', '').replace('-', '').isalnum():
                return jsonify({'success': False, 'error': 'Invalid table name'}), 400
            limit = min(int(request.args.get('limit', 50)), 500)
            offset = int(request.args.get('offset', 0))
            order = request.args.get('order', '')
            direction = request.args.get('dir', 'DESC')
            sql_filter = request.args.get('where', '')

            if direction not in ('ASC', 'DESC'):
                direction = 'DESC'

            with get_conn() as conn:
                # Build WHERE clause
                where_clause = ''
                if sql_filter:
                    where_clause = f'WHERE {sql_filter}'

                # Get total count (with filter applied)
                if where_clause:
                    total = conn.execute(f'SELECT COUNT(*) as c FROM "{table}" {where_clause}').fetchone()['c']
                else:
                    counts = _get_table_counts(conn)
                    total = next((t['rows'] for t in counts if t['name'] == table), -1)

                order_clause = ''
                if order:
                    cols = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
                    valid_cols = {c['name'] for c in cols}
                    if order in valid_cols:
                        order_clause = f'ORDER BY "{order}" {direction}'

                cursor = conn.execute(
                    f'SELECT * FROM "{table}" {where_clause} {order_clause} LIMIT ? OFFSET ?',
                    (limit, offset)
                )
                rows = cursor.fetchall()
                columns = [desc[0] for desc in cursor.description] if cursor.description else []
                data = [dict(r) for r in rows]

            return jsonify({
                'success': True, 'table': table, 'columns': columns,
                'data': data, 'total': total, 'limit': limit, 'offset': offset
            })
        except Exception as e:
            logger.error(f"db data error: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500

    @bp.route('/api/v1/db/query', methods=['POST'])
    def api_db_query():
        """Run a custom SQL query (SELECT only)."""
        try:
            body = request.get_json()
            sql = (body or {}).get('sql', '').strip()
            if not sql:
                return jsonify({'success': False, 'error': 'SQL required'}), 400

            upper = sql.upper().lstrip()
            if not upper.startswith('SELECT'):
                return jsonify({'success': False, 'error': 'Only SELECT queries are allowed'}), 400
            for kw in ('INSERT', 'UPDATE', 'DELETE', 'DROP', 'ALTER', 'CREATE', 'REPLACE', 'ATTACH', 'DETACH'):
                if kw in upper:
                    return jsonify({'success': False, 'error': f'Keyword {kw} is not allowed'}), 400

            limit = min(int((body or {}).get('limit', 200)), 1000)
            sql_final = sql if 'LIMIT' in sql.upper() else sql + f' LIMIT {limit}'

            with get_conn() as conn:
                cursor = conn.execute(sql_final)
                rows = cursor.fetchall()
                columns = [desc[0] for desc in cursor.description] if cursor.description else []
                data = [dict(r) for r in rows]

            return jsonify({
                'success': True, 'columns': columns, 'data': data,
                'count': len(data), 'sql': sql
            })
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 400

    @bp.route('/api/v1/db/analyze/<table>', methods=['POST'])
    def api_db_analyze(table):
        """Run ANALYZE to update sqlite_stat1 for faster COUNT queries."""
        try:
            if not table.replace('_', '').replace('-', '').isalnum():
                return jsonify({'success': False, 'error': 'Invalid table name'}), 400
            with get_conn() as conn:
                conn.execute(f'ANALYZE "{table}"')
            # Invalidate cache
            _row_count_cache['data'] = None
            return jsonify({'success': True, 'message': f'ANALYZE {table} done'})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500

    @bp.route('/api/v1/db/facets/<table>', methods=['GET'])
    def api_db_facets(table):
        """Get facet (distinct value counts) for specified columns."""
        try:
            if not table.replace('_', '').replace('-', '').isalnum():
                return jsonify({'success': False, 'error': 'Invalid table name'}), 400
            columns = request.args.get('columns', '')
            if not columns:
                return jsonify({'success': False, 'error': 'columns parameter required'}), 400
            col_list = [c.strip() for c in columns.split(',') if c.strip()]
            limit = min(int(request.args.get('limit', 20)), 50)

            # Get current WHERE filter from query params
            where_filter = request.args.get('where', '')

            with get_conn() as conn:
                # Validate columns exist
                schema = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
                valid_cols = {c['name'] for c in schema}
                # Build base WHERE for filtered facets
                base_where = ''
                if where_filter:
                    # Simple pass-through - validate it's safe-ish
                    base_where = f'WHERE {where_filter}'

                facets = {}
                for col in col_list:
                    if col not in valid_cols:
                        continue
                    # Skip very high-cardinality columns (likely not good facets)
                    try:
                        distinct_count = conn.execute(
                            f'SELECT COUNT(DISTINCT "{col}") as c FROM "{table}" {base_where}'
                        ).fetchone()['c']
                        if distinct_count > 200:
                            facets[col] = {'values': [], 'too_many': True, 'distinct': distinct_count}
                            continue
                        rows = conn.execute(
                            f'SELECT "{col}" as val, COUNT(*) as cnt FROM "{table}" {base_where} GROUP BY "{col}" ORDER BY cnt DESC LIMIT ?',
                            (limit,)
                        ).fetchall()
                        facets[col] = {
                            'values': [{'value': r['val'], 'count': r['cnt']} for r in rows],
                            'too_many': False,
                            'distinct': distinct_count
                        }
                    except Exception as e:
                        logger.warning(f"facet error for {col}: {e}")
                        continue

            return jsonify({'success': True, 'table': table, 'facets': facets})
        except Exception as e:
            logger.error(f"db facets error: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500

    @bp.route('/api/v1/db/fkeys/<table>', methods=['GET'])
    def api_db_fkeys(table):
        """Get foreign key relationships for a table."""
        try:
            if not table.replace('_', '').replace('-', '').isalnum():
                return jsonify({'success': False, 'error': 'Invalid table name'}), 400
            with get_conn() as conn:
                fkeys = conn.execute(f'PRAGMA foreign_key_list("{table}")').fetchall()
                fk_list = [{
                    'from': fk['from'],
                    'to_table': fk['table'],
                    'to_column': fk['to'],
                    'id': fk['id']
                } for fk in fkeys]

                # Also find tables that reference this table (reverse FKs)
                all_tables = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                ).fetchall()
                reverse_fks = []
                for t in all_tables:
                    if t['name'] == table:
                        continue
                    refs = conn.execute(f'PRAGMA foreign_key_list("{t["name"]}")').fetchall()
                    for ref in refs:
                        if ref['table'] == table:
                            reverse_fks.append({
                                'from_table': t['name'],
                                'from_column': ref['from'],
                                'to_column': ref['to']
                            })

            return jsonify({'success': True, 'table': table, 'foreign_keys': fk_list, 'referenced_by': reverse_fks})
        except Exception as e:
            logger.error(f"db fkeys error: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500

    @bp.route('/api/v1/db/export/<table>', methods=['GET'])
    def api_db_export(table):
        """Export table data or SQL result as CSV."""
        try:
            if not table.replace('_', '').replace('-', '').isalnum():
                return jsonify({'success': False, 'error': 'Invalid table name'}), 400
            sql_filter = request.args.get('where', '')
            limit = min(int(request.args.get('limit', 10000)), 50000)
            order = request.args.get('order', '')
            direction = request.args.get('dir', 'DESC')
            if direction not in ('ASC', 'DESC'):
                direction = 'DESC'

            with get_conn() as conn:
                # Validate order column
                order_clause = ''
                if order:
                    cols = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
                    valid_cols = {c['name'] for c in cols}
                    if order in valid_cols:
                        order_clause = f'ORDER BY "{order}" {direction}'

                where_clause = ''
                if sql_filter:
                    where_clause = f'WHERE {sql_filter}'

                cursor = conn.execute(
                    f'SELECT * FROM "{table}" {where_clause} {order_clause} LIMIT ?',
                    (limit,)
                )
                rows = cursor.fetchall()
                columns = [desc[0] for desc in cursor.description] if cursor.description else []

            # Generate CSV
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(columns)
            for row in rows:
                writer.writerow([row[c] for c in columns])

            return Response(
                output.getvalue(),
                mimetype='text/csv',
                headers={'Content-Disposition': f'attachment; filename={table}.csv'}
            )
        except Exception as e:
            logger.error(f"db export error: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500

    @bp.route('/api/v1/db/export-query', methods=['POST'])
    def api_db_export_query():
        """Export SQL query result as CSV."""
        try:
            body = request.get_json()
            sql = (body or {}).get('sql', '').strip()
            if not sql:
                return jsonify({'success': False, 'error': 'SQL required'}), 400
            upper = sql.upper().lstrip()
            if not upper.startswith('SELECT'):
                return jsonify({'success': False, 'error': 'Only SELECT queries are allowed'}), 400
            for kw in ('INSERT', 'UPDATE', 'DELETE', 'DROP', 'ALTER', 'CREATE', 'REPLACE', 'ATTACH', 'DETACH'):
                if kw in upper:
                    return jsonify({'success': False, 'error': f'Keyword {kw} is not allowed'}), 400

            limit = min(int((body or {}).get('limit', 10000)), 50000)
            sql_final = sql if 'LIMIT' in sql.upper() else sql + f' LIMIT {limit}'

            with get_conn() as conn:
                cursor = conn.execute(sql_final)
                rows = cursor.fetchall()
                columns = [desc[0] for desc in cursor.description] if cursor.description else []

            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(columns)
            for row in rows:
                writer.writerow([row[c] for c in columns])

            return Response(
                output.getvalue(),
                mimetype='text/csv',
                headers={'Content-Disposition': 'attachment; filename=query_result.csv'}
            )
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 400

    return bp
