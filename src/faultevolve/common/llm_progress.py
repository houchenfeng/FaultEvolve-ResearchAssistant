"""Content-free live progress and provider token counters for LLM requests."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import threading
import time
from typing import Any


_hubs: dict[str, "ProgressHub"] = {}
_hubs_lock = threading.Lock()


def _number(value: Any) -> int | None:
    return value if type(value) is int and value >= 0 else None


def _get(value: Any, name: str) -> Any:
    return value.get(name) if isinstance(value, dict) else getattr(value, name, None)


class ProgressHub:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.lock = threading.RLock()
        self.requests: dict[str, dict[str, Any]] = {}
        self.io_warning = False

    def publish(self, event: str, key: str) -> None:
        """Called under the hub lock; never write prompts or response text."""
        now = time.time()
        rows = []
        for state in self.requests.values():
            row = dict(state)
            row["elapsed_s"] = round((row.get("ended_at") or now) - row["started_at"], 3)
            row["last_chunk_age_s"] = round(now - row["last_chunk_at"], 3) if row["last_chunk_at"] else None
            row["last_output_age_s"] = round(now - row["last_output_at"], 3) if row["last_output_at"] else None
            rows.append(row)
        known = [r for r in rows if r["reported_total_tokens"] is not None]
        payload = {
            "updated_at": now,
            "pid": os.getpid(),
            "active_requests": [r for r in rows if r["ended_at"] is None],
            "recent_requests": rows[-20:],
            "latest_request": rows[-1] if rows else None,
            "total_requests": len(rows),
            "requests_with_reported_usage": len(known),
            "requests_without_reported_usage": len(rows) - len(known),
            "total_reported_tokens": sum(r["reported_total_tokens"] for r in known) if known else None,
            "total_reported_prompt_tokens": sum(r["reported_prompt_tokens"] or 0 for r in known) if known else None,
            "total_reported_completion_tokens": sum(r["reported_completion_tokens"] or 0 for r in known) if known else None,
            "token_counts_note": "Token 仅记录接口回传用量；null 表示未知。字符和分块计数不是 Token，推理 Token 通常已包含在输出 Token 中。",
        }
        row = next(r for r in rows if r["key"] == key)
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            temporary = self.directory / "live.json.tmp"
            temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
            temporary.replace(self.directory / "live.json")
            with (self.directory / "events.jsonl").open("a") as handle:
                handle.write(json.dumps({"event": event, "ts": now, **row}, ensure_ascii=False) + "\n")
        except OSError as exc:
            if not self.io_warning:
                logging.getLogger(__name__).warning("LLM progress output unavailable (%s)", type(exc).__name__)
                self.io_warning = True


class CallProgress:
    def __init__(self, hub: ProgressHub, request_id: str, attempt: int, model: str,
                 max_tokens: int, streaming: bool, interval: float) -> None:
        self.hub, self.interval = hub, interval
        self.key = f"{request_id}:{attempt}"
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._heartbeat, name="llm-live-progress", daemon=True)
        now = time.time()
        self.state: dict[str, Any] = {
            "key": self.key, "request_id": request_id, "gateway_attempt": attempt,
            "model": model, "max_tokens_requested": max_tokens, "streaming": streaming,
            "state": "waiting_response", "started_at": now, "ended_at": None,
            "last_chunk_at": None, "last_output_at": None,
            "time_to_first_chunk_s": None, "time_to_first_content_s": None,
            "chunks": 0, "content_chars": 0, "reasoning_chars": 0,
            "reported_prompt_tokens": None, "reported_completion_tokens": None,
            "reported_reasoning_tokens": None, "reported_total_tokens": None,
            "provider_request_id": None, "finish_reason": None,
        }
        with hub.lock:
            hub.requests[self.key] = self.state
            hub.publish("request_started", self.key)
        self.thread.start()

    def _heartbeat(self) -> None:
        while not self.stop.wait(self.interval):
            with self.hub.lock:
                self.hub.publish("heartbeat", self.key)

    def _usage(self, usage: Any) -> None:
        if usage is None:
            return
        for source, target in (("prompt_tokens", "reported_prompt_tokens"),
                               ("completion_tokens", "reported_completion_tokens"),
                               ("total_tokens", "reported_total_tokens")):
            value = _number(_get(usage, source))
            if value is not None:
                self.state[target] = value
        details = _get(usage, "completion_tokens_details")
        reasoning = _number(_get(details, "reasoning_tokens"))
        if reasoning is not None:
            self.state["reported_reasoning_tokens"] = reasoning
        if _number(_get(usage, "total_tokens")) is None:
            a, b = self.state["reported_prompt_tokens"], self.state["reported_completion_tokens"]
            if a is not None and b is not None:
                self.state["reported_total_tokens"] = a + b

    def chunk(self, chunk: Any) -> None:
        now = time.time()
        with self.hub.lock:
            first = self.state["chunks"] == 0
            self.state["chunks"] += 1
            self.state["last_chunk_at"] = now
            self.state["state"] = "streaming"
            if first:
                self.state["time_to_first_chunk_s"] = round(now - self.state["started_at"], 3)
            provider_id = _get(chunk, "id")
            if isinstance(provider_id, str):
                self.state["provider_request_id"] = provider_id[:128]
            first_output = False
            for choice in (_get(chunk, "choices") or []):
                delta = _get(choice, "delta")
                content = _get(delta, "content")
                reasoning = _get(delta, "reasoning_content") or _get(delta, "reasoning")
                if isinstance(reasoning, str) and reasoning:
                    self.state["reasoning_chars"] += len(reasoning)
                    self.state["last_output_at"] = now
                    self.state["state"] = "streaming_reasoning"
                if isinstance(content, str) and content:
                    first_output = self.state["time_to_first_content_s"] is None
                    if first_output:
                        self.state["time_to_first_content_s"] = round(now - self.state["started_at"], 3)
                    self.state["content_chars"] += len(content)
                    self.state["last_output_at"] = now
                    self.state["state"] = "streaming_content"
                reason = _get(choice, "finish_reason")
                if isinstance(reason, str):
                    self.state["finish_reason"] = reason
            before = self.state["reported_total_tokens"]
            self._usage(_get(chunk, "usage"))
            if first or first_output or self.state["reported_total_tokens"] != before:
                self.hub.publish("stream_progress", self.key)

    def finish(self, state: str, usage: Any = None, error: Exception | None = None) -> None:
        self.stop.set()
        self.thread.join(timeout=1)
        with self.hub.lock:
            self._usage(usage)
            self.state["state"] = state
            self.state["ended_at"] = time.time()
            if error is not None:
                self.state["error_type"] = type(error).__name__
                self.state["http_status"] = getattr(error, "status_code", None)
            self.hub.publish("request_" + state, self.key)


def start_progress(request_id: str, attempt: int, model: str, max_tokens: int,
                   streaming: bool) -> CallProgress | None:
    path = os.environ.get("FE_LLM_PROGRESS_DIR", "").strip()
    if not path:
        return None
    try:
        interval = max(0.01, float(os.environ.get("FE_LLM_PROGRESS_INTERVAL_S", "10")))
    except ValueError:
        interval = 10.0
    with _hubs_lock:
        hub = _hubs.setdefault(path, ProgressHub(Path(path)))
    return CallProgress(hub, request_id, attempt, model, max_tokens, streaming, interval)
