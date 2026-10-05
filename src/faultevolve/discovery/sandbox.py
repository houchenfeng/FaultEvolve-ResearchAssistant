"""Sandboxed execution of discovered feature code."""

from __future__ import annotations

import ast
import os
import resource
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import numpy as np
import pandas as pd

from faultevolve.common.codecheck import pattern_check, syntax_check

STDERR_TAIL_CHARS = 800

ALLOWED_IMPORT_ROOTS = {
    "numpy",
    "pandas",
    "math",
    "scipy",
    "statistics",
    "itertools",
    "functools",
    "collections",
}
FORBIDDEN_NAMES = {
    "open",
    "exec",
    "eval",
    "compile",
    "__import__",
    "input",
    "globals",
    "locals",
    "getattr",
    "setattr",
    "delattr",
    "vars",
    "breakpoint",
}
FORBIDDEN_ATTRS = {
    "read_csv",
    "to_csv",
    "read_parquet",
    "to_parquet",
    "read_pickle",
    "to_pickle",
    "read_sql",
    "read_json",
    "to_json",
}

_RUNNER = r"""
import pickle
import sys
import traceback
import pandas as pd

try:
    with open("history.pkl", "rb") as f:
        history = pickle.load(f)
    ns = {}
    exec(open("feature.py").read(), ns)
    feature = ns.get("feature")
    if feature is None:
        print("feature() not defined in feature.py", file=sys.stderr)
        sys.exit(2)
    result = feature(history)
    if not isinstance(result, pd.Series):
        t = type(result)
        msg = (
            f"feature() must return pandas.Series indexed by unit, "
            f"got {t.__module__}.{t.__qualname__}"
        )
        if isinstance(result, pd.DataFrame):
            cols = list(result.columns)[:5]
            msg += f" (shape={result.shape}, columns={cols})"
        elif hasattr(result, "__len__"):
            try:
                msg += f" (len={len(result)})"
            except TypeError:
                pass
        msg += " hint: use .squeeze() or .iloc[:, 0] for single-column DataFrame"
        print(msg, file=sys.stderr)
        sys.exit(3)
    result.to_csv("out.csv", header=["value"])
except Exception:
    traceback.print_exc()
    sys.exit(1)
"""


def tail_stderr(stderr: bytes, returncode: int) -> str:
    """Format subprocess stderr or a clear message when stderr is empty."""
    decoded = stderr.decode(errors="replace").strip()
    if decoded:
        if len(decoded) > STDERR_TAIL_CHARS:
            decoded = decoded[-STDERR_TAIL_CHARS:]
        return decoded
    sig = ""
    if returncode < 0:
        sig = f", signal {-returncode}"
    return f"exit {returncode} (no stderr{sig})"


@dataclass
class SandboxResult:
    ok: bool
    series: pd.Series | None
    error: str
    duration_s: float
    error_type: str = ""


class _SandboxVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.error: str = ""

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            root = alias.name.split(".")[0]
            if root not in ALLOWED_IMPORT_ROOTS:
                self.error = f"import not allowed: {alias.name}"
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module:
            root = node.module.split(".")[0]
            if root not in ALLOWED_IMPORT_ROOTS:
                self.error = f"import not allowed: {node.module}"
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if node.id in FORBIDDEN_NAMES:
            self.error = f"forbidden name: {node.id}"
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr.startswith("__") and node.attr.endswith("__"):
            self.error = "dunder attribute access forbidden"
        if node.attr in FORBIDDEN_ATTRS:
            self.error = f"forbidden attribute: {node.attr}"
        self.generic_visit(node)


def _static_check(code: str) -> str:
    err = syntax_check(code)
    if err:
        return err
    err = pattern_check(code)
    if err:
        return err
    if "def feature(" not in code:
        return "missing def feature("
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return str(e)
    visitor = _SandboxVisitor()
    visitor.visit(tree)
    return visitor.error


def run_feature(
    code: str,
    history: pd.DataFrame,
    unit_col: str,
    expected_units: Sequence,
    timeout_s: int,
) -> SandboxResult:
    t0 = time.time()
    err = _static_check(code)
    if err:
        return SandboxResult(False, None, err, time.time() - t0, "StaticCheck")
    workdir = tempfile.mkdtemp()
    try:
        feature_path = Path(workdir) / "feature.py"
        feature_path.write_text(code, encoding="utf-8")
        hist_path = Path(workdir) / "history.pkl"
        history.to_pickle(hist_path)
        env = {
            "PATH": os.environ.get("PATH", ""),
            "PYTHONHASHSEED": "0",
            "OMP_NUM_THREADS": "1",
        }
        preexec = None
        if hasattr(os, "setrlimit"):
            def _limit() -> None:
                resource.setrlimit(resource.RLIMIT_AS, (4 * 1024**3, 4 * 1024**3))

            preexec = _limit
        proc = subprocess.run(
            [sys.executable, "-c", _RUNNER],
            cwd=workdir,
            env=env,
            timeout=timeout_s,
            capture_output=True,
            preexec_fn=preexec,
        )
        if proc.returncode != 0:
            if proc.returncode == -9:
                return SandboxResult(
                    False,
                    None,
                    "killed by SIGKILL (timeout or out of memory)",
                    time.time() - t0,
                    "TimeoutExpired",
                )
            err_msg = tail_stderr(proc.stderr, proc.returncode)
            return SandboxResult(False, None, err_msg, time.time() - t0, "SubprocessError")
        out_path = Path(workdir) / "out.csv"
        if not out_path.exists():
            return SandboxResult(False, None, "no output", time.time() - t0, "SandboxFailure")
        df = pd.read_csv(out_path, index_col=0)
        if "value" not in df.columns:
            return SandboxResult(False, None, "bad output", time.time() - t0, "SandboxFailure")
        series = df["value"]
        series = series.replace([np.inf, -np.inf], np.nan)
        expected = pd.Index([str(u) for u in expected_units])
        series.index = series.index.astype(str)
        series = series.reindex(expected)
        coverage = series.notna().mean()
        if coverage < 0.8:
            return SandboxResult(False, None, "low_coverage", time.time() - t0, "ValidationError")
        if series.dropna().nunique() <= 1:
            return SandboxResult(False, None, "constant", time.time() - t0, "ValidationError")
        med = float(series.median(skipna=True))
        series = series.fillna(med)
        return SandboxResult(True, series, "", time.time() - t0)
    except subprocess.TimeoutExpired:
        return SandboxResult(False, None, "timeout", time.time() - t0, "TimeoutExpired")
    except Exception as e:
        return SandboxResult(
            False,
            None,
            f"{type(e).__name__}: {e}"[:200],
            time.time() - t0,
            type(e).__name__,
        )
    finally:
        try:
            for p in Path(workdir).iterdir():
                p.unlink(missing_ok=True)
            Path(workdir).rmdir()
        except OSError:
            pass
