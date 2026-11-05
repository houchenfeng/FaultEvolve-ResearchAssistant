"""Generate the unified Web UI showcase replay fixture.

Combines the 21-node / 6-layer tree shape from ``make_tree_showcase_fixture.py``
with HDD-realistic scores (validation ROS high-water ~38.14, init ~22.81) and
a populated knowledge-discovery slice centered on claim ``C-89f4bdd1-0010``
(CONFIRMED window-end ``smart_194_normalized`` signal — not a DISCOVERED stub).

Usage::

    python scripts/make_web_showcase_fixture.py
    python scripts/make_web_showcase_fixture.py --check
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FIXTURE_ROOT = REPO / "tests" / "fixtures" / "runs"

EXPERIMENT_ID = "c89e2a01"
RUN_ID = f"hdd_mvp_showcase_{EXPERIMENT_ID}"
DEMO_RUN_ID = "hdd_mvp_demo_7510f100"

ROOT_SCORE = 22.807355886970594
BEST_SCORE = 38.139345971596875
BEST_NODE = "n18a3b4dd"

CLAIM_C89 = "C-89f4bdd1-0010"
PREREG_HASH = "a1b2c3d4e5f6789012345678901234567890abcdef1234567890abcdef123456"

# Baseline HDD val metrics at init ROS (~22.81), from ``hdd_mvp_demo_7510f100`` events.
_BASE_METRIC = {
    "precision": 0.19826,
    "recall": 0.33598,
    "f1": 0.24937,
    "f1_p10": 0.22935,
    "f1_boot_std": 0.01652,
    "auprc": 0.19546,
    "recall_at_far": 0.27381,
    "false_alarm_rate": 0.0034,
    "missed_detection_rate": 0.66402,
    "alarms_per_1k_disks": 4.23,
    "quality": 0.22807,
    "run_time_s": 3.66,
    "time_factor": 1.0,
    "split": "val",
}


def _load_tree_module():
    path = REPO / "scripts" / "make_tree_showcase_fixture.py"
    spec = importlib.util.spec_from_file_location("make_tree_showcase_fixture", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _rescale_nodes(tree_mod) -> list[tuple]:
    old_root = tree_mod.ROOT_SCORE
    old_best = tree_mod.BEST_SCORE
    scale = (BEST_SCORE - ROOT_SCORE) / (old_best - old_root)
    by_id = {row[0]: row for row in tree_mod.N}

    def rescale(score: float | None) -> float | None:
        if score is None or score == 0:
            return score
        return round(ROOT_SCORE + (score - old_root) * scale, 2)

    out: list[tuple] = []
    for row in tree_mod.N:
        nid, parent, depth, operator, score, _delta, noise, status, hypo, err, repair, second = row
        new_score = rescale(score)
        parent_score = rescale(by_id[parent][4]) if parent else None
        if new_score is not None and parent_score is not None and status == "done":
            new_delta = round(new_score - parent_score, 2)
        else:
            new_delta = _delta
        out.append(
            (nid, parent, depth, operator, new_score, new_delta, noise, status, hypo, err, repair, second),
        )
    return out


def _metric_for_ros(ros: float | None) -> dict[str, object]:
    if ros is None or ros <= 0:
        return {"f1_p10": 0.0, "run_time_s": 2.4, "split": "val"}
    ratio = ros / ROOT_SCORE
    metric = dict(_BASE_METRIC)
    for key in (
        "precision",
        "recall",
        "f1",
        "f1_p10",
        "auprc",
        "recall_at_far",
        "quality",
    ):
        metric[key] = round(float(metric[key]) * ratio, 5)
    metric["run_time_s"] = round(2.4 + (ros - ROOT_SCORE) * 0.08, 2)
    metric["combined_ros"] = ros
    return metric


def _patch_tree_module(tree_mod) -> None:
    tree_mod.EXPERIMENT_ID = EXPERIMENT_ID
    tree_mod.RUN_ID = RUN_ID
    tree_mod.ROOT_SCORE = ROOT_SCORE
    tree_mod.BEST_SCORE = BEST_SCORE
    tree_mod.BEST_NODE = BEST_NODE
    tree_mod.N = _rescale_nodes(tree_mod)
    tree_mod.NODE_BY_ID = {row[0]: row for row in tree_mod.N}

    def evidence(row: tuple) -> dict[str, object]:
        _id, _p, _d, _op, score, delta, noise, status, _h, error, _r, _s = row
        evaluation: dict[str, object] = {
            "validity": 1.0 if status == "done" else 0.0,
            "combined_score": score,
            "cost_time": 2.0 + (len(_id) % 7) / 10.0,
            "error_info": "",
            "metric": _metric_for_ros(score),
        }
        if error:
            evaluation["error_info"] = (
                f"TimeoutError: 候选在 900s 预算内未写出 pred.csv（{error}）"
            )
        payload: dict[str, object] = {"evaluation": evaluation}
        if delta is not None:
            payload["delta_score"] = delta
        if noise is not None:
            payload["noise_delta"] = noise
        return payload

    tree_mod._evidence = evidence

    patch = dict(tree_mod.SUMMARY_PATCH)
    patch.update(
        {
            "experiment_id": EXPERIMENT_ID,
            "best_node_id": BEST_NODE,
            "best_score": BEST_SCORE,
            "initial_score": ROOT_SCORE,
            "improvement": round(BEST_SCORE - ROOT_SCORE, 6),
            "total_tokens": 146415,
            "wall_time_s": 2113.44,
            "discovery_tokens": 7557,
            "discovery_rounds": 2,
            "claims_proposed": 2,
            "claims_tested": 2,
            "claims_confirmed": 1,
            "claims_refuted": 0,
            "claims_discovered": 0,
            "claims_sandbox_failed": 0,
            "mechanisms_proposed": 3,
            "mechanisms_established": 1,
            "mechanisms_refuted": 1,
            "mechanism_patches": 1,
            "mechanism_cards_count": 2,
            "tournament_rounds": 1,
            "matches_played": 4,
            "decisive_matches": 2,
            "underpowered_draws": 1,
            "certificates_issued": 1,
            "min_detectable_effect": 0.0812,
            "planted_mechanism_recovered": 0.75,
            "llm_vs_data_kendall_tau": 0.62,
            "shuffled_env_false_pass": 0.0,
            "neg_control_false_positives": 0,
            "neg_control_fpr": 0.0,
            "discovered_card_ids": [],
            "fixture_showcase": True,
            "fixture_label_zh": "HDD 展示运行（合成 fixture，分数与 C-89 信号为演示数据）",
        },
    )
    tree_mod.SUMMARY_PATCH = patch


def _write_discovery(discovery_dir: Path) -> None:
    discovery_dir.mkdir(parents=True, exist_ok=True)
    phenomena = [
        {
            "claim_id": CLAIM_C89,
            "grade": "confirmed",
            "payload": {
                "split": "confirm",
                "n": 9262,
                "n_pos": 327,
                "n_neg": 8935,
                "effect": 0.3124,
                "ci_low": 0.2781,
                "ci_high": 0.3459,
                "p": 1e-24,
                "e": 4.2e12,
                "direction_ok": True,
                "temporal_ok": True,
                "feature": "smart_194_normalized",
                "window": "window_end",
                "title": "窗口末端 smart_194_normalized 与短期 HDD 故障信号",
                "factor_id": "HDD3_F10",
            },
        },
        {
            "claim_id": "C-showcase-0002",
            "grade": "refuted",
            "payload": {
                "split": "confirm",
                "n": 9262,
                "effect": 0.02,
                "ci_low": -0.01,
                "ci_high": 0.05,
                "p": 0.42,
                "e": 1.2,
                "direction_ok": False,
                "temporal_ok": True,
            },
        },
    ]
    (discovery_dir / "phenomena.json").write_text(
        json.dumps(phenomena, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    prereg = [{"claim_id": CLAIM_C89, "hash": PREREG_HASH}]
    (discovery_dir / "preregistration.json").write_text(
        json.dumps(prereg, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    controls = [
        {
            "neg_trials": 10,
            "neg_false_positives": 0,
            "neg_fpr": 0.0,
            "planted": {
                "0.5": {"trials": 5.0, "recovered": 4.0, "rate": 0.8},
            },
            "passed": True,
        },
    ]
    (discovery_dir / "controls.json").write_text(
        json.dumps(controls, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    certificates = [
        {
            "mechanism_id": "M-showcase-c89",
            "rival_id": "R-llm-rival-01",
            "test_id": "T-preregistered-01",
            "test_type": "pre_registered",
            "env": "confirm",
            "stat": 3.84,
            "ci": [0.28, 0.35],
            "e_value": 4.2e12,
            "prereg_hash": PREREG_HASH,
            "date": "2026-10-05",
        },
    ]
    (discovery_dir / "certificates.json").write_text(
        json.dumps(certificates, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (discovery_dir / "theories.json").write_text("[]\n", encoding="utf-8")
    (discovery_dir / "mechanisms.json").write_text("[]\n", encoding="utf-8")
    (discovery_dir / "tournament_results.json").write_text("{}\n", encoding="utf-8")
    snapshot = (
        '{"card_id":"FE09","title":"Window-end normalized SMART deltas",'
        '"category":"feature_engineering"}\n'
    )
    (discovery_dir / "discovered_cards.snapshot.jsonl").write_text(snapshot, encoding="utf-8")


def generate(root: Path) -> Path:
    tree_mod = _load_tree_module()
    _patch_tree_module(tree_mod)
    out = tree_mod.generate(root)
    _write_discovery(out / "discovery")
    summary_path = out / "run_summary.json"
    data = json.loads(summary_path.read_text(encoding="utf-8"))
    data["discovered_card_ids"] = []
    summary_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return out


def check(out: Path) -> int:
    failures: list[str] = []
    if not out.is_dir():
        return 1

    summary = json.loads((out / "run_summary.json").read_text(encoding="utf-8"))
    if abs(summary.get("best_score", 0) - BEST_SCORE) > 0.01:
        failures.append(f"best_score expected ~{BEST_SCORE}, got {summary.get('best_score')}")
    if summary.get("best_node_id") != BEST_NODE:
        failures.append("best_node_id mismatch")

    phenomena = json.loads((out / "discovery/phenomena.json").read_text(encoding="utf-8"))
    c89 = next((p for p in phenomena if p.get("claim_id") == CLAIM_C89), None)
    if c89 is None or c89.get("grade") != "confirmed":
        failures.append(f"{CLAIM_C89} must be grade=confirmed")

    tree_mod = _load_tree_module()
    _patch_tree_module(tree_mod)
    tree_mod.RUN_ID = RUN_ID
    failures.extend(
        line.removeprefix("FAIL ")
        for line in _run_tree_check(tree_mod, out)
    )

    for line in failures:
        print(f"FAIL {line}", file=sys.stderr)
    return len(failures)


def _run_tree_check(tree_mod, out: Path) -> list[str]:
    """Reuse tree fixture structural checks."""
    import io
    from contextlib import redirect_stderr

    buf = io.StringIO()
    with redirect_stderr(buf):
        code = tree_mod.check(out)
    if code == 0:
        return []
    return [line for line in buf.getvalue().splitlines() if line.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    target = FIXTURE_ROOT / RUN_ID
    if args.check:
        if not target.is_dir():
            print(f"FAIL missing fixture: {target}", file=sys.stderr)
            return 1
        return 1 if check(target) else 0

    out = generate(FIXTURE_ROOT)
    broken = check(out)
    print(f"wrote {out} ({broken} problem(s))")
    return 1 if broken else 0


if __name__ == "__main__":
    raise SystemExit(main())
