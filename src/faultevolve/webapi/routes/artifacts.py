"""Artifact listing, download and the report manifest (TODO §2.6).

Downloads are addressed by a *server-minted* id. The raw path is never accepted
as a parameter and never returned in a body: the route validates the id shape,
looks it up in a freshly built catalog, and only then hands the resolved path to
``FileResponse``. ``Content-Disposition`` carries the basename only.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse

from faultevolve.webapi import replay_service
from faultevolve.webapi.contracts import (
    ArtifactListResponse,
    ReportManifestResponse,
)
from faultevolve.webapi.settings import WebSettings


def _settings(request: Request) -> WebSettings:
    return request.app.state.settings


def register(app: FastAPI) -> None:
    """Attach the artifact and report endpoints."""

    @app.get(
        "/api/runs/{run_id}/artifacts",
        response_model=ArtifactListResponse,
        tags=["artifacts"],
        summary="制品清单",
    )
    async def list_artifacts(request: Request, run_id: str) -> ArtifactListResponse:
        """Everything that exists in the run directory, with a minted id each."""
        return replay_service.artifact_catalog(_settings(request), run_id)

    @app.get(
        "/api/runs/{run_id}/artifacts/{artifact_id}",
        tags=["artifacts"],
        summary="下载制品",
        response_class=FileResponse,
    )
    async def download_artifact(
        request: Request, run_id: str, artifact_id: str
    ) -> FileResponse:
        """Stream one artifact. Unknown ids 404; engine internals 403."""
        entry = replay_service.resolve_artifact(
            _settings(request), run_id, artifact_id
        )
        # ``filename`` is a basename: the resolved host path stays server-side.
        return FileResponse(
            path=entry.path,
            media_type=entry.media_type,
            filename=entry.display_name,
        )

    @app.get(
        "/api/runs/{run_id}/reports/manifest",
        response_model=ReportManifestResponse,
        tags=["artifacts"],
        summary="已导出报告清单",
    )
    async def get_report_manifest(
        request: Request, run_id: str
    ) -> ReportManifestResponse:
        """List report files that already exist. Never generates one."""
        return replay_service.report_manifest(_settings(request), run_id)
