#!/usr/bin/env python3
"""Offline factor-library checks (KD1-H §4.1): sandbox + pre-fill coverage/degeneracy."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[3]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from faultevolve.discovery.baseline_features import build_baseline_features
from faultevolve.discovery.factors import code_sha256, load_factor_library
from faultevolve.discovery.sandbox import _static_check
from faultevolve.tasks.hdd_adapter import HDDAdapter, HDD_K0_COLUMNS
from faultevolve.tasks.protocol import TaskSpec

# Same subprocess runner as sandbox, but no coverage / constant validation.
_RAW_RUNNER = r"""
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
        print("feature() not defined", file=sys.stderr)
        sys.exit(2)
    result = feature(history)
    if not isinstance(result, pd.Series):
        print("feature() must return pandas.Series", file=sys.stderr)
        sys.exit(3)
    result.to_csv("out.csv", header=["value"])
except Exception:
    traceback.print_exc()
    sys.exit(1)
"""

SUBGROUP_COL = {
    "HDD3_S01": "smart_191_raw",
    "HDD3_S02": "smart_240_raw",
    "HDD3_S03": "smart_241_raw",
    "HDD3_D01": "smart_191_raw",
    "HDD3_D02": "smart_240_raw",
    "HDD3_D03": "smart_241_raw",
}

OLD_FORBIDDEN_IDS = {
    "HDD2_F001",
    "HDD2_F002",
    "HDD2_F007",
    "HDD2_F008",
    "HDD2_F009",
    "HDD2_F010",
    "HDD2_F012",
    "HDD2_F014",
    "HDD2_F020",
}


def _mode_fraction(series: pd.Series) -> float:
    s = series.replace([np.inf, -np.inf], np.nan).dropna()
    if s.empty:
        return 1.0
    vc = s.value_counts(normalize=True)
    return float(vc.iloc[0])


def _subgroup_membership(history: pd.DataFrame, col: str, units: pd.Index) -> pd.Series:
    if col not in history.columns:
        return pd.Series(0.0, index=units.astype(str))
    mem = history.groupby("serial_number", group_keys=False)[col].apply(lambda s: bool(s.notna().any()))
    mem.index = mem.index.astype(str)
    return mem.reindex(units.astype(str)).fillna(0.0).astype(float)


def sandbox_ok_from_series(series: pd.Series) -> tuple[bool, str]:
    """Mirror post-exec validation in discovery/sandbox.run_feature (without subprocess)."""
    s = series.replace([np.inf, -np.inf], np.nan)
    coverage = float(s.notna().mean())
    if coverage < 0.8:
        return False, "low_coverage"
    if s.dropna().nunique() <= 1:
        return False, "constant"
    return True, ""


def raw_feature_series(
    code: str,
    history: pd.DataFrame,
    expected_units: pd.Index,
    timeout_s: int = 120,
) -> tuple[pd.Series | None, str]:
    err = _static_check(code)
    if err:
        return None, err
    import os
    import subprocess

    workdir = tempfile.mkdtemp()
    try:
        feature_path = Path(workdir) / "feature.py"
        feature_path.write_text(code, encoding="utf-8")
        hist_path = Path(workdir) / "history.pkl"
        history.to_pickle(hist_path)
        proc = subprocess.run(
            [sys.executable, "-c", _RAW_RUNNER],
            cwd=workdir,
            timeout=timeout_s,
            capture_output=True,
            env={
                "PATH": os.environ.get("PATH", ""),
                "PYTHONHASHSEED": "0",
                "OMP_NUM_THREADS": "1",
            },
        )
        if proc.returncode != 0:
            tail = proc.stderr.decode(errors="replace")[-800:]
            return None, tail or f"exit {proc.returncode}"
        out_path = Path(workdir) / "out.csv"
        df = pd.read_csv(out_path, index_col=0)
        series = df["value"].replace([np.inf, -np.inf], np.nan)
        series.index = series.index.astype(str)
        return series.reindex(expected_units.astype(str)), ""
    except subprocess.TimeoutExpired:
        return None, "timeout"
    except Exception as exc:
        return None, str(exc)


def load_discovery_history(task_dir: Path) -> tuple[pd.DataFrame, pd.Index, str]:
    adapter = HDDAdapter()
    spec = TaskSpec(
        task_dir=task_dir,
        problem_md="",
        prompt_md="",
        init_code="",
        evaluator_path=task_dir / "evaluator.py",
    )
    frames = adapter.discovery_frames(spec)
    units = frames.labels["serial_number"].astype(str)
    return frames.history, units, frames.unit_col


def prior_library_hashes(repo: Path, current: Path | None = None) -> set[str]:
    out: set[str] = set()
    for name in ("hdd_v1.jsonl", "hdd_v2.jsonl", "hdd_v3.jsonl"):
        path = repo / "src/faultevolve/discovery/factor_library" / name
        if not path.exists() or (current is not None and path.resolve() == current.resolve()):
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            data = json.loads(line)
            out.add(code_sha256(str(data.get("code", ""))))
    return out


def _max_abs_spearman(series: pd.Series, baseline: pd.DataFrame) -> float:
    """Maximum absolute Spearman correlation with finite, non-constant K0 columns."""
    if baseline.empty:
        return 0.0
    joined = baseline.reindex(series.index.astype(str)).copy()
    joined["__candidate__"] = series.to_numpy()
    corr = joined.corr(method="spearman", numeric_only=True)["__candidate__"].drop(
        labels=["__candidate__"], errors="ignore"
    )
    finite = corr.replace([np.inf, -np.inf], np.nan).dropna().abs()
    return float(finite.max()) if not finite.empty else 0.0


def _permute_values_within_units(history: pd.DataFrame, unit_col: str) -> pd.DataFrame:
    """Deterministically permute values while keeping each unit's calendar axis fixed."""
    out = history.copy()
    fixed = {unit_col, "date", "model"}
    value_cols = [c for c in out.columns if c not in fixed]
    rng = np.random.default_rng(20261004)
    for _, idx in out.groupby(unit_col, sort=False).groups.items():
        ordered = out.loc[idx].sort_values("date").index
        # A pure reversal cannot distinguish reversal-symmetric order statistics
        # such as max(abs(diff)) and sign-flip count.
        source = rng.permutation(len(ordered))
        out.loc[ordered, value_cols] = out.loc[ordered[source], value_cols].to_numpy()
    return out


def _synthetic_order_history(columns: pd.Index) -> pd.DataFrame:
    base = np.array([0.0, 1.0, 4.0, 2.0, 9.0, 3.0, 8.0, 5.0])
    rows: list[dict[str, Any]] = []
    for unit, offset in (("SYN_A", 0.0), ("SYN_B", 11.0)):
        for i, value in enumerate(base):
            row: dict[str, Any] = {
                "serial_number": unit,
                "date": f"2024-01-{i + 1:02d}",
                "model": "SYN_MODEL",
            }
            for j, col in enumerate(columns):
                if col.startswith("smart_"):
                    row[col] = float((value + 1.0) ** (1 + j % 2) + offset + (i % (j % 3 + 1)))
            rows.append(row)
    return pd.DataFrame(rows)


def evaluate_row(
    factor_id: str,
    lane: str,
    code: str,
    history: pd.DataFrame,
    units: pd.Index,
    unit_col: str,
    timeout_s: int,
    baseline: pd.DataFrame | None = None,
    check_order_sensitivity: bool = False,
) -> dict[str, Any]:
    row: dict[str, Any] = {"factor_id": factor_id, "lane": lane, "ok": False, "reasons": []}
    series, err = raw_feature_series(code, history, units, timeout_s=timeout_s)
    if series is None:
        row["reasons"].append(f"exec: {err[:200]}")
        return row
    static_err = _static_check(code)
    if static_err:
        row["reasons"].append(f"static: {static_err[:200]}")
        return row
    sb_ok, sb_msg = sandbox_ok_from_series(series)
    row["sandbox_ok"] = sb_ok
    if not sb_ok:
        row["reasons"].append(f"sandbox: {sb_msg}")
    coverage = float(series.notna().mean())
    nunique = int(series.dropna().nunique())
    mode_frac = _mode_fraction(series)
    row["prefill_coverage"] = round(coverage, 4)
    row["nunique"] = nunique
    row["mode_fraction"] = round(mode_frac, 4)
    if baseline is not None:
        rho_k0 = _max_abs_spearman(series, baseline)
        row["rhoK0"] = round(rho_k0, 4)
        if lane == "confirm" and rho_k0 >= 0.8:
            row["reasons"].append(f"rhoK0 {rho_k0:.4f} >= 0.8")
    if check_order_sensitivity:
        order_history = _synthetic_order_history(history.columns)
        order_units = pd.Index(["SYN_A", "SYN_B"])
        original_series, original_err = raw_feature_series(
            code, order_history, order_units, timeout_s=timeout_s
        )
        permuted_history = _permute_values_within_units(order_history, unit_col)
        permuted_series, permutation_err = raw_feature_series(
            code, permuted_history, order_units, timeout_s=timeout_s
        )
        changed = False
        if original_series is not None and permuted_series is not None:
            both = original_series.notna() & permuted_series.notna()
            changed = bool(
                both.any()
                and not np.allclose(
                    original_series[both].to_numpy(dtype=float),
                    permuted_series[both].to_numpy(dtype=float),
                    equal_nan=True,
                )
            )
        row["order_sensitive"] = changed
        if original_series is None:
            row["reasons"].append(f"original synthetic exec: {original_err[:200]}")
        elif permuted_series is None:
            row["reasons"].append(f"permutation exec: {permutation_err[:200]}")
        elif not changed:
            row["reasons"].append("order sensitivity check found no changed unit")

    if factor_id.startswith("HDD3_D"):
        col = SUBGROUP_COL[factor_id]
        mem = _subgroup_membership(history, col, units)
        group_frac = float(mem.mean())
        row["group_fraction"] = round(group_frac, 4)
        uniq = set(float(x) for x in series.dropna().unique())
        if not (0.30 <= group_frac <= 0.80):
            row["reasons"].append(f"group_fraction {group_frac:.4f} not in [0.30,0.80]")
        if not uniq.issubset({0.0, 1.0}) or len(uniq) < 2:
            row["reasons"].append(f"indicator values {uniq} not binary 0/1")
    elif factor_id.startswith("HDD3_S"):
        col = SUBGROUP_COL[factor_id]
        mem = _subgroup_membership(history, col, units)
        group_frac = float(mem.mean())
        row["group_fraction"] = round(group_frac, 4)
        in_group = mem > 0.5
        inner = series[in_group]
        inner_cov = float(inner.notna().mean()) if in_group.any() else 0.0
        row["in_group_coverage"] = round(inner_cov, 4)
        row["in_group_nunique"] = int(inner.dropna().nunique()) if in_group.any() else 0
        row["in_group_mode_fraction"] = round(_mode_fraction(inner), 4) if in_group.any() else 1.0
        if not (0.30 <= group_frac <= 0.80):
            row["reasons"].append(f"group_fraction {group_frac:.4f} not in [0.30,0.80]")
        if inner_cov < 0.999:
            row["reasons"].append(f"in_group_coverage {inner_cov:.4f} != 1")
        if row["in_group_nunique"] < 10:
            row["reasons"].append(f"in_group_nunique {row['in_group_nunique']} < 10")
        if row["in_group_mode_fraction"] > 0.95:
            row["reasons"].append("in_group_mode_fraction > 0.95")
    elif factor_id == "HDD3_C01":
        if nunique <= 1:
            row["reasons"].append("nunique <= 1")
    elif factor_id == "HDD3_C02" or lane == "confirm":
        if coverage < 0.95:
            row["reasons"].append(f"coverage {coverage:.4f} < 0.95")
        if nunique < 10:
            row["reasons"].append(f"nunique {nunique} < 10")
        if mode_frac > 0.95:
            row["reasons"].append(f"mode_fraction {mode_frac:.4f} > 0.95")

    row["ok"] = not row["reasons"] and sb_ok
    return row


def check_library(
    library_path: Path,
    task_dir: Path,
    timeout_s: int = 120,
    family_prefix: str | None = None,
    order_sensitive_ids: set[str] | None = None,
) -> tuple[list[dict[str, Any]], bool]:
    entries = load_factor_library(library_path, max_candidates=30)
    history, units, unit_col = load_discovery_history(task_dir)
    prior = prior_library_hashes(REPO, library_path)
    baseline = None
    if family_prefix is not None:
        k0_cols = [c for c in HDD_K0_COLUMNS if c in history.columns]
        baseline = build_baseline_features(history, unit_col, "date", k0_cols, lag_rows=14)
        baseline.index = baseline.index.astype(str)
    seen: set[str] = set()
    rows: list[dict[str, Any]] = []
    all_ok = True
    for ent in entries:
        if family_prefix is not None and not ent.factor_id.startswith(family_prefix):
            all_ok = False
            rows.append(
                {"factor_id": ent.factor_id, "ok": False, "reasons": [f"id lacks prefix {family_prefix}"]}
            )
            continue
        if ent.factor_id in OLD_FORBIDDEN_IDS:
            all_ok = False
            rows.append(
                {
                    "factor_id": ent.factor_id,
                    "ok": False,
                    "reasons": ["reuses forbidden old id"],
                }
            )
            continue
        ch = code_sha256(ent.code)
        if ch in seen:
            all_ok = False
            rows.append({"factor_id": ent.factor_id, "ok": False, "reasons": ["duplicate hash in library"]})
            continue
        seen.add(ch)
        if ch in prior:
            all_ok = False
            rows.append({"factor_id": ent.factor_id, "ok": False, "reasons": ["code hash matches v1/v2"]})
            continue
        row = evaluate_row(
            ent.factor_id,
            ent.lane,
            ent.code,
            history,
            units,
            unit_col,
            timeout_s,
            baseline=baseline,
            check_order_sensitivity=bool(order_sensitive_ids and ent.factor_id in order_sensitive_ids),
        )
        rows.append(row)
        if not row.get("ok"):
            all_ok = False
    return rows, all_ok


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline HDD factor library validation (KD1-H §4.1)")
    parser.add_argument(
        "--library",
        type=Path,
        default=REPO / "src/faultevolve/discovery/factor_library/hdd_v3.jsonl",
    )
    parser.add_argument(
        "--task-dir",
        type=Path,
        default=REPO / "benchmark/hdd_mvp",
    )
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument(
        "--family-prefix",
        default=None,
        help="Require factor ids to use this prefix and add rhoK0 checks.",
    )
    parser.add_argument(
        "--order-sensitive",
        default=None,
        help="Comma-separated ids/ranges are not expanded; use 'HDD4' for KD1-I F01-F18,F21.",
    )
    parser.add_argument("--json-out", type=Path, default=None)
    args = parser.parse_args()
    lib = args.library.resolve()
    if not lib.exists():
        print(f"library not found: {lib}", file=sys.stderr)
        return 2
    order_ids: set[str] | None = None
    if args.order_sensitive:
        if args.order_sensitive == "HDD4":
            order_ids = {
                *(f"HDD4_F{i:02d}" for i in range(1, 19)),
                "HDD4_F21",
                "HDD4_F22",
            }
        else:
            order_ids = {x.strip() for x in args.order_sensitive.split(",") if x.strip()}
    rows, ok = check_library(
        lib,
        args.task_dir.resolve(),
        timeout_s=args.timeout,
        family_prefix=args.family_prefix,
        order_sensitive_ids=order_ids,
    )
    payload = {
        "library": str(lib),
        "library_sha256": file_sha256(lib),
        "ok": ok,
        "rows": rows,
    }
    text = json.dumps(payload, indent=2, ensure_ascii=False)
    if args.json_out:
        args.json_out.write_text(text, encoding="utf-8")
    print(text)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
