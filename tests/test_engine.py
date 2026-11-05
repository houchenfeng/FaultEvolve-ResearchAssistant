"""Tests for the evolution engine with mock components."""

import tempfile
from pathlib import Path

import pytest

from faultevolve.cloud.engine import EvolutionEngine
from faultevolve.cloud.llm import MockLLM
from faultevolve.cloud.store import Store
from faultevolve.common.schemas import BranchMemory
from faultevolve.config import EvolveConfig, IslandsConfig
from faultevolve.worker.runner import FakeAdapter, FakeTaskSpec


class TrackingMockLLM(MockLLM):
    """MockLLM that tracks all prompts received."""

    def __init__(self) -> None:
        super().__init__()
        self.chat_history: list[list[dict[str, str]]] = []
        self.reasoning_history: list[list[dict[str, str]]] = []

    def chat(self, messages, model=None, temperature=None, max_tokens=None):
        self.chat_history.append(list(messages))
        return super().chat(messages, model, temperature, max_tokens)

    def chat_for_reasoning(self, messages, temperature=0.2):
        self.reasoning_history.append(list(messages))
        return super().chat_for_reasoning(messages, temperature)


@pytest.fixture
def temp_db():
    """Create a temporary database."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)
    yield db_path
    db_path.unlink(missing_ok=True)


@pytest.fixture
def fake_task_spec(tmp_path):
    """Create a fake task specification."""
    return FakeTaskSpec(
        task_dir=tmp_path,
        problem_md="Test problem for HDD failure prediction",
        prompt_md="You are an expert in storage reliability.",
        init_code='''"""Test init."""
import argparse
import pandas as pd
import numpy as np
import os

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--split", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    idx = pd.read_csv(os.path.join(args.data_dir, f"{args.split}_index.csv"))
    pred = pd.DataFrame({
        "serial_number": idx["serial_number"],
        "score": 0.5,
        "alarm": 0,
    })
    pred.to_csv(args.out, index=False)

if __name__ == "__main__":
    main()
''',
    )


@pytest.fixture
def config():
    """Create a test configuration."""
    config = EvolveConfig()
    config.budget.max_iterations = 3
    config.budget.max_wall_hours = 0.1
    return config


def test_engine_initialization(temp_db, fake_task_spec, config):
    """Test engine initialization."""
    store = Store(temp_db)
    llm = MockLLM()
    adapter = FakeAdapter()

    engine = EvolutionEngine(
        config=config,
        task_adapter=adapter,
        task_spec=fake_task_spec,
        store=store,
        llm=llm,
        mock=True,
    )

    exp_id = engine.initialize()

    assert exp_id is not None
    assert engine.tree is not None
    assert engine.tree.get_root() is not None


def test_engine_evaluates_init(temp_db, fake_task_spec, config):
    """Test that engine evaluates initial solution."""
    store = Store(temp_db)
    llm = MockLLM()
    adapter = FakeAdapter()
    adapter.set_results([
        {"validity": 1.0, "combined_score": 22.81, "cost_time": 5.0, "metric": {"f1_boot_std": 0.02}},
    ])

    engine = EvolutionEngine(
        config=config,
        task_adapter=adapter,
        task_spec=fake_task_spec,
        store=store,
        llm=llm,
        mock=True,
    )

    exp_id = engine.initialize()
    root = engine.tree.get_root()

    assert root is not None
    assert root.evidence.evaluation is not None
    assert root.evidence.evaluation.combined_score == 22.81


def test_engine_run_iterations(temp_db, fake_task_spec, config):
    """Test running multiple iterations."""
    store = Store(temp_db)
    llm = MockLLM()
    adapter = FakeAdapter()

    engine = EvolutionEngine(
        config=config,
        task_adapter=adapter,
        task_spec=fake_task_spec,
        store=store,
        llm=llm,
        mock=True,
    )

    engine.initialize()
    summary = engine.run(max_iterations=3)

    assert summary.iterations_done == 3
    assert summary.status == "finished"
    assert summary.best_score > 0


def test_engine_stops_on_target_score(temp_db, fake_task_spec, config):
    """Test that engine stops when target score is reached."""
    store = Store(temp_db)
    llm = MockLLM()
    adapter = FakeAdapter()

    adapter.set_results([
        {"validity": 1.0, "combined_score": 22.0, "cost_time": 1.0, "metric": {"f1_boot_std": 0.02}},
        {"validity": 1.0, "combined_score": 30.0, "cost_time": 1.0, "metric": {"f1_boot_std": 0.02}},
    ])

    config.stop.target_score = 25.0
    config.budget.max_iterations = 10

    engine = EvolutionEngine(
        config=config,
        task_adapter=adapter,
        task_spec=fake_task_spec,
        store=store,
        llm=llm,
        mock=True,
    )

    engine.initialize()
    summary = engine.run()

    assert summary.best_score >= 25.0
    assert summary.stop_reason == "target_score_reached"


def test_engine_handles_invalid_candidates(temp_db, fake_task_spec, config):
    """Test that engine handles invalid candidates."""
    store = Store(temp_db)
    llm = MockLLM()
    adapter = FakeAdapter()

    adapter.set_results([
        {"validity": 1.0, "combined_score": 22.0, "cost_time": 1.0, "metric": {}},
        {"validity": 0.0, "combined_score": 0.0, "cost_time": 0.5, "error_info": "Timeout"},
        {"validity": 1.0, "combined_score": 23.0, "cost_time": 1.0, "metric": {}},
    ])

    engine = EvolutionEngine(
        config=config,
        task_adapter=adapter,
        task_spec=fake_task_spec,
        store=store,
        llm=llm,
        mock=True,
    )

    engine.initialize()
    summary = engine.run(max_iterations=3)

    assert summary.iterations_done == 3
    assert summary.valid_rate < 1.0


def test_engine_creates_output_files(tmp_path, fake_task_spec, config):
    """Test that engine creates output files."""
    from faultevolve.cloud.engine import run_local_evolution

    task_dir = tmp_path / "task"
    task_dir.mkdir()

    (task_dir / "evaluator.py").write_text("def evaluate(p, **kw): return {'validity': 1, 'combined_score': 20, 'cost_time': 1, 'error_info': '', 'metric': {}}")
    (task_dir / "init.py").write_text(fake_task_spec.init_code)
    (task_dir / "problem.md").write_text("Test problem")
    (task_dir / "prompt.md").write_text("Test prompt")

    result = run_local_evolution(
        task_dir=task_dir,
        mock=True,
        max_iterations=2,
    )

    output_dir = Path(result["output_dir"])
    assert output_dir.exists()
    assert (output_dir / "run_summary.json").exists()
    assert (output_dir / "tree.json").exists()
    assert (output_dir / "events.jsonl").exists()


def test_engine_resume(temp_db, fake_task_spec, config):
    """Test resuming an experiment."""
    store = Store(temp_db)
    llm = MockLLM()
    adapter = FakeAdapter()

    engine1 = EvolutionEngine(
        config=config,
        task_adapter=adapter,
        task_spec=fake_task_spec,
        store=store,
        llm=llm,
        mock=True,
    )
    exp_id = engine1.initialize()
    engine1.run(max_iterations=2)

    engine2 = EvolutionEngine(
        config=config,
        task_adapter=adapter,
        task_spec=fake_task_spec,
        store=store,
        llm=llm,
        mock=True,
    )
    resumed_id = engine2.initialize(resume_id=exp_id)

    assert resumed_id == exp_id
    assert engine2.tree.get_root() is not None


def test_engine_resume_continues_same_tree(temp_db, fake_task_spec, config):
    """--resume continues the same tree structure."""
    store = Store(temp_db)
    llm = MockLLM()
    adapter = FakeAdapter()
    config.budget.max_iterations = 5
    config.islands = IslandsConfig.legacy_single()

    engine1 = EvolutionEngine(
        config=config,
        task_adapter=adapter,
        task_spec=fake_task_spec,
        store=store,
        llm=llm,
        mock=True,
    )
    exp_id = engine1.initialize()
    engine1.run(max_iterations=2)

    nodes_before = list(engine1.tree.nodes.keys())
    root_id_before = engine1.tree.get_root().id

    engine2 = EvolutionEngine(
        config=config,
        task_adapter=adapter,
        task_spec=fake_task_spec,
        store=store,
        llm=llm,
        mock=True,
    )
    engine2.initialize(resume_id=exp_id)
    engine2.run(max_iterations=3)

    assert engine2.tree.get_root().id == root_id_before
    for node_id in nodes_before:
        assert node_id in engine2.tree.nodes


def test_resume_continues_every_island_tree_without_new_roots(
    temp_db, fake_task_spec, config
):
    """A three-island resume keeps each island's own root and nodes.

    ``engine.tree`` ends on the island holding the global best, which is not
    necessarily the island it was on before the interruption, so continuity is
    asserted per island rather than on that single live attribute.
    """
    store = Store(temp_db)
    llm = MockLLM()
    adapter = FakeAdapter()
    config.budget.max_iterations = 5

    engine1 = EvolutionEngine(
        config=config,
        task_adapter=adapter,
        task_spec=fake_task_spec,
        store=store,
        llm=llm,
        mock=True,
    )
    exp_id = engine1.initialize()
    engine1.run(max_iterations=2)

    roots_before = {
        rt.island_id: rt.attrs["tree"].get_root().id for rt in engine1._island_nodes()
    }
    nodes_before = {
        rt.island_id: set(rt.attrs["tree"].nodes) for rt in engine1._island_nodes()
    }
    assert len(roots_before) == 3
    assert len(set(roots_before.values())) == 3, "three islands need three distinct roots"

    engine2 = EvolutionEngine(
        config=config,
        task_adapter=adapter,
        task_spec=fake_task_spec,
        store=store,
        llm=llm,
        mock=True,
    )
    engine2.initialize(resume_id=exp_id)
    engine2.run(max_iterations=3)

    roots_after = {
        rt.island_id: rt.attrs["tree"].get_root().id for rt in engine2._island_nodes()
    }
    assert roots_after == roots_before, "resume must not create a second root"
    for island_id, previous in nodes_before.items():
        live = set(engine2._coordinator.runtime(island_id).attrs["tree"].nodes)
        assert previous <= live, f"island {island_id} lost nodes across resume"

    best_id, _ = engine2._best_across_islands()
    assert best_id in engine2.tree.nodes, "live tree is the champion's island tree"


def test_repair_hint_appears_in_prompt(temp_db, fake_task_spec, config):
    """Test that repair hints from implementation errors appear in subsequent prompts."""
    store = Store(temp_db)
    llm = TrackingMockLLM()
    adapter = FakeAdapter()

    adapter.set_results([
        {"validity": 1.0, "combined_score": 22.0, "cost_time": 1.0, "metric": {}},
        {"validity": 0.0, "combined_score": 0.0, "cost_time": 0.5, "error_info": "SyntaxError: unexpected token at line 42"},
        {"validity": 1.0, "combined_score": 23.0, "cost_time": 1.0, "metric": {}},
        {"validity": 1.0, "combined_score": 24.0, "cost_time": 1.0, "metric": {}},
    ])

    config.budget.max_iterations = 4

    engine = EvolutionEngine(
        config=config,
        task_adapter=adapter,
        task_spec=fake_task_spec,
        store=store,
        llm=llm,
        mock=True,
    )

    engine.initialize()
    engine.run(max_iterations=4)

    all_prompts = "".join(
        msg["content"] for msgs in llm.chat_history for msg in msgs if msg["role"] == "user"
    )

    assert "修复提示" in all_prompts or "repair" in all_prompts.lower() or "error" in all_prompts.lower()


def test_refuted_hypothesis_appears_in_prompt(temp_db, fake_task_spec, config):
    """Test that refuted hypotheses appear in subsequent prompts."""
    store = Store(temp_db)
    llm = TrackingMockLLM()
    adapter = FakeAdapter()

    adapter.set_results([
        {"validity": 1.0, "combined_score": 22.0, "cost_time": 1.0, "metric": {}},
        {"validity": 1.0, "combined_score": 15.0, "cost_time": 1.0, "metric": {}},
        {"validity": 1.0, "combined_score": 14.0, "cost_time": 1.0, "metric": {}},
        {"validity": 1.0, "combined_score": 25.0, "cost_time": 1.0, "metric": {}},
    ])

    config.budget.max_iterations = 4
    config.reflection.hypothesis_delta_factor = 1.0

    engine = EvolutionEngine(
        config=config,
        task_adapter=adapter,
        task_spec=fake_task_spec,
        store=store,
        llm=llm,
        mock=True,
    )

    engine.initialize()

    root = engine.tree.get_root()
    memory = BranchMemory(
        summary="",
        top_insight_ids=[],
        refuted_hypotheses=["Hypothesis about threshold tuning that failed twice"],
    )
    engine.tree.update_branch_memory(root.id, memory)

    engine.run(max_iterations=3)

    all_prompts = "".join(
        msg["content"] for msgs in llm.chat_history for msg in msgs if msg["role"] == "user"
    )

    assert "证伪" in all_prompts or "refuted" in all_prompts.lower() or "threshold tuning" in all_prompts.lower()


def test_engine_tracks_reflect_purpose_tokens(temp_db, fake_task_spec, config):
    """Test that reflection tokens are tracked under 'reflect' purpose."""
    store = Store(temp_db)
    llm = MockLLM()
    adapter = FakeAdapter()

    adapter.set_results([
        {"validity": 1.0, "combined_score": 22.0, "cost_time": 1.0, "metric": {}},
        {"validity": 1.0, "combined_score": 25.0, "cost_time": 1.0, "metric": {}},
    ])

    config.budget.max_iterations = 2

    engine = EvolutionEngine(
        config=config,
        task_adapter=adapter,
        task_spec=fake_task_spec,
        store=store,
        llm=llm,
        mock=True,
    )

    engine.initialize()
    engine.run(max_iterations=2)

    llm_calls = store.get_llm_calls(engine.experiment_id)
    purposes = [call.purpose for call in llm_calls]

    assert "refine" in purposes
    assert "reflect" in purposes or len([p for p in purposes if p == "refine"]) >= 1


# === B-13 regression tests (appended) ===


def test_self_fix_calls_are_persisted(temp_db, fake_task_spec, config):
    """B-13：self_fix 的记账必须同步落到 llm_call 表。"""
    store = Store(temp_db)
    llm = MockLLM()
    adapter = FakeAdapter()

    engine = EvolutionEngine(
        config=config,
        task_adapter=adapter,
        task_spec=fake_task_spec,
        store=store,
        llm=llm,
        mock=True,
    )
    engine.initialize()
    parent = engine.tree.get_root()

    engine._attempt_perf_self_fix("print('x')", ["slow loop"], parent)
    engine._attempt_smoke_self_fix("print('x')", "Traceback: boom", parent)

    calls = store.get_llm_calls(engine.experiment_id)
    self_fix_calls = [c for c in calls if c.purpose == "self_fix"]

    assert len(self_fix_calls) == 2
    assert engine.metrics.self_fix_tokens == 2 * (100 + 200)

    persisted = sum(c.prompt_tokens + c.completion_tokens for c in calls)
    assert persisted == engine.metrics.total_tokens


def test_llm_call_table_partitions_total_tokens(temp_db, fake_task_spec, config):
    """不变式：SUM(llm_call tokens) == run_summary.total_tokens（B-13 的守卫）。"""
    store = Store(temp_db)
    llm = MockLLM()
    adapter = FakeAdapter()

    adapter.set_results([
        {"validity": 1.0, "combined_score": 22.0, "cost_time": 1.0, "metric": {}},
        {"validity": 1.0, "combined_score": 25.0, "cost_time": 1.0, "metric": {}},
    ])
    config.budget.max_iterations = 2

    engine = EvolutionEngine(
        config=config,
        task_adapter=adapter,
        task_spec=fake_task_spec,
        store=store,
        llm=llm,
        mock=True,
    )
    engine.initialize()
    engine.run(max_iterations=2)

    calls = store.get_llm_calls(engine.experiment_id)
    persisted = sum(c.prompt_tokens + c.completion_tokens for c in calls)

    assert persisted > 0
    assert persisted == engine.metrics.total_tokens
