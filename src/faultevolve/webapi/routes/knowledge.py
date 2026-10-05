"""Knowledge cards, insights and discovery artifacts (TODO §2.6)."""

from __future__ import annotations

from fastapi import FastAPI, Request

from faultevolve.webapi import replay_service
from faultevolve.webapi.contracts import (
    DiscoveryResponse,
    InsightsResponse,
    KnowledgeCardResponse,
)
from faultevolve.webapi.settings import WebSettings


def _settings(request: Request) -> WebSettings:
    return request.app.state.settings


def register(app: FastAPI) -> None:
    """Attach the knowledge / insights / discovery endpoints."""

    @app.get(
        "/api/runs/{run_id}/knowledge/cards",
        response_model=list[KnowledgeCardResponse],
        tags=["knowledge"],
        summary="知识卡与运行中的采用统计",
    )
    async def get_knowledge_cards(
        request: Request, run_id: str
    ) -> list[KnowledgeCardResponse]:
        """One entry per card the run offered, with how it fared."""
        return replay_service.knowledge_cards(_settings(request), run_id)

    @app.get(
        "/api/runs/{run_id}/insights",
        response_model=InsightsResponse,
        tags=["knowledge"],
        summary="反思洞见",
    )
    async def get_insights(request: Request, run_id: str) -> InsightsResponse:
        """Insights, with an explicit ``available`` flag for the empty case."""
        return replay_service.insights(_settings(request), run_id)

    @app.get(
        "/api/runs/{run_id}/discovery",
        response_model=DiscoveryResponse,
        tags=["knowledge"],
        summary="知识发现产物",
    )
    async def get_discovery(request: Request, run_id: str) -> DiscoveryResponse:
        """Discovery artifacts, each with its own availability state."""
        return replay_service.discovery(_settings(request), run_id)
