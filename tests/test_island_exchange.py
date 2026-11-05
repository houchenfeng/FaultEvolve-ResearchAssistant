"""S3 acceptance: islands exchange summaries, never programs.

TODO steps D3.1-D3.6 (tests T10-T14, T26). The distinction this file pins is the
one the whole stage rests on: *offered*, *accepted*, *applied* and *evaluated*
are four separate facts, and the only thing that crosses an island boundary is
method text plus numbers the local evaluator produced. Everything runs offline
(MockLLM + FakeAdapter), so every score asserted here is a number the engine
itself recorded -- never one a model was allowed to invent.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

import pytest

from faultevolve.cloud.engine import EvolutionEngine
from faultevolve.cloud.exchange import (
    IslandExchange,
    SummaryContext,
    content_hash,
    error_class_of,
    evaluator_fingerprint,
    sanitize,
    task_fingerprint,
)
from faultevolve.cloud.llm import MockLLM
from faultevolve.cloud.store import Store
from faultevolve.cloud.tree import create_init_node
from faultevolve.common.schemas import (
    EvaluationResult,
    ExchangeDelivery,
    IslandState,
    Node,
    NodeEvidence,
    NodeStatus,
    OperatorType,
)
from faultevolve.config import EvolveConfig
from faultevolve.worker.runner import FakeAdapter, FakeTaskSpec

from tests.test_island_isolation import (
    _RecordingLLM,
    _invalid,
    _island_states,
    _tree_of,
    _valid,
)

MARKER = "A-ONLY-SOURCE-MARKER-8842"


@pytest.fixture
def temp_db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)
    yield db_path
    db_path.unlink(missing_ok=True)


@pytest.fixture
def fake_task_spec(tmp_path):
    spec = FakeTaskSpec(
        task_dir=tmp_path,
        problem_md="predict failing disks",
        prompt_md="SHARED-TASK-INSTRUCTION",
        init_code='"""init"""\npass\n',
    )
    (tmp_path / "evaluator.py").write_text("SCORE = 1\n", encoding="utf-8")
    return spec


def _exchange_config(*, bandit: bool = False) -> EvolveConfig:
    """Three islands that talk after every single attempt."""
    config = EvolveConfig()
    config.budget.max_iterations = 30
    config.budget.max_wall_hours = 0.5
    config.budget.stall_iterations = 100
    config.smoke_test.enabled = False
    config.operators.bandit = bandit
    config.islands.exchange_interval = 1
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


def _take_attempt(engine: EvolutionEngine, island_id: str) -> bool:
    """One attempt, in the exact order the run loop uses."""
    rt = engine._coordinator.runtime(island_id)
    engine._activate_island(island_id)
    success = engine._run_one_iteration()
    engine._update_island_after_attempt(rt, success)
    engine._maybe_exchange(rt)
    return success


def _typed(engine: EvolutionEngine, event_type: str) -> list[Any]:
    return [e for e in engine.store.get_events(engine.experiment_id) if e.type == event_type]


def _summaries(engine: EvolutionEngine, kinds: tuple[str, ...]) -> list[Any]:
    return engine.store.get_summaries_by_experiment(engine.experiment_id, kinds=kinds)


def _prompts_for(llm: _RecordingLLM, config: EvolveConfig, island_id: str) -> list[str]:
    focus = next(s.focus for s in config.islands.islands if s.island_id == island_id)
    return [prompt for prompt in llm.prompts if focus in prompt]


def _scored_node(experiment_id: str, island_id: str, score: float, intent: str) -> Node:
    node = create_init_node(experiment_id, f"branch-{intent}", "# code", island_id=island_id)
    node.status = NodeStatus.DONE
    node.evidence = NodeEvidence(
        evaluation=EvaluationResult(
            validity=1.0, combined_score=score, cost_time=1.0, metric={}
        )
    )
    node.artifact.intent = intent
    return node


def _failed_node(experiment_id: str, island_id: str, error_class: str) -> Node:
    node = create_init_node(
        experiment_id, f"branch-{error_class}", "# code", island_id=island_id
    )
    node.status = NodeStatus.INVALID
    node.error_class = error_class
    node.evidence = NodeEvidence(
        evaluation=EvaluationResult(
            validity=0.0, combined_score=0.0, cost_time=0.5, error_info=error_class
        )
    )
    return node


def _exchange(store: Store, experiment_id: str, **fp: str) -> IslandExchange:
    events: list[tuple[str, dict[str, Any]]] = []
    exchange = IslandExchange(
        store=store,
        experiment_id=experiment_id,
        islands=EvolveConfig().islands,
        log_event=lambda t, p: events.append((t, p)),
        **fp,
    )
    exchange.events = events  # type: ignore[attr-defined]
    return exchange


# --------------------------------------------------------------------------
# D3.1 -- what may leave an island
# --------------------------------------------------------------------------


def test_sanitize_removes_programs_paths_and_identifiers_but_keeps_the_lesson():
    raw = (
        "NameError: name 'rolling' is not defined\n"
        "Traceback (most recent call last):\n"
        '  File "C:\\Users\\hdd\\project\\predict.py", line 88, in run\n'
        "  disk serial 123456789000 measured 2026-10-08T09:12:33\n"
        "```python\nimport pandas as pd\nmodel.fit(X, y)\n```\n"
        "改用滚动窗口统计，窗口 30 天"
    )
    clean = sanitize(raw)
    for fragment in (
        "predict.py",
        "C:\\",
        "123456789000",
        "model.fit",
        "import pandas",
        "Traceback",
        "2026-10-08T09:12:33",
    ):
        assert fragment not in clean, f"{fragment!r} survived sanitizing"
    assert "改用滚动窗口统计" in clean, "the usable lesson must survive"
    assert len(clean) <= 1200


def test_only_the_error_class_is_read_out_of_a_traceback():
    node = _failed_node("exp-x", "a", "")
    node.error_class = ""
    node.evidence = NodeEvidence(
        evaluation=EvaluationResult(
            validity=0.0,
            combined_score=0.0,
            cost_time=0.5,
            error_info="NameError: name 'x' is not defined\n  at /secret/path/holdout.csv",
        )
    )
    assert error_class_of(node) == "NameError"


def test_an_over_long_body_is_reduced_by_whole_segments_not_mid_sentence():
    """1200 chars is a budget, not a pair of scissors."""
    lines = [f"结论 {index}：" + "有效方法描述" * 25 for index in range(1, 13)]
    assert all(len(line) <= 160 for line in lines), "each line stays a description"
    assert len("；".join(lines)) > 1200, "the fixture must actually exceed the budget"
    clean = sanitize("；".join(lines))
    assert 0 < len(clean) <= 1200
    segments = clean.split("；")
    assert len(segments) < len(lines), "nothing was dropped, so the cap is unproven"
    for segment in segments:
        assert segment in lines, f"a kept segment is not a whole original line: {segment!r}"


def test_fingerprints_describe_task_and_evaluator(fake_task_spec):
    assert task_fingerprint(fake_task_spec) == task_fingerprint(fake_task_spec)
    fake_task_spec.prompt_md = "changed"
    assert task_fingerprint(fake_task_spec) != ""
    assert evaluator_fingerprint(fake_task_spec) != ""
    fake_task_spec.evaluator_path = Path("nowhere/evaluator.py")
    assert evaluator_fingerprint(fake_task_spec) == "", "unreadable stays unknown"


def test_content_hash_is_normalized_but_kind_sensitive():
    assert content_hash("best", "窗口 30 天", "岛 a") == content_hash(
        "best", "窗口  30\n天", "岛 a"
    )
    assert content_hash("best", "same", "same") != content_hash("failure", "same", "same")


def test_summary_dto_has_no_place_for_code():
    """The receiving side cannot copy a program it was never given."""
    ctx = SummaryContext(
        delivery_id="dlv-1",
        summary_id="sum-1",
        kind="best",
        source_island_id="a",
        source_node_id="n-1",
        text="method",
        conditions="岛 a",
        metrics={"combined_score": 30.0},
    )
    assert set(ctx.as_dict()) == {
        "delivery_id",
        "summary_id",
        "kind",
        "source_island_id",
        "source_node_id",
        "summary_text",
        "conditions",
        "metrics",
    }


# --------------------------------------------------------------------------
# T10 / D3.4 -- a positive summary reaches a sibling and gets its own result
# --------------------------------------------------------------------------


def test_a_positive_summary_reaches_the_sibling_prompt_and_is_evaluated_locally(
    temp_db, fake_task_spec
):
    adapter = FakeAdapter()
    # shared init, island a's candidate, island b's grafted candidate
    adapter.set_results(
        [_valid(22.0), _valid(31.0), _valid(18.0)] + [_valid(20.0)] * 20
    )
    llm = _RecordingLLM()
    config = _exchange_config()
    engine = _make_engine(temp_db, fake_task_spec, adapter, config, llm=llm)

    _take_attempt(engine, "a")
    _take_attempt(engine, "b")

    # Each island announces its own best, so a's message is scoped by its author.
    best = [s for s in _summaries(engine, ("best",)) if s.source_island_id == "a"]
    assert len(best) == 1
    assert best[0].metrics["combined_score"] == 31.0
    assert best[0].confidence_status == "single_observation"

    deliveries = [
        d for d in engine.store.get_deliveries(engine.experiment_id)
        if d.summary_id == best[0].summary_id
    ]
    assert {d.target_island_id for d in deliveries} == {"b", "c"}
    # b generated after the delivery, so it decided; c has not run yet (T26).
    assert {d.target_island_id: d.status for d in deliveries} == {"b": "accepted", "c": "offered"}

    prompts_b = _prompts_for(llm, config, "b")
    assert prompts_b, "island b never asked the model"
    assert any(best[0].summary_text in p for p in prompts_b), (
        "b's prompt never carried a's conclusion"
    )

    tree_b = _tree_of(engine, "b")
    grafted = [n for n in tree_b.nodes.values() if n.operator == OperatorType.SUMMARY_CROSS]
    assert len(grafted) == 1
    child = grafted[0]
    assert child.parent_id in tree_b.nodes, "the tree parent must stay in this island"
    assert child.parent_id != best[0].source_node_id
    assert engine.store.get_node_parents(child.id) == [], (
        "a summary graft is not a two-parent crossover"
    )
    assert child.get_score() == 18.0, "b's candidate keeps b's own evaluator number"

    applications = engine.store.get_applications_by_experiment(engine.experiment_id)
    assert [(a.candidate_node_id, a.score) for a in applications] == [(child.id, 18.0)]
    assert applications[0].evaluation_id == child.id

    applied = _typed(engine, "exchange_applied")
    assert [(e.payload["summary_id"], e.payload["from"]) for e in applied] == [
        (best[0].summary_id, "a")
    ]
    crossover = _typed(engine, "summary_crossover")
    assert len(crossover) == 1
    assert crossover[0].payload["island_id"] == "b"
    assert crossover[0].payload["parent_id"] == child.parent_id
    assert crossover[0].payload["sources"][0]["source_island_id"] == "a"
    assert crossover[0].payload["sources"][0]["source_node_id"] == best[0].source_node_id


def test_a_summary_is_delivered_once_per_target_island(temp_db):
    store = Store(temp_db)
    delivery = ExchangeDelivery(
        delivery_id="dlv-1",
        experiment_id="exp-d",
        summary_id="sum-1",
        source_island_id="a",
        target_island_id="b",
    )
    assert store.create_delivery(delivery) is True
    assert store.create_delivery(ExchangeDelivery(
        delivery_id="dlv-2", experiment_id="exp-d", summary_id="sum-1",
        source_island_id="a", target_island_id="b",
    )) is False
    assert len(store.get_deliveries("exp-d")) == 1


# --------------------------------------------------------------------------
# T11 -- a failure lesson arrives without the raw trace
# --------------------------------------------------------------------------


def test_a_failure_lesson_reaches_a_sibling_without_the_raw_trace(temp_db, fake_task_spec):
    adapter = FakeAdapter()
    adapter.set_results([
        _valid(22.0),
        _invalid(
            "NameError: name 'rolling' is not defined\n"
            '  File "C:\\data\\holdout\\disk_serial_1234567890.py", line 42\n'
            "  measured at 2026-10-08T09:12:33 with 9876543210 rows\n"
            "```\nimport numpy as np\nnp.roll(x, 30)\n```"
        ),
        _valid(24.0),
    ] + [_valid(24.0)] * 20)
    llm = _RecordingLLM()
    config = _exchange_config()
    engine = _make_engine(temp_db, fake_task_spec, adapter, config, llm=llm)

    _take_attempt(engine, "a")
    _take_attempt(engine, "c")

    failures = _summaries(engine, ("failure",))
    assert len(failures) == 1, "one new error class must produce one lesson"
    text = failures[0].summary_text
    assert "NameError" in text, "the classified error type is the usable part"
    for leak in (
        "holdout",
        "disk_serial_1234567890",
        "9876543210",
        "np.roll",
        "import numpy",
        "2026-10-08T09:12:33",
        "C:\\",
    ):
        assert leak not in text, f"sensitive fragment leaked: {leak}"
    assert failures[0].metrics["occurrences"] >= 1
    assert failures[0].metrics.get("combined_score") is None, (
        "a failed candidate has no score to advertise"
    )

    prompts_c = _prompts_for(llm, config, "c")
    assert any(text in p for p in prompts_c), "c never saw the avoidance condition"
    for prompt in prompts_c:
        for leak in ("holdout", "disk_serial_1234567890", "np.roll"):
            assert leak not in prompt


# --------------------------------------------------------------------------
# T12 -- island A's source never appears in island B's context
# --------------------------------------------------------------------------


def test_a_sibling_source_never_enters_the_receiving_prompt(temp_db, fake_task_spec):
    adapter = FakeAdapter()
    adapter.set_results(
        [_valid(22.0), _valid(31.0), _valid(20.0)] + [_valid(20.0)] * 20
    )
    llm = _RecordingLLM()
    config = _exchange_config()
    engine = _make_engine(temp_db, fake_task_spec, adapter, config, llm=llm)

    _take_attempt(engine, "a")
    # The only route from a's program to b is the summary, so mark the program.
    tree_a = _tree_of(engine, "a")
    best_id, _ = tree_a.get_island_best()
    tree_a.nodes[best_id].artifact.code += f"\n# {MARKER}\n"

    _take_attempt(engine, "b")

    best = [s for s in _summaries(engine, ("best",)) if s.source_island_id == "a"]
    assert best and best[0].source_node_id == best_id
    # The leak source is really marked, otherwise the absence below proves nothing.
    assert MARKER in tree_a.nodes[best_id].artifact.code

    prompts_b = _prompts_for(llm, config, "b")
    assert prompts_b, "island b never asked the model"
    assert any(best[0].summary_text in p for p in prompts_b), "the channel did not deliver"
    for prompt in prompts_b:
        assert MARKER not in prompt, "a's source reached b's context"
    for node in _tree_of(engine, "b").nodes.values():
        assert MARKER not in node.artifact.code, "b holds a copy of a's program"


# --------------------------------------------------------------------------
# T13 -- no score is inherited; an un-evaluated graft stays pending or invalid
# --------------------------------------------------------------------------


def test_a_grafted_candidate_never_inherits_the_source_score(temp_db, fake_task_spec):
    adapter = FakeAdapter()
    adapter.set_results(
        [_valid(22.0), _valid(31.0), _invalid("ZeroDivisionError: division by zero")]
        + [_valid(20.0)] * 20
    )
    config = _exchange_config()
    engine = _make_engine(temp_db, fake_task_spec, adapter, config)

    _take_attempt(engine, "a")
    _take_attempt(engine, "b")

    applications = engine.store.get_applications_by_experiment(engine.experiment_id)
    assert len(applications) == 1
    row = applications[0]
    assert row.score is None, "an invalid candidate has no score to record"
    assert row.evaluation_id == row.candidate_node_id
    assert row.candidate_node_id not in {s.source_node_id for s in _summaries(engine, ("best",))}


def test_an_application_is_pending_until_its_own_candidate_is_evaluated(temp_db):
    store = Store(temp_db)
    exchange = _exchange(store, "exp-p")
    context = SummaryContext(
        delivery_id="dlv-x",
        summary_id="sum-x",
        kind="best",
        source_island_id="a",
        source_node_id="n-x",
        text="t",
        conditions="岛 a",
        metrics={},
    )
    ids = exchange.record_applications([context], "cand-y")
    rows = store.get_applications_for_delivery("dlv-x")
    assert [(r.application_id, r.score, r.evaluation_id) for r in rows] == [
        (ids[0], None, "")
    ]

    # The same summary in the same candidate is one row, not two.
    assert exchange.record_applications([context], "cand-y") == []
    assert len(store.get_applications_for_delivery("dlv-x")) == 1

    exchange.complete_applications(ids, evaluation_id="cand-y", score=None)
    assert store.get_applications_for_delivery("dlv-x")[0].score is None


# --------------------------------------------------------------------------
# T14 -- a summary from another task or evaluator is refused, with a reason
# --------------------------------------------------------------------------


def test_a_summary_from_another_task_or_evaluator_is_rejected_with_reason(temp_db):
    store = Store(temp_db)
    producer = _exchange(store, "exp-a", task_fp="task-1", evaluator_fp="eval-1")
    producer.checkpoint(
        IslandState(experiment_id="exp-a", island_id="a", attempts=1),
        best_node=_scored_node("exp-a", "a", 30.0, "用滚动窗口统计替代逐行判断"),
        failed_nodes=[],
        target_islands=["b", "c", "d", "e"],
    )
    assert len(producer.events) >= 2  # type: ignore[attr-defined]

    foreign_task = _exchange(store, "exp-a", task_fp="task-2", evaluator_fp="eval-1")
    assert foreign_task.accept_for("b", runnable=True, best_score=10.0) == []
    assert [
        d.reason for d in store.get_deliveries("exp-a", target_island_id="b")
    ] == ["task_fingerprint_mismatch"]

    foreign_evaluator = _exchange(store, "exp-a", task_fp="task-1", evaluator_fp="eval-2")
    assert foreign_evaluator.accept_for("c", runnable=True, best_score=10.0) == []
    assert [
        d.reason for d in store.get_deliveries("exp-a", target_island_id="c")
    ] == ["evaluator_fingerprint_mismatch"]

    stopped = _exchange(store, "exp-a", task_fp="task-1", evaluator_fp="eval-1")
    assert stopped.accept_for("d", runnable=False, best_score=10.0) == []
    assert [
        d.reason for d in store.get_deliveries("exp-a", target_island_id="d")
    ] == ["target_island_not_runnable"]

    same = _exchange(store, "exp-a", task_fp="task-1", evaluator_fp="eval-1")
    accepted = same.accept_for("e", runnable=True, best_score=10.0)
    assert [c.metrics["combined_score"] for c in accepted] == [30.0]
    rejected_events = [
        p for t, p in same.events if t == "exchange_rejected"  # type: ignore[attr-defined]
    ]
    assert rejected_events == []


def test_an_overtaken_best_is_rejected_as_superseded(temp_db):
    store = Store(temp_db)
    exchange = _exchange(store, "exp-s")
    state = IslandState(experiment_id="exp-s", island_id="a", attempts=3)
    for index, score in enumerate((20.0, 30.0, 40.0), start=1):
        exchange.checkpoint(
            state,
            best_node=_scored_node("exp-s", "a", score, f"策略 {index}"),
            failed_nodes=[],
            target_islands=["b"],
        )

    contexts = exchange.accept_for("b", runnable=True, best_score=10.0)
    assert [c.metrics["combined_score"] for c in contexts] == [40.0], (
        "only the sibling's current best may be grafted"
    )
    rejected = store.get_deliveries("exp-s", target_island_id="b", statuses=("rejected",))
    assert [d.reason for d in rejected] == [
        "superseded_by_newer_best",
        "superseded_by_newer_best",
    ]

    # A second read replays the decision instead of re-deciding (restart-safe).
    again = exchange.accept_for("b", runnable=True, best_score=10.0)
    assert [c.summary_id for c in again] == [c.summary_id for c in contexts]
    events = [t for t, _ in exchange.events]  # type: ignore[attr-defined]
    assert events.count("exchange_rejected") == 2, "re-reading must not re-decide"


def test_the_context_queue_is_capped_at_the_configured_size(temp_db):
    store = Store(temp_db)
    islands = EvolveConfig().islands
    islands.max_summaries_in_context = 2
    exchange = IslandExchange(
        store=store,
        experiment_id="exp-q",
        islands=islands,
        log_event=lambda t, p: None,
    )
    state = IslandState(experiment_id="exp-q", island_id="a", attempts=4)
    exchange.checkpoint(
        state,
        best_node=_scored_node("exp-q", "a", 40.0, "领先策略"),
        failed_nodes=[_failed_node("exp-q", "a", "NameError")],
        target_islands=["b"],
    )
    exchange.checkpoint(
        state,
        best_node=None,
        failed_nodes=[_failed_node("exp-q", "a", "ZeroDivisionError")],
        target_islands=["b"],
    )

    contexts = exchange.accept_for("b", runnable=True, best_score=10.0)
    assert len(contexts) == 2, "history must not pile up in every prompt"
    assert contexts[0].kind == "best", "the sibling that is ahead leads the queue"


# --------------------------------------------------------------------------
# T10 idempotency / D3.3 -- the cursor, repetition and restart
# --------------------------------------------------------------------------


def test_the_same_lesson_is_published_once_even_across_a_restart(
    temp_db, fake_task_spec
):
    adapter = FakeAdapter()
    adapter.set_results([_valid(22.0), _valid(31.0)] + [_valid(20.0)] * 20)
    config = _exchange_config()
    engine = _make_engine(temp_db, fake_task_spec, adapter, config)

    _take_attempt(engine, "a")
    assert (
        len(_summaries(engine, ("best",))),
        len(engine.store.get_deliveries(engine.experiment_id)),
    ) == (1, 2)

    # The cursor is what keeps a not-yet-due island quiet, and it is persisted.
    rt_a = engine._coordinator.runtime("a")
    engine._maybe_exchange(rt_a)
    assert len(_summaries(engine, ("best",))) == 1
    assert rt_a.state.last_exchange_attempt == rt_a.state.attempts

    resumed = EvolutionEngine(
        config=config,
        task_adapter=adapter,
        task_spec=fake_task_spec,
        store=Store(temp_db),
        llm=MockLLM(),
        mock=True,
    )
    resumed.initialize(resume_id=engine.experiment_id)
    assert resumed._exchange is not None
    state = resumed._coordinator.runtime("a").state
    assert state.last_exchange_attempt == state.attempts
    tree_a = _tree_of(resumed, "a")
    best_id, _ = tree_a.get_island_best()
    # Force the round the way a due checkpoint would, to prove publication itself
    # is idempotent: the store remembers what island a already announced.
    resumed._exchange.checkpoint(
        state,
        best_node=tree_a.nodes[best_id],
        failed_nodes=resumed._unpublished_failures(resumed._coordinator.runtime("a")),
        target_islands=["b", "c"],
    )
    assert len(resumed.store.get_summaries_by_experiment(
        engine.experiment_id, kinds=("best",)
    )) == 1
    assert len(resumed.store.get_deliveries(engine.experiment_id)) == 2


def test_a_repeat_of_the_same_error_adds_evidence_instead_of_a_second_message(
    temp_db, fake_task_spec
):
    adapter = FakeAdapter()
    # Each island attempt that fails is followed by its own repair, so the two
    # lessons below come from two separate generative candidates.
    adapter.set_results([
        _valid(22.0),
        _invalid("NameError: name 'rolling' is not defined"),
        _valid(19.0),
        _invalid("NameError: name 'window' is not defined"),
        _valid(19.0),
    ] + [_valid(20.0)] * 20)
    config = _exchange_config()
    engine = _make_engine(temp_db, fake_task_spec, adapter, config)

    _take_attempt(engine, "a")
    failures = _summaries(engine, ("failure",))
    assert len(failures) == 1
    assert len(failures[0].evidence_refs) == 1
    assert failures[0].confidence_status == "single_observation"
    deliveries_after_first = len(engine.store.get_deliveries(engine.experiment_id))

    _take_attempt(engine, "a")
    failures = _summaries(engine, ("failure",))
    assert len(failures) == 1, "the same error class must not fork a second lesson"
    assert len(failures[0].evidence_refs) == 2, "both candidates should back it"
    assert failures[0].confidence_status == "replicated"
    assert failures[0].metrics["occurrences"] >= 2
    assert len(engine.store.get_deliveries(engine.experiment_id)) == deliveries_after_first
    assert _typed(engine, "exchange_summary_replicated")


def test_a_baseline_root_is_described_without_claiming_an_improvement(
    temp_db, fake_task_spec
):
    """Nothing beat the island yet, so the shared start is only a baseline.

    The second round has nothing new to say, which is what makes the zero-send
    accounting visible instead of being inferred from an absence of rows.
    """
    adapter = FakeAdapter()
    adapter.set_results([_valid(22.0), _valid(21.0)] + [_valid(21.0)] * 20)
    config = _exchange_config()
    engine = _make_engine(temp_db, fake_task_spec, adapter, config)

    _take_attempt(engine, "a")
    best = _summaries(engine, ("best",))
    assert len(best) == 1, "the island's own baseline strategy may still be described"
    root = _tree_of(engine, "a").get_root()
    assert best[0].source_node_id == root.id
    assert "gain_vs_published_best" not in best[0].metrics
    assert "previous_published_best" not in best[0].metrics

    checks = _typed(engine, "exchange_check")
    assert checks and checks[0].payload["island_id"] == "a"

    _take_attempt(engine, "a")
    assert len(_summaries(engine, ("best",))) == 1, "a worse candidate is not a new best"
    checks = _typed(engine, "exchange_check")
    assert len(checks) == 2
    assert checks[1].payload["zero_send"] is True
    rt_a = engine._coordinator.runtime("a")
    assert rt_a.state.last_exchange_attempt == rt_a.state.attempts


# --------------------------------------------------------------------------
# D3.3 -- an island that stopped takes no further part
# --------------------------------------------------------------------------


def test_a_stopped_island_is_neither_a_reader_nor_a_writer(temp_db, fake_task_spec):
    adapter = FakeAdapter()
    adapter.set_results([_valid(22.0), _valid(31.0)] + [_valid(20.0)] * 20)
    config = _exchange_config()
    engine = _make_engine(temp_db, fake_task_spec, adapter, config)

    engine._coordinator.runtime("c").state.status = "finished"
    engine._coordinator.runtime("c").state.stop_reason = "max_attempts"

    _take_attempt(engine, "a")

    targets = {d.target_island_id for d in engine.store.get_deliveries(engine.experiment_id)}
    assert targets == {"b"}, "a finished island must not be sent work"
    assert _island_states(engine)["c"].attempts == 0


def test_a_broken_summary_channel_never_touches_a_score(temp_db, fake_task_spec):
    """A failed bookkeeping step is recorded; the candidate keeps its result."""
    adapter = FakeAdapter()
    adapter.set_results([_valid(22.0), _valid(31.0)] + [_valid(20.0)] * 20)
    config = _exchange_config()
    engine = _make_engine(temp_db, fake_task_spec, adapter, config)

    def explode(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("summary channel down")

    engine._exchange._publish_best = explode  # type: ignore[method-assign]
    _take_attempt(engine, "a")

    assert _typed(engine, "exchange_summary_failed")
    checks = _typed(engine, "exchange_check")
    assert checks and checks[0].payload["zero_send"] is True
    assert _island_states(engine)["a"].best_score == 31.0, "the evaluator's number is untouched"
    assert _summaries(engine, ("best",)) == []


# --------------------------------------------------------------------------
# T26 / D3.6 -- the four facts are counted on four separate axes
# --------------------------------------------------------------------------


def _exchange_counts(engine: EvolutionEngine, summary_id: str) -> dict[str, int]:
    """offered / accepted / applied / evaluated for one summary, axis by axis.

    Scoped to one summary on purpose: every island also announces its own best,
    so a run-level total would mix four authors' messages into one number.
    """
    deliveries = [
        d for d in engine.store.get_deliveries(engine.experiment_id)
        if d.summary_id == summary_id
    ]
    delivery_ids = {d.delivery_id for d in deliveries}
    applications = [
        a for a in engine.store.get_applications_by_experiment(engine.experiment_id)
        if a.delivery_id in delivery_ids
    ]
    return {
        "delivered": len(deliveries),
        "offered": len([d for d in deliveries if d.status == "offered"]),
        "accepted": len([d for d in deliveries if d.status == "accepted"]),
        "rejected": len([d for d in deliveries if d.status == "rejected"]),
        "applied": len(applications),
        "evaluated": len([a for a in applications if a.evaluation_id]),
    }


def test_offered_accepted_applied_and_evaluated_are_not_counted_as_one(
    temp_db, fake_task_spec
):
    adapter = FakeAdapter()
    # shared init, a's champion, b's and c's grafted candidates
    adapter.set_results(
        [_valid(22.0), _valid(31.0), _valid(18.0), _valid(19.0)] + [_valid(20.0)] * 20
    )
    config = _exchange_config()
    engine = _make_engine(temp_db, fake_task_spec, adapter, config)

    _take_attempt(engine, "a")
    published = [
        s for s in _summaries(engine, ("best",)) if s.source_island_id == "a"
    ][0]
    # One message, two readers, no decision taken yet.
    assert _exchange_counts(engine, published.summary_id) == {
        "delivered": 2, "offered": 2, "accepted": 0, "rejected": 0,
        "applied": 0, "evaluated": 0,
    }

    _take_attempt(engine, "b")
    # b looked: it accepted, the text entered one candidate, and that candidate
    # then got its own evaluator result.
    assert _exchange_counts(engine, published.summary_id) == {
        "delivered": 2, "offered": 1, "accepted": 1, "rejected": 0,
        "applied": 1, "evaluated": 1,
    }

    _take_attempt(engine, "c")
    # The same delivery serves a second island, so *accepted* counts readers
    # while *applied* counts prompt injections -- one delivery, two of each.
    assert _exchange_counts(engine, published.summary_id) == {
        "delivered": 2, "offered": 0, "accepted": 2, "rejected": 0,
        "applied": 2, "evaluated": 2,
    }

    delivery_ids = {
        d.delivery_id
        for d in engine.store.get_deliveries(engine.experiment_id)
        if d.summary_id == published.summary_id
    }
    scores = {
        a.candidate_node_id: a.score
        for a in engine.store.get_applications_by_experiment(engine.experiment_id)
        if a.delivery_id in delivery_ids
    }
    assert set(scores.values()) == {18.0, 19.0}, (
        "an application carries the receiver's number, never the source's 31.0"
    )


# --------------------------------------------------------------------------
# D3.3 -- a one-tree run has no sibling to talk to
# --------------------------------------------------------------------------


def test_a_single_island_run_has_no_summary_channel(temp_db, fake_task_spec):
    adapter = FakeAdapter()
    adapter.set_results([_valid(22.0), _valid(31.0)] + [_valid(20.0)] * 20)
    config = _exchange_config()
    config.islands = EvolveConfig().islands.legacy_single()
    engine = _make_engine(temp_db, fake_task_spec, adapter, config)

    assert engine._exchange is None
    assert len(engine._coordinator.order) == 1
    engine._activate_island(engine._coordinator.order[0])
    assert engine._run_one_iteration() is True
    assert engine._summary_contexts == []
    assert engine._accepted_summaries() == []
