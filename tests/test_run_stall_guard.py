"""The run loop must not spin when no iteration can make progress.

Regression for a defect found through the Web UI's run launcher:

``run()`` loops on ``while self.metrics.iterations_done < max_iterations``, and
``iterations_done`` only advances on a *successful* iteration. Every skipped path
returns without touching it -- a refused selection (nothing in the tree can be
expanded, e.g. because the root evaluation failed) or a skipped round after a
transient LLM error -- so the loop condition stays true forever.

Two real local runs demonstrated it: an unexpandable tree produced **13,646** and
**2,250** ``selection_failed`` events, grew ``fe.db`` to 1.7 MB, and never reached
``max_iterations``. The guard bounds consecutive no-progress rounds and stops with
``stop_reason == "selection_stalled"``.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from faultevolve.cloud.engine import EvolutionEngine
from faultevolve.cloud.llm import MockLLM
from faultevolve.cloud.store import Store
from faultevolve.config import EvolveConfig
from faultevolve.worker.runner import FakeAdapter, FakeTaskSpec


@pytest.fixture
def temp_db():
    """Create a temporary database."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)
    yield db_path
    db_path.unlink(missing_ok=True)


@pytest.fixture
def fake_task_spec(tmp_path):
    """A task spec the FakeAdapter can evaluate without running any code."""
    return FakeTaskSpec(task_dir=tmp_path, init_code='"""init"""\npass\n')


def _make_engine(temp_db, fake_task_spec, adapter, config):
    return EvolutionEngine(
        config=config,
        task_adapter=adapter,
        task_spec=fake_task_spec,
        store=Store(temp_db),
        llm=MockLLM(),
        mock=True,
    )


def _base_config(stall_iterations: int, max_iterations: int = 10) -> EvolveConfig:
    config = EvolveConfig()
    config.budget.max_iterations = max_iterations
    config.budget.max_wall_hours = 0.1
    config.budget.stall_iterations = stall_iterations
    return config


def _event_types(engine) -> list[str]:
    return [event.type for event in engine.store.get_events(engine.experiment_id)]


def test_an_invalid_initial_evaluation_stops_before_searching(
    temp_db, fake_task_spec
):
    """A root the evaluator cannot score ends the run instead of seeding a search.

    Under the island protocol a 0-score invalid initialization is not a usable
    baseline, so every island closes with the reason before an attempt is made.
    The historical defect this file records was this same situation spinning to
    13,646 ``selection_failed`` events, so the "does not spin" half is still
    asserted -- it just stops being reachable through the search loop.
    """
    adapter = FakeAdapter()
    adapter.set_results([
        {
            "validity": 0.0,
            "combined_score": 0.0,
            "cost_time": 0.1,
            "error_info": "Evaluation failed: [WinError 5]",
            "metric": {},
        }
    ])

    engine = _make_engine(temp_db, fake_task_spec, adapter, _base_config(stall_iterations=5))
    engine.initialize()
    summary = engine.run(max_iterations=10)

    assert summary.iterations_done == 0
    assert summary.stop_reason == "init_evaluation_invalid"

    states = engine.store.get_island_states(engine.experiment_id)
    assert len(states) == 3, "each island is closed, none searched"
    assert all(s.status == "finished" for s in states)
    assert all(s.stop_reason == "init_evaluation_invalid" for s in states)
    assert sum(s.attempts for s in states) == 0

    types = _event_types(engine)
    assert "selection_failed" not in types
    assert types.count("run_stalled") == 0


def test_the_stall_limit_is_configurable(temp_db, fake_task_spec):
    adapter = FakeAdapter()

    engine = _make_engine(temp_db, fake_task_spec, adapter, _base_config(stall_iterations=2))
    engine.initialize()
    # Every iteration fails, which is what a refused selection does; the guard
    # must bound it at the configured limit regardless of island rotation.
    with patch.object(EvolutionEngine, "_run_one_iteration", return_value=False):
        summary = engine.run(max_iterations=10)

    assert summary.stop_reason == "selection_stalled"
    assert _event_types(engine).count("run_stalled") == 1


def test_a_healthy_run_is_not_cut_short(temp_db, fake_task_spec):
    """The guard must not fire on a run that is making progress."""
    adapter = FakeAdapter()  # default results are valid

    engine = _make_engine(
        temp_db, fake_task_spec, adapter, _base_config(stall_iterations=5, max_iterations=3)
    )
    engine.initialize()
    summary = engine.run(max_iterations=3)

    assert summary.iterations_done == 3
    assert summary.stop_reason == "max_iterations"
    assert "run_stalled" not in _event_types(engine)


def test_an_old_config_without_the_new_key_still_loads():
    """Backward compatibility: existing evolve.yaml files keep working."""
    config = EvolveConfig.from_dict({})
    assert config.budget.stall_iterations == 5
