"""Read-only SQLite access for replay (TODO §2.3).

**Why not reuse ``Store``.** ``Store.__init__`` does three things that are fatal
for replay: it creates the parent directory, runs the DDL script, and issues
``PRAGMA journal_mode=WAL``. Pointed at a committed fixture that means the
fixture gets rewritten and ``fe.db-wal`` / ``fe.db-shm`` appear in the repository
as untracked files. Replay must therefore never touch ``Store``.

The connection opened here is opened ``mode=ro``: SQLite itself refuses writes,
so a mistake upstream cannot corrupt the artifact even if it tries.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from faultevolve.webapi.errors import RunUnreadableError


def _uri(db_path: Path) -> str:
    """Build the ``file:`` URI SQLite needs for read-only mode.

    ``as_uri`` percent-encodes spaces and other awkward characters, and SQLite
    accepts the resulting empty authority (``file:///C:/...``). Building the URI
    by string concatenation instead would break on any path with a space.
    """
    return f"{db_path.resolve().as_uri()}?mode=ro"


@contextmanager
def connect_ro(db_path: Path, *, run_id: str = "") -> Iterator[sqlite3.Connection]:
    """Yield a read-only connection, or raise ``RunUnreadableError``.

    The file must already exist: this function never creates one, so a typo in a
    run id surfaces as "unreadable" rather than as a new empty database.
    """
    if not db_path.is_file():
        raise RunUnreadableError(run_id or db_path.name, "database file is missing")
    try:
        conn = sqlite3.connect(_uri(db_path), uri=True, timeout=5.0)
    except sqlite3.Error as exc:  # pragma: no cover - rare on this platform
        raise RunUnreadableError(run_id or db_path.name, type(exc).__name__) from exc
    conn.row_factory = sqlite3.Row
    try:
        # Fail fast on a corrupt file rather than on the first query.
        conn.execute("SELECT 1")
        yield conn
    except sqlite3.OperationalError as exc:
        raise RunUnreadableError(
            run_id or db_path.name, _safe_sqlite_reason(exc)
        ) from exc
    finally:
        conn.close()


def _safe_sqlite_reason(exc: sqlite3.Error) -> str:
    """Map a sqlite error to a short reason that cannot leak a host path.

    SQLite error strings happily quote the absolute database path, so the raw
    message is never propagated.
    """
    text = str(exc).lower()
    if "readonly" in text or "read-only" in text:
        return "database requires write access (WAL recovery?)"
    if "malformed" in text or "not a database" in text:
        return "database file is malformed"
    if "no such table" in text:
        return "expected table is missing"
    return "database could not be read"


def table_names(conn: sqlite3.Connection) -> set[str]:
    """Names of the real tables present, excluding SQLite internals."""
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    ).fetchall()
    return {row[0] for row in rows if not str(row[0]).startswith("sqlite_")}


def has_table(conn: sqlite3.Connection, table: str) -> bool:
    """Whether ``table`` exists, without raising on a missing one."""
    return table in table_names(conn)


def count_rows(conn: sqlite3.Connection, table: str) -> int:
    """Row count of ``table``, or ``0`` when the table does not exist.

    ``table`` is validated against the live table list, so it can never become
    an injection point even if a caller passes something dynamic.
    """
    if not has_table(conn, table):
        return 0
    row = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()
    return int(row[0]) if row else 0


def fetch_all(
    conn: sqlite3.Connection, table: str, *, order_by: str | None = None
) -> list[dict[str, Any]]:
    """All rows of ``table`` as plain dicts, or ``[]`` when it is absent.

    Returning ``[]`` for a missing table is deliberate: ten of the fixture's
    twenty tables are empty by design, and "table not present" and "table empty"
    both mean *available but no rows* to the UI.
    """
    if not has_table(conn, table):
        return []
    sql = f'SELECT * FROM "{table}"'
    if order_by:
        sql += f" ORDER BY {order_by}"
    return [dict(row) for row in conn.execute(sql)]
