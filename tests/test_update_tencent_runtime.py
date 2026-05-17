import importlib
import os
import sqlite3
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = PROJECT_ROOT / 'scripts' / 'daily'
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import sync_health


def _load_update_tencent(monkeypatch, tmp_path, require_pg='0', runtime_python=None):
    monkeypatch.setenv('REQUIRE_PG', require_pg)
    monkeypatch.setenv('STOCKS_FILE', str(tmp_path / 'stocks.json'))
    monkeypatch.setenv('SYNC_LOG_DIR', str(tmp_path / 'logs'))
    monkeypatch.setattr(sys, 'argv', ['update_tencent.py'])
    if runtime_python is not None:
        monkeypatch.setenv('RUNTIME_PYTHON', runtime_python)
    else:
        monkeypatch.delenv('RUNTIME_PYTHON', raising=False)
    (tmp_path / 'stocks.json').write_text('{"stocks": []}', encoding='utf-8')
    sys.modules.pop('update_tencent', None)
    return importlib.import_module('update_tencent')


def test_find_best_trade_date_postgres_uses_interval_safe_sql():
    calls = []

    def exec_fn(sql, params=None):
        calls.append((sql, params))
        return ('2026-05-12', 5088)

    def fetchone_fn(result):
        return result

    result = sync_health.find_best_trade_date(
        exec_fn,
        fetchone_fn,
        today='2026-05-15',
        db_target='postgresql://user:pass@localhost/db',
        min_stocks=4000,
        lookback_days=10,
    )

    assert result == '2026-05-12'
    assert len(calls) == 1
    sql, params = calls[0]
    assert "WHERE trade_date >= (%s::date - (%s || ' day')::interval)" in sql
    assert '(%s || \' day\')::interval' in sql
    assert params == ('2026-05-15', 10, 4000)


def test_write_sync_status_persists_ready_payload(tmp_path):
    status_path = tmp_path / 'stock_sync_status.json'
    sync_health.write_sync_status({'ready': True, 'target_date': '2026-05-12'}, path=str(status_path))

    saved = sync_health.read_sync_status(path=str(status_path))
    assert saved['ready'] is True
    assert saved['target_date'] == '2026-05-12'
    assert 'updated_at' in saved


def test_get_runtime_python_prefers_existing_runtime_python_env(monkeypatch, tmp_path):
    runtime_python = tmp_path / 'runtime-python'
    runtime_python.write_text('#!/bin/sh\n', encoding='utf-8')
    runtime_python.chmod(0o755)
    module = _load_update_tencent(monkeypatch, tmp_path, runtime_python=str(runtime_python))

    assert module.get_runtime_python() == str(runtime_python)


def test_get_runtime_python_skips_missing_runtime_python_env(monkeypatch, tmp_path):
    missing = str(tmp_path / 'missing-runtime-python')
    module = _load_update_tencent(monkeypatch, tmp_path, runtime_python=missing)
    project_root = Path(module.PROJECT_ROOT)
    project_venv_python = project_root / '.venv' / 'bin' / 'python'
    original_isfile = module.os.path.isfile

    def fake_isfile(path):
        path = str(path)
        if path == str(project_venv_python):
            return False
        return original_isfile(path)

    monkeypatch.setattr(module.os.path, 'isfile', fake_isfile)

    assert module.get_runtime_python() == sys.executable


def test_get_runtime_python_skips_non_executable_project_venv(monkeypatch, tmp_path):
    module = _load_update_tencent(monkeypatch, tmp_path, runtime_python='')
    project_root = Path(module.PROJECT_ROOT)
    project_venv_python = project_root / '.venv' / 'bin' / 'python'
    project_venv_python.parent.mkdir(parents=True, exist_ok=True)
    project_venv_python.write_text('#!/bin/sh\n', encoding='utf-8')

    original_isfile = module.os.path.isfile
    original_access = module.os.access

    def fake_isfile(path):
        path = str(path)
        if path == str(project_venv_python) or path == '/tmp/fake-sys-python':
            return True
        if path == '/usr/bin/python3':
            return False
        return original_isfile(path)

    def fake_access(path, mode):
        path = str(path)
        if path == str(project_venv_python):
            return False
        if path == '/tmp/fake-sys-python':
            return True
        return original_access(path, mode)

    monkeypatch.setattr(module.os.path, 'isfile', fake_isfile)
    monkeypatch.setattr(module.os, 'access', fake_access)
    monkeypatch.setattr(module.sys, 'executable', '/tmp/fake-sys-python')

    assert module.get_runtime_python() == '/tmp/fake-sys-python'


def test_get_runtime_python_prefers_executable_project_venv(monkeypatch, tmp_path):
    module = _load_update_tencent(monkeypatch, tmp_path, runtime_python='')
    project_root = Path(module.PROJECT_ROOT)
    project_venv_python = project_root / '.venv' / 'bin' / 'python'
    backup_content = None
    backup_mode = None
    existed = project_venv_python.exists()
    if existed:
        backup_content = project_venv_python.read_bytes()
        backup_mode = project_venv_python.stat().st_mode
    project_venv_python.parent.mkdir(parents=True, exist_ok=True)
    project_venv_python.write_text('#!/bin/sh\n', encoding='utf-8')
    project_venv_python.chmod(0o755)
    try:
        module = _load_update_tencent(monkeypatch, tmp_path, runtime_python='')
        assert module.get_runtime_python() == str(project_venv_python)
    finally:
        if existed:
            project_venv_python.write_bytes(backup_content)
            project_venv_python.chmod(backup_mode)
        else:
            project_venv_python.unlink(missing_ok=True)


def test_get_runtime_python_falls_back_when_project_venv_missing(monkeypatch, tmp_path):
    module = _load_update_tencent(monkeypatch, tmp_path, runtime_python='')
    project_root = Path(module.PROJECT_ROOT)
    project_venv_python = project_root / '.venv' / 'bin' / 'python'
    original_isfile = module.os.path.isfile

    def fake_isfile(path):
        path = str(path)
        if path == str(project_venv_python):
            return False
        return original_isfile(path)

    monkeypatch.setattr(module.os.path, 'isfile', fake_isfile)

    runtime_python = module.get_runtime_python()
    assert runtime_python == sys.executable or runtime_python == '/usr/bin/python3'
    assert runtime_python != str(project_venv_python)


def test_resolve_db_target_prefers_postgres_over_stale_stock_db(monkeypatch, tmp_path):
    module = _load_update_tencent(monkeypatch, tmp_path)

    resolved = module.resolve_db_target(
        {
            'POSTGRES_DSN': 'postgresql://user:***@localhost/db',
            'STOCK_DB': '/tmp/stale.db',
        },
        require_pg=True,
        default_db_path='/tmp/default.db',
    )

    assert resolved == 'postgresql://user:***@localhost/db'


def test_resolve_db_target_ignores_default_stock_db_override_when_require_pg(monkeypatch, tmp_path):
    module = _load_update_tencent(monkeypatch, tmp_path)

    resolved = module.resolve_db_target(
        {'STOCK_DB': '/tmp/default.db'},
        require_pg=True,
        default_db_path='/tmp/default.db',
    )

    assert resolved == '/tmp/default.db'


def test_resolve_db_target_falls_back_to_default_when_require_pg_and_no_postgres(monkeypatch, tmp_path):
    module = _load_update_tencent(monkeypatch, tmp_path)

    resolved = module.resolve_db_target(
        {'STOCK_DB': '/tmp/stale.db'},
        require_pg=True,
        default_db_path='/tmp/default.db',
    )

    assert resolved == '/tmp/default.db'


def test_post_sync_validate_writes_ready_false_when_no_valid_trade_date(monkeypatch, tmp_path):
    module = _load_update_tencent(monkeypatch, tmp_path)
    db_path = tmp_path / 'health.db'
    conn = sqlite3.connect(db_path)
    conn.execute(
        '''
        CREATE TABLE kline_daily (
            symbol TEXT NOT NULL,
            trade_date TEXT NOT NULL,
            open REAL,
            close REAL,
            high REAL,
            low REAL,
            volume REAL,
            amount REAL,
            chg REAL,
            chg_pct REAL,
            ma20 REAL,
            rsi14 REAL,
            boll_lower REAL
        )
        '''
    )
    conn.execute(
        '''
        CREATE TABLE daily_valuation (
            symbol TEXT,
            trade_date TEXT,
            pe_ttm REAL,
            pb REAL
        )
        '''
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(module, 'DB_TARGET', str(db_path), raising=False)
    monkeypatch.setattr(module, 'DB_PATH', str(db_path), raising=False)
    monkeypatch.setattr(module, 'DB_IS_POSTGRES', False, raising=False)
    monkeypatch.setattr(module, 'TODAY', '2026-05-15', raising=False)
    monkeypatch.setattr(module, 'MIN_STOCKS', 4000, raising=False)
    monkeypatch.setattr(module, 'VALID_LOOKBACK_DAYS', 10, raising=False)
    monkeypatch.setattr(module, 'READY_FLAG', str(tmp_path / 'stock_data_ready.flag'), raising=False)
    monkeypatch.setattr(module, 'FETCH_STATS', {'kline': {}, 'quote': {}}, raising=False)

    status_path = tmp_path / 'stock_sync_status.json'
    alert_path = tmp_path / 'stock_sync_alert.txt'

    original_write_sync_status = module.write_sync_status

    def write_sync_status_with_temp_path(payload, path=None):
        return original_write_sync_status(payload, path=str(status_path))

    original_open = open

    def patched_open(file, mode='r', *args, **kwargs):
        if file == '/tmp/stock_sync_alert.txt':
            file = str(alert_path)
        return original_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(module, 'write_sync_status', write_sync_status_with_temp_path, raising=False)
    monkeypatch.setattr('builtins.open', patched_open)

    ok, target_date = module.post_sync_validate()

    assert ok is False
    assert target_date is None
    saved = sync_health.read_sync_status(path=str(status_path))
    assert saved['ready'] is False
    assert saved['target_date'] is None
    assert saved['today_kline_count'] == 0
    assert saved['validation_errors']
    assert alert_path.exists()
