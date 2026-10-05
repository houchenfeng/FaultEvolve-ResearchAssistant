"""Transport-agnostic event streaming core (phase 8 preparation).

Phase 8 exposes ``GET /api/runs/{run_id}/stream`` as **SSE** (decision
2026-10-02: one push channel, overriding the PRD's WebSocket / Socket.IO
split). This module deliberately owns only the parts that are *not*
transport-specific, so they could be written and pinned by tests today
**without opening any endpoint** -- the same staging the project already used
for :mod:`faultevolve.webapi.execution_backend` in phase 4.

What lives here:

* :func:`sse_frame` -- one event rendered as an SSE frame, byte-for-byte per
  the TODO §8.2 wire format.
* :func:`heartbeat_frame` -- the keep-alive comment frame.
* :func:`coerce_last_event_id` -- ``Last-Event-ID`` parsing, so a reconnecting
  browser resumes with *exactly* the same cursor semantics as ``?after_id=``
  (PRD §16.3).
* :func:`select_after` / :func:`split_page` -- the cursor and paging rules
  shared by the existing polling endpoint and the future stream.

Deliberately **not** here: the endpoint, the generator loop, the SQLite live
reader, heartbeats on a timer, and client disconnects. Those are phase 8, and
they need a running app.

Security note: this module never formats payloads itself. Callers pass data
that already went through
:func:`faultevolve.webapi.sanitization.sanitize_value`, exactly as
``replay_service._event_response`` does. Frames carry whatever they are given,
so sanitising upstream is what keeps secrets and absolute paths out.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

#: Media type for ``text/event-stream`` responses.
SSE_MEDIA_TYPE = "text/event-stream"

#: Response headers the SSE endpoint must send.
#:
#: ``Cache-Control: no-store`` keeps a proxy from replaying a stale stream, and
#: ``X-Accel-Buffering: no`` is what stops nginx from buffering the stream into
#: oblivion -- without it the client sees nothing until the run ends, which
#: looks exactly like "the push channel is broken".
SSE_HEADERS: dict[str, str] = {
    "Cache-Control": "no-store",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}

#: Seconds between keep-alive comments. Browsers only fire ``onerror`` after
#: the connection drops; without a periodic byte the stream can sit idle for
#: minutes and be reaped by an intermediary.
HEARTBEAT_INTERVAL_SECONDS = 15.0


def coerce_last_event_id(value: str | int | None) -> int | None:
    """Parse a cursor from ``Last-Event-ID`` (or a query string).

    Anything that is not a non-negative integer means "no cursor" -- that is,
    send the timeline from the beginning. Refusing to guess matters: a cursor
    silently coerced to ``0`` would look like a valid resume point, and a
    client that reconnects with a garbage header would then receive a partial
    timeline while believing it was complete.
    """
    if value is None:
        return None
    if isinstance(value, bool):  # bool is an int subclass; never a cursor
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = int(text, 10)
    except ValueError:
        return None
    return parsed if parsed >= 0 else None


def select_after(
    events: Sequence[Mapping[str, Any]], after_id: int | None
) -> list[Mapping[str, Any]]:
    """Events strictly after ``after_id``, in the order the engine wrote them.

    Entries whose ``id`` is missing or not an ``int`` are dropped rather than
    fabricated -- an id-less event cannot be deduplicated by a client, and
    inventing one would break "same event id" across reconnects (PRD §16.3).

    ``after_id=None`` returns everything. This is the same rule
    ``replay_service.events_page`` applies, kept here so the polling path and
    the stream cannot drift apart.
    """
    known = [e for e in events if isinstance(e.get("id"), int)]
    if after_id is None:
        return known
    return [e for e in known if int(e["id"]) > after_id]


def split_page(
    selected: Sequence[Mapping[str, Any]], limit: int | None
) -> tuple[list[Mapping[str, Any]], bool]:
    """Take one page and report whether more remains.

    ``has_more`` is computed from the *pre-slice* length, so a caller that
    receives an exactly-full page still learns there is nothing behind it.
    """
    if limit is None:
        return list(selected), False
    page = list(selected[:limit])
    return page, len(selected) > len(page)


def heartbeat_frame() -> str:
    """An SSE comment line, used as the keep-alive tick.

    A comment is the correct shape here: it carries no event, so a client's
    ``onmessage`` never fires and no phantom event ends up in the timeline.
    """
    return ": keep-alive\n\n"


def sse_frame(*, event_id: int | None, event_type: str, data: Any) -> str:
    """Render one event in the TODO §8.2 wire format::

        id: 124
        event: iteration_complete
        data: {"node_id": "..."}

    Rules the frame keeps, each for a reason:

    * ``id:`` is omitted when the engine gave no id. Sending ``id: 0`` would
      tell the browser to resume from a cursor that never existed.
    * the payload is compact JSON on **one** line. A raw newline inside
      ``data:`` would terminate the frame early and the remainder would be
      parsed as a new field.
    * if the serialized payload somehow does contain a newline, it is split
      into repeated ``data:`` lines (the SSE spec's multi-line form) instead of
      being emitted raw.
    * the event name is flattened to a single token. A name is a fixed string
      from our own taxonomy, so a newline here means a bug or an injection
      attempt -- either way it must not be able to forge a frame boundary.
    * the frame ends with a blank line, which is what actually dispatches it.
    """
    lines: list[str] = []

    if event_id is not None:
        lines.append("id: %d" % event_id)

    lines.append("event: %s" % _event_name(event_type))
    lines.extend(_data_lines(serialize_payload(data)))

    return "\n".join(lines) + "\n\n"


def serialize_payload(data: Any) -> str:
    """Compact JSON for a payload.

    ``ensure_ascii=False`` keeps Chinese readable in the stream instead of
    turning it into escapes; ``default=str`` keeps one unserializable field
    from killing the whole stream mid-run.
    """
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"), default=str)


def _data_lines(payload: str) -> list[str]:
    """Serialized payload as one or more ``data:`` lines.

    ``json.dumps`` escapes newlines, so a well-formed payload is always a
    single line -- but the SSE spec defines the multi-line form for a reason,
    and emitting a raw newline here would end the frame early. Splitting keeps
    that impossible regardless of how the payload was produced.
    """
    return ["data: %s" % line.replace("\r", "") for line in payload.splitlines() or [""]]


def _event_name(value: str) -> str:
    """Reduce an event name to an identifier.

    Event names come from our own fixed taxonomy (``iteration_complete``,
    ``run_finished``, ...), so this is a no-op in practice. It exists because a
    name is the one field a caller could otherwise use to inject text into the
    frame: anything outside ``[A-Za-z0-9_.-]`` becomes ``_``, so no name can
    carry a newline, a colon, or a space into the stream.
    """
    text = str(value)
    cleaned = "".join(
        ch if (ch.isascii() and ch.isalnum()) or ch in "_.-" else "_" for ch in text
    )
    return cleaned.strip("_") or "unknown"
