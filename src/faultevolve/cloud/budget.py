"""Token budget control for evolution runs (task-agnostic)."""

from __future__ import annotations

from collections import deque

from faultevolve.config import BudgetConfig

STAGES = ("reflect", "repair", "knowledge", "jev", "mechanism", "crossover")


class BudgetController:
    """Tracks budget usage and recommends expand/stop decisions."""

    def __init__(self, cfg: BudgetConfig) -> None:
        self.cfg = cfg
        self.best_history: list[float] = []
        self.stage_cap_hits: dict[str, int] = {s: 0 for s in STAGES}
        self._costs: deque[int] = deque(maxlen=cfg.cost_window)
        self._eval_times: deque[float] = deque(maxlen=cfg.cost_window)

    def stage_cap_tokens(self, stage: str) -> int | None:
        frac = self.cfg.stage_caps.get(stage)
        if frac is None:
            return None
        return int(frac * self.cfg.max_tokens)

    def stage_exceeded(self, stage: str, used_tokens: int) -> bool:
        cap = self.stage_cap_tokens(stage)
        return cap is not None and used_tokens >= cap

    def note_cap_hit(self, stage: str) -> bool:
        self.stage_cap_hits[stage] = self.stage_cap_hits.get(stage, 0) + 1
        return self.stage_cap_hits[stage] == 1

    def record_iteration(self, tokens: int, eval_s: float) -> None:
        self._costs.append(tokens)
        self._eval_times.append(eval_s)

    def expected_iteration_tokens(self) -> float:
        if not self._costs:
            return 0.0
        return sum(self._costs) / len(self._costs)

    def remaining_tokens(self, used: int) -> int:
        return max(0, self.cfg.max_tokens - used)

    def should_expand(self, used_tokens: int, is_top_node: bool) -> bool:
        if not self.cfg.expand_gating:
            return True
        if is_top_node:
            return True
        if not self._costs:
            return True
        remaining = self.remaining_tokens(used_tokens)
        expected = self.expected_iteration_tokens() * self.cfg.safety_factor
        return remaining >= expected

    def record_best(self, best_score: float) -> None:
        self.best_history.append(best_score)

    def check_stop(
        self,
        *,
        iterations_done: int,
        total_tokens: int,
        best_score: float,
        initial_score: float,
        noise_delta: float,
    ) -> str:
        if iterations_done < self.cfg.min_iterations_before_stop:
            return ""
        window = self.cfg.stagnation_window
        if (
            window > 0
            and len(self.best_history) >= window + 1
            and self.best_history[-1] - self.best_history[-1 - window] < noise_delta
        ):
            return "stagnation"
        cap = self.cfg.tokens_per_point_cap
        if cap is not None:
            gain = best_score - initial_score
            if gain >= noise_delta and total_tokens / gain > cap:
                return "tokens_per_point_cap"
        return ""
