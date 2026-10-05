#!/usr/bin/env python3
"""Extract PR run metrics from fe.db + run_summary.json (see docs/TODO.md §3.5)."""

from __future__ import annotations

import json
import sqlite3
import sys


def main() -> None:
    if len(sys.argv) != 3:
        print("Usage: python report_run.py <fe.db> <run_summary.json>", file=sys.stderr)
        sys.exit(2)

    db_path, summary_path = sys.argv[1], sys.argv[2]
    summ = json.load(open(summary_path, encoding="utf-8"))
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row

    best = con.execute(
        "SELECT evidence_json FROM node WHERE id=?",
        (summ["best_node_id"],),
    ).fetchone()
    metric = {}
    if best and best["evidence_json"]:
        metric = json.loads(best["evidence_json"]).get("evaluation", {}).get("metric") or {}

    rows = con.execute(
        "SELECT operator, status, evidence_json FROM node",
    ).fetchall()
    ref = [r for r in rows if r["operator"] == "refine"]
    ref_valid = sum(
        1
        for r in ref
        if (json.loads(r["evidence_json"] or "{}").get("evaluation") or {}).get("validity", 0)
        >= 1
    )
    generative_ops = {"refine", "recall_focus", "threshold_calibrate", "inject", "crossover"}
    gen = [r for r in rows if r["operator"] in generative_ops]
    gen_valid = sum(
        1
        for r in gen
        if (json.loads(r["evidence_json"] or "{}").get("evaluation") or {}).get("validity", 0)
        >= 1
    )
    timeouts = sum(
        1
        for r in rows
        if "timeout"
        in (
            (json.loads(r["evidence_json"] or "{}").get("evaluation") or {}).get("error_info")
            or ""
        ).lower()
    )
    gain = summ["best_score"] - summ.get("initial_score", 0)
    tpr = summ.get("tokens_per_ros_point")
    if tpr is None and gain > 0:
        tpr = summ.get("total_tokens", 0) / gain

    out = {
        "ROS": summ["best_score"],
        "P": metric.get("precision"),
        "R": metric.get("recall"),
        "F1": metric.get("f1"),
        "AUPRC": metric.get("auprc"),
        "false_alarm_rate": metric.get("false_alarm_rate"),
        "miss_rate": metric.get("missed_detection_rate"),
        "total_tokens": summ.get("total_tokens"),
        "tokens_by_stage": {
            k: summ.get(k)
            for k in [
                "generate_tokens",
                "repair_tokens",
                "reflect_tokens",
                "knowledge_tokens",
                "self_fix_tokens",
                "jev_tokens",
                "discovery_tokens",
                "crossover_tokens",
            ]
            if k in summ
        },
        "tokens_per_ros_point": tpr,
        "wall_time_s": summ.get("wall_time_s"),
        "refine_valid": f"{ref_valid}/{len(ref)}",
        "generative_valid": f"{gen_valid}/{len(gen)}",
        "timeouts": timeouts,
        "stop_reason": summ.get("stop_reason"),
        "iteration_events": summ.get("iteration_events"),
        "iterations_done": summ.get("iterations_done"),
        "avg_smoke_time_s": summ.get("avg_smoke_time_s"),
        "jev_calls": summ.get("jev_calls", 0),
        "jev_errors": summ.get("jev_errors", 0),
        "jev_fail_open": summ.get("jev_fail_open", 0),
        "evaluations_saved": summ.get("evaluations_saved", 0),
        "eval_time_saved_est_s": summ.get("eval_time_saved_est_s", 0),
        "screening_precision": summ.get("screening_precision"),
        "jev_prior_active": summ.get("jev_prior_active", False),
        "jev_disabled_reason": summ.get("jev_disabled_reason", ""),
        "analysis_calls": summ.get("analysis_calls", 0),
        "analysis_failures": summ.get("analysis_failures", 0),
        "analysis_time_s": summ.get("analysis_time_s", 0.0),
        "analysis_nonempty_rate": summ.get("analysis_nonempty_rate", 0.0),
        "budget_stop_reason": summ.get("budget_stop_reason", ""),
        "stage_cap_hits": summ.get("stage_cap_hits", {}),
        "elite_archive_sizes": summ.get("elite_archive_sizes", {}),
        "expand_skipped_budget": summ.get("expand_skipped_budget", 0),
        "value_mode": summ.get("value_mode", "scalar"),
    }
    for key in (
        "operator_counts",
        "operator_valid_rate",
        "operator_mean_delta",
        "operator_posteriors",
        "operator_tokens",
        "generative_valid_rate",
        "bandit_active",
    ):
        if key in summ:
            out[key] = summ.get(key, {} if key != "generative_valid_rate" else None)
    for key in (
        "crossover_count",
        "crossover_valid_rate",
        "crossover_mean_delta",
        "crossover_best_gain",
        "crossover_tokens",
    ):
        if key in summ:
            out[key] = summ[key]
    for key in (
        "discovery_tokens",
        "discovery_token_share",
        "discovery_rounds",
        "discovery_rounds_skipped",
        "claims_proposed",
        "claims_tested",
        "claims_sandbox_failed",
        "claims_confirmed",
        "claims_revised",
        "claims_discovered",
        "claims_refuted",
        "claims_undetermined",
        "discovered_cards_count",
        "discovered_cards_offered",
        "discovered_cards_adopted",
        "discovered_card_adoption_rate",
        "discovered_card_mean_delta",
        "literature_card_mean_delta",
        "score_delta_after_discovery",
        "neg_control_false_positives",
        "neg_control_fpr",
        "planted_recovery_rate",
    ):
        if key in summ:
            out[key] = summ[key]
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
