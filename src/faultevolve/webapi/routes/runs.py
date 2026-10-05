"""Run discovery, run detail and the run lifecycle (TODO §2.4 / §10).

Read side and write side live in one module because they are one resource: the
same run id names both a replayable artifact directory and a process the service
started. Splitting them would mean two places to look when the two disagree --
and they *can* disagree (a directory with no registry row), which is exactly why
``/live`` reports ``registered`` explicitly.

Every write endpoint refuses with ``not_supported`` when process control is off.
The default is off, so a mis-click cannot start a process on a fresh deployment.
"""

from __future__ import annotations

from fastapi import FastAPI, Request

from faultevolve.webapi import replay_service, run_control
from faultevolve.webapi.contracts import (
    AppendRoundsRequest,
    RunControlResponse,
    RunCreateRequest,
    RunCreateResponse,
    RunDetailResponse,
    RunLiveResponse,
    RunSummaryResponse,
)
from faultevolve.webapi.paths import validate_id
from faultevolve.webapi.settings import WebSettings


def _settings(request: Request) -> WebSettings:
    return request.app.state.settings


def register(app: FastAPI) -> None:
    """Attach ``/api/runs`` endpoints."""

    @app.get(
        "/api/runs",
        response_model=list[RunSummaryResponse],
        tags=["runs"],
        summary="列出可回放的运行",
    )
    async def list_runs(request: Request) -> list[RunSummaryResponse]:
        """Every run directory one level below the configured roots.

        An unreadable run still appears, marked ``unreadable``: hiding it would
        make a broken run look like a run that never existed.
        """
        return replay_service.list_runs(_settings(request))

    @app.post(
        "/api/runs",
        response_model=RunCreateResponse,
        status_code=202,
        tags=["runs"],
        summary="创建并启动一次运行",
    )
    async def create_run(
        request: Request, body: RunCreateRequest
    ) -> RunCreateResponse:
        """TODO 7.3: validate -> resolve paths -> readiness -> spawn -> 202.

        ``202`` rather than ``201``: the run has been accepted and a process is
        running, but nothing is finished. The body carries the id the UI then
        polls ``/live`` with.
        """
        return await run_control.start_run(_settings(request), body)

    @app.get(
        "/api/runs/{run_id}",
        response_model=RunDetailResponse,
        tags=["runs"],
        summary="读取单个运行的详情",
    )
    async def get_run(request: Request, run_id: str) -> RunDetailResponse:
        """Grouped view. Each group is ``null`` when its artifact is unreadable."""
        return replay_service.run_detail(_settings(request), run_id)

    @app.get(
        "/api/runs/{run_id}/live",
        response_model=RunLiveResponse,
        tags=["runs"],
        summary="读取运行的进程态摘要",
    )
    async def get_run_live(request: Request, run_id: str) -> RunLiveResponse:
        """Process state, not artifacts. Read-only, so it needs no control flag."""
        validate_id(run_id, kind="run_id", field="run_id")
        return await run_control.live_state(_settings(request), run_id)

    @app.post(
        "/api/runs/{run_id}/cancel",
        response_model=RunControlResponse,
        tags=["runs"],
        summary="取消运行（保留已有制品）",
    )
    async def cancel_run(request: Request, run_id: str) -> RunControlResponse:
        """TODO test #13: stopping a run never deletes what it produced."""
        validate_id(run_id, kind="run_id", field="run_id")
        return await run_control.cancel_run(_settings(request), run_id)

    @app.post(
        "/api/runs/{run_id}/pause",
        response_model=RunControlResponse,
        tags=["runs"],
        summary="暂停运行（本版本不支持）",
    )
    async def pause_run(request: Request, run_id: str) -> RunControlResponse:
        """Always ``409`` with a reason. The engine has no safe pause point.

        Declared rather than omitted so the UI has a stable answer to render:
        a 404 would read as "wrong URL", which is not what is happening.
        """
        validate_id(run_id, kind="run_id", field="run_id")
        return await run_control.pause_run(_settings(request), run_id)

    @app.post(
        "/api/runs/{run_id}/resume",
        response_model=RunCreateResponse,
        tags=["runs"],
        summary="从已有运行恢复",
    )
    async def resume_run(request: Request, run_id: str) -> RunCreateResponse:
        """Continue the same experiment under the same id (``--resume``)."""
        validate_id(run_id, kind="run_id", field="run_id")
        return await run_control.resume_run(_settings(request), run_id)

    @app.post(
        "/api/runs/{run_id}/rounds",
        response_model=RunControlResponse,
        tags=["runs"],
        summary="追加进化轮次",
    )
    async def append_rounds(
        request: Request, run_id: str, body: AppendRoundsRequest
    ) -> RunControlResponse:
        """PRD §16.1. ``additional_iterations`` is a delta, not a new total."""
        validate_id(run_id, kind="run_id", field="run_id")
        return await run_control.append_rounds(_settings(request), run_id, body)
