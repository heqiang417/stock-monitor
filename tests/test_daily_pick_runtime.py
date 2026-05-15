import importlib
import subprocess
import sys
import types
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = PROJECT_ROOT / 'scripts' / 'daily'
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))


def _load_daily_pick(monkeypatch, tmp_path, runtime_python=None):
    runtime_python = runtime_python or sys.executable
    module = types.SimpleNamespace()
    module.UPDATE_TENCENT = '/fake/update_tencent.py'
    module.DAILY_SYNC = '/fake/daily_sync.py'
    module.SCRIPT_DIR = str(tmp_path)
    module.os = types.SimpleNamespace(path=types.SimpleNamespace(exists=lambda path: True, basename=lambda path: Path(path).name))
    module.subprocess = types.SimpleNamespace(run=None, TimeoutExpired=subprocess.TimeoutExpired)

    source = Path(PROJECT_ROOT / 'scripts' / 'daily' / 'daily_pick_combined.py').read_text(encoding='utf-8')
    start = source.index('def try_repair_before_pick')
    end = source.index('    return repaired_tencent or repaired_extended') + len('    return repaired_tencent or repaired_extended')
    function_code = source[start:end]
    exec(function_code, {
        'os': module.os,
        'subprocess': module.subprocess,
        'get_runtime_python': lambda: runtime_python,
        'UPDATE_TENCENT': module.UPDATE_TENCENT,
        'DAILY_SYNC': module.DAILY_SYNC,
        'SCRIPT_DIR': module.SCRIPT_DIR,
        '__builtins__': __builtins__,
    }, module.__dict__)
    return module


def test_try_repair_before_pick_uses_runtime_python_for_both_subprocesses(monkeypatch, tmp_path):
    runtime_python = tmp_path / 'runtime-python'
    runtime_python.write_text('#!/bin/sh\n', encoding='utf-8')
    module = _load_daily_pick(monkeypatch, tmp_path, runtime_python=str(runtime_python))

    monkeypatch.setattr(module.os.path, 'exists', lambda path: True)

    calls = []

    class Result:
        returncode = 0
        stdout = ''
        stderr = ''

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return Result()

    monkeypatch.setattr(module.subprocess, 'run', fake_run)

    repaired = module.try_repair_before_pick('2026-05-15')

    assert repaired is True
    assert calls[0][0] == str(runtime_python)
    assert calls[0][1] == module.UPDATE_TENCENT
    assert calls[1][0] == str(runtime_python)
    assert calls[1][1] == module.DAILY_SYNC
