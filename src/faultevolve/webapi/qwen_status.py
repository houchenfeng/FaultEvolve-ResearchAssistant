"""Live Qwen reachability check for the Web API.

The badge used to treat a non-empty ``DASHSCOPE_API_KEY`` as success. This
module asks the OpenAI-compatible ``/models`` endpoint and reports only
whether that call was accepted. The key never leaves the process.
"""
from __future__ import annotations

import hashlib
import os
import threading
import time

import httpx

from faultevolve.config import LLMConfig

_CACHE_TTL_S = 30.0
_TIMEOUT_S = 5.0
_lock = threading.Lock()
# (monotonic time, reachable, key fingerprint)
_cache: tuple[float, bool, str] | None = None


def qwen_base_url() -> str:
    """Endpoint the default LLM client would use, before a task yaml overrides it."""
    override = os.environ.get("DASHSCOPE_BASE_URL", "").strip()
    if override:
        return override.rstrip("/")
    return LLMConfig().base_url.rstrip("/")


def probe_qwen(*, client: httpx.Client | None = None) -> bool | None:
    """Return whether Qwen accepted the configured key.

    ``None`` means there is no key, so nothing was called. ``True`` means
    ``GET {base}/models`` returned 200. Any other outcome is ``False``.
    """
    key = os.environ.get("DASHSCOPE_API_KEY", "").strip()
    if not key:
        return None

    fingerprint = hashlib.sha256(key.encode()).hexdigest()
    if client is None:
        global _cache
        now = time.monotonic()
        with _lock:
            cached = _cache
        if cached is not None and cached[2] == fingerprint and now - cached[0] < _CACHE_TTL_S:
            return cached[1]

    reachable = _request(key, client)
    if client is None:
        with _lock:
            _cache = (time.monotonic(), reachable, fingerprint)
    return reachable


def _request(key: str, client: httpx.Client | None) -> bool:
    owns_client = client is None
    http = client or httpx.Client(timeout=_TIMEOUT_S)
    try:
        response = http.get(
            qwen_base_url() + "/models",
            headers={"Authorization": f"Bearer {key}"},
        )
    except httpx.HTTPError:
        return False
    finally:
        if owns_client:
            http.close()
    return response.status_code == 200
