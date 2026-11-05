"""Tests for metering utilities."""

import time

import pytest

from faultevolve.common.metering import CallMetrics, NodeMetrics, RunMetrics, Timer


class TestCallMetrics:
    """Tests for CallMetrics dataclass."""

    def test_default_values(self):
        """Test default values are zero/false."""
        metrics = CallMetrics()

        assert metrics.prompt_tokens == 0
        assert metrics.completion_tokens == 0
        assert metrics.latency_ms == 0
        assert metrics.cached is False

    def test_custom_values(self):
        """Test setting custom values."""
        metrics = CallMetrics(
            prompt_tokens=100,
            completion_tokens=200,
            latency_ms=500,
            cached=True,
        )

        assert metrics.prompt_tokens == 100
        assert metrics.completion_tokens == 200
        assert metrics.latency_ms == 500
        assert metrics.cached is True


class TestNodeMetrics:
    """Tests for NodeMetrics dataclass."""

    def test_default_values(self):
        """Test default values."""
        metrics = NodeMetrics()

        assert metrics.generation_tokens == 0
        assert metrics.reflection_tokens == 0
        assert metrics.generation_latency_ms == 0
        assert metrics.reflection_latency_ms == 0
        assert metrics.eval_time_s == 0.0
        assert metrics.total_time_s == 0.0


class TestRunMetrics:
    """Tests for RunMetrics class."""

    def test_total_tokens(self):
        """Test total_tokens property."""
        metrics = RunMetrics()
        metrics.total_prompt_tokens = 100
        metrics.total_completion_tokens = 200

        assert metrics.total_tokens == 300

    def test_valid_rate_with_no_evals(self):
        """Test valid_rate returns 0.0 when no evaluations done."""
        metrics = RunMetrics()

        assert metrics.valid_rate == 0.0

    def test_valid_rate_calculation(self):
        """Test valid_rate calculation."""
        metrics = RunMetrics()
        metrics.valid_count = 7
        metrics.invalid_count = 3

        assert metrics.valid_rate == 0.7

    def test_add_llm_call(self):
        """Test adding LLM call metrics."""
        metrics = RunMetrics()
        call_metrics = CallMetrics(
            prompt_tokens=50,
            completion_tokens=100,
            latency_ms=200,
        )

        metrics.add_llm_call(call_metrics)

        assert metrics.total_prompt_tokens == 50
        assert metrics.total_completion_tokens == 100
        assert metrics.total_llm_latency_ms == 200

    def test_add_eval(self):
        """Test adding evaluation metrics."""
        metrics = RunMetrics()

        metrics.add_eval(time_s=1.5, valid=True)
        metrics.add_eval(time_s=2.0, valid=False)

        assert metrics.total_eval_time_s == 3.5
        assert metrics.valid_count == 1
        assert metrics.invalid_count == 1
        assert metrics.iterations_done == 2

    def test_jev_stage_counts_in_total(self):
        metrics = RunMetrics()
        metrics.add_llm_call(CallMetrics(prompt_tokens=4, completion_tokens=2), "jev")
        assert metrics.total_tokens == 6
        assert metrics.jev_tokens == 6
        assert metrics.generate_tokens == metrics.repair_tokens == metrics.reflect_tokens == 0

    def test_screening_precision_null_and_fraction(self):
        metrics = RunMetrics()
        assert metrics.screening_precision is None
        metrics.screen_audited = 3
        metrics.screen_audit_bad = 2
        assert metrics.screening_precision == pytest.approx(2 / 3)

    def test_defer_flush_does_not_repeat_iteration(self):
        metrics = RunMetrics(iterations_done=4)
        metrics.add_eval(2.0, True, count_iteration=False)
        assert metrics.iterations_done == 4
        assert metrics.valid_count == 1

    def test_mark_target_reached(self):
        """Test marking target as reached."""
        metrics = RunMetrics()
        metrics.iterations_done = 5
        metrics.total_prompt_tokens = 500
        metrics.total_completion_tokens = 1000

        metrics.mark_target_reached()

        assert metrics.target_reached is True
        assert metrics.rounds_to_target == 5
        assert metrics.tokens_to_target == 1500
        assert metrics.time_to_target_s is not None

    def test_mark_target_reached_only_once(self):
        """Test that target can only be marked once."""
        metrics = RunMetrics()
        metrics.iterations_done = 3
        metrics.total_prompt_tokens = 300
        metrics.total_completion_tokens = 600

        metrics.mark_target_reached()
        first_rounds = metrics.rounds_to_target

        metrics.iterations_done = 10
        metrics.total_prompt_tokens = 1000
        metrics.total_completion_tokens = 2000

        metrics.mark_target_reached()

        assert metrics.rounds_to_target == first_rounds
        assert metrics.tokens_to_target == 900

    def test_to_target_metrics_null_when_not_reached(self):
        """Test that to-target metrics are null when target not reached."""
        metrics = RunMetrics()
        metrics.iterations_done = 10
        metrics.total_prompt_tokens = 1000
        metrics.total_completion_tokens = 2000
        metrics.finalize()

        result = metrics.to_dict()

        assert result["rounds_to_target"] is None
        assert result["time_to_target_s"] is None
        assert result["tokens_to_target"] is None

    def test_to_target_metrics_populated_when_reached(self):
        """Test that to-target metrics are populated when target reached."""
        metrics = RunMetrics()
        metrics.iterations_done = 5
        metrics.total_prompt_tokens = 500
        metrics.total_completion_tokens = 1000

        metrics.mark_target_reached()
        metrics.finalize()

        result = metrics.to_dict()

        assert result["rounds_to_target"] == 5
        assert result["time_to_target_s"] is not None
        assert result["tokens_to_target"] == 1500

    def test_zero_time_to_target_is_not_reported_as_missing(self):
        """0.0s to target is a real measurement, not a missing one.

        time.time() granularity is coarse on Windows, so marking the target
        right after construction measures exactly 0.0.
        """
        metrics = RunMetrics()
        metrics.time_to_target_s = 0.0

        assert metrics.to_dict()["time_to_target_s"] == 0.0

    def test_finalize_sets_wall_time(self):
        """Test that finalize sets wall time."""
        metrics = RunMetrics()
        time.sleep(0.01)
        metrics.finalize()

        assert metrics.total_wall_time_s > 0

    def test_to_dict_serialization(self):
        """Test to_dict returns all expected fields."""
        metrics = RunMetrics()
        metrics.total_prompt_tokens = 100
        metrics.total_completion_tokens = 200
        metrics.total_llm_latency_ms = 500
        metrics.total_eval_time_s = 10.5
        metrics.iterations_done = 5
        metrics.valid_count = 4
        metrics.invalid_count = 1
        metrics.finalize()

        result = metrics.to_dict()

        assert "total_tokens" in result
        assert "total_prompt_tokens" in result
        assert "total_completion_tokens" in result
        assert "total_llm_latency_ms" in result
        assert "total_eval_time_s" in result
        assert "total_wall_time_s" in result
        assert "iterations_done" in result
        assert "valid_count" in result
        assert "invalid_count" in result
        assert "valid_rate" in result
        assert "rounds_to_target" in result
        assert "time_to_target_s" in result
        assert "tokens_to_target" in result

        assert result["total_tokens"] == 300
        assert result["valid_rate"] == 0.8
        assert result["iterations_done"] == 5


    def test_analysis_metrics_in_summary(self):
        metrics = RunMetrics()
        metrics.analysis_calls = 2
        metrics.analysis_failures = 1
        metrics.analysis_nonempty_count = 1
        metrics.analysis_time_s = 1.25
        result = metrics.to_dict()
        assert result["analysis_calls"] == 2
        assert result["analysis_failures"] == 1
        assert result["analysis_time_s"] == 1.25
        assert result["analysis_nonempty_rate"] == 0.5

    def test_analysis_does_not_change_token_or_eval_totals(self):
        metrics = RunMetrics()
        metrics.analysis_calls = 3
        metrics.analysis_failures = 1
        metrics.analysis_time_s = 2.0
        assert metrics.total_tokens == 0
        assert metrics.total_eval_time_s == 0.0


class TestTimer:
    """Tests for Timer context manager."""

    def test_timer_measures_elapsed_time(self):
        """Test that timer measures elapsed time correctly."""
        with Timer() as timer:
            time.sleep(0.05)

        assert timer.elapsed_ms >= 50
        assert timer.elapsed_s >= 0.05

    def test_timer_elapsed_zero_before_exit(self):
        """Test that elapsed is zero before exiting context."""
        timer = Timer()
        timer.__enter__()

        assert timer.elapsed_ms == 0
        assert timer.elapsed_s == 0.0

        time.sleep(0.01)
        timer.__exit__(None, None, None)

        assert timer.elapsed_ms >= 10
        assert timer.elapsed_s >= 0.01
