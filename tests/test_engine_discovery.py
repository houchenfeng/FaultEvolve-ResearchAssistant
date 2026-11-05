"""Integration tests for engine-wired knowledge discovery."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from faultevolve.cloud.engine import EvolutionEngine
from faultevolve.cloud.llm import LLMTransientError, MockLLM
from faultevolve.cloud.operators import OperatorContext, OperatorType, build_user_message
from faultevolve.cloud.store import Store
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


FEATURE_CLAIM_JSON = {
    "title": "m1 last value",
    "condition": "toy units",
    "feature_code": (
        "def feature(history):\n"
        "    return history.groupby('unit')['m1'].last()"
    ),
    "outcome": "Higher m1 on failures",
    "direction": "+",
    "scope": "train explore",
    "falsifier": "no separation",
    "category": "feature_engineering",
    "tags": ["m1"],
}


class ScriptedDiscoveryLLM(MockLLM):
    """Route KD discovery markers; other calls use MockLLM defaults."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._translate_fail = False
        self._promoted_id: str | None = None

    def chat_for_reasoning(self, messages, temperature=0.2):
        from faultevolve.common.metering import CallMetrics

        text = messages[-1]["content"] if messages else ""
        if "KD_TRANSLATE" in text:
            if self._translate_fail:
                raise LLMTransientError("mock transient")
            payload = f"<claim>{json.dumps(FEATURE_CLAIM_JSON)}</claim>"
            return payload, CallMetrics(prompt_tokens=50, completion_tokens=30, latency_ms=10, cached=False)
        if "KD_ENTAIL" in text:
            payload = json.dumps({"card_id": None, "relation": "none"})
            return payload, CallMetrics(prompt_tokens=40, completion_tokens=20, latency_ms=8, cached=False)
        return super().chat_for_reasoning(messages, temperature)

    def chat(self, messages, model=None, temperature=None, max_tokens=None):
        text, metrics = super().chat(messages, model, temperature, max_tokens)
        if self._promoted_id and "<adopted_cards>" in text:
            text = text.replace(
                "<adopted_cards></adopted_cards>",
                f"<adopted_cards>{self._promoted_id}</adopted_cards>",
            )
            if self._promoted_id not in text:
                text = text.replace(
                    "<adopted_cards>FE01,M01</adopted_cards>",
                    f"<adopted_cards>{self._promoted_id}</adopted_cards>",
                )
        return text, metrics


def _task_dir(tmp_path: Path) -> Path:
    task = tmp_path / "task"
    task.mkdir()
    (task / "init.py").write_text("# init\n", encoding="utf-8")
    (task / "problem.md").write_text("# p", encoding="utf-8")
    (task / "prompt.md").write_text("# prompt", encoding="utf-8")
    (task / "evaluator.py").write_text(
        "def evaluate(p, **kw):\n"
        "    return {'validity': 1, 'combined_score': 22, 'cost_time': 1, "
        "'error_info': '', 'metric': {'f1': 0.2, 'f1_boot_std': 0.02}}\n",
        encoding="utf-8",
    )
    knowledge = task / "knowledge"
    knowledge.mkdir()
    cards = [
        {"id": "K1", "title": "K1", "category": "model", "claim": "c1", "source_ids": [], "tags": []},
        {"id": "K2", "title": "K2", "category": "evaluation", "claim": "c2", "source_ids": [], "tags": []},
        {"id": "K3", "title": "K3", "category": "feature_engineering", "claim": "c3", "source_ids": [], "tags": []},
    ]
    with (knowledge / "cards.jsonl").open("w", encoding="utf-8") as f:
        for c in cards:
            f.write(json.dumps(c) + "\n")
    return task


def _discovery_config(**overrides: Any) -> EvolveConfig:
    cfg = EvolveConfig()
    cfg.budget.max_iterations = 6
    cfg.budget.max_wall_hours = 1.0
    cfg.knowledge.enabled = True
    cfg.knowledge.dir = "knowledge"
    base = {
        "enabled": True,
        "every_n_iterations": 2,
        "run_at_end": True,
        "min_insight_z": 0.5,
        "bootstrap_b": 80,
        "neg_control_repeats": 5,
    }
    tour = overrides.pop("tournament", None)
    base.update(overrides)
    cfg.discovery = cfg.discovery.model_copy(update=base)
    if tour is not None:
        cfg.discovery.tournament = cfg.discovery.tournament.model_copy(update=tour)
    return cfg


def _engine(tmp_path: Path, cfg: EvolveConfig, llm: MockLLM) -> EvolutionEngine:
    task_dir = _task_dir(tmp_path)
    adapter = FakeAdapter()
    adapter.set_results(
        [
            {
                "validity": 1.0,
                "combined_score": 20.0 + i,
                "cost_time": 1.0,
                "metric": {"f1_boot_std": 0.02},
            }
            for i in range(24)
        ]
    )
    db = tmp_path / "db" / "fe.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    engine = EvolutionEngine(
        cfg,
        adapter,
        adapter.load_task(task_dir),
        Store(db),
        llm,
        mock=True,
        task_dir=task_dir,
    )
    engine.initialize(experiment_id="e2e")
    engine.artifacts_dir = db.parent
    return engine


def test_discovery_end_to_end(tmp_path):
    llm = ScriptedDiscoveryLLM(enable_repair_scenario=False)
    engine = _engine(tmp_path, _discovery_config(), llm)
    summary = engine.run(6)

    assert summary.discovery_rounds >= 1
    assert summary.claims_tested >= 1
    assert summary.claims_discovered >= 1
    assert summary.discovered_cards_count >= 1
    card_file = engine.store.db_path.parent.parent / "knowledge" / "discovered_cards.jsonl"
    assert card_file.exists()

    types = [e.type for e in engine.store.get_events("e2e")]
    for required in (
        "discovery_round_started",
        "claim_proposed",
        "claim_tested",
        "claim_graded",
        "card_promoted",
    ):
        assert required in types

    assert summary.discovery_tokens > 0
    assert summary.total_tokens >= summary.discovery_tokens
    purposes = {c.purpose for c in engine.store.get_llm_calls("e2e")}
    assert "discover" in purposes

    disc_dir = engine.artifacts_dir / "discovery"
    engine.write_discovery_artifacts(engine.artifacts_dir)
    for name in (
        "phenomena.json",
        "preregistration.json",
        "controls.json",
        "discovered_cards.snapshot.jsonl",
    ):
        assert (disc_dir / name).exists()


def test_discovered_card_adopted_feeds_card_stats(tmp_path):
    llm = ScriptedDiscoveryLLM(enable_repair_scenario=False)

    def _capture_promote(*args, **kwargs):
        from faultevolve.discovery.promotion import promote_claims as real

        out = real(*args, **kwargs)
        if out:
            llm._promoted_id = out[0]["id"]
        return out

    with patch("faultevolve.discovery.pipeline.promote_claims", side_effect=_capture_promote):
        engine = _engine(tmp_path, _discovery_config(max_claims_per_round=2), llm)
        summary = engine.run(5)

    assert llm._promoted_id is not None
    stats = engine.store.get_card_stats("e2e").get(llm._promoted_id, {})
    assert stats.get("n", 0) >= 1
    assert summary.discovered_cards_offered >= 1
    assert summary.discovered_cards_adopted >= 1
    from faultevolve.cloud.engine import _write_artifacts

    _write_artifacts(engine, engine.store, "e2e", engine.artifacts_dir, summary)
    tree = json.loads((engine.artifacts_dir / "tree.json").read_text())
    nodes = tree.get("nodes", tree) if isinstance(tree, dict) else tree
    if isinstance(nodes, dict):
        adopted = [n.get("adopted_cards", []) for n in nodes.values()]
    else:
        adopted = [n.get("adopted_cards", []) for n in nodes]
    assert any(llm._promoted_id in a for a in adopted)


def test_final_round_after_flush(tmp_path, monkeypatch):
    llm = ScriptedDiscoveryLLM(enable_repair_scenario=False)
    cfg = _discovery_config()
    cfg.budget.max_iterations = 1
    engine = _engine(tmp_path, cfg, llm)
    order: list[str] = []
    real_flush = engine._flush_deferred
    real_maybe = engine._maybe_run_discovery

    def _wrap_flush(*args, **kwargs):
        order.append("flush")
        return real_flush(*args, **kwargs)

    def _wrap_maybe(final=False):
        if final:
            order.append("discovery_final")
        return real_maybe(final=final)

    monkeypatch.setattr(engine, "_flush_deferred", _wrap_flush)
    monkeypatch.setattr(engine, "_maybe_run_discovery", _wrap_maybe)
    engine.run(1)
    assert "flush" in order and "discovery_final" in order
    assert order.index("flush") < order.index("discovery_final")


def test_llm_transient_error_fail_open(tmp_path):
    llm = ScriptedDiscoveryLLM(enable_repair_scenario=False)
    llm._translate_fail = True
    engine = _engine(tmp_path, _discovery_config(), llm)
    summary = engine.run(4)
    assert summary.status in {"finished", "stopped", "budget"}
    types = [e.type for e in engine.store.get_events("e2e")]
    assert "discovery_llm_error" in types


def test_token_share_skip(tmp_path):
    llm = ScriptedDiscoveryLLM(enable_repair_scenario=False)
    engine = _engine(tmp_path, _discovery_config(max_token_share=0.0001), llm)
    summary = engine.run(4)
    assert summary.discovery_rounds_skipped >= 1


def test_discover_op_prompt(tmp_path):
    task_dir = _task_dir(tmp_path)
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
    refine = OperatorContext(node, FakeTaskSpec(task_dir=task_dir), OperatorType.REFINE)
    refine.set_discover_claim(True)
    inject = OperatorContext(node, FakeTaskSpec(task_dir=task_dir), OperatorType.INJECT)
    assert "<claim>" in build_user_message(refine)
    assert "<claim>" not in build_user_message(inject)


def test_resume_no_duplicate_claims(tmp_path):
    task_dir = _task_dir(tmp_path)
    cfg = _discovery_config()
    adapter = FakeAdapter()
    adapter.set_results(
        [{"validity": 1.0, "combined_score": 22.0 + i, "cost_time": 1.0, "metric": {}} for i in range(16)]
    )
    llm = ScriptedDiscoveryLLM(enable_repair_scenario=False)
    db_root = tmp_path / "resume"
    db_root.mkdir()
    store_path = db_root / "fe.db"
    engine = EvolutionEngine(
        cfg, adapter, adapter.load_task(task_dir), Store(store_path), llm, mock=True, task_dir=task_dir,
    )
    engine.initialize(experiment_id="resume1")
    engine.artifacts_dir = db_root
    engine.run(3)
    first_count = len(engine.store.get_claims("resume1"))

    engine2 = EvolutionEngine(
        cfg.model_copy(update={"budget": cfg.budget.model_copy(update={"max_iterations": 8})}),
        adapter,
        adapter.load_task(task_dir),
        Store(store_path),
        llm,
        mock=True,
        task_dir=task_dir,
    )
    engine2.initialize(resume_id="resume1")
    engine2.artifacts_dir = db_root
    engine2.run(3)
    with engine2.store._conn() as conn:
        rows = conn.execute(
            "SELECT origin_node_id, COUNT(*) AS n FROM claim WHERE experiment_id = ? "
            "GROUP BY origin_node_id",
            ("resume1",),
        ).fetchall()
    for row in rows:
        assert row["n"] == 1
    assert len(engine2.store.get_claims("resume1")) >= first_count


def test_sandbox_failure_emits_claim_sandbox_failed_event(tmp_path):
    llm = ScriptedDiscoveryLLM()
    bad_claim = dict(FEATURE_CLAIM_JSON)
    bad_claim["feature_code"] = (
        "import os\n"
        "def feature(history):\n"
        "    return history.groupby('unit')['m1'].last()"
    )

    def chat_for_reasoning(messages, temperature=0.2):
        from faultevolve.common.metering import CallMetrics

        text = messages[-1]["content"] if messages else ""
        if "KD_TRANSLATE" in text:
            payload = f"<claim>{json.dumps(bad_claim)}</claim>"
            return payload, CallMetrics(prompt_tokens=50, completion_tokens=30, latency_ms=10, cached=False)
        if "KD_ENTAIL" in text:
            payload = json.dumps({"card_id": None, "relation": "none"})
            return payload, CallMetrics(prompt_tokens=40, completion_tokens=20, latency_ms=8, cached=False)
        return MockLLM.chat_for_reasoning(llm, messages, temperature)

    llm.chat_for_reasoning = chat_for_reasoning  # type: ignore[method-assign]
    engine = _engine(tmp_path, _discovery_config(max_claims_per_round=1), llm)
    engine.run(4)
    failed = [e for e in engine.store.get_events("e2e") if e.type == "claim_sandbox_failed"]
    assert failed
    assert failed[0].payload.get("error_type")
    assert failed[0].payload.get("error")
