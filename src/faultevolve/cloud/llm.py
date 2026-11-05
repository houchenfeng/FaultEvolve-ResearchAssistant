"""LLM Gateway for FaultEvolve.

Handles communication with Qwen via DashScope OpenAI-compatible API.
Includes retry logic, token metering, and caching.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import time
import uuid
from typing import Any, Protocol

from faultevolve.common.metering import CallMetrics, Timer
from faultevolve.common.llm_progress import CallProgress, start_progress
from faultevolve.common.schemas import LLMCall
from faultevolve.config import EvolveConfig


class LLMClient(Protocol):
    """Protocol for LLM clients."""

    def chat(
        self,
        messages: list[dict[str, str]],
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> tuple[str, CallMetrics]:
        """Send a chat completion request.

        Returns:
            Tuple of (response_text, call_metrics)
        """
        ...


class LLMTransientError(Exception):
    """Transient LLM error that was not recoverable after retries.

    Carries the request it failed on: a request that went out and never came back
    is a spend the run has to record as unresolved, not as if nothing was sent.
    """

    def __init__(self, message: str, *, request_id: str = "", attempts: int = 1) -> None:
        super().__init__(message)
        self.request_id = request_id
        self.attempts = attempts


class DashScopeLLM:
    """LLM client for DashScope (Qwen) via OpenAI-compatible API."""

    RETRY_DELAYS = [4, 8, 16]
    RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
    RETRYABLE_ERRORS = ["connection error", "timeout", "timed out", "rate limit"]

    def __init__(self, config: EvolveConfig) -> None:
        """Initialize the LLM client.

        Args:
            config: Evolution configuration
        """
        self.config = config
        self.base_url = os.environ.get("DASHSCOPE_BASE_URL", "").strip() or config.llm.base_url
        self.model = config.llm.generate_model
        self.reason_model = config.llm.reason_model
        self.temperature = config.llm.temperature
        self.max_tokens = config.llm.max_tokens
        self._cache: dict[str, tuple[str, CallMetrics]] = {}
        self._client: Any = None

    def _get_client(self) -> Any:
        """Get or create the OpenAI client."""
        if self._client is None:
            import httpx
            from openai import OpenAI

            api_key = os.environ.get("DASHSCOPE_API_KEY", "")
            # The read timeout is a run-level knob: the SDK default (600s) kills a
            # slow reasoning generation mid-flight, and the retry re-sends the same
            # prompt, so the run can never make progress on a slow model.
            timeout = httpx.Timeout(self.config.llm.timeout_s, connect=15.0)
            self._client = OpenAI(api_key=api_key, base_url=self.base_url, timeout=timeout)
        return self._client

    def _stream_chat(
        self,
        client: Any,
        model: str,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
        progress: CallProgress | None = None,
        extra_body: dict[str, Any] | None = None,
    ) -> tuple[str, Any]:
        """Run one streaming request, joining content deltas as they arrive.

        Streaming keeps the socket alive while the model generates, so a long
        generation is not killed by the read timeout; the token usage rides the
        final chunk via stream_options.include_usage.
        """
        stream = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
            stream_options={"include_usage": True},
            extra_body=extra_body or None,
        )
        parts: list[str] = []
        usage: Any = None
        try:
            for chunk in stream:
                if progress is not None:
                    progress.chunk(chunk)
                if getattr(chunk, "usage", None):
                    usage = chunk.usage
                for choice in (chunk.choices or []):
                    delta = getattr(choice, "delta", None)
                    content = getattr(delta, "content", None) if delta is not None else None
                    if content:
                        parts.append(content)
        finally:
            close = getattr(stream, "close", None)
            if close is not None:
                close()
        return "".join(parts), usage

    def _cache_key(self, model: str, messages: list[dict[str, str]], temperature: float) -> str:
        """Generate cache key for a request."""
        content = f"{model}:{temperature}:{messages}"
        return hashlib.sha256(content.encode()).hexdigest()

    def _is_transient_error(self, error: Exception) -> bool:
        """Check if an error is transient and should be retried."""
        error_str = str(error).lower()

        for code in self.RETRYABLE_STATUS_CODES:
            if str(code) in str(error):
                return True

        for pattern in self.RETRYABLE_ERRORS:
            if pattern in error_str:
                return True

        return False

    def chat(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        raise_on_transient: bool = True,
        thinking: bool | None = None,
    ) -> tuple[str, CallMetrics]:
        """Send a chat completion request with retry logic.

        Args:
            messages: List of message dicts with 'role' and 'content'
            model: Model to use (defaults to config)
            temperature: Temperature (defaults to config)
            max_tokens: Max tokens (defaults to config)
            raise_on_transient: If False, raises LLMTransientError instead of
                               the original error when all retries fail on
                               transient errors
            thinking: False disables the model's reasoning stage (DashScope
                      ``enable_thinking``); None keeps the endpoint default

        Returns:
            Tuple of (response_text, call_metrics)

        Raises:
            Exception: If all retries fail and raise_on_transient=True
            LLMTransientError: If all retries fail on transient error and
                              raise_on_transient=False
        """
        model = model or self.model
        temperature = temperature if temperature is not None else self.temperature
        max_tokens = max_tokens or self.max_tokens
        # Short structured calls (reflection, cards) must not spend their whole
        # budget on a reasoning model's thinking stage and return no content.
        extra_body = {"enable_thinking": thinking} if thinking is not None else None

        if temperature == 0:
            cache_key = self._cache_key(model, messages, temperature)
            if cache_key in self._cache:
                text, metrics = self._cache[cache_key]
                # A cache hit sent no request, so it gets no request id; its token
                # counts are the original call's, which the rollup can tell apart
                # from fresh spend through the cached flag.
                return text, CallMetrics(
                    prompt_tokens=metrics.prompt_tokens,
                    completion_tokens=metrics.completion_tokens,
                    latency_ms=0,
                    cached=True,
                )

        client = self._get_client()
        request_id = uuid.uuid4().hex[:12]
        last_error: Exception | None = None
        was_transient = False

        for attempt, delay in enumerate(self.RETRY_DELAYS + [0]):
            progress = start_progress(request_id, attempt + 1, model, max_tokens, self.config.llm.stream)
            try:
                with Timer() as timer:
                    if self.config.llm.stream:
                        text, usage = self._stream_chat(
                            client, model, messages, temperature, max_tokens,
                            progress=progress, extra_body=extra_body,
                        )
                    else:
                        response = client.chat.completions.create(
                            model=model,
                            messages=messages,
                            temperature=temperature,
                            max_tokens=max_tokens,
                            extra_body=extra_body,
                        )
                        text = response.choices[0].message.content or ""
                        usage = response.usage

                metrics = CallMetrics(
                    prompt_tokens=usage.prompt_tokens if usage else 0,
                    completion_tokens=usage.completion_tokens if usage else 0,
                    latency_ms=timer.elapsed_ms,
                    cached=False,
                    request_id=request_id,
                    attempts=attempt + 1,
                )
                if progress is not None:
                    progress.finish("completed", usage=usage)

                if temperature == 0:
                    cache_key = self._cache_key(model, messages, temperature)
                    self._cache[cache_key] = (text, metrics)

                return text, metrics

            except Exception as e:
                last_error = e
                is_transient = self._is_transient_error(e)
                if progress is not None:
                    progress.finish("retry_wait" if is_transient and attempt < len(self.RETRY_DELAYS) else "failed", error=e)

                if is_transient:
                    was_transient = True
                    if attempt < len(self.RETRY_DELAYS):
                        time.sleep(delay)
                        continue

                if not is_transient:
                    raise

        if was_transient:
            # The caller can still see which request died and how many sends it
            # used, so the spend can be written down as unresolved.
            raise LLMTransientError(
                f"LLM call failed after {len(self.RETRY_DELAYS)} retries: {last_error}",
                request_id=request_id,
                attempts=len(self.RETRY_DELAYS) + 1,
            )

        raise last_error or Exception("LLM call failed")

    def chat_for_reasoning(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.2,
    ) -> tuple[str, CallMetrics]:
        """Chat using the reasoning model (for insight extraction, etc.).

        Thinking is disabled: these calls expect a short JSON answer, and a
        reasoning model would otherwise exhaust ``max_tokens`` before emitting
        any content.
        """
        return self.chat(
            messages=messages,
            model=self.reason_model,
            temperature=temperature,
            max_tokens=2000,
            thinking=False,
        )


class MockLLM:
    """Mock LLM for offline testing.

    Returns scripted responses based on the prompt content.
    Supports both code generation, reflection, and repair responses.

    By default, generates one failing code at call 2 to trigger repair.
    """

    def __init__(self, enable_repair_scenario: bool = True) -> None:
        """Initialize mock LLM.

        Args:
            enable_repair_scenario: If True, generate failing code to trigger repair
        """
        self._call_count = 0
        self._responses: list[str] = []
        self._reasoning_responses: list[str] = []
        self._reasoning_call_count = 0
        self._enable_repair_scenario = enable_repair_scenario

    def set_responses(self, responses: list[str]) -> None:
        """Set the list of responses to return for chat (code generation)."""
        self._responses = responses
        self._call_count = 0

    def set_reasoning_responses(self, responses: list[str]) -> None:
        """Set the list of responses for reasoning (reflection) calls."""
        self._reasoning_responses = responses
        self._reasoning_call_count = 0

    def chat(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> tuple[str, CallMetrics]:
        """Return a mock response.

        Returns scripted responses if set, otherwise generates a
        deterministic response based on call count.
        Detects repair prompts and returns repair-specific responses.
        """
        user_msg = messages[-1].get("content", "") if messages else ""
        is_repair = "修复" in user_msg or "失败的代码" in user_msg

        if self._responses and self._call_count < len(self._responses):
            response = self._responses[self._call_count]
        elif is_repair:
            response = self._generate_repair_response(self._call_count)
        elif self._enable_repair_scenario and self._call_count == 2:
            response = self._generate_failing_code_response(self._call_count)
        else:
            response = self._generate_mock_response(self._call_count)

        self._call_count += 1

        return response, CallMetrics(
            prompt_tokens=100,
            completion_tokens=200,
            latency_ms=50,
            cached=False,
            request_id=f"mock-req-{self._call_count}",
        )

    def chat_for_reasoning(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.2,
    ) -> tuple[str, CallMetrics]:
        """Mock reasoning model call for reflection.

        Returns scripted reasoning responses if set, otherwise generates
        a deterministic JSON reflection response.
        """
        if (self._reasoning_responses and
                self._reasoning_call_count < len(self._reasoning_responses)):
            response = self._reasoning_responses[self._reasoning_call_count]
        else:
            response = self._generate_mock_reflection_response(self._reasoning_call_count)

        self._reasoning_call_count += 1

        return response, CallMetrics(
            prompt_tokens=150,
            completion_tokens=100,
            latency_ms=40,
            cached=False,
            request_id=f"mock-reason-{self._reasoning_call_count}",
        )

    def _generate_mock_response(self, call_number: int) -> str:
        """Generate a deterministic mock response for code generation."""
        adopted_cards = ""
        if call_number % 2 == 0:
            adopted_cards = "<adopted_cards>FE01,M01</adopted_cards>\n"
        elif call_number % 3 == 0:
            adopted_cards = "<adopted_cards>T01</adopted_cards>\n"
        else:
            adopted_cards = "<adopted_cards></adopted_cards>\n"

        return f"""<hypothesis>Mock hypothesis for call {call_number}</hypothesis>
<intent>Mock improvement: adjust threshold by {call_number * 0.01:.2f}</intent>
{adopted_cards}
```python
\"\"\"Mock solution iteration {call_number}.\"\"\"

import argparse
import os
import pandas as pd
import numpy as np
from sklearn.linear_model import LogisticRegression

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--split", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    train_hist = pd.read_csv(os.path.join(args.data_dir, "train_history.csv.gz"))
    train_lab = pd.read_csv(os.path.join(args.data_dir, "train_labels.csv"))
    query_idx = pd.read_csv(os.path.join(args.data_dir, f"{{args.split}}_index.csv"))

    # Mock feature: use threshold adjustment {call_number * 0.01:.2f}
    threshold = 0.5 + {call_number * 0.01}

    pred = pd.DataFrame({{
        "serial_number": query_idx["serial_number"],
        "score": np.random.rand(len(query_idx)),
        "alarm": 0,
    }})
    pred.loc[pred["score"] > threshold, "alarm"] = 1
    pred.to_csv(args.out, index=False)

if __name__ == "__main__":
    main()
```"""

    def _generate_mock_reflection_response(self, call_number: int) -> str:
        """Generate a deterministic mock reflection JSON response."""
        import json

        layers = ["design", "implementation", "hypothesis"]
        layer = layers[call_number % 3]

        reflection = {
            "layer": layer,
            "change_summary": f"Mock change {call_number}: threshold adjustment",
            "mechanism": f"Adjusted threshold by {call_number * 0.01:.2f} to improve recall",
            "conditions": "Works when data distribution is stable",
            "tags": ["threshold:tuning", f"mock:call_{call_number}"],
            "affects": {"recall": "+", "false_alarm_rate": "-"},
            "causes": [
                {
                    "cause": f"Threshold change affected decision boundary",
                    "layer": layer,
                    "confidence": 0.8,
                    "evidence": f"Score delta observed in iteration {call_number}",
                },
                {
                    "cause": "Feature importance shift",
                    "layer": "design",
                    "confidence": 0.6,
                    "evidence": "Model weights changed",
                },
            ],
        }

        return f"```json\n{json.dumps(reflection, ensure_ascii=False, indent=2)}\n```"

    def _generate_failing_code_response(self, call_number: int) -> str:
        """Generate code that will fail at runtime (for repair testing)."""
        return f"""<hypothesis>Using wrong parameter names will cause TypeError</hypothesis>
<intent>Intentionally use wrong LightGBM parameter to trigger repair</intent>

```python
\"\"\"Mock failing solution iteration {call_number} - wrong parameter.\"\"\"

import argparse
import os
import pandas as pd
import numpy as np

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--split", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    train_hist = pd.read_csv(os.path.join(args.data_dir, "train_history.csv.gz"))
    train_lab = pd.read_csv(os.path.join(args.data_dir, "train_labels.csv"))
    query_idx = pd.read_csv(os.path.join(args.data_dir, f"{{args.split}}_index.csv"))

    # This will cause an error - wrong usage
    undefined_variable_that_does_not_exist.some_method()

    pred = pd.DataFrame({{
        "serial_number": query_idx["serial_number"],
        "score": np.random.rand(len(query_idx)),
        "alarm": 0,
    }})
    pred.to_csv(args.out, index=False)

if __name__ == "__main__":
    main()
```"""

    def _generate_repair_response(self, call_number: int) -> str:
        """Generate repaired code response."""
        return f"""<hypothesis>Fix the undefined variable error by using proper logic</hypothesis>
<intent>Remove undefined variable and use correct computation</intent>

```python
\"\"\"Repaired solution iteration {call_number}.\"\"\"

import argparse
import os
import pandas as pd
import numpy as np
from sklearn.linear_model import LogisticRegression

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--split", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    train_hist = pd.read_csv(os.path.join(args.data_dir, "train_history.csv.gz"))
    train_lab = pd.read_csv(os.path.join(args.data_dir, "train_labels.csv"))
    query_idx = pd.read_csv(os.path.join(args.data_dir, f"{{args.split}}_index.csv"))

    # Fixed: use proper computation instead of undefined variable
    threshold = 0.5 + {call_number * 0.01}

    pred = pd.DataFrame({{
        "serial_number": query_idx["serial_number"],
        "score": np.random.rand(len(query_idx)),
        "alarm": 0,
    }})
    pred.loc[pred["score"] > threshold, "alarm"] = 1
    pred.to_csv(args.out, index=False)

if __name__ == "__main__":
    main()
```"""


def create_llm_call_record(
    experiment_id: str,
    purpose: str,
    model: str,
    metrics: CallMetrics,
    node_id: str | None = None,
    island_id: str = "",
    stage: str = "",
    island_attempt: int | None = None,
    outcome: str = "ok",
) -> LLMCall:
    """Create an LLMCall record for the database.

    ``outcome`` is ``"unknown_outcome"`` for a request that was sent and never
    answered; that row carries no tokens because the client never learned any, and
    leaving the request out entirely would make the run look cheaper than it was.
    Money is not derived here: ``cost_usd`` stays null unless a caller with a real
    bill or rate fills it, so ``cost_basis`` says what the number is worth.
    """
    from faultevolve.cloud.store import now_iso

    return LLMCall(
        id=str(uuid.uuid4())[:8],
        experiment_id=experiment_id,
        island_id=island_id,
        node_id=node_id,
        purpose=purpose,
        model=model,
        prompt_tokens=metrics.prompt_tokens,
        completion_tokens=metrics.completion_tokens,
        latency_ms=metrics.latency_ms,
        cached=metrics.cached,
        created_at=now_iso(),
        request_id=metrics.request_id,
        transport_attempts=metrics.attempts,
        island_attempt=island_attempt,
        stage=stage,
        outcome=outcome,
    )
