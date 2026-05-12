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

from db import _is_postgres_target

logger = logging.getLogger(__name__)

# Load table metadata
_METADATA_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'table_metadata.json')
_table_meta = {}
if os.path.exists(_METADATA_PATH):
    with open(_METADATA_PATH, 'r', encoding='utf-8') as f:
        _table_meta = json.load(f)

# Cache for table row counts
_row_count_cache = {'data': None, 'ts': 0}
_CACHE_TTL = 300


def create_db_routes(stock_service):
    """Create and return the database query routes blueprint."""

    bp = Blueprint('db_v1', __name__)
    is_postgres = _is_postgres_target(stock_service.db_path)

    def get_conn():
        return stock_service._db.get_connection()

    def _exec(conn, sql, params=()):
        if is_postgres:
            from psycopg2.extras import RealDictCursor
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(sql.replace('?', '%s'), params)
                rows = cursor.fetchall() if cursor.description else []
                columns = [desc[0] for desc in cursor.description] if cursor.description else []
            return rows, columns
        cursor = conn.execute(sql, params)
        rows = cursor.fetchall()
        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        return rows, columns

    def _list_tables(conn):
        if is_postgres:
            rows, _ = _exec(conn, """
                SELECT tablename
                FROM pg_catalog.pg_tables
                WHERE schemaname = 'public'
                ORDER BY tablename
            """)
            return [{'name': r['tablename']} for r in rows]
        rows, _ = _exec(conn, "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")
        return [{'name': r['name']} for r in rows]

    def _table_columns(conn, table):
        if is_postgres:
            rows, _ = _exec(conn, """
                SELECT c.column_name AS name,
                       c.data_type AS type,
                       CASE WHEN c.is_nullable = 'NO' THEN 1 ELSE 0 END AS notnull,
                       CASE WHEN tc.constraint_type = 'PRIMARY KEY' THEN 1 ELSE 0 END AS pk,
                       c.column_default AS dflt_value
                FROM information_schema.columns c
                LEFT JOIN information_schema.key_column_usage kcu
                  ON c.table_schema = kcu.table_schema
                 AND c.table_name = kcu.table_name
                 AND c.column_name = kcu.column_name
                LEFT JOIN information_schema.table_constraints tc
                  ON kcu.constraint_name = tc.constraint_name
                 AND kcu.table_schema = tc.table_schema
                 AND tc.constraint_type = 'PRIMARY KEY'
                WHERE c.table_schema = 'public' AND c.table_name = ?
                ORDER BY c.ordinal_position
            """, (table,))
            return rows
        rows, _ = _exec(conn, f'PRAGMA table_info("{table}")')
        return rows

    def _table_indexes(conn, table):
        if is_postgres:
            rows, _ = _exec(conn, """
                SELECT indexname AS name, indexdef
                FROM pg_indexes
                WHERE schemaname = 'public' AND tablename = ?
                ORDER BY indexname
            """, (table,))
            return [{'name': r['name'], 'unique': ' UNIQUE INDEX ' in r['indexdef']} for r in rows]
        rows, _ = _exec(conn, f'PRAGMA index_list("{table}")')
        return [{'name': r['name'], 'unique': bool(r['unique'])} for r in rows]

    def _table_fkeys(conn, table):
        if is_postgres:
            rows, _ = _exec(conn, """
                SELECT
                    kcu.column_name AS "from",
                    ccu.table_name AS table,
                    ccu.column_name AS "to",
                    tc.constraint_name AS id
                FROM information_schema.table_constraints AS tc
                JOIN information_schema.key_column_usage AS kcu
                  ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema
                JOIN information_schema.constraint_column_usage AS ccu
                  ON ccu.constraint_name = tc.constraint_name AND ccu.table_schema = tc.table_schema
                WHERE tc.constraint_type = 'FOREIGN KEY'
                  AND tc.table_schema = 'public'
                  AND tc.table_name = ?
            """, (table,))
            return rows
        rows, _ = _exec(conn, f'PRAGMA foreign_key_list("{table}")')
        return rows

    def _get_table_counts(conn):
        now = time.time()
        if _row_count_cache['data'] and (now - _row_count_cache['ts']) < _CACHE_TTL:
            return _row_count_cache['data']

        result = []
        tables = _list_tables(conn)
        for t in tables:
            name = t['name']
            try:
                rows, _ = _exec(conn, f'SELECT COUNT(*) as c FROM "{name}"')
                count = rows[0]['c'] if rows else -1
                result.append({'name': name, 'rows': count})
            except Exception:
                result.append({'name': name, 'rows': -1})

        _row_count_cache['data'] = result
        _row_count_cache['ts'] = now
        return result

    @bp.route('/api/v1/db/tables', methods=['GET'])
    def api_db_tables():
        try:
            with get_conn() as conn:
                result = _get_table_counts(conn)
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
        try:
            if not table.replace('_', '').replace('-', '').isalnum():
                return jsonify({'success': False, 'error': 'Invalid table name'}), 400
            with get_conn() as conn:
                cols = _table_columns(conn, table)
                col_descs = _table_meta.get(table, {}).get('columns', {})
                schema = [{
                    'name': c['name'],
                    'type': c['type'],
                    'notnull': bool(c['notnull']),
                    'pk': bool(c['pk']),
                    'default': c['dflt_value'],
                    'desc': col_descs.get(c['name'], '')
                } for c in cols]
                idx_list = _table_indexes(conn, table)
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
                where_clause = f'WHERE {sql_filter}' if sql_filter else ''
                if where_clause:
                    rows, _ = _exec(conn, f'SELECT COUNT(*) as c FROM "{table}" {where_clause}')
                    total = rows[0]['c'] if rows else 0
                else:
                    counts = _get_table_counts(conn)
                    total = next((t['rows'] for t in counts if t['name'] == table), -1)

                order_clause = ''
                if order:
                    cols = _table_columns(conn, table)
                    valid_cols = {c['name'] for c in cols}
                    if order in valid_cols:
                        order_clause = f'ORDER BY "{order}" {direction}'

                rows, columns = _exec(
                    conn,
                    f'SELECT * FROM "{table}" {where_clause} {order_clause} LIMIT ? OFFSET ?',
                    (limit, offset)
                )
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
                rows, columns = _exec(conn, sql_final)
                data = [dict(r) for r in rows]

            return jsonify({
                'success': True, 'columns': columns, 'data': data,
                'count': len(data), 'sql': sql
            })
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 400

    @bp.route('/api/v1/db/analyze/<table>', methods=['POST'])
    def api_db_analyze(table):
        try:
            if not table.replace('_', '').replace('-', '').isalnum():
                return jsonify({'success': False, 'error': 'Invalid table name'}), 400
            with get_conn() as conn:
                _exec(conn, f'ANALYZE "{table}"')
            _row_count_cache['data'] = None
            return jsonify({'success': True, 'message': f'ANALYZE {table} done'})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500

    @bp.route('/api/v1/db/facets/<table>', methods=['GET'])
    def api_db_facets(table):
        try:
            if not table.replace('_', '').replace('-', '').isalnum():
                return jsonify({'success': False, 'error': 'Invalid table name'}), 400
            columns = request.args.get('columns', '')
            if not columns:
                return jsonify({'success': False, 'error': 'columns parameter required'}), 400
            col_list = [c.strip() for c in columns.split(',') if c.strip()]
            limit = min(int(request.args.get('limit', 20)), 50)
            where_filter = request.args.get('where', '')

            with get_conn() as conn:
                schema = _table_columns(conn, table)
                valid_cols = {c['name'] for c in schema}
                base_where = f'WHERE {where_filter}' if where_filter else ''

                facets = {}
                for col in col_list:
                    if col not in valid_cols:
                        continue
                    try:
                        rows, _ = _exec(conn, f'SELECT COUNT(DISTINCT "{col}") as c FROM "{table}" {base_where}')
                        distinct_count = rows[0]['c'] if rows else 0
                        if distinct_count > 200:
                            facets[col] = {'values': [], 'too_many': True, 'distinct': distinct_count}
                            continue
                        rows, _ = _exec(
                            conn,
                            f'SELECT "{col}" as val, COUNT(*) as cnt FROM "{table}" {base_where} GROUP BY "{col}" ORDER BY cnt DESC LIMIT ?',
                            (limit,)
                        )
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
        try:
            if not table.replace('_', '').replace('-', '').isalnum():
                return jsonify({'success': False, 'error': 'Invalid table name'}), 400
            with get_conn() as conn:
                fkeys = _table_fkeys(conn, table)
                fk_list = [{
                    'from': fk['from'],
                    'to_table': fk['table'],
                    'to_column': fk['to'],
                    'id': fk['id']
                } for fk in fkeys]

                all_tables = _list_tables(conn)
                reverse_fks = []
                for t in all_tables:
                    if t['name'] == table:
                        continue
                    refs = _table_fkeys(conn, t['name'])
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
                order_clause = ''
                if order:
                    cols = _table_columns(conn, table)
                    valid_cols = {c['name'] for c in cols}
                    if order in valid_cols:
                        order_clause = f'ORDER BY "{order}" {direction}'

                where_clause = f'WHERE {sql_filter}' if sql_filter else ''
                rows, columns = _exec(
                    conn,
                    f'SELECT * FROM "{table}" {where_clause} {order_clause} LIMIT ?',
                    (limit,)
                )

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
                rows, columns = _exec(conn, sql_final)

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
