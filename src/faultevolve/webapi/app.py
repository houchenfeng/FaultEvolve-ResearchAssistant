"""FastAPI application factory for the FaultEvolve Web API.

Phase 1 ships the shell only: ``/api/health`` and ``/api/meta``. It exists now
because the contract export script needs ``create_app().openapi()`` to produce
``web/openapi/faultevolve.openapi.json``.

Invariants (TODO §2.1):
* no background thread is started at import;
* no environment secret is read at import;
* tests can inject temporary roots through ``WebSettings``;
* error responses are uniform and never leak paths, keys or stack details.
"""

from __future__ import annotations

import os
from importlib import metadata
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from faultevolve.webapi.catalog import (
    DEPLOYMENT_MODES,
    ENGINE_RUN_STATUSES,  # re-exported for callers that build /api/meta extras
    NAV_MODULES,
    STREAM_TRANSPORT,
    UNAVAILABLE_DEPLOYMENT_MODES,
)
from faultevolve.webapi.contracts import (
    CONTRACT_MODELS,
    CONTRACT_VERSION,
    ApiErrorResponse,
    DeploymentMode,
    DeploymentModeAvailability,
    HealthResponse,
    MetaResponse,
    QwenConfigRequest,
    QwenConfigResponse,
)
from faultevolve.webapi.errors import ErrorCode, InvalidQwenConfigError, WebApiError
from faultevolve.webapi.etag import ETagMiddleware
from faultevolve.webapi.routes import register_all
from faultevolve.webapi.settings import PathNotAllowedError, WebSettings

#: Environment variable that may carry the engine commit, if the deployment
#: knows it. Read lazily inside ``create_app``, never at import time.
ENGINE_COMMIT_ENV = "FAULTEVOLVE_ENGINE_COMMIT"


def _engine_version() -> str:
    try:
        return metadata.version("faultevolve")
    except metadata.PackageNotFoundError:  # pragma: no cover - editable installs vary
        return "0.0.0+unknown"


def _qwen_configured() -> bool:
    """Whether a Qwen key is present. The value is never returned."""
    return bool(os.environ.get("DASHSCOPE_API_KEY", "").strip())


def _qwen_reachable() -> bool | None:
    """Probe Qwen only when a key exists. Never returns the key."""
    if not _qwen_configured():
        return None
    from faultevolve.webapi import qwen_status

    return qwen_status.probe_qwen()


def _error_response(
    status_code: int,
    code: ErrorCode,
    message: str,
    *,
    detail: str | None = None,
    field: str | None = None,
) -> JSONResponse:
    body = ApiErrorResponse(
        error_code=code.value, message=message, detail=detail, field=field
    )
    return JSONResponse(status_code=status_code, content=body.model_dump())


def _install_contract_schemas(app: FastAPI) -> None:
    """Publish every DTO into ``components/schemas``.

    FastAPI only emits types a route references. That would hide all the DTOs
    whose endpoints land in later phases, leaving the front-end to hand-declare
    them -- which TODO §1.5 forbids and which would also make the drift check
    blind to them. Merging them here keeps the contract complete from day one.

    Pydantic returns nested models under ``$defs``; those are lifted into the
    same component namespace so ``#/components/schemas/...`` refs resolve.
    """
    default_openapi = app.openapi

    def custom_openapi() -> dict[str, Any]:
        if app.openapi_schema is not None:
            return app.openapi_schema
        schema = get_openapi(
            title=app.title,
            version=app.version,
            description=app.description,
            routes=app.routes,
        )
        components = schema.setdefault("components", {}).setdefault("schemas", {})
        for model in CONTRACT_MODELS:
            raw = model.model_json_schema(
                ref_template="#/components/schemas/{model}"
            )
            for name, definition in raw.pop("$defs", {}).items():
                # setdefault: an identical nested model may be shared by several
                # DTOs, and the first definition wins.
                components.setdefault(name, definition)
            components[model.__name__] = raw
        app.openapi_schema = schema
        return schema

    app.openapi = custom_openapi  # type: ignore[method-assign]


def create_app(settings: WebSettings | None = None) -> FastAPI:
    """Build the application.

    Args:
        settings: injected configuration. Defaults to an empty ``WebSettings``,
            which reaches no filesystem path at all.
    """
    resolved = settings if settings is not None else WebSettings()
    engine_commit = os.environ.get(ENGINE_COMMIT_ENV)

    app = FastAPI(
        title="FaultEvolve Web API",
        version=CONTRACT_VERSION,
        description=(
            "Read-only control and replay surface for the FaultEvolve engine. "
            "Scores are produced by the task evaluator and only ever read back here."
        ),
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )
    app.state.settings = resolved

    # --------------------------------------------------------------- caching
    # Installed here (not in the route layer) so no handler can forget it, and
    # so the validator is always derived from the bytes actually sent. See
    # ``etag.py`` for why SSE and non-200s are passed straight through.
    app.add_middleware(ETagMiddleware)

    # ---------------------------------------------------------------- errors
    @app.exception_handler(WebApiError)
    async def _handle_webapi_error(
        request: Request, exc: WebApiError
    ) -> JSONResponse:
        """Single mapping point for every domain error.

        The status and code travel on the exception, so no route has to build a
        reply and no message can be assembled from user input.
        """
        return _error_response(
            exc.http_status, exc.error_code, exc.message_zh, detail=exc.detail,
            field=getattr(exc, "field", None),
        )

    @app.exception_handler(PathNotAllowedError)
    async def _handle_path_not_allowed(
        request: Request, exc: PathNotAllowedError
    ) -> JSONResponse:
        return _error_response(
            403,
            ErrorCode.PATH_NOT_ALLOWED,
            "该路径不在允许访问的范围内",
        )

    @app.exception_handler(RequestValidationError)
    async def _handle_validation(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else {}
        location = [str(part) for part in first.get("loc", []) if part != "body"]
        return _error_response(
            422,
            ErrorCode.INVALID_REQUEST,
            "请求参数不合法",
            detail=first.get("msg"),
            field=".".join(location) or None,
        )

    @app.exception_handler(StarletteHTTPException)
    async def _handle_http(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        """Framework-level errors (unmatched route, wrong method).

        The framework's own ``detail`` is English and occasionally echoes the
        requested path, so it is discarded: the body is built from the status
        code alone.
        """
        code = ErrorCode.NOT_FOUND
        message = "没有这个接口"
        if exc.status_code == 405:
            code = ErrorCode.METHOD_NOT_ALLOWED
            message = "该接口不支持这个请求方法"
        elif exc.status_code >= 500:
            code = ErrorCode.INTERNAL
            message = "服务内部错误"
        return _error_response(exc.status_code, code, message)

    @app.exception_handler(Exception)
    async def _handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        # No detail in the body: it could contain a host path or a key fragment.
        return _error_response(500, ErrorCode.INTERNAL, "服务内部错误")

    # ---------------------------------------------------------------- routes
    @app.get("/api/health", response_model=HealthResponse, tags=["meta"])
    async def health() -> HealthResponse:
        """Liveness probe. Says nothing about the environment."""
        return HealthResponse(status="ok", contract_version=CONTRACT_VERSION)

    @app.get("/api/meta", response_model=MetaResponse, tags=["meta"])
    async def meta() -> MetaResponse:
        """Static capability description the UI reads once at start-up."""
        # Availability is read off what actually exists, not off a wish list:
        # local_cloud is delivered (phase 4), ssh_cloud additionally requires
        # asyncssh to import. Reporting anything else would be the first fake
        # feature in the project (PRD 2.3).
        from faultevolve.webapi import presets as presets_module
        from faultevolve.webapi import run_registry
        from faultevolve.webapi import server_profiles
        from faultevolve.webapi import task_service

        ssh_ok = server_profiles.ssh_available()
        availability: list[DeploymentModeAvailability] = []
        for mode in DEPLOYMENT_MODES:
            if mode is DeploymentMode.LOCAL_CLOUD:
                availability.append(
                    DeploymentModeAvailability(
                        mode=mode,
                        available=True,
                        supported_transports=[mode],
                        detail="本机/同机云端执行目标可用",
                    )
                )
            elif mode is DeploymentMode.SSH_CLOUD:
                availability.append(
                    DeploymentModeAvailability(
                        mode=mode,
                        available=ssh_ok,
                        supported_transports=[mode] if ssh_ok else [],
                        detail=(
                            "SSH 云端执行目标可用"
                            if ssh_ok
                            else "asyncssh 不可用：SSH 云端目标未启用"
                        ),
                    )
                )
        for mode in UNAVAILABLE_DEPLOYMENT_MODES:
            availability.append(
                DeploymentModeAvailability(
                    mode=mode,
                    available=False,
                    supported_transports=[],
                    detail="P0 不提供该模式",
                )
            )
        return MetaResponse(
            contract_version=CONTRACT_VERSION,
            engine_version=_engine_version(),
            engine_commit=engine_commit,
            deployment_modes=availability,
            default_deployment_mode=DeploymentMode.LOCAL_CLOUD,
            nav_modules=list(NAV_MODULES),
            stream_transport=STREAM_TRANSPORT,
            process_control_enabled=resolved.enable_process_control,
            auth_required=resolved.token_required(),
            demo_run_ids=list(resolved.demo_run_ids),
            task_catalog_available=task_service.task_catalog_available(resolved),
            preset_names=list(presets_module.PRESET_NAMES),
            server_profiles_enabled=server_profiles.store_configured(resolved),
            run_registry_configured=run_registry.registry_configured(resolved),
            qwen_configured=_qwen_configured(),
            qwen_reachable=_qwen_reachable(),
        )

    @app.get("/api/qwen/config", response_model=QwenConfigResponse, tags=["meta"])
    async def get_qwen_config() -> QwenConfigResponse:
        from faultevolve.webapi.qwen_status import qwen_base_url

        return QwenConfigResponse(
            base_url=qwen_base_url(),
            configured=_qwen_configured(),
            reachable=_qwen_reachable(),
        )

    @app.post("/api/qwen/config", response_model=QwenConfigResponse, tags=["meta"])
    async def update_qwen_config(body: QwenConfigRequest) -> QwenConfigResponse:
        from faultevolve.webapi.qwen_status import qwen_base_url

        base_url = body.base_url.strip().rstrip("/")
        if not base_url.startswith(("https://", "http://")):
            raise InvalidQwenConfigError(field="base_url")
        os.environ["DASHSCOPE_BASE_URL"] = base_url
        return QwenConfigResponse(
            base_url=qwen_base_url(),
            configured=_qwen_configured(),
            reachable=_qwen_reachable(),
        )

    # ------------------------------------------------------------- run replay
    register_all(app)

    _install_contract_schemas(app)
    return app


__all__ = ["create_app", "ENGINE_COMMIT_ENV", "ENGINE_RUN_STATUSES"]
