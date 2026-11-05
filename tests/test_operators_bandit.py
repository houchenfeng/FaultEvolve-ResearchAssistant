"""Tests for recall/threshold operators and operator bandit."""

from __future__ import annotations

import json
import random
import re
import sqlite3
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from faultevolve.cloud.engine import EvolutionEngine
from faultevolve.cloud.llm import MockLLM
from faultevolve.cloud.operators import (
    OperatorContext,
    OperatorType,
    build_user_message,
    fn_profile_keywords,
    select_operator,
)
from faultevolve.cloud.store import DDL, Store
from faultevolve.common.schemas import (
    BranchMemory,
    EvaluationResult,
    HypothesisStatus,
    Node,
    NodeArtifact,
    NodeEvidence,
    NodeStatus,
)
from faultevolve.config import EvolveConfig, OperatorsConfig
from faultevolve.knowledge.loader import KnowledgeCard
from faultevolve.knowledge.retriever import CardRetriever, RetrievalContext
from faultevolve.tasks.protocol import TaskSpec
from faultevolve.worker.runner import FakeAdapter, FakeTaskSpec


def _engine(tmp_path: Path, adapter, config: EvolveConfig | None = None) -> EvolutionEngine:
    config = config or EvolveConfig()
    store = Store(tmp_path / "fe.db")
    spec = FakeTaskSpec(task_dir=tmp_path)
    engine = EvolutionEngine(
        config=config,
        task_adapter=adapter,
        task_spec=spec,
        store=store,
        llm=MockLLM(enable_repair_scenario=False),
        mock=True,
        task_dir=tmp_path,
    )
    engine.operator = __import__(
        "faultevolve.cloud.operators", fromlist=["RefineOperator"]
    ).RefineOperator(engine.llm)
    return engine


def _bandit_config(**overrides: Any) -> EvolveConfig:
    cfg = EvolveConfig()
    cfg.operators.bandit = True
    cfg.budget.max_iterations = 12
    cfg.smoke_test.enabled = False
    for key, value in overrides.items():
        setattr(cfg.operators, key, value)
    return cfg


def test_select_operator_default_refine_when_bandit_off():
    rng = MagicMock(spec=random.Random)
    chosen = select_operator(
        None,
        [OperatorType.REFINE, OperatorType.RECALL_FOCUS, OperatorType.INJECT],
        stats={OperatorType.RECALL_FOCUS: (50.0, 1.0)},
        rng=rng,
        bandit=False,
    )
    assert chosen == OperatorType.REFINE
    rng.random.assert_not_called()
    rng.betavariate.assert_not_called()


def test_thompson_prefers_rewarded_operator():
    stats = {
        OperatorType.REFINE: (1.0, 20.0),
        OperatorType.RECALL_FOCUS: (20.0, 1.0),
    }
    rng = random.Random(7)
    counts = {OperatorType.RECALL_FOCUS: 0, OperatorType.REFINE: 0}
    for _ in range(200):
        op = select_operator(
            None,
            [OperatorType.REFINE, OperatorType.RECALL_FOCUS],
            stats=stats,
            rng=rng,
            min_explore=0.0,
            bandit=True,
        )
        counts[op] += 1
    assert counts[OperatorType.RECALL_FOCUS] >= 190


def test_min_explore():
    ops = [
        OperatorType.REFINE,
        OperatorType.RECALL_FOCUS,
        OperatorType.THRESHOLD_CALIBRATE,
        OperatorType.INJECT,
    ]
    stats = {OperatorType.REFINE: (100.0, 1.0)}
    rng = random.Random(3)
    counts = {op: 0 for op in ops}
    for _ in range(4000):
        chosen = select_operator(
            None,
            ops,
            stats=stats,
            rng=rng,
            min_explore=0.1,
            bandit=True,
        )
        counts[chosen] += 1
    for op in ops:
        assert counts[op] / 4000 >= 0.07


def test_recall_focus_fallback_without_analysis(tmp_path):
    cfg = _bandit_config()
    adapter = FakeAdapter()
    adapter.set_results([{"validity": 1.0, "combined_score": 22.0 + i * 0.1, "metric": {}} for i in range(10)])
    engine = _engine(tmp_path, adapter, cfg)
    engine.initialize()
    parent = engine.tree.get_root()
    avail = engine._available_operators(parent)
    assert OperatorType.RECALL_FOCUS not in avail
    summary = engine.run(max_iterations=6)
    nodes = engine.store.get_nodes_by_experiment(engine.experiment_id)
    assert not any(n.operator == OperatorType.RECALL_FOCUS for n in nodes)
    assert summary.bandit_active is True


def test_recall_focus_available_with_fn_groups(tmp_path):
    cfg = EvolveConfig()
    engine = _engine(tmp_path, FakeAdapter(), cfg)
    engine.initialize()
    parent = engine.tree.get_root()
    parent.evidence = NodeEvidence(
        evaluation=EvaluationResult(
            validity=1.0,
            combined_score=22.0,
            cost_time=1.0,
            error_info="",
            metric={"analysis": {"fn_groups": [{"dimension": "a", "value": "x", "n": 12}]}},
        )
    )
    avail = engine._available_operators(parent)
    assert OperatorType.RECALL_FOCUS in avail


def test_operator_stats_persist_resume(tmp_path):
    db_path = tmp_path / "fe.db"
    cfg = _bandit_config(enabled=["refine", "threshold_calibrate"], min_explore=0.5)
    adapter = FakeAdapter()
    adapter.set_results([
        {"validity": 1.0, "combined_score": 22.0 + i * 0.2, "metric": {}}
        for i in range(20)
    ])
    engine = _engine(tmp_path, adapter, cfg)
    engine.initialize()
    engine.run(max_iterations=6)
    exp_id = engine.experiment_id
    stats_after_first = engine.store.get_operator_stats(exp_id)
    n_first = sum(int(r["n"]) for r in stats_after_first.values())
    ab_first = sum(
        int(r["alpha"]) + int(r["beta"]) for r in stats_after_first.values()
    )

    engine2 = _engine(tmp_path, adapter, cfg)
    engine2.initialize(resume_id=exp_id)
    engine2.run(max_iterations=4)
    stats_after_second = engine2.store.get_operator_stats(exp_id)
    n_total = sum(int(r["n"]) for r in stats_after_second.values())
    ab_second = sum(
        int(r["alpha"]) + int(r["beta"]) for r in stats_after_second.values()
    )
    assert n_total >= n_first
    assert ab_second >= ab_first
    summary2 = engine2._operator_summary()
    assert sum(summary2["operator_counts"].values()) == n_total


def test_inject_forces_card(tmp_path, monkeypatch):
    knowledge_dir = tmp_path / "knowledge"
    knowledge_dir.mkdir()
    card = {
        "id": "FE99",
        "title": "Silent pattern",
        "category": "feature_engineering",
        "claim": "Use silent flag",
        "source_ids": [],
        "tags": ["silent"],
        "impl_hint": "Add feature",
        "risk": "Low",
        "priority": 1,
    }
    with (knowledge_dir / "cards.jsonl").open("w") as f:
        f.write(json.dumps(card) + "\n")
    (tmp_path / "evolve.yaml").write_text(
        "knowledge:\n  dir: knowledge\n  k: 1\n  max_per_category: 1\n"
    )

    cfg = _bandit_config(enabled=["refine", "inject"], min_explore=0.0)
    cfg.knowledge.dir = "knowledge"
    adapter = FakeAdapter()
    adapter.set_results([{"validity": 1.0, "combined_score": 23.0, "metric": {}}])
    engine = _engine(tmp_path, adapter, cfg)
    engine.llm.set_responses([
        "<hypothesis>h</hypothesis><intent>i</intent>\n```python\n# child\n```",
    ])
    captured_messages: list[list[dict[str, str]]] = []
    real_chat = engine.llm.chat

    def chat_log(messages, *args, **kwargs):
        captured_messages.append(messages)
        return real_chat(messages, *args, **kwargs)

    engine.llm.chat = chat_log  # type: ignore[method-assign]
    monkeypatch.setattr(
        "faultevolve.cloud.engine.select_operator",
        lambda *args, **kwargs: OperatorType.INJECT,
    )
    engine.initialize()
    engine.run(max_iterations=1)
    user_content = captured_messages[-1][-1]["content"]
    assert "FE99" in user_content
    assert "必须采纳" in user_content
    nodes = [n for n in engine.store.get_nodes_by_experiment(engine.experiment_id) if n.parent_id]
    child = max(nodes, key=lambda n: n.created_at)
    assert child.operator == OperatorType.INJECT
    assert child.card_ids == ["FE99"]


def test_inject_fallback_no_cards(tmp_path, monkeypatch):
    cfg = _bandit_config(enabled=["refine", "inject"], min_explore=0.0)
    adapter = FakeAdapter()
    adapter.set_results([{"validity": 1.0, "combined_score": 23.0, "metric": {}}])
    engine = _engine(tmp_path, adapter, cfg)
    monkeypatch.setattr(
        "faultevolve.cloud.engine.select_operator",
        lambda *args, **kwargs: OperatorType.INJECT,
    )
    engine.initialize()
    engine.run(max_iterations=1)
    nodes = [n for n in engine.store.get_nodes_by_experiment(engine.experiment_id) if n.parent_id]
    child = max(nodes, key=lambda n: n.created_at)
    assert child.operator == OperatorType.REFINE
    events = engine.store.get_events(engine.experiment_id)
    assert any(e.type == "operator_fallback" for e in events)


def test_operator_enum_backward_compat(tmp_path):
    assert OperatorType("refine") == OperatorType.REFINE
    assert OperatorType("recall_focus") == OperatorType.RECALL_FOCUS

    old_ddl = DDL.split("CREATE TABLE IF NOT EXISTS operator_stats")[0]
    db_path = tmp_path / "legacy.db"
    with sqlite3.connect(db_path) as conn:
        conn.executescript(old_ddl)
        conn.execute(
            """
            INSERT INTO experiment (
                id, name, status, config_json, problem_md, prompt_md, created_at
            ) VALUES ('e1', 'n', 'running', '{}', '', '', 't')
            """
        )
        conn.execute(
            """
            INSERT INTO node (
                id, experiment_id, parent_id, branch_id, depth, operator,
                artifact_json, evidence_json, status, hypothesis_status, created_at
            ) VALUES (
                'n1', 'e1', NULL, 'main', 0, 'refine',
                '{"code":"# x"}', '{}', 'done', 'open', 't'
            )
            """
        )

    store = Store(db_path)
    assert store.get_operator_stats("e1") == {}
    node = store.get_node("n1")
    assert node is not None
    assert node.operator == OperatorType.REFINE


def test_operator_prompts_isolated(tmp_path):
    task_spec = FakeTaskSpec(task_dir=tmp_path)
    node = Node(
        id="n",
        experiment_id="e",
        branch_id="main",
        artifact=NodeArtifact(code="# x", intent="", hypothesis=""),
        evidence=NodeEvidence(
            evaluation=EvaluationResult(
                validity=1.0,
                combined_score=20.0,
                cost_time=1.0,
                error_info="",
                metric={},
            )
        ),
        status=NodeStatus.DONE,
        hypothesis_status=HypothesisStatus.OPEN,
        branch_memory=BranchMemory(),
    )
    refine_ctx = OperatorContext(node, task_spec, OperatorType.REFINE)
    refine_msg = build_user_message(refine_ctx)
    assert "针对错例画像中最主要的误告或漏告来源" in refine_msg
    assert "禁止读取任何标签文件" not in refine_msg

    recall_ctx = OperatorContext(node, task_spec, OperatorType.RECALL_FOCUS)
    recall_msg = build_user_message(recall_ctx)
    assert "fn_groups" in recall_msg or "漏告" in recall_msg

    threshold_ctx = OperatorContext(node, task_spec, OperatorType.THRESHOLD_CALIBRATE)
    threshold_msg = build_user_message(threshold_ctx)
    assert "禁止读取任何标签文件" in threshold_msg


def test_fn_profile_keywords():
    analysis = {
        "fn_groups": [
            {"dimension": "silent", "value": "yes"},
            {"dimension": "model", "value": "AB-1"},
        ]
    }
    assert fn_profile_keywords(analysis) == ["silent", "yes", "model", "ab-1"]
    assert fn_profile_keywords({}) == []


def test_retriever_profile_keywords_boost():
    cards = [
        KnowledgeCard(
            id="A",
            title="A",
            category="feature_engineering",
            claim="a",
            source_ids=[],
            tags=["other"],
            impl_hint="",
            risk="",
            priority=2,
        ),
        KnowledgeCard(
            id="B",
            title="B",
            category="feature_engineering",
            claim="b",
            source_ids=[],
            tags=["silent"],
            impl_hint="",
            risk="",
            priority=2,
        ),
    ]
    retriever = CardRetriever(cards=cards, default_k=2)
    ctx = RetrievalContext(keywords=["x"], profile_keywords=["silent"])
    selected = retriever.retrieve(ctx, k=2)
    assert selected[0].id == "B"


def test_default_behavior_unchanged(tmp_path):
    adapter = FakeAdapter()
    adapter.set_results([{"validity": 1.0, "combined_score": 22.5, "metric": {}}] * 10)
    cfg = EvolveConfig()
    cfg.seed = 42
    cfg.budget.max_iterations = 2
    engine = _engine(tmp_path / "a", adapter, cfg)
    engine.initialize()
    summary_a = engine.run(max_iterations=2)
    engine_b = _engine(tmp_path / "b", adapter, cfg)
    engine_b.initialize()
    summary_b = engine_b.run(max_iterations=2)
    nodes_a = engine.store.get_nodes_by_experiment(engine.experiment_id)
    assert all(n.operator == OperatorType.REFINE for n in nodes_a if n.parent_id)
    assert summary_a.total_tokens == summary_b.total_tokens
    assert summary_a.bandit_active is False
    events = engine.store.get_events(engine.experiment_id)
    assert not any(e.type == "operator_selected" for e in events)


def test_bandit_summary_fields(tmp_path):
    cfg = _bandit_config(enabled=["refine", "threshold_calibrate"], min_explore=0.5)
    adapter = FakeAdapter()
    adapter.set_results([
        {"validity": 1.0, "combined_score": 22.0 + i * 0.3, "metric": {}}
        for i in range(20)
    ])
    engine = _engine(tmp_path, adapter, cfg)
    engine.initialize()
    summary = engine.run(max_iterations=12)
    assert summary.bandit_active is True
    assert len(summary.operator_counts) >= 2
    for op, posterior in summary.operator_posteriors.items():
        assert {"alpha", "beta", "mean"} <= set(posterior.keys())
    assert summary.generative_valid_rate is not None
    assert 0.0 <= summary.generative_valid_rate <= 1.0
    assert sum(summary.operator_tokens.values()) <= (
        summary.generate_tokens + summary.crossover_tokens
    )


def test_reward_uses_noise_delta(tmp_path):
    engine = _engine(tmp_path, FakeAdapter(), EvolveConfig())
    engine.initialize()
    engine._record_operator_outcome(
        OperatorType.REFINE, valid=True, delta=0.4, noise_delta=0.5,
    )
    engine._record_operator_outcome(
        OperatorType.REFINE, valid=True, delta=0.6, noise_delta=0.5,
    )
    engine._record_operator_outcome(
        OperatorType.REFINE, valid=False, delta=0.0, noise_delta=0.5,
    )
    row = engine.store.get_operator_stats(engine.experiment_id)["refine"]
    assert row["alpha"] == pytest.approx(2.0)
    assert row["beta"] == pytest.approx(3.0)
    assert int(row["n_valid"]) == 2
    assert row["sum_delta"] == pytest.approx(1.0)


def test_jev_deferred_updates_bandit(tmp_path, monkeypatch):
    cfg = _bandit_config(enabled=["refine", "threshold_calibrate"], min_explore=0.0)
    adapter = FakeAdapter()
    adapter.set_results([{"validity": 1.0, "combined_score": 23.0, "metric": {}}])
    engine = _engine(tmp_path, adapter, cfg)
    engine.initialize()
    parent = engine.tree.get_root()
    from faultevolve.cloud.tree import create_child_node

    child = create_child_node(
        parent, "# deferred", "intent", "hyp", OperatorType.THRESHOLD_CALIBRATE,
    )
    engine.tree.add_node(child)
    engine._deferred.append(
        __import__(
            "faultevolve.cloud.engine", fromlist=["DeferredCandidate"]
        ).DeferredCandidate(child.id, parent.id, 0.5, []),
    )
    assert engine.store.get_operator_stats(engine.experiment_id) == {}
    engine._flush_deferred(1)
    row = engine.store.get_operator_stats(engine.experiment_id).get(
        "threshold_calibrate", {},
    )
    assert row.get("n", 0) == 1.0


def test_config_operators_validation():
    with pytest.raises(ValidationError):
        OperatorsConfig(enabled=["recall_focus"])
    with pytest.raises(ValidationError):
        OperatorsConfig(enabled=["refine", "bogus"])
    with pytest.raises(ValidationError):
        OperatorsConfig(prior_alpha=0)
    assert EvolveConfig().operators.bandit is False


def test_cloud_modules_agnostic_pr7():
    root = Path(__file__).resolve().parents[1] / "src" / "faultevolve"
    pattern = re.compile(
        r"HDD|SMART|Backblaze|hard\s*disk|disk failure",
        re.IGNORECASE,
    )
    for rel in ("cloud/operators.py", "cloud/engine.py", "knowledge/retriever.py", "cloud/selection.py"):
        text = (root / rel).read_text(encoding="utf-8")
        assert pattern.search(text) is None, rel
