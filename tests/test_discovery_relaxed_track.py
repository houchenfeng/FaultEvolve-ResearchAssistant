"""Offline tests for KD relaxed track (R1 explore incr + R3 fdr_mode)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from faultevolve.cli import app
from faultevolve.cloud.engine import run_local_evolution
from faultevolve.config import DiscoveryConfig
from faultevolve.discovery.grading import (
    FDR_MODE_BH_CONFIRM_EBH_DISCOVER,
    FDR_MODE_BH_EBH,
    GradeInputs,
    grade_claim,
)
from faultevolve.discovery.novelty import Entailment, functional_novel
from faultevolve.discovery.pipeline import (
    EXPLORE_INCR_RULE_CI_LOW,
    EXPLORE_INCR_RULE_POINT_GAIN,
    _explore_detail,
    explore_increment_pass,
)
from faultevolve.worker.runner import FakeAdapter

REPO = Path(__file__).resolve().parents[1]
runner = CliRunner()


def _inp(**kwargs) -> GradeInputs:
    base = dict(
        ci_low=0.05,
        ci_high=0.2,
        direction_ok=True,
        temporal_ok=True,
        bh_pass=True,
        ebh_pass=True,
        functional_novel=True,
        entailment=Entailment(relation="none"),
        controls_ok=True,
    )
    base.update(kwargs)
    return GradeInputs(**base)


def test_explore_increment_pass_defaults_match_ilo_gate():
    assert explore_increment_pass(0.01, -0.1, EXPLORE_INCR_RULE_CI_LOW, 0.0) is True
    assert explore_increment_pass(0.0, 0.5, EXPLORE_INCR_RULE_CI_LOW, 0.0) is False
    assert explore_increment_pass(-0.01, 0.5, EXPLORE_INCR_RULE_CI_LOW, 0.0) is False


def test_explore_increment_pass_point_gain():
    assert explore_increment_pass(-0.1, 0.02, EXPLORE_INCR_RULE_POINT_GAIN, 0.0) is True
    assert explore_increment_pass(0.1, 0.0, EXPLORE_INCR_RULE_POINT_GAIN, 0.0) is False
    assert explore_increment_pass(0.1, -0.01, EXPLORE_INCR_RULE_POINT_GAIN, 0.0) is False


def test_point_gain_explore_incr_with_nonpositive_ci_low():
    ilo, gain = -0.02, 0.03
    assert explore_increment_pass(ilo, gain, EXPLORE_INCR_RULE_POINT_GAIN, 0.0)
    detail = _explore_detail(
        coverage=0.9,
        rho_max_abs=0.1,
        incr_gain=gain,
        incr_ci_low=ilo,
        incr_ci_high=0.05,
        explore_effect=0.06,
        explore_ci=(0.01, 0.02),
        explore_sign="+",
        power_gate_pass=False,
        lane="confirm",
        confirm_eligible=True,
        explore_incr_rule=EXPLORE_INCR_RULE_POINT_GAIN,
    )
    assert detail["incr_gain"] > 0
    assert detail["incr_ci_low"] <= 0
    assert detail["power_gate_pass"] is False


def test_grade_same_bh_no_ebh_strict_vs_relaxed():
    inp = _inp(
        ebh_pass=False,
        entailment=Entailment(relation="same", card_id="FE01"),
    )
    g_strict, _, _ = grade_claim(inp, fdr_mode=FDR_MODE_BH_EBH)
    g_relaxed, confirms, _ = grade_claim(inp, fdr_mode=FDR_MODE_BH_CONFIRM_EBH_DISCOVER)
    assert g_strict.value == "undetermined"
    assert g_relaxed.value == "confirmed"
    assert confirms == "FE01"


def test_grade_none_novel_no_ebh_never_discovered():
    inp = _inp(ebh_pass=False, entailment=Entailment(relation="none"))
    for mode in (FDR_MODE_BH_EBH, FDR_MODE_BH_CONFIRM_EBH_DISCOVER):
        g, _, _ = grade_claim(inp, fdr_mode=mode)
        assert g.value == "undetermined"


def test_discovered_blocked_when_not_functionally_novel():
    cfg = DiscoveryConfig()
    assert functional_novel(0.9, 0.1, cfg) is False
    assert functional_novel(0.5, -0.01, cfg) is False
    inp = _inp(
        entailment=Entailment(relation="none"),
        functional_novel=functional_novel(0.9, 0.1, cfg),
    )
    g, _, _ = grade_claim(inp, fdr_mode=FDR_MODE_BH_CONFIRM_EBH_DISCOVER)
    assert g.value == "undetermined"


def _task(tmp_path: Path) -> Path:
    task = tmp_path / "task"
    task.mkdir()
    (task / "init.py").write_text("# init", encoding="utf-8")
    (task / "problem.md").write_text("# p", encoding="utf-8")
    (task / "prompt.md").write_text("# prompt", encoding="utf-8")
    (task / "evaluator.py").write_text(
        "def evaluate(p, **kw):\n"
        "    return {'validity': 1, 'combined_score': 22, 'cost_time': 1, 'error_info': '', 'metric': {}}\n",
        encoding="utf-8",
    )
    (task / "evolve.yaml").write_text(
        "discovery:\n  enabled: true\n  min_insight_z: 0.1\n  bootstrap_b: 50\n  neg_control_repeats: 1\n",
        encoding="utf-8",
    )
    return task


def test_discover_factors_default_audit_track_fields(tmp_path: Path):
    task = _task(tmp_path)
    adapter = FakeAdapter()
    adapter.set_results(
        [{"validity": 1.0, "combined_score": 22.0 + i, "cost_time": 1.0, "metric": {}} for i in range(6)]
    )
    runs = task / ".fe" / "runs"
    with patch("faultevolve.tasks.create_benchmark_adapter", return_value=adapter):
        evo = run_local_evolution(
            task_dir=task,
            mock=True,
            max_iterations=3,
            runs_dir=runs,
            adapter=adapter,
        )
    run_id = evo["experiment_id"]
    lib = REPO / "tests/fixtures/toy_factors.jsonl"
    with patch("faultevolve.tasks.create_benchmark_adapter", return_value=adapter):
        res = runner.invoke(
            app,
            [
                "discover",
                "factors",
                str(task),
                "--run-id",
                run_id,
                "--mock",
                "--json",
                "--runs-dir",
                str(runs),
                "--library",
                str(lib),
                "--max-candidates",
                "3",
                "--max-confirm",
                "2",
            ],
        )
    assert res.exit_code == 0
    payload = json.loads(res.stdout)
    assert payload["track_label"] == ""
    assert payload["explore_incr_rule"] == "ci_low"
    assert payload["min_incr_ci_low"] == 0.0
    assert payload["fdr_mode"] == "bh_ebh"
    audit = json.loads(
        (Path(payload["artifacts_dir"]) / "discovery" / "data_audit.json").read_text(encoding="utf-8")
    )
    assert audit["explore_incr_rule"] == "ci_low"
    assert audit["fdr_mode"] == "bh_ebh"
    summary = json.loads(
        (Path(payload["artifacts_dir"]) / "discovery" / "funnel_summary.json").read_text(
            encoding="utf-8"
        )
    )
    assert summary["explore_incr_rule"] == "ci_low"


def test_cli_default_library_still_hdd_v1():
    text = (REPO / "src/faultevolve/cli.py").read_text(encoding="utf-8")
    assert 'Path("src/faultevolve/discovery/factor_library/hdd_v1.jsonl")' in text


@pytest.mark.parametrize(
    "rule,gain,ilo,stage",
    [
        ("ci_low", 0.1, -0.01, "explore_no_increment"),
        ("point_gain", 0.1, -0.01, "explore_incr"),
        ("point_gain", -0.01, 0.1, "explore_no_increment"),
    ],
)
def test_funnel_stage_from_incr_rules(rule, gain, ilo, stage):
    incr_pass = explore_increment_pass(
        ilo,
        gain,
        rule,
        0.0,
    )
    if not incr_pass:
        assert stage == "explore_no_increment"
    elif rule == "point_gain" and gain > 0 and ilo <= 0:
        assert stage == "explore_incr"
