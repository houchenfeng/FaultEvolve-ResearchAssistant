"""Tests for discovery feature sandbox."""

from __future__ import annotations

import pandas as pd

from faultevolve.discovery.sandbox import run_feature


def _history(n_units: int = 10) -> pd.DataFrame:
    rows = []
    for u in range(n_units):
        uid = f"u{u}"
        for t in range(5):
            rows.append({"unit": uid, "t": t, "m1": float(u + t)})
    return pd.DataFrame(rows)


def _units(n: int = 10) -> list[str]:
    return [f"u{i}" for i in range(n)]


def test_valid_feature_full_coverage():
    code = """
def feature(history):
    return history.groupby('unit')['m1'].last()
"""
    hist = _history()
    res = run_feature(code, hist, "unit", _units(), timeout_s=30)
    assert res.ok
    assert res.series is not None
    assert res.series.notna().mean() == 1.0


def test_static_reject_import_os():
    code = "import os\ndef feature(history):\n    return history.groupby('unit')['m1'].last()"
    res = run_feature(code, _history(), "unit", _units(), timeout_s=5)
    assert not res.ok


def test_static_reject_open():
    code = "def feature(history):\n    open('x')\n    return history.groupby('unit')['m1'].last()"
    res = run_feature(code, _history(), "unit", _units(), timeout_s=5)
    assert not res.ok


def test_static_reject_dunder_import():
    code = "def feature(history):\n    __import__('os')\n    return history.groupby('unit')['m1'].last()"
    res = run_feature(code, _history(), "unit", _units(), timeout_s=5)
    assert not res.ok


def test_static_reject_eval():
    code = "def feature(history):\n    eval('1')\n    return history.groupby('unit')['m1'].last()"
    res = run_feature(code, _history(), "unit", _units(), timeout_s=5)
    assert not res.ok


def test_timeout():
    code = "def feature(history):\n    while True:\n        pass\n    return history.groupby('unit')['m1'].last()"
    res = run_feature(code, _history(), "unit", _units(), timeout_s=2)
    assert not res.ok
    assert "timeout" in res.error


def test_constant_feature():
    code = (
        "def feature(history):\n"
        "    import pandas as pd\n"
        "    idx = history['unit'].unique()\n"
        "    return pd.Series(1.0, index=idx)"
    )
    res = run_feature(code, _history(), "unit", _units(), timeout_s=10)
    assert not res.ok
    assert res.error == "constant"


def test_low_coverage():
    code = """
def feature(history):
    import pandas as pd
    import numpy as np
    units = history['unit'].unique()
    vals = [float('nan')] * len(units)
    vals[0] = 1.0
    return pd.Series(vals, index=units)
"""
    res = run_feature(code, _history(), "unit", _units(), timeout_s=10)
    assert not res.ok
    assert res.error == "low_coverage"


def test_sandbox_workdir_isolated(monkeypatch):
    import subprocess
    from pathlib import Path

    captured_cwd: list[str] = []
    real_run = subprocess.run

    def _capture_run(*args, **kwargs):
        cwd = kwargs.get("cwd")
        if cwd:
            captured_cwd.append(str(cwd))
            names = {p.name for p in Path(cwd).iterdir()}
            assert "AGENTS.md" not in names
            assert "requirements.txt" not in names
        return real_run(*args, **kwargs)

    monkeypatch.setattr(subprocess, "run", _capture_run)
    code = """
def feature(history):
    return history.groupby('unit')['m1'].last()
"""
    hist = _history(3)
    res = run_feature(code, hist, "unit", _units(3), timeout_s=10)
    assert res.ok
    assert captured_cwd
    assert not captured_cwd[0].endswith("/workspace")


def test_stderr_tail_keeps_exception_line():
    code = """
def feature(history):
    def inner():
        def deeper():
            raise KeyError("needle_col")
        deeper()
    inner()
"""
    res = run_feature(code, _history(), "unit", _units(), timeout_s=30)
    assert not res.ok
    assert "needle_col" in res.error
    assert len(res.error) <= 800
    assert res.error_type == "SubprocessError"


def test_traceback_containing_word_timeout_is_not_timeout():
    code = """
def feature(history):
    raise ValueError("timeout-like message")
"""
    res = run_feature(code, _history(), "unit", _units(), timeout_s=10)
    assert not res.ok
    assert res.error_type == "SubprocessError"
    assert res.error_type != "TimeoutExpired"


def test_non_series_return_reports_type():
    code = """
def feature(history):
    return history.groupby('unit')[['m1']].last()
"""
    res = run_feature(code, _history(), "unit", _units(), timeout_s=30)
    assert not res.ok
    assert res.error_type == "SubprocessError"
    assert "DataFrame" in res.error
    assert "pandas.Series" in res.error
    assert res.error != "exit 3"


def test_missing_feature_reports_message():
    code = """
def feature(history):
    pass
feature = None
"""
    res = run_feature(code, _history(), "unit", _units(), timeout_s=10)
    assert not res.ok
    assert res.error != "exit 2"
    assert "feature" in res.error.lower()


def test_keyerror_traceback_preserved():
    code = """
def feature(history):
    return history.groupby('unit')['missing_col_xyz'].last()
"""
    res = run_feature(code, _history(), "unit", _units(), timeout_s=30)
    assert not res.ok
    assert "KeyError" in res.error
    assert "missing_col_xyz" in res.error


def test_silent_exit_reports_signal_or_no_stderr():
    code = """
def feature(history):
    raise SystemExit(5)
"""
    res = run_feature(code, _history(), "unit", _units(), timeout_s=10)
    assert not res.ok
    assert "exit 5" in res.error
    assert "no stderr" in res.error
