"""Live metering stays observable without retaining request or response text."""

import json
import threading
from types import SimpleNamespace as NS

import pytest

from faultevolve.cloud.llm import DashScopeLLM
from faultevolve.common.llm_progress import CallProgress, ProgressHub
from faultevolve.config import EvolveConfig


def chunk(content=None, reasoning=None, usage=None):
    return NS(id="provider-request", usage=usage,
              choices=[NS(delta=NS(content=content, reasoning_content=reasoning), finish_reason=None)])


def test_live_stream_reports_reasoning_then_content_and_exact_usage_without_text(tmp_path, monkeypatch):
    monkeypatch.setenv("FE_LLM_PROGRESS_DIR", str(tmp_path))
    config = EvolveConfig()
    config.llm.stream = True
    llm = DashScopeLLM(config)
    states = []

    def stream():
        yield chunk(reasoning="private reasoning")
        states.append(json.loads((tmp_path / "live.json").read_text()))
        yield chunk(content="private generated code")
        states.append(json.loads((tmp_path / "live.json").read_text()))
        yield chunk(usage=NS(prompt_tokens=12, completion_tokens=9,
                             completion_tokens_details=NS(reasoning_tokens=4)))

    monkeypatch.setattr(llm, "_get_client", lambda: NS(chat=NS(completions=NS(create=lambda **k: stream()))))
    text, metrics = llm.chat([{"role": "user", "content": "private prompt"}])
    assert text == "private generated code"
    assert metrics.prompt_tokens == 12 and metrics.completion_tokens == 9
    assert states[0]["latest_request"]["reasoning_chars"] == len("private reasoning")
    assert states[0]["total_reported_tokens"] is None
    assert states[1]["latest_request"]["content_chars"] == len(text)
    final = json.loads((tmp_path / "live.json").read_text())
    assert final["total_reported_tokens"] == 21
    assert final["active_requests"] == []
    assert final["latest_request"]["reported_reasoning_tokens"] == 4
    raw = (tmp_path / "events.jsonl").read_text()
    assert "private" not in raw
    assert "private" not in (tmp_path / "live.json").read_text()


def test_heartbeat_updates_even_before_any_response(tmp_path):
    hub = ProgressHub(tmp_path)
    observed = threading.Event()
    publish = hub.publish

    def recording(event, key):
        publish(event, key)
        if event == "heartbeat":
            observed.set()

    hub.publish = recording
    progress = CallProgress(hub, "req", 1, "model", 10, True, .01)
    try:
        assert observed.wait(2)
        live = json.loads((tmp_path / "live.json").read_text())
        request = live["active_requests"][0]
        assert request["state"] == "waiting_response"
        assert request["chunks"] == 0
        assert request["last_chunk_age_s"] is None
        assert request["elapsed_s"] > 0
        assert live["total_reported_tokens"] is None
    finally:
        progress.finish("failed", error=TimeoutError())


def test_usage_updates_are_cumulative_and_reasoning_is_not_double_counted(tmp_path):
    progress = CallProgress(ProgressHub(tmp_path), "req", 1, "model", 10, True, 10)
    progress.chunk(chunk(usage=NS(prompt_tokens=3, completion_tokens=2)))
    progress.chunk(chunk(usage=NS(prompt_tokens=3, completion_tokens=5)))
    progress.finish("completed", usage=NS(prompt_tokens=3, completion_tokens=7,
                                          completion_tokens_details=NS(reasoning_tokens=4)))
    live = json.loads((tmp_path / "live.json").read_text())
    assert live["total_reported_tokens"] == 10
    assert live["total_reported_completion_tokens"] == 7


def test_failed_partial_stream_is_recorded_and_closed(tmp_path, monkeypatch):
    monkeypatch.setenv("FE_LLM_PROGRESS_DIR", str(tmp_path))
    config = EvolveConfig()
    config.llm.stream = True
    llm = DashScopeLLM(config)
    closed = []

    class Stream:
        def __iter__(self):
            yield chunk(reasoning="do not persist")
            raise ValueError("do not log this body or token")

        def close(self):
            closed.append(True)

    monkeypatch.setattr(llm, "_get_client", lambda: NS(chat=NS(completions=NS(create=lambda **k: Stream()))))
    with pytest.raises(ValueError):
        llm.chat([])
    live = json.loads((tmp_path / "live.json").read_text())
    assert live["latest_request"]["state"] == "failed"
    assert live["latest_request"]["error_type"] == "ValueError"
    assert live["active_requests"] == []
    assert live["total_reported_tokens"] is None
    assert closed == [True]
    assert "do not" not in (tmp_path / "events.jsonl").read_text()


def test_retry_keeps_attempts_distinct_without_counting_unknown_usage(tmp_path, monkeypatch):
    monkeypatch.setenv("FE_LLM_PROGRESS_DIR", str(tmp_path))
    config = EvolveConfig()
    config.llm.stream = True
    llm = DashScopeLLM(config)
    llm.RETRY_DELAYS = [0]
    count = 0

    def create(**kwargs):
        nonlocal count
        count += 1
        if count == 1:
            raise TimeoutError("timeout")
        return iter([chunk(content="ok", usage=NS(prompt_tokens=3, completion_tokens=1))])

    monkeypatch.setattr(llm, "_get_client", lambda: NS(chat=NS(completions=NS(create=create))))
    text, metrics = llm.chat([])
    live = json.loads((tmp_path / "live.json").read_text())
    assert text == "ok" and metrics.attempts == 2
    assert live["total_requests"] == 2
    assert live["requests_without_reported_usage"] == 1
    assert live["total_reported_tokens"] == 4
    assert live["recent_requests"][0]["state"] == "retry_wait"
