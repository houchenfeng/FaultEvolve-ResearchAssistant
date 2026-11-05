"""Unit tests for the Qwen /models probe. No live network."""
from __future__ import annotations

import httpx

from faultevolve.webapi.qwen_status import probe_qwen, qwen_base_url


def test_missing_key_does_not_call(monkeypatch) -> None:
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)

    def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("request made without a key")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert probe_qwen(client=client) is None


def test_models_200_is_reachable(monkeypatch) -> None:
    secret = "sk-unit-test-key"
    monkeypatch.setenv("DASHSCOPE_API_KEY", secret)
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers["Authorization"])
        assert request.url.path.endswith("/models")
        return httpx.Response(200, json={"data": []})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert probe_qwen(client=client) is True
    assert seen == [f"Bearer {secret}"]


def test_models_401_is_not_reachable(monkeypatch) -> None:
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-unit-test-key")

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "invalid"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert probe_qwen(client=client) is False


def test_network_error_is_not_reachable(monkeypatch) -> None:
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-unit-test-key")

    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert probe_qwen(client=client) is False


def test_base_url_env_overrides_default(monkeypatch) -> None:
    monkeypatch.setenv(
        "DASHSCOPE_BASE_URL",
        "https://example.invalid/compatible-mode/v1/",
    )
    assert qwen_base_url() == "https://example.invalid/compatible-mode/v1"
