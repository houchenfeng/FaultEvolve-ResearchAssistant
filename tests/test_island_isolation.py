"""S2 acceptance: three real trees, one scheduler, no cross-island leakage.

TODO steps D2.1/D2.4/D2.6 (tests T04-T08). The isolation this file pins is the
difference between "three islands" and "one tree whose nodes carry a label": an
island's own counters, node set and subtree backups must not move when a sibling
improves. Everything here runs offline (MockLLM + FakeAdapter), so the only
numbers asserted are counters the engine itself maintains -- never a score that
came from the LLM.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

import pytest

from faultevolve.cloud.engine import EvolutionEngine
from faultevolve.cloud.llm import MockLLM
from faultevolve.cloud.store import Store
from faultevolve.cloud.tree import create_child_node
from faultevolve.common.schemas import IslandStatus, OperatorType
from faultevolve.config import EvolveConfig
from faultevolve.worker.runner import FakeAdapter, FakeTaskSpec

ISLANDS = ("a", "b", "c")


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
        init_code='"""init"""\npass\n',
        prompt_md="SHARED-TASK-INSTRUCTION",
    )


def _island_config(
    *,
    max_iterations: int = 6,
    max_attempts: int = 50,
    stall_iterations: int = 100,
) -> EvolveConfig:
    """Three islands with a small, equal budget so rotation is observable."""
    config = EvolveConfig()
    config.budget.max_iterations = max_iterations
    config.budget.max_wall_hours = 0.5
    config.budget.stall_iterations = stall_iterations
    config.smoke_test.enabled = False
    for spec in config.islands.islands:
        spec.max_attempts = max_attempts
    return config


def _make_engine(temp_db, fake_task_spec, adapter, config, llm=None) -> EvolutionEngine:
    engine = EvolutionEngine(
        config=config,
        task_adapter=adapter,
        task_spec=fake_task_spec,
        store=Store(temp_db),
        llm=llm or MockLLM(),
        mock=True,
    )
    engine.initialize()
    return engine


def _valid(score: float = 22.0) -> dict[str, Any]:
    return {"validity": 1.0, "combined_score": score, "cost_time": 1.0, "metric": {}}


def _invalid(reason: str) -> dict[str, Any]:
    return {
        "validity": 0.0,
        "combined_score": 0.0,
        "cost_time": 0.5,
        "error_info": reason,
        "metric": {},
    }


def _persisted_nodes(engine: EvolutionEngine) -> dict[str, set[str]]:
    """Node ids per island, straight from the store rather than the cache."""
    out: dict[str, set[str]] = {}
    for island_id in ISLANDS:
        rows = engine.store.get_nodes_by_experiment(
            engine.experiment_id, island_id=island_id
        )
        out[island_id] = {node.id for node in rows}
    return out


def _tree_of(engine: EvolutionEngine, island_id: str):
    return engine._coordinator.runtime(island_id).attrs["tree"]


def _events(engine: EvolutionEngine) -> list[Any]:
    return engine.store.get_events(engine.experiment_id)


def _event_types(engine: EvolutionEngine) -> list[str]:
    return [e.type for e in engine.store.get_events(engine.experiment_id)]


def _island_states(engine: EvolutionEngine) -> dict[str, Any]:
    return {
        s.island_id: s
        for s in engine.store.get_island_states(engine.experiment_id)
    }


# --------------------------------------------------------------------------
# T04 -- three roots, three disjoint node sets, cache == store
# --------------------------------------------------------------------------


def test_every_island_loads_only_its_own_nodes(temp_db, fake_task_spec):
    adapter = FakeAdapter()
    adapter.set_results([_valid()] + [_valid(23.0 + i) for i in range(20)])
    engine = _make_engine(
        temp_db, fake_task_spec, adapter, _island_config(max_iterations=6)
    )
    engine.run(max_iterations=6)

    persisted = _persisted_nodes(engine)
    assert all(persisted[i] for i in ISLANDS), "no island may be empty"
    union = set().union(*persisted.values())
    assert len(union) == sum(len(ids) for ids in persisted.values()), (
        "a node id appears in two islands: the trees are not disjoint"
    )

    roots = {i: _tree_of(engine, i).root_id for i in ISLANDS}
    assert len(set(roots.values())) == 3, "each island owns exactly one root"
    for island_id, root_id in roots.items():
        assert root_id in persisted[island_id]

    # The in-memory view is what selection reads; a stale or over-wide cache would
    # let one island expand another's node without touching the store.
    for island_id in ISLANDS:
        tree = _tree_of(engine, island_id)
        tree.load_from_store()
        assert set(tree.nodes) == persisted[island_id]
        assert {n.island_id for n in tree.nodes.values()} == {island_id}
        for node in tree.nodes.values():
            if node.parent_id is not None:
                assert node.parent_id in tree.nodes
            for child_id in node.children:
                assert child_id in tree.nodes


def test_island_best_does_not_leak_into_a_sibling_backup(temp_db, fake_task_spec):
    """Max-backup propagation stops at the island root."""
    adapter = FakeAdapter()
    adapter.set_results([_valid()] + [_valid(30.0) for _ in range(20)])
    engine = _make_engine(temp_db, fake_task_spec, adapter, _island_config(max_iterations=3))
    engine.run(max_iterations=3)

    for island_id in ISLANDS:
        tree = _tree_of(engine, island_id)
        root = tree.get_root()
        assert root is not None
        best_id, best_score = tree.get_island_best()
        assert best_score == tree.subtree_best[root.id]
        for sibling in (i for i in ISLANDS if i != island_id):
            sibling_tree = _tree_of(engine, sibling)
            assert set(sibling_tree.subtree_best) <= set(sibling_tree.nodes)
            if best_id is not None:
                assert best_id not in sibling_tree.nodes


# --------------------------------------------------------------------------
# T05 -- a candidate whose parent lives in another island is refused
# --------------------------------------------------------------------------


def test_foreign_parent_is_rejected_without_polluting_either_tree(
    temp_db, fake_task_spec
):
    adapter = FakeAdapter()
    engine = _make_engine(temp_db, fake_task_spec, adapter, _island_config(max_iterations=1))
    before = _persisted_nodes(engine)

    b_root = _tree_of(engine, "b").get_root()
    a_tree = engine.tree
    assert a_tree.island_id == "a"

    # A node that carries island b's label cannot enter a's tree.
    foreign = create_child_node(b_root, "# foreign", "intent", "hyp", OperatorType.REFINE)
    assert foreign.island_id == "b"
    with pytest.raises(ValueError, match="island"):
        a_tree.add_node(foreign)

    # A node labelled a but hanging off b's root is refused as well: a's tree does
    # not know that parent, and "unknown parent" is the honest description.
    mislabelled = create_child_node(
        b_root, "# mislabelled", "intent", "hyp", OperatorType.REFINE
    )
    mislabelled.island_id = "a"
    with pytest.raises(ValueError, match="unknown parent"):
        a_tree.add_node(mislabelled)

    after = _persisted_nodes(engine)
    assert after == before, "a refused candidate must not appear in either tree"
    assert foreign.id not in a_tree.nodes
    assert b_root.children == []


def test_island_view_refuses_a_second_root(temp_db, fake_task_spec):
    """Two roots in one island is data corruption, not something to paper over."""
    adapter = FakeAdapter()
    engine = _make_engine(temp_db, fake_task_spec, adapter, _island_config(max_iterations=1))
    tree = engine.tree
    duplicate = create_child_node(tree.get_root(), "# dup", "i", "h", OperatorType.REFINE)
    duplicate.parent_id = None
    duplicate.island_id = tree.island_id
    with pytest.raises(ValueError, match="already has root"):
        tree.add_node(duplicate)


# --------------------------------------------------------------------------
# T06 -- one island's progress leaves the siblings' counters untouched
# --------------------------------------------------------------------------


def _counters(state) -> dict[str, Any]:
    return {
        "attempts": state.attempts,
        "valid_evaluations": state.valid_evaluations,
        "invalid_evaluations": state.invalid_evaluations,
        "consecutive_failures": state.consecutive_failures,
        "stall_valid_evals": state.stall_valid_evals,
        "infra_fail_streak": state.infra_fail_streak,
        "best_score": state.best_score,
        "best_node_id": state.best_node_id,
        "status": state.status,
    }


def _tree_snapshot(tree) -> dict[str, Any]:
    return {
        "nodes": {n.id: (n.visit_count, n.get_score()) for n in tree.nodes.values()},
        "subtree_best": dict(tree.subtree_best),
        "children": {n.id: list(n.children) for n in tree.nodes.values()},
        "best": tree.get_island_best(),
    }


def test_an_island_attempt_moves_only_that_island(temp_db, fake_task_spec):
    """A improves; B and C are byte-for-byte the same afterwards."""
    adapter = FakeAdapter()
    adapter.set_results([_valid()] + [_valid(99.0) for _ in range(20)])
    engine = _make_engine(temp_db, fake_task_spec, adapter, _island_config(max_iterations=1))

    states_before = {i: _counters(_island_states(engine)[i]) for i in ISLANDS}
    snapshots = {i: _tree_snapshot(_tree_of(engine, i)) for i in ISLANDS}
    events_before = len(_event_types(engine))

    # One attempt, taken by island a, straight through the real code path.
    engine._activate_island("a")
    assert engine._run_one_iteration() is True

    states_after = {i: _counters(_island_states(engine)[i]) for i in ISLANDS}
    assert states_after["a"]["attempts"] == states_before["a"]["attempts"] + 1
    assert states_after["a"]["valid_evaluations"] > states_before["a"]["valid_evaluations"]
    for sibling in ("b", "c"):
        assert states_after[sibling] == states_before[sibling], sibling

    for sibling in ("b", "c"):
        assert _tree_snapshot(_tree_of(engine, sibling)) == snapshots[sibling], sibling

    # Island a's champion is not readable as anyone else's best.
    assert states_after["a"]["best_score"] > states_before["a"]["best_score"]
    for sibling in ("b", "c"):
        assert states_after[sibling]["best_score"] == states_before[sibling]["best_score"]
        assert states_after[sibling]["best_node_id"] != states_after["a"]["best_node_id"]

    new_events = engine.store.get_events(engine.experiment_id)[events_before:]
    island_of_new = {e.payload.get("island_id") for e in new_events if "island_id" in e.payload}
    assert island_of_new == {"a"}, f"a sibling was logged during a's attempt: {island_of_new}"


# --------------------------------------------------------------------------
# T07 -- a paused island is skipped, never mistaken for finished
# --------------------------------------------------------------------------


def test_rotation_is_round_robin_and_skips_a_paused_island(temp_db, fake_task_spec):
    adapter = FakeAdapter()
    engine = _make_engine(temp_db, fake_task_spec, adapter, _island_config(max_iterations=1))
    coord = engine._coordinator

    assert [coord.next_runnable().island_id for _ in range(6)] == [
        "a", "b", "c", "a", "b", "c",
    ]

    coord.runtime("b").state.status = IslandStatus.PAUSED
    coord.runtime("b").state.stop_reason = "infra_failures"
    assert [coord.next_runnable().island_id for _ in range(4)] == ["a", "c", "a", "c"]
    assert not coord.all_finished(), "a paused island is not a finished one"
    assert [i for i in coord.order if coord.runtime(i).runnable] == ["a", "c"]

    # Resuming puts b back in the ring without starving it.
    coord.runtime("b").state.status = IslandStatus.RUNNING
    resumed = [coord.next_runnable().island_id for _ in range(3)]
    assert sorted(resumed) == ["a", "b", "c"], resumed

    coord.persist_cursor()
    assert coord.store.get_scheduler_state(engine.experiment_id) is not None


def test_a_paused_island_does_not_stop_the_parent_run(temp_db, fake_task_spec):
    adapter = FakeAdapter()
    adapter.set_results([_valid()] + [_valid(25.0 + i) for i in range(20)])
    engine = _make_engine(temp_db, fake_task_spec, adapter, _island_config(max_iterations=4))
    engine._coordinator.runtime("b").state.status = IslandStatus.PAUSED

    summary = engine.run(max_iterations=4)

    states = _island_states(engine)
    assert states["a"].attempts == 2
    assert states["c"].attempts == 2
    assert states["b"].attempts == 0, "a paused island must take no attempt"
    assert states["b"].status == "paused"
    assert summary.iterations_done == 4
    assert "all_islands_stopped" not in _event_types(engine)


def test_the_run_ends_when_no_island_is_runnable(temp_db, fake_task_spec):
    """No runnable island closes the run instead of busy-waiting."""
    adapter = FakeAdapter()
    engine = _make_engine(temp_db, fake_task_spec, adapter, _island_config(max_iterations=50))
    for island_id in ISLANDS:
        rt = engine._coordinator.runtime(island_id)
        rt.state.status = IslandStatus.FINISHED
        rt.state.stop_reason = "max_attempts"

    summary = engine.run(max_iterations=50)

    assert summary.iterations_done == 0
    assert summary.stop_reason == "all_islands_stopped"
    types = _event_types(engine)
    assert types.count("all_islands_stopped") == 1
    assert "run_stalled" not in types

    finished = [
        event for event in _events(engine) if event.type == "run_finished"
    ][-1]
    islands = finished.payload["islands"]
    assert set(islands) == set(ISLANDS)
    assert {i: islands[i]["stop_reason"] for i in ISLANDS} == {
        island_id: "max_attempts" for island_id in ISLANDS
    }


# --------------------------------------------------------------------------
# T08 -- invalid generations still spend the island budget, then close it
# --------------------------------------------------------------------------


def test_consecutive_invalid_candidates_hit_the_attempt_cap(
    temp_db, fake_task_spec
):
    adapter = FakeAdapter()
    adapter.set_results([_valid()] + [_invalid("candidate raised") for _ in range(20)])
    engine = _make_engine(
        temp_db,
        fake_task_spec,
        adapter,
        _island_config(max_iterations=30, max_attempts=2),
    )

    summary = engine.run(max_iterations=30)

    states = _island_states(engine)
    assert {i: states[i].attempts for i in ISLANDS} == {"a": 2, "b": 2, "c": 2}
    for island_id in ISLANDS:
        state = states[island_id]
        assert state.status == "finished"
        assert state.stop_reason == "max_attempts"
        assert state.invalid_evaluations >= 1
        assert state.valid_evaluations == 1, "only the shared init scored validly"
    assert summary.iterations_done <= 6
    assert "all_islands_stopped" in _event_types(engine)

    stopped = [
        e for e in engine.store.get_events(engine.experiment_id)
        if e.type == "island_stopped"
    ]
    assert len(stopped) == 3
    assert {e.payload["island_id"] for e in stopped} == set(ISLANDS)
    for event in stopped:
        assert event.payload["attempts"] == 2


# --------------------------------------------------------------------------
# T-adjacent (D2.5) -- the profile differences reach the real prompts
# --------------------------------------------------------------------------


class _RecordingLLM:
    """Keeps every prompt so profile differences are observable, not assumed."""

    def __init__(self) -> None:
        self._inner = MockLLM(enable_repair_scenario=False)
        self.prompts: list[str] = []

    def _record(self, messages: list[dict[str, str]]) -> None:
        self.prompts.append("\n".join(str(m.get("content", "")) for m in messages))

    def chat(self, messages, **kwargs: Any):
        self._record(messages)
        return self._inner.chat(messages, **kwargs)

    def chat_for_reasoning(self, messages, **kwargs: Any):
        self._record(messages)
        return self._inner.chat_for_reasoning(messages, **kwargs)


def test_island_focus_reaches_only_its_own_prompts(temp_db, fake_task_spec):
    """Three islands, one task: only the strategy text differs in the prompt.

    This is the assertion that makes D2.5 real rather than cosmetic -- an island
    whose focus string never reaches the LLM is a label in the UI, and an island
    that sees a sibling's focus is not an independent strategy.
    """
    adapter = FakeAdapter()
    adapter.set_results([_valid()] + [_valid(25.0 + i) for i in range(20)])
    llm = _RecordingLLM()
    config = _island_config(max_iterations=6)
    engine = _make_engine(temp_db, fake_task_spec, adapter, config, llm=llm)
    engine.run(max_iterations=6)

    focuses = {spec.island_id: spec.focus for spec in config.islands.islands}
    assert len(set(focuses.values())) == 3
    task_text = fake_task_spec.prompt_md

    tagged = {
        island_id: [p for p in llm.prompts if focuses[island_id] in p]
        for island_id in ISLANDS
    }
    for island_id in ISLANDS:
        assert tagged[island_id], f"island {island_id} never saw its own focus"
    for island_id, own in tagged.items():
        foreign = [i for i in ISLANDS if i != island_id]
        for prompt in own:
            for other in foreign:
                assert focuses[other] not in prompt, (
                    f"island {island_id}'s prompt carried island {other}'s focus"
                )
            assert task_text in prompt, "the shared task statement must be identical"

    # Metering follows the request: every llm_call row names the island that paid
    # for it, so the run's cost can be rolled up per island (S4 reads this).
    calls = engine.store.get_llm_calls(engine.experiment_id)
    assert calls, "the run must have metered its LLM calls"
    assert {c.island_id for c in calls} <= set(ISLANDS)
    for island_id in ISLANDS:
        scoped = engine.store.get_llm_calls(engine.experiment_id, island_id=island_id)
        assert {c.island_id for c in scoped} == {island_id}


def test_profile_bias_narrows_the_pool_unless_the_draw_explores(
    temp_db, fake_task_spec
):
    """exploration_ratio=0 keeps an island on its profile; =1 lets everything in."""
    avail = [
        OperatorType.REFINE,
        OperatorType.RECALL_FOCUS,
        OperatorType.INJECT,
        OperatorType.THRESHOLD_CALIBRATE,
    ]
    adapter = FakeAdapter()
    engine = _make_engine(temp_db, fake_task_spec, adapter, _island_config(max_iterations=1))

    for ratio, expected in (
        (0.0, {"a": {"refine", "inject"}, "b": {"recall_focus", "threshold_calibrate"}}),
        (1.0, None),
    ):
        for spec in engine.config.islands.islands:
            spec.exploration_ratio = ratio
        for island_id in ("a", "b"):
            engine._activate_island(island_id)
            out = engine._apply_island_bias(list(avail))
            if expected is None:
                assert {op.value for op in out} == {op.value for op in avail}
            else:
                assert {op.value for op in out} == expected[island_id]


def test_exploration_draws_are_island_local_and_reproducible(
    temp_db, fake_task_spec, tmp_path
):
    """Touching B and C must not advance A's random stream (seeded, per island)."""
    avail = [
        OperatorType.REFINE,
        OperatorType.RECALL_FOCUS,
        OperatorType.INJECT,
        OperatorType.THRESHOLD_CALIBRATE,
    ]

    def draws(db: Path, touch_siblings: bool) -> list[str]:
        adapter = FakeAdapter()
        config = _island_config(max_iterations=1)
        for spec in config.islands.islands:
            spec.exploration_ratio = 0.5
        engine = _make_engine(db, fake_task_spec, adapter, config)
        engine._activate_island("a")
        if touch_siblings:
            for _ in range(30):
                for sibling in ("b", "c"):
                    engine._activate_island(sibling)
                    engine._apply_island_bias(list(avail))
                engine._activate_island("a")
        out: list[str] = []
        for _ in range(20):
            engine._activate_island("a")
            out.append(",".join(sorted(op.value for op in engine._apply_island_bias(list(avail)))))
        return out

    quiet = draws(Path(temp_db), touch_siblings=False)
    busy_db = Path(temp_db).with_name("sibling_busy.db")
    busy = draws(busy_db, touch_siblings=True)
    busy_db.unlink(missing_ok=True)
    assert quiet == busy, "a sibling's draws changed this island's stream"
    assert len(set(quiet)) == 2, "a 50% escape ratio must show both behaviours"


def test_repair_candidate_spends_an_island_attempt(temp_db, fake_task_spec):
    """A repair is a candidate, so it is charged to the same cap (D2.6)."""
    adapter = FakeAdapter()
    adapter.set_results([
        _valid(22.0),
        _invalid("NameError: name 'undefined_var' is not defined"),
        _valid(24.0),
    ] + [_valid(24.0) for _ in range(20)])
    config = _island_config(max_iterations=1, max_attempts=2)
    engine = _make_engine(temp_db, fake_task_spec, adapter, config)
    engine._activate_island("a")
    engine._run_one_iteration()

    attempts = [
        e for e in engine.store.get_events(engine.experiment_id)
        if e.type == "attempt_started"
    ]
    assert [e.payload["operator"] for e in attempts] == ["refine", "repair"]
    assert {e.payload["island_id"] for e in attempts} == {"a"}
    assert [e.payload["attempt"] for e in attempts] == [1, 2]

    states = _island_states(engine)
    assert states["a"].attempts == 2
    assert states["a"].invalid_evaluations == 1
    tree = _tree_of(engine, "a")
    repairs = [n for n in tree.nodes.values() if n.is_repair_node()]
    assert len(repairs) == 1


def test_repair_is_refused_once_the_island_cap_is_reached(temp_db, fake_task_spec):
    """The cap cannot be crossed through a repair chain -- and the refusal is loud."""
    adapter = FakeAdapter()
    adapter.set_results([
        _valid(22.0),
        _invalid("NameError: name 'undefined_var' is not defined"),
        _valid(24.0),
    ] + [_valid(24.0) for _ in range(20)])
    config = _island_config(max_iterations=1, max_attempts=1)
    engine = _make_engine(temp_db, fake_task_spec, adapter, config)
    engine._activate_island("a")
    engine._run_one_iteration()

    states = _island_states(engine)
    assert states["a"].attempts == 1
    tree = _tree_of(engine, "a")
    assert [n for n in tree.nodes.values() if n.is_repair_node()] == []

    hits = [
        e for e in engine.store.get_events(engine.experiment_id)
        if e.type == "island_attempt_cap_hit"
    ]
    assert len(hits) == 1
    assert hits[0].payload["refused"] == "repair"
    assert hits[0].payload["max_attempts"] == 1


def test_eval_concurrency_above_one_is_refused_not_ignored(temp_db, fake_task_spec):
    """Serial scheduling is what exists; a bigger number must fail at startup."""
    adapter = FakeAdapter()
    config = _island_config(max_iterations=1)
    config.islands.eval_concurrency = 2
    engine = EvolutionEngine(
        config=config,
        task_adapter=adapter,
        task_spec=fake_task_spec,
        store=Store(temp_db),
        llm=MockLLM(),
        mock=True,
    )
    with pytest.raises(ValueError, match="eval_concurrency"):
        engine.initialize()


def test_island_budget_is_charged_per_attempt_not_per_operator(
    temp_db, fake_task_spec
):
    """Repair/HPO-style candidates use the same unit as a refine (D2.6)."""
    adapter = FakeAdapter()
    adapter.set_results([_valid()] + [_valid(40.0) for _ in range(20)])
    engine = _make_engine(
        temp_db,
        fake_task_spec,
        adapter,
        _island_config(max_iterations=12, max_attempts=3),
    )
    engine.run(max_iterations=12)

    attempts = [
        e for e in engine.store.get_events(engine.experiment_id)
        if e.type == "attempt_started"
    ]
    assert len(attempts) == 9, "three islands x three attempts"
    assert {e.payload["max_attempts"] for e in attempts} == {3}
    per_island: dict[str, list[int]] = {}
    for event in attempts:
        per_island.setdefault(event.payload["island_id"], []).append(event.payload["attempt"])
    assert {i: sorted(v) for i, v in per_island.items()} == {
        "a": [1, 2, 3], "b": [1, 2, 3], "c": [1, 2, 3],
    }
