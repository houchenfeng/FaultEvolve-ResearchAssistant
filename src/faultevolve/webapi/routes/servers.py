"""Execution-target endpoints (TODO 4.3 / 4.4)."""

from __future__ import annotations

from fastapi import FastAPI, Request

from faultevolve.webapi import server_profiles
from faultevolve.webapi.contracts import (
    PathProbeRequest,
    PathProbeResponse,
    ServerProfileListResponse,
    ServerProfileRequest,
    ServerProfileResponse,
    ServerProbeResponse,
)
from faultevolve.webapi.errors import CapabilityNotSupportedError
from faultevolve.webapi.execution_backend import (
    LocalCloudExecutionBackend,
    SSHCloudExecutionBackend,
)
from faultevolve.webapi.settings import WebSettings


def _settings(request: Request) -> WebSettings:
    return request.app.state.settings


def _require_store(settings: WebSettings) -> None:
    if not server_profiles.store_configured(settings):
        raise CapabilityNotSupportedError(
            "未配置服务器配置存储（FE_WEB_SERVER_PROFILE_STORE）"
        )


def register(app: FastAPI) -> None:
    """Attach ``/api/servers`` endpoints."""

    @app.get(
        "/api/servers",
        response_model=ServerProfileListResponse,
        tags=["servers"],
        summary="列出服务器配置",
    )
    async def list_servers(request: Request) -> ServerProfileListResponse:
        """Masked profiles plus the default one to preselect (plan D-E)."""
        _require_store(_settings(request))
        return server_profiles.list_profiles(_settings(request))

    @app.post(
        "/api/servers",
        response_model=ServerProfileResponse,
        tags=["servers"],
        summary="新建或更新服务器配置",
    )
    async def upsert_server(
        request: Request, body: ServerProfileRequest, profile_id: str | None = None
    ) -> ServerProfileResponse:
        """Secrets never travel: only a ``private_key_ref`` is accepted."""
        settings = _settings(request)
        _require_store(settings)
        return server_profiles.upsert_profile(settings, body, profile_id)

    @app.get(
        "/api/servers/{profile_id}",
        response_model=ServerProfileResponse,
        tags=["servers"],
        summary="读取单个服务器配置",
    )
    async def get_server(request: Request, profile_id: str) -> ServerProfileResponse:
        _require_store(_settings(request))
        return server_profiles.get_profile(_settings(request), profile_id)

    @app.delete(
        "/api/servers/{profile_id}",
        status_code=204,
        tags=["servers"],
        summary="删除服务器配置",
    )
    async def delete_server(request: Request, profile_id: str) -> None:
        _require_store(_settings(request))
        server_profiles.delete_profile(_settings(request), profile_id)

    @app.post(
        "/api/servers/{profile_id}/probe",
        response_model=ServerProbeResponse,
        tags=["servers"],
        summary="测试连接",
    )
    async def probe_server(request: Request, profile_id: str) -> ServerProbeResponse:
        """Reachability + environment report (PRD 7.4 交互规则 2)."""
        settings = _settings(request)
        _require_store(settings)
        record = server_profiles.require_record(settings, profile_id)

        if record.get("mode") == "ssh_cloud":
            backend = SSHCloudExecutionBackend(settings, record)
            probe = await backend.probe()
            paths = []
        else:
            backend = LocalCloudExecutionBackend(settings)
            probe = await backend.probe()
            paths = []
        return ServerProbeResponse(
            profile_id=profile_id,
            mode=record.get("mode") or "local_cloud",
            reachable=probe.reachable,
            latency_ms=probe.latency_ms,
            engine_installed=probe.engine_installed,
            engine_version=probe.engine_version,
            python_version=probe.python_version,
            gpu_summary=probe.gpu_summary,
            paths=paths,
            llm_key_present=probe.llm_key_present,
            detail=probe.detail,
        )

    @app.post(
        "/api/servers/{profile_id}/check-path",
        response_model=PathProbeResponse,
        tags=["servers"],
        summary="测试目录",
    )
    async def check_path(
        request: Request, profile_id: str, body: PathProbeRequest
    ) -> PathProbeResponse:
        """Existence / writability / free space for one directory.

        The path is checked against the allow-list before anything is
        stat'ed, locally and remotely alike.
        """
        settings = _settings(request)
        _require_store(settings)
        record = server_profiles.require_record(settings, profile_id)

        if record.get("mode") == "ssh_cloud":
            backend = SSHCloudExecutionBackend(settings, record)
        else:
            backend = LocalCloudExecutionBackend(settings)
        probe = await backend.check_path(body.path)

        detail = probe.detail
        if probe.free_gb is not None:
            detail = (detail + "; " if detail else "") + f"剩余 {probe.free_gb} GB"
        return PathProbeResponse(
            path=probe.path,
            exists=probe.exists,
            is_directory=probe.is_directory,
            writable=probe.writable,
            detail=detail,
        )
