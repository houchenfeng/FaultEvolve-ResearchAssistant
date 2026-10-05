"""Event timeline, score history and leaderboard (TODO §2.5)."""

from __future__ import annotations

from fastapi import FastAPI, Query, Request
from fastapi.responses import StreamingResponse

from faultevolve.webapi import replay_service, stream_service
from faultevolve.webapi.contracts import (
    EventPageResponse,
    ScoreboardEntryResponse,
    ScorePointResponse,
)
from faultevolve.webapi.event_stream import (
    SSE_HEADERS,
    SSE_MEDIA_TYPE,
    coerce_last_event_id,
)
from faultevolve.webapi.paths import validate_id
from faultevolve.webapi.settings import WebSettings

#: Page ceiling. A caller asking for everything still gets a bounded reply.
MAX_PAGE_SIZE = 2000


def _settings(request: Request) -> WebSettings:
    return request.app.state.settings


def register(app: FastAPI) -> None:
    """Attach the event, score and leaderboard endpoints."""

    @app.get(
        "/api/runs/{run_id}/events",
        response_model=EventPageResponse,
        tags=["events"],
        summary="按事件序号增量拉取事件",
    )
    async def get_events(
        request: Request,
        run_id: str,
        after_id: int | None = Query(default=None, ge=0),
        limit: int | None = Query(default=None, ge=1, le=MAX_PAGE_SIZE),
    ) -> EventPageResponse:
        """One page of ``events.jsonl``, keyed on the engine's own event ids.

        ``after_id`` is what makes reconnection work: the client sends the last
        id it saw and receives only what came after (PRD §16.3).
        """
        return replay_service.events_page(
            _settings(request), run_id, after_id=after_id, limit=limit
        )

    @app.get(
        "/api/runs/{run_id}/stream",
        tags=["events"],
        summary="SSE 实时事件流（阶段 8）",
        response_class=StreamingResponse,
    )
    async def stream_events(
        request: Request,
        run_id: str,
        after_id: int | None = Query(default=None, ge=0),
    ) -> StreamingResponse:
        """Server-sent events for one run, then a finite close.

        The cursor comes from ``?after_id=`` or from the ``Last-Event-ID`` header
        a reconnecting browser sends, and **the header wins**.

        That precedence is the whole reason the header exists. ``EventSource``
        reconnects to the *same URL*, so a stream opened as
        ``/stream?after_id=40`` comes back as ``?after_id=40`` **plus**
        ``Last-Event-ID: 57`` -- and 57 is the truth, because that is what the
        client actually received. Preferring the query string would re-deliver
        everything after 40 on every automatic reconnect, which PRD §16.3 names
        directly ("同一事件重复投递不会产生重复节点或重复轮次").

        Both go through the same ``coerce_last_event_id``, so the two paths
        cannot come to mean different things.

        No ``response_model`` on purpose: the body is a stream of frames, not a
        document, and declaring a model would make FastAPI try to validate -- and
        buffer -- an endless body.

        The stream is read-only, so like ``/live`` it needs no control flag.
        """
        validate_id(run_id, kind="run_id", field="run_id")
        cursor = coerce_last_event_id(
            request.headers.get("last-event-id")
            if request.headers.get("last-event-id") is not None
            else after_id
        )
        return StreamingResponse(
            stream_service.stream_run_events(_settings(request), run_id, after_id=cursor),
            media_type=SSE_MEDIA_TYPE,
            headers=SSE_HEADERS,
        )

    @app.get(
        "/api/runs/{run_id}/scores",
        response_model=list[ScorePointResponse],
        tags=["events"],
        summary="分数时间线",
    )
    async def get_scores(request: Request, run_id: str) -> list[ScorePointResponse]:
        """One point per evaluated node, straight from the evaluator's record."""
        return replay_service.score_points(_settings(request), run_id)

    @app.get(
        "/api/runs/{run_id}/leaderboard",
        response_model=list[ScoreboardEntryResponse],
        tags=["events"],
        summary="排行榜",
    )
    async def get_leaderboard(
        request: Request, run_id: str
    ) -> list[ScoreboardEntryResponse]:
        """Nodes ranked by score, with unscored nodes sorted last."""
        return replay_service.leaderboard(_settings(request), run_id)
