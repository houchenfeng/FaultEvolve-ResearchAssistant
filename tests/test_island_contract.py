"""S1 contract tests: island config, budget null semantics, store persistence.

Covers the behaviour required by THREE_ISLAND_REQUIREMENTS sections 3/5 and
TODO steps D1.4/D1.5 (suggestions T01/T03/T09 partial, plus store contracts).
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from pathlib import Path

import pytest
from pydantic import ValidationError

from faultevolve.cloud.budget import BudgetController, token_cap_exceeded, wall_cap_exceeded
from faultevolve.cloud.store import SCHEMA_VERSION, Store
from faultevolve.common.schemas import (
    ExchangeDelivery,
    ExchangeSummary,
    IslandState,
    Node,
    NodeArtifact,
    SchedulerState,
    SummaryApplication,
)
from faultevolve.config import (
    BudgetConfig,
    EvolveConfig,
    IslandSpec,
    IslandsConfig,
    default_islands,
)


# ---------------------------------------------------------------------------
# Configuration (D1.4)
# ---------------------------------------------------------------------------


def test_default_config_has_three_distinct_islands():
    cfg = EvolveConfig()
    islands = cfg.islands
    assert islands.enabled is True
    assert len(islands.islands) == 3
    assert [s.island_id for s in islands.islands] == ["a", "b", "c"]
    assert {s.profile for s in islands.islands} == {"performance", "miss_alert", "efficiency"}
    assert all(s.focus for s in islands.islands)


def test_island_defaults_are_audit_friendly():
    cfg = EvolveConfig()
    assert cfg.islands.exchange_interval == 5
    assert cfg.islands.max_positive_per_exchange == 1
    assert cfg.islands.max_negative_per_exchange == 2
    assert cfg.islands.eval_concurrency == 1
    assert all(s.max_attempts == 50 for s in cfg.islands.islands)
    assert all(s.exploration_ratio == pytest.approx(0.2) for s in cfg.islands.islands)


def test_explicit_single_island_config_allowed():
    cfg = IslandsConfig(
        enabled=False,
        islands=[IslandSpec(island_id="solo", profile="performance", focus="one tree")],
    )
    assert len(cfg.islands) == 1


def test_legacy_single_factory():
    cfg = IslandsConfig.legacy_single()
    assert cfg.enabled is False
    assert cfg.islands[0].island_id == "default"


def test_duplicate_island_ids_rejected():
    with pytest.raises(ValidationError, match="duplicate island_id"):
        IslandsConfig(islands=[
            IslandSpec(island_id="a", profile="performance", focus="x"),
            IslandSpec(island_id="a", profile="efficiency", focus="y"),
        ])


def test_empty_islands_rejected():
    with pytest.raises(ValidationError):
        IslandsConfig(islands=[])


def test_empty_island_id_rejected():
    with pytest.raises(ValidationError):
        IslandSpec(island_id="  ", profile="performance")


def test_invalid_profile_rejected():
    with pytest.raises(ValidationError):
        IslandSpec(island_id="z", profile="magic")


def test_custom_profile_requires_focus():
    with pytest.raises(ValidationError, match="requires a focus"):
        IslandSpec(island_id="d", profile="custom", focus="")
    spec = IslandSpec(island_id="d", profile="custom", focus="quarterly seasonality")
    assert spec.profile == "custom"


def test_invalid_exchange_interval_and_concurrency_rejected():
    with pytest.raises(ValidationError):
        IslandsConfig(exchange_interval=0)
    with pytest.raises(ValidationError):
        IslandsConfig(exchange_interval=-5)
    with pytest.raises(ValidationError):
        IslandsConfig(eval_concurrency=0)


def test_disabled_exchange_requires_single_island():
    with pytest.raises(ValidationError, match="exactly one island"):
        IslandsConfig(enabled=False, islands=default_islands())


def test_fourth_island_needs_own_profile():
    cfg = IslandsConfig(islands=[
        *[IslandSpec(**s) for s in default_islands()],
        IslandSpec(island_id="d", profile="custom", focus="seasonality grouping"),
    ])
    assert len(cfg.islands) == 4
    with pytest.raises(ValidationError, match="duplicate island profile"):
        IslandsConfig(islands=[
            *[IslandSpec(**s) for s in default_islands()],
            IslandSpec(island_id="d", profile="performance", focus="dup"),
        ])


def test_config_from_dict_roundtrip_preserves_islands():
    data = {
        "budget": {"max_iterations": 6, "max_tokens": None, "max_wall_hours": None},
        "islands": {
            "exchange_interval": 1,
            "islands": [
                {"island_id": "solo", "profile": "performance", "focus": "f", "max_attempts": 2},
            ],
        },
    }
    cfg = EvolveConfig.from_dict(json.loads(json.dumps(data)))
    dumped = cfg.model_dump()
    assert dumped["islands"]["exchange_interval"] == 1
    assert dumped["islands"]["islands"][0]["island_id"] == "solo"
    assert dumped["budget"]["max_tokens"] is None
    again = EvolveConfig.from_dict(dumped)
    assert [s.island_id for s in again.islands.islands] == ["solo"]


# ---------------------------------------------------------------------------
# Budget: explicit no-limit vs finite (D1.4 / T09)
# ---------------------------------------------------------------------------


def test_null_budget_accepted_and_never_triggers_caps():
    cfg = BudgetConfig(max_tokens=None, max_wall_hours=None)
    assert token_cap_exceeded(10**12, cfg.max_tokens) is False
    assert wall_cap_exceeded(9999.0, cfg.max_wall_hours) is False


def test_finite_budget_still_triggers():
    cfg = BudgetConfig(max_tokens=100, max_wall_hours=1.0)
    assert token_cap_exceeded(100, cfg.max_tokens) is True
    assert token_cap_exceeded(99, cfg.max_tokens) is False
    assert wall_cap_exceeded(1.5, cfg.max_wall_hours) is True


def test_fraction_stage_cap_inert_without_total_cap():
    bc = BudgetController(BudgetConfig(
        max_tokens=None,
        max_wall_hours=None,
        stage_caps={"reflect": 0.2},
    ))
    assert bc.stage_cap_tokens("reflect") is None
    assert bc.stage_exceeded("reflect", 10**9) is False
    assert bc.remaining_tokens(123) is None
    bc.cfg.expand_gating = True
    bc._costs.append(10)
    assert bc.should_expand(10**12, is_top_node=False) is True


def test_absolute_stage_cap_active_without_total():
    bc = BudgetController(BudgetConfig(max_tokens=None, stage_caps_absolute={"repair": 500}))
    assert bc.stage_cap_tokens("repair") == 500
    assert bc.stage_exceeded("repair", 500) is True
    assert bc.stage_exceeded("repair", 499) is False


def test_finite_stage_caps_keep_previous_semantics():
    bc = BudgetController(BudgetConfig(max_tokens=1000, stage_caps={"reflect": 0.25}))
    assert bc.stage_cap_tokens("reflect") == 250
    assert bc.remaining_tokens(800) == 200


def test_invalid_absolute_stage_cap_rejected():
    with pytest.raises(ValidationError):
        BudgetConfig(stage_caps_absolute={"bogus": 5})
    with pytest.raises(ValidationError):
        BudgetConfig(stage_caps_absolute={"jev": 0})


# ---------------------------------------------------------------------------
# Store: islands, summaries, deliveries, applications, scheduler (D1.2)
# ---------------------------------------------------------------------------


@pytest.fixture()
def store(tmp_path: Path) -> Store:
    return Store(tmp_path / "fe.db")


def make_node(node_id: str, island: str, parent: str | None = None) -> Node:
    return Node(
        id=node_id,
        experiment_id="exp1",
        island_id=island,
        parent_id=parent,
        branch_id="b1",
        artifact=NodeArtifact(code="print(1)"),
        created_at="2026-10-08T00:00:00+00:00",
    )


def test_schema_version_recorded(store: Store):
    with sqlite3.connect(str(store.db_path)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION


def test_nodes_persist_island_and_filter(store: Store):
    store.create_node(make_node("r1", "a"))
    store.create_node(make_node("r2", "b"))
    store.create_node(make_node("r3", "c"))
    store.create_node(make_node("a1", "a", parent="r1"))

    all_nodes = store.get_nodes_by_experiment("exp1")
    assert len(all_nodes) == 4
    for island, expected in (("a", {"r1", "a1"}), ("b", {"r2"}), ("c", {"r3"})):
        got = {n.id for n in store.get_nodes_by_experiment("exp1", island_id=island)}
        assert got == expected, island
    assert store.get_node("a1").island_id == "a"


def test_island_state_roundtrip_and_upsert(store: Store):
    state = IslandState(
        experiment_id="exp1", island_id="a", profile="performance",
        root_id="r1", status="running", attempts=3, valid_evaluations=2,
    )
    store.upsert_island_state(state)
    loaded = store.get_island_state("exp1", "a")
    assert loaded is not None
    assert loaded.root_id == "r1" and loaded.attempts == 3

    store.upsert_island_state(state.model_copy(update={"attempts": 4, "status": "paused"}))
    again = store.get_island_state("exp1", "a")
    assert again.attempts == 4 and again.status == "paused"
    assert again.created_at == loaded.created_at

    store.upsert_island_state(IslandState(experiment_id="exp1", island_id="b", profile="miss_alert"))
    store.upsert_island_state(IslandState(experiment_id="exp2", island_id="a", profile="efficiency"))
    assert {s.island_id for s in store.get_island_states("exp1")} == {"a", "b"}
    assert len(store.get_island_states("exp2")) == 1


def test_island_state_status_pattern(store: Store):
    with pytest.raises(ValidationError):
        IslandState(experiment_id="exp1", island_id="a", status="exploded")


def _summary(sid: str, text: str = "using EWMA smoothing on SMART-197 helped", kind: str = "best") -> ExchangeSummary:
    return ExchangeSummary(
        summary_id=sid,
        experiment_id="exp1",
        kind=kind,
        source_island_id="a",
        source_node_id="n7",
        summary_text=text,
        metrics={"combined_score": 30.1},
        content_hash=f"h-{sid}",
        created_at=f"2026-10-08T00:00:{len(sid) % 60:02d}+00:00",
    )


def test_summary_persist_and_dedup_by_content_hash(store: Store):
    s1 = _summary("s1")
    s2 = _summary("s2", text="whatever")
    s2 = s2.model_copy(update={"content_hash": s1.content_hash})
    assert store.create_summary(s1) is True
    assert store.create_summary(s2) is False, "same content hash must dedup"
    got = store.get_summary("s1")
    assert got is not None
    assert got.metrics["combined_score"] == pytest.approx(30.1)
    assert got.source_node_id == "n7"
    assert len(store.get_summaries_by_experiment("exp1")) == 1
    assert store.get_summaries_by_experiment("exp1", kinds=("failure",)) == []


def test_summary_rejects_overlong_text():
    with pytest.raises(ValidationError, match="exceeds"):
        _summary("sX", text="x" * 1201)


def test_delivery_and_application_dedup(store: Store):
    store.create_summary(_summary("s1"))
    d = ExchangeDelivery(
        delivery_id="d1", experiment_id="exp1", summary_id="s1",
        source_island_id="a", target_island_id="b",
    )
    assert store.create_delivery(d) is True
    dup = d.model_copy(update={"delivery_id": "d1b"})
    assert store.create_delivery(dup) is False, "one delivery per (summary, target)"

    store.update_delivery_decision("d1", "accepted", reason="matches recall goal")
    loaded = store.get_deliveries("exp1", target_island_id="b")
    assert loaded[0].status == "accepted" and loaded[0].reason == "matches recall goal"

    app = SummaryApplication(application_id="p1", delivery_id="d1", experiment_id="exp1", candidate_node_id="n21")
    assert store.record_application(app) is True
    assert store.record_application(app.model_copy(update={"application_id": "p2"})) is False
    store.complete_application("p1", evaluation_id="e9", score=31.5)
    done = store.get_applications_for_delivery("d1")[0]
    assert done.evaluation_id == "e9" and done.score == pytest.approx(31.5)
    assert len(store.get_applications_by_experiment("exp1")) == 1

    assert store.get_deliveries("exp1", statuses=("offered",)) == []
    assert len(store.get_deliveries("exp1", statuses=("accepted",))) == 1


def test_delivery_status_validated(store: Store):
    store.create_summary(_summary("s1"))
    store.create_delivery(ExchangeDelivery(
        delivery_id="d1", experiment_id="exp1", summary_id="s1",
        source_island_id="a", target_island_id="b",
    ))
    with pytest.raises(ValueError):
        store.update_delivery_decision("d1", "adopted")


def test_scheduler_state_roundtrip(store: Store):
    assert store.get_scheduler_state("exp1") is None
    store.save_scheduler_state(SchedulerState(experiment_id="exp1", next_island_index=2, rng_state_json="{\"x\":1}"))
    got = store.get_scheduler_state("exp1")
    assert got.next_island_index == 2 and got.schema_version == 2
    store.save_scheduler_state(SchedulerState(experiment_id="exp1", next_island_index=0))
    assert store.get_scheduler_state("exp1").next_island_index == 0


# ---------------------------------------------------------------------------
# Legacy store migration (read-only compatibility)
# ---------------------------------------------------------------------------

LEGACY_NODE_DDL = """
CREATE TABLE node (
    id TEXT PRIMARY KEY,
    experiment_id TEXT,
    parent_id TEXT,
    branch_id TEXT,
    depth INTEGER,
    operator TEXT,
    artifact_json TEXT,
    evidence_json TEXT,
    status TEXT,
    hypothesis_status TEXT,
    visit_count INTEGER DEFAULT 0,
    expand_count INTEGER DEFAULT 0,
    children_json TEXT,
    insight_ids_json TEXT,
    card_ids_json TEXT,
    branch_memory_json TEXT,
    repair_attempted INTEGER DEFAULT 0,
    hypothesis_fail_count INTEGER DEFAULT 0,
    repair_count INTEGER DEFAULT 0,
    repair_parent_id TEXT,
    error_class TEXT DEFAULT '',
    repair_exhausted INTEGER DEFAULT 0,
    created_at TEXT
);
"""


def test_legacy_db_migrates_and_reads_single_island(tmp_path: Path):
    db = tmp_path / "legacy.db"
    with sqlite3.connect(str(db)) as conn:
        conn.executescript(LEGACY_NODE_DDL)
        conn.execute(
            "INSERT INTO node (id, experiment_id, parent_id, branch_id, depth, operator,"
            " artifact_json, evidence_json, status, hypothesis_status, created_at)"
            " VALUES ('r1', 'old1', NULL, 'b1', 0, 'init', ?, '{}', 'done', 'open', '2026-01-01T00:00:00')",
            (json.dumps({"code": "print(1)"}),),
        )

    store = Store(db)
    nodes = store.get_nodes_by_experiment("old1")
    assert len(nodes) == 1
    assert nodes[0].island_id == "", "legacy rows resolve to the implicit single island"
    with sqlite3.connect(str(db)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert store.get_island_states("old1") == []
    store.create_node(make_node("n2", ""))
    assert len(store.get_nodes_by_experiment("exp1", island_id="")) == 1


# ---------------------------------------------------------------------------
# Read-only access to a historical run (D1.5 bullet 4, T18)
# ---------------------------------------------------------------------------

FIXTURE_RUNS = Path(__file__).resolve().parent / "fixtures" / "runs"
LEGACY_FIXTURE = FIXTURE_RUNS / "hdd_mvp_real_38cb38cf" / "fe.db"
#: The experiment id stored inside that committed historical run.
LEGACY_EXPERIMENT_ID = "38cb38cf"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.skipif(not LEGACY_FIXTURE.exists(), reason="committed fixture missing")
def test_read_only_store_never_touches_the_original():
    before = _sha256(LEGACY_FIXTURE)

    store = Store(LEGACY_FIXTURE, read_only=True)
    nodes = store.get_nodes_by_experiment(LEGACY_EXPERIMENT_ID)
    assert nodes, "fixture must contain nodes"
    assert {n.island_id for n in nodes} == {""}, "legacy rows are one implicit island"

    # Reads of island-era tables answer "nothing", not "no such table".
    assert store.get_island_states(LEGACY_EXPERIMENT_ID) == []
    assert store.get_scheduler_state(LEGACY_EXPERIMENT_ID) is None
    assert store.get_summaries_by_experiment(LEGACY_EXPERIMENT_ID) == []
    assert store.get_deliveries(LEGACY_EXPERIMENT_ID) == []

    assert _sha256(LEGACY_FIXTURE) == before, "read-only open must not migrate"
    with sqlite3.connect(str(LEGACY_FIXTURE)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 0
        assert "island_id" not in {r[1] for r in conn.execute("PRAGMA table_info(node)")}


@pytest.mark.skipif(not LEGACY_FIXTURE.exists(), reason="committed fixture missing")
def test_read_only_store_rejects_writes():
    store = Store(LEGACY_FIXTURE, read_only=True)
    with pytest.raises(sqlite3.OperationalError):
        store.upsert_island_state(IslandState(experiment_id="x", island_id="a"))
    assert store.get_experiment(LEGACY_EXPERIMENT_ID) is not None


@pytest.mark.skipif(not LEGACY_FIXTURE.exists(), reason="committed fixture missing")
def test_resumed_copy_migrates_without_touching_source(tmp_path: Path):
    """Resume path: copy the old run first, then open the copy for writing."""
    source_hash = _sha256(LEGACY_FIXTURE)
    target = tmp_path / "resumed" / "fe.db"
    target.parent.mkdir(parents=True)
    shutil.copy2(LEGACY_FIXTURE, target)

    store = Store(target)
    nodes = store.get_nodes_by_experiment(LEGACY_EXPERIMENT_ID)
    assert nodes
    with sqlite3.connect(str(target)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert "island_id" in {r[1] for r in conn.execute("PRAGMA table_info(node)")}

    store.upsert_island_state(IslandState(experiment_id=nodes[0].experiment_id, island_id="a"))
    assert len(store.get_island_states(nodes[0].experiment_id)) == 1
    assert _sha256(LEGACY_FIXTURE) == source_hash
