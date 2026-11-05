"""Offline tests for crossover / ensemble operator (PR #8)."""

from __future__ import annotations

import random
import re
import sqlite3
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from faultevolve.cloud.crossover import (
    branch_key,
    complementarity_overlap,
    select_crossover_partner,
    valid_node_count,
)
from faultevolve.cloud.engine import EvolutionEngine
from faultevolve.cloud.llm import MockLLM
from faultevolve.cloud.operators import (
    OperatorContext,
    OperatorType,
    build_user_message,
    select_operator,
)
from faultevolve.cloud.store import DDL, Store
from faultevolve.common.schemas import (
    GENERATIVE_OPERATORS,
    EvaluationResult,
    Node,
    NodeArtifact,
    NodeEvidence,
    NodeStatus,
    OperatorType as Op,
)
from faultevolve.config import EvolveConfig, OperatorsConfig
from faultevolve.worker.runner import FakeAdapter, FakeTaskSpec


def _task_spec(tmp_path: Path | None = None) -> FakeTaskSpec:
    return FakeTaskSpec(task_dir=tmp_path or Path("/tmp"))

from tests.test_operators_bandit import _bandit_config, _engine


def _node(
    id: str,
    parent_id: str | None,
    depth: int,
    score: float,
    operator: Op = Op.REFINE,
    fn_groups: list[dict[str, Any]] | None = None,
    metric: dict[str, Any] | None = None,
    cost_time: float = 1.0,
    experiment_id: str = "exp",
) -> Node:
    m = dict(metric or {})
    if fn_groups is not None:
        m["analysis"] = {"fn_groups": fn_groups}
    ev = EvaluationResult(
        validity=1.0,
        combined_score=score,
        cost_time=cost_time,
        metric=m,
    )
    return Node(
        id=id,
        experiment_id=experiment_id,
        parent_id=parent_id,
        branch_id="main",
        depth=depth,
        operator=operator,
        artifact=NodeArtifact(code=f"# {id}\nprint(1)", intent=""),
        evidence=NodeEvidence(evaluation=ev),
        status=NodeStatus.DONE,
    )


def test_partner_selection_diff_branch_complementary():
    root = _node("root", None, 0, 50.0, Op.INIT)
    a1 = _node("A1", "root", 1, 80.0)
    a2 = _node(
        "A2", "A1", 2, 90.0,
        fn_groups=[
            {"dimension": "x", "value": 1, "group_recall": 0.1},
            {"dimension": "y", "value": 2, "group_recall": 0.2},
        ],
    )
    b1 = _node(
        "B1", "root", 1, 85.0,
        fn_groups=[
            {"dimension": "x", "value": 1, "group_recall": 0.2},
            {"dimension": "y", "value": 2, "group_recall": 0.3},
        ],
    )
    c1 = _node(
        "C1", "root", 1, 84.0,
        fn_groups=[
            {"dimension": "x", "value": 1, "group_recall": 0.2},
            {"dimension": "z", "value": 3, "group_recall": 0.4},
        ],
    )
    nodes = {n.id: n for n in (root, a1, a2, b1, c1)}
    partner = select_crossover_partner(a2, nodes, top_quantile=1.0)
    assert partner is not None
    assert partner.id == "C1"
    assert branch_key(partner, nodes) != branch_key(a2, nodes)
    assert all(n.branch_id == "main" for n in nodes.values())


def test_partner_fallback_metric_difference():
    root = _node("root", None, 0, 50.0, Op.INIT)
    parent = _node("P", "root", 1, 80.0, metric={"a": 0.8, "b": 0.1})
    same = _node("S", "root", 1, 85.0, metric={"a": 0.8, "b": 0.1})
    diff = _node("D", "root", 1, 84.0, metric={"a": 0.2, "b": 0.9})
    nodes = {n.id: n for n in (root, parent, same, diff)}
    target = _node("T", "P", 2, 90.0, metric={"a": 0.8, "b": 0.1})
    nodes[target.id] = target
    partner = select_crossover_partner(target, nodes, top_quantile=1.0)
    assert partner is not None
    assert partner.id == "D"
    assert complementarity_overlap(target, same) > complementarity_overlap(target, diff)


def test_partner_top_quantile_excludes_low_scores():
    root = _node("root", None, 0, 50.0, Op.INIT)
    nodes: dict[str, Node] = {root.id: root}
    for i, score in enumerate([95, 90, 85, 70, 65, 60], start=1):
        n = _node(f"n{i}", "root", 1, float(score), metric={"a": 0.5, "b": i * 0.1})
        nodes[n.id] = n
    target = _node("tgt", "n1", 2, 92.0, metric={"a": 0.1, "b": 0.9})
    nodes[target.id] = target
    partner = select_crossover_partner(target, nodes, top_quantile=0.3)
    assert partner is not None
    assert partner.get_score() >= 85.0

    for nid in list(nodes):
        if nid.startswith("n") and nid != "n1":
            nodes[nid].parent_id = "n1"
            nodes[nid].depth = 2
    partner_none = select_crossover_partner(target, nodes, top_quantile=0.3)
    assert partner_none is None


def test_crossover_disabled_small_tree(tmp_path):
    cfg = _bandit_config()
    cfg.operators.crossover.enabled = True
    cfg.operators.crossover.min_valid_nodes = 4
    adapter = FakeAdapter()
    engine = _engine(tmp_path, adapter, cfg)
    engine.initialize()
    root = engine.tree.get_root()
    parent = _node("p1", root.id, 1, 80.0)
    _add_tree_node(engine, parent)
    partner = _node("p2", root.id, 1, 85.0, metric={"a": 0.1, "b": 0.9})
    _add_tree_node(engine, partner)
    avail = engine._available_operators(parent)
    assert Op.CROSSOVER not in avail

    extra = _node("p3", root.id, 1, 82.0, metric={"a": 0.2, "b": 0.8})
    _add_tree_node(engine, extra)
    assert valid_node_count(engine.tree.nodes) >= 4
    avail2 = engine._available_operators(parent)
    assert Op.CROSSOVER in avail2

    cfg_off = EvolveConfig()
    engine_off = _engine(tmp_path / "off", adapter, cfg_off)
    engine_off.initialize()
    assert Op.CROSSOVER not in engine_off._available_operators(parent)


def _add_tree_node(engine: EvolutionEngine, node: Node) -> None:
    node.experiment_id = engine.experiment_id
    # Synthetic fixtures carry no island; the tree owns exactly one, and an
    # off-island node is a data-integrity error rather than something to hide.
    node.island_id = engine.tree.island_id
    engine.tree.add_node(node)


def _force_expand(monkeypatch, engine: EvolutionEngine, node: Node) -> None:
    from faultevolve.cloud.selection import SelectionResult

    monkeypatch.setattr(
        engine.selector,
        "select",
        lambda _tree: SelectionResult(node=node, should_expand=True, prior={}),
    )


def _patch_crossover_partner(monkeypatch, partner: Node) -> None:
    import faultevolve.cloud.engine as engine_mod

    def _fake(node, nodes, **kwargs):
        if node.id != partner.id:
            return partner
        for n in nodes.values():
            if n.id != node.id and n.depth >= 1:
                return n
        return None

    monkeypatch.setattr(engine_mod, "select_crossover_partner", _fake)


def test_node_parents_recorded_no_schema_change(tmp_path, monkeypatch):
    cfg = _bandit_config(min_explore=0.0)
    cfg.operators.crossover.enabled = True
    cfg.operators.crossover.min_valid_nodes = 2
    adapter = FakeAdapter()
    adapter.set_results([{"validity": 1.0, "combined_score": 25.0, "metric": {}}] * 20)
    engine = _engine(tmp_path, adapter, cfg)
    engine.initialize()
    root = engine.tree.get_root()
    expand_from = _node("base", root.id, 1, 70.0, metric={"a": 0.5, "b": 0.5})
    partner = _node("partner", root.id, 1, 88.0, metric={"a": 0.1, "b": 0.9})
    _add_tree_node(engine, expand_from)
    _add_tree_node(engine, partner)

    def _force_crossover(_parent):
        return Op.CROSSOVER

    monkeypatch.setattr(engine, "_choose_operator", _force_crossover)
    _patch_crossover_partner(monkeypatch, partner)
    _force_expand(monkeypatch, engine, expand_from)
    engine.run(max_iterations=1)
    children = [n for n in engine.tree.nodes.values() if n.operator == Op.CROSSOVER]
    assert children
    child = children[0]
    parents = engine.store.get_node_parents(child.id)
    assert parents == [
        (child.parent_id, "primary"),
        ("partner", "secondary"),
    ]
    events = [e for e in engine.store.get_events(engine.experiment_id) if e.type == "crossover_parents"]
    assert events

    with engine.store._conn() as conn:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(node)")}
    expected = {
        "id", "experiment_id", "island_id", "parent_id", "branch_id", "depth", "operator",
        "artifact_json", "evidence_json", "status", "hypothesis_status",
        "visit_count", "expand_count", "children_json", "insight_ids_json",
        "card_ids_json", "branch_memory_json", "repair_attempted",
        "hypothesis_fail_count", "repair_count", "repair_parent_id",
        "error_class", "repair_exhausted", "created_at",
    }
    assert cols == expected

    old_db = tmp_path / "legacy.db"
    legacy_ddl = re.sub(
        r"\nCREATE TABLE IF NOT EXISTS node_parents.*?idx_node_parents_node ON node_parents\(node_id\);\n",
        "\n",
        DDL,
        count=1,
        flags=re.DOTALL,
    )
    with sqlite3.connect(old_db) as conn:
        conn.executescript(legacy_ddl)
    legacy_store = Store(old_db)
    with legacy_store._conn() as conn:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='node_parents'",
        ).fetchone()
    assert row is not None


def test_crossover_in_bandit(tmp_path, monkeypatch):
    chosen = select_operator(
        None,
        [Op.REFINE, Op.CROSSOVER],
        stats={Op.CROSSOVER: (50.0, 1.0)},
        rng=random.Random(0),
        min_explore=0.0,
        bandit=True,
    )
    assert chosen == Op.CROSSOVER
    assert Op.CROSSOVER in GENERATIVE_OPERATORS

    cfg = _bandit_config(min_explore=0.0)
    cfg.operators.crossover.enabled = True
    cfg.operators.crossover.min_valid_nodes = 2
    adapter = FakeAdapter()
    adapter.set_results([{"validity": 1.0, "combined_score": 25.0, "metric": {}}] * 5)
    engine = _engine(tmp_path, adapter, cfg)
    engine.initialize()
    root = engine.tree.get_root()
    expand_from = _node("base", root.id, 1, 70.0)
    pt = _node("pt", root.id, 1, 88.0, metric={"a": 0.1, "b": 0.9})
    _add_tree_node(engine, expand_from)
    _add_tree_node(engine, pt)
    monkeypatch.setattr(engine, "_choose_operator", lambda _p: Op.CROSSOVER)
    _patch_crossover_partner(monkeypatch, pt)
    _force_expand(monkeypatch, engine, expand_from)
    summary = engine.run(max_iterations=1)
    stats = engine.store.get_operator_stats(engine.experiment_id)
    assert "crossover" in stats
    assert summary.operator_counts.get("crossover", 0) >= 1


def test_prompt_truncation():
    long_code = "x" * 20000
    parent_a = _node("a", "root", 1, 80.0)
    parent_a.artifact.code = long_code
    parent_b = _node("b", "root", 1, 82.0)
    parent_b.artifact.code = long_code
    spec = _task_spec()
    ctx = OperatorContext(parent_a, spec, Op.CROSSOVER)
    ctx.set_partner(parent_b, max_chars=1000)
    msg = build_user_message(ctx)
    assert msg.count("[truncated]") == 2
    assert len(msg) < 2 * 1000 + 4000

    short_a = _node("sa", "root", 1, 80.0)
    short_a.artifact.code = "print(1)"
    short_b = _node("sb", "root", 1, 81.0)
    short_b.artifact.code = "print(2)"
    ctx2 = OperatorContext(short_a, spec, Op.CROSSOVER)
    ctx2.set_partner(short_b, max_chars=1000)
    assert "[truncated]" not in build_user_message(ctx2)


def test_crossover_runtime_guard_prompt():
    spec = _task_spec()
    a = _node("a", "r", 1, 80.0, cost_time=200.0)
    b = _node("b", "r", 1, 81.0, cost_time=200.0)
    ctx = OperatorContext(a, spec, Op.CROSSOVER)
    ctx.set_partner(b, runtime_budget_s=300.0)
    assert "超过" in build_user_message(ctx)

    a2 = _node("a2", "r", 1, 80.0, cost_time=100.0)
    b2 = _node("b2", "r", 1, 81.0, cost_time=100.0)
    ctx2 = OperatorContext(a2, spec, Op.CROSSOVER)
    ctx2.set_partner(b2, runtime_budget_s=300.0)
    low = build_user_message(ctx2)
    assert "运行时间之和约" not in low


def test_crossover_baseline_is_max_parent(tmp_path):
    cfg = EvolveConfig()
    adapter = FakeAdapter()
    adapter.set_results([
        {"validity": 1.0, "combined_score": 22.0, "metric": {}},
        {"validity": 1.0, "combined_score": 85.0, "metric": {}},
    ])
    engine = _engine(tmp_path, adapter, cfg)
    engine.initialize()
    root = engine.tree.get_root()
    parent = _node("pa", root.id, 1, 80.0)
    partner = _node("pb", root.id, 1, 90.0)
    _add_tree_node(engine, parent)
    _add_tree_node(engine, partner)
    from faultevolve.cloud.tree import create_child_node

    child = create_child_node(parent, "code", "i", "h", Op.CROSSOVER)
    engine.tree.add_node(child)
    engine._evaluate_child(
        parent,
        child,
        [],
        count_iteration=False,
        baseline_score=max(parent.get_score(), partner.get_score()),
    )
    updated = engine.tree.get_node(child.id)
    assert updated is not None
    assert updated.evidence.delta_score == pytest.approx(-5.0)


def test_crossover_skips_jev_prescreen(tmp_path):
    from faultevolve.cloud.judge import JudgeClient, PrescreenResult

    cfg = EvolveConfig()
    cfg.judge.provider = "mock"
    cfg.judge.prescreen = True
    adapter = FakeAdapter()
    engine = _engine(tmp_path, adapter, cfg)
    engine.judge = JudgeClient(cfg)
    engine.judge.enabled = True
    engine.judge.prescreen = MagicMock(return_value=PrescreenResult(decision="skip"))
    engine.initialize()
    root = engine.tree.get_root()
    parent = engine.tree.get_node(root.id)
    from faultevolve.cloud.tree import create_child_node

    child = create_child_node(parent, "c", "i", "h", Op.CROSSOVER)
    result = engine._apply_prescreen(parent, child, [])
    assert result.decision == "evaluate"
    engine.judge.prescreen.assert_not_called()


def test_crossover_tokens_own_stage(tmp_path, monkeypatch):
    cfg = _bandit_config(min_explore=0.0)
    cfg.operators.crossover.enabled = True
    cfg.operators.crossover.min_valid_nodes = 2
    adapter = FakeAdapter()
    adapter.set_results([{"validity": 1.0, "combined_score": 25.0, "metric": {}}] * 10)
    engine = _engine(tmp_path, adapter, cfg)
    engine.initialize()
    root = engine.tree.get_root()
    expand_from = _node("base", root.id, 1, 70.0)
    pt = _node("pt", root.id, 1, 88.0, metric={"a": 0.1, "b": 0.9})
    _add_tree_node(engine, expand_from)
    _add_tree_node(engine, pt)
    monkeypatch.setattr(engine, "_choose_operator", lambda _p: Op.CROSSOVER)
    _patch_crossover_partner(monkeypatch, pt)
    _force_expand(monkeypatch, engine, expand_from)
    summary = engine.run(max_iterations=1)
    assert summary.crossover_tokens > 0
    assert summary.generate_tokens < summary.total_tokens


def test_crossover_summary_fields(tmp_path, monkeypatch):
    cfg = _bandit_config(min_explore=0.0)
    cfg.operators.crossover.enabled = True
    cfg.operators.crossover.min_valid_nodes = 2
    adapter = FakeAdapter()
    adapter.set_results([{"validity": 1.0, "combined_score": 86.0, "metric": {}}] * 5)
    engine = _engine(tmp_path, adapter, cfg)
    engine.initialize()
    root = engine.tree.get_root()
    expand_from = _node("base", root.id, 1, 70.0)
    pt = _node("pt", root.id, 1, 90.0)
    _add_tree_node(engine, expand_from)
    _add_tree_node(engine, pt)
    monkeypatch.setattr(engine, "_choose_operator", lambda _p: Op.CROSSOVER)
    _patch_crossover_partner(monkeypatch, pt)
    _force_expand(monkeypatch, engine, expand_from)
    summary = engine.run(max_iterations=1)
    assert summary.crossover_count >= 1
    assert summary.crossover_valid_rate is not None
    assert 0.0 <= summary.crossover_valid_rate <= 1.0

    off = engine._crossover_summary()
    cfg.operators.crossover.enabled = False
    engine.config = cfg
    disabled = engine._crossover_summary()
    assert disabled["crossover_count"] == 0
    assert disabled["crossover_valid_rate"] is None


def test_crossover_excluded_from_discovery_harvest(tmp_path):
    cfg = EvolveConfig()
    cfg.discovery.enabled = True
    cfg.discovery.top_k_programs = 5
    engine = _engine(tmp_path, FakeAdapter(), cfg)
    engine.initialize()
    root = engine.tree.get_root()
    parent = _node("par", root.id, 1, 80.0)
    child = _node("cx", parent.id, 2, 85.0, Op.CROSSOVER)
    _add_tree_node(engine, parent)
    _add_tree_node(engine, child)
    out = engine._harvest_discovery_candidates()
    origin_ids = [item[0] for item in out]
    assert "cx" not in origin_ids


def test_crossover_requires_bandit():
    with pytest.raises(ValidationError):
        OperatorsConfig(crossover={"enabled": True})
    ok = OperatorsConfig(crossover={"enabled": True}, bandit=True)
    assert ok.crossover.enabled is True
    assert ok.crossover.min_valid_nodes == 4
    cfg = EvolveConfig.from_dict(
        {"operators": {"bandit": True, "crossover": {"enabled": True}}},
    )
    assert cfg.operators.crossover.enabled is True
    roundtrip = cfg.with_overrides(seed=99)
    assert roundtrip.operators.crossover.enabled is True


def test_default_behavior_unchanged_pr8(tmp_path):
    adapter = FakeAdapter()
    adapter.set_results([{"validity": 1.0, "combined_score": 22.5, "metric": {}}] * 10)
    cfg = EvolveConfig()
    cfg.seed = 42
    cfg.budget.max_iterations = 2
    cfg.smoke_test.enabled = False
    engine = _engine(tmp_path / "a", adapter, cfg)
    engine.initialize()
    summary_a = engine.run(max_iterations=2)
    engine_b = _engine(tmp_path / "b", adapter, cfg)
    engine_b.initialize()
    summary_b = engine_b.run(max_iterations=2)
    assert summary_a.total_tokens == summary_b.total_tokens
    assert summary_a.crossover_count == 0
    assert "crossover" not in (summary_a.operator_counts or {})
    events = engine.store.get_events(engine.experiment_id)
    assert not any(e.type.startswith("crossover_") for e in events)
    nodes = [n for n in engine.store.get_nodes_by_experiment(engine.experiment_id) if n.parent_id]
    assert all(n.operator == Op.REFINE for n in nodes)


def test_cloud_modules_agnostic_pr8():
    pattern = re.compile(
        r"HDD|SMART|Backblaze|hard\s*disk|disk failure",
        re.IGNORECASE,
    )
    root = Path(__file__).resolve().parents[1] / "src" / "faultevolve"
    paths = [
        root / "cloud" / "crossover.py",
        root / "cloud" / "operators.py",
        root / "cloud" / "engine.py",
        root / "common" / "metering.py",
    ]
    for path in paths:
        text = path.read_text(encoding="utf-8")
        assert pattern.search(text) is None, f"task-specific term in {path.name}"
