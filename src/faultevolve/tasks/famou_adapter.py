"""Generic Famou-style task adapter.

This adapter works with any task directory that follows the Famou
four-file convention: evaluator.py, init.py, problem.md, prompt.md.
"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
from pathlib import Path
from typing import Any

import yaml

from faultevolve.common.codecheck import full_check
from faultevolve.tasks.protocol import EvalResult, TaskSpec


class FamouAdapter:
    """Adapter for Famou-style task directories.

    A Famou task directory contains:
    - evaluator.py: Evaluation script with evaluate() function
    - init.py: Initial solution
    - problem.md: Problem description
    - prompt.md: LLM system prompt
    - evolve.yaml (optional): Evolution configuration
    """

    REQUIRED_FILES = ["evaluator.py", "init.py", "problem.md", "prompt.md"]
    DEFAULT_TIMEOUT = 900
    DEFAULT_MIN_NOISE_DELTA = 0.5

    def __init__(self, min_noise_delta: float = DEFAULT_MIN_NOISE_DELTA) -> None:
        """Initialize the adapter.

        Args:
            min_noise_delta: Minimum noise delta threshold
        """
        self.min_noise_delta = min_noise_delta
        self._evaluator_cache: dict[str, Any] = {}

    def load_task(self, task_dir: Path) -> TaskSpec:
        """Load task specification from a directory."""
        task_dir = task_dir.resolve()

        missing = [f for f in self.REQUIRED_FILES if not (task_dir / f).exists()]
        if missing:
            raise FileNotFoundError(f"Missing required files: {missing}")

        problem_md = (task_dir / "problem.md").read_text(encoding="utf-8")
        prompt_md = (task_dir / "prompt.md").read_text(encoding="utf-8")
        init_code = (task_dir / "init.py").read_text(encoding="utf-8")
        evaluator_path = task_dir / "evaluator.py"

        config = None
        evolve_yaml = task_dir / "evolve.yaml"
        if evolve_yaml.exists():
            config = yaml.safe_load(evolve_yaml.read_text(encoding="utf-8"))

        return TaskSpec(
            task_dir=task_dir,
            problem_md=problem_md,
            prompt_md=prompt_md,
            init_code=init_code,
            evaluator_path=evaluator_path,
            config=config,
        )

    def _load_evaluator(self, evaluator_path: Path) -> Any:
        """Load evaluator module, with caching."""
        cache_key = str(evaluator_path)
        if cache_key in self._evaluator_cache:
            return self._evaluator_cache[cache_key]

        spec = importlib.util.spec_from_file_location("evaluator", evaluator_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot load evaluator from {evaluator_path}")

        module = importlib.util.module_from_spec(spec)
        sys.modules["evaluator"] = module
        spec.loader.exec_module(module)
        self._evaluator_cache[cache_key] = module
        return module

    def evaluate(self, code: str, task_spec: TaskSpec, timeout: int = DEFAULT_TIMEOUT) -> EvalResult:
        """Evaluate a candidate solution."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, encoding="utf-8"
        ) as f:
            f.write(code)
            candidate_path = f.name

        try:
            evaluator = self._load_evaluator(task_spec.evaluator_path)
            result = evaluator.evaluate(candidate_path, timeout=timeout)

            return EvalResult(
                validity=float(result.get("validity", 0)),
                combined_score=float(result.get("combined_score", 0)),
                cost_time=float(result.get("cost_time", 0)),
                error_info=str(result.get("error_info", "")),
                metric=result.get("metric", {}),
            )
        except Exception as e:
            return EvalResult(
                validity=0.0,
                combined_score=0.0,
                cost_time=0.0,
                error_info=f"Evaluation failed: {e}",
                metric={},
            )
        finally:
            Path(candidate_path).unlink(missing_ok=True)

    def get_noise_delta(self, eval_result: EvalResult) -> float:
        """Get noise delta from bootstrap std if available.

        For generic Famou tasks, uses a fixed minimum delta.
        Subclasses can override for task-specific noise estimation.
        """
        return self.min_noise_delta

    def static_check(self, code: str, task_spec: TaskSpec) -> str:
        """Perform static analysis on candidate code."""
        return full_check(code, task_spec.evaluator_path)

    def constraints(self, task_spec: TaskSpec) -> str:
        """Get task-specific constraints to inject into prompts.

        Default implementation returns empty string.
        Subclasses should override for task-specific constraints.
        """
        return ""

    def context_keywords(self, code: str) -> list[str]:
        """Extract context keywords from code for knowledge retrieval.

        Default implementation returns empty list.
        Subclasses should override for task-specific keyword extraction.
        """
        return []

    def api_notes(self) -> str:
        """Get library API notes to inject into prompts.

        Default implementation returns empty string.
        Subclasses should override for task-specific API notes.
        """
        return ""

    def smoke_test(
        self,
        code: str,
        task_spec: TaskSpec,
        timeout: int = 60,
        sample_fraction: float = 0.02,
        smoke_data_dir: Path | None = None,
    ) -> EvalResult:
        """Run a quick smoke test with short timeout.

        This is used to catch obvious errors before full evaluation.
        Base implementation runs on full data with short timeout.
        Subclasses (like HDDAdapter) can override for sampled data.

        Args:
            code: Candidate code to test
            task_spec: Task specification
            timeout: Short timeout for smoke test (default 60s)
            sample_fraction: Fraction of data to sample (ignored in base)
            smoke_data_dir: Pre-built smoke data directory (ignored in base)

        Returns:
            EvalResult from quick evaluation
        """
        return self.evaluate(code, task_spec, timeout=timeout)
