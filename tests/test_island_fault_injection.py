"""S4 D4.4: the five places a run can stop halfway, and what a resume may claim.

Every group interrupts a real offline run (MockLLM + FakeAdapter) at one commit
boundary in a temporary task directory, restarts it, and compares counts taken
before the interruption with counts taken after:

* **summary written, delivery missing** -- exactly one offer per sibling that can
  still act, and a second round that adds nothing;
* **application written, candidate not evaluated** -- the row stays unfinished and
  says so; only the process that actually evaluates the candidate may complete it,
  and then with its own number;
* **evaluations done, report missing** -- the report is a projection of the
  database, so rebuilding it calls the evaluator zero times and appends no rows;
* **island paused when the process died** -- it comes back paused with its own
  counters, the siblings keep going, and nobody sends it work;
* **ledger written, terminal output lost** -- the replay reads the committed rows,
  announces itself once, and re-appends none of them.

The scores asserted here are all the fake evaluator's; nothing a model produced
becomes a number a test reads back.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

import pytest

from faultevolve.cloud.engine import island_report, rebuild_run_report, run_local_evolution
from faultevolve.cloud.store import Store
from faultevolve.common.schemas import IslandState, NodeStatus
from faultevolve.worker.runner import FakeAdapter

from tests.test_island_cost import _config, _engine
from tests.test_island_exchange import (
    _exchange,
    _exchange_config,
    _scored_node,
    _summaries,
    _take_attempt,
)
from tests.test_island_isolation import _island_states, _tree_of, _valid
from tests.test_island_resume import _spec

SOURCE_INTENT = "用滚动窗口统计替代逐行判断"


@pytest.fixture
def temp_db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)
    yield db_path
    db_path.unlink(missing_ok=True)


@pytest.fixture
def task_dir(tmp_path: Path) -> Path:
    """A task directory the identity check can describe: text, evaluator, descriptor.

    It carries the four files every Famou-style task must have, so the same
    directory also works for ``run_local_evolution`` -- the point being that this
    run is driven by a generic task contract, not by an HDD-shaped one.
    """
    root = tmp_path / "task"
    (root / "data").mkdir(parents=True)
    (root / "evaluator.py").write_text("print('eval v1')\n", encoding="utf-8")
    (root / "init.py").write_text('"""seed"""\n', encoding="utf-8")
    (root / "problem.md").write_text("# Toy scoring task\n", encoding="utf-8")
    (root / "prompt.md").write_text("Make the toy metric better.\n", encoding="utf-8")
    (root / "data" / "meta.json").write_text(
        json.dumps({"horizon_days": 7, "splits": {"train": {"rows": 10}}}), encoding="utf-8"
    )
    return root


def _adapter(results: list[dict[str, Any]]) -> FakeAdapter:
    adapter = FakeAdapter()
    adapter.set_results(results + [_valid(20.0)] * 20)
    return adapter


def _results() -> list[dict[str, Any]]:
    return [_valid(22.0), _valid(25.0), _valid(26.0)]


def _typed(store: Store, experiment_id: str, event_type: str) -> list[dict[str, Any]]:
    return [
        event.payload
        for event in store.get_events(experiment_id)
        if event.type == event_type
    ]


def _deliveries(store: Store, experiment_id: str, summary_id: str | None = None):
    rows = store.get_deliveries(experiment_id)
    if summary_id is not None:
        rows = [d for d in rows if d.summary_id == summary_id]
    return rows


# ---------------------------------------------------------------------------
# 1. summary written, delivery missing -> exactly one offer per target
# ---------------------------------------------------------------------------


def test_a_summary_written_but_never_offered_is_offered_once(temp_db):
    store = Store(temp_db)
    producer = _exchange(store, "exp-fi1", task_fp="task-1", evaluator_fp="eval-1")
    state = IslandState(experiment_id="exp-fi1", island_id="a", attempts=2)
    node = _scored_node("exp-fi1", "a", 30.0, SOURCE_INTENT)

    # Publication and delivery are two inserts: the process died between them.
    summary = producer._publish_best(state, node, -1.0)
    assert summary is not None
    assert _deliveries(store, "exp-fi1") == [], "nothing left this island yet"

    # A restarted process, forced to say nothing new, still has to send it.
    reader = _exchange(store, "exp-fi1", task_fp="task-1", evaluator_fp="eval-1")
    outcome = reader.checkpoint(
        state, best_node=None, failed_nodes=[], target_islands=["b", "c"]
    )

    rows = _deliveries(store, "exp-fi1")
    assert {(d.summary_id, d.target_island_id, d.status) for d in rows} == {
        (summary.summary_id, "b", "offered"),
        (summary.summary_id, "c", "offered"),
    }, "exactly one offer per still-actionable sibling"
    assert outcome.delivered == 2
    assert len(store.get_summaries_by_experiment("exp-fi1", kinds=("best",))) == 1, (
        "the repair offers what exists; it does not write a second copy of the lesson"
    )

    backfilled = [p for kind, p in reader.events if kind == "exchange_delivery_backfilled"]  # type: ignore[attr-defined]
    assert {p["to"] for p in backfilled} == {"b", "c"}
    assert {p["summary_id"] for p in backfilled} == {summary.summary_id}
    assert {p["island_id"] for p in backfilled} == {"a"}

    # The one-delivery-per-(summary, target) key makes a second round quiet.
    again = reader.checkpoint(
        state, best_node=node, failed_nodes=[], target_islands=["b", "c"]
    )
    assert len(_deliveries(store, "exp-fi1")) == 2, "the repair is not a re-broadcast"
    assert again.delivered == 0
    assert again.zero_send is True


def test_the_repair_only_offers_siblings_that_can_still_act(temp_db):
    """An island that stopped gets nothing, so a repair cannot hand it work."""
    store = Store(temp_db)
    producer = _exchange(store, "exp-fi2", task_fp="task-1", evaluator_fp="eval-1")
    state = IslandState(experiment_id="exp-fi2", island_id="a", attempts=1)
    summary = producer._publish_best(
        state, _scored_node("exp-fi2", "a", 28.0, "分窗口建模"), -1.0
    )
    assert summary is not None

    reader = _exchange(store, "exp-fi2", task_fp="task-1", evaluator_fp="eval-1")
    # ``_exchange_targets`` of a live run names only pending/running siblings; c
    # finished for its own reasons, so it is simply not in the list.
    reader.checkpoint(state, best_node=None, failed_nodes=[], target_islands=["b"])

    rows = _deliveries(store, "exp-fi2")
    assert [(d.summary_id, d.target_island_id) for d in rows] == [
        (summary.summary_id, "b")
    ]


def test_a_resumed_round_offers_what_the_interrupted_round_never_sent(
    temp_db, task_dir
):
    """The gap closes inside the run loop, not only when called by hand."""
    adapter = _adapter([_valid(22.0), _valid(31.0)])
    config = _exchange_config()
    engine = _engine(temp_db, _spec(task_dir), adapter, config)
    experiment_id = engine.experiment_id

    # Both siblings are stopped, so island a publishes into an empty target list.
    for island_id in ("b", "c"):
        engine._coordinator.runtime(island_id).state.status = "finished"
    _take_attempt(engine, "a")

    published = [
        s for s in _summaries(engine, ("best",)) if s.source_island_id == "a"
    ]
    assert len(published) == 1, "the lesson was written"
    assert _deliveries(engine.store, experiment_id) == [], "and never sent"

    # The operator brings the siblings back before restarting the process.
    for island_id in ("b", "c"):
        engine._coordinator.runtime(island_id).state.status = "running"
    engine._coordinator.save_states()

    resumed = _engine(
        temp_db, _spec(task_dir), adapter, config, resume_id=experiment_id
    )
    resumed_state = resumed._coordinator.runtime("a").state
    outcome = resumed._exchange.checkpoint(
        resumed_state, best_node=None, failed_nodes=[], target_islands=["b", "c"]
    )
    assert outcome.delivered == 2
    rows = _deliveries(resumed.store, experiment_id, published[0].summary_id)
    assert sorted(d.target_island_id for d in rows) == ["b", "c"]
    assert all(d.status == "offered" for d in rows)

    # The next scheduled round has nothing new and repairs nothing either.
    quiet = resumed._exchange.checkpoint(
        resumed_state, best_node=None, failed_nodes=[], target_islands=["b", "c"]
    )
    assert quiet.delivered == 0
    assert len(_deliveries(resumed.store, experiment_id)) == 2


# ---------------------------------------------------------------------------
# 2. application written, candidate not evaluated -> unfinished, and saying so
# ---------------------------------------------------------------------------


class _Interrupted(RuntimeError):
    """The evaluator subprocess never answered: this process is ending here."""


def test_an_application_recorded_before_the_evaluator_stays_unfinished(
    temp_db, task_dir
):
    adapter = _adapter([_valid(22.0), _valid(31.0), _valid(18.0)])
    config = _exchange_config()
    engine = _engine(temp_db, _spec(task_dir), adapter, config)
    experiment_id = engine.experiment_id

    _take_attempt(engine, "a")
    published = [
        s for s in _summaries(engine, ("best",)) if s.source_island_id == "a"
    ][0]
    source_score = published.metrics["combined_score"]

    live_evaluate = adapter.evaluate

    def die(*args: Any, **kwargs: Any) -> Any:
        raise _Interrupted("stopped between generation and evaluation")

    adapter.evaluate = die  # type: ignore[method-assign]
    with pytest.raises(_Interrupted):
        _take_attempt(engine, "b")

    rows = engine.store.get_applications_by_experiment(experiment_id)
    pending = [r for r in rows if not r.evaluation_id]
    assert len(pending) == 1, (
        "the sibling's text went into exactly one candidate that got no result"
    )
    assert pending[0].score is None, "an un-evaluated candidate has no number to report"
    child = _tree_of(engine, "b").nodes[pending[0].candidate_node_id]
    assert child.evidence.evaluation is None
    assert child.status not in (NodeStatus.DONE, NodeStatus.INVALID), (
        "the candidate is not claimed as finished anywhere"
    )

    # A restart may not call it evaluated: the row is still exactly as unfinished.
    adapter.evaluate = live_evaluate
    resumed = _engine(
        temp_db, _spec(task_dir), adapter, config, resume_id=experiment_id
    )
    after_resume = [
        r
        for r in resumed.store.get_applications_by_experiment(experiment_id)
        if not r.evaluation_id
    ]
    assert [r.application_id for r in after_resume] == [pending[0].application_id]
    assert after_resume[0].evaluation_id == ""
    assert after_resume[0].score is None

    # The link is re-attached, and only for the island that owns the candidate.
    assert resumed._coordinator.runtime("b").attrs["_summary_applications"] == {
        child.id: [pending[0].application_id]
    }
    assert resumed._coordinator.runtime("a").attrs["_summary_applications"] == {}, (
        "island a does not adopt a sibling's unfinished row"
    )

    # The retry pays for the evaluation and only then completes the row.
    resumed._activate_island("b")
    tree_b = resumed._coordinator.runtime("b").attrs["tree"]
    node = tree_b.nodes[child.id]
    calls_before = adapter._call_count
    result, _delta = resumed._evaluate_child(
        tree_b.nodes[node.parent_id], node, [], count_iteration=False
    )
    row = [
        r
        for r in resumed.store.get_applications_by_experiment(experiment_id)
        if r.application_id == pending[0].application_id
    ][0]
    assert adapter._call_count == calls_before + 1, "one retry, one evaluation"
    assert row.evaluation_id == node.id
    assert row.score == result.combined_score
    assert row.score != source_score, "the receiver's own number, never the source's"


# ---------------------------------------------------------------------------
# 3. evaluations done, report missing -> rebuild reads, never re-scores
# ---------------------------------------------------------------------------


def test_a_run_that_lost_its_report_rebuilds_it_without_paying_again(
    temp_db, task_dir, tmp_path
):
    adapter = _adapter([_valid(22.0), _valid(31.0), _valid(18.0)])
    config = _exchange_config()
    engine = _engine(temp_db, _spec(task_dir), adapter, config)
    experiment_id = engine.experiment_id
    _take_attempt(engine, "a")
    _take_attempt(engine, "b")

    store = Store(temp_db)  # a restarted process opens its own handle
    nodes = store.get_nodes_by_experiment(experiment_id)
    valid_nodes = [
        n
        for n in nodes
        if n.evidence.evaluation is not None and n.evidence.evaluation.validity >= 1.0
    ]
    rollup_before = store.get_cost_rollup(experiment_id)
    calls_before = adapter._call_count
    rows_before = len(store.get_llm_calls(experiment_id))
    events_before = len(store.get_events(experiment_id))
    best_before = engine._best_across_islands()[1]

    art_dir = tmp_path / "lost-report"
    assert not art_dir.exists(), "the process died before writing any artifact"

    summary = rebuild_run_report(store, experiment_id, art_dir)

    assert adapter._call_count == calls_before, "rebuilding a report evaluates nothing"
    assert len(store.get_llm_calls(experiment_id)) == rows_before
    assert len(store.get_events(experiment_id)) == events_before, (
        "the rebuild is a reader: it appends no bookkeeping of its own"
    )
    assert summary["node_count"] == len(nodes)
    assert summary["valid_count"] == len(valid_nodes)
    assert summary["best_score"] == pytest.approx(best_before)
    assert summary["total_tokens"] == rollup_before["total_tokens"]
    assert summary["cost"]["total_tokens"] == rollup_before["total_tokens"]
    assert summary["rebuilt_from_store"] is True
    assert summary["islands"] == island_report(store, experiment_id)["islands"]
    assert summary["exchange"] == island_report(store, experiment_id)["exchange"]
    assert (art_dir / "run_summary.json").exists()
    assert (art_dir / "tree.json").exists()
    assert (art_dir / "programs").is_dir()
    assert len(list((art_dir / "programs").glob("*.py"))) == len(nodes)
    assert sum(1 for _ in (art_dir / "events.jsonl").open(encoding="utf-8")) == (
        events_before
    )

    # A second rebuild is the same projection: nothing accumulates per render.
    again = rebuild_run_report(store, experiment_id, art_dir)
    assert again == summary
    assert (art_dir / "run_summary.json").read_text(
        encoding="utf-8"
    ) == json.dumps(summary, indent=2, ensure_ascii=False)


def test_resuming_a_finished_run_rewrites_a_lost_report_without_evaluating(
    task_dir, tmp_path
):
    """The same interruption point through the production entry point.

    The direct-call test above can only observe rows and events; the adapter a
    re-evaluation would run on is reachable *here*, because ``run_local_evolution``
    holds it across the restart and rewrites the report in its ``finally``. The
    run is over (same iteration cap as before), so the resume has nothing left to
    do but re-project the database.
    """
    adapter = _adapter([_valid(22.0), _valid(31.0), _valid(18.0)])
    runs = tmp_path / "runs"
    first = run_local_evolution(
        task_dir=task_dir, mock=True, max_iterations=2, runs_dir=runs, adapter=adapter
    )
    run_id = first["experiment_id"]
    home = runs / run_id
    assert first["status"] == "finished"

    calls_before = adapter._call_count
    reader = Store(home / "fe.db", read_only=True)
    cost_rows_before = len(reader.get_llm_calls(run_id))
    (home / "run_summary.json").unlink()
    (home / "tree.json").unlink()

    resumed = run_local_evolution(
        task_dir=task_dir,
        mock=True,
        max_iterations=2,
        runs_dir=runs,
        adapter=adapter,
        resume_id=run_id,
    )

    assert resumed["status"] == "finished"
    assert adapter._call_count == calls_before, (
        "a finished run has nothing left to evaluate; the resume only re-projects"
    )
    assert (home / "run_summary.json").is_file()
    assert (home / "tree.json").is_file()
    assert len(reader.get_llm_calls(run_id)) == cost_rows_before


# ---------------------------------------------------------------------------
# 4. island paused when the process died -> it stays paused
# ---------------------------------------------------------------------------


def test_a_paused_island_comes_back_paused_with_its_own_counters(temp_db, task_dir):
    adapter = _adapter([_valid(22.0), _valid(31.0), _valid(18.0)])
    config = _exchange_config()
    engine = _engine(temp_db, _spec(task_dir), adapter, config)
    experiment_id = engine.experiment_id
    _take_attempt(engine, "a")
    _take_attempt(engine, "b")

    runtime_b = engine._coordinator.runtime("b")
    runtime_b.state.status = "paused"
    runtime_b.state.stop_reason = "operator"
    engine._coordinator.save_state("b")
    before = _island_states(engine)["b"]
    assert before.status == "paused"

    resumed = _engine(
        temp_db, _spec(task_dir), adapter, config, resume_id=experiment_id
    )
    after = resumed.store.get_island_state(experiment_id, "b")
    assert after is not None
    assert after.status == "paused", "a resume does not quietly put a stopped island back"
    assert after.attempts == before.attempts
    assert after.best_score == before.best_score
    assert after.stop_reason == "operator"
    assert resumed._coordinator.runtime("b").runnable is False

    taken: list[str] = []
    for _ in range(6):
        nxt = resumed._coordinator.next_runnable()
        assert nxt is not None, "two islands are still running, so the ring is not empty"
        taken.append(nxt.island_id)
    assert set(taken) == {"a", "c"}, "the ring keeps B's place but never hands it an attempt"

    # A/C really continue; B is untouched by their progress.
    for island_id in ("a", "c"):
        assert _take_attempt(resumed, island_id) is True
    states = _island_states(resumed)
    assert states["b"].status == "paused"
    assert states["b"].attempts == before.attempts
    assert states["a"].attempts > 0
    assert states["c"].attempts > 0


def test_a_paused_island_is_not_sent_work_by_its_siblings(temp_db, task_dir):
    adapter = _adapter([_valid(22.0), _valid(31.0), _valid(18.0)])
    config = _exchange_config()
    engine = _engine(temp_db, _spec(task_dir), adapter, config)
    experiment_id = engine.experiment_id
    _take_attempt(engine, "a")

    engine._coordinator.runtime("b").state.status = "paused"
    engine._coordinator.save_state("b")

    resumed = _engine(
        temp_db, _spec(task_dir), adapter, config, resume_id=experiment_id
    )
    runtime_a = resumed._coordinator.runtime("a")
    assert "b" not in resumed._exchange_targets(runtime_a), (
        "a paused sibling is not an actionable target"
    )

    # Island a finds a new best after the pause; only c may hear about it.
    resumed._exchange.checkpoint(
        runtime_a.state,
        best_node=_scored_node(experiment_id, "a", 40.0, "更严格的窗口对齐"),
        failed_nodes=[],
        target_islands=resumed._exchange_targets(runtime_a),
    )
    newest = [
        s
        for s in _summaries(resumed, ("best",))
        if s.metrics.get("combined_score") == 40.0
    ]
    assert len(newest) == 1
    rows = _deliveries(resumed.store, experiment_id, newest[0].summary_id)
    assert sorted(d.target_island_id for d in rows) == ["c"]
    assert resumed.store.get_island_state(experiment_id, "b").status == "paused"


# ---------------------------------------------------------------------------
# 5. ledger written, terminal output lost -> replay, do not re-append
# ---------------------------------------------------------------------------


def test_the_interrupted_run_committed_one_row_per_request(temp_db, task_dir):
    """The ledger is the durable spend, so its rows may not repeat.

    ``request_id`` counts inside one client, which is why a row's own id is the
    key: a resume gets a fresh client whose numbering starts again, and that must
    not make the run read as if it had paid twice.
    """
    adapter = _adapter(_results())
    config = _config(ledger=True)
    engine = _engine(temp_db, _spec(task_dir), adapter, config)
    _take_attempt(engine, "a")
    _take_attempt(engine, "b")

    rows = engine.store.get_llm_calls(engine.experiment_id)
    assert rows, "two attempts have to have spent something"
    assert len({r.id for r in rows}) == len(rows), "one row identity per spend"
    requested = [r.request_id for r in rows if r.request_id]
    assert len(set(requested)) == len(requested), (
        "this process appended the same request twice"
    )


def test_a_resume_replays_the_committed_ledger_and_appends_nothing(
    temp_db, task_dir
):
    adapter = _adapter(_results())
    config = _config(ledger=True)
    engine = _engine(temp_db, _spec(task_dir), adapter, config)
    experiment_id = engine.experiment_id
    _take_attempt(engine, "a")
    _take_attempt(engine, "b")

    store = Store(temp_db)
    rows_before = store.get_llm_calls(experiment_id)
    ledger_before = store.list_cost_records(experiment_id)
    rollup_before = store.get_cost_rollup(experiment_id)
    iterations_before = store.get_experiment(experiment_id).iterations_done
    assert ledger_before, "the run writes durable cost records too"
    assert len(_typed(store, experiment_id, "run_resumed")) == 0

    resumed = _engine(
        temp_db, _spec(task_dir), adapter, config, resume_id=experiment_id
    )
    resumed.run(max_iterations=1)

    after_store = Store(temp_db)
    payloads = _typed(after_store, experiment_id, "run_resumed")
    assert len(payloads) == 1, "one resume announces itself once"
    payload = payloads[0]
    assert payload["cost_rows"] == len(rows_before), (
        "the replay read exactly the rows the interrupted run had committed"
    )
    assert payload["total_tokens"] == rollup_before["total_tokens"]
    assert payload["iterations_done"] == iterations_before

    rows_after = after_store.get_llm_calls(experiment_id)
    assert len(rows_after) > len(rows_before), "the new attempt spent for real"
    assert len({r.id for r in rows_after}) == len(rows_after), (
        "the resumed run appended rows; it did not re-append the old ones"
    )
    by_id = {r.id: r for r in rows_after}
    for row in rows_before:
        kept = by_id[row.id]
        assert (kept.purpose, kept.request_id, kept.prompt_tokens, kept.completion_tokens) == (
            row.purpose,
            row.request_id,
            row.prompt_tokens,
            row.completion_tokens,
        ), "a committed cost row was rewritten"

    rollup_after = after_store.get_cost_rollup(experiment_id)
    assert rollup_after["total_tokens"] == sum(
        r.prompt_tokens + r.completion_tokens for r in rows_after
    )
    assert (
        sum(bucket["tokens"] for bucket in rollup_after["by_island"])
        + rollup_after["shared"]["tokens"]
    ) == rollup_after["total_tokens"], "a cost may not appear under two islands"

    # The counter the budget reads equals the durable ledger: no double counting.
    assert resumed.metrics.total_tokens == rollup_after["total_tokens"]

    # The autotune ledger counts on instead of re-using its own sequence numbers.
    ledger_after = after_store.list_cost_records(experiment_id)
    seqs = [r["seq"] for r in ledger_after]
    assert len(seqs) == len(set(seqs)), "(experiment, seq) is written twice"
    old_max = max(r["seq"] for r in ledger_before)
    old_seqs = {r["seq"] for r in ledger_before}
    assert {r["seq"] for r in ledger_after} >= old_seqs
    assert all(r["seq"] > old_max for r in ledger_after if r["seq"] not in old_seqs)


def test_the_run_directory_names_every_island_without_any_sql(task_dir, tmp_path):
    """A reader of run_summary.json sees the three trees and the exchange channel.

    This is the first file an operator opens after a run, so it has to answer "did
    each island really search, and did they talk" without knowing SQL -- and the
    same projection a rebuilt report writes, or the two files would disagree after
    a crash. The run is driven by a generic four-file task contract plus a fake
    evaluator, so nothing here is HDD-specific.
    """
    runs = tmp_path / "runs"
    config_path = tmp_path / "islands.yaml"
    config_path.write_text("islands:\n  exchange_interval: 1\n", encoding="utf-8")

    result = run_local_evolution(
        task_dir=task_dir,
        mock=True,
        max_iterations=6,
        runs_dir=runs,
        adapter=_adapter(_results()),
        seed=7,
        config_path=config_path,
    )
    experiment_id = result["experiment_id"]
    art_dir = Path(result["output_dir"])
    summary = json.loads(
        (art_dir / "run_summary.json").read_text(encoding="utf-8")
    )
    store = Store(Path(result["db_dir"]) / "fe.db")
    projection = island_report(store, experiment_id)

    assert set(summary["islands"]) == {"a", "b", "c"}
    assert {
        island["status"] for island in summary["islands"].values()
    } <= {"pending", "running", "paused", "finished"}, (
        "island status must be the plain lifecycle value, not an enum repr: "
        f"{[island['status'] for island in summary['islands'].values()]}"
    )
    assert {
        island["profile"] for island in summary["islands"].values()
    } == {"performance", "miss_alert", "efficiency"}
    assert all(island["attempts"] >= 1 for island in summary["islands"].values())
    assert sum(
        island["attempts"] for island in summary["islands"].values()
    ) == summary["iterations_done"], "an island attempt not counted in the summary"

    assert set(summary["exchange"]) == {
        "summaries",
        "by_kind",
        "deliveries",
        "accepted",
        "rejected",
        "applications",
        "evaluated_applications",
    }
    assert set(summary["exchange"]["by_kind"]) == {"best", "failure", "knowledge"}
    assert summary["exchange"]["summaries"] == len(
        store.get_summaries_by_experiment(experiment_id)
    )
    assert summary["exchange"]["deliveries"] == len(
        store.get_deliveries(experiment_id)
    )
    assert summary["exchange"]["applications"] == len(
        store.get_applications_by_experiment(experiment_id)
    )

    rebuilt = rebuild_run_report(
        Store(Path(result["db_dir"]) / "fe.db"), experiment_id, tmp_path / "rebuilt"
    )
    assert rebuilt["islands"] == projection["islands"] == summary["islands"]
    assert rebuilt["exchange"] == projection["exchange"] == summary["exchange"]

    # Cost: the run total has to be exactly the islands' own spend plus the
    # shared bucket, or a reader cannot tell which island to charge.
    assert set(summary["cost"]) == {
        "total_tokens",
        "by_island",
        "shared_tokens",
        "unresolved_calls",
        "cost_usd",
        "cost_basis",
    }
    rollup = store.get_cost_rollup(experiment_id)
    assert summary["cost"]["total_tokens"] == rollup["total_tokens"]
    assert sum(
        bucket["tokens"] for bucket in summary["cost"]["by_island"].values()
    ) + summary["cost"]["shared_tokens"] == rollup["total_tokens"]
    assert rebuilt["cost"] == projection["cost"] == summary["cost"]
