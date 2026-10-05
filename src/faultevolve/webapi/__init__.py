"""Thin Web API layer over the FaultEvolve engine.

Layering rules:

* this package reads the engine; the engine never imports it;
* the front-end sees only :mod:`faultevolve.webapi.contracts` DTOs;
* scores come from the task evaluator and are only ever read back here.

See docs/plans/FRONTEND_IMPLEMENTATION_TODO.md and docs/plans/WEBUI_BASELINE.md.
"""

from __future__ import annotations

from faultevolve.webapi.app import create_app
from faultevolve.webapi.contracts import CONTRACT_VERSION
from faultevolve.webapi.settings import WebSettings

__all__ = ["CONTRACT_VERSION", "WebSettings", "create_app"]
