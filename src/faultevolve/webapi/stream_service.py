"""Live event stream for one run (phase 8, TODO §8.1-§8.3).

This is the layer that turns :mod:`faultevolve.webapi.event_stream`'s transport-
agnostic pieces into an actual generator, plus the route-facing entry point. It
owns three decisions the frame module deliberately did not:

**Where events come from while the run is alive.** ``events.jsonl`` is written
*once, at the end* (``engine.write_artifacts``), so during a run it does not
exist yet. The live source is therefore ``fe.db``'s ``event`` table, read
through the existing read-only helper with a busy timeout -- the engine is
writing to that file right now, and a reader that blocked it (or wrote to it)
would corrupt the run it is supposed to report on.

**When to stop reading the live database.** On ``run_finished`` the run is over
and the artifacts become the truth. From that point the stream re-reads the
stable artifacts, emits ``snapshot_ready`` and closes, so the client invalidates
its REST queries and stops guessing (TODO §8.3's five steps).

**How a run that is already over is handled.** Nothing to stream: the whole
timeline is in ``events.jsonl``, it is emitted, ``snapshot_ready`` follows, done.
Opening a stream on a finished run must not hang.

Security: payloads pass through :func:`replay_service.event_responses`, the same
function the polling endpoint uses, so sanitisation has exactly one gate. This
module never formats a payload itself.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import Any

from faultevolve.webapi import replay_service
from faultevolve.webapi.catalog import EVENT_TYPES
from faultevolve.webapi.event_stream import (
    HEARTBEAT_INTERVAL_SECONDS,
    SSE_MEDIA_TYPE,
    coerce_last_event_id,
    heartbeat_frame,
    select_after,
    sse_frame,
)
from faultevolve.webapi.sqlite_ro import connect_ro, has_table
from faultevolve.webapi.settings import WebSettings

#: Event that ends the live phase. Its payload is the last thing read from the
#: live database; everything after it comes from the stable artifacts.
RUN_FINISHED = "run_finished"

#: Pseudo-event telling the client the artifacts are now authoritative. Not an
#: engine event type -- it is deliberately outside ``EVENT_TYPES`` so it can
#: never be confused for one, and it carries no id (there is no engine row).
SNAPSHOT_READY = "snapshot_ready"

#: How often the live database is polled while a run is in flight. The engine
#: writes an event every few seconds at most, so this is fast enough to feel
#: live and slow enough not to hammer the file the engine is writing.
LIVE_POLL_SECONDS = 0.5

#: Upper bound on how long the stream waits for the engine to finish writing
#: artifacts after ``run_finished``. Past it the stream emits what it has and
#: closes: a client stuck on an open stream forever is worse than one that has
#: to re-read, because the REST endpoints still answer either way.
ARTIFACT_WAIT_SECONDS = 30.0


def _live_event_rows(db_path: Path, run_id: str) -> list[dict[str, Any]]:
    """Read the ``event`` table as the shape ``events.jsonl`` rows have.

    Returns ``[]`` for every "cannot read right now" case -- no file yet, table
    not created yet, or the engine holding the write lock. Those are all normal
    states of a run in flight, not errors, and the caller retries. Only an
    unreadable *file* (a corrupt database) is worth surfacing, and even then the
    stream stays useful: it just carries no live events until the artifacts land.
    """
    if not db_path.is_file():
        return []
    try:
        with connect_ro(db_path, run_id=run_id) as conn:
            if not has_table(conn, "event"):
                return []
            rows = conn.execute(
                "SELECT id, experiment_id, type, payload_json, ts "
                "FROM event ORDER BY id"
            ).fetchall()
    except Exception:
        # A busy or locked database is the expected state while the engine
        # writes. Swallowing it here is what keeps the stream alive; the read
        # simply returns nothing this tick.
        return []

    events: list[dict[str, Any]] = []
    for row in rows:
        raw = row["payload_json"]
        try:
            payload = json.loads(raw) if isinstance(raw, str) else {}
        except (TypeError, ValueError):
            # One unparseable payload must not cost the client every other event
            # in this tick -- the same rule `read_events` applies to a partially
            # written jsonl.
            payload = {}
        events.append(
            {
                "id": row["id"],
                "experiment_id": row["experiment_id"],
                "type": row["type"],
                "payload": payload if isinstance(payload, dict) else {},
                "ts": row["ts"] or "",
            }
        )
    return events


def _frames_for(
    events: Sequence[dict[str, Any]], run_id: str
) -> tuple[list[str], int | None]:
    """Render events as SSE frames, returning the frames and the new cursor.

    ``runId`` is inside every payload because the frame's ``data`` is the same
    :class:`EventResponse` the REST endpoint returns. That is deliberate: one
    shape for both paths means a client that falls back from SSE to polling
    (or reconnects across the boundary) does not have to translate, and it is
    what makes "two open streams must not cross events" checkable by the client.
    """
    frames: list[str] = []
    cursor: int | None = None
    for response in replay_service.event_responses(events, run_id):
        frames.append(
            sse_frame(
                event_id=response.id,
                event_type=response.type,
                data=response.model_dump(mode="json"),
            )
        )
        if response.id is not None:
            cursor = response.id if cursor is None else max(cursor, response.id)
    return frames, cursor


def _snapshot_ready_frame() -> str:
    """The convergence signal. No ``id:`` -- there is no engine row behind it.

    Sending an id would be a lie the browser would act on: it would resume from
    a cursor that does not exist.
    """
    return sse_frame(
        event_id=None,
        event_type=SNAPSHOT_READY,
        data={
            "contract_version": replay_service.contract_version(),
            "event": SNAPSHOT_READY,
        },
    )


def _finished(artifacts: replay_service.RunArtifacts) -> bool:
    """Whether the stable artifacts are there, i.e. the run is over.

    ``run_summary.json`` is written first among the artifacts, so its presence
    is the earliest honest signal that the engine reached the end.
    """
    return artifacts.summary_path.is_file()


async def stream_run_events(
    settings: WebSettings,
    run_id: str,
    *,
    after_id: int | None = None,
    poll_seconds: float | None = None,
    artifact_wait_seconds: float = ARTIFACT_WAIT_SECONDS,
    heartbeat_seconds: float = HEARTBEAT_INTERVAL_SECONDS,
) -> AsyncIterator[str]:
    """Yield SSE frames for ``run_id``, starting strictly after ``after_id``.

    The generator is finite on purpose: it ends after ``snapshot_ready``. A
    stream that never closes is a socket, a thread and a browser retry loop
    nobody asked for; the client re-opens it if it needs more.

    ``poll_seconds`` defaults to the module constant *at call time* rather than
    as a default argument. A default argument freezes the value when the module
    is imported, which makes the constant a lie: it reads like a knob and
    behaves like a constant, and no test can slow the loop down without a
    five-second wait per iteration.
    """
    interval = LIVE_POLL_SECONDS if poll_seconds is None else poll_seconds
    artifacts = replay_service.artifacts_for(settings, run_id)
    cursor = after_id

    # Phase 0 -- already over. The whole timeline is in the artifacts, so there
    # is nothing to tail: emit it and converge immediately.
    if _finished(artifacts):
        events, _skipped, _warnings = replay_service.read_events(artifacts)
        for frame in _frames_for(select_after(events, cursor), run_id)[0]:
            yield frame
        yield _snapshot_ready_frame()
        return

    # Phase 1 -- live. Tail fe.db until the run ends.
    since_output = 0.0
    while True:
        rows = _live_event_rows(artifacts.db_path, run_id)
        fresh = select_after(rows, cursor)
        if fresh:
            frames, new_cursor = _frames_for(fresh, run_id)
            for frame in frames:
                yield frame
            if new_cursor is not None:
                cursor = new_cursor
            since_output = 0.0

            if any(e.get("type") == RUN_FINISHED for e in fresh):
                # The engine is on its way to writing artifacts. Stop reading
                # the live database now -- not because it is unsafe, but because
                # the artifacts are about to be authoritative and reading both
                # would deliver the tail twice.
                break
        elif _finished(artifacts):
            # The run ended without us seeing `run_finished` in this batch (we
            # may have connected mid-tail). The artifacts are there; go converge.
            break

        await asyncio.sleep(interval)
        since_output += interval
        if since_output >= heartbeat_seconds:
            # A comment, not an event: it keeps proxies from reaping an idle
            # connection without putting a ghost entry in the timeline.
            yield heartbeat_frame()
            since_output = 0.0

    # Phase 2 -- converge (TODO §8.3). Wait for the artifacts to be complete,
    # then emit whatever the live phase did not, in id order.
    #
    # The wait is bounded on purpose. If the engine dies between writing
    # `run_finished` and writing its summary, waiting forever would leave the
    # client holding a socket that will never say anything again. Past the
    # budget we emit what exists and close: the REST endpoints answer either
    # way, so a closed stream costs one re-read, not a broken page.
    waited = 0.0
    while not _finished(artifacts) and waited < artifact_wait_seconds:
        await asyncio.sleep(interval)
        waited += poll_seconds

    events, _skipped, _warnings = replay_service.read_events(artifacts)
    for frame in _frames_for(select_after(events, cursor), run_id)[0]:
        yield frame

    yield _snapshot_ready_frame()


__all__ = [
    "ARTIFACT_WAIT_SECONDS",
    "LIVE_POLL_SECONDS",
    "RUN_FINISHED",
    "SNAPSHOT_READY",
    "SSE_MEDIA_TYPE",
    "coerce_last_event_id",
    "stream_run_events",
]
