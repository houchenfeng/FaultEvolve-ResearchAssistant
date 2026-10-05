"""Task catalogue endpoints (TODO 4.1 / 4.2)."""

from __future__ import annotations

from fastapi import FastAPI, Request

from faultevolve.webapi import task_service
from faultevolve.webapi.contracts import (
    TaskDatasetCardResponse,
    TaskDetailResponse,
    TaskReadinessResponse,
    TaskSummaryResponse,
)
from faultevolve.webapi.settings import WebSettings


def _settings(request: Request) -> WebSettings:
    return request.app.state.settings


def register(app: FastAPI) -> None:
    """Attach ``/api/tasks`` endpoints."""

    @app.get(
        "/api/tasks",
        response_model=list[TaskSummaryResponse],
        tags=["tasks"],
        summary="列出任务目录中的任务",
    )
    async def list_tasks(request: Request) -> list[TaskSummaryResponse]:
        """Every task directory one level below the configured task roots.

        Stub datasets (no four-file set) are listed too, marked ``is_stub``:
        PRD 7.7 wants the card visible with a reason, not hidden.
        """
        settings = _settings(request)
        return [
            task_service.task_summary(settings, task_dir)
            for task_dir in task_service.list_task_dirs(settings)
        ]

    @app.get(
        "/api/tasks/{task_id}",
        response_model=TaskDetailResponse,
        tags=["tasks"],
        summary="读取单个任务的详情",
    )
    async def get_task(request: Request, task_id: str) -> TaskDetailResponse:
        """Sanitised problem/prompt documents plus file and data listings."""
        settings = _settings(request)
        task_dir = task_service.resolve_task_dir(settings, task_id)
        return task_service.task_detail(settings, task_dir)

    @app.get(
        "/api/tasks/{task_id}/readiness",
        response_model=TaskReadinessResponse,
        tags=["tasks"],
        summary="任务就绪检查",
    )
    async def get_task_readiness(
        request: Request, task_id: str
    ) -> TaskReadinessResponse:
        """Pre-flight check. ``checks`` lists blocking problems only."""
        settings = _settings(request)
        task_dir = task_service.resolve_task_dir(settings, task_id)
        return task_service.task_readiness(settings, task_dir)

    @app.get(
        "/api/tasks/{task_id}/card",
        response_model=TaskDatasetCardResponse,
        tags=["tasks"],
        summary="读取单个任务的总览卡片",
    )
    async def get_task_card(
        request: Request, task_id: str
    ) -> TaskDatasetCardResponse:
        """The overview card (PRD 7.7): one request, no client-side joins."""
        settings = _settings(request)
        task_dir = task_service.resolve_task_dir(settings, task_id)
        return task_service.task_card(settings, task_dir)
