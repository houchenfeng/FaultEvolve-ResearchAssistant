"""S4 D4.2: every LLM request is one attributed cost row, and money is not guessed.

Three things this pins, all of them cheap to get wrong:

* a row says who paid -- island, the island's own attempt number, the stage, and
  the request identity including how many sends it took, so a run can be read
  after the fact instead of being re-derived from the prompt text;
* a request that went out and never came back is written down as unresolved, not
  omitted -- omitting it makes the run look cheaper than it was;
* money is never inferred from tokens. There is no rate table in this codebase, so
  the honest value is "unknown", and the totals have to reconcile as
  ``sum(per island) + shared == total`` without any currency attached.

Everything here is offline (MockLLM + FakeAdapter); the only scores asserted are
the local evaluator's numbers.
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path
from typing import Any

import pytest

from faultevolve.cloud.engine import EvolutionEngine
from faultevolve.cloud.llm import LLMTransientError, MockLLM
from faultevolve.cloud.store import Store
from faultevolve.common.metering import CallMetrics
from faultevolve.config import EvolveConfig
from faultevolve.worker.runner import FakeAdapter, FakeTaskSpec

from tests.test_island_exchange import _take_attempt
from tests.test_island_isolation import _valid


@pytest.fixture
def temp_db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)
    yield db_path
    db_path.unlink(missing_ok=True)


@pytest.fixture
def task_spec(tmp_path):
    return FakeTaskSpec(
        task_dir=tmp_path,
        init_code='"""init"""\npass\n',
        prompt_md="SHARED-TASK-INSTRUCTION",
    )


def _config(*, ledger: bool = False) -> EvolveConfig:
    """Three islands, one operator, knowledge off: cost rows only about cost."""
    config = EvolveConfig()
    config.budget.max_iterations = 20
    config.budget.max_wall_hours = 0.5
    config.budget.stall_iterations = 100
    config.smoke_test.enabled = False
    config.operators.enabled = ["refine"]
    config.operators.bandit = False
    config.islands.exchange_interval = 1
    config.knowledge.enabled = False
    config.autotune.ledger.enabled = ledger
    return config


def _engine(
    temp_db: Path,
    task_spec: FakeTaskSpec,
    adapter: FakeAdapter,
    config: EvolveConfig,
    llm: Any = None,
    resume_id: str | None = None,
) -> EvolutionEngine:
    engine = EvolutionEngine(
        config=config,
        task_adapter=adapter,
        task_spec=task_spec,
        store=Store(temp_db),
        llm=llm or MockLLM(enable_repair_scenario=False),
        mock=True,
    )
    engine.initialize(resume_id=resume_id)
    return engine


def _results() -> list[dict[str, Any]]:
    return [_valid(20.0)] + [_valid(25.0)] * 14


def _calls(engine: EvolutionEngine) -> list[Any]:
    return engine.store.get_llm_calls(engine.experiment_id)


def _events(engine: EvolutionEngine, event_type: str) -> list[dict[str, Any]]:
    return [
        e.payload
        for e in engine.store.get_events(engine.experiment_id)
        if e.type == event_type
    ]


def _rollup(engine: EvolutionEngine) -> dict[str, Any]:
    return engine.store.get_cost_rollup(engine.experiment_id)


class _ExplodingLLM(MockLLM):
    """Every send dies after the retries, carrying the identity of the request."""

    def __init__(self, error: LLMTransientError) -> None:
        super().__init__(enable_repair_scenario=False)
        self.error = error

    def chat(self, messages, **kwargs: Any):
        raise self.error


class _GarbageThenCodeLLM(MockLLM):
    """Answers once in an unusable format, then properly: one generation, two sends."""

    def __init__(self) -> None:
        super().__init__(enable_repair_scenario=False)
        self.sends = 0

    def chat(self, messages, **kwargs: Any):
        self.sends += 1
        if self.sends == 1:
            return (
                "I could not put that in the requested format.",
                CallMetrics(prompt_tokens=30, completion_tokens=5, request_id="chain-first"),
            )
        return super().chat(messages, **kwargs)


# ---------------------------------------------------------------------------
# One row, fully attributed
# ---------------------------------------------------------------------------


def test_every_cost_row_names_its_request_island_attempt_and_stage(temp_db, task_spec):
    adapter = FakeAdapter()
    adapter.set_results(_results())
    engine = _engine(temp_db, task_spec, adapter, _config())

    for island_id in ("a", "b", "c"):
        _take_attempt(engine, island_id)

    calls = _calls(engine)
    assert calls, "an island attempt made no LLM call at all"
    for call in calls:
        assert call.request_id, f"{call.purpose} row has no request identity"
        assert call.island_id in {"a", "b", "c"}, call.island_id
        assert call.stage in {"generate", "reflect", "repair", "crossover", "self_fix", "other"}
        assert call.purpose and call.model and call.created_at
        assert call.transport_attempts >= 1
        # The island was mid-attempt, so its attempt index is a real number here,
        # not null and not a zero that would read as "attempt zero".
        assert call.island_attempt is not None and call.island_attempt >= 1
        assert call.outcome == "ok"


def test_the_run_total_is_the_islands_plus_the_shared_bucket(temp_db, task_spec):
    adapter = FakeAdapter()
    adapter.set_results(_results())
    engine = _engine(temp_db, task_spec, adapter, _config())

    for island_id in ("a", "b", "c"):
        _take_attempt(engine, island_id)

    rollup = _rollup(engine)
    rows = _calls(engine)
    direct = sum(bucket["tokens"] for bucket in rollup["by_island"])
    assert rollup["total_tokens"] == direct + rollup["shared"]["tokens"]
    assert rollup["total_tokens"] == sum(
        c.prompt_tokens + c.completion_tokens for c in rows
    )
    # The same number the in-memory accounting reports, so a reader cannot get two
    # different costs out of one run.
    assert rollup["total_tokens"] == engine.metrics.total_tokens
    assert {bucket["island_id"] for bucket in rollup["by_island"]} == {"a", "b", "c"}


def test_one_request_is_never_counted_under_two_islands(temp_db, task_spec):
    """Delivery moves words, not spend: each row belongs to exactly one island."""
    adapter = FakeAdapter()
    adapter.set_results(_results())
    config = _config()
    config.operators.enabled = ["refine", "inject"]
    engine = _engine(temp_db, task_spec, adapter, config)

    for island_id in ("a", "b", "c", "a", "b"):
        _take_attempt(engine, island_id)

    rows = _calls(engine)
    rollup = _rollup(engine)
    assert (
        sum(bucket["calls"] for bucket in rollup["by_island"]) + rollup["shared"]["calls"]
        == len(rows)
    ), "the buckets do not partition the recorded calls"

    # Moving a summary between islands is program work: publish, deliver, accept
    # and apply write rows and events but never a cost row, and no row may be
    # billed to the island that only wrote the conclusion.
    assert not [c for c in rows if "exchange" in c.purpose or "deliver" in c.purpose]
    grafted = [c for c in rows if c.purpose == "summary_cross"]
    assert grafted, "the run never read a sibling, so this asserts nothing"
    for row in grafted:
        # Grafting a sibling's conclusion into a prompt is a real generation: the
        # island that read the summary pays for it.
        assert row.stage == "generate"
        assert row.island_attempt is not None
    assert not [c for c in rows if "knowledge" in c.purpose]


# ---------------------------------------------------------------------------
# A lost request is a spend, not an absence
# ---------------------------------------------------------------------------


def test_a_request_that_never_came_back_is_recorded_as_unresolved(temp_db, task_spec):
    adapter = FakeAdapter()
    adapter.set_results(_results())
    error = LLMTransientError("gateway died", request_id="req-lost-1", attempts=4)
    engine = _engine(temp_db, task_spec, adapter, _config(), _ExplodingLLM(error))

    _take_attempt(engine, "a")

    lost = [c for c in _calls(engine) if c.outcome == "unknown_outcome"]
    assert len(lost) == 1, lost
    assert lost[0].request_id == "req-lost-1"
    assert lost[0].transport_attempts == 4
    assert lost[0].island_id == "a"
    assert lost[0].stage == "generate"
    # The client never saw a usage report, so the honest token count is none --
    # and the rollup has to say one request is unresolved rather than free.
    assert lost[0].prompt_tokens == 0 and lost[0].completion_tokens == 0

    events = _events(engine, "llm_call_lost")
    assert [e["request_id"] for e in events] == ["req-lost-1"]
    assert events[0]["island_id"] == "a"

    rollup = _rollup(engine)
    island_a = next(b for b in rollup["by_island"] if b["island_id"] == "a")
    assert island_a["unresolved_calls"] == 1


def test_a_generation_that_needed_two_sends_says_so(temp_db, task_spec):
    """The operator's format-retry loop is several requests behind one row."""
    adapter = FakeAdapter()
    adapter.set_results(_results())
    engine = _engine(temp_db, task_spec, adapter, _config(), _GarbageThenCodeLLM())

    _take_attempt(engine, "a")

    generated = [c for c in _calls(engine) if c.stage == "generate"]
    assert len(generated) == 1, generated
    row = generated[0]
    assert row.transport_attempts == 2
    # The chain is named by its first send, and the tokens are the sum of both.
    assert row.request_id == "chain-first"
    assert row.prompt_tokens == 130 and row.completion_tokens == 205


# ---------------------------------------------------------------------------
# Money
# ---------------------------------------------------------------------------


def test_money_is_never_guessed_from_tokens(temp_db, task_spec):
    adapter = FakeAdapter()
    adapter.set_results(_results())
    engine = _engine(temp_db, task_spec, adapter, _config())

    _take_attempt(engine, "a")

    for call in _calls(engine):
        assert call.cost_usd is None
        assert call.cost_basis == "unknown"
    rollup = _rollup(engine)
    assert rollup["cost_usd"] is None
    assert rollup["cost_basis"] == "unknown", (
        "a run without a rate source must report unknown, not a number"
    )


# ---------------------------------------------------------------------------
# The stored ledger keeps counting across a restart
# ---------------------------------------------------------------------------


def test_a_resumed_ledger_continues_the_stored_sequence(temp_db, task_spec):
    """``cost_ledger`` is keyed by (experiment_id, seq), and a restart must not
    restart the sequence -- that would collide with the run's own history."""
    adapter = FakeAdapter()
    adapter.set_results(_results())
    config = _config(ledger=True)
    engine = _engine(temp_db, task_spec, adapter, config)

    _take_attempt(engine, "a")
    first = engine.store.list_cost_records(engine.experiment_id)
    assert first and max(r["seq"] for r in first) == len(first)

    resumed = _engine(temp_db, task_spec, adapter, config, resume_id=engine.experiment_id)
    _take_attempt(resumed, "b")

    after = resumed.store.list_cost_records(resumed.experiment_id)
    seqs = [r["seq"] for r in after]
    assert len(seqs) == len(set(seqs)), "a resumed run re-used a ledger sequence"
    assert seqs == sorted(seqs)
    assert max(seqs) == len(seqs), "the resumed ledger did not continue from the stored rows"
    assert {r["island_id"] for r in after} <= {"a", "b", "c", ""}
    assert [r["island_id"] for r in after[1:]] and any(
        r["island_id"] == "b" for r in after[len(first):]
    ), "records written after the restart are not attributed to an island"


# ---------------------------------------------------------------------------
# A run directory written before these columns existed
# ---------------------------------------------------------------------------


#: The identity columns ``llm_call`` gained with per-request accounting.
_LLM_CALL_COST_COLUMNS = (
    "request_id",
    "transport_attempts",
    "island_attempt",
    "stage",
    "outcome",
    "cost_usd",
    "cost_basis",
)


def test_an_old_run_directory_still_opens_and_reads(temp_db, task_spec):
    """Adding a column must not strand the databases that predate it.

    Two ways this breaks silently: the DDL's index on a column an old table does
    not have yet, and a reader that turns "that run never recorded it" into a
    number. Both are checked against a file with the columns taken back out.
    """
    adapter = FakeAdapter()
    adapter.set_results(_results())
    engine = _engine(temp_db, task_spec, adapter, _config())
    _take_attempt(engine, "a")
    experiment_id = engine.experiment_id
    recorded = _calls(engine)
    assert recorded[0].stage == "generate"
    tokens = sum(c.prompt_tokens + c.completion_tokens for c in recorded)

    conn = sqlite3.connect(temp_db)
    try:
        conn.execute("DROP INDEX IF EXISTS idx_cost_ledger_island")
        for column in _LLM_CALL_COST_COLUMNS:
            conn.execute(f"ALTER TABLE llm_call DROP COLUMN {column}")
        conn.execute("ALTER TABLE cost_ledger DROP COLUMN island_id")
        conn.commit()
    finally:
        conn.close()

    # Read the file as it really is before anything migrates it: the columns are
    # absent here, so a reader that asked for them by name would raise.
    legacy = Store(temp_db, read_only=True)
    old_rows = legacy.get_llm_calls(experiment_id)
    assert [c.stage for c in old_rows] == [""] * len(old_rows)
    assert [c.outcome for c in old_rows] == ["ok"] * len(old_rows)
    assert all(c.island_attempt is None and c.cost_usd is None for c in old_rows)
    old_rollup = legacy.get_cost_rollup(experiment_id)
    # The tokens that run did record still add up; only the identity is missing.
    assert old_rollup["total_tokens"] == tokens
    assert old_rollup["unresolved_calls"] == 0

    store = Store(temp_db)
    rows = store.get_llm_calls(experiment_id)
    assert len(rows) == len(old_rows), "migration lost or duplicated cost rows"
    assert rows[0].transport_attempts == 1
    assert rows[0].cost_basis == "unknown"
    rollup = store.get_cost_rollup(experiment_id)
    assert rollup["total_tokens"] == old_rollup["total_tokens"]
    assert [b["by_stage"] for b in rollup["by_island"]] == [
        {"other": b["tokens"]} for b in rollup["by_island"]
    ], "a migrated run invented a stage name for work that never recorded one"
