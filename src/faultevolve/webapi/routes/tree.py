"""Evolution tree and node detail (TODO §2.5)."""

from __future__ import annotations

from fastapi import FastAPI, Request

from faultevolve.webapi import replay_service
from faultevolve.webapi.contracts import NodeDetailResponse, TreeResponse
from faultevolve.webapi.settings import WebSettings


def _settings(request: Request) -> WebSettings:
    return request.app.state.settings


def register(app: FastAPI) -> None:
    """Attach the tree and node endpoints."""

    @app.get(
        "/api/runs/{run_id}/tree",
        response_model=TreeResponse,
        tags=["tree"],
        summary="整棵进化树",
    )
    async def get_tree(request: Request, run_id: str) -> TreeResponse:
        """Nodes, edges and the best path.

        Parent links are joined onto each node because ``tree.json`` stores them
        as a separate edge list; the database's own ``parent_id`` wins when the
        two disagree, and the disagreement is reported.
        """
        return replay_service.tree(_settings(request), run_id)

    @app.get(
        "/api/runs/{run_id}/nodes/{node_id}",
        response_model=NodeDetailResponse,
        tags=["tree"],
        summary="单个节点的详情",
    )
    async def get_node(request: Request, run_id: str, node_id: str) -> NodeDetailResponse:
        """Code, evaluation, insights and a sanitized log excerpt."""
        return replay_service.node_detail(_settings(request), run_id, node_id)
