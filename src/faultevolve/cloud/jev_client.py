"""Small synchronous client for the MiYang Jev relay."""

from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass
from typing import Any

import httpx

from faultevolve.config import JudgeConfig


@dataclass(frozen=True)
class JevResponse:
    answers: dict[str, dict[str, Any]]
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    latency_ms: int = 0


class JevError(RuntimeError):
    """Sanitized Jev failure."""


def _probability(value: Any) -> float:
    try:
        return min(1.0, max(0.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def parse_noul(answer: dict[str, Any]) -> float:
    value: Any = answer.get("noul", answer.get("value", answer))
    if isinstance(value, dict):
        value = value.get("true", value.get(True, 0.0))
    return _probability(value)


def parse_choice(answer: dict[str, Any], options: list[str]) -> dict[str, float]:
    raw = answer.get("probabilities", answer.get("choices", answer))
    if not isinstance(raw, dict):
        raw = {}
    values = {option: max(0.0, float(raw.get(option, 0.0) or 0.0)) for option in options}
    total = sum(values.values())
    if total <= 0:
        return {option: 1.0 / len(options) for option in options} if options else {}
    return {option: value / total for option, value in values.items()}


def parse_score(answer: dict[str, Any]) -> float:
    value: Any = answer.get("score", answer.get("value", 0.0))
    try:
        score = float(value)
    except (TypeError, ValueError):
        score = 0.0
    if score > 10:
        score /= 100.0
    elif score > 1:
        score /= 10.0
    return min(1.0, max(0.0, score))


def _build_request_body(
    model: str,
    state: str,
    questions: list[dict[str, Any]],
) -> dict[str, Any]:
    questions_obj: dict[str, Any] = {}
    for question in questions:
        name = str(question.get("name", ""))
        if not name:
            continue
        questions_obj[name] = {k: v for k, v in question.items() if k != "name"}
    return {"model": model, "state": {"text": state}, "questions": questions_obj}


def _parse_response(data: Any, latency_ms: int) -> JevResponse:
    if (
        not isinstance(data, dict)
        or not isinstance(data.get("answers"), dict)
        or not all(isinstance(answer, dict) for answer in data["answers"].values())
    ):
        raise JevError("invalid_answers")
    usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    prompt = int(usage.get("prompt_tokens", usage.get("input_tokens", 0)) or 0)
    completion = int(usage.get("completion_tokens", usage.get("output_tokens", 0)) or 0)
    total = int(usage.get("total_tokens", 0) or 0)
    if total and not prompt and not completion:
        prompt = total
    total = max(total, prompt + completion)
    return JevResponse(
        answers=data["answers"],
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=total,
        latency_ms=latency_ms,
    )


class JevClient:
    def __init__(
        self,
        config: JudgeConfig,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.config = config
        self._client = httpx.Client(
            transport=transport,
            timeout=config.timeout_s,
        )

    def decide(self, state: str, questions: list[dict[str, Any]]) -> JevResponse:
        key = os.environ.get(self.config.api_key_env)
        if not key:
            raise JevError("missing_key")
        body = _build_request_body(self.config.model, state, questions)
        started = time.monotonic()
        for attempt in range(self.config.retries + 1):
            try:
                response = self._client.post(
                    self.config.base_url,
                    json=body,
                    headers={"Authorization": f"Bearer {key}"},
                )
            except httpx.TimeoutException as exc:
                raise JevError("timeout") from exc
            except httpx.HTTPError as exc:
                raise JevError("network_error") from exc
            if response.status_code == 429 or response.status_code >= 500:
                if attempt < self.config.retries:
                    continue
                raise JevError(f"http_{response.status_code}")
            if not response.is_success:
                raise JevError(f"http_{response.status_code}")
            try:
                data = response.json()
            except ValueError as exc:
                raise JevError("invalid_json") from exc
            latency = int((time.monotonic() - started) * 1000)
            return _parse_response(data, latency)
        raise JevError("retry_exhausted")


class MockJevClient:
    """Deterministic offline judge used by the skill smoke run."""

    def __init__(self, config: JudgeConfig) -> None:
        self.config = config
        self.call_count = 0

    def decide(self, state: str, questions: list[dict[str, Any]]) -> JevResponse:
        self.call_count += 1
        digest = hashlib.sha256(
            f"{state}:{self.call_count}".encode()
        ).digest()
        screened = self.call_count % 3 == 0
        answers: dict[str, dict[str, Any]] = {}
        for question in questions:
            name = str(question.get("name", ""))
            if name == "valid":
                answers[name] = {"noul": 0.05 if screened else 0.95}
            elif name == "improve":
                answers[name] = {
                    "probabilities": {
                        "better": 0.05 if screened else 0.7,
                        "same": 0.15,
                        "worse": 0.8 if screened else 0.15,
                    }
                }
            elif name == "value":
                answers[name] = {"score": 0.05 if screened else digest[0] / 255}
            else:
                answers[name] = {"noul": digest[1] / 255}
        return JevResponse(answers, 40, 10, 50, 1)
