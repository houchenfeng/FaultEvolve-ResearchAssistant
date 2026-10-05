"""Local evaluation runner for FaultEvolve.

Runs candidate solutions through the task evaluator.
"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from faultevolve.tasks.protocol import DiscoveryFrames


def load_evaluator(evaluator_path: Path) -> Any:
    """Load an evaluator module from a path.

    Args:
        evaluator_path: Path to evaluator.py

    Returns:
        The loaded evaluator module
    """
    spec = importlib.util.spec_from_file_location("evaluator", evaluator_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load evaluator from {evaluator_path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules["evaluator"] = module
    spec.loader.exec_module(module)
    return module


def run_candidate(
    code: str,
    evaluator_path: Path,
    timeout: int = 900,
    split: str = "val",
) -> dict[str, Any]:
    """Run a candidate solution through the evaluator.

    Args:
        code: Candidate Python code
        evaluator_path: Path to evaluator.py
        timeout: Evaluation timeout in seconds
        split: Data split to use

    Returns:
        Evaluation result dictionary
    """
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", delete=False, encoding="utf-8"
    ) as f:
        f.write(code)
        candidate_path = f.name

    try:
        evaluator = load_evaluator(evaluator_path)
        result = evaluator.evaluate(candidate_path, timeout=timeout, split=split)
        return dict(result)
    finally:
        Path(candidate_path).unlink(missing_ok=True)


class FakeAdapter:
    """Fake task adapter for testing.

    Returns scripted evaluation results for deterministic testing.
    """

    discovery_planted_strength: float = 1.0

    def __init__(self) -> None:
        """Initialize the fake adapter."""
        self._results: list[dict[str, Any]] = []
        self._call_count = 0

    def set_results(self, results: list[dict[str, Any]]) -> None:
        """Set the list of results to return.

        Args:
            results: List of result dictionaries
        """
        self._results = results
        self._call_count = 0

    def evaluate(
        self,
        code: str,
        task_spec: Any,
        timeout: int = 900,
    ) -> "FakeEvalResult":
        """Return a scripted evaluation result.

        Args:
            code: Candidate code (ignored)
            task_spec: Task spec (ignored)
            timeout: Timeout (ignored)

        Returns:
            Scripted or default result
        """
        if self._results and self._call_count < len(self._results):
            result = self._results[self._call_count]
        else:
            result = self._generate_default_result(self._call_count)

        self._call_count += 1

        return FakeEvalResult(
            validity=result.get("validity", 1.0),
            combined_score=result.get("combined_score", 20.0 + self._call_count * 0.5),
            cost_time=result.get("cost_time", 1.0),
            error_info=result.get("error_info", ""),
            metric=result.get("metric", {}),
        )

    def _generate_default_result(self, call_number: int) -> dict[str, Any]:
        """Generate a default result."""
        base_score = 22.0
        delta = (call_number % 5) * 0.3 - 0.5

        return {
            "validity": 1.0,
            "combined_score": base_score + delta,
            "cost_time": 2.0 + call_number * 0.1,
            "error_info": "",
            "metric": {
                "f1": 0.25 + delta * 0.01,
                "f1_p10": 0.22 + delta * 0.01,
                "f1_boot_std": 0.02,
                "auprc": 0.20 + delta * 0.005,
                "recall_at_far": 0.15 + delta * 0.01,
                "false_alarm_rate": 0.003,
            },
        }

    def get_noise_delta(self, eval_result: "FakeEvalResult") -> float:
        """Get noise delta from the result."""
        f1_boot_std = eval_result.metric.get("f1_boot_std", 0.02)
        return max(0.5, f1_boot_std * 50)

    def static_check(self, code: str, task_spec: Any) -> str:
        """Static check - always passes in fake adapter."""
        return ""

    def load_task(self, task_dir: Path) -> "FakeTaskSpec":
        """Load a fake task spec."""
        return FakeTaskSpec(task_dir=task_dir)

    def constraints(self, task_spec: Any) -> str:
        """Return empty constraints for testing."""
        return ""

    def context_keywords(self, code: str) -> list[str]:
        """Return empty keywords for testing."""
        return []

    def api_notes(self) -> str:
        """Return empty API notes for testing."""
        return ""

    def discovery_frames(self, task_spec: Any) -> DiscoveryFrames:
        rng = np.random.default_rng(20260926)
        n_units = 600
        rows_hist = []
        labels = []
        pos_rate = 0.3
        y = (rng.random(n_units) < pos_rate).astype(int)
        for i in range(n_units):
            unit = f"u{i:04d}"
            labels.append({"unit": unit, "label": int(y[i])})
            for t in range(20):
                m0 = rng.normal()
                m1 = rng.normal() + (self.discovery_planted_strength if y[i] else 0.0)
                m2 = rng.normal()
                m3 = rng.normal()
                rows_hist.append({"unit": unit, "t": t, "m0": m0, "m1": m1, "m2": m2, "m3": m3})
        history = pd.DataFrame(rows_hist)
        label_df = pd.DataFrame(labels)
        n_units = len(label_df)
        envs = np.array([f"e{i % 4}" for i in range(n_units)])
        env_frame = pd.DataFrame({
            "env": envs,
            "conf": envs,
            "time": np.arange(n_units),
            "censor": 0,
        })
        return DiscoveryFrames(
            labels=label_df,
            history=history,
            unit_col="unit",
            time_col="t",
            label_col="label",
            baseline_cols=["m0", "m2", "m3"],
            schema_note="synthetic toy columns m0..m3",
            env_frame=env_frame,
        )

    def cleanup_discovery_data(self) -> None:
        return None


class FakeEvalResult:
    """Fake evaluation result for testing."""

    def __init__(
        self,
        validity: float = 1.0,
        combined_score: float = 20.0,
        cost_time: float = 1.0,
        error_info: str = "",
        metric: dict[str, Any] | None = None,
    ) -> None:
        self.validity = validity
        self.combined_score = combined_score
        self.cost_time = cost_time
        self.error_info = error_info
        self.metric = metric or {}

    @property
    def is_valid(self) -> bool:
        return self.validity >= 1.0


class FakeTaskSpec:
    """Fake task specification for testing."""

    def __init__(
        self,
        task_dir: Path | None = None,
        problem_md: str = "Test problem",
        prompt_md: str = "Test prompt",
        init_code: str = "# Test init code",
        evaluator_path: Path | None = None,
    ) -> None:
        self.task_dir = task_dir or Path(".")
        self.problem_md = problem_md
        self.prompt_md = prompt_md
        self.init_code = init_code
        self.evaluator_path = evaluator_path or (task_dir / "evaluator.py" if task_dir else Path("evaluator.py"))
        self.config = None
