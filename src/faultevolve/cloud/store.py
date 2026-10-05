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
    Event,
    Experiment,
    ExperimentConfig,
    Insight,
    LLMCall,
    Node,
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
    node_id TEXT,
    purpose TEXT,
    model TEXT,
    prompt_tokens INTEGER,
    completion_tokens INTEGER,
    latency_ms INTEGER,
    cached INTEGER DEFAULT 0,
    created_at TEXT
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
    operator TEXT,
    alpha REAL,
    beta REAL,
    n INTEGER DEFAULT 0,
    n_valid INTEGER DEFAULT 0,
    sum_delta REAL DEFAULT 0.0,
    PRIMARY KEY (experiment_id, operator)
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
"""


def now_iso() -> str:
    """Get current UTC time in ISO format."""
    return datetime.now(timezone.utc).isoformat()


class Store:
    """SQLite-based store for FaultEvolve data."""

    def __init__(self, db_path: Path) -> None:
        """Initialize the store.

        Args:
            db_path: Path to the SQLite database file
        """
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        """Initialize the database schema."""
        with self._conn() as conn:
            conn.executescript(DDL)
            conn.execute("PRAGMA journal_mode=WAL")

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        """Context manager for database connections."""
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

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
                INSERT INTO node (id, experiment_id, parent_id, branch_id, depth, operator,
                                  artifact_json, evidence_json, status, hypothesis_status,
                                  visit_count, expand_count, children_json, insight_ids_json,
                                  card_ids_json, branch_memory_json, repair_attempted,
                                  hypothesis_fail_count, repair_count, repair_parent_id,
                                  error_class, repair_exhausted, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    node.id,
                    node.experiment_id,
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
    ) -> None:
        """Update node fields."""
        updates = []
        params: list[Any] = []

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

    def get_nodes_by_experiment(self, experiment_id: str) -> list[Node]:
        """Get all nodes for an experiment."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM node WHERE experiment_id = ? ORDER BY created_at",
                (experiment_id,),
            ).fetchall()

        return [self._row_to_node(row) for row in rows]

    def create_insight(self, insight: Insight, experiment_id: str) -> None:
        """Create a new insight."""
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO insight (id, experiment_id, origin_node, branch_id, polarity,
                                     payload_json, delta, z_score, alpha, beta, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    insight.id,
                    experiment_id,
                    insight.origin_node,
                    insight.branch_id,
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

    def get_insights_by_experiment(self, experiment_id: str) -> list[Insight]:
        """Get all insights for an experiment."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM insight WHERE experiment_id = ? ORDER BY created_at",
                (experiment_id,),
            ).fetchall()

        insights = []
        for row in rows:
            payload = json.loads(row["payload_json"]) if row["payload_json"] else {}
            insights.append(Insight(
                id=row["id"],
                origin_node=row["origin_node"],
                branch_id=row["branch_id"],
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
                INSERT INTO llm_call (id, experiment_id, node_id, purpose, model,
                                      prompt_tokens, completion_tokens, latency_ms,
                                      cached, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    llm_call.id,
                    llm_call.experiment_id,
                    llm_call.node_id,
                    llm_call.purpose,
                    llm_call.model,
                    llm_call.prompt_tokens,
                    llm_call.completion_tokens,
                    llm_call.latency_ms,
                    1 if llm_call.cached else 0,
                    llm_call.created_at or now_iso(),
                ),
            )

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

    def get_llm_calls(self, experiment_id: str) -> list[LLMCall]:
        """Get all LLM calls for an experiment."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM llm_call WHERE experiment_id = ? ORDER BY created_at",
                (experiment_id,),
            ).fetchall()

        return [
            LLMCall(
                id=row["id"],
                experiment_id=row["experiment_id"],
                node_id=row["node_id"],
                purpose=row["purpose"],
                model=row["model"],
                prompt_tokens=row["prompt_tokens"],
                completion_tokens=row["completion_tokens"],
                latency_ms=row["latency_ms"],
                cached=bool(row["cached"]),
                created_at=row["created_at"],
            )
            for row in rows
        ]

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
                WHERE experiment_id = ? AND operator = ?
                """,
                (experiment_id, operator),
            ).fetchone()
            if row is None:
                alpha = prior_alpha + (1 if success else 0)
                beta = prior_beta + (0 if success else 1)
                n_valid = 1 if valid else 0
                sum_delta = delta if valid else 0.0
                conn.execute(
                    """
                    INSERT INTO operator_stats (
                        experiment_id, operator, alpha, beta, n, n_valid, sum_delta
                    ) VALUES (?, ?, ?, ?, 1, ?, ?)
                    """,
                    (experiment_id, operator, alpha, beta, n_valid, sum_delta),
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
                WHERE experiment_id = ? AND operator = ?
                """,
                (alpha, beta, n, n_valid, sum_delta, experiment_id, operator),
            )

    def get_operator_stats(self, experiment_id: str) -> dict[str, dict[str, float]]:
        """Return operator bandit stats keyed by operator name."""
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT operator, alpha, beta, n, n_valid, sum_delta
                FROM operator_stats
                WHERE experiment_id = ?
                """,
                (experiment_id,),
            ).fetchall()
        result: dict[str, dict[str, float]] = {}
        for row in rows:
            result[str(row["operator"])] = {
                "alpha": float(row["alpha"]),
                "beta": float(row["beta"]),
                "n": float(row["n"]),
                "n_valid": float(row["n_valid"]),
                "sum_delta": float(row["sum_delta"]),
            }
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
                    experiment_id, seq, stage, fidelity, node_id,
                    prompt_tokens, completion_tokens, model_fit_count, evaluator_calls,
                    cpu_seconds, rss_peak_mb, wall_s, cache_hit, status,
                    reservation_id, meta_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    experiment_id,
                    rec.seq,
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
