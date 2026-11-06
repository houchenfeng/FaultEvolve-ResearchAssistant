"""Hybrid mode: edge telemetry ingest, local GPU evaluation and the data boundary."""

from __future__ import annotations

import json
from typing import Any

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

from faultevolve.edge import gpu, paths
from faultevolve.edge.cloud import cloud_replay
from faultevolve.edge.hub import HUB


def register(app: FastAPI) -> None:
    @app.get("/api/edge/state", tags=["edge"])
    async def edge_state(request: Request) -> dict[str, Any]:
        snap = HUB.snapshot()
        port = request.url.port or 80
        ips = snap.pop("lan_ips")
        snap["endpoints"] = [f"ws://{ip}:{port}/api/edge/ws" for ip in ips]
        snap["tablet_urls"] = [f"http://{ip}:{port}/edge-tablet/" for ip in ips]
        return snap

    @app.get("/api/edge/gpu", tags=["edge"])
    async def edge_gpu() -> dict[str, Any]:
        return gpu.gpu_status()

    @app.get("/api/edge/cloud", tags=["edge"])
    async def edge_cloud() -> dict[str, Any]:
        return cloud_replay()

    @app.get("/api/edge/evaluation", tags=["edge"])
    async def edge_evaluation() -> dict[str, Any]:
        return HUB.evaluation

    @app.post("/api/edge/evaluate", tags=["edge"])
    async def edge_evaluate() -> dict[str, Any]:
        return {"started": HUB.start_evaluation(), "status": HUB.evaluation.get("status")}

    @app.post("/api/edge/models/prepare", tags=["edge"])
    async def edge_prepare() -> dict[str, Any]:
        HUB.models.ensure_started()
        return HUB.models.describe()

    @app.post("/api/edge/simulate", tags=["edge"])
    async def edge_simulate(day_seconds: float = 1.0) -> dict[str, Any]:
        return {"started": HUB.start_simulation(max(0.2, min(day_seconds, 5.0)))}

    @app.websocket("/api/edge/ws")
    async def edge_ws(ws: WebSocket) -> None:
        await ws.accept()
        client = ws.client.host if ws.client else "unknown"
        HUB.attach("边缘设备", client)
        try:
            while True:
                raw = await ws.receive_text()
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if msg.get("type") == "hello" and HUB.device is not None:
                    HUB.device["name"] = str(msg.get("device") or "边缘设备")
                for reply in await HUB.process(msg, len(raw.encode())):
                    await ws.send_text(json.dumps(reply, ensure_ascii=False))
        except WebSocketDisconnect:
            pass
        finally:
            HUB.detach()

    if paths.TABLET_DIST.is_dir():
        app.mount("/edge-tablet", StaticFiles(directory=paths.TABLET_DIST, html=True), name="edge-tablet")
