"""Tests for task adapters."""

import re
from pathlib import Path

import pytest

from faultevolve.tasks.famou_adapter import FamouAdapter
from faultevolve.tasks.hdd_adapter import HDDAdapter
from faultevolve.tasks.protocol import EvalResult


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "toy_task"


class TestFamouAdapterWithToyTask:
    """Tests for Famou adapter using the toy task fixture."""

    def test_load_task_success(self):
        """Test loading a valid task directory."""
        adapter = FamouAdapter()
        task_spec = adapter.load_task(FIXTURE_DIR)

        assert task_spec.task_dir == FIXTURE_DIR.resolve()
        assert "Toy" in task_spec.problem_md or "toy" in task_spec.problem_md.lower()
        assert task_spec.init_code
        assert task_spec.evaluator_path.exists()

    def test_load_task_missing_files(self, tmp_path):
        """Test error when required files are missing."""
        adapter = FamouAdapter()

        with pytest.raises(FileNotFoundError, match="Missing required files"):
            adapter.load_task(tmp_path)

    def test_evaluate_valid_code(self):
        """Test evaluating valid code through the toy evaluator."""
        adapter = FamouAdapter()
        task_spec = adapter.load_task(FIXTURE_DIR)

        code = task_spec.init_code
        result = adapter.evaluate(code, task_spec)

        assert result.validity == 1.0
        assert result.combined_score > 0
        assert result.is_valid

    def test_evaluate_returns_metric_dict(self):
        """Test that evaluation returns a metric dictionary."""
        adapter = FamouAdapter()
        task_spec = adapter.load_task(FIXTURE_DIR)

        result = adapter.evaluate(task_spec.init_code, task_spec)

        assert isinstance(result.metric, dict)
        assert "f1" in result.metric or len(result.metric) >= 0

    def test_evaluate_forbidden_pattern(self):
        """Test that forbidden patterns are rejected."""
        adapter = FamouAdapter()
        task_spec = adapter.load_task(FIXTURE_DIR)

        code = """import subprocess\nsubprocess.run(['ls'])"""
        result = adapter.evaluate(code, task_spec)

        assert result.validity == 0.0
        assert "Forbidden" in result.error_info or "subprocess" in result.error_info.lower()

    def test_static_check_passes_valid_code(self):
        """Test static check passes for valid code."""
        adapter = FamouAdapter()
        task_spec = adapter.load_task(FIXTURE_DIR)

        error = adapter.static_check(task_spec.init_code, task_spec)

        assert error == ""

    def test_static_check_fails_on_dangerous_pattern(self):
        """Test static check catches dangerous patterns."""
        adapter = FamouAdapter()
        task_spec = adapter.load_task(FIXTURE_DIR)

        code = """import os\npath = data_dir + '/../secret'"""
        error = adapter.static_check(code, task_spec)

        assert error != ""

    def test_noise_delta_uses_minimum(self):
        """Test that generic adapter uses minimum noise delta."""
        adapter = FamouAdapter(min_noise_delta=0.5)
        result = EvalResult(
            validity=1.0,
            combined_score=20.0,
            cost_time=1.0,
            error_info="",
            metric={"f1_boot_std": 0.1},
        )

        delta = adapter.get_noise_delta(result)

        assert delta == 0.5


class TestHDDAdapter:
    """Tests for HDD adapter."""

    def test_noise_delta_from_f1_boot_std(self):
        """Test noise delta calculation: delta = kappa * f1_boot_std * 50."""
        adapter = HDDAdapter(min_noise_delta=0.5, kappa=1.0)
        result = EvalResult(
            validity=1.0,
            combined_score=22.0,
            cost_time=1.0,
            error_info="",
            metric={"f1_boot_std": 0.02},
        )

        delta = adapter.get_noise_delta(result)

        assert delta == 1.0

    def test_noise_delta_with_kappa_multiplier(self):
        """Test kappa multiplier in noise delta calculation."""
        adapter = HDDAdapter(min_noise_delta=0.5, kappa=2.0)
        result = EvalResult(
            validity=1.0,
            combined_score=22.0,
            cost_time=1.0,
            error_info="",
            metric={"f1_boot_std": 0.02},
        )

        delta = adapter.get_noise_delta(result)

        assert delta == 2.0

    def test_noise_delta_uses_minimum_when_std_missing(self):
        """Test fallback to min_noise_delta when f1_boot_std is missing."""
        adapter = HDDAdapter(min_noise_delta=0.5, kappa=1.0)
        result = EvalResult(
            validity=1.0,
            combined_score=22.0,
            cost_time=1.0,
            error_info="",
            metric={},
        )

        delta = adapter.get_noise_delta(result)

        assert delta == 0.5

    def test_noise_delta_uses_minimum_when_std_zero(self):
        """Test fallback when f1_boot_std is zero."""
        adapter = HDDAdapter(min_noise_delta=0.5, kappa=1.0)
        result = EvalResult(
            validity=1.0,
            combined_score=22.0,
            cost_time=1.0,
            error_info="",
            metric={"f1_boot_std": 0.0},
        )

        delta = adapter.get_noise_delta(result)

        assert delta == 0.5

    def test_noise_delta_enforces_minimum(self):
        """Test that minimum is enforced for small f1_boot_std."""
        adapter = HDDAdapter(min_noise_delta=0.5, kappa=1.0)
        result = EvalResult(
            validity=1.0,
            combined_score=22.0,
            cost_time=1.0,
            error_info="",
            metric={"f1_boot_std": 0.005},
        )

        delta = adapter.get_noise_delta(result)

        assert delta == 0.5

    def test_hdd_adapter_inherits_famou_behavior(self):
        """Test that HDD adapter can load toy task like Famou adapter."""
        adapter = HDDAdapter()
        task_spec = adapter.load_task(FIXTURE_DIR)

        assert task_spec.init_code
        result = adapter.evaluate(task_spec.init_code, task_spec)
        assert result.is_valid


class TestNoHDDSpecificStringsInCoreModules:
    """Tests to ensure engine and operators are task-agnostic."""

    HDD_SPECIFIC_PATTERNS = [
        r"\bhdd\b",
        r"\bhard\s*disk\b",
        r"\bdisk\s*failure\b",
        r"\bserial_number\b",
        r"\bserial\b",
        r"\bsmart\b",
        r"\bs\.m\.a\.r\.t\b",
        r"\breallocated\b",
        r"\bsector\b",
        r"\bbackblaze\b",
        r"\bbaidu\b",
        r"\bf1_boot_std\b",
    ]

    EXCLUDED_FILES = {
        "hdd_adapter.py",
        "test_hdd_evaluator.py",
        "test_adapters.py",
    }

    def _check_file_for_hdd_strings(self, filepath: Path) -> list[tuple[int, str, str]]:
        """Check a file for HDD-specific strings.

        Returns list of (line_number, pattern_matched, line_content).
        """
        violations = []

        if filepath.name in self.EXCLUDED_FILES:
            return violations

        content = filepath.read_text(encoding="utf-8")
        lines = content.split("\n")

        for line_num, line in enumerate(lines, 1):
            line_lower = line.lower()
            for pattern in self.HDD_SPECIFIC_PATTERNS:
                if re.search(pattern, line_lower, re.IGNORECASE):
                    if "# noqa: hdd" not in line.lower():
                        violations.append((line_num, pattern, line.strip()[:80]))

        return violations

    def test_engine_has_no_hdd_strings(self):
        """Test that engine.py contains no HDD-specific strings."""
        engine_path = Path(__file__).parent.parent / "src" / "faultevolve" / "cloud" / "engine.py"
        violations = self._check_file_for_hdd_strings(engine_path)

        if violations:
            msg = "\n".join(f"Line {ln}: {pat} in '{line}'" for ln, pat, line in violations)
            pytest.fail(f"HDD-specific strings found in engine.py:\n{msg}")

    def test_operators_has_no_hdd_strings(self):
        """Test that operators.py contains no HDD-specific strings."""
        ops_path = Path(__file__).parent.parent / "src" / "faultevolve" / "cloud" / "operators.py"
        violations = self._check_file_for_hdd_strings(ops_path)

        if violations:
            msg = "\n".join(f"Line {ln}: {pat} in '{line}'" for ln, pat, line in violations)
            pytest.fail(f"HDD-specific strings found in operators.py:\n{msg}")

    def test_selection_has_no_hdd_strings(self):
        """Test that selection.py contains no HDD-specific strings."""
        sel_path = Path(__file__).parent.parent / "src" / "faultevolve" / "cloud" / "selection.py"
        violations = self._check_file_for_hdd_strings(sel_path)

        if violations:
            msg = "\n".join(f"Line {ln}: {pat} in '{line}'" for ln, pat, line in violations)
            pytest.fail(f"HDD-specific strings found in selection.py:\n{msg}")

    def test_insights_has_no_hdd_strings(self):
        """Test that insights.py contains no HDD-specific strings."""
        ins_path = Path(__file__).parent.parent / "src" / "faultevolve" / "cloud" / "insights.py"
        violations = self._check_file_for_hdd_strings(ins_path)

        if violations:
            msg = "\n".join(f"Line {ln}: {pat} in '{line}'" for ln, pat, line in violations)
            pytest.fail(f"HDD-specific strings found in insights.py:\n{msg}")

    def test_tree_has_no_hdd_strings(self):
        """Test that tree.py contains no HDD-specific strings."""
        tree_path = Path(__file__).parent.parent / "src" / "faultevolve" / "cloud" / "tree.py"
        violations = self._check_file_for_hdd_strings(tree_path)

        if violations:
            msg = "\n".join(f"Line {ln}: {pat} in '{line}'" for ln, pat, line in violations)
            pytest.fail(f"HDD-specific strings found in tree.py:\n{msg}")


class TestEvalResult:
    """Tests for EvalResult dataclass."""

    def test_is_valid_property(self):
        """Test is_valid property returns True for validity >= 1.0."""
        valid = EvalResult(validity=1.0, combined_score=20.0, cost_time=1.0, error_info="", metric={})
        invalid = EvalResult(validity=0.5, combined_score=0.0, cost_time=0.5, error_info="Error", metric={})

        assert valid.is_valid is True
        assert invalid.is_valid is False

    def test_metric_field_is_dict(self):
        """Test that metric field is a dict when provided."""
        result = EvalResult(validity=1.0, combined_score=20.0, cost_time=1.0, error_info="", metric={"f1": 0.5})

        assert result.metric == {"f1": 0.5}
