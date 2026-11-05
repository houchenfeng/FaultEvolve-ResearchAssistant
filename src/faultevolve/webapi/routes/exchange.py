"""Cross-island exchange summaries (TODO D6.3).

Read-only: the three exchange tables are what the engine wrote, and the only
capability offered is "what did island *b* publish, whom was it delivered to, and
which candidates were built with it". No endpoint here returns a source file path
or the body of a foreign island's program.
"""

from __future__ import annotations

from fastapi import FastAPI, Request

from faultevolve.webapi import replay_service
from faultevolve.webapi.contracts import RunSummariesResponse, SummaryDetailResponse
from faultevolve.webapi.settings import WebSettings


def _settings(request: Request) -> WebSettings:
    return request.app.state.settings


def register(app: FastAPI) -> None:
    """Attach the exchange endpoints."""

    @app.get(
        "/api/runs/{run_id}/summaries",
        response_model=RunSummariesResponse,
        tags=["exchange"],
        summary="本运行的跨岛摘要",
    )
    async def get_summaries(request: Request, run_id: str) -> RunSummariesResponse:
        """Every published summary with its deliveries and applications.

        A run without an exchange layer answers ``missing`` with a reason instead
        of an empty list that would look like "three islands, nothing exchanged".
        """
        return replay_service.summaries(_settings(request), run_id)

    @app.get(
        "/api/runs/{run_id}/summaries/{summary_id}",
        response_model=SummaryDetailResponse,
        tags=["exchange"],
        summary="单条摘要的投递与采用记录",
    )
    async def get_summary(
        request: Request, run_id: str, summary_id: str
    ) -> SummaryDetailResponse:
        """One summary. An unknown id is a structured ``missing``, not a 500."""
        return replay_service.summary_detail(_settings(request), run_id, summary_id)
