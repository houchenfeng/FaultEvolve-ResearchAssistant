"""SQLite-based persistence for FaultEvolve.

Stores experiments, nodes, evaluations, insights, and events.
Uses WAL mode for better concurrent read performance.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from faultevolve.common.schemas import (
    DELIVERY_STATUSES,
    Event,
    ExchangeDelivery,
    ExchangeSummary,
    Experiment,
    ExperimentConfig,
    Insight,
    IslandState,
    LLMCall,
    Node,
    SchedulerState,
    SummaryApplication,
)

DDL = """
CREATE TABLE IF NOT EXISTS experiment (
    id TEXT PRIMARY KEY,
    name TEXT,
    status TEXT,
    config_json TEXT,
    problem_md TEXT,
    prompt_md TEXT,
    best_node_id TEXT,
    best_score REAL DEFAULT 0,
    iterations_done INTEGER DEFAULT 0,
    total_tokens INTEGER DEFAULT 0,
    created_at TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS node (
    id TEXT PRIMARY KEY,
    experiment_id TEXT,
    island_id TEXT NOT NULL DEFAULT '',
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

CREATE TABLE IF NOT EXISTS insight (
    id TEXT PRIMARY KEY,
    experiment_id TEXT,
    origin_node TEXT,
    branch_id TEXT,
    island_id TEXT NOT NULL DEFAULT '',
    polarity INTEGER,
    payload_json TEXT,
    delta REAL,
    z_score REAL,
    alpha REAL DEFAULT 1,
    beta REAL DEFAULT 1,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS llm_call (
    id TEXT PRIMARY KEY,
    experiment_id TEXT,
    island_id TEXT NOT NULL DEFAULT '',
    node_id TEXT,
    purpose TEXT,
    model TEXT,
    prompt_tokens INTEGER,
    completion_tokens INTEGER,
    latency_ms INTEGER,
    cached INTEGER DEFAULT 0,
    created_at TEXT,
    request_id TEXT NOT NULL DEFAULT '',
    transport_attempts INTEGER NOT NULL DEFAULT 1,
    island_attempt INTEGER,
    stage TEXT NOT NULL DEFAULT '',
    outcome TEXT NOT NULL DEFAULT 'ok',
    cost_usd REAL,
    cost_basis TEXT NOT NULL DEFAULT 'unknown'
);

CREATE TABLE IF NOT EXISTS event (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id TEXT,
    type TEXT,
    payload_json TEXT,
    ts TEXT
);

CREATE TABLE IF NOT EXISTS card_stats (
    experiment_id TEXT,
    card_id TEXT,
    n INTEGER DEFAULT 0,
    sum_delta REAL DEFAULT 0.0,
    sum_sq REAL DEFAULT 0.0,
    refuted_count INTEGER DEFAULT 0,
    invalid_count INTEGER DEFAULT 0,
    PRIMARY KEY (experiment_id, card_id)
);

CREATE TABLE IF NOT EXISTS branch_offered_cards (
    experiment_id TEXT,
    branch_id TEXT,
    card_id TEXT,
    iteration INTEGER,
    was_invalid INTEGER DEFAULT 0,
    offered_at TEXT,
    PRIMARY KEY (experiment_id, branch_id, card_id, iteration)
);

CREATE TABLE IF NOT EXISTS branch_refuted_cards (
    experiment_id TEXT,
    branch_id TEXT,
    card_id TEXT,
    refuted_at TEXT,
    PRIMARY KEY (experiment_id, branch_id, card_id)
);

CREATE TABLE IF NOT EXISTS node_adopted_cards (
    node_id TEXT,
    card_id TEXT,
    adopted_at TEXT,
    PRIMARY KEY (node_id, card_id)
);

CREATE TABLE IF NOT EXISTS operator_stats (
    experiment_id TEXT,
    island_id TEXT NOT NULL DEFAULT '',
    operator TEXT,
    alpha REAL,
    beta REAL,
    n INTEGER DEFAULT 0,
    n_valid INTEGER DEFAULT 0,
    sum_delta REAL DEFAULT 0.0,
    PRIMARY KEY (experiment_id, island_id, operator)
);

CREATE INDEX IF NOT EXISTS idx_node_experiment ON node(experiment_id);
CREATE INDEX IF NOT EXISTS idx_node_parent ON node(parent_id);
CREATE INDEX IF NOT EXISTS idx_insight_experiment ON insight(experiment_id);
CREATE INDEX IF NOT EXISTS idx_event_experiment ON event(experiment_id);
CREATE INDEX IF NOT EXISTS idx_card_stats_experiment ON card_stats(experiment_id);

CREATE TABLE IF NOT EXISTS claim (
    id TEXT PRIMARY KEY,
    experiment_id TEXT,
    origin_node_id TEXT,
    source TEXT,
    round INTEGER,
    payload_json TEXT,
    prereg_hash TEXT,
    status TEXT,
    grade TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS claim_test (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_id TEXT,
    experiment_id TEXT,
    split TEXT,
    payload_json TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS discovered_card (
    card_id TEXT PRIMARY KEY,
    claim_id TEXT,
    experiment_id TEXT,
    grade TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS mechanism (
    id TEXT PRIMARY KEY,
    experiment_id TEXT,
    claim_id TEXT,
    family_id TEXT,
    role TEXT,
    status TEXT,
    patch_count INTEGER,
    payload_json TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS match (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id TEXT,
    family_id TEXT,
    round INTEGER,
    mech_a TEXT,
    mech_b TEXT,
    slice_id TEXT,
    payload_json TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS test_result (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id INTEGER,
    experiment_id TEXT,
    test_type TEXT,
    payload_json TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS certificate (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id TEXT,
    mechanism_id TEXT,
    rival_id TEXT,
    payload_json TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS theory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id TEXT,
    payload_json TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS node_parents (
    experiment_id TEXT,
    node_id TEXT,
    parent_id TEXT,
    role TEXT,
    PRIMARY KEY (node_id, parent_id, role)
);
CREATE INDEX IF NOT EXISTS idx_node_parents_node ON node_parents(node_id);

CREATE TABLE IF NOT EXISTS cost_ledger (
    experiment_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    island_id TEXT NOT NULL DEFAULT '',
    stage TEXT NOT NULL,
    fidelity TEXT NOT NULL,
    node_id TEXT,
    prompt_tokens INTEGER DEFAULT 0,
    completion_tokens INTEGER DEFAULT 0,
    model_fit_count INTEGER DEFAULT 0,
    evaluator_calls INTEGER DEFAULT 0,
    cpu_seconds REAL,
    rss_peak_mb REAL,
    wall_s REAL DEFAULT 0,
    cache_hit INTEGER DEFAULT 0,
    status TEXT NOT NULL,
    reservation_id TEXT,
    meta_json TEXT,
    created_at TEXT,
    PRIMARY KEY (experiment_id, seq)
);

CREATE TABLE IF NOT EXISTS candidate_spec (
    id TEXT PRIMARY KEY,
    experiment_id TEXT NOT NULL,
    structure_id TEXT NOT NULL,
    spec_json TEXT NOT NULL,
    source_hash TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS hpo_trial (
    trial_id TEXT PRIMARY KEY,
    experiment_id TEXT NOT NULL,
    structure_id TEXT NOT NULL,
    trial_index INTEGER NOT NULL,
    config_hash TEXT NOT NULL,
    params_json TEXT NOT NULL,
    seed INTEGER NOT NULL,
    fidelity TEXT NOT NULL,
    status TEXT NOT NULL,
    fit_count INTEGER DEFAULT 0,
    dev_proxy REAL,
    dev_metrics_json TEXT,
    cache_hit INTEGER DEFAULT 0,
    failure_reason TEXT,
    promoted_node_id TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS eval_cache (
    key TEXT PRIMARY KEY,
    fidelity TEXT NOT NULL,
    result_json TEXT NOT NULL,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS explore_archive (
    experiment_id TEXT NOT NULL,
    node_id TEXT NOT NULL,
    reason TEXT NOT NULL,
    parent_score REAL,
    score REAL,
    module TEXT,
    created_at TEXT,
    PRIMARY KEY (experiment_id, node_id)
);

CREATE TABLE IF NOT EXISTS island_state (
    experiment_id TEXT NOT NULL,
    island_id TEXT NOT NULL,
    profile TEXT NOT NULL DEFAULT 'performance',
    root_id TEXT,
    best_node_id TEXT,
    best_score REAL DEFAULT 0,
    attempts INTEGER DEFAULT 0,
    valid_evaluations INTEGER DEFAULT 0,
    invalid_evaluations INTEGER DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending',
    stop_reason TEXT DEFAULT '',
    last_exchange_attempt INTEGER DEFAULT 0,
    stall_valid_evals INTEGER DEFAULT 0,
    infra_fail_streak INTEGER DEFAULT 0,
    consecutive_failures INTEGER DEFAULT 0,
    shared_initial_evaluation_id TEXT,
    created_at TEXT,
    updated_at TEXT,
    PRIMARY KEY (experiment_id, island_id)
);

CREATE TABLE IF NOT EXISTS exchange_summary (
    summary_id TEXT PRIMARY KEY,
    experiment_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    source_island_id TEXT NOT NULL,
    source_node_id TEXT DEFAULT '',
    task_fingerprint TEXT DEFAULT '',
    evaluator_fingerprint TEXT DEFAULT '',
    summary_text TEXT DEFAULT '',
    conditions TEXT DEFAULT '',
    evidence_json TEXT DEFAULT '[]',
    metrics_json TEXT DEFAULT '{}',
    confidence_status TEXT DEFAULT 'single_observation',
    content_hash TEXT NOT NULL DEFAULT '',
    created_at TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_summary_content
    ON exchange_summary(experiment_id, kind, content_hash);

CREATE TABLE IF NOT EXISTS exchange_delivery (
    delivery_id TEXT PRIMARY KEY,
    experiment_id TEXT NOT NULL,
    summary_id TEXT NOT NULL,
    source_island_id TEXT NOT NULL,
    target_island_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'offered',
    reason TEXT DEFAULT '',
    created_at TEXT,
    updated_at TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_delivery_unique
    ON exchange_delivery(summary_id, target_island_id);

CREATE TABLE IF NOT EXISTS summary_application (
    application_id TEXT PRIMARY KEY,
    delivery_id TEXT NOT NULL,
    experiment_id TEXT NOT NULL,
    candidate_node_id TEXT NOT NULL,
    evaluation_id TEXT DEFAULT '',
    score REAL,
    created_at TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_application_unique
    ON summary_application(delivery_id, candidate_node_id);

CREATE TABLE IF NOT EXISTS scheduler_state (
    experiment_id TEXT PRIMARY KEY,
    next_island_index INTEGER DEFAULT 0,
    rng_state_json TEXT DEFAULT '',
    schema_version INTEGER DEFAULT 2,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS run_identity (
    experiment_id TEXT PRIMARY KEY,
    identity_json TEXT NOT NULL DEFAULT '',
    created_at TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS run_claim (
    experiment_id TEXT PRIMARY KEY,
    holder_id TEXT NOT NULL DEFAULT '',
    holder_pid INTEGER,
    claimed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_node_experiment_island ON node(experiment_id, island_id);
CREATE INDEX IF NOT EXISTS idx_llm_call_island ON llm_call(experiment_id, island_id);

CREATE INDEX IF NOT EXISTS idx_cost_ledger_island ON cost_ledger(experiment_id, island_id);
"""

# Bump when the island schema changes. Databases below this version are
# migrated in place; version 0 means a pre-island (legacy single-tree) store.
SCHEMA_VERSION = 2


def now_iso() -> str:
    """Get current UTC time in ISO format."""
    return datetime.now(timezone.utc).isoformat()


#: Columns the ``llm_call`` table gained after its first draft. A historical run
#: can legitimately lack them, so both the reader and the rollup treat a missing
#: column as "not recorded" rather than as a zero.
_LLM_CALL_ADDED_COLUMNS = {
    "request_id": "TEXT NOT NULL DEFAULT ''",
    "transport_attempts": "INTEGER NOT NULL DEFAULT 1",
    "island_attempt": "INTEGER",
    "stage": "TEXT NOT NULL DEFAULT ''",
    "outcome": "TEXT NOT NULL DEFAULT 'ok'",
    "cost_usd": "REAL",
    "cost_basis": "TEXT NOT NULL DEFAULT 'unknown'",
}

def _llm_call_from_row(row: sqlite3.Row) -> LLMCall:
    """Read one cost row. A database written before the identity columns existed
    reports them as "not recorded", not as a zero a reader must second-guess."""
    data = dict(row)
    return LLMCall(
        id=data["id"],
        experiment_id=data["experiment_id"],
        island_id=data.get("island_id") or "",
        node_id=data["node_id"],
        purpose=data["purpose"],
        model=data["model"],
        prompt_tokens=data["prompt_tokens"],
        completion_tokens=data["completion_tokens"],
        latency_ms=data["latency_ms"],
        cached=bool(data["cached"]),
        created_at=data["created_at"],
        request_id=data.get("request_id") or "",
        transport_attempts=int(data.get("transport_attempts") or 1),
        island_attempt=data.get("island_attempt"),
        stage=data.get("stage") or "",
        outcome=data.get("outcome") or "ok",
        cost_usd=data.get("cost_usd"),
        cost_basis=data.get("cost_basis") or "unknown",
    )


def _empty_cost_bucket(island_id: str) -> dict[str, Any]:
    """One island's spend, zeroed -- so a run reports an empty island as empty."""
    return {
        "island_id": island_id,
        "calls": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "tokens": 0,
        "unresolved_calls": 0,
        "retried_calls": 0,
        # A cache hit re-uses the original call's token counts, so a reader has to
        # be able to see how much of a bucket was re-served rather than bought.
        "cached_calls": 0,
        "cost_usd": None,
        "by_stage": {},
    }


class Store:
    """SQLite-based store for FaultEvolve data."""

    def __init__(self, db_path: Path, read_only: bool = False) -> None:
        """Initialize the store.

        Args:
            db_path: Path to the SQLite database file
            read_only: Open a historical database without creating, migrating or
                writing anything. A resumed run must never mutate the original
                artifacts, so readers of old runs pass this flag.
        """
        self.db_path = db_path
        self.read_only = read_only
        if read_only:
            if not db_path.exists():
                raise FileNotFoundError(f"read-only store needs an existing file: {db_path}")
            return
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        """Initialize the database schema, migrating legacy stores in place."""
        with self._conn() as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version < SCHEMA_VERSION:
                # Add island_id before the shared DDL: indexes on node(island_id)
                # would otherwise fail on a legacy database.
                self._migrate_to_v2(conn)
            # Columns gained after a table's first draft go on before the DDL too,
            # for the same reason: an in-progress run's database already has the
            # table, and DDL indexes reference those columns.
            self._ensure_island_columns(conn)
            conn.executescript(DDL)
            conn.execute("PRAGMA journal_mode=WAL")
            if version < SCHEMA_VERSION:
                conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")

    #: Columns added to the island tables after their first draft, kept here so
    #: an in-progress development database is brought forward instead of
    #: needing a fresh run directory.
    _ISLAND_ADDED_COLUMNS = {
        "island_state": {"consecutive_failures": "INTEGER DEFAULT 0"},
        "llm_call": dict(_LLM_CALL_ADDED_COLUMNS),
        "cost_ledger": {"island_id": "TEXT NOT NULL DEFAULT ''"},
    }

    @classmethod
    def _ensure_island_columns(cls, conn: sqlite3.Connection) -> None:
        for table, added in cls._ISLAND_ADDED_COLUMNS.items():
            if not cls._table_exists(conn, table):
                continue
            cols = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
            for name, ddl in added.items():
                if name not in cols:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")

    @staticmethod
    def _migrate_to_v2(conn: sqlite3.Connection) -> None:
        """Bring a pre-island database up to the current schema."""
        has_node = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'node'"
        ).fetchone()
        if not has_node:
            return  # fresh database: the DDL creates everything current
        for table in ("node", "insight", "llm_call"):
            has = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
            ).fetchone()
            if not has:
                continue
            cols = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
            if "island_id" not in cols:
                conn.execute(
                    f"ALTER TABLE {table} ADD COLUMN island_id TEXT NOT NULL DEFAULT ''"
                )
        Store._rebuild_operator_stats_key(conn)

    @staticmethod
    def _rebuild_operator_stats_key(conn: sqlite3.Connection) -> None:
        """Move operator_stats onto a (experiment, island, operator) primary key.

        The bandit posterior is per island: island A learning that ``inject``
        pays off must not bias island C's operator choice. A pre-island table
        cannot gain that column in its key, so it is rebuilt with every legacy
        row landing in the implicit single island (empty string).
        """
        cols = {
            row["name"] for row in conn.execute("PRAGMA table_info(operator_stats)")
        }
        if not cols:
            return
        if "island_id" not in cols:
            conn.execute(
                "ALTER TABLE operator_stats ADD COLUMN island_id TEXT NOT NULL DEFAULT ''"
            )
        pk_cols = [
            str(row["name"])
            for row in conn.execute("PRAGMA table_info(operator_stats)")
            if row["pk"]
        ]
        if pk_cols == ["experiment_id", "island_id", "operator"]:
            return
        conn.executescript(
            """
            CREATE TABLE operator_stats_v2 (
                experiment_id TEXT,
                island_id TEXT NOT NULL DEFAULT '',
                operator TEXT,
                alpha REAL,
                beta REAL,
                n INTEGER DEFAULT 0,
                n_valid INTEGER DEFAULT 0,
                sum_delta REAL DEFAULT 0.0,
                PRIMARY KEY (experiment_id, island_id, operator)
            );
            INSERT OR IGNORE INTO operator_stats_v2 (
                experiment_id, island_id, operator, alpha, beta, n, n_valid, sum_delta
            )
            SELECT experiment_id, island_id, operator, alpha, beta, n, n_valid, sum_delta
            FROM operator_stats;
            DROP TABLE operator_stats;
            ALTER TABLE operator_stats_v2 RENAME TO operator_stats;
            """
        )

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        """Context manager for database connections."""
        if self.read_only:
            uri = self.db_path.resolve().as_uri() + "?mode=ro"
            conn = sqlite3.connect(uri, uri=True, timeout=30.0)
        else:
            conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
        """True when a table carries a column; old databases may not."""
        if not Store._table_exists(conn, table):
            return False
        return column in {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}

    @staticmethod
    def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
        """False on a pre-island database read without migration."""
        return conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
        ).fetchone() is not None

    def create_experiment(self, experiment: Experiment) -> None:
        """Create a new experiment."""
        now = now_iso()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO experiment (id, name, status, config_json, problem_md, prompt_md,
                                        best_node_id, best_score, iterations_done, total_tokens,
                                        created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    experiment.id,
                    experiment.name,
                    experiment.status,
                    experiment.config.model_dump_json(),
                    experiment.problem_md,
                    experiment.prompt_md,
                    experiment.best_node_id,
                    experiment.best_score,
                    experiment.iterations_done,
                    experiment.total_tokens,
                    now,
                    now,
                ),
            )

    def get_experiment(self, experiment_id: str) -> Experiment | None:
        """Get an experiment by ID."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM experiment WHERE id = ?", (experiment_id,)
            ).fetchone()

        if row is None:
            return None

        config_data = json.loads(row["config_json"]) if row["config_json"] else {}
        return Experiment(
            id=row["id"],
            name=row["name"] or "",
            status=row["status"] or "created",
            config=ExperimentConfig(**config_data),
            problem_md=row["problem_md"] or "",
            prompt_md=row["prompt_md"] or "",
            best_node_id=row["best_node_id"],
            best_score=row["best_score"] or 0.0,
            iterations_done=row["iterations_done"] or 0,
            total_tokens=row["total_tokens"] or 0,
            created_at=row["created_at"] or "",
            updated_at=row["updated_at"] or "",
        )

    def update_experiment(
        self,
        experiment_id: str,
        status: str | None = None,
        best_node_id: str | None = None,
        best_score: float | None = None,
        iterations_done: int | None = None,
        total_tokens: int | None = None,
    ) -> None:
        """Update experiment fields."""
        updates = []
        params: list[Any] = []

        if status is not None:
            updates.append("status = ?")
            params.append(status)
        if best_node_id is not None:
            updates.append("best_node_id = ?")
            params.append(best_node_id)
        if best_score is not None:
            updates.append("best_score = ?")
            params.append(best_score)
        if iterations_done is not None:
            updates.append("iterations_done = ?")
            params.append(iterations_done)
        if total_tokens is not None:
            updates.append("total_tokens = ?")
            params.append(total_tokens)

        if not updates:
            return

        updates.append("updated_at = ?")
        params.append(now_iso())
        params.append(experiment_id)

        sql = f"UPDATE experiment SET {', '.join(updates)} WHERE id = ?"
        with self._conn() as conn:
            conn.execute(sql, params)

    def create_node(self, node: Node) -> None:
        """Create a new node."""
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO node (id, experiment_id, island_id, parent_id, branch_id, depth, operator,
                                  artifact_json, evidence_json, status, hypothesis_status,
                                  visit_count, expand_count, children_json, insight_ids_json,
                                  card_ids_json, branch_memory_json, repair_attempted,
                                  hypothesis_fail_count, repair_count, repair_parent_id,
                                  error_class, repair_exhausted, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    node.id,
                    node.experiment_id,
                    node.island_id,
                    node.parent_id,
                    node.branch_id,
                    node.depth,
                    node.operator.value,
                    node.artifact.model_dump_json(),
                    node.evidence.model_dump_json(),
                    node.status.value,
                    node.hypothesis_status.value,
                    node.visit_count,
                    node.expand_count,
                    json.dumps(node.children),
                    json.dumps(node.insight_ids),
                    json.dumps(node.card_ids),
                    node.branch_memory.model_dump_json(),
                    1 if node.repair_attempted else 0,
                    node.hypothesis_fail_count,
                    node.repair_count,
                    node.repair_parent_id,
                    node.error_class,
                    1 if node.repair_exhausted else 0,
                    node.created_at or now_iso(),
                ),
            )

    def get_node(self, node_id: str) -> Node | None:
        """Get a node by ID."""
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM node WHERE id = ?", (node_id,)).fetchone()

        if row is None:
            return None

        return self._row_to_node(row)

    def _row_to_node(self, row: sqlite3.Row) -> Node:
        """Convert a database row to a Node object."""
        from faultevolve.common.schemas import (
            BranchMemory,
            HypothesisStatus,
            NodeArtifact,
            NodeEvidence,
            NodeStatus,
            OperatorType,
        )

        artifact_data = json.loads(row["artifact_json"]) if row["artifact_json"] else {}
        evidence_data = json.loads(row["evidence_json"]) if row["evidence_json"] else {}
        branch_memory_data = json.loads(row["branch_memory_json"]) if row["branch_memory_json"] else {}

        row_dict = dict(row)

        return Node(
            id=row["id"],
            experiment_id=row["experiment_id"],
            island_id=row_dict.get("island_id") or "",
            parent_id=row["parent_id"],
            branch_id=row["branch_id"],
            depth=row["depth"] or 0,
            operator=OperatorType(row["operator"]),
            artifact=NodeArtifact(**artifact_data),
            evidence=NodeEvidence(**evidence_data),
            status=NodeStatus(row["status"]),
            hypothesis_status=HypothesisStatus(row["hypothesis_status"]),
            visit_count=row["visit_count"] or 0,
            expand_count=row["expand_count"] or 0,
            children=json.loads(row["children_json"]) if row["children_json"] else [],
            insight_ids=json.loads(row["insight_ids_json"]) if row["insight_ids_json"] else [],
            card_ids=json.loads(row["card_ids_json"]) if row["card_ids_json"] else [],
            branch_memory=BranchMemory(**branch_memory_data),
            repair_attempted=bool(row["repair_attempted"]),
            hypothesis_fail_count=row["hypothesis_fail_count"] or 0,
            repair_count=row_dict.get("repair_count") or 0,
            repair_parent_id=row_dict.get("repair_parent_id"),
            error_class=row_dict.get("error_class") or "",
            repair_exhausted=bool(row_dict.get("repair_exhausted", 0)),
            created_at=row["created_at"] or "",
        )

    def update_node(
        self,
        node_id: str,
        evidence_json: str | None = None,
        status: str | None = None,
        hypothesis_status: str | None = None,
        visit_count: int | None = None,
        expand_count: int | None = None,
        children: list[str] | None = None,
        insight_ids: list[str] | None = None,
        branch_memory_json: str | None = None,
        repair_attempted: bool | None = None,
        hypothesis_fail_count: int | None = None,
        repair_count: int | None = None,
        error_class: str | None = None,
        repair_exhausted: bool | None = None,
        artifact_json: str | None = None,
    ) -> None:
        """Update node fields."""
        updates = []
        params: list[Any] = []

        if artifact_json is not None:
            updates.append("artifact_json = ?")
            params.append(artifact_json)
        if evidence_json is not None:
            updates.append("evidence_json = ?")
            params.append(evidence_json)
        if status is not None:
            updates.append("status = ?")
            params.append(status)
        if hypothesis_status is not None:
            updates.append("hypothesis_status = ?")
            params.append(hypothesis_status)
        if visit_count is not None:
            updates.append("visit_count = ?")
            params.append(visit_count)
        if expand_count is not None:
            updates.append("expand_count = ?")
            params.append(expand_count)
        if children is not None:
            updates.append("children_json = ?")
            params.append(json.dumps(children))
        if insight_ids is not None:
            updates.append("insight_ids_json = ?")
            params.append(json.dumps(insight_ids))
        if branch_memory_json is not None:
            updates.append("branch_memory_json = ?")
            params.append(branch_memory_json)
        if repair_attempted is not None:
            updates.append("repair_attempted = ?")
            params.append(1 if repair_attempted else 0)
        if hypothesis_fail_count is not None:
            updates.append("hypothesis_fail_count = ?")
            params.append(hypothesis_fail_count)
        if repair_count is not None:
            updates.append("repair_count = ?")
            params.append(repair_count)
        if error_class is not None:
            updates.append("error_class = ?")
            params.append(error_class)
        if repair_exhausted is not None:
            updates.append("repair_exhausted = ?")
            params.append(1 if repair_exhausted else 0)

        if not updates:
            return

        params.append(node_id)
        sql = f"UPDATE node SET {', '.join(updates)} WHERE id = ?"
        with self._conn() as conn:
            conn.execute(sql, params)

    def get_nodes_by_experiment(self, experiment_id: str, island_id: str | None = None) -> list[Node]:
        """Get nodes for an experiment, optionally filtered to one island."""
        with self._conn() as conn:
            if island_id is not None and not self._has_column(conn, "node", "island_id"):
                island_id = None
            if island_id is None:
                rows = conn.execute(
                    "SELECT * FROM node WHERE experiment_id = ? ORDER BY created_at",
                    (experiment_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM node WHERE experiment_id = ? AND island_id = ? ORDER BY created_at",
                    (experiment_id, island_id),
                ).fetchall()

        return [self._row_to_node(row) for row in rows]

    def create_insight(self, insight: Insight, experiment_id: str) -> None:
        """Create a new insight."""
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO insight (id, experiment_id, origin_node, branch_id, island_id,
                                     polarity, payload_json, delta, z_score, alpha, beta, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    insight.id,
                    experiment_id,
                    insight.origin_node,
                    insight.branch_id,
                    insight.island_id,
                    insight.polarity,
                    json.dumps({
                        "change_summary": insight.change_summary,
                        "mechanism": insight.mechanism,
                        "conditions": insight.conditions,
                        "tags": insight.tags,
                    }),
                    insight.delta,
                    insight.z_score,
                    insight.alpha,
                    insight.beta,
                    insight.created_at or now_iso(),
                ),
            )

    def get_insights_by_experiment(
        self,
        experiment_id: str,
        island_id: str | None = None,
    ) -> list[Insight]:
        """Get insights for an experiment, optionally filtered to one island.

        ``island_id`` is an island-scoped read: callers that build a generation
        context must pass it, because only exchange summaries may cross islands.
        """
        with self._conn() as conn:
            if island_id is not None and not self._has_column(conn, "insight", "island_id"):
                # A read-only pre-island database has no island column: every
                # row belongs to the implicit single island, so the filter is
                # satisfied by reading all of them.
                island_id = None
            if island_id is None:
                rows = conn.execute(
                    "SELECT * FROM insight WHERE experiment_id = ? ORDER BY created_at",
                    (experiment_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM insight WHERE experiment_id = ? AND island_id = ?"
                    " ORDER BY created_at",
                    (experiment_id, island_id),
                ).fetchall()

        insights = []
        for row in rows:
            row_dict = dict(row)
            payload = json.loads(row["payload_json"]) if row["payload_json"] else {}
            insights.append(Insight(
                id=row["id"],
                origin_node=row["origin_node"],
                branch_id=row["branch_id"],
                island_id=row_dict.get("island_id") or "",
                polarity=row["polarity"],
                change_summary=payload.get("change_summary", ""),
                mechanism=payload.get("mechanism", ""),
                conditions=payload.get("conditions", ""),
                tags=payload.get("tags", []),
                delta=row["delta"],
                z_score=row["z_score"],
                alpha=row["alpha"],
                beta=row["beta"],
                created_at=row["created_at"] or "",
            ))
        return insights

    def create_llm_call(self, llm_call: LLMCall) -> None:
        """Record an LLM call."""
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO llm_call (id, experiment_id, island_id, node_id, purpose, model,
                                      prompt_tokens, completion_tokens, latency_ms,
                                      cached, created_at, request_id, transport_attempts,
                                      island_attempt, stage, outcome, cost_usd, cost_basis)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    llm_call.id,
                    llm_call.experiment_id,
                    llm_call.island_id,
                    llm_call.node_id,
                    llm_call.purpose,
                    llm_call.model,
                    llm_call.prompt_tokens,
                    llm_call.completion_tokens,
                    llm_call.latency_ms,
                    1 if llm_call.cached else 0,
                    llm_call.created_at or now_iso(),
                    llm_call.request_id,
                    llm_call.transport_attempts,
                    llm_call.island_attempt,
                    llm_call.stage,
                    llm_call.outcome,
                    llm_call.cost_usd,
                    llm_call.cost_basis,
                ),
            )

    def get_cost_rollup(self, experiment_id: str) -> dict[str, Any]:
        """Per-island spend, plus the shared spend, straight from ``llm_call``.

        The requirement this answers is arithmetic, not presentational: the run
        total has to equal every island's own cost plus the shared cost, and a
        cost must not appear under two islands. ``island_id = ''`` is the shared
        bucket -- a call made while no island was active -- and it is reported
        separately instead of being quietly added to whichever island asked last.
        Money is never estimated: ``cost_usd`` is summed only where a row already
        carries it, and ``cost_basis`` says whether anything known was present.
        """
        with self._conn() as conn:
            if not self._table_exists(conn, "llm_call"):
                return {"total_tokens": 0, "by_island": [],
                        "shared": _empty_cost_bucket(""), "cost_basis": "unknown",
                        "unresolved_calls": 0, "cost_usd": None}
            # ``SELECT *`` on purpose: a historical run written before these
            # columns existed is read through this same path, and its rows simply
            # have no stage/outcome keys to read out of.
            rows = conn.execute(
                "SELECT * FROM llm_call WHERE experiment_id = ?",
                (experiment_id,),
            ).fetchall()

        buckets: dict[str, dict[str, Any]] = {}
        money_known = False
        for raw in rows:
            row = dict(raw)
            island_id = row.get("island_id") or ""
            bucket = buckets.setdefault(island_id, _empty_cost_bucket(island_id))
            prompt = int(row.get("prompt_tokens") or 0)
            completion = int(row.get("completion_tokens") or 0)
            bucket["calls"] += 1
            bucket["prompt_tokens"] += prompt
            bucket["completion_tokens"] += completion
            bucket["tokens"] += prompt + completion
            if (row.get("outcome") or "ok") != "ok":
                # A request that went out and never came back spent something, but
                # the client could not say how much: it counts as unresolved, not
                # as free.
                bucket["unresolved_calls"] += 1
            if int(row.get("transport_attempts") or 1) > 1:
                bucket["retried_calls"] += 1
            if row.get("cached"):
                # A cache hit re-serves the original call's token counts without
                # sending anything, so it is counted apart from fresh spend.
                bucket["cached_calls"] += 1
            if row.get("cost_usd") is not None:
                bucket["cost_usd"] = round((bucket["cost_usd"] or 0.0) + float(row["cost_usd"]), 6)
                money_known = True
            stage = row.get("stage") or "other"
            bucket["by_stage"][stage] = bucket["by_stage"].get(stage, 0) + prompt + completion

        shared = buckets.pop("", _empty_cost_bucket(""))
        by_island = [buckets[key] for key in sorted(buckets)]
        total = sum(bucket["tokens"] for bucket in buckets.values()) + shared["tokens"]
        return {
            "total_tokens": total,
            "shared": shared,
            "by_island": by_island,
            "unresolved_calls": sum(b["unresolved_calls"] for b in buckets.values())
            + shared["unresolved_calls"],
            "cost_usd": (
                round(sum(b["cost_usd"] or 0.0 for b in list(buckets.values()) + [shared]), 6)
                if money_known
                else None
            ),
            "cost_basis": "recorded" if money_known else "unknown",
        }

    def max_cost_seq(self, experiment_id: str) -> int:
        """Highest ``seq`` already stored, so a resumed ledger keeps counting.

        ``cost_ledger`` is keyed by ``(experiment_id, seq)`` and the in-memory
        ledger starts at zero, so a resume that rebuilds the ledger without this
        would collide with its own history on the first record.
        """
        with self._conn() as conn:
            if not self._table_exists(conn, "cost_ledger"):
                return 0
            row = conn.execute(
                "SELECT MAX(seq) FROM cost_ledger WHERE experiment_id = ?",
                (experiment_id,),
            ).fetchone()
        return int(row[0]) if row and row[0] is not None else 0

    def create_event(self, event: Event) -> None:
        """Create an event."""
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO event (experiment_id, type, payload_json, ts)
                VALUES (?, ?, ?, ?)
                """,
                (
                    event.experiment_id,
                    event.type,
                    json.dumps(event.payload),
                    event.ts or now_iso(),
                ),
            )

    def get_llm_calls(self, experiment_id: str, island_id: str | None = None) -> list[LLMCall]:
        """Get LLM calls for an experiment, optionally filtered to one island."""
        with self._conn() as conn:
            if island_id is not None and not self._has_column(conn, "llm_call", "island_id"):
                island_id = None
            if island_id is None:
                rows = conn.execute(
                    "SELECT * FROM llm_call WHERE experiment_id = ? ORDER BY created_at",
                    (experiment_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM llm_call WHERE experiment_id = ? AND island_id = ?"
                    " ORDER BY created_at",
                    (experiment_id, island_id),
                ).fetchall()

        return [_llm_call_from_row(row) for row in rows]

    def get_events(self, experiment_id: str) -> list[Event]:
        """Get all events for an experiment."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM event WHERE experiment_id = ? ORDER BY ts",
                (experiment_id,),
            ).fetchall()

        return [
            Event(
                id=row["id"],
                experiment_id=row["experiment_id"],
                type=row["type"],
                payload=json.loads(row["payload_json"]) if row["payload_json"] else {},
                ts=row["ts"],
            )
            for row in rows
        ]

    def get_card_stats(self, experiment_id: str) -> dict[str, dict[str, Any]]:
        """Get card statistics for an experiment.

        Returns:
            Dictionary mapping card_id to stats dict
        """
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM card_stats WHERE experiment_id = ?",
                (experiment_id,),
            ).fetchall()

        return {
            row["card_id"]: {
                "n": row["n"] or 0,
                "sum_delta": row["sum_delta"] or 0.0,
                "sum_sq": row["sum_sq"] or 0.0,
                "refuted_count": row["refuted_count"] or 0,
                "invalid_count": row["invalid_count"] if "invalid_count" in row.keys() else 0,
            }
            for row in rows
        }

    def update_card_stats(
        self,
        experiment_id: str,
        card_id: str,
        delta: float,
    ) -> None:
        """Update card statistics after adoption.

        Args:
            experiment_id: Experiment ID
            card_id: Card ID
            delta: Score delta observed
        """
        with self._conn() as conn:
            row = conn.execute(
                "SELECT n, sum_delta, sum_sq FROM card_stats WHERE experiment_id = ? AND card_id = ?",
                (experiment_id, card_id),
            ).fetchone()

            if row is None:
                conn.execute(
                    """
                    INSERT INTO card_stats (experiment_id, card_id, n, sum_delta, sum_sq, refuted_count)
                    VALUES (?, ?, 1, ?, ?, 0)
                    """,
                    (experiment_id, card_id, delta, delta * delta),
                )
            else:
                new_n = (row["n"] or 0) + 1
                new_sum = (row["sum_delta"] or 0.0) + delta
                new_sq = (row["sum_sq"] or 0.0) + delta * delta
                conn.execute(
                    """
                    UPDATE card_stats
                    SET n = ?, sum_delta = ?, sum_sq = ?
                    WHERE experiment_id = ? AND card_id = ?
                    """,
                    (new_n, new_sum, new_sq, experiment_id, card_id),
                )

    def increment_card_refuted_count(self, experiment_id: str, card_id: str) -> None:
        """Increment refuted count for a card.

        Args:
            experiment_id: Experiment ID
            card_id: Card ID
        """
        with self._conn() as conn:
            row = conn.execute(
                "SELECT refuted_count FROM card_stats WHERE experiment_id = ? AND card_id = ?",
                (experiment_id, card_id),
            ).fetchone()

            if row is None:
                conn.execute(
                    """
                    INSERT INTO card_stats (experiment_id, card_id, n, sum_delta, sum_sq, refuted_count)
                    VALUES (?, ?, 0, 0.0, 0.0, 1)
                    """,
                    (experiment_id, card_id),
                )
            else:
                new_count = (row["refuted_count"] or 0) + 1
                conn.execute(
                    """
                    UPDATE card_stats SET refuted_count = ?
                    WHERE experiment_id = ? AND card_id = ?
                    """,
                    (new_count, experiment_id, card_id),
                )

    def update_card_stats_invalid(
        self,
        experiment_id: str,
        card_id: str,
        penalty_delta: float,
    ) -> None:
        """Update card statistics when adoption resulted in invalid code.

        Args:
            experiment_id: Experiment ID
            card_id: Card ID
            penalty_delta: Negative penalty delta (e.g., -2 * noise_delta)
        """
        with self._conn() as conn:
            row = conn.execute(
                "SELECT n, sum_delta, sum_sq, invalid_count FROM card_stats WHERE experiment_id = ? AND card_id = ?",
                (experiment_id, card_id),
            ).fetchone()

            if row is None:
                conn.execute(
                    """
                    INSERT INTO card_stats (experiment_id, card_id, n, sum_delta, sum_sq, refuted_count, invalid_count)
                    VALUES (?, ?, 1, ?, ?, 0, 1)
                    """,
                    (experiment_id, card_id, penalty_delta, penalty_delta * penalty_delta),
                )
            else:
                new_n = (row["n"] or 0) + 1
                new_sum = (row["sum_delta"] or 0.0) + penalty_delta
                new_sq = (row["sum_sq"] or 0.0) + penalty_delta * penalty_delta
                new_invalid = (row["invalid_count"] if "invalid_count" in row.keys() else 0) + 1
                conn.execute(
                    """
                    UPDATE card_stats
                    SET n = ?, sum_delta = ?, sum_sq = ?, invalid_count = ?
                    WHERE experiment_id = ? AND card_id = ?
                    """,
                    (new_n, new_sum, new_sq, new_invalid, experiment_id, card_id),
                )

    def get_branch_invalid_adoption_count(
        self,
        experiment_id: str,
        branch_id: str,
        card_id: str,
    ) -> int:
        """Get count of invalid adoptions of a card on a branch.

        Args:
            experiment_id: Experiment ID
            branch_id: Branch ID
            card_id: Card ID

        Returns:
            Number of times this card was adopted and resulted in invalid code on this branch
        """
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) as cnt FROM branch_offered_cards
                WHERE experiment_id = ? AND branch_id = ? AND card_id = ? AND was_invalid = 1
                """,
                (experiment_id, branch_id, card_id),
            ).fetchone()
            return row["cnt"] if row else 0

    def record_offered_cards(
        self,
        experiment_id: str,
        branch_id: str,
        card_ids: list[str],
        iteration: int,
        was_invalid: bool = False,
    ) -> None:
        """Record which cards were offered in an iteration.

        Args:
            experiment_id: Experiment ID
            branch_id: Branch ID
            card_ids: List of offered card IDs
            iteration: Iteration number
            was_invalid: Whether the resulting code was invalid
        """
        if not card_ids:
            return
        now = now_iso()
        with self._conn() as conn:
            for card_id in card_ids:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO branch_offered_cards
                    (experiment_id, branch_id, card_id, iteration, was_invalid, offered_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (experiment_id, branch_id, card_id, iteration, 1 if was_invalid else 0, now),
                )

    def get_recently_offered_cards(
        self,
        experiment_id: str,
        branch_id: str,
        last_n_iterations: int = 3,
    ) -> dict[str, int]:
        """Get cards offered in recent iterations with their offer counts.

        Args:
            experiment_id: Experiment ID
            branch_id: Branch ID
            last_n_iterations: Number of recent iterations to consider

        Returns:
            Dict mapping card_id to number of times offered recently
        """
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT card_id, COUNT(*) as cnt FROM branch_offered_cards
                WHERE experiment_id = ? AND branch_id = ?
                  AND iteration > (SELECT COALESCE(MAX(iteration), 0) - ? FROM branch_offered_cards
                                   WHERE experiment_id = ? AND branch_id = ?)
                GROUP BY card_id
                """,
                (experiment_id, branch_id, last_n_iterations, experiment_id, branch_id),
            ).fetchall()
            return {row["card_id"]: row["cnt"] for row in rows}

    def get_recently_failed_card_sets(
        self,
        experiment_id: str,
        branch_id: str,
        last_n_iterations: int = 3,
    ) -> list[set[str]]:
        """Get card sets that resulted in invalid code in recent iterations.

        Args:
            experiment_id: Experiment ID
            branch_id: Branch ID
            last_n_iterations: Number of recent iterations to consider

        Returns:
            List of card ID sets that failed
        """
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT iteration, card_id FROM branch_offered_cards
                WHERE experiment_id = ? AND branch_id = ? AND was_invalid = 1
                  AND iteration > (SELECT COALESCE(MAX(iteration), 0) - ? FROM branch_offered_cards
                                   WHERE experiment_id = ? AND branch_id = ?)
                ORDER BY iteration
                """,
                (experiment_id, branch_id, last_n_iterations, experiment_id, branch_id),
            ).fetchall()

            by_iter: dict[int, set[str]] = {}
            for row in rows:
                it = row["iteration"]
                if it not in by_iter:
                    by_iter[it] = set()
                by_iter[it].add(row["card_id"])

            return list(by_iter.values())

    def add_branch_refuted_card(
        self,
        experiment_id: str,
        branch_id: str,
        card_id: str,
    ) -> None:
        """Mark a card as refuted on a branch.

        Args:
            experiment_id: Experiment ID
            branch_id: Branch ID
            card_id: Card ID
        """
        with self._conn() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO branch_refuted_cards
                (experiment_id, branch_id, card_id, refuted_at)
                VALUES (?, ?, ?, ?)
                """,
                (experiment_id, branch_id, card_id, now_iso()),
            )

    def get_branch_refuted_cards(self, experiment_id: str, branch_id: str) -> set[str]:
        """Get cards refuted on a branch.

        Args:
            experiment_id: Experiment ID
            branch_id: Branch ID

        Returns:
            Set of refuted card IDs
        """
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT card_id FROM branch_refuted_cards WHERE experiment_id = ? AND branch_id = ?",
                (experiment_id, branch_id),
            ).fetchall()

        return {row["card_id"] for row in rows}

    def add_node_adopted_cards(
        self,
        experiment_id: str,
        node_id: str,
        card_ids: list[str],
    ) -> None:
        """Record cards adopted by a node.

        Args:
            experiment_id: Experiment ID (unused but for future compatibility)
            node_id: Node ID
            card_ids: List of adopted card IDs
        """
        if not card_ids:
            return

        now = now_iso()
        with self._conn() as conn:
            for card_id in card_ids:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO node_adopted_cards (node_id, card_id, adopted_at)
                    VALUES (?, ?, ?)
                    """,
                    (node_id, card_id, now),
                )

    def get_node_adopted_cards(self, node_id: str) -> list[str]:
        """Get cards adopted by a node.

        Args:
            node_id: Node ID

        Returns:
            List of adopted card IDs
        """
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT card_id FROM node_adopted_cards WHERE node_id = ?",
                (node_id,),
            ).fetchall()

        return [row["card_id"] for row in rows]

    def get_ancestor_adopted_cards(self, node_id: str) -> set[str]:
        """Get all cards adopted by ancestors of a node.

        Args:
            node_id: Node ID

        Returns:
            Set of adopted card IDs from all ancestors
        """
        adopted: set[str] = set()
        current_id: str | None = node_id

        while current_id:
            adopted.update(self.get_node_adopted_cards(current_id))
            node = self.get_node(current_id)
            if node is None:
                break
            current_id = node.parent_id

        return adopted

    def get_all_card_stats(self, experiment_id: str) -> dict[str, Any]:
        """Get all card stats as CardStats-like objects.

        Args:
            experiment_id: Experiment ID

        Returns:
            Dictionary mapping card_id to CardStats-like objects
        """
        from faultevolve.knowledge.retriever import CardStats

        raw_stats = self.get_card_stats(experiment_id)
        result = {}
        for card_id, data in raw_stats.items():
            result[card_id] = CardStats(
                card_id=card_id,
                n=data["n"],
                sum_delta=data["sum_delta"],
                sum_sq=data["sum_sq"],
                refuted_count=data["refuted_count"],
                invalid_count=data.get("invalid_count", 0),
            )
        return result

    def record_operator_outcome(
        self,
        experiment_id: str,
        operator: str,
        island_id: str = "",
        *,
        valid: bool,
        success: bool,
        delta: float,
        prior_alpha: float = 1.0,
        prior_beta: float = 1.0,
    ) -> None:
        """Update Beta-Bernoulli bandit stats for an operator."""
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT alpha, beta, n, n_valid, sum_delta
                FROM operator_stats
                WHERE experiment_id = ? AND island_id = ? AND operator = ?
                """,
                (experiment_id, island_id, operator),
            ).fetchone()
            if row is None:
                alpha = prior_alpha + (1 if success else 0)
                beta = prior_beta + (0 if success else 1)
                n_valid = 1 if valid else 0
                sum_delta = delta if valid else 0.0
                conn.execute(
                    """
                    INSERT INTO operator_stats (
                        experiment_id, island_id, operator, alpha, beta, n, n_valid, sum_delta
                    ) VALUES (?, ?, ?, ?, ?, 1, ?, ?)
                    """,
                    (experiment_id, island_id, operator, alpha, beta, n_valid, sum_delta),
                )
                return

            alpha = float(row["alpha"]) + (1 if success else 0)
            beta = float(row["beta"]) + (0 if success else 1)
            n = int(row["n"]) + 1
            n_valid = int(row["n_valid"]) + (1 if valid else 0)
            sum_delta = float(row["sum_delta"]) + (delta if valid else 0.0)
            conn.execute(
                """
                UPDATE operator_stats
                SET alpha = ?, beta = ?, n = ?, n_valid = ?, sum_delta = ?
                WHERE experiment_id = ? AND island_id = ? AND operator = ?
                """,
                (alpha, beta, n, n_valid, sum_delta, experiment_id, island_id, operator),
            )

    def get_operator_stats(
        self,
        experiment_id: str,
        island_id: str | None = None,
    ) -> dict[str, dict[str, float]]:
        """Operator bandit stats keyed by operator name.

        ``island_id`` reads one island's posterior. Left open it merges every
        island into one row per operator, which is what run-level reporting
        wants; island selection must never use the merged view.
        """
        with self._conn() as conn:
            if island_id is None:
                rows = conn.execute(
                    """
                    SELECT operator, alpha, beta, n, n_valid, sum_delta
                    FROM operator_stats
                    WHERE experiment_id = ?
                    """,
                    (experiment_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT operator, alpha, beta, n, n_valid, sum_delta
                    FROM operator_stats
                    WHERE experiment_id = ? AND island_id = ?
                    """,
                    (experiment_id, island_id),
                ).fetchall()
        result: dict[str, dict[str, float]] = {}
        for row in rows:
            entry = result.setdefault(
                str(row["operator"]),
                {"alpha": 0.0, "beta": 0.0, "n": 0.0, "n_valid": 0.0, "sum_delta": 0.0},
            )
            entry["alpha"] += float(row["alpha"])
            entry["beta"] += float(row["beta"])
            entry["n"] += float(row["n"])
            entry["n_valid"] += float(row["n_valid"])
            entry["sum_delta"] += float(row["sum_delta"])
        return result

    def create_claim(self, experiment_id: str, claim: dict, round_idx: int) -> None:
        now = now_iso()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO claim (
                    id, experiment_id, origin_node_id, source, round,
                    payload_json, prereg_hash, status, grade, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    claim.get("id"),
                    experiment_id,
                    claim.get("origin_node_id", ""),
                    claim.get("source", ""),
                    round_idx,
                    json.dumps(claim, ensure_ascii=False),
                    claim.get("prereg_hash", ""),
                    claim.get("status", "proposed"),
                    claim.get("grade"),
                    now,
                ),
            )

    def update_claim(self, claim_id: str, **fields: Any) -> None:
        allowed = {"status", "grade", "payload_json"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return
        sets = ", ".join(f"{k} = ?" for k in updates)
        vals = list(updates.values()) + [claim_id]
        with self._conn() as conn:
            conn.execute(f"UPDATE claim SET {sets} WHERE id = ?", vals)

    def get_claims(self, experiment_id: str) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT payload_json FROM claim WHERE experiment_id = ? ORDER BY created_at",
                (experiment_id,),
            ).fetchall()
        out: list[dict] = []
        for row in rows:
            try:
                out.append(json.loads(row["payload_json"]))
            except json.JSONDecodeError:
                continue
        return out

    def max_claim_seq(self, experiment_id: str) -> int:
        """Largest numeric suffix on C-{experiment_id}-* ids (ignores payload parsing)."""
        prefix = f"C-{experiment_id}-"
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id FROM claim WHERE experiment_id = ?",
                (experiment_id,),
            ).fetchall()
        max_seq = 0
        for row in rows:
            cid = str(row["id"])
            if not cid.startswith(prefix):
                continue
            suffix = cid[len(prefix) :]
            try:
                max_seq = max(max_seq, int(suffix))
            except ValueError:
                continue
        return max_seq

    def create_claim_test(
        self,
        claim_id: str,
        experiment_id: str,
        split: str,
        payload: dict,
    ) -> None:
        now = now_iso()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO claim_test (claim_id, experiment_id, split, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (claim_id, experiment_id, split, json.dumps(payload), now),
            )

    def get_claim_tests(self, claim_id: str) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT payload_json FROM claim_test WHERE claim_id = ?",
                (claim_id,),
            ).fetchall()
        return [json.loads(r["payload_json"]) for r in rows]

    def record_discovered_card(
        self,
        card_id: str,
        claim_id: str,
        experiment_id: str,
        grade: str,
    ) -> None:
        now = now_iso()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO discovered_card (card_id, claim_id, experiment_id, grade, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (card_id, claim_id, experiment_id, grade, now),
            )

    def get_discovered_cards(self, experiment_id: str) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT card_id, claim_id, grade, created_at FROM discovered_card WHERE experiment_id = ?",
                (experiment_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def create_mechanism(self, experiment_id: str, m: dict, family_id: str) -> None:
        now = now_iso()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO mechanism (
                    id, experiment_id, claim_id, family_id, role, status,
                    patch_count, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    m.get("id"),
                    experiment_id,
                    m.get("claim_id", ""),
                    family_id,
                    m.get("role", ""),
                    m.get("status", "proposed"),
                    int(m.get("patch_count", 0)),
                    json.dumps(m, ensure_ascii=False),
                    now,
                ),
            )

    def update_mechanism(
        self,
        mech_id: str,
        status: str | None = None,
        patch_count: int | None = None,
    ) -> None:
        updates: list[str] = []
        params: list[Any] = []
        if status is not None:
            updates.append("status = ?")
            params.append(status)
        if patch_count is not None:
            updates.append("patch_count = ?")
            params.append(patch_count)
        if not updates:
            return
        params.append(mech_id)
        with self._conn() as conn:
            conn.execute(f"UPDATE mechanism SET {', '.join(updates)} WHERE id = ?", params)

    def get_mechanisms(
        self,
        experiment_id: str,
        status: str | None = None,
    ) -> list[dict]:
        sql = "SELECT * FROM mechanism WHERE experiment_id = ?"
        args: list[Any] = [experiment_id]
        if status:
            sql += " AND status = ?"
            args.append(status)
        with self._conn() as conn:
            rows = conn.execute(sql, args).fetchall()
        out: list[dict] = []
        for row in rows:
            try:
                payload = json.loads(row["payload_json"]) if row["payload_json"] else {}
            except json.JSONDecodeError:
                payload = {}
            payload["family_id"] = row["family_id"]
            payload["status"] = row["status"]
            out.append(payload)
        return out

    def create_match(
        self,
        experiment_id: str,
        family_id: str,
        round_idx: int,
        mech_a: str,
        mech_b: str,
        slice_id: str,
        payload: dict,
    ) -> int:
        now = now_iso()
        with self._conn() as conn:
            cur = conn.execute(
                """
                INSERT INTO match (
                    experiment_id, family_id, round, mech_a, mech_b, slice_id, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    experiment_id,
                    family_id,
                    round_idx,
                    mech_a,
                    mech_b,
                    slice_id,
                    json.dumps(payload),
                    now,
                ),
            )
            return int(cur.lastrowid)

    def create_test_result(
        self,
        match_id: int,
        experiment_id: str,
        test_type: str,
        payload: dict,
    ) -> None:
        now = now_iso()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO test_result (match_id, experiment_id, test_type, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (match_id, experiment_id, test_type, json.dumps(payload), now),
            )

    def get_matches(self, experiment_id: str) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT payload_json FROM match WHERE experiment_id = ?",
                (experiment_id,),
            ).fetchall()
        return [json.loads(r["payload_json"]) for r in rows]

    def create_certificate(
        self,
        experiment_id: str,
        mechanism_id: str,
        rival_id: str,
        payload: dict,
    ) -> None:
        now = now_iso()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO certificate (experiment_id, mechanism_id, rival_id, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (experiment_id, mechanism_id, rival_id, json.dumps(payload), now),
            )

    def get_certificates(self, experiment_id: str) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT payload_json FROM certificate WHERE experiment_id = ?",
                (experiment_id,),
            ).fetchall()
        return [json.loads(r["payload_json"]) for r in rows]

    def update_insight_beta(
        self,
        insight_id: str,
        experiment_id: str,
        d_alpha: float,
        d_beta: float,
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                UPDATE insight SET alpha = alpha + ?, beta = beta + ?
                WHERE id = ? AND experiment_id = ?
                """,
                (d_alpha, d_beta, insight_id, experiment_id),
            )

    def add_node_parent(
        self,
        experiment_id: str,
        node_id: str,
        parent_id: str,
        role: str,
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO node_parents (experiment_id, node_id, parent_id, role)
                VALUES (?, ?, ?, ?)
                """,
                (experiment_id, node_id, parent_id, role),
            )

    def get_node_parents(self, node_id: str) -> list[tuple[str, str]]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT parent_id, role FROM node_parents
                WHERE node_id = ?
                ORDER BY role ASC
                """,
                (node_id,),
            ).fetchall()
        return [(str(r["parent_id"]), str(r["role"])) for r in rows]

    def append_cost_record(self, experiment_id: str, rec: Any) -> None:
        from faultevolve.optimization.ledger import CostRecord

        if not isinstance(rec, CostRecord):
            raise TypeError("rec must be CostRecord")
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO cost_ledger (
                    experiment_id, seq, island_id, stage, fidelity, node_id,
                    prompt_tokens, completion_tokens, model_fit_count, evaluator_calls,
                    cpu_seconds, rss_peak_mb, wall_s, cache_hit, status,
                    reservation_id, meta_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    experiment_id,
                    rec.seq,
                    rec.island_id,
                    rec.stage,
                    rec.fidelity,
                    rec.node_id,
                    rec.prompt_tokens,
                    rec.completion_tokens,
                    rec.model_fit_count,
                    rec.evaluator_calls,
                    rec.cpu_seconds,
                    rec.rss_peak_mb,
                    rec.wall_s,
                    int(rec.cache_hit),
                    rec.status,
                    rec.reservation_id,
                    json.dumps(rec.meta, ensure_ascii=False),
                    now_iso(),
                ),
            )

    def list_cost_records(self, experiment_id: str) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM cost_ledger WHERE experiment_id = ? ORDER BY seq",
                (experiment_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def upsert_eval_cache(self, key: str, fidelity: str, result_json: str) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO eval_cache (key, fidelity, result_json, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (key, fidelity, result_json, now_iso()),
            )

    def get_eval_cache(self, key: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT result_json, fidelity FROM eval_cache WHERE key = ?",
                (key,),
            ).fetchone()
        if not row:
            return None
        return {"fidelity": row["fidelity"], "result": json.loads(row["result_json"])}

    def save_hpo_trial(self, experiment_id: str, trial: dict[str, Any]) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO hpo_trial (
                    trial_id, experiment_id, structure_id, trial_index, config_hash,
                    params_json, seed, fidelity, status, fit_count, dev_proxy,
                    dev_metrics_json, cache_hit, failure_reason, promoted_node_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    trial["trial_id"],
                    experiment_id,
                    trial["structure_id"],
                    trial["trial_index"],
                    trial["config_hash"],
                    trial["params_json"],
                    trial["seed"],
                    trial["fidelity"],
                    trial["status"],
                    trial.get("fit_count", 0),
                    trial.get("dev_proxy"),
                    json.dumps(trial.get("dev_metrics")),
                    int(trial.get("cache_hit", 0)),
                    trial.get("failure_reason", ""),
                    trial.get("promoted_node_id"),
                    now_iso(),
                ),
            )

    def add_explore_archive(
        self,
        experiment_id: str,
        node_id: str,
        reason: str,
        parent_score: float,
        score: float,
        module: str | None,
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO explore_archive (
                    experiment_id, node_id, reason, parent_score, score, module, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (experiment_id, node_id, reason, parent_score, score, module, now_iso()),
            )

    # ------------------------------------------------------------------
    # Island state, exchange summaries, deliveries and applications
    # ------------------------------------------------------------------

    def upsert_island_state(self, state: IslandState) -> None:
        """Insert or replace the persisted state of one island."""
        now = now_iso()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO island_state (
                    experiment_id, island_id, profile, root_id, best_node_id, best_score,
                    attempts, valid_evaluations, invalid_evaluations, status, stop_reason,
                    last_exchange_attempt, stall_valid_evals, infra_fail_streak,
                    consecutive_failures, shared_initial_evaluation_id,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(experiment_id, island_id) DO UPDATE SET
                    profile = excluded.profile,
                    root_id = excluded.root_id,
                    best_node_id = excluded.best_node_id,
                    best_score = excluded.best_score,
                    attempts = excluded.attempts,
                    valid_evaluations = excluded.valid_evaluations,
                    invalid_evaluations = excluded.invalid_evaluations,
                    status = excluded.status,
                    stop_reason = excluded.stop_reason,
                    last_exchange_attempt = excluded.last_exchange_attempt,
                    stall_valid_evals = excluded.stall_valid_evals,
                    infra_fail_streak = excluded.infra_fail_streak,
                    consecutive_failures = excluded.consecutive_failures,
                    shared_initial_evaluation_id = excluded.shared_initial_evaluation_id,
                    updated_at = excluded.updated_at
                """,
                (
                    state.experiment_id,
                    state.island_id,
                    state.profile,
                    state.root_id,
                    state.best_node_id,
                    state.best_score,
                    state.attempts,
                    state.valid_evaluations,
                    state.invalid_evaluations,
                    state.status,
                    state.stop_reason,
                    state.last_exchange_attempt,
                    state.stall_valid_evals,
                    state.infra_fail_streak,
                    state.consecutive_failures,
                    state.shared_initial_evaluation_id,
                    state.created_at or now,
                    now,
                ),
            )

    @staticmethod
    def _row_to_island_state(row: sqlite3.Row) -> IslandState:
        return IslandState(
            experiment_id=row["experiment_id"],
            island_id=row["island_id"],
            profile=row["profile"],
            root_id=row["root_id"],
            best_node_id=row["best_node_id"],
            best_score=row["best_score"] or 0.0,
            attempts=row["attempts"] or 0,
            valid_evaluations=row["valid_evaluations"] or 0,
            invalid_evaluations=row["invalid_evaluations"] or 0,
            status=row["status"],
            stop_reason=row["stop_reason"] or "",
            last_exchange_attempt=row["last_exchange_attempt"] or 0,
            stall_valid_evals=row["stall_valid_evals"] or 0,
            infra_fail_streak=row["infra_fail_streak"] or 0,
            consecutive_failures=row["consecutive_failures"] or 0,
            shared_initial_evaluation_id=row["shared_initial_evaluation_id"],
            created_at=row["created_at"] or "",
            updated_at=row["updated_at"] or "",
        )

    def get_island_states(self, experiment_id: str) -> list[IslandState]:
        with self._conn() as conn:
            if not self._table_exists(conn, "island_state"):
                return []
            rows = conn.execute(
                "SELECT * FROM island_state WHERE experiment_id = ? ORDER BY island_id",
                (experiment_id,),
            ).fetchall()
        return [self._row_to_island_state(r) for r in rows]

    def get_island_state(self, experiment_id: str, island_id: str) -> IslandState | None:
        with self._conn() as conn:
            if not self._table_exists(conn, "island_state"):
                return None
            row = conn.execute(
                "SELECT * FROM island_state WHERE experiment_id = ? AND island_id = ?",
                (experiment_id, island_id),
            ).fetchone()
        return self._row_to_island_state(row) if row is not None else None

    def create_summary(self, summary: ExchangeSummary) -> bool:
        """Persist a summary; content-hash dedup returns False when already known."""
        with self._conn() as conn:
            cur = conn.execute(
                """
                INSERT OR IGNORE INTO exchange_summary (
                    summary_id, experiment_id, kind, source_island_id, source_node_id,
                    task_fingerprint, evaluator_fingerprint, summary_text, conditions,
                    evidence_json, metrics_json, confidence_status, content_hash, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    summary.summary_id,
                    summary.experiment_id,
                    summary.kind,
                    summary.source_island_id,
                    summary.source_node_id,
                    summary.task_fingerprint,
                    summary.evaluator_fingerprint,
                    summary.summary_text,
                    summary.conditions,
                    json.dumps(summary.evidence_refs, ensure_ascii=False),
                    json.dumps(summary.metrics, ensure_ascii=False),
                    summary.confidence_status,
                    summary.content_hash,
                    summary.created_at or now_iso(),
                ),
            )
            return cur.rowcount > 0

    @staticmethod
    def _row_to_summary(row: sqlite3.Row) -> ExchangeSummary:
        return ExchangeSummary(
            summary_id=row["summary_id"],
            experiment_id=row["experiment_id"],
            kind=row["kind"],
            source_island_id=row["source_island_id"],
            source_node_id=row["source_node_id"] or "",
            task_fingerprint=row["task_fingerprint"] or "",
            evaluator_fingerprint=row["evaluator_fingerprint"] or "",
            summary_text=row["summary_text"] or "",
            conditions=row["conditions"] or "",
            evidence_refs=json.loads(row["evidence_json"] or "[]"),
            metrics=json.loads(row["metrics_json"] or "{}"),
            confidence_status=row["confidence_status"] or "single_observation",
            content_hash=row["content_hash"] or "",
            created_at=row["created_at"] or "",
        )

    def get_summary(self, summary_id: str) -> ExchangeSummary | None:
        with self._conn() as conn:
            if not self._table_exists(conn, "exchange_summary"):
                return None
            row = conn.execute(
                "SELECT * FROM exchange_summary WHERE summary_id = ?",
                (summary_id,),
            ).fetchone()
        return self._row_to_summary(row) if row is not None else None

    def get_summary_by_content_hash(
        self, experiment_id: str, content_hash: str
    ) -> ExchangeSummary | None:
        """The already-known summary for a normalized content hash."""
        if not content_hash:
            return None
        with self._conn() as conn:
            if not self._table_exists(conn, "exchange_summary"):
                return None
            row = conn.execute(
                "SELECT * FROM exchange_summary WHERE experiment_id = ? AND content_hash = ?",
                (experiment_id, content_hash),
            ).fetchone()
        return self._row_to_summary(row) if row is not None else None

    def add_summary_evidence(
        self,
        summary_id: str,
        evidence_ref: str,
        confidence_status: str,
        metrics: dict[str, Any] | None = None,
    ) -> None:
        """Attach another piece of evidence to an existing summary.

        Deduplicating identical conclusions must not lose the fact that a
        second node or island reached it, so the evidence list grows and the
        confidence rises instead of a duplicate row being inserted. The counts
        travel with the evidence, otherwise a reader would be told "1 occurrence"
        about a lesson three islands have now seen.
        """
        with self._conn() as conn:
            if not self._table_exists(conn, "exchange_summary"):
                return
            row = conn.execute(
                "SELECT evidence_json, metrics_json FROM exchange_summary "
                "WHERE summary_id = ?",
                (summary_id,),
            ).fetchone()
            if row is None:
                return
            refs = json.loads(row["evidence_json"] or "[]")
            if evidence_ref in refs:
                return
            refs.append(evidence_ref)
            payload = (
                metrics
                if metrics is not None
                else json.loads(row["metrics_json"] or "{}")
            )
            conn.execute(
                "UPDATE exchange_summary SET evidence_json = ?, confidence_status = ?, "
                "metrics_json = ? WHERE summary_id = ?",
                (
                    json.dumps(refs, ensure_ascii=False),
                    confidence_status,
                    json.dumps(payload, ensure_ascii=False),
                    summary_id,
                ),
            )

    def get_summaries_by_experiment(
        self,
        experiment_id: str,
        kinds: tuple[str, ...] | None = None,
    ) -> list[ExchangeSummary]:
        with self._conn() as conn:
            if not self._table_exists(conn, "exchange_summary"):
                return []
            if kinds:
                marks = ",".join("?" for _ in kinds)
                rows = conn.execute(
                    f"SELECT * FROM exchange_summary WHERE experiment_id = ? "
                    f"AND kind IN ({marks}) ORDER BY created_at",
                    (experiment_id, *kinds),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM exchange_summary WHERE experiment_id = ? ORDER BY created_at",
                    (experiment_id,),
                ).fetchall()
        return [self._row_to_summary(r) for r in rows]

    def create_delivery(self, delivery: ExchangeDelivery) -> bool:
        """Insert a delivery; at most one delivery per (summary, target island)."""
        with self._conn() as conn:
            cur = conn.execute(
                """
                INSERT OR IGNORE INTO exchange_delivery (
                    delivery_id, experiment_id, summary_id, source_island_id,
                    target_island_id, status, reason, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    delivery.delivery_id,
                    delivery.experiment_id,
                    delivery.summary_id,
                    delivery.source_island_id,
                    delivery.target_island_id,
                    delivery.status,
                    delivery.reason,
                    delivery.created_at or now_iso(),
                    now_iso(),
                ),
            )
            return cur.rowcount > 0

    @staticmethod
    def _row_to_delivery(row: sqlite3.Row) -> ExchangeDelivery:
        return ExchangeDelivery(
            delivery_id=row["delivery_id"],
            experiment_id=row["experiment_id"],
            summary_id=row["summary_id"],
            source_island_id=row["source_island_id"],
            target_island_id=row["target_island_id"],
            status=row["status"],
            reason=row["reason"] or "",
            created_at=row["created_at"] or "",
            updated_at=row["updated_at"] or "",
        )

    def get_deliveries(
        self,
        experiment_id: str,
        target_island_id: str | None = None,
        statuses: tuple[str, ...] | None = None,
    ) -> list[ExchangeDelivery]:
        query = "SELECT * FROM exchange_delivery WHERE experiment_id = ?"
        params: list[Any] = [experiment_id]
        if target_island_id is not None:
            query += " AND target_island_id = ?"
            params.append(target_island_id)
        if statuses:
            query += " AND status IN (" + ",".join("?" for _ in statuses) + ")"
            params.extend(statuses)
        query += " ORDER BY created_at"
        with self._conn() as conn:
            if not self._table_exists(conn, "exchange_delivery"):
                return []
            rows = conn.execute(query, params).fetchall()
        return [self._row_to_delivery(r) for r in rows]

    def update_delivery_decision(
        self,
        delivery_id: str,
        status: str,
        reason: str = "",
    ) -> None:
        if status not in DELIVERY_STATUSES:
            raise ValueError(f"invalid delivery status: {status}")
        with self._conn() as conn:
            conn.execute(
                "UPDATE exchange_delivery SET status = ?, reason = ?, updated_at = ? WHERE delivery_id = ?",
                (status, reason, now_iso(), delivery_id),
            )

    def record_application(self, application: SummaryApplication) -> bool:
        """Record summary usage by a candidate; one row per (delivery, candidate)."""
        with self._conn() as conn:
            cur = conn.execute(
                """
                INSERT OR IGNORE INTO summary_application (
                    application_id, delivery_id, experiment_id, candidate_node_id,
                    evaluation_id, score, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    application.application_id,
                    application.delivery_id,
                    application.experiment_id,
                    application.candidate_node_id,
                    application.evaluation_id,
                    application.score,
                    application.created_at or now_iso(),
                ),
            )
            return cur.rowcount > 0

    def complete_application(
        self,
        application_id: str,
        evaluation_id: str,
        score: float | None,
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE summary_application SET evaluation_id = ?, score = ? WHERE application_id = ?",
                (evaluation_id, score, application_id),
            )

    def get_applications_for_delivery(self, delivery_id: str) -> list[SummaryApplication]:
        with self._conn() as conn:
            if not self._table_exists(conn, "summary_application"):
                return []
            rows = conn.execute(
                "SELECT * FROM summary_application WHERE delivery_id = ? ORDER BY created_at",
                (delivery_id,),
            ).fetchall()
        return [
            SummaryApplication(
                application_id=r["application_id"],
                delivery_id=r["delivery_id"],
                experiment_id=r["experiment_id"],
                candidate_node_id=r["candidate_node_id"],
                evaluation_id=r["evaluation_id"] or "",
                score=r["score"],
                created_at=r["created_at"] or "",
            )
            for r in rows
        ]

    def get_applications_by_experiment(self, experiment_id: str) -> list[SummaryApplication]:
        with self._conn() as conn:
            if not self._table_exists(conn, "summary_application"):
                return []
            rows = conn.execute(
                "SELECT * FROM summary_application WHERE experiment_id = ? ORDER BY created_at",
                (experiment_id,),
            ).fetchall()
        return [
            SummaryApplication(
                application_id=r["application_id"],
                delivery_id=r["delivery_id"],
                experiment_id=r["experiment_id"],
                candidate_node_id=r["candidate_node_id"],
                evaluation_id=r["evaluation_id"] or "",
                score=r["score"],
                created_at=r["created_at"] or "",
            )
            for r in rows
        ]

    def save_scheduler_state(self, state: SchedulerState) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO scheduler_state (
                    experiment_id, next_island_index, rng_state_json, schema_version, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(experiment_id) DO UPDATE SET
                    next_island_index = excluded.next_island_index,
                    rng_state_json = excluded.rng_state_json,
                    schema_version = excluded.schema_version,
                    updated_at = excluded.updated_at
                """,
                (
                    state.experiment_id,
                    state.next_island_index,
                    state.rng_state_json,
                    state.schema_version,
                    now_iso(),
                ),
            )

    def put_run_identity(self, experiment_id: str, identity_json: str) -> None:
        """Record what this run was started with, for a later resume to check."""
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO run_identity (experiment_id, identity_json, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(experiment_id) DO UPDATE SET
                    identity_json = excluded.identity_json,
                    updated_at = excluded.updated_at
                """,
                (experiment_id, identity_json, now_iso(), now_iso()),
            )

    def get_run_identity(self, experiment_id: str) -> str | None:
        """The stored identity record, or None when this run never described itself."""
        with self._conn() as conn:
            if not self._table_exists(conn, "run_identity"):
                return None
            row = conn.execute(
                "SELECT identity_json FROM run_identity WHERE experiment_id = ?",
                (experiment_id,),
            ).fetchone()
        if row is None:
            return None
        return str(row["identity_json"] or "")

    def get_run_claim(self, experiment_id: str) -> dict[str, Any] | None:
        """Who currently holds this run, or None when nobody does."""
        with self._conn() as conn:
            if not self._table_exists(conn, "run_claim"):
                return None
            row = conn.execute(
                "SELECT * FROM run_claim WHERE experiment_id = ?",
                (experiment_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "holder_id": str(row["holder_id"] or ""),
            "holder_pid": row["holder_pid"],
            "claimed_at": str(row["claimed_at"] or ""),
        }

    def take_run_claim(self, experiment_id: str, holder_id: str, pid: int) -> None:
        """Say out loud which process is writing this run right now."""
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO run_claim (experiment_id, holder_id, holder_pid, claimed_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(experiment_id) DO UPDATE SET
                    holder_id = excluded.holder_id,
                    holder_pid = excluded.holder_pid,
                    claimed_at = excluded.claimed_at
                """,
                (experiment_id, holder_id, pid, now_iso()),
            )

    def release_run_claim(self, experiment_id: str, holder_id: str) -> None:
        """Drop the claim, but only the one this process wrote.

        A holder that arrives after someone else took over must not delete the new
        holder's claim on its way out -- that is how two processes end up running
        one experiment again.
        """
        with self._conn() as conn:
            if not self._table_exists(conn, "run_claim"):
                return
            conn.execute(
                "DELETE FROM run_claim WHERE experiment_id = ? AND holder_id = ?",
                (experiment_id, holder_id),
            )

    def get_scheduler_state(self, experiment_id: str) -> SchedulerState | None:
        with self._conn() as conn:
            if not self._table_exists(conn, "scheduler_state"):
                return None
            row = conn.execute(
                "SELECT * FROM scheduler_state WHERE experiment_id = ?",
                (experiment_id,),
            ).fetchone()
        if row is None:
            return None
        return SchedulerState(
            experiment_id=row["experiment_id"],
            next_island_index=row["next_island_index"] or 0,
            rng_state_json=row["rng_state_json"] or "",
            schema_version=row["schema_version"] or 2,
            updated_at=row["updated_at"] or "",
        )
