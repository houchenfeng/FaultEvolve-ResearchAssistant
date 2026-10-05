"""Task adapter protocol for FaultEvolve.

This module defines the interfaces that task adapters must implement,
making the evolution engine task-agnostic.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


@dataclass
class TaskSpec:
    """Specification of a task for evolution.

    Attributes:
        task_dir: Path to the task directory
        problem_md: Content of problem.md
        prompt_md: Content of prompt.md
        init_code: Content of init.py
        evaluator_path: Path to evaluator.py
        config: Optional configuration from evolve.yaml
    """
    task_dir: Path
    problem_md: str
    prompt_md: str
    init_code: str
    evaluator_path: Path
    config: dict[str, Any] | None = None


@dataclass
class EvalResult:
    """Result from evaluating a candidate.

    Attributes:
        validity: 1.0 if valid, 0.0 otherwise
        combined_score: The main score to optimize
        cost_time: Time taken to evaluate
        error_info: Error message if any
        metric: Dictionary of detailed metrics
    """
    validity: float
    combined_score: float
    cost_time: float
    error_info: str
    metric: dict[str, Any]

    @property
    def is_valid(self) -> bool:
        return self.validity >= 1.0


@runtime_checkable
class TaskAdapter(Protocol):
    """Protocol for task adapters.

    Task adapters provide the interface between the evolution engine
    and specific evaluation tasks (e.g., HDD failure prediction).
    """

    def load_task(self, task_dir: Path) -> TaskSpec:
        """Load task specification from a directory.

        Args:
            task_dir: Path to the task directory

        Returns:
            TaskSpec containing all task information

        Raises:
            FileNotFoundError: If required files are missing
            ValueError: If task specification is invalid
        """
        ...

    def evaluate(self, code: str, task_spec: TaskSpec, timeout: int = 900) -> EvalResult:
        """Evaluate a candidate solution.

        Args:
            code: The candidate Python code to evaluate
            task_spec: The task specification
            timeout: Maximum time allowed for evaluation

        Returns:
            EvalResult containing validity, score, and metrics
        """
        ...

    def get_noise_delta(self, eval_result: EvalResult) -> float:
        """Get the noise threshold (delta) for determining significance.

        This is used to determine if a score change is significant
        or within noise bounds.

        Args:
            eval_result: The evaluation result

        Returns:
            The noise delta threshold
        """
        ...

    def static_check(self, code: str, task_spec: TaskSpec) -> str:
        """Perform static analysis on candidate code.

        Args:
            code: The candidate code to check
            task_spec: The task specification

        Returns:
            Empty string if valid, error message otherwise
        """
        ...

    def constraints(self, task_spec: TaskSpec) -> str:
        """Get task-specific constraints to inject into prompts.

        The returned text is always injected into refine and repair prompts
        to help the LLM avoid generating invalid code.

        Args:
            task_spec: The task specification

        Returns:
            Constraints text (empty string if no constraints)
        """
        ...

    def context_keywords(self, code: str) -> list[str]:
        """Extract context keywords from code for knowledge retrieval.

        Task-specific keyword extraction for matching knowledge cards.
        For example, HDD tasks may extract SMART attribute names like
        'smart_5', 'smart_187', etc.

        Args:
            code: The current solution code

        Returns:
            List of keywords for knowledge card matching
        """
        ...

    def api_notes(self) -> str:
        """Get library API notes to inject into prompts.

        Returns notes about common API pitfalls that differ between
        library versions. For example, LightGBM 4.x no longer supports
        fit(early_stopping_rounds=...) and requires callbacks instead.

        These notes are injected alongside constraints into both refine
        and repair prompts.

        Returns:
            API notes text (empty string if none)
        """
        ...


@runtime_checkable
class ObjectiveSpec(Protocol):
    """Optional protocol for multi-objective selection metrics."""

    def objectives(self) -> list[str]:
        """Ranking quality metric keys (higher is better)."""
        ...

    def threshold_objectives(self) -> list[str]:
        """Threshold quality metric keys (higher is better)."""
        ...

    def noise_metric(self) -> str:
        """Noise metric key (lower is better)."""
        ...


@runtime_checkable
class ErrorProfiler(Protocol):
    """Optional protocol for dev-set error profiling on evaluated candidates."""

    def analyze(self, code: str, task_spec: TaskSpec, timeout: int) -> dict[str, Any]:
        """Run candidate on a dev split and return aggregated error profile."""
        ...


@runtime_checkable
class ObjectiveBriefProvider(Protocol):
    """Optional protocol for evaluator-aware objective text in generation prompts."""

    def objective_brief(self, task_spec: TaskSpec) -> str:
        """Return a short objective / trade-off brief for refine prompts."""
        ...


@dataclass
class DiscoveryFrames:
    """Frames for knowledge discovery.

    ``labels`` holds **one row per unit**.  ``history`` does NOT: it is the
    per-(unit, time) panel, i.e. a LONG frame with many rows per unit (the HDD
    adapter caps it at ~16 rows/unit).  Getting this backwards is the single
    most common way a generated ``feature(history)`` breaks, so the distinction
    is stated explicitly here and again in ``schema_note``.
    """

    labels: Any
    history: Any
    unit_col: str
    time_col: str
    label_col: str = "label"
    baseline_cols: list[str] | None = None
    baseline_lag_rows: int = 14
    schema_note: str = ""
    env_frame: Any = None
    # Machine-readable description of the *actual* `history` frame, derived
    # from the data at load time (columns, dtypes, rows-per-unit, contract).
    # Dumped to <artifacts>/discovery/history_schema.json.
    history_schema: dict | None = None

    def __post_init__(self) -> None:
        if self.baseline_cols is None:
            self.baseline_cols = []


@runtime_checkable
class DiscoveryDataProvider(Protocol):
    """Optional protocol for discovery data frames."""

    def discovery_frames(self, task_spec: TaskSpec) -> DiscoveryFrames:
        """Return label/history frames for claim testing."""
        ...


@runtime_checkable
class FactorLibraryProvider(Protocol):
    """Optional protocol for the factor-discovery layer (KD1-F/G).

    Kept separate from :class:`DiscoveryDataProvider` on purpose: the latter is
    probed with ``isinstance`` in two places, and widening a ``runtime_checkable``
    protocol makes existing adapters fail that probe.

    Both methods are optional -- the discovery package works without them -- but a
    task that ships a factor library should provide the columns, so the library is
    validated against real data before anything runs.
    """

    def discovery_input_columns(self) -> tuple[str, ...]:
        """Columns a factor's ``inputs`` may name (unit identifiers excluded)."""
        ...

    def factor_mock_feature(self) -> tuple[str, str]:
        """``(feature_code, title)`` standing in for an LLM proposal offline."""
        ...


@dataclass
class DataStatus:
    """Read-only data directory readiness (no label/holdout file reads)."""

    ok: bool
    data_dir: str
    missing: list[str]
    message: str


@runtime_checkable
class DataStatusProvider(Protocol):
    """Optional protocol for reporting prepared public split files."""

    def data_status(self, task_dir: Path) -> DataStatus:
        """Return existence checks for required public data files."""
        ...
