"""Metering utilities for tracking tokens, latency, and costs."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class CallMetrics:
    """Metrics for a single LLM or judge call."""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0
    cached: bool = False


@dataclass
class NodeMetrics:
    """Aggregated metrics for a node."""
    generation_tokens: int = 0
    reflection_tokens: int = 0
    generation_latency_ms: int = 0
    reflection_latency_ms: int = 0
    eval_time_s: float = 0.0
    total_time_s: float = 0.0


@dataclass
class RunMetrics:
    """Aggregated metrics for an entire run."""
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_llm_latency_ms: int = 0
    total_eval_time_s: float = 0.0
    total_wall_time_s: float = 0.0
    iterations_done: int = 0
    valid_count: int = 0
    invalid_count: int = 0
    rounds_to_target: int | None = None
    time_to_target_s: float | None = None
    tokens_to_target: int | None = None
    start_time: float = field(default_factory=time.time)
    target_reached: bool = False
    repair_attempts: int = 0
    repair_successes: int = 0
    repair_tokens: int = 0
    repair_iterations: int = 0
    knowledge_tokens: int = 0
    cards_offered_count: int = 0
    cards_adopted_count: int = 0
    cards_adopted_valid_count: int = 0
    generate_tokens: int = 0
    reflect_tokens: int = 0
    precheck_fixes: int = 0
    adapter_errors: int = 0
    perf_rejections: int = 0
    smoke_failures: int = 0
    smoke_fixes: int = 0
    self_fix_tokens: int = 0
    smoke_time_s_total: float = 0.0
    smoke_tests: int = 0
    iteration_events: int = 0
    jev_calls: int = 0
    jev_errors: int = 0
    jev_fail_open: int = 0
    jev_prompt_tokens: int = 0
    jev_completion_tokens: int = 0
    jev_tokens: int = 0
    jev_latency_ms: int = 0
    jev_disabled_reason: str = ""
    candidates_screened: int = 0
    evaluations_saved: int = 0
    screen_audited: int = 0
    screen_audit_bad: int = 0
    screen_shadow: int = 0
    jev_prior_active: bool = False
    regular_eval_count: int = 0
    regular_eval_time_s: float = 0.0
    analysis_calls: int = 0
    analysis_failures: int = 0
    analysis_time_s: float = 0.0
    analysis_nonempty_count: int = 0
    stage_cap_hits: dict[str, int] = field(default_factory=dict)
    expand_skipped_budget: int = 0
    discovery_prompt_tokens: int = 0
    discovery_completion_tokens: int = 0
    discovery_tokens: int = 0
    discovery_latency_ms: int = 0
    entailment_prompt_tokens: int = 0
    entailment_completion_tokens: int = 0
    entailment_tokens: int = 0
    discovered_cards_offered: int = 0
    discovered_cards_adopted: int = 0
    mechanism_prompt_tokens: int = 0
    mechanism_completion_tokens: int = 0
    mechanism_tokens: int = 0
    mechanism_latency_ms: int = 0
    crossover_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.total_prompt_tokens + self.total_completion_tokens

    @property
    def valid_rate(self) -> float:
        total = self.valid_count + self.invalid_count
        return self.valid_count / total if total > 0 else 0.0

    @property
    def card_adoption_rate(self) -> float:
        """Rate of card adoption (adopted / offered)."""
        if self.cards_offered_count == 0:
            return 0.0
        return self.cards_adopted_count / self.cards_offered_count

    @property
    def knowledge_token_share(self) -> float:
        """Share of knowledge tokens in total prompt tokens."""
        if self.total_prompt_tokens == 0:
            return 0.0
        return self.knowledge_tokens / self.total_prompt_tokens

    @property
    def analysis_nonempty_rate(self) -> float:
        if self.analysis_calls == 0:
            return 0.0
        return self.analysis_nonempty_count / self.analysis_calls

    @property
    def screening_precision(self) -> float | None:
        if self.screen_audited == 0:
            return None
        return self.screen_audit_bad / self.screen_audited

    @property
    def eval_time_saved_est_s(self) -> float:
        if self.regular_eval_count == 0:
            return 0.0
        return self.evaluations_saved * self.regular_eval_time_s / self.regular_eval_count

    def compute_tokens_per_score_gain(self, best_score: float, initial_score: float, eps: float = 0.001) -> float:
        """Compute tokens spent per unit of score improvement.

        Args:
            best_score: Best score achieved
            initial_score: Initial score
            eps: Minimum gain to avoid division by zero

        Returns:
            Tokens per score gain
        """
        gain = max(best_score - initial_score, eps)
        return self.total_tokens / gain

    def add_llm_call(self, metrics: CallMetrics, purpose: str = "generate") -> None:
        """Add metrics from an LLM call."""
        self.total_prompt_tokens += metrics.prompt_tokens
        self.total_completion_tokens += metrics.completion_tokens
        self.total_llm_latency_ms += metrics.latency_ms

        if purpose == "repair":
            self.repair_tokens += metrics.prompt_tokens + metrics.completion_tokens
        elif purpose == "generate":
            self.generate_tokens += metrics.prompt_tokens + metrics.completion_tokens
        elif purpose == "reflect":
            self.reflect_tokens += metrics.prompt_tokens + metrics.completion_tokens
        elif purpose == "self_fix":
            self.self_fix_tokens += metrics.prompt_tokens + metrics.completion_tokens
        elif purpose == "jev":
            self.jev_prompt_tokens += metrics.prompt_tokens
            self.jev_completion_tokens += metrics.completion_tokens
            self.jev_tokens += metrics.prompt_tokens + metrics.completion_tokens
            self.jev_latency_ms += metrics.latency_ms
        elif purpose == "discover":
            self.discovery_prompt_tokens += metrics.prompt_tokens
            self.discovery_completion_tokens += metrics.completion_tokens
            self.discovery_tokens += metrics.prompt_tokens + metrics.completion_tokens
            self.discovery_latency_ms += metrics.latency_ms
        elif purpose == "entailment":
            self.entailment_prompt_tokens += metrics.prompt_tokens
            self.entailment_completion_tokens += metrics.completion_tokens
            self.entailment_tokens += metrics.prompt_tokens + metrics.completion_tokens
            self.discovery_latency_ms += metrics.latency_ms
        elif purpose == "mechanism":
            self.mechanism_prompt_tokens += metrics.prompt_tokens
            self.mechanism_completion_tokens += metrics.completion_tokens
            self.mechanism_tokens += metrics.prompt_tokens + metrics.completion_tokens
            self.mechanism_latency_ms += metrics.latency_ms
        elif purpose == "crossover":
            self.crossover_tokens += metrics.prompt_tokens + metrics.completion_tokens

    @property
    def mechanism_token_share(self) -> float:
        if self.total_tokens == 0:
            return 0.0
        return self.mechanism_tokens / self.total_tokens

    @property
    def discovery_token_share(self) -> float:
        if self.total_tokens == 0:
            return 0.0
        return self.discovery_tokens / self.total_tokens

    @property
    def discovered_card_adoption_rate(self) -> float:
        if self.discovered_cards_offered == 0:
            return 0.0
        return self.discovered_cards_adopted / self.discovered_cards_offered

    def add_smoke_duration(self, duration_s: float) -> None:
        """Record one smoke test invocation."""
        self.smoke_tests += 1
        self.smoke_time_s_total += duration_s

    @property
    def avg_smoke_time_s(self) -> float | None:
        if self.smoke_tests == 0:
            return None
        return self.smoke_time_s_total / self.smoke_tests

    def add_knowledge_tokens(self, tokens: int) -> None:
        """Add tokens spent on knowledge cards block."""
        self.knowledge_tokens += tokens

    def add_card_adoption(self, offered: int, adopted: int) -> None:
        """Add card adoption stats for one iteration."""
        self.cards_offered_count += offered
        self.cards_adopted_count += adopted

    def add_eval(
        self,
        time_s: float,
        valid: bool,
        is_repair: bool = False,
        count_iteration: bool = True,
    ) -> None:
        """Add metrics from an evaluation.

        Args:
            time_s: Evaluation time in seconds
            valid: Whether the evaluation was valid
            is_repair: If True, counts toward repair_iterations instead of iterations_done
        """
        self.total_eval_time_s += time_s
        if valid:
            self.valid_count += 1
        else:
            self.invalid_count += 1

        if not is_repair:
            self.regular_eval_count += 1
            self.regular_eval_time_s += time_s
        if is_repair:
            self.repair_iterations += 1
        elif count_iteration:
            self.iterations_done += 1

    def add_repair_attempt(self, success: bool) -> None:
        """Record a repair attempt."""
        self.repair_attempts += 1
        if success:
            self.repair_successes += 1

    def mark_target_reached(self) -> None:
        """Mark that the target score was reached."""
        if not self.target_reached:
            self.target_reached = True
            self.rounds_to_target = self.iterations_done
            self.time_to_target_s = time.time() - self.start_time
            self.tokens_to_target = self.total_tokens

    def finalize(self) -> None:
        """Finalize the metrics at the end of a run."""
        self.total_wall_time_s = time.time() - self.start_time

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "total_tokens": self.total_tokens,
            "total_prompt_tokens": self.total_prompt_tokens,
            "total_completion_tokens": self.total_completion_tokens,
            "total_llm_latency_ms": self.total_llm_latency_ms,
            "total_eval_time_s": round(self.total_eval_time_s, 2),
            "total_wall_time_s": round(self.total_wall_time_s, 2),
            "iterations_done": self.iterations_done,
            "valid_count": self.valid_count,
            "invalid_count": self.invalid_count,
            "valid_rate": round(self.valid_rate, 3),
            "rounds_to_target": self.rounds_to_target,
            "time_to_target_s": (
                round(self.time_to_target_s, 2)
                if self.time_to_target_s is not None
                else None
            ),
            "tokens_to_target": self.tokens_to_target,
            "repair_attempts": self.repair_attempts,
            "repair_successes": self.repair_successes,
            "repair_tokens": self.repair_tokens,
            "repair_iterations": self.repair_iterations,
            "knowledge_tokens": self.knowledge_tokens,
            "card_adoption_rate": round(self.card_adoption_rate, 3),
            "cards_offered_count": self.cards_offered_count,
            "cards_adopted_count": self.cards_adopted_count,
            "cards_adopted_valid_count": self.cards_adopted_valid_count,
            "generate_tokens": self.generate_tokens,
            "reflect_tokens": self.reflect_tokens,
            "knowledge_token_share": round(self.knowledge_token_share, 3),
            "precheck_fixes": self.precheck_fixes,
            "adapter_errors": self.adapter_errors,
            "perf_rejections": self.perf_rejections,
            "smoke_failures": self.smoke_failures,
            "smoke_fixes": self.smoke_fixes,
            "self_fix_tokens": self.self_fix_tokens,
            "smoke_time_s_total": round(self.smoke_time_s_total, 3),
            "smoke_tests": self.smoke_tests,
            "avg_smoke_time_s": (
                round(self.avg_smoke_time_s, 3) if self.avg_smoke_time_s is not None else None
            ),
            "iteration_events": self.iteration_events,
            "jev_calls": self.jev_calls,
            "jev_errors": self.jev_errors,
            "jev_fail_open": self.jev_fail_open,
            "jev_prompt_tokens": self.jev_prompt_tokens,
            "jev_completion_tokens": self.jev_completion_tokens,
            "jev_tokens": self.jev_tokens,
            "jev_latency_ms": self.jev_latency_ms,
            "jev_disabled_reason": self.jev_disabled_reason,
            "candidates_screened": self.candidates_screened,
            "evaluations_saved": self.evaluations_saved,
            "eval_time_saved_est_s": round(self.eval_time_saved_est_s, 3),
            "screen_audited": self.screen_audited,
            "screen_audit_bad": self.screen_audit_bad,
            "screen_shadow": self.screen_shadow,
            "screening_precision": self.screening_precision,
            "jev_prior_active": self.jev_prior_active,
            "analysis_calls": self.analysis_calls,
            "analysis_failures": self.analysis_failures,
            "analysis_time_s": round(self.analysis_time_s, 3),
            "analysis_nonempty_rate": round(self.analysis_nonempty_rate, 3),
            "stage_cap_hits": dict(self.stage_cap_hits),
            "expand_skipped_budget": self.expand_skipped_budget,
            "discovery_prompt_tokens": self.discovery_prompt_tokens,
            "discovery_completion_tokens": self.discovery_completion_tokens,
            "discovery_tokens": self.discovery_tokens,
            "discovery_latency_ms": self.discovery_latency_ms,
            "entailment_tokens": self.entailment_tokens,
            "discovery_token_share": round(self.discovery_token_share, 3),
            "discovered_cards_offered": self.discovered_cards_offered,
            "discovered_cards_adopted": self.discovered_cards_adopted,
            "discovered_card_adoption_rate": round(self.discovered_card_adoption_rate, 3),
            "mechanism_tokens": self.mechanism_tokens,
            "mechanism_token_share": round(self.mechanism_token_share, 3),
            "crossover_tokens": self.crossover_tokens,
        }


class Timer:
    """Context manager for timing operations."""

    def __init__(self) -> None:
        self.start_time: float = 0.0
        self.elapsed_ms: int = 0
        self.elapsed_s: float = 0.0

    def __enter__(self) -> "Timer":
        self.start_time = time.time()
        return self

    def __exit__(self, *args: Any) -> None:
        self.elapsed_s = time.time() - self.start_time
        self.elapsed_ms = int(self.elapsed_s * 1000)
