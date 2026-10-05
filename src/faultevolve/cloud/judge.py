"""Fail-open Jev screening and pure prior helpers."""

from __future__ import annotations

import difflib
import logging
import os
from dataclasses import dataclass
from typing import Any

from faultevolve.common.schemas import Node
from faultevolve.cloud.jev_client import (
    JevClient,
    JevError,
    MockJevClient,
    parse_choice,
    parse_noul,
    parse_score,
)
from faultevolve.config import EvolveConfig

logger = logging.getLogger(__name__)


@dataclass
class JudgeResult:
    """Result from a judge decision."""
    probabilities: dict[str, float]
    confidence: float = 0.5
    raw_response: dict[str, Any] | None = None


@dataclass
class PrescreenResult:
    """Result from evaluation prescreen."""
    ok: bool = False
    attempted: bool = False
    p_invalid: float = 0.0
    p_improve: float = 0.5
    value: float = 0.5
    decision: str = "evaluate"
    would_screen: bool = False
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    latency_ms: int = 0
    error: str = ""


class JudgeClient:
    """Client for judge (Jev) decisions.

    All methods currently return uniform/default values.
    Hooks are provided for Jev API integration.
    """

    def __init__(
        self,
        config: EvolveConfig,
        client: JevClient | MockJevClient | None = None,
    ) -> None:
        """Initialize the judge client.

        Args:
            config: Evolution configuration
        """
        self.config = config
        self.provider = config.judge.provider
        self.model = config.judge.model
        self.enabled = self.provider in {"jev", "mock"}
        self.disabled_reason = ""
        self.call_count = 0
        self.consecutive_errors = 0
        self.circuit_open = False
        self.warmup_seen = 0
        self.calibration_data: list[dict[str, Any]] = []
        self.value_cache: dict[str, float] = {}
        self.client = client
        if self.provider == "none":
            self.enabled = False
        elif self.client is None and self.provider == "mock":
            self.client = MockJevClient(config.judge)
        elif self.client is None and self.provider == "jev":
            if os.environ.get(config.judge.api_key_env):
                self.client = JevClient(config.judge)
            else:
                self.enabled = False
                self.disabled_reason = "missing_key"
                logger.warning("Jev disabled: required API key is missing")

    def node_prior(
        self,
        parent: Node,
        options: list[Node | str],
        context: dict[str, Any] | None = None,
    ) -> dict[str, float]:
        """Get prior probabilities for node selection.

        Hook for Jev Choice API.
        Currently returns uniform distribution.

        Args:
            parent: Parent node
            options: List of child nodes or "expand_self"
            context: Additional context

        Returns:
            Dictionary mapping option IDs to probabilities
        """
        n = len(options)
        if n == 0:
            return {}

        priors = {}
        for opt in options:
            key = opt.id if isinstance(opt, Node) else str(opt)
            priors[key] = self.value_cache.get(key, 0.0)

        if not any(priors.values()):
            return {key: 1.0 / n for key in priors}
        total = sum(max(0.0, value) for value in priors.values())
        return {key: max(0.0, value) / total for key, value in priors.items()}

    def operator_choice(
        self,
        node: Node,
        operators: list[str],
        context: dict[str, Any] | None = None,
    ) -> dict[str, float]:
        """Get probabilities for operator selection.

        Hook for Jev Choice API.
        Currently returns uniform distribution.

        Args:
            node: Node to expand
            operators: List of operator names
            context: Additional context

        Returns:
            Dictionary mapping operators to probabilities
        """
        n = len(operators)
        if n == 0:
            return {}

        return {op: 1.0 / n for op in operators}

    def prescreen(
        self,
        parent: Node,
        code: str,
        intent: str,
        context: dict[str, Any] | None = None,
    ) -> PrescreenResult:
        """Prescreen a candidate before evaluation.

        Hook for Jev Score + Noul API.
        Currently returns default values (no deferral).

        Args:
            parent: Parent node
            code: Generated candidate code
            intent: Change intent
            context: Additional context

        Returns:
            PrescreenResult with default probabilities
        """
        if not self.enabled or self.circuit_open or self.client is None:
            return PrescreenResult()
        if self.call_count >= self.config.judge.max_calls:
            self.enabled = False
            self.disabled_reason = "max_calls"
            return PrescreenResult()

        context = context or {}
        diff = "".join(difflib.unified_diff(
            parent.artifact.code.splitlines(keepends=True),
            code.splitlines(keepends=True),
            fromfile="parent.py",
            tofile="candidate.py",
        ))
        prefix = (
            f"任务摘要：{context.get('problem_md', '')}\n"
            f"约束：{context.get('constraints', '')}\n"
            f"父节点意图：{parent.artifact.intent}\n"
            f"父节点假设：{parent.artifact.hypothesis}\n"
            f"父节点真实分数：{parent.get_score()}\n"
            f"候选意图：{intent}\n"
            f"候选假设：{context.get('candidate_hypothesis', '')}\n"
            "父子 unified diff：\n"
        )
        remaining = max(0, self.config.judge.max_state_chars - len(prefix))
        state = (
            prefix[:self.config.judge.max_state_chars]
            if remaining == 0
            else prefix + diff[-remaining:]
        )
        questions = [
            {
                "name": "valid",
                "type": "noul",
                "instructions": "候选是否满足硬约束且值得真实评估？",
                "criteria": {"true": "满足", "false": "违反"},
            },
            {
                "name": "improve",
                "type": "choice",
                "instructions": "候选相对父节点的真实分数会如何变化？",
                "criteria": {"better": "更好", "same": "相同", "worse": "更差"},
            },
            {
                "name": "value",
                "type": "score",
                "instructions": "候选的评估价值。",
                "criteria": ["低", "高"],
            },
        ]
        self.call_count += 1
        try:
            response = self.client.decide(state, questions)
            valid = parse_noul(response.answers.get("valid", {}))
            improve = parse_choice(
                response.answers.get("improve", {}), ["better", "same", "worse"]
            )
            value = parse_score(response.answers.get("value", {}))
            self.consecutive_errors = 0
            self.warmup_seen += 1
            raw = PrescreenResult(
                ok=True,
                attempted=True,
                p_invalid=1.0 - valid,
                p_improve=improve["better"],
                value=value,
                prompt_tokens=response.prompt_tokens,
                completion_tokens=response.completion_tokens,
                total_tokens=response.total_tokens,
                latency_ms=response.latency_ms,
            )
            raw.would_screen = should_defer_candidate(
                raw,
                True,
                self.config.judge.invalid_threshold,
                self.config.judge.low_value_threshold,
                self.config.judge.low_value_action,
            ) != "evaluate"
            if self.warmup_seen > self.config.judge.warmup:
                raw.decision = should_defer_candidate(
                    raw,
                    True,
                    self.config.judge.invalid_threshold,
                    self.config.judge.low_value_threshold,
                    self.config.judge.low_value_action,
                )
            return raw
        except JevError as exc:
            self.consecutive_errors += 1
            if self.consecutive_errors >= self.config.judge.max_consecutive_errors:
                self.circuit_open = True
                self.enabled = False
                self.disabled_reason = "circuit_open"
            return PrescreenResult(attempted=True, error=str(exc))

    def insight_applicability(
        self,
        insight: dict[str, Any],
        target_node: Node,
        context: dict[str, Any] | None = None,
    ) -> float:
        """Get applicability score for an insight.

        Hook for Jev Noul API.
        Currently returns default value.

        Args:
            insight: The insight to check
            target_node: Target node for application
            context: Additional context

        Returns:
            Applicability probability (0.0 to 1.0)
        """
        return 0.5

    def should_continue(
        self,
        recent_history: list[dict[str, Any]],
        context: dict[str, Any] | None = None,
    ) -> float:
        """Judge whether evolution should continue.

        Hook for Jev Noul API.
        Currently returns default value.

        Args:
            recent_history: Recent evaluation results
            context: Additional context

        Returns:
            Probability that continuing is worthwhile
        """
        return 0.5

    def record_outcome(
        self,
        decision_type: str,
        predicted: dict[str, float],
        actual: str | int | float,
        context: dict[str, Any] | None = None,
    ) -> None:
        """Record outcome for calibration.

        Hook for Jev calibration updates.

        Args:
            decision_type: Type of decision made
            predicted: Predicted probabilities
            actual: Actual outcome
            context: Additional context
        """
        self.calibration_data.append({
            "decision_type": decision_type,
            "predicted": predicted,
            "actual": actual,
        })

        if len(self.calibration_data) >= self.config.judge.calibration_window:
            self.calibration_data = self.calibration_data[-self.config.judge.calibration_window:]

    def get_trust(self) -> float:
        """Get current trust level.

        Hook for calibration-based trust computation.
        Currently returns initial trust.

        Returns:
            Trust level (0.0 to 1.0)
        """
        return self.config.judge.prior_tau


def compute_expected_gain(p_improve: float, gain_scale: float = 1.25) -> float:
    """Compute expected score gain from improvement probability.

    Uses simplified model:
    - P(improvement) -> expected gain of +gain_scale
    - P(no change or worse) -> expected gain of 0 or negative

    Args:
        p_improve: Probability of improvement
        gain_scale: Scale factor for expected gain

    Returns:
        Expected gain value
    """
    return p_improve * gain_scale - (1 - p_improve) * gain_scale * 0.5


def should_defer_candidate(
    prescreen: PrescreenResult,
    warmup_done: bool,
    invalid_threshold: float = 0.85,
    low_value_threshold: float = 0.15,
    low_value_action: str = "skip",
) -> str:
    """Determine if a candidate should be deferred.

    Hook for Jev-based deferral logic.

    Args:
        prescreen: Prescreen result
        warmup_done: Whether warmup period is complete
        threshold_improve: Minimum p_improve to not defer
        threshold_violation: Maximum p_violation to not defer

    Returns:
        True if candidate should be deferred
    """
    if not warmup_done:
        return "evaluate"
    if prescreen.p_invalid >= invalid_threshold:
        return "skip_invalid"
    if prescreen.value < low_value_threshold:
        return "defer" if low_value_action == "defer" else "skip_low_value"
    return "evaluate"
