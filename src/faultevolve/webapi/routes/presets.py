"""Evolution-strength preset endpoints (TODO 4.6)."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI

from faultevolve.webapi import presets
from faultevolve.webapi.contracts import PresetListResponse, PresetResponse


def register(app: FastAPI) -> None:
    """Attach ``/api/presets`` endpoints."""

    @app.get(
        "/api/presets",
        response_model=PresetListResponse,
        tags=["presets"],
        summary="列出三档进化强度预设",
    )
    async def list_presets() -> PresetListResponse:
        """Each preset is a complete, already-validated ``EvolveConfig``."""
        return presets.list_presets()

    @app.get(
        "/api/presets/{name}",
        response_model=PresetResponse,
        tags=["presets"],
        summary="读取单档预设",
    )
    async def get_preset(name: str) -> PresetResponse:
        return presets.build_preset(name)

    @app.post(
        "/api/presets/{name}/merge",
        response_model=PresetResponse,
        tags=["presets"],
        summary="把用户 patch 合并到预设并重新校验",
    )
    async def merge_preset(name: str, body: dict[str, Any]) -> PresetResponse:
        """Merge, re-validate, and report per-field provenance.

        The body is the raw ``config_patch`` object (``{"budget":
        {"max_iterations": 3}}``). Phase 7's run-creation endpoint will send
        the same patch inside ``RunCreateRequest``; validating the merge
        semantics here means that endpoint cannot discover them late.
        """
        return presets.merge_patch(name, dict(body))
