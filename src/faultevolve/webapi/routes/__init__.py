"""Route modules of the Web API.

Each module exposes ``register(app)`` and owns one slice of the surface, so
``app.create_app`` stays a wiring list rather than a thousand-line function.
"""

from __future__ import annotations

from fastapi import FastAPI

from faultevolve.webapi.routes import (
    artifacts,
    events,
    knowledge,
    presets,
    runs,
    servers,
    tasks,
    tree,
)

__all__ = ["register_all"]


def register_all(app: FastAPI) -> None:
    """Attach every route group to ``app``."""
    runs.register(app)
    tree.register(app)
    events.register(app)
    knowledge.register(app)
    artifacts.register(app)
    tasks.register(app)
    servers.register(app)
    presets.register(app)
