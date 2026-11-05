"""Tests that discovery defaults off and does not change baseline behavior."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from faultevolve.cloud.engine import run_local_evolution
from faultevolve.cloud.operators import OperatorContext, OperatorType, build_user_message
from faultevolve.common.schemas import (
    BranchMemory,
    EvaluationResult,
    HypothesisStatus,
    Node,
    NodeArtifact,
    NodeEvidence,
    NodeStatus,
)
from faultevolve.config import EvolveConfig
from faultevolve.worker.runner import FakeAdapter, FakeTaskSpec


DISCOVERY_SUMMARY_KEYS = {
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
}


def _minimal_task(tmp_path: Path) -> Path:
    task = tmp_path / "task"
    task.mkdir()
    (task / "init.py").write_text("# init", encoding="utf-8")
    (task / "problem.md").write_text("# p", encoding="utf-8")
    (task / "prompt.md").write_text("# p", encoding="utf-8")
    (task / "evaluator.py").write_text(
        "def evaluate(p, **kw):\n"
        "    return {'validity': 1, 'combined_score': 22, 'cost_time': 1, 'error_info': '', 'metric': {}}\n",
        encoding="utf-8",
    )
    return task


def test_discovery_default_disabled():
    assert EvolveConfig().discovery.enabled is False


def test_run_summary_unchanged_when_disabled(tmp_path):
    task = _minimal_task(tmp_path)
    runs = tmp_path / "runs"
    off = run_local_evolution(
        task_dir=task,
        mock=True,
        max_iterations=3,
        runs_dir=runs,
        adapter=FakeAdapter(),
        seed=7,
    )
    on_cfg_path = task / "evolve.yaml"
    on_cfg_path.write_text(
        "discovery:\n  enabled: true\n  every_n_iterations: 99\n  run_at_end: false\n",
        encoding="utf-8",
    )
    runs2 = tmp_path / "runs2"
    on = run_local_evolution(
        task_dir=task,
        mock=True,
        max_iterations=3,
        runs_dir=runs2,
        adapter=FakeAdapter(),
        seed=7,
    )

    off_summary = json.loads((Path(off["output_dir"]) / "run_summary.json").read_text())
    on_summary = json.loads((Path(on["output_dir"]) / "run_summary.json").read_text())

    volatile = DISCOVERY_SUMMARY_KEYS | {
        "experiment_id",
        "wall_time_s",
        "best_node_id",
        "tokens_per_ros_point",
        "tokens_per_score_gain",
    }

    def strip_volatile(d: dict) -> dict:
        return {k: v for k, v in d.items() if k not in volatile}

    assert strip_volatile(off_summary) == strip_volatile(on_summary)
    assert off_summary["total_tokens"] == on_summary["total_tokens"]

    out_off = Path(off["output_dir"])
    for line in (out_off / "events.jsonl").read_text().splitlines():
        ev = json.loads(line)
        assert not ev.get("type", "").startswith("discovery_")
    from faultevolve.cloud.store import Store

    store = Store(out_off / "fe.db")
    assert store.get_claims(off["experiment_id"]) == []
    assert not (out_off / "discovery").exists()
    assert not (out_off.parent / "knowledge" / "discovered_cards.jsonl").exists()


def test_build_user_message_unchanged_without_discover_claim(tmp_path):
    node = Node(
        id="n",
        experiment_id="e",
        branch_id="main",
        artifact=NodeArtifact(code="# x", intent="", hypothesis=""),
        evidence=NodeEvidence(
            evaluation=EvaluationResult(
                validity=1.0, combined_score=20.0, cost_time=1.0, error_info="", metric={},
            )
        ),
        status=NodeStatus.DONE,
        hypothesis_status=HypothesisStatus.OPEN,
        branch_memory=BranchMemory(),
    )
    ctx = OperatorContext(node, FakeTaskSpec(task_dir=tmp_path), OperatorType.REFINE)
    ctx.set_discover_claim(False)
    msg = build_user_message(ctx)
    snapshot = build_user_message(
        OperatorContext(node, FakeTaskSpec(task_dir=tmp_path), OperatorType.REFINE)
    )
    assert msg == snapshot
    assert "<claim>" not in msg


def test_discovery_config_round_trip():
    cfg = EvolveConfig.from_dict({"discovery": {"enabled": True}})
    assert cfg.discovery.enabled is True
    assert cfg.with_overrides(max_iterations=5).discovery.enabled is True
