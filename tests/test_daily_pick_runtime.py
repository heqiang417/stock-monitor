import subprocess
import sys
import types
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = PROJECT_ROOT / 'scripts' / 'daily'
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))


def _load_function(function_name: str, extra_globals=None):
    source = Path(PROJECT_ROOT / 'scripts' / 'daily' / 'daily_pick_combined.py').read_text(encoding='utf-8')
    marker = f'def {function_name}'
    start = source.index(marker)
    rest = source[start:]
    next_def = rest.find('\ndef ', 1)
    function_code = rest if next_def == -1 else rest[:next_def]

    namespace = {'__builtins__': __builtins__}
    if extra_globals:
        namespace.update(extra_globals)
    exec(function_code, namespace)
    return namespace[function_name]


def _load_daily_pick(monkeypatch, tmp_path, runtime_python=None, require_pg=True, db_env=None, stock_db=None):
    runtime_python = runtime_python or sys.executable
    module = types.SimpleNamespace()
    module.UPDATE_TENCENT = '/fake/update_tencent.py'
    module.DAILY_SYNC = '/fake/daily_sync.py'
    module.SCRIPT_DIR = str(tmp_path)
    module.REQUIRE_PG = require_pg
    environ = {}
    if db_env:
        environ.update(db_env)
    if stock_db is not None:
        environ['STOCK_DB'] = stock_db
    module.os = types.SimpleNamespace(
        environ=environ,
        path=types.SimpleNamespace(exists=lambda path: True, basename=lambda path: Path(path).name),
    )
    module.subprocess = types.SimpleNamespace(run=None, TimeoutExpired=subprocess.TimeoutExpired)

    source = Path(PROJECT_ROOT / 'scripts' / 'daily' / 'daily_pick_combined.py').read_text(encoding='utf-8')
    get_runtime_env_start = source.index('def get_runtime_env')
    function_block = source[get_runtime_env_start:]
    end_marker = '    return repaired_tencent or repaired_extended'
    end = function_block.index(end_marker) + len(end_marker)
    function_code = function_block[:end]
    exec(function_code, {
        'os': module.os,
        'subprocess': module.subprocess,
        'get_runtime_python': lambda: runtime_python,
        'UPDATE_TENCENT': module.UPDATE_TENCENT,
        'DAILY_SYNC': module.DAILY_SYNC,
        'SCRIPT_DIR': module.SCRIPT_DIR,
        'REQUIRE_PG': module.REQUIRE_PG,
        '__builtins__': __builtins__,
    }, module.__dict__)
    module.get_runtime_env.__globals__['get_runtime_env'] = module.get_runtime_env
    module.try_repair_before_pick.__globals__['get_runtime_env'] = module.get_runtime_env
    return module


def test_try_repair_before_pick_uses_runtime_python_for_both_subprocesses(monkeypatch, tmp_path):
    runtime_python = tmp_path / 'runtime-python'
    runtime_python.write_text('#!/bin/sh\n', encoding='utf-8')
    module = _load_daily_pick(
        monkeypatch,
        tmp_path,
        runtime_python=str(runtime_python),
        require_pg=True,
        db_env={'POSTGRES_DSN': 'postgresql://user:pass@localhost/db'},
        stock_db='/tmp/stale.db',
    )

    monkeypatch.setattr(module.os.path, 'exists', lambda path: True)

    calls = []

    class Result:
        returncode = 0
        stdout = ''
        stderr = ''

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return Result()

    monkeypatch.setattr(module.subprocess, 'run', fake_run)

    repaired = module.try_repair_before_pick('2026-05-15')

    assert repaired is True
    first_cmd, first_kwargs = calls[0]
    second_cmd, second_kwargs = calls[1]
    assert first_cmd[0] == str(runtime_python)
    assert first_cmd[1] == module.UPDATE_TENCENT
    assert first_cmd[2:] == ['--no-weekly', '--no-monthly']
    assert second_cmd[0] == str(runtime_python)
    assert second_cmd[1] == module.DAILY_SYNC
    assert first_kwargs['env']['RUNTIME_PYTHON'] == str(runtime_python)
    assert second_kwargs['env']['RUNTIME_PYTHON'] == str(runtime_python)
    assert 'STOCK_DB' not in first_kwargs['env']
    assert 'STOCK_DB' not in second_kwargs['env']
    assert first_kwargs['env']['POSTGRES_DSN'] == 'postgresql://user:pass@localhost/db'


def test_get_runtime_env_keeps_stock_db_without_postgres_env(monkeypatch, tmp_path):
    runtime_python = tmp_path / 'runtime-python'
    runtime_python.write_text('#!/bin/sh\n', encoding='utf-8')
    module = _load_daily_pick(
        monkeypatch,
        tmp_path,
        runtime_python=str(runtime_python),
        require_pg=False,
        stock_db='/tmp/sqlite.db',
    )

    runtime_env = module.get_runtime_env()

    assert runtime_env['RUNTIME_PYTHON'] == str(runtime_python)
    assert runtime_env['STOCK_DB'] == '/tmp/sqlite.db'


def test_normalize_date_str_accepts_date_objects():
    import datetime as dt

    normalize_date_str = _load_function(
        'normalize_date_str',
        extra_globals={'datetime': dt.datetime},
    )

    assert normalize_date_str(dt.date(2026, 5, 8)) == '2026-05-08'
    assert normalize_date_str(dt.datetime(2026, 5, 8, 12, 30, 0)) == '2026-05-08'
