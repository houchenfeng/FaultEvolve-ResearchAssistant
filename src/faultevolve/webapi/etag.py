"""Stable-artifact ETags (TODO §12.6).

Why this exists
---------------
§12.6 asks for "API 对同一稳定制品使用 ETag". Nothing in the service emitted
one: every replay GET returned a full body on every poll, and the UI polls
(run list, tree, events, live status) on an interval. Replaying a finished run
therefore re-shipped the same bytes over and over.

Why a middleware and not per-route headers
------------------------------------------
The ETag has to be derived from **the bytes actually returned**, otherwise it
goes stale the moment serialisation changes and a client caches a lie. Computing
it per route would mean every handler remembers to do it (and one forgetful
handler = a wrong ETag). Doing it once, on the way out, is the only place that
cannot drift from the body.

Semantics
---------
* **Strong** validator: identical bytes ⇒ identical representation, which is
  exactly what a byte hash proves.
* ``Cache-Control: no-cache`` is sent alongside. That means "you may store it,
  but must revalidate" — the 304 saves the body, not the request. Without it a
  browser could serve a stale replay from cache with no round trip at all,
  which would be wrong for a run that is still moving.
* Bodies are hashed, so a **live** run whose bytes changed simply gets a new
  ETag — no "stable only" allowlist is needed for correctness. The middleware
  still refuses to buffer two kinds of response it must not touch: SSE
  (``text/event-stream``, where holding the body back would stall the stream)
  and anything already streaming in chunks.
"""

from __future__ import annotations

import hashlib
from typing import Any

#: Response header names that must be dropped from a 304 (no body is sent).
_BODY_HEADERS = (b"content-length", b"content-type", b"content-encoding")

_STREAM_CONTENT_TYPES = (b"text/event-stream",)


def _get_header(headers: list[tuple[bytes, bytes]], name: bytes) -> bytes | None:
    for key, value in headers:
        if key.lower() == name:
            return value
    return None


def _set_header(headers: list[tuple[bytes, bytes]], name: bytes, value: bytes) -> None:
    """Replace ``name`` in place, or append it."""
    for index, (key, _value) in enumerate(headers):
        if key.lower() == name:
            headers[index] = (name, value)
            return
    headers.append((name, value))


def _is_streaming(headers: list[tuple[bytes, bytes]]) -> bool:
    content_type = _get_header(headers, b"content-type") or b""
    return any(marker in content_type for marker in _STREAM_CONTENT_TYPES)


def _matches(if_none_match: str, etag: str) -> bool:
    """``If-None-Match`` may carry ``*`` or a comma-separated list."""
    candidate = if_none_match.strip()
    if candidate == "*":
        return True
    for part in candidate.split(","):
        if part.strip().strip('"') == etag.strip('"'):
            return True
    return False


def compute_etag(body: bytes) -> str:
    """Strong validator over the exact bytes that will be sent."""
    return '"' + hashlib.sha256(body).hexdigest() + '"'


class ETagMiddleware:
    """Pure-ASGI middleware: hash the 200 body, answer 304 when it matches.

    Raw ASGI rather than ``BaseHTTPMiddleware`` on purpose: the latter rebuilds
    the response and is known to interact badly with streaming, and this one has
    to sit in front of the SSE endpoint without breaking it.
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        # HEAD is deliberately excluded: it sends no body, so hashing it would
        # produce a validator that contradicts the one the matching GET hands
        # out. A client that probes with HEAD first would then never get a 304.
        if scope.get("type") != "http" or scope.get("method") != "GET":
            await self.app(scope, receive, send)
            return
        if not str(scope.get("path", "")).startswith("/api/"):
            await self.app(scope, receive, send)
            return

        raw_inm = _get_header(list(scope.get("headers") or []), b"if-none-match")
        if_none_match = raw_inm.decode("latin-1") if raw_inm else None

        body = bytearray()
        started: dict[str, Any] = {}

        async def buffered_send(message: dict[str, Any]) -> None:
            kind = message["type"]

            if kind == "http.response.start":
                status = int(message["status"])
                headers = list(message.get("headers") or [])
                # 304/204 and friends carry no body worth hashing; SSE must
                # never be held back (the client is waiting on each chunk).
                if status != 200 or _is_streaming(headers):
                    started["passthrough"] = True
                    await send(message)
                    return
                started["status"] = status
                started["headers"] = headers
                return

            if kind != "http.response.body":
                await send(message)
                return

            if started.get("passthrough"):
                await send(message)
                return

            body.extend(message.get("body") or b"")
            if message.get("more_body"):
                return

            payload = bytes(body)
            etag = compute_etag(payload)
            headers = list(started.get("headers") or [])
            _set_header(headers, b"etag", etag.encode("latin-1"))
            _set_header(headers, b"cache-control", b"no-cache")

            if if_none_match and _matches(if_none_match, etag):
                trimmed = [
                    (key, value)
                    for key, value in headers
                    if key.lower() not in _BODY_HEADERS
                ]
                await send({"type": "http.response.start", "status": 304, "headers": trimmed})
                await send({"type": "http.response.body", "body": b"", "more_body": False})
                return

            _set_header(headers, b"content-length", str(len(payload)).encode("ascii"))
            await send(
                {
                    "type": "http.response.start",
                    "status": int(started.get("status", 200)),
                    "headers": headers,
                }
            )
            await send({"type": "http.response.body", "body": payload, "more_body": False})

        await self.app(scope, receive, buffered_send)
