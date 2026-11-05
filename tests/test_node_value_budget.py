"""Tests for multi-objective node value and token budget control."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from faultevolve.cloud.budget import BudgetController
from faultevolve.cloud.engine import EvolutionEngine, run_local_evolution
from faultevolve.cloud.judge import JudgeClient, PrescreenResult
from faultevolve.cloud.llm import CallMetrics, MockLLM
from faultevolve.cloud.selection import EliteArchive, UCTSelector
from faultevolve.cloud.store import Store
from faultevolve.cloud.tree import Tree, create_child_node, create_init_node
from faultevolve.common.schemas import (
    EvaluationResult,
    HypothesisStatus,
    Node,
    NodeEvidence,
    NodeStatus,
    OperatorType,
)
from faultevolve.config import BudgetConfig, EvolveConfig
from faultevolve.tasks.hdd_adapter import HDDAdapter
from faultevolve.tasks.protocol import ObjectiveSpec
from faultevolve.worker.runner import FakeAdapter, FakeEvalResult, FakeTaskSpec


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "fe.db")


def _tree(store: Store) -> Tree:
    tree = Tree("exp-budget", store)
    root = create_init_node("exp-budget", "main", "# root")
    root.evidence = NodeEvidence(
        evaluation=EvaluationResult(
            validity=1.0,
            combined_score=20.0,
            cost_time=1.0,
            error_info="",
            metric={"auprc": 0.10, "recall_at_far": 0.10, "f1_boot_std": 0.02},
        )
    )
    root.status = NodeStatus.DONE
    tree.add_node(root)
    return tree


def _add(
    tree: Tree,
    parent: Node,
    node_id: str,
    score: float,
    metric: dict[str, Any],
) -> Node:
    child = create_child_node(parent, f"# {node_id}", "intent", "hyp", OperatorType.REFINE)
    child.id = node_id
    tree.add_node(child)
    tree.update_node_evidence(
        child.id,
        NodeEvidence(
            evaluation=EvaluationResult(
                validity=1.0,
                combined_score=score,
                cost_time=1.0,
                error_info="",
                metric=metric,
            )
        ),
    )
    child.status = NodeStatus.DONE
    return child


def _engine(tmp_path: Path, adapter, config: EvolveConfig | None = None) -> EvolutionEngine:
    config = config or EvolveConfig()
    store = Store(tmp_path / "fe.db")
    spec = FakeTaskSpec(task_dir=tmp_path)
    return EvolutionEngine(
        config=config,
        task_adapter=adapter,
        task_spec=spec,
        store=store,
        llm=MockLLM(enable_repair_scenario=False),
        mock=True,
        task_dir=tmp_path,
    )


def _multi_config() -> EvolveConfig:
    cfg = EvolveConfig()
    cfg.selection.value.mode = "multi"
    cfg.selection.value.rank_keys = ["auprc", "recall_at_far"]
    cfg.selection.value.noise_key = "f1_boot_std"
    return cfg


def test_q_scalar_default_unchanged(store):
    tree = _tree(store)
    root = tree.get_root()
    node_a = _add(tree, root, "A", 22.0, {})
    node_b = _add(tree, root, "B", 21.6, {})
    cfg = EvolveConfig()
    selector = UCTSelector(cfg)
    selector.set_initial_score(20.0)
    selector.update_best_score(22.0)
    selector.set_noise_delta(0.0)
    selector.set_objective_spec(["auprc"], ["f1_p10"], "f1_boot_std")
    assert selector._compute_q(node_a, root, tree) == 1.0
    assert selector._compute_q(node_b, root, tree) == pytest.approx(0.8)


def test_q_multi_prefers_rank_gain(store):
    tree = _tree(store)
    root = tree.get_root()
    node_a = _add(
        tree, root, "A", 22.0,
        {"auprc": 0.10, "recall_at_far": 0.10, "f1_boot_std": 0.02},
    )
    node_b = _add(
        tree, root, "B", 21.6,
        {"auprc": 0.20, "recall_at_far": 0.14, "f1_boot_std": 0.02},
    )
    selector = UCTSelector(_multi_config())
    selector.set_initial_score(20.0)
    selector.update_best_score(22.0)
    selector.set_noise_delta(0.0)
    selector.set_reference(root)
    assert selector._compute_q(node_b, root, tree) == pytest.approx(1.01)
    assert selector._compute_q(node_a, root, tree) == pytest.approx(1.0)
    assert selector._compute_q(node_b, root, tree) > selector._compute_q(node_a, root, tree)
    scalar = UCTSelector(EvolveConfig())
    scalar.set_initial_score(20.0)
    scalar.update_best_score(22.0)
    scalar.set_noise_delta(0.0)
    assert scalar._compute_q(node_a, root, tree) > scalar._compute_q(node_b, root, tree)


def test_q_noise_discount(store):
    tree = _tree(store)
    root = tree.get_root()
    node_a = _add(tree, root, "A", 22.0, {"f1_boot_std": 0.02})
    node_b = _add(tree, root, "B", 22.0, {"f1_boot_std": 0.04})
    cfg = _multi_config()
    cfg.selection.value.lambda_noise = 1.0
    selector = UCTSelector(cfg)
    selector.set_initial_score(20.0)
    selector.update_best_score(22.0)
    selector.set_noise_delta(0.0)
    selector.set_reference(root)
    assert selector._compute_q(node_a, root, tree) == pytest.approx(1.0)
    assert selector._compute_q(node_b, root, tree) == pytest.approx(0.0)
    cfg.selection.value.lambda_noise = 0.0
    selector2 = UCTSelector(cfg)
    selector2.set_initial_score(20.0)
    selector2.update_best_score(22.0)
    selector2.set_noise_delta(0.0)
    selector2.set_reference(root)
    assert selector2._compute_q(node_a, root, tree) == selector2._compute_q(node_b, root, tree)


def test_q_softmax_backup(store):
    tree = _tree(store)
    root = tree.get_root()
    x = _add(tree, root, "X", 22.0, {"auprc": 0.10, "recall_at_far": 0.10, "f1_boot_std": 0.02})
    _add(tree, x, "Y1", 22.0, {"auprc": 0.10, "recall_at_far": 0.10, "f1_boot_std": 0.02})
    _add(tree, x, "Y2", 20.0, {"auprc": 0.05, "recall_at_far": 0.05, "f1_boot_std": 0.02})
    cfg = _multi_config()
    cfg.selection.value.backup = "softmax"
    selector = UCTSelector(cfg)
    selector.set_initial_score(20.0)
    selector.update_best_score(22.0)
    selector.set_noise_delta(0.0)
    selector.set_reference(root)
    q_soft = selector._compute_q(x, root, tree)
    assert 0 < q_soft < 1.0
    cfg.selection.value.backup = "max"
    selector_max = UCTSelector(cfg)
    selector_max.set_initial_score(20.0)
    selector_max.update_best_score(22.0)
    selector_max.set_noise_delta(0.0)
    selector_max.set_reference(root)
    assert selector_max._compute_q(x, root, tree) == pytest.approx(1.0)


def test_elite_archive():
    archive = EliteArchive(2)
    data = [
        ("n1", 0.1, 0.9),
        ("n2", 0.5, 0.1),
        ("n3", 0.3, 0.2),
        ("n4", 0.4, 0.3),
    ]
    for nid, rank_q, thr_q in data:
        archive.update(nid, rank_q, thr_q)
    assert [nid for _, nid in archive.rank] == ["n2", "n4"]
    assert [nid for _, nid in archive.threshold] == ["n1", "n4"]
    assert archive.sizes() == {"rank": 2, "threshold": 2}
    assert len(archive.ids()) == 4
    archive.update("n2", 0.0, None)
    assert [nid for _, nid in archive.rank] == ["n4", "n2"]
    empty = EliteArchive(0)
    empty.update("n1", 1.0, 1.0)
    assert empty.sizes() == {"rank": 0, "threshold": 0}


def test_elite_selection_deterministic(store):
    tree = _tree(store)
    root = tree.get_root()
    n2 = _add(tree, root, "n2", 22.0, {"auprc": 0.2, "recall_at_far": 0.2, "f1_boot_std": 0.02})
    cfg = _multi_config()
    cfg.selection.value.elite_prob = 1.0
    cfg.selection.value.elite_m = 2
    cfg.seed = 7
    selector = UCTSelector(cfg)
    selector.set_initial_score(20.0)
    selector.update_best_score(22.0)
    selector.set_noise_delta(0.0)
    selector.set_reference(root)
    selector.elite.update("n2", 0.9, 0.9)
    result = selector.select(tree)
    assert result.node.id == "n2"
    assert result.should_expand is True
    selector_b = UCTSelector(cfg)
    selector_b.set_initial_score(20.0)
    selector_b.update_best_score(22.0)
    selector_b.set_noise_delta(0.0)
    selector_b.set_reference(root)
    selector_b.elite.update("n2", 0.9, 0.9)
    seq_a = [selector.select(tree).node.id for _ in range(3)]
    seq_b = [selector_b.select(tree).node.id for _ in range(3)]
    assert seq_a == seq_b
    scalar_cfg = EvolveConfig()
    scalar_cfg.seed = 7
    scalar = UCTSelector(scalar_cfg)
    scalar.set_initial_score(20.0)
    scalar.set_noise_delta(0.0)
    with patch.object(scalar._value_rng, "random") as mocked:
        scalar.select(tree)
        mocked.assert_not_called()


def test_missing_metric_fallback(tmp_path):
    cfg = _multi_config()
    cfg.budget.max_iterations = 1
    adapter = FakeAdapter()
    adapter.set_results([{"validity": 1.0, "combined_score": 22.0, "metric": {}}])
    engine = _engine(tmp_path, adapter, cfg)
    engine.initialize()
    summary = engine.run(max_iterations=1)
    events = engine.store.get_events(engine.experiment_id)
    kinds = [e.type for e in events]
    assert "value_mode_fallback" in kinds
    assert summary.value_mode == "scalar"
    assert not engine.selector.multi_active


def test_config_roundtrip_and_validation():
    cfg = EvolveConfig.from_dict({
        "selection": {"value": {"mode": "multi", "elite_m": 5}},
        "budget": {"stage_caps": {"reflect": 0.25}, "stagnation_window": 8},
    }).with_overrides(seed=1)
    assert cfg.selection.value.mode == "multi"
    assert cfg.selection.value.elite_m == 5
    assert cfg.budget.stage_caps == {"reflect": 0.25}
    assert cfg.budget.stagnation_window == 8
    assert cfg.seed == 1
    defaults = EvolveConfig()
    assert defaults.selection.value.mode == "scalar"
    assert defaults.budget.stage_caps == {}
    assert defaults.budget.stagnation_window == 0
    with pytest.raises(ValidationError):
        EvolveConfig.from_dict({"budget": {"stage_caps": {"bogus": 0.1}}})
    with pytest.raises(ValidationError):
        EvolveConfig.from_dict({"budget": {"stage_caps": {"reflect": 1.5}}})


class CountingReasonLLM(MockLLM):
    def __init__(self) -> None:
        super().__init__(enable_repair_scenario=False)
        self.reason_calls = 0

    def chat_for_reasoning(self, messages, temperature=0.2):
        self.reason_calls += 1
        return super().chat_for_reasoning(messages, temperature)


def test_budget_stage_cap_degrades_reflect(tmp_path):
    cfg = EvolveConfig()
    cfg.budget.max_tokens = 1000
    cfg.budget.stage_caps = {"reflect": 0.25}
    engine = _engine(tmp_path, FakeAdapter(), cfg)
    engine.llm = CountingReasonLLM()
    engine.operator = __import__(
        "faultevolve.cloud.operators", fromlist=["RefineOperator"]
    ).RefineOperator(engine.llm)
    engine.insight_extractor = __import__(
        "faultevolve.cloud.insights", fromlist=["InsightExtractor"]
    ).InsightExtractor(engine.llm)
    engine.initialize()
    parent = engine.tree.get_root()
    child = create_child_node(parent, "# c", "i", "h", OperatorType.REFINE)
    engine.tree.add_node(child)
    engine.tree.update_node_evidence(
        child.id,
        NodeEvidence(
            evaluation=EvaluationResult(
                validity=1.0,
                combined_score=25.0,
                cost_time=1.0,
                error_info="",
                metric={},
            )
        ),
    )
    eval_result = FakeEvalResult(validity=1.0, combined_score=25.0, cost_time=1.0, error_info="", metric={})
    engine.metrics.reflect_tokens = 300
    engine._apply_reflection(parent, child, 5.0, 0.5, eval_result, [])
    assert engine.llm.reason_calls == 0
    assert engine.metrics.stage_cap_hits.get("reflect", 0) == 1
    assert child.hypothesis_status == HypothesisStatus.SUPPORTED
    assert engine.store.get_insights_by_experiment(engine.experiment_id) == []
    engine.metrics.reflect_tokens = 0
    engine.llm.reason_calls = 0
    engine._apply_reflection(parent, child, 5.0, 0.5, eval_result, [])
    assert engine.llm.reason_calls == 1


def test_budget_stage_caps_repair_knowledge_jev(tmp_path):
    cfg = EvolveConfig()
    cfg.budget.max_tokens = 1000
    cfg.budget.stage_caps = {"reflect": 0.25, "repair": 0.25, "knowledge": 0.25, "jev": 0.25}
    cfg.judge.provider = "mock"
    cfg.judge.prescreen = True
    engine = _engine(tmp_path, FakeAdapter(), cfg)
    engine.judge = JudgeClient(cfg)
    engine.initialize()
    engine.metrics.repair_tokens = 300
    engine.metrics.knowledge_tokens = 300
    engine.metrics.jev_tokens = 300
    parent = engine.tree.get_root()
    failed = create_child_node(parent, "# bad", "i", "h", OperatorType.REFINE)
    engine.tree.add_node(failed)
    with patch.object(engine.repair_operator, "generate") as repair_gen:
        engine._attempt_repair(failed, parent, "err", "runtime")
        repair_gen.assert_not_called()
    assert engine.metrics.stage_cap_hits.get("repair", 0) == 1
    assert engine._retrieve_knowledge_cards(parent).cards == []
    assert engine.metrics.stage_cap_hits.get("knowledge", 0) == 1
    child = create_child_node(parent, "# c", "i", "h", OperatorType.REFINE)
    engine.tree.add_node(child)
    with patch.object(engine.judge, "prescreen") as prescreen:
        result = engine._apply_prescreen(parent, child, [])
        prescreen.assert_not_called()
    assert result.decision == "evaluate"
    events = [e.type for e in engine.store.get_events(engine.experiment_id)]
    assert events.count("budget_stage_cap_hit") == 3


def test_stagnation_stop(tmp_path):
    cfg = EvolveConfig()
    cfg.budget.stagnation_window = 3
    cfg.budget.min_iterations_before_stop = 0
    cfg.budget.max_iterations = 20
    adapter = FakeAdapter()
    adapter.set_results([
        {"validity": 1.0, "combined_score": 22.0, "metric": {}}
    ] * 30)
    engine = _engine(tmp_path, adapter, cfg)
    engine.llm = MockLLM(enable_repair_scenario=False)
    engine.operator = __import__(
        "faultevolve.cloud.operators", fromlist=["RefineOperator"]
    ).RefineOperator(engine.llm)
    engine.initialize()
    summary = engine.run(max_iterations=20)
    assert summary.stop_reason == "stagnation"
    assert summary.budget_stop_reason == "stagnation"
    assert len(engine.budget.best_history) == 4
    cfg2 = EvolveConfig()
    cfg2.budget.max_iterations = 5
    engine2 = _engine(tmp_path / "b", adapter, cfg2)
    engine2.initialize()
    summary2 = engine2.run(max_iterations=5)
    assert summary2.stop_reason == "max_iterations"


def test_tokens_per_point_cap_unit():
    ctrl = BudgetController(BudgetConfig(max_tokens=1000, tokens_per_point_cap=1000, min_iterations_before_stop=0))
    assert ctrl.check_stop(
        iterations_done=10,
        total_tokens=5000,
        best_score=22,
        initial_score=20,
        noise_delta=0.5,
    ) == "tokens_per_point_cap"
    assert ctrl.check_stop(
        iterations_done=10,
        total_tokens=5000,
        best_score=20.3,
        initial_score=20,
        noise_delta=0.5,
    ) == ""
    ctrl2 = BudgetController(BudgetConfig(min_iterations_before_stop=5))
    assert ctrl2.check_stop(
        iterations_done=3,
        total_tokens=100,
        best_score=25,
        initial_score=20,
        noise_delta=0.5,
    ) == ""


def test_expand_gating():
    cfg = BudgetConfig(max_tokens=1000, expand_gating=True, safety_factor=1.5)
    ctrl = BudgetController(cfg)
    ctrl.record_iteration(400, 1.0)
    assert ctrl.should_expand(500, False) is False
    assert ctrl.should_expand(500, True) is True
    assert ctrl.should_expand(100, False) is True
    cfg_off = BudgetConfig(expand_gating=False)
    assert BudgetController(cfg_off).should_expand(900, False) is True


def test_expand_gating_engine(tmp_path):
    cfg = EvolveConfig()
    cfg.budget.max_tokens = 1000
    cfg.budget.expand_gating = True
    cfg.budget.max_iterations = 2
    adapter = FakeAdapter()
    adapter.set_results([
        {"validity": 1.0, "combined_score": 24.0, "metric": {}},
        {"validity": 1.0, "combined_score": 24.0, "metric": {}},
    ])
    engine = _engine(tmp_path, adapter, cfg)
    engine.initialize()
    root = engine.tree.get_root()
    best = _add(engine.tree, root, "best", 30.0, {})
    _add(engine.tree, root, "mid", 25.0, {})
    _add(engine.tree, root, "mid2", 24.0, {})
    very_low = _add(engine.tree, root, "vl", 15.0, {})
    engine.selector.update_best_score(30.0)
    best_id = best.id
    engine.budget.record_iteration(400, 1.0)
    original_select = engine.selector.select

    def pick_low(tree):
        result = original_select(tree)
        return type(result)(node=very_low, should_expand=True, prior=result.prior)

    with patch.object(engine.budget, "should_expand", side_effect=lambda used, is_top: is_top):
        with patch.object(engine.selector, "select", side_effect=pick_low):
            engine.run(max_iterations=1)
    assert engine.metrics.expand_skipped_budget >= 1
    assert engine.tree.nodes[best_id].expand_count >= 1


def test_tokens_per_ros_point_in_summary(tmp_path):
    adapter = FakeAdapter()
    adapter.set_results([
        {"validity": 1.0, "combined_score": 22.0, "metric": {}},
        {"validity": 1.0, "combined_score": 24.0, "metric": {}},
        {"validity": 1.0, "combined_score": 24.0, "metric": {}},
    ] * 5)
    cfg = EvolveConfig()
    cfg.budget.max_iterations = 3
    engine = _engine(tmp_path, adapter, cfg)
    engine.llm = MockLLM(enable_repair_scenario=False)
    engine.operator = __import__(
        "faultevolve.cloud.operators", fromlist=["RefineOperator"]
    ).RefineOperator(engine.llm)
    engine.initialize()
    summary = engine.run(max_iterations=3)
    gain = summary.best_score - summary.initial_score
    if gain > 0:
        assert summary.tokens_per_ros_point == round(summary.total_tokens / gain, 2)
    flat = FakeAdapter()
    flat.set_results([{"validity": 1.0, "combined_score": 22.0, "metric": {}}] * 5)
    engine2 = _engine(tmp_path / "flat", flat, cfg)
    engine2.llm = MockLLM(enable_repair_scenario=False)
    engine2.operator = __import__(
        "faultevolve.cloud.operators", fromlist=["RefineOperator"]
    ).RefineOperator(engine2.llm)
    engine2.initialize()
    flat_summary = engine2.run(max_iterations=2)
    assert flat_summary.tokens_per_ros_point is None
    dumped = json.loads(summary.model_dump_json())
    for key in (
        "stage_cap_hits",
        "budget_stop_reason",
        "elite_archive_sizes",
        "expand_skipped_budget",
        "value_mode",
    ):
        assert key in dumped


def test_default_summary_unchanged(tmp_path):
    adapter = FakeAdapter()
    adapter.set_results([{"validity": 1.0, "combined_score": 22.5, "metric": {}}] * 10)
    cfg = EvolveConfig()
    cfg.seed = 42
    cfg.budget.max_iterations = 2
    engine = _engine(tmp_path / "a", adapter, cfg)
    engine.llm = MockLLM(enable_repair_scenario=False)
    engine.operator = __import__(
        "faultevolve.cloud.operators", fromlist=["RefineOperator"]
    ).RefineOperator(engine.llm)
    engine.initialize()
    summary_a = engine.run(max_iterations=2)
    engine_b = _engine(tmp_path / "b", adapter, cfg)
    engine_b.llm = MockLLM(enable_repair_scenario=False)
    engine_b.operator = __import__(
        "faultevolve.cloud.operators", fromlist=["RefineOperator"]
    ).RefineOperator(engine_b.llm)
    engine_b.initialize()
    summary_b = engine_b.run(max_iterations=2)
    assert summary_a.stage_cap_hits == {}
    assert summary_a.budget_stop_reason == ""
    assert summary_a.elite_archive_sizes == {"rank": 0, "threshold": 0}
    assert summary_a.expand_skipped_budget == 0
    assert summary_a.value_mode == "scalar"
    assert summary_a.total_tokens == summary_b.total_tokens


def test_hdd_adapter_objective_spec():
    adapter = HDDAdapter()
    assert isinstance(adapter, ObjectiveSpec)
    assert adapter.objectives() == ["auprc", "recall_at_far"]
    assert adapter.threshold_objectives() == ["f1_p10"]
    assert adapter.noise_metric() == "f1_boot_std"
    assert not isinstance(FakeAdapter(), ObjectiveSpec)


def test_multi_with_jev_prior(tmp_path):
    cfg = EvolveConfig()
    cfg.selection.policy = "jev_puct"
    cfg.selection.value.mode = "multi"
    cfg.selection.value.rank_keys = ["auprc", "recall_at_far"]
    cfg.selection.value.noise_key = "f1_boot_std"
    cfg.judge.provider = "mock"
    cfg.judge.prescreen = True
    cfg.budget.max_iterations = 6
    adapter = FakeAdapter()
    adapter.set_results([
        {"validity": 1.0, "combined_score": 22.0 + i * 0.2, "metric": {
            "auprc": 0.1 + i * 0.01,
            "recall_at_far": 0.1,
            "f1_boot_std": 0.02,
        }}
        for i in range(10)
    ])
    engine = _engine(tmp_path, adapter, cfg)
    engine.llm = MockLLM(enable_repair_scenario=False)
    engine.operator = __import__(
        "faultevolve.cloud.operators", fromlist=["RefineOperator"]
    ).RefineOperator(engine.llm)
    engine.initialize()
    priors = []
    original = engine.selector._compute_option_priors

    def capture(children, can_widen):
        p = original(children, can_widen)
        priors.append(dict(p))
        return p

    with patch.object(engine.selector, "_compute_option_priors", side_effect=capture):
        engine.run(max_iterations=6)
    assert priors
    assert engine.selector.prior_enabled or engine.config.judge.prior
