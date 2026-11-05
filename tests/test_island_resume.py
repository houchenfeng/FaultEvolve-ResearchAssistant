"""S4 D4.3: a resume either continues the run it was given or says why it cannot.

Four ways a resume goes wrong, one group of tests each:

* **identity** -- task text, evaluator bytes, data descriptor, island ring, schema
  and seed. Keeping an experiment id while changing what the experiment *is* makes
  every number after the resume mean something else, so it must be refused with the
  field named. A value the stored run never recorded is reported as unverified
  rather than counted as a match.
* **cost** -- the counters are per-process, the spend is not. A resumed run starts
  where its ledger rows say it had got to, including the knowledge stage, which is
  an estimate about a prompt block and therefore lives in events, not in cost rows.
* **state** -- the rotation cursor, each island's operator stream and the deferred
  candidates come back; a candidate the evaluator already answered is never charged
  a second evaluation or credited a second time.
* **ownership** -- one live process holds one run. A dead process's claim is written
  down as an interrupted attempt before the new holder takes over, and an old run is
  copied through SQLite's backup interface so its WAL is part of the copy instead of
  a discrepancy.

Everything is offline (MockLLM + FakeAdapter); the only scores asserted are the fake
evaluator's, and the report rebuild is required to call it zero times.
"""

from __future__ import annotations

import hashlib
import json
import random
import sqlite3
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from faultevolve.cli import app
from faultevolve.cloud import resume as resume_module
from faultevolve.cloud.engine import (
    DeferredCandidate,
    rebuild_run_report,
    run_local_evolution,
)
from faultevolve.cloud.llm import LLMTransientError
from faultevolve.cloud.resume import (
    CHECKED_FIELDS,
    RunIdentity,
    ResumeRefused,
    RunBusy,
    check_identity,
    clone_run_directory,
    copy_run_artifacts,
    data_fingerprint,
    rng_from_snapshot,
    snapshot_rng,
)
from faultevolve.cloud.store import SCHEMA_VERSION, Store, now_iso
from faultevolve.cloud.islands import IslandCoordinator, IslandRuntime
from faultevolve.cloud.tree import create_init_node
from faultevolve.common.schemas import (
    Event,
    EvaluationResult,
    IslandState,
    NodeEvidence,
    NodeStatus,
    SchedulerState,
    SummaryApplication,
)
from faultevolve.config import EvolveConfig, IslandSpec
from faultevolve.worker.runner import FakeAdapter, FakeTaskSpec

from tests.test_island_cost import _calls, _config, _engine, _results
from tests.test_island_exchange import _take_attempt

runner = CliRunner()


@pytest.fixture
def task_dir(tmp_path: Path) -> Path:
    """A task directory whose data is described by a small descriptor file."""
    root = tmp_path / "task"
    (root / "data").mkdir(parents=True)
    (root / "evaluator.py").write_text("print('eval v1')\n", encoding="utf-8")
    (root / "data" / "meta.json").write_text(
        json.dumps({"horizon_days": 7, "splits": {"train": {"rows": 10}}}), encoding="utf-8"
    )
    return root


@pytest.fixture
def run_dir(tmp_path: Path) -> Path:
    """One run's home directory, the way ``run_local_evolution`` lays it out."""
    home = tmp_path / "runs" / "exp-1"
    home.mkdir(parents=True)
    return home


@pytest.fixture
def temp_db(run_dir: Path) -> Path:
    return run_dir / "fe.db"


def _spec(task_dir: Path, **changes: str) -> FakeTaskSpec:
    kwargs: dict[str, Any] = {
        "task_dir": task_dir,
        "problem_md": "predict failures from SMART attributes",
        "prompt_md": "SHARED-TASK-INSTRUCTION",
        "init_code": '"""init"""\npass\n',
        "evaluator_path": task_dir / "evaluator.py",
    }
    kwargs.update(changes)
    return FakeTaskSpec(**kwargs)


def _adapter() -> FakeAdapter:
    adapter = FakeAdapter()
    adapter.set_results(_results())
    return adapter


def _identity(store: Store, experiment_id: str) -> RunIdentity:
    return RunIdentity.from_json(store.get_run_identity(experiment_id) or "")


def _typed(store: Store, experiment_id: str, event_type: str) -> list[dict[str, Any]]:
    return [
        event.payload
        for event in store.get_events(experiment_id)
        if event.type == event_type
    ]


#: A cost row's purpose -> the :class:`RunMetrics` counter its budget stage cap
#: reads. Stated here independently of the engine's own map, so a purpose the
#: replay cannot place fails a test instead of spending toward nothing.
PURPOSE_TO_COUNTER = {
    "generate": "generate_tokens",
    "refine": "generate_tokens",
    "summary_cross": "generate_tokens",
    "repair": "repair_tokens",
    "reflect": "reflect_tokens",
    "self_fix": "self_fix_tokens",
    "crossover": "crossover_tokens",
    "jev": "jev_tokens",
    "jev_prescreen": "jev_tokens",
}


# ---------------------------------------------------------------- identity


def test_a_run_records_what_it_was_started_with(temp_db, task_dir):
    engine = _engine(temp_db, _spec(task_dir), _adapter(), _config())

    stored = _identity(engine.store, engine.experiment_id)
    assert stored.task_fp and stored.data_fp and stored.init_fp and stored.evaluator_fp
    assert stored.island_ids == tuple(engine._coordinator.order)
    assert stored.schema_version == SCHEMA_VERSION
    assert stored.identity_version == resume_module.IDENTITY_VERSION
    assert stored.seed == engine.config.seed


def test_a_resume_of_the_same_experiment_is_allowed(temp_db, task_dir):
    adapter = _adapter()
    engine = _engine(temp_db, _spec(task_dir), adapter, _config())
    experiment_id = engine.experiment_id

    resumed = _engine(temp_db, _spec(task_dir), adapter, _config(), resume_id=experiment_id)
    assert resumed.experiment_id == experiment_id
    assert resumed._resume_check["unverified"] == []
    assert list(resumed._resume_check["verified"]) == list(CHECKED_FIELDS)
    assert "task_fp" in resumed._resume_check["verified"]


def test_a_changed_task_is_refused_and_names_the_field(temp_db, task_dir):
    adapter = _adapter()
    engine = _engine(temp_db, _spec(task_dir), adapter, _config())

    with pytest.raises(ResumeRefused) as failure:
        _engine(
            temp_db,
            _spec(task_dir, prompt_md="A DIFFERENT INSTRUCTION"),
            adapter,
            _config(),
            resume_id=engine.experiment_id,
        )
    stored_value, incoming_value = failure.value.mismatches["task_fp"]
    assert stored_value != incoming_value
    # Refusing writes nothing else: no island state, no cost row, no half attempt.
    assert _typed(engine.store, engine.experiment_id, "run_resume_refused")
    assert not _typed(engine.store, engine.experiment_id, "run_resumed")


def test_a_changed_evaluator_is_refused(temp_db, task_dir):
    adapter = _adapter()
    engine = _engine(temp_db, _spec(task_dir), adapter, _config())

    # Same path, different scoring program: numbers from the two are not comparable,
    # so continuing the old experiment would mix two scales.
    (task_dir / "evaluator.py").write_text("print('eval v2')\n", encoding="utf-8")
    with pytest.raises(ResumeRefused) as failure:
        _engine(temp_db, _spec(task_dir), adapter, _config(), resume_id=engine.experiment_id)
    assert "evaluator_fp" in failure.value.mismatches


def test_a_changed_data_descriptor_is_refused(temp_db, task_dir):
    adapter = _adapter()
    engine = _engine(temp_db, _spec(task_dir), adapter, _config())

    (task_dir / "data" / "meta.json").write_text(
        json.dumps({"horizon_days": 30, "splits": {"train": {"rows": 999}}}), encoding="utf-8"
    )
    with pytest.raises(ResumeRefused) as failure:
        _engine(temp_db, _spec(task_dir), adapter, _config(), resume_id=engine.experiment_id)
    assert "data_fp" in failure.value.mismatches


def test_a_data_descriptor_that_disappeared_counts_as_a_change(temp_db, task_dir):
    """"Unknown now" is not "unchanged": the run cannot show what it reads."""
    adapter = _adapter()
    engine = _engine(temp_db, _spec(task_dir), adapter, _config())
    (task_dir / "data" / "meta.json").unlink()

    with pytest.raises(ResumeRefused) as failure:
        _engine(temp_db, _spec(task_dir), adapter, _config(), resume_id=engine.experiment_id)
    assert failure.value.mismatches == {}
    assert failure.value.lost == ["data_fp"]


def test_a_different_seed_is_refused(temp_db, task_dir):
    adapter = _adapter()
    engine = _engine(temp_db, _spec(task_dir), adapter, _config())

    config = _config()
    config.seed = engine.config.seed + 1
    with pytest.raises(ResumeRefused) as failure:
        _engine(temp_db, _spec(task_dir), adapter, config, resume_id=engine.experiment_id)
    assert "seed" in failure.value.mismatches


def test_the_island_ring_is_the_one_the_run_was_built_with(temp_db, task_dir):
    """A config that now says two islands does not shrink a three-island run."""
    adapter = _adapter()
    engine = _engine(temp_db, _spec(task_dir), adapter, _config())
    assert len(engine._coordinator.order) == 3

    shrunk = _config()
    shrunk.islands.islands = shrunk.islands.islands[:2]
    resumed = _engine(temp_db, _spec(task_dir), adapter, shrunk, resume_id=engine.experiment_id)
    assert resumed._coordinator.order == engine._coordinator.order
    assert _identity(resumed.store, engine.experiment_id).island_ids == tuple(
        engine._coordinator.order
    )


def test_a_run_without_an_identity_record_resumes_and_says_what_is_unverified(
    temp_db, task_dir
):
    """The task text is still comparable from the experiment row; the rest is not.

    ``verified`` names only what this resume actually checked, so the run cannot
    later claim a full identity match for a record it never read.
    """
    adapter = _adapter()
    engine = _engine(temp_db, _spec(task_dir), adapter, _config())
    experiment_id = engine.experiment_id
    with engine.store._conn() as conn:
        conn.execute("DELETE FROM run_identity WHERE experiment_id = ?", (experiment_id,))

    resumed = _engine(temp_db, _spec(task_dir), adapter, _config(), resume_id=experiment_id)
    assert resumed._resume_check["verified"] == ["task_fp"]
    assert resumed._resume_check["unverified"] == ["no identity record"]
    # The missing fields are recorded on the way through, so the *next* resume of
    # this run has a complete record to check against -- read back from a fresh
    # connection, because the resume's own process is about to exit.
    after = _identity(Store(temp_db), experiment_id)
    assert after.task_fp and after.evaluator_fp and after.data_fp and after.init_fp
    assert after.island_ids == tuple(engine._coordinator.order)


def test_a_run_without_an_identity_record_still_refuses_a_changed_task(
    temp_db, task_dir
):
    """No record is not a free pass: the experiment row carries its own task text."""
    adapter = _adapter()
    engine = _engine(temp_db, _spec(task_dir), adapter, _config())
    experiment_id = engine.experiment_id
    with engine.store._conn() as conn:
        conn.execute("DELETE FROM run_identity WHERE experiment_id = ?", (experiment_id,))

    with pytest.raises(ResumeRefused) as failure:
        _engine(
            temp_db,
            _spec(task_dir, prompt_md="A DIFFERENT INSTRUCTION"),
            adapter,
            _config(),
            resume_id=experiment_id,
        )
    assert "task_fp" in failure.value.mismatches
    refused = _typed(engine.store, experiment_id, "run_resume_refused")
    assert refused[-1]["reason"] == "no identity record; the experiment row reads differently"
    # Refusing fills nothing in: a run that was not allowed to continue does not
    # get an identity describing the attempt that never ran.
    assert _identity(Store(temp_db), experiment_id).task_fp == ""


def test_the_data_fingerprint_reads_only_descriptors(task_dir):
    """A digest of the data would mean reading 40 GB, and the private split stays
    unread; a digest of its description is enough to notice it moved."""
    spec = _spec(task_dir)
    before = data_fingerprint(spec)
    assert before

    (task_dir / "data" / "train_history.csv.gz").write_text("x", encoding="utf-8")
    assert data_fingerprint(spec) == before, "data bytes are not part of the digest"

    holdout = task_dir / "data" / "holdout"
    holdout.mkdir()
    (holdout / "meta.json").write_text('{"leak": true}', encoding="utf-8")
    assert data_fingerprint(spec) == before, "nothing under holdout is read"


def test_check_identity_treats_absent_fields_as_unverified():
    stored = RunIdentity(
        identity_version=1, schema_version=SCHEMA_VERSION, seed=7, island_ids=("a",)
    )
    incoming = RunIdentity(
        identity_version=1,
        schema_version=SCHEMA_VERSION,
        seed=7,
        island_ids=("a",),
        data_fp="abcd",
    )
    assert check_identity(stored, incoming) == ({}, [])

    mismatches, lost = check_identity(
        RunIdentity(
            identity_version=1,
            schema_version=SCHEMA_VERSION,
            seed=7,
            island_ids=("a",),
            data_fp="abcd",
        ),
        RunIdentity(
            identity_version=1,
            schema_version=SCHEMA_VERSION,
            seed=8,
            island_ids=("a",),
        ),
    )
    assert "seed" in mismatches
    assert lost == ["data_fp"]


# -------------------------------------------------------------------- cost


def test_a_resume_carries_the_tokens_the_run_already_spent(temp_db, task_dir):
    adapter = _adapter()
    engine = _engine(temp_db, _spec(task_dir), adapter, _config())
    _take_attempt(engine, "a")
    _take_attempt(engine, "b")
    spent = engine.store.get_cost_rollup(engine.experiment_id)["total_tokens"]
    assert spent > 0

    resumed = _engine(
        temp_db, _spec(task_dir), adapter, _config(), resume_id=engine.experiment_id
    )
    restored = resumed._restore_run_cost()
    assert restored["total_tokens"] == spent
    assert restored["cost_rows"] == len(_calls(engine))
    assert resumed.metrics.total_tokens == spent
    assert resumed.metrics.generate_tokens > 0


def test_a_resumed_stage_counter_matches_the_rows_of_that_stage(temp_db, task_dir):
    """Each stage cap reads one counter, so every counter has to equal its rows."""
    adapter = _adapter()
    engine = _engine(temp_db, _spec(task_dir), adapter, _config())
    _take_attempt(engine, "a")
    _take_attempt(engine, "b")

    resumed = _engine(
        temp_db, _spec(task_dir), adapter, _config(), resume_id=engine.experiment_id
    )
    resumed._restore_run_cost()

    expected: dict[str, int] = {}
    for row in _calls(resumed):
        counter = PURPOSE_TO_COUNTER.get(row.purpose)
        assert counter is not None, f"the replay has no bucket for {row.purpose!r}"
        expected[counter] = expected.get(counter, 0) + row.prompt_tokens + row.completion_tokens
    assert expected, "two attempts have to have spent something"
    for counter, tokens in expected.items():
        assert getattr(resumed.metrics, counter) == tokens
    rollup = resumed.store.get_cost_rollup(engine.experiment_id)
    assert sum(expected.values()) == rollup["total_tokens"]


def test_a_lost_request_is_not_counted_as_spend_but_stays_visible(temp_db, task_dir):
    adapter = _adapter()
    engine = _engine(temp_db, _spec(task_dir), adapter, _config())
    engine._record_lost_llm_call(
        LLMTransientError("went out and never came back", request_id="req-lost", attempts=3),
        "generate",
        node_id="n1",
    )
    experiment_id = engine.experiment_id

    resumed = _engine(temp_db, _spec(task_dir), adapter, _config(), resume_id=experiment_id)
    assert resumed._restore_run_cost()["total_tokens"] == 0
    lost_rows = [row for row in _calls(resumed) if row.outcome == "unknown_outcome"]
    assert [row.request_id for row in lost_rows] == ["req-lost"]
    rollup = resumed.store.get_cost_rollup(experiment_id)
    assert rollup["unresolved_calls"] == 1


def test_the_knowledge_stage_is_restored_from_what_was_injected(temp_db, task_dir):
    """Knowledge tokens estimate a prompt block, not a call, so they are not in the
    cost rows -- the injection events carry the estimate the interrupted run used."""
    adapter = _adapter()
    engine = _engine(temp_db, _spec(task_dir), adapter, _config())
    engine.store.create_event(Event(
        experiment_id=engine.experiment_id,
        type="knowledge_injected",
        payload={"island_id": "a", "card_ids": ["K-A1"], "estimated_tokens": 120},
        ts=now_iso(),
    ))
    engine.store.create_event(Event(
        experiment_id=engine.experiment_id,
        type="knowledge_injected",
        payload={"island_id": "b", "card_ids": [], "estimated_tokens": 0},
        ts=now_iso(),
    ))
    experiment_id = engine.experiment_id

    resumed = _engine(temp_db, _spec(task_dir), adapter, _config(), resume_id=experiment_id)
    assert resumed._restore_run_cost()["knowledge_tokens"] == 120
    assert resumed._stage_used_tokens("knowledge") == 120


def test_the_budget_stop_uses_the_restored_spend(temp_db, task_dir):
    adapter = _adapter()
    engine = _engine(temp_db, _spec(task_dir), adapter, _config())
    _take_attempt(engine, "a")
    spent = engine.metrics.total_tokens
    assert spent > 0

    config = _config()
    # Half of what the run already spent: the resumed attempt is already over the
    # cap, and a counter that restarted at zero would happily keep going.
    config.budget.max_tokens = spent // 2
    resumed = _engine(temp_db, _spec(task_dir), adapter, config, resume_id=engine.experiment_id)
    resumed._restore_run_cost()
    assert resumed._should_stop(resumed.metrics.start_time) is True


def test_a_resume_without_a_token_cap_keeps_spending(temp_db, task_dir):
    """The mirror image: ``max_tokens=None`` means "no cost limit", so the spend
    replayed from the rows must neither stop the resumed run nor surface as a
    budget stop reason -- and the next attempt must actually spend more.

    T09's predicate is unit-tested elsewhere; this is the same decision taken by
    an engine whose predecessor already wrote rows to disk.
    """
    adapter = _adapter()
    engine = _engine(temp_db, _spec(task_dir), adapter, _config())
    _take_attempt(engine, "a")
    spent = engine.metrics.total_tokens
    assert spent > 0
    experiment_id = engine.experiment_id

    config = _config()
    config.budget.max_tokens = None
    config.budget.max_wall_hours = None
    resumed = _engine(temp_db, _spec(task_dir), adapter, config, resume_id=experiment_id)
    assert resumed._restore_run_cost()["total_tokens"] == spent
    assert resumed._should_stop(resumed.metrics.start_time) is False
    assert resumed._get_stop_reason() not in ("token_budget", "wall_time")

    before = resumed.store.get_island_state(experiment_id, "a")
    assert _take_attempt(resumed, "a") is True
    assert resumed.metrics.total_tokens > spent
    after = resumed.store.get_island_state(experiment_id, "a")
    assert after.attempts == before.attempts + 1


# ------------------------------------------------------------------- state


def test_the_rotation_cursor_and_operator_stream_come_back_together(temp_db, task_dir):
    adapter = _adapter()
    engine = _engine(temp_db, _spec(task_dir), adapter, _config())
    _take_attempt(engine, "a")
    island_a = engine._coordinator.runtime("a")
    island_a.attrs["_op_rng"].random()
    engine._coordinator.persist_cursor()
    engine._sync_island_states()
    expected = [island_a.attrs["_op_rng"].random() for _ in range(3)]

    resumed = _engine(
        temp_db, _spec(task_dir), adapter, _config(), resume_id=engine.experiment_id
    )
    state = resumed.store.get_scheduler_state(engine.experiment_id)
    assert state is not None and state.rng_state_json

    resumed_a = resumed._coordinator.runtime("a")
    assert [resumed_a.attrs["_op_rng"].random() for _ in range(3)] == expected, (
        "the resumed island replays its own draws instead of re-deriving them"
    )
    assert resumed._coordinator._index == engine._coordinator._index


def test_the_stream_snapshot_survives_json_and_a_bad_payload():
    rng = random.Random("seed-a")
    rng.random()
    restored = rng_from_snapshot(snapshot_rng(rng))
    assert restored is not None
    assert [restored.random() for _ in range(4)] == [rng.random() for _ in range(4)]
    assert rng_from_snapshot("") is None
    assert rng_from_snapshot("{not json") is None
    assert rng_from_snapshot("[1, 2]") is None


def test_the_coordinator_keeps_reading_a_cursor_without_a_stream(temp_db):
    """A cursor written before streams were snapshotted still restores."""
    store = Store(temp_db)
    store.save_scheduler_state(
        SchedulerState(
            experiment_id="exp-1", next_island_index=1, rng_state_json="{broken"
        )
    )
    coordinator = IslandCoordinator(
        "exp-1",
        [
            IslandRuntime(
                spec=IslandSpec(island_id=iso, profile="performance"),
                state=IslandState(experiment_id="exp-1", island_id=iso),
            )
            for iso in ("a", "b")
        ],
        store,
    )
    coordinator.restore_cursor()
    assert coordinator._index == 1
    assert coordinator.rng_states == {}, "an unreadable payload resumes as no stream"


def test_an_application_recorded_before_the_crash_still_gets_its_result(temp_db, task_dir):
    """The row says a candidate was built from a sibling's summary; the in-memory
    link is what completes it, so the unfinished rows are re-attached from the store."""
    adapter = _adapter()
    config = _config()
    engine = _engine(temp_db, _spec(task_dir), adapter, config)
    root = engine.tree.get_root()
    assert root is not None
    # A branch of the island's own tree: an island owns exactly one root, and the
    # candidate a summary was applied to has to sit where the run left it.
    child = create_init_node(engine.experiment_id, "branch-app", "# c", island_id="a")
    child.parent_id = root.id
    child.depth = 1
    engine.store.create_node(child)
    application = SummaryApplication(
        application_id="app-1",
        delivery_id="dlv-1",
        experiment_id=engine.experiment_id,
        candidate_node_id=child.id,
    )
    assert engine.store.record_application(application)

    resumed = _engine(temp_db, _spec(task_dir), adapter, config, resume_id=engine.experiment_id)
    tree = resumed._coordinator.runtime("a").attrs["tree"]
    assert resumed._pending_summary_applications(tree) == {child.id: ["app-1"]}
    assert resumed._coordinator.runtime("a").attrs["_summary_applications"] == {
        child.id: ["app-1"]
    }

    # A completed row is not re-attached: its result was already reported.
    application2 = SummaryApplication(
        application_id="app-2",
        delivery_id="dlv-2",
        experiment_id=engine.experiment_id,
        candidate_node_id=child.id,
        evaluation_id=child.id,
        score=30.0,
    )
    assert engine.store.record_application(application2)
    again = _engine(temp_db, _spec(task_dir), adapter, config, resume_id=engine.experiment_id)
    pending = again._pending_summary_applications(again._coordinator.runtime("a").attrs["tree"])
    assert pending.get(child.id) == ["app-1"]
    rows = again.store.get_applications_by_experiment(engine.experiment_id)
    assert {row.application_id for row in rows} == {"app-1", "app-2"}


def test_a_deferred_candidate_the_evaluator_answered_is_not_charged_twice(temp_db, task_dir):
    adapter = _adapter()
    config = _config()
    engine = _engine(temp_db, _spec(task_dir), adapter, config)
    engine._activate_island("a")
    root = engine.tree.get_root()
    assert root is not None

    child = create_init_node(engine.experiment_id, "branch-deferred", "# child", island_id="a")
    child.parent_id = root.id
    child.depth = 1
    child.status = NodeStatus.ABANDONED
    # The evaluator answered and the node kept the score; the process died before
    # the flush event was written.
    child.evidence = NodeEvidence(
        evaluation=EvaluationResult(validity=1.0, combined_score=31.0, cost_time=1.0, metric={})
    )
    engine.store.create_node(child)
    engine.store.create_event(Event(
        experiment_id=engine.experiment_id,
        type="jev_screened",
        payload={
            "island_id": "a",
            "node_id": child.id,
            "parent_id": root.id,
            "decision": "defer",
            "value": 0.9,
            "deferred": True,
            "audited": False,
        },
        ts=now_iso(),
    ))

    resumed = _engine(temp_db, _spec(task_dir), adapter, config, resume_id=engine.experiment_id)
    resumed._activate_island("a")
    assert [item.node_id for item in resumed._deferred] == [child.id]
    calls_before = adapter._call_count
    resumed._flush_deferred(1)

    assert adapter._call_count == calls_before, "the evaluator ran a second time"
    events = _typed(resumed.store, engine.experiment_id, "jev_deferred_evaluated")
    assert events[-1]["rebuilt_from_node"] is True
    assert events[-1]["island_id"] == "a"
    assert events[-1]["valid"] is True
    assert resumed.tree.get_node(child.id).status == NodeStatus.DONE
    assert resumed._deferred == []


def test_a_deferred_candidate_that_was_never_evaluated_is_evaluated(temp_db, task_dir):
    adapter = _adapter()
    config = _config()
    engine = _engine(temp_db, _spec(task_dir), adapter, config)
    engine._activate_island("a")
    root = engine.tree.get_root()
    child = create_init_node(engine.experiment_id, "branch-unscored", "# child", island_id="a")
    child.parent_id = root.id
    child.depth = 1
    child.status = NodeStatus.ABANDONED
    # In the live run the candidate was added in memory and persisted in the same
    # attempt; the queue only flushes what this island's tree can see.
    engine.tree.add_node(child)
    engine._deferred = [DeferredCandidate(child.id, root.id, 0.9, [])]

    calls_before = adapter._call_count
    engine._flush_deferred(1)

    assert adapter._call_count == calls_before + 1
    events = _typed(engine.store, engine.experiment_id, "jev_deferred_evaluated")
    assert "rebuilt_from_node" not in events[-1]
    assert events[-1]["island_id"] == "a"
    assert engine._deferred == [], "the queue drains, so a second flush costs nothing more"
    engine._flush_deferred(1)
    assert adapter._call_count == calls_before + 1


# --------------------------------------------------------------- ownership


def test_a_live_claim_from_another_process_blocks_the_resume(temp_db, task_dir, monkeypatch):
    adapter = _adapter()
    config = _config()
    engine = _engine(temp_db, _spec(task_dir), adapter, config)
    experiment_id = engine.experiment_id
    engine._release_run_claim()

    monkeypatch.setattr(resume_module, "pid_alive", lambda pid: True)
    engine.store.take_run_claim(experiment_id, "other-holder", 999_991)

    with pytest.raises(RunBusy) as failure:
        _engine(temp_db, _spec(task_dir), adapter, config, resume_id=experiment_id)
    assert failure.value.holder_id == "other-holder"
    assert failure.value.holder_pid == 999_991
    assert engine.store.get_run_claim(experiment_id)["holder_id"] == "other-holder"
    assert not _typed(engine.store, experiment_id, "run_interrupted")


def test_a_dead_claim_is_recorded_as_an_interrupted_attempt(temp_db, task_dir, monkeypatch):
    adapter = _adapter()
    config = _config()
    engine = _engine(temp_db, _spec(task_dir), adapter, config)
    experiment_id = engine.experiment_id
    engine._release_run_claim()

    monkeypatch.setattr(resume_module, "pid_alive", lambda pid: False)
    engine.store.take_run_claim(experiment_id, "gone-holder", 999_992)

    resumed = _engine(temp_db, _spec(task_dir), adapter, config, resume_id=experiment_id)
    interruptions = _typed(Store(temp_db), experiment_id, "run_interrupted")
    assert interruptions[-1]["previous_holder"]["holder_id"] == "gone-holder"
    assert interruptions[-1]["previous_holder"]["alive"] is False
    assert resumed.store.get_run_claim(experiment_id)["holder_id"] == resumed._holder_id


def test_a_finished_run_leaves_no_claim(temp_db, task_dir):
    engine = _engine(temp_db, _spec(task_dir), _adapter(), _config())
    assert engine.store.get_run_claim(engine.experiment_id)["holder_id"] == engine._holder_id
    engine._release_run_claim()
    assert engine.store.get_run_claim(engine.experiment_id) is None


def test_a_release_does_not_delete_another_holders_claim(temp_db, task_dir):
    engine = _engine(temp_db, _spec(task_dir), _adapter(), _config())
    # A late-exiting previous holder must not unlock the run it no longer owns.
    engine.store.release_run_claim(engine.experiment_id, "somebody-else")
    assert engine.store.get_run_claim(engine.experiment_id)["holder_id"] == engine._holder_id


def test_two_engines_in_one_process_are_a_restart_not_a_competing_run(temp_db, task_dir):
    """Islands run serially and one engine per process is the design, so a claim left
    by this same pid is a handover; only another live process is a second execution."""
    adapter = _adapter()
    config = _config()
    engine = _engine(temp_db, _spec(task_dir), adapter, config)
    resumed = _engine(temp_db, _spec(task_dir), adapter, config, resume_id=engine.experiment_id)
    assert engine.store.get_run_claim(engine.experiment_id)["holder_id"] == resumed._holder_id
    assert resumed._interrupted_claim == {}


def test_an_unknowable_pid_does_not_hold_a_run_forever(temp_db, task_dir, monkeypatch):
    adapter = _adapter()
    config = _config()
    engine = _engine(temp_db, _spec(task_dir), adapter, config)
    engine._release_run_claim()
    monkeypatch.setattr(resume_module, "pid_alive", lambda pid: None)
    engine.store.take_run_claim(engine.experiment_id, "unknown-holder", 999_993)

    resumed = _engine(temp_db, _spec(task_dir), adapter, config, resume_id=engine.experiment_id)
    assert resumed.store.get_run_claim(engine.experiment_id)["holder_id"] == resumed._holder_id


# ------------------------------------------------------------------ report


def test_a_report_is_rebuilt_from_the_database_without_another_evaluation(
    temp_db, task_dir, run_dir
):
    adapter = _adapter()
    config = _config()
    engine = _engine(temp_db, _spec(task_dir), adapter, config)
    _take_attempt(engine, "a")
    _take_attempt(engine, "b")
    engine._sync_island_states()
    experiment_id = engine.experiment_id
    evaluations_before = adapter._call_count

    store = Store(temp_db, read_only=True)
    nodes_before = len(store.get_nodes_by_experiment(experiment_id))
    events_before = len(store.get_events(experiment_id))
    art_dir = run_dir.parent / "rebuilt"

    summary = rebuild_run_report(store, experiment_id, art_dir)

    assert summary["rebuilt_from_store"] is True
    assert summary["node_count"] == nodes_before
    assert summary["iterations_done"] == store.get_experiment(experiment_id).iterations_done
    assert summary["total_tokens"] == store.get_cost_rollup(experiment_id)["total_tokens"]
    # Every number in the report is a stored evaluation's own score: the rebuild
    # reads them and never asks the evaluator to produce them again.
    assert summary["best_score"] == max(
        node.get_score()
        for node in store.get_nodes_by_experiment(experiment_id)
        if node.evidence.evaluation is not None and node.evidence.evaluation.validity >= 1.0
    )
    assert set(summary["islands"]) == {"a", "b", "c"}
    assert (art_dir / "run_summary.json").is_file()
    assert (art_dir / "events.jsonl").is_file()
    body = json.loads((art_dir / "tree.json").read_text(encoding="utf-8"))
    assert len(body["nodes"]) == nodes_before
    assert list((art_dir / "programs").glob("*.py"))

    assert adapter._call_count == evaluations_before, "a rebuild must not spend an evaluation"
    after = Store(temp_db, read_only=True)
    assert len(after.get_nodes_by_experiment(experiment_id)) == nodes_before
    assert len(after.get_events(experiment_id)) == events_before


def test_a_rebuild_refuses_an_id_that_does_not_exist(temp_db):
    Store(temp_db)  # an empty but existing run database
    with pytest.raises(ValueError):
        rebuild_run_report(Store(temp_db, read_only=True), "nope1234", temp_db.parent / "x")


# ------------------------------------------------------------------- clone


def _copy_of(run_dir: Path, home: str) -> Path:
    """Clone one run directory into a fresh home and return the new database."""
    dst = Path(home) / "copy"
    dst.mkdir()
    return clone_run_directory(run_dir, dst)


def test_an_old_run_is_resumed_from_a_copy_not_from_the_original(
    temp_db, task_dir, run_dir
):
    """A write-mode resume of an old run goes through SQLite's backup interface into
    a new directory; the original stays exactly as the interrupted run left it."""
    adapter = _adapter()
    config = _config()
    engine = _engine(temp_db, _spec(task_dir), adapter, config)
    _take_attempt(engine, "a")
    engine._coordinator.persist_cursor()
    engine._sync_island_states()
    experiment_id = engine.experiment_id
    source = Store(temp_db, read_only=True)
    nodes_before = len(source.get_nodes_by_experiment(experiment_id))
    events_before = len(source.get_events(experiment_id))

    with tempfile.TemporaryDirectory() as home:
        dst_db = _copy_of(run_dir, home)
        resumed = _engine(dst_db, _spec(task_dir), adapter, config, resume_id=experiment_id)
        assert resumed.experiment_id == experiment_id
        assert resumed._resume_check["unverified"] == []
        assert resumed.store.get_run_claim(experiment_id)["holder_id"] == resumed._holder_id
        # The claim the interrupted process left behind still names it: the resume
        # wrote into the copy, so a comparison run can still read the original.
        assert Store(temp_db, read_only=True).get_run_claim(experiment_id)[
            "holder_id"
        ] == engine._holder_id
        after = Store(temp_db, read_only=True)
        assert len(after.get_nodes_by_experiment(experiment_id)) == nodes_before
        assert len(after.get_events(experiment_id)) == events_before


def test_artifacts_travel_as_files_and_a_database_never_does(tmp_path):
    """A run directory holds two kinds of file. The artifacts are ordinary; a
    SQLite main file copied by hand is a half-checkpointed snapshot, and its WAL
    arriving without its database is just a discrepancy."""
    src = tmp_path / "src"
    (src / "programs").mkdir(parents=True)
    (src / "run_summary.json").write_text('{"old": true}', encoding="utf-8")
    (src / "events.jsonl").write_text('{"type": "x"}\n', encoding="utf-8")
    (src / "programs" / "n1.py").write_text("# n1\n", encoding="utf-8")
    (src / "fe.db").write_bytes(b"database bytes")
    (src / "fe.db-wal").write_bytes(b"uncheckpointed commit")

    dst = tmp_path / "dst"
    dst.mkdir()
    (dst / "run_summary.json").write_text('{"kept": true}', encoding="utf-8")

    copied = copy_run_artifacts(src, dst)
    assert sorted(copied) == ["events.jsonl", "programs"]
    assert (dst / "programs" / "n1.py").is_file()
    assert json.loads((dst / "run_summary.json").read_text(encoding="utf-8")) == {
        "kept": True
    }, "an existing artifact is the copy's, not something to overwrite"
    assert not (dst / "fe.db").exists(), "a database never comes along as a file"
    assert not (dst / "fe.db-wal").exists()


def test_a_clone_never_overwrites_a_database_that_exists(temp_db, task_dir, run_dir):
    """The destination is somebody else's run; a copy that replaced it would be a
    silent delete of the only copy of an experiment."""
    _engine(temp_db, _spec(task_dir), _adapter(), _config())
    with tempfile.TemporaryDirectory() as home:
        dst = Path(home) / "copy"
        dst.mkdir()
        (dst / "fe.db").write_bytes(b"already a database, not an empty placeholder")
        with pytest.raises(FileExistsError):
            clone_run_directory(run_dir, dst)


def test_a_clone_carries_the_wal_and_leaves_the_source_readable(temp_db, task_dir, run_dir):
    """A run directory in WAL mode is not one file: its newest commits sit in
    ``fe.db-wal``. Copying the database file alone would lose them."""
    engine = _engine(temp_db, _spec(task_dir), _adapter(), _config())
    experiment_id = engine.experiment_id
    nodes_before = len(Store(temp_db, read_only=True).get_nodes_by_experiment(experiment_id))

    # A writer that commits and stays open, so its row is only in the WAL.
    holder = sqlite3.connect(str(temp_db), timeout=30.0)
    holder.execute("PRAGMA journal_mode=WAL")
    holder.execute(
        "INSERT INTO run_identity (experiment_id, identity_json, created_at, updated_at)"
        " VALUES ('wal-only', '{}', '', '')"
    )
    holder.commit()
    try:
        with tempfile.TemporaryDirectory() as home:
            dst = Path(home) / "copy"
            dst.mkdir()
            dst_db = clone_run_directory(run_dir, dst)
            copy = sqlite3.connect(str(dst_db), timeout=30.0)
            try:
                stored = {
                    row[0]
                    for row in copy.execute("SELECT experiment_id FROM run_identity")
                }
            finally:
                copy.close()
            assert "wal-only" in stored, "the copy dropped the commits that were in the WAL"
            assert not (dst / "fe.db-wal").exists(), (
                "one consistent file, not a half-applied database/WAL pair"
            )
            copied = Store(dst_db, read_only=True)
            assert len(copied.get_nodes_by_experiment(experiment_id)) == nodes_before
            assert copied.get_run_identity(experiment_id)
            assert len(copied.get_events(experiment_id)) == len(
                Store(temp_db, read_only=True).get_events(experiment_id)
            )
    finally:
        holder.close()


# ----------------------------------------------------------------- cli

# The CLI is where a resume is actually launched, so the two switches a broken
# resume needs -- copy the old run first, or rebuild its report from the database
# -- are exercised through it, on a synthetic task directory, never on the benchmark.


def _evolve_task(tmp_path: Path) -> Path:
    """A task directory ``evolve local`` accepts, with an always-answering evaluator."""
    task = tmp_path / "evo-task"
    task.mkdir()
    (task / "init.py").write_text("# init\n", encoding="utf-8")
    (task / "problem.md").write_text("# problem\n", encoding="utf-8")
    (task / "prompt.md").write_text("# prompt\n", encoding="utf-8")
    (task / "evaluator.py").write_text(
        "def evaluate(p, **kw):\n"
        "    return {'validity': 1, 'combined_score': 22, 'cost_time': 1,"
        " 'error_info': '', 'metric': {}}\n",
        encoding="utf-8",
    )
    return task


def _mock_run(task: Path, runs: Path, adapter: FakeAdapter, iterations: int) -> str:
    with patch("faultevolve.tasks.create_benchmark_adapter", return_value=adapter):
        result = run_local_evolution(
            task_dir=task,
            mock=True,
            max_iterations=iterations,
            runs_dir=runs,
            adapter=adapter,
        )
    return str(result["experiment_id"])


def _run_files(home: Path) -> dict[str, str]:
    """Content of one run directory, sidecars excluded.

    ``fe.db-wal``/``fe.db-shm`` are SQLite's transient files -- opening a database
    read-only can create them -- so they say nothing about whether the run was
    written. That the WAL holds no commit the database file lacks is asserted
    separately, because the comparison above is only meaningful when it does not.
    """
    return {
        str(p.relative_to(home)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(home.rglob("*"))
        if p.is_file() and not p.name.endswith(("-wal", "-shm", "-journal"))
    }


def _wal_settled(home: Path) -> bool:
    """Whether every commit is already inside ``fe.db`` rather than in its WAL.

    The hash comparison above is only a statement about the run if the WAL it skips
    is empty; ``-shm`` is a memory-mapped index and carries no run data either way.
    """
    return all(p.stat().st_size == 0 for p in home.glob("*.db-wal"))


def test_resume_from_continues_a_copy_and_leaves_the_original_files_alone(tmp_path):
    task = _evolve_task(tmp_path)
    runs = tmp_path / "runs"
    adapter = FakeAdapter()
    adapter.set_results(_results())
    run_id = _mock_run(task, runs, adapter, 2)
    source = runs / run_id
    before = _run_files(source)

    home = tmp_path / "continued"
    with patch("faultevolve.tasks.create_benchmark_adapter", return_value=adapter):
        result = runner.invoke(
            app,
            [
                "evolve", "local", str(task), "--mock", "-n", "1",
                "--resume", run_id, "--resume-from", str(source), "--runs-dir", str(home),
            ],
        )
    assert result.exit_code == 0, result.output + result.stderr
    assert (home / run_id / "fe.db").is_file()
    assert _run_files(source) == before, (
        "the resumed run wrote into the copy, not into the run it was copied from"
    )
    assert _wal_settled(source), "the original holds no commit outside its database file"
    copy_store = Store(home / run_id / "fe.db", read_only=True)
    original = Store(source / "fe.db", read_only=True)
    assert len(copy_store.get_nodes_by_experiment(run_id)) >= len(
        original.get_nodes_by_experiment(run_id)
    )
    assert original.get_run_claim(run_id) is None, (
        "a finished run holds nothing; the copy is the one being written"
    )


def test_resume_from_a_directory_the_run_would_write_into_is_refused(tmp_path):
    """Copying a run onto itself would replace the original with a half-written
    clone, so the two paths have to differ before anything is opened."""
    task = _evolve_task(tmp_path)
    runs = tmp_path / "runs"
    adapter = FakeAdapter()
    adapter.set_results(_results())
    run_id = _mock_run(task, runs, adapter, 1)

    result = runner.invoke(
        app,
        [
            "evolve", "local", str(task), "--mock", "-n", "1",
            "--resume", run_id, "--resume-from", str(runs / run_id), "--runs-dir", str(runs),
        ],
    )
    assert result.exit_code == 1
    assert "--runs-dir" in result.stderr


def test_report_only_writes_a_missing_report_from_the_database(tmp_path):
    task = _evolve_task(tmp_path)
    runs = tmp_path / "runs"
    adapter = FakeAdapter()
    adapter.set_results(_results())
    run_id = _mock_run(task, runs, adapter, 2)
    home = runs / run_id
    stored_nodes = len(Store(home / "fe.db", read_only=True).get_nodes_by_experiment(run_id))
    (home / "run_summary.json").unlink()
    evaluations_before = adapter._call_count

    result = runner.invoke(
        app,
        ["evolve", "local", str(task), "--mock", "--report-only", "--resume", run_id,
         "--runs-dir", str(runs)],
    )
    assert result.exit_code == 0, result.output + result.stderr
    summary = json.loads((home / "run_summary.json").read_text(encoding="utf-8"))
    assert summary["rebuilt_from_store"] is True
    assert summary["node_count"] == stored_nodes
    assert summary["best_score"] > 0
    assert adapter._call_count == evaluations_before, (
        "a report rebuild may not spend an evaluation"
    )


def test_the_copy_and_rebuild_switches_name_a_run_that_has_to_exist(tmp_path):
    task = _evolve_task(tmp_path)
    missing = runner.invoke(
        app, ["evolve", "local", str(task), "--mock", "--resume-from", str(tmp_path / "x")]
    )
    assert missing.exit_code == 1
    assert "need --resume" in missing.stderr

    unrun = runner.invoke(
        app,
        ["evolve", "local", str(task), "--mock", "--report-only", "--resume", "deadbeef",
         "--runs-dir", str(tmp_path / "runs")],
    )
    assert unrun.exit_code == 1
    assert "no run database" in unrun.stderr
