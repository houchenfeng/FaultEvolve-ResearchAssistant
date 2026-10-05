"""Rebuild baseline metrics from run artifacts (read-only)."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

from faultevolve.optimization.candidate_spec import source_hash


def _load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _load_events(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    if not path.exists():
        return events
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                events.append(json.loads(line))
    return events


def compute_baseline_metrics(
    db_path: Path,
    *,
    events_path: Path | None = None,
    run_summary_path: Path | None = None,
) -> dict[str, Any]:
    """Compute metrics per E0 spec; missing data yields null + unknown_reason."""
    uri = f"file:{db_path.resolve()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    try:
        exp = conn.execute("SELECT id FROM experiment LIMIT 1").fetchone()
        experiment_id = exp["id"] if exp else None
        nodes = []
        if experiment_id:
            rows = conn.execute(
                "SELECT operator, artifact_json, evidence_json, status FROM node WHERE experiment_id=?",
                (experiment_id,),
            ).fetchall()
            nodes = [dict(r) for r in rows]
    finally:
        conn.close()

    events = _load_events(events_path) if events_path else []
    summary = _load_json(run_summary_path) if run_summary_path and run_summary_path.exists() else {}

    gen_ops = {
        "refine",
        "recall_focus",
        "threshold_calibrate",
        "inject",
        "crossover",
        "patch",
    }
    n_generation_requests = sum(
        1 for e in events if e.get("type") == "iteration_complete" and e.get("payload", {}).get("operator") in gen_ops
    )
    if n_generation_requests == 0:
        n_generation_requests = sum(
            1 for n in nodes if json.loads(n["operator"]) if False else n.get("operator") in gen_ops
        )

    reject_types = {
        "invalid_generation",
        "precheck_fix",
        "smoke_failed",
        "perf_rejected",
        "patch_rejected",
    }
    n_pre_eval_reject = sum(1 for e in events if e.get("type") in reject_types)

    valid_first = 0
    n_first_eval = 0
    hashes: set[str] = set()
    valid_nodes = 0
    positive_gain = 0
    sig_gain = 0
    for n in nodes:
        op = n.get("operator")
        if op == "init":
            continue
        artifact = json.loads(n["artifact_json"])
        code = artifact.get("code", "")
        ev = json.loads(n["evidence_json"] or "{}")
        evaluation = ev.get("evaluation") or {}
        validity = evaluation.get("validity", 0)
        if validity >= 1:
            valid_nodes += 1
            hashes.add(source_hash(code))
            delta = ev.get("delta_score")
            if delta is not None and delta > 0:
                positive_gain += 1
            noise = ev.get("noise_delta")
            if delta is not None and noise is not None and delta > noise:
                sig_gain += 1
        if op in gen_ops and evaluation:
            n_first_eval += 1
            if validity >= 1:
                valid_first += 1

    out: dict[str, Any] = {
        "n_generation_requests": n_generation_requests or None,
        "n_pre_eval_reject": n_pre_eval_reject,
        "n_first_eval": n_first_eval or None,
        "valid_rate_first_eval": (valid_first / n_first_eval) if n_first_eval else None,
        "gen_to_first_valid_rate": (valid_first / n_generation_requests) if n_generation_requests else None,
        "valid_rate_after_selffix": None,
        "valid_rate_after_repair": None,
        "positive_gain_rate": (positive_gain / valid_nodes) if valid_nodes else None,
        "significant_gain_rate": None,
        "significant_gain_note": "工程噪声门，不是父子 ROS 差的置信区间",
        "unique_candidate_rate": (len(hashes) / valid_nodes) if valid_nodes else None,
        "legacy_valid_rate": summary.get("valid_rate"),
        "legacy_valid_rate_denominator": "valid_count/(valid_count+invalid_count) from run_summary",
    }
    if n_first_eval == 0:
        out["unknown_reason"] = "cannot distinguish first eval events"
    if valid_nodes and n_first_eval:
        out["significant_gain_rate"] = sig_gain / valid_nodes
    return out


def verify_readonly_copy(original: Path, copy_path: Path) -> str:
    """Return sha256 of original after read-only access via copy."""
    digest = hashlib.sha256(copy_path.read_bytes()).hexdigest()
    return f"sha256:{digest}"
