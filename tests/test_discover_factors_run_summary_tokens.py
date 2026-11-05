"""run_summary token accounting for fe discover factors (KD1-H §4 metering fix)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from faultevolve.cli import app
from faultevolve.cloud.engine import run_local_evolution
from faultevolve.worker.runner import FakeAdapter

from tests.test_cli_discover_factors import _task

runner = CliRunner()
REPO = Path(__file__).resolve().parents[1]


def test_discover_factors_run_summary_total_tokens_includes_entailment(tmp_path):
    """After mock entailment calls, total_tokens matches metrics.total_tokens, not discovery-only."""
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
    assert payload["claims_tested"] >= 1
    art = Path(payload["artifacts_dir"])
    summary = json.loads((art / "run_summary.json").read_text(encoding="utf-8"))

    assert summary["discovery_tokens"] == 0
    assert summary["entailment_tokens"] > 0
    assert summary["total_tokens"] == summary["entailment_tokens"]
    assert summary["total_tokens"] != summary["discovery_tokens"]

    tiers = payload["token_tiers"]
    assert tiers["discovery_run"]["entailment_tokens"] == summary["entailment_tokens"]
    assert tiers["discovery_token_share"] == summary["discovery_token_share"]
