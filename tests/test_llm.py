"""Tests for LLM gateway and mock LLM."""

from types import SimpleNamespace

import pytest

from faultevolve.cloud.llm import DashScopeLLM, MockLLM, create_llm_call_record
from faultevolve.common.metering import CallMetrics
from faultevolve.config import EvolveConfig


def test_mock_llm_default_response():
    """Test mock LLM returns default responses."""
    llm = MockLLM()

    response, metrics = llm.chat([{"role": "user", "content": "test"}])

    assert response is not None
    assert "<hypothesis>" in response
    assert "<intent>" in response
    assert "```python" in response
    assert metrics.prompt_tokens == 100
    assert metrics.completion_tokens == 200


def test_mock_llm_scripted_responses():
    """Test mock LLM with scripted responses."""
    llm = MockLLM()
    llm.set_responses([
        "Response 1",
        "Response 2",
        "Response 3",
    ])

    r1, _ = llm.chat([])
    assert r1 == "Response 1"

    r2, _ = llm.chat([])
    assert r2 == "Response 2"

    r3, _ = llm.chat([])
    assert r3 == "Response 3"

    r4, _ = llm.chat([])
    assert "Mock hypothesis" in r4


def test_mock_llm_increments_call_count():
    """Test that mock LLM increments call count."""
    llm = MockLLM(enable_repair_scenario=False)

    r1, _ = llm.chat([])
    r2, _ = llm.chat([])
    r3, _ = llm.chat([])

    assert "call 0" in r1
    assert "call 1" in r2
    assert "call 2" in r3


def test_mock_llm_reasoning():
    """Test mock LLM reasoning endpoint returns JSON reflection."""
    llm = MockLLM()
    response, metrics = llm.chat_for_reasoning([{"role": "user", "content": "analyze"}])

    assert response is not None
    assert "layer" in response or "json" in response.lower()
    assert metrics.prompt_tokens == 150
    assert metrics.completion_tokens == 100
    assert metrics.latency_ms == 40


def test_mock_llm_reasoning_scripted():
    """Test mock LLM reasoning with scripted responses."""
    llm = MockLLM()
    llm.set_reasoning_responses([
        '{"layer": "design", "change_summary": "test"}',
        '{"layer": "hypothesis", "change_summary": "test2"}',
    ])

    r1, _ = llm.chat_for_reasoning([])
    assert "design" in r1

    r2, _ = llm.chat_for_reasoning([])
    assert "hypothesis" in r2

    r3, _ = llm.chat_for_reasoning([])
    assert "layer" in r3


def test_create_llm_call_record():
    """Test creating LLM call records."""
    metrics = CallMetrics(
        prompt_tokens=1000,
        completion_tokens=500,
        latency_ms=2000,
        cached=False,
    )

    record = create_llm_call_record(
        experiment_id="exp-001",
        purpose="refine",
        model="test-model",
        metrics=metrics,
        node_id="node-001",
    )

    assert record.experiment_id == "exp-001"
    assert record.purpose == "refine"
    assert record.model == "test-model"
    assert record.prompt_tokens == 1000
    assert record.completion_tokens == 500
    assert record.node_id == "node-001"


def test_mock_llm_generates_valid_code():
    """Test that mock LLM generates syntactically valid code."""
    import ast

    llm = MockLLM()
    response, _ = llm.chat([])

    from faultevolve.common.codecheck import extract_code_from_response
    code = extract_code_from_response(response)

    assert code is not None
    ast.parse(code)


def test_dashscope_llm_streams_deltas_and_usage(monkeypatch):
    """Streaming mode joins content deltas and reads usage from the final chunk."""
    config = EvolveConfig()
    config.llm.stream = True
    llm = DashScopeLLM(config)

    chunks = [
        SimpleNamespace(
            choices=[SimpleNamespace(delta=SimpleNamespace(content="Hel"), finish_reason=None)],
            usage=None,
        ),
        SimpleNamespace(
            choices=[SimpleNamespace(delta=SimpleNamespace(content="lo"), finish_reason=None)],
            usage=None,
        ),
        SimpleNamespace(
            choices=[SimpleNamespace(delta=SimpleNamespace(content=""), finish_reason="stop")],
            usage=None,
        ),
        SimpleNamespace(
            choices=[],
            usage=SimpleNamespace(prompt_tokens=7, completion_tokens=2),
        ),
    ]
    calls = []

    class _FakeCompletions:
        def create(self, **kwargs):
            calls.append(kwargs)
            return iter(chunks)

    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=_FakeCompletions()))
    monkeypatch.setattr(llm, "_get_client", lambda: fake_client)

    text, metrics = llm.chat([{"role": "user", "content": "hi"}], temperature=0.7)

    assert text == "Hello"
    assert metrics.prompt_tokens == 7
    assert metrics.completion_tokens == 2
    assert metrics.cached is False
    assert calls[0]["stream"] is True
    assert calls[0]["stream_options"] == {"include_usage": True}
    assert calls[0]["model"] == config.llm.generate_model


def test_dashscope_llm_nonstream_still_used_by_default(monkeypatch):
    """Default config keeps the non-streaming call path."""
    config = EvolveConfig()
    assert config.llm.stream is False
    llm = DashScopeLLM(config)

    calls = []

    class _FakeCompletions:
        def create(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))],
                usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
            )

    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=_FakeCompletions()))
    monkeypatch.setattr(llm, "_get_client", lambda: fake_client)

    text, _ = llm.chat([{"role": "user", "content": "hi"}], temperature=0.7)

    assert text == "ok"
    assert "stream" not in calls[0]


def test_dashscope_llm_client_timeout_from_config(monkeypatch):
    """The OpenAI client is built with the configured read timeout."""
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")
    config = EvolveConfig()
    config.llm.timeout_s = 3600.0
    llm = DashScopeLLM(config)

    client = llm._get_client()

    assert client.timeout.read == 3600.0
    assert client.timeout.connect == 15.0
