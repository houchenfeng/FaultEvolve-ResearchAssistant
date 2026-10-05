"""HDD failure-prediction evaluator (shared by FaultEvolve and Baidu Famou).

Interface follows the Famou adapter contract:

    evaluate(path_user_py, task_name="default", timeout=900) -> {
        "validity", "combined_score", "cost_time", "error_info", "metric"
    }

Candidate I/O contract (see problem.md):

    python <candidate.py> --data-dir <abs dir> --split <val|test> --out <abs csv>

The candidate writes a CSV with columns serial_number, score, alarm.

combined_score (higher is better, 0 when invalid) is the Robust Operational Score:

    ROS = 100 * (0.5 * F1_p10 + 0.3 * AUPRC + 0.2 * R@FAR) * time_factor

    F1_p10       10th percentile of fleet-weighted F1 over stratified bootstrap
                 resamples, so a lucky threshold on a noisy split is not rewarded
    AUPRC        fleet-weighted average precision of `score`
    R@FAR        recall achievable by `score` while falsely alarming at most
                 FAR_BUDGET of healthy disks
    time_factor  min(1, TIME_BUDGET_S / cost_time)

Command line:
    python evaluator.py <candidate.py> [--split val|test]
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
DATA_ROOT = Path(os.environ.get("HDD_BENCH_DATA_ROOT", HERE / "data")).resolve()

# Search order supports both the repo layout (data/public, data/eval_only) and a flat
# upload where every file sits next to evaluator.py (e.g. the Famou web console).
SEARCH_DIRS = {
    "val": {
        "public": [DATA_ROOT / "public", DATA_ROOT, HERE],
        "labels": [DATA_ROOT / "eval_only", DATA_ROOT, HERE],
    },
    "test": {
        "public": [DATA_ROOT / "holdout"],
        "labels": [DATA_ROOT / "holdout_labels"],
    },
}
LABEL_FILE = {"val": "val_labels.csv", "test": "test_labels.csv"}

TIME_BUDGET_S = 600.0
FAR_BUDGET = 0.002
N_BOOTSTRAP = 200
BOOTSTRAP_SEED = 20260926
WEIGHTS = {"f1_p10": 0.5, "auprc": 0.3, "recall_at_far": 0.2}

PUBLIC_FILES = {
    "val": ["train_history.csv.gz", "train_labels.csv", "val_history.csv.gz", "val_index.csv"],
    "test": ["train_history.csv.gz", "train_labels.csv", "test_history.csv.gz", "test_index.csv"],
}

# Candidates may only open the documented files inside --data-dir. Anything that could
# reach evaluator-only answers (path climbing, directory listing, cwd tricks) is rejected.
FORBIDDEN_PATTERNS = {
    "evaluator-only path": r"eval_only|holdout|val_labels|test_labels",
    "path climbing": r"\.parent\b|\.\./|\.\.\\|os\.pardir|\bparents\[",
    "directory listing": r"\blistdir\b|os\.walk|\bglob\b|\bscandir\b|\biterdir\b|rglob",
    "working-directory access": r"getcwd|Path\.cwd|\bchdir\b",
    "process/network escape": r"\bsubprocess\b|os\.system|\bsocket\b|urllib|requests\b|http\.client",
}


def locate_split(split: str) -> tuple[dict[str, Path], Path] | tuple[None, str]:
    """Return ({public file name: path}, labels path) or (None, error message)."""
    public: dict[str, Path] = {}
    for name in PUBLIC_FILES[split]:
        found = next((d / name for d in SEARCH_DIRS[split]["public"] if (d / name).exists()), None)
        if found is None:
            return None, f"data file '{name}' for split '{split}' not found"
        public[name] = found
    labels = next((d / LABEL_FILE[split] for d in SEARCH_DIRS[split]["labels"] if (d / LABEL_FILE[split]).exists()), None)
    if labels is None:
        return None, f"labels for split '{split}' not available on this machine"
    return public, labels


def _result(validity: float, score: float, cost: float, error: str, metric: dict | None = None) -> dict:
    return {
        "validity": float(validity),
        "combined_score": float(score),
        "cost_time": float(cost),
        "error_info": error,
        "metric": metric or {},
    }


def static_check(source: str) -> str:
    """Reject candidates that could reach evaluator-only material."""
    for lineno, line in enumerate(source.splitlines(), 1):
        code = line.split("#", 1)[0]
        for reason, pat in FORBIDDEN_PATTERNS.items():
            if re.search(pat, code):
                return f"{reason} (line {lineno}): {code.strip()[:120]}"
    return ""


def weighted_confusion(y: np.ndarray, alarm: np.ndarray, w: np.ndarray) -> tuple[float, float, float, float]:
    tp = float(np.sum(w * (y == 1) * (alarm == 1)))
    fp = float(np.sum(w * (y == 0) * (alarm == 1)))
    fn = float(np.sum(w * (y == 1) * (alarm == 0)))
    tn = float(np.sum(w * (y == 0) * (alarm == 0)))
    return tp, fp, fn, tn


def f1_from_counts(tp: np.ndarray, fp: np.ndarray, fn: np.ndarray) -> np.ndarray:
    denom = 2 * tp + fp + fn
    return np.where(denom > 0, 2 * tp / np.maximum(denom, 1e-12), 0.0)


def weighted_auprc(y: np.ndarray, score: np.ndarray, w: np.ndarray) -> float:
    order = np.argsort(-score, kind="mergesort")
    y, s, w = y[order], score[order], w[order]
    tp_cum = np.cumsum(w * y)
    fp_cum = np.cumsum(w * (1 - y))
    last_of_tie = np.r_[s[1:] != s[:-1], True]
    tp_cum, fp_cum = tp_cum[last_of_tie], fp_cum[last_of_tie]
    total_pos = tp_cum[-1]
    if total_pos <= 0:
        return 0.0
    precision = tp_cum / np.maximum(tp_cum + fp_cum, 1e-12)
    recall = tp_cum / total_pos
    recall_prev = np.r_[0.0, recall[:-1]]
    return float(np.sum((recall - recall_prev) * precision))


def recall_at_far(y: np.ndarray, score: np.ndarray, w: np.ndarray, far_budget: float) -> float:
    order = np.argsort(-score, kind="mergesort")
    y, s, w = y[order], score[order], w[order]
    tp_cum = np.cumsum(w * y)
    fp_cum = np.cumsum(w * (1 - y))
    last_of_tie = np.r_[s[1:] != s[:-1], True]
    tp_cum, fp_cum = tp_cum[last_of_tie], fp_cum[last_of_tie]
    total_pos, total_neg = tp_cum[-1], fp_cum[-1]
    ok = fp_cum / max(total_neg, 1e-12) <= far_budget
    return float(tp_cum[ok].max() / total_pos) if ok.any() and total_pos > 0 else 0.0


def bootstrap_f1(y: np.ndarray, alarm: np.ndarray, w: np.ndarray) -> np.ndarray:
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    pos, neg = np.flatnonzero(y == 1), np.flatnonzero(y == 0)
    f1s = np.empty(N_BOOTSTRAP)
    for b in range(N_BOOTSTRAP):
        idx = np.concatenate([rng.choice(pos, pos.size), rng.choice(neg, neg.size)])
        tp, fp, fn, _ = weighted_confusion(y[idx], alarm[idx], w[idx])
        f1s[b] = f1_from_counts(np.array(tp), np.array(fp), np.array(fn))
    return f1s


def score_predictions(pred: pd.DataFrame, labels: pd.DataFrame) -> tuple[float, dict]:
    df = labels.merge(pred, on="serial_number", how="left")
    y = df["label"].to_numpy(dtype=int)
    w = df["weight"].to_numpy(dtype=float)
    score = df["score"].to_numpy(dtype=float)
    alarm = df["alarm"].to_numpy(dtype=int)

    tp, fp, fn, tn = weighted_confusion(y, alarm, w)
    precision = tp / (tp + fp) if tp + fp > 0 else 0.0
    recall = tp / (tp + fn) if tp + fn > 0 else 0.0
    f1 = float(f1_from_counts(np.array(tp), np.array(fp), np.array(fn)))
    f1_boot = bootstrap_f1(y, alarm, w)
    auprc = weighted_auprc(y, score, w)
    r_far = recall_at_far(y, score, w, FAR_BUDGET)
    quality = (WEIGHTS["f1_p10"] * float(np.percentile(f1_boot, 10))
               + WEIGHTS["auprc"] * auprc
               + WEIGHTS["recall_at_far"] * r_far)
    metric = {
        "precision": round(precision, 5),
        "recall": round(recall, 5),
        "f1": round(f1, 5),
        "f1_p10": round(float(np.percentile(f1_boot, 10)), 5),
        "f1_boot_std": round(float(f1_boot.std()), 5),
        "auprc": round(auprc, 5),
        "recall_at_far": round(r_far, 5),
        "false_alarm_rate": round(fp / (fp + tn), 6) if fp + tn > 0 else 0.0,
        "missed_detection_rate": round(fn / (tp + fn), 5) if tp + fn > 0 else 0.0,
        "alarms_per_1k_disks": round(1000 * (tp + fp) / (tp + fp + fn + tn), 3),
        "quality": round(quality, 5),
    }
    return quality, metric


def validate_output(out_path: Path, index: pd.DataFrame) -> tuple[pd.DataFrame | None, str]:
    if not out_path.exists():
        return None, "candidate did not write the output csv"
    try:
        pred = pd.read_csv(out_path)
    except Exception as exc:  # noqa: BLE001
        return None, f"output csv unreadable: {exc}"
    missing_cols = {"serial_number", "score", "alarm"} - set(pred.columns)
    if missing_cols:
        return None, f"output csv missing columns: {sorted(missing_cols)}"
    pred = pred[["serial_number", "score", "alarm"]]
    if pred["serial_number"].duplicated().any():
        return None, "duplicate serial_number rows in output"
    expected = set(index["serial_number"])
    got = set(pred["serial_number"])
    if expected - got:
        return None, f"{len(expected - got)} query disks have no prediction"
    if got - expected:
        return None, f"{len(got - expected)} predicted disks are not in the query index"
    score = pd.to_numeric(pred["score"], errors="coerce")
    if not np.isfinite(score).all():
        return None, "score contains NaN/inf or non-numeric values"
    if not pred["alarm"].isin([0, 1]).all():
        return None, "alarm must be 0 or 1"
    pred = pred.assign(score=score.astype(float), alarm=pred["alarm"].astype(int))
    return pred, ""


def evaluate(path_user_py: str, task_name: str = "default", timeout: int = 900, split: str = "val") -> dict:
    start = time.time()
    candidate = Path(path_user_py).resolve()
    if not candidate.exists():
        return _result(0, 0, 0, f"candidate not found: {candidate}")
    if split not in SEARCH_DIRS:
        return _result(0, 0, 0, f"unknown split {split}")
    public_files, labels_path = locate_split(split)
    if public_files is None:
        return _result(0, 0, 0, labels_path)

    violation = static_check(candidate.read_text(encoding="utf-8", errors="ignore"))
    if violation:
        return _result(0, 0, time.time() - start, f"static check failed: {violation}")

    index = pd.read_csv(public_files[f"{split}_index.csv"])
    labels = pd.read_csv(labels_path)

    with tempfile.TemporaryDirectory(prefix="hdd_eval_") as tmp:
        staging = Path(tmp) / "data"
        staging.mkdir()
        for name, src in public_files.items():
            shutil.copy2(src, staging / name)
        out_path = Path(tmp) / "pred.csv"
        cmd = [sys.executable, str(candidate), "--data-dir", str(staging), "--split", split, "--out", str(out_path)]
        t0 = time.time()
        try:
            proc = subprocess.run(cmd, cwd=str(HERE), capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return _result(0, 0, time.time() - start, f"timeout after {timeout}s")
        run_time = time.time() - t0
        if proc.returncode != 0:
            tail = (proc.stderr or proc.stdout or "")[-1500:]
            return _result(0, 0, run_time, f"candidate exited with code {proc.returncode}: {tail}")
        pred, err = validate_output(out_path, index)
        if err:
            return _result(0, 0, run_time, err)

    quality, metric = score_predictions(pred, labels)
    time_factor = min(1.0, TIME_BUDGET_S / max(run_time, 1e-6))
    metric.update({"run_time_s": round(run_time, 2), "time_factor": round(time_factor, 4), "split": split})
    return _result(1, 100.0 * quality * time_factor, run_time, "", metric)


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("candidate")
    ap.add_argument("--split", default="val", choices=sorted(SEARCH_DIRS))
    ap.add_argument("--timeout", type=int, default=900)
    a = ap.parse_args()
    print(json.dumps(evaluate(a.candidate, timeout=a.timeout, split=a.split), indent=2, ensure_ascii=False))
