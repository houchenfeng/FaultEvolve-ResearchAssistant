"""Run registry: the Web API's own ledger of runs it started (TODO 7.2).

Separate from the engine's ``fe.db`` on purpose. ``fe.db`` is a run *artifact*
-- the replay endpoints read it, and its DDL belongs to the engine. The registry
answers a different question: "which processes did this Web service start, and
are they still alive?" Mixing the two would put a Web concern inside an artifact
the engine owns, so this gets its own file.

**Why ``journal_mode=MEMORY``.** The default rollback journal writes a
``<db>-journal`` sidecar and *deletes* it on commit; WAL mode creates and
deletes ``-wal``/``-shm``. On this host a long-running service process that
unlinks files under a user data directory trips the environment's bulk-delete
guard, which raises ``SystemExit`` and kills the process -- a 500 plus a dead
server. Keeping the journal in memory means sqlite creates one file and never
removes anything. The trade-off is that a crash mid-commit can leave the
registry inconsistent; it is a cache of process state that can be rebuilt from
the runs directories, so that is the cheaper failure.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from faultevolve.webapi.settings import WebSettings

#: One row per run the Web API started.
_SCHEMA = """
CREATE TABLE IF NOT EXISTS run_record (
    run_id            TEXT PRIMARY KEY,
    execution_backend TEXT NOT NULL,
    server_profile_id TEXT,
    pid               INTEGER,
    status            TEXT NOT NULL,
    task_dir          TEXT NOT NULL,
    db_dir            TEXT NOT NULL,
    artifacts_dir     TEXT NOT NULL,
    log_dir           TEXT,
    start_args        TEXT NOT NULL,
    created_at        TEXT NOT NULL,
    finished_at       TEXT,
    exit_code         INTEGER,
    resumed_from      TEXT,
    detail            TEXT
)
"""

#: Lifecycle states the registry may hold. ``interrupted`` is the one the
#: recovery pass assigns: the process is gone and no completion was recorded.
STATUS_RUNNING = "running"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"
STATUS_CANCELLED = "cancelled"
STATUS_INTERRUPTED = "interrupted"

TERMINAL_STATUSES = frozenset(
    {STATUS_COMPLETED, STATUS_FAILED, STATUS_CANCELLED, STATUS_INTERRUPTED}
)


class RegistryNotConfiguredError(RuntimeError):
    """``WebSettings.run_registry`` is unset, so there is nowhere to write."""


@dataclass
class RunRecord:
    """One registry row, typed."""

    run_id: str
    execution_backend: str
    server_profile_id: str | None
    pid: int | None
    status: str
    task_dir: str
    db_dir: str
    artifacts_dir: str
    log_dir: str | None
    start_args: list[str] = field(default_factory=list)
    created_at: str = ""
    finished_at: str | None = None
    exit_code: int | None = None
    resumed_from: str | None = None
    detail: str = ""

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES


def now_iso() -> str:
    """UTC timestamp, second precision. Sortable as a string."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def registry_path(settings: WebSettings) -> Path | None:
    return settings.run_registry


def registry_configured(settings: WebSettings) -> bool:
    """Whether a registry can be written at all.

    Routes turn ``False`` into a capability error, so "not configured" reads as
    "this build cannot start runs", not as a 500.
    """
    return settings.run_registry is not None


@contextmanager
def _open(settings: WebSettings) -> Iterator[sqlite3.Connection]:
    path = settings.run_registry
    if path is None:
        raise RegistryNotConfiguredError("run registry is not configured")
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=5.0)
    try:
        conn.row_factory = sqlite3.Row
        # See the module docstring: no on-disk journal, therefore no unlink.
        conn.execute("PRAGMA journal_mode=MEMORY")
        conn.execute("PRAGMA synchronous=FULL")
        conn.execute(_SCHEMA)
        yield conn
        conn.commit()
    finally:
        conn.close()


def _row_to_record(row: sqlite3.Row) -> RunRecord:
    raw_args = row["start_args"] or "[]"
    try:
        parsed = json.loads(raw_args)
    except json.JSONDecodeError:
        parsed = []
    return RunRecord(
        run_id=row["run_id"],
        execution_backend=row["execution_backend"],
        server_profile_id=row["server_profile_id"],
        pid=row["pid"],
        status=row["status"],
        task_dir=row["task_dir"],
        db_dir=row["db_dir"],
        artifacts_dir=row["artifacts_dir"],
        log_dir=row["log_dir"],
        start_args=[str(part) for part in parsed] if isinstance(parsed, list) else [],
        created_at=row["created_at"] or "",
        finished_at=row["finished_at"],
        exit_code=row["exit_code"],
        resumed_from=row["resumed_from"],
        detail=row["detail"] or "",
    )


def insert_record(settings: WebSettings, record: RunRecord) -> None:
    """Insert a brand-new run.

    Raises ``sqlite3.IntegrityError`` if the id is already present. Refusing
    rather than upserting is the point: a second launch under an id that is
    already accounted for would overwrite the row that names a *live* process,
    and the orphan would become untrackable.
    """
    with _open(settings) as conn:
        conn.execute(
            """
            INSERT INTO run_record (
                run_id, execution_backend, server_profile_id, pid, status,
                task_dir, db_dir, artifacts_dir, log_dir, start_args,
                created_at, finished_at, exit_code, resumed_from, detail
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.run_id,
                record.execution_backend,
                record.server_profile_id,
                record.pid,
                record.status,
                record.task_dir,
                record.db_dir,
                record.artifacts_dir,
                record.log_dir,
                json.dumps(record.start_args, ensure_ascii=False),
                record.created_at or now_iso(),
                record.finished_at,
                record.exit_code,
                record.resumed_from,
                record.detail,
            ),
        )


def get_record(settings: WebSettings, run_id: str) -> RunRecord | None:
    with _open(settings) as conn:
        row = conn.execute(
            "SELECT * FROM run_record WHERE run_id = ?", (run_id,)
        ).fetchone()
    return _row_to_record(row) if row is not None else None


def list_records(settings: WebSettings) -> list[RunRecord]:
    """Every row, newest first."""
    with _open(settings) as conn:
        rows = conn.execute(
            "SELECT * FROM run_record ORDER BY created_at DESC, run_id DESC"
        ).fetchall()
    return [_row_to_record(row) for row in rows]


def update_launch(
    settings: WebSettings,
    run_id: str,
    *,
    pid: int | None,
    status: str,
    execution_backend: str | None = None,
    detail: str | None = None,
) -> None:
    """Point an existing row at a (re)started process.

    Used by resume: the id stays, the process handle changes. ``created_at`` is
    deliberately left alone -- it is when the run first existed, not when it was
    last restarted.
    """
    with _open(settings) as conn:
        conn.execute(
            """
            UPDATE run_record
               SET pid = ?, status = ?, finished_at = NULL, exit_code = NULL,
                   execution_backend = COALESCE(?, execution_backend),
                   detail = COALESCE(?, detail)
             WHERE run_id = ?
            """,
            (pid, status, execution_backend, detail, run_id),
        )


def mark_finished(
    settings: WebSettings,
    run_id: str,
    *,
    status: str,
    exit_code: int | None = None,
    detail: str | None = None,
) -> None:
    """Close out a row that reached a terminal state."""
    with _open(settings) as conn:
        conn.execute(
            """
            UPDATE run_record
               SET status = ?, exit_code = ?, finished_at = ?,
                   detail = COALESCE(?, detail)
             WHERE run_id = ?
            """,
            (status, exit_code, now_iso(), detail, run_id),
        )


def running_records(settings: WebSettings) -> list[RunRecord]:
    """Rows claiming to be live -- the recovery pass's input."""
    with _open(settings) as conn:
        rows = conn.execute(
            "SELECT * FROM run_record WHERE status = ? ORDER BY created_at",
            (STATUS_RUNNING,),
        ).fetchall()
    return [_row_to_record(row) for row in rows]


def delete_record(settings: WebSettings, run_id: str) -> None:
    """Drop a row. Only for tests and for a run that never actually started."""
    with _open(settings) as conn:
        conn.execute("DELETE FROM run_record WHERE run_id = ?", (run_id,))


def as_dict(record: RunRecord) -> dict[str, Any]:
    """Plain mapping, for tests and for building DTOs."""
    return {
        "run_id": record.run_id,
        "execution_backend": record.execution_backend,
        "server_profile_id": record.server_profile_id,
        "pid": record.pid,
        "status": record.status,
        "task_dir": record.task_dir,
        "db_dir": record.db_dir,
        "artifacts_dir": record.artifacts_dir,
        "log_dir": record.log_dir,
        "start_args": list(record.start_args),
        "created_at": record.created_at,
        "finished_at": record.finished_at,
        "exit_code": record.exit_code,
        "resumed_from": record.resumed_from,
        "detail": record.detail,
    }


__all__ = [
    "RegistryNotConfiguredError",
    "RunRecord",
    "STATUS_CANCELLED",
    "STATUS_COMPLETED",
    "STATUS_FAILED",
    "STATUS_INTERRUPTED",
    "STATUS_RUNNING",
    "TERMINAL_STATUSES",
    "as_dict",
    "delete_record",
    "get_record",
    "insert_record",
    "list_records",
    "mark_finished",
    "now_iso",
    "registry_configured",
    "registry_path",
    "running_records",
    "update_launch",
]
