"""PR #3.1 hotfix tests (reflection routing, stop_reason, traceback tail, smoke timing)."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from faultevolve.cloud.engine import EvolutionEngine
from faultevolve.cloud.llm import MockLLM
from faultevolve.cloud.store import Store
from faultevolve.cloud.tree import create_child_node, create_init_node
from faultevolve.common.metering import CallMetrics, RunMetrics
from faultevolve.common.schemas import (
    EvaluationResult,
    HypothesisStatus,
    NodeEvidence,
    OperatorType,
)
from faultevolve.common.textutil import sanitize_error_info
from faultevolve.config import EvolveConfig
from faultevolve.tasks.protocol import EvalResult
from faultevolve.worker.runner import FakeAdapter, FakeTaskSpec


@pytest.fixture
def temp_db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)
    yield db_path
    db_path.unlink(missing_ok=True)


@pytest.fixture
def fake_task_spec(tmp_path):
    return FakeTaskSpec(
        task_dir=tmp_path,
        problem_md="Test problem",
        prompt_md="Test prompt",
        init_code='print("init")',
    )


@pytest.fixture
def config():
    return EvolveConfig.from_yaml(Path("benchmark/hdd_mvp/evolve.yaml"))


def _make_engine(temp_db, fake_task_spec, config, adapter=None):
    store = Store(temp_db)
    llm = MockLLM()
    adapter = adapter or FakeAdapter()
    engine = EvolutionEngine(
        config=config,
        task_adapter=adapter,
        task_spec=fake_task_spec,
        store=store,
        llm=llm,
        mock=True,
    )
    engine.initialize()
    return engine, store


def test_positive_delta_goes_to_reflect_positive_even_if_layer_hypothesis(
    temp_db, fake_task_spec, config,
):
    engine, _ = _make_engine(temp_db, fake_task_spec, config)
    parent = engine.tree.get_root()
    parent.evidence = NodeEvidence(
        evaluation=EvaluationResult(
            validity=1.0, combined_score=20.0, cost_time=1.0, metric={},
        )
    )
    child = create_child_node(parent, "# v2", "intent", "hyp", OperatorType.REFINE)
    engine.tree.add_node(child)
    eval_result = EvalResult(
        validity=1.0, combined_score=25.0, cost_time=1.0, error_info="", metric={},
    )

    with patch.object(engine, "_reflect_positive") as pos, patch.object(
        engine, "_reflect_hypothesis_refuted",
    ) as refute, patch(
        "faultevolve.cloud.engine.LayeredReflector.reflect_with_llm",
        return_value=({"layer": "hypothesis", "causes": []}, CallMetrics()),
    ):
        engine._apply_reflection(
            parent, child, delta=3.0, noise_delta=0.5,
            eval_result=eval_result, adopted_cards=[],
        )

    pos.assert_called_once()
    refute.assert_not_called()


def test_positive_child_never_refuted(temp_db, fake_task_spec, config):
    engine, store = _make_engine(temp_db, fake_task_spec, config)
    parent = engine.tree.get_root()
    parent.hypothesis_fail_count = 1
    parent.evidence = NodeEvidence(
        evaluation=EvaluationResult(
            validity=1.0, combined_score=20.0, cost_time=1.0, metric={},
        )
    )
    child = create_child_node(parent, "# v2", "intent", "same hyp", OperatorType.REFINE)
    child.card_ids = ["card-a"]
    engine.tree.add_node(child)
    store.add_branch_refuted_card(engine.experiment_id, child.branch_id, "other")
    eval_result = EvalResult(
        validity=1.0, combined_score=24.0, cost_time=1.0, error_info="", metric={},
    )

    with patch(
        "faultevolve.cloud.engine.LayeredReflector.reflect_with_llm",
        return_value=({"layer": "hypothesis", "causes": []}, CallMetrics()),
    ):
        engine._apply_reflection(
            parent, child, delta=4.0, noise_delta=0.5,
            eval_result=eval_result, adopted_cards=["card-a"],
        )

    node = engine.tree.nodes[child.id]
    assert node.hypothesis_status != HypothesisStatus.REFUTED
    refuted_cards = store.get_branch_refuted_cards(engine.experiment_id, child.branch_id)
    assert "card-a" not in refuted_cards


def test_negative_delta_routing_unchanged(temp_db, fake_task_spec, config):
    engine, _ = _make_engine(temp_db, fake_task_spec, config)
    parent = engine.tree.get_root()
    parent.evidence = NodeEvidence(
        evaluation=EvaluationResult(
            validity=1.0, combined_score=20.0, cost_time=1.0, metric={},
        )
    )
    child = create_child_node(parent, "# v2", "intent", "hyp", OperatorType.REFINE)
    engine.tree.add_node(child)
    eval_result = EvalResult(
        validity=1.0, combined_score=10.0, cost_time=1.0, error_info="", metric={},
    )

    with patch.object(engine, "_reflect_hypothesis_refuted") as refute, patch(
        "faultevolve.cloud.engine.LayeredReflector.reflect_with_llm",
        return_value=({"layer": "hypothesis", "causes": []}, CallMetrics()),
    ):
        engine._apply_reflection(
            parent, child, delta=-5.0, noise_delta=0.5,
            eval_result=eval_result, adopted_cards=[],
        )

    refute.assert_called_once()


def test_stop_reason_max_iterations_when_stop_at_target_false(
    temp_db, fake_task_spec, config,
):
    config.stop.stop_at_target = False
    config.stop.target_score = 10.0
    config.budget.max_iterations = 2
    adapter = FakeAdapter()
    adapter.set_results([
        {"validity": 1.0, "combined_score": 22.0, "cost_time": 1.0, "metric": {}},
        {"validity": 1.0, "combined_score": 30.0, "cost_time": 1.0, "metric": {}},
    ])
    engine, _ = _make_engine(temp_db, fake_task_spec, config, adapter)
    summary = engine.run(max_iterations=2)

    assert summary.best_score >= 30.0
    assert engine.metrics.target_reached is True
    assert summary.stop_reason == "max_iterations"


def test_stop_reason_target_when_stop_at_target_true(temp_db, fake_task_spec, config):
    config.stop.stop_at_target = True
    config.stop.target_score = 25.0
    config.budget.max_iterations = 10
    adapter = FakeAdapter()
    adapter.set_results([
        {"validity": 1.0, "combined_score": 22.0, "cost_time": 1.0, "metric": {}},
        {"validity": 1.0, "combined_score": 30.0, "cost_time": 1.0, "metric": {}},
    ])
    engine, _ = _make_engine(temp_db, fake_task_spec, config, adapter)
    summary = engine.run()

    assert summary.stop_reason == "target_score_reached"


def test_error_info_keeps_tail():
    tail_line = "ValueError: final failure at end"
    error = ("X" * 2500) + "\n" + tail_line
    sanitized = sanitize_error_info(error, max_chars=800, keep_tail=True)

    assert tail_line in sanitized
    assert sanitized.startswith("... [truncated]")


def test_smoke_duration_and_avg_in_summary(temp_db, fake_task_spec, config):
    adapter = FakeAdapter()
    adapter.set_results([
        {"validity": 1.0, "combined_score": 22.0, "cost_time": 1.0, "metric": {}},
        {"validity": 1.0, "combined_score": 23.0, "cost_time": 1.0, "metric": {}},
    ])
    engine, _ = _make_engine(temp_db, fake_task_spec, config, adapter)

    def fake_smoke(code, parent):
        engine.metrics.add_smoke_duration(1.25)
        return EvalResult(
            validity=1.0, combined_score=0.0, cost_time=0.0, error_info="", metric={},
        ), 1.25

    engine._run_smoke_test = fake_smoke  # type: ignore[method-assign]
    summary = engine.run(max_iterations=1)

    assert summary.smoke_tests >= 1
    assert summary.avg_smoke_time_s is not None
    assert summary.avg_smoke_time_s > 0


def test_self_fix_tokens_separate_from_repair(temp_db, fake_task_spec, config):
    engine, _ = _make_engine(temp_db, fake_task_spec, config)
    engine.metrics = RunMetrics()
    engine.metrics.add_llm_call(
        CallMetrics(prompt_tokens=100, completion_tokens=50), "self_fix",
    )
    engine.metrics.add_llm_call(
        CallMetrics(prompt_tokens=200, completion_tokens=100), "repair",
    )

    assert engine.metrics.self_fix_tokens == 150
    assert engine.metrics.repair_tokens == 300


def test_iteration_complete_count_equals_iterations_done(temp_db, fake_task_spec, config):
    config.budget.max_iterations = 3
    adapter = FakeAdapter()
    adapter.set_results([
        {"validity": 1.0, "combined_score": 22.0, "cost_time": 1.0, "metric": {}},
        {"validity": 0.0, "combined_score": 0.0, "cost_time": 0.5, "error_info": "fail"},
        {"validity": 1.0, "combined_score": 23.0, "cost_time": 1.0, "metric": {}},
    ])
    engine, store = _make_engine(temp_db, fake_task_spec, config, adapter)
    summary = engine.run(max_iterations=3)

    events = store.get_events(engine.experiment_id)
    complete = [e for e in events if e.type == "iteration_complete"]
    assert len(complete) == summary.iterations_done
    assert summary.iteration_events == summary.iterations_done


# --------------------------------------------------------------------------
# node_created (PRD §16.2 "节点创建" -- 阶段 8)
# --------------------------------------------------------------------------
#
# These are here and not in tests/webapi/ because they assert engine behaviour
# (one event per node, ever), which the Web API's transport-level tests stub
# out. The bug they guard against is a *silently* short event stream: a node
# that nobody announces just doesn't appear in the UI timeline, and nothing
# errors.


def _node_created_events(store, experiment_id):
    return [e for e in store.get_events(experiment_id) if e.type == "node_created"]


def test_node_created_is_emitted_once_for_every_node(temp_db, fake_task_spec, config):
    config.budget.max_iterations = 3
    adapter = FakeAdapter()
    adapter.set_results([
        {"validity": 1.0, "combined_score": 22.0, "cost_time": 1.0, "metric": {}},
        {"validity": 0.0, "combined_score": 0.0, "cost_time": 0.5, "error_info": "fail"},
        {"validity": 1.0, "combined_score": 23.0, "cost_time": 1.0, "metric": {}},
    ])
    engine, store = _make_engine(temp_db, fake_task_spec, config, adapter)
    summary = engine.run(max_iterations=3)

    created = _node_created_events(store, engine.experiment_id)
    persisted = store.get_nodes_by_experiment(engine.experiment_id)

    # One per node -- neither fewer (a site forgot) nor more (a site double-logs).
    assert len(created) == len(persisted)
    assert len({e.payload["node_id"] for e in created}) == len(created)

    # Each island announces its own root: `iteration_complete` never fires for a
    # root, so before this event a UI drawing from the stream had no way to know
    # a tree had a beginning.
    roots = [e for e in created if e.payload["is_root"] is True]
    islands = {node.island_id for node in persisted}
    assert len(roots) == len(islands) == 3
    assert len({e.payload["node_id"] for e in roots}) == 3
    assert roots[0].payload["node_id"] == engine.tree.root_id
    assert roots[0].payload["parent_id"] is None


def test_node_created_precedes_the_iteration_that_made_it(
    temp_db, fake_task_spec, config
):
    """A node must be visible before the iteration closes, not after.

    This is the whole point of a separate event: the UI draws the node when it
    appears, and the iteration marker is a separate, later fact.
    """
    config.budget.max_iterations = 1
    engine, store = _make_engine(temp_db, fake_task_spec, config)
    engine.run(max_iterations=1)

    events = store.get_events(engine.experiment_id)
    order = [e.type for e in events]
    assert order.index("node_created") < order.index("iteration_complete")
    # ts ties are possible within one clock tick, so position is the assertion.
    assert order[0] == "node_created"


def test_node_created_payload_never_claims_a_score(temp_db, fake_task_spec, config):
    """`score` is null at birth, not 0.0 -- see _log_node_created's docstring."""
    engine, store = _make_engine(temp_db, fake_task_spec, config)
    created = _node_created_events(store, engine.experiment_id)
    assert created
    for event in created:
        assert event.payload["score"] is None
        assert set(event.payload) >= {
            "node_id",
            "parent_id",
            "depth",
            "operator",
            "status",
            "is_root",
            "is_repair",
        }


def test_a_resumed_run_does_not_re_announce_existing_nodes(
    temp_db, fake_task_spec, config
):
    """Re-announcing would double every node in the stream after a resume.

    ``load_from_store`` fills the tree's dict directly instead of going through
    the add funnel, and a resumed run finds a root so it never re-creates the
    init node -- between them, resuming must add nothing to the event stream.
    """
    config.budget.max_iterations = 1
    engine, store = _make_engine(temp_db, fake_task_spec, config)
    engine.run(max_iterations=1)
    before = len(_node_created_events(store, engine.experiment_id))
    assert before > 0

    reloaded = EvolutionEngine(
        config=config,
        task_adapter=FakeAdapter(),
        task_spec=fake_task_spec,
        store=store,
        llm=MockLLM(),
        mock=True,
    )
    resumed_id = reloaded.initialize(resume_id=engine.experiment_id)

    assert resumed_id == engine.experiment_id
    assert len(_node_created_events(store, resumed_id)) == before
    # The tree really was carried over, so the assertion above is about the
    # event stream and not about an empty tree.
    assert len(store.get_nodes_by_experiment(resumed_id)) > 1


