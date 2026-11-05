"""CLI smoke for fe discover factors / propose."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from faultevolve.cli import app
from faultevolve.cloud.engine import run_local_evolution
from faultevolve.worker.runner import FakeAdapter

runner = CliRunner()
REPO = Path(__file__).resolve().parents[1]


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


def test_discover_factors_mock_smoke(tmp_path):
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
    assert payload["ok"] is True
    assert payload["round_finished"] is True
    assert "funnel" in payload
    assert "registry_path" in payload
    reg = Path(payload["registry_path"])
    assert reg.exists()
    art = Path(payload["artifacts_dir"])
    assert (art / "discovery" / "funnel_summary.json").exists()
    assert (art / "discovery" / "candidate_registry.jsonl").exists()
    assert payload["discovery_llm_error"]["count"] >= 0


def test_discover_propose_mock(tmp_path):
    task = _task(tmp_path)
    adapter = FakeAdapter()
    runs = task / ".fe" / "runs"
    with patch("faultevolve.tasks.create_benchmark_adapter", return_value=adapter):
        evo = run_local_evolution(
            task_dir=task,
            mock=True,
            max_iterations=2,
            runs_dir=runs,
            adapter=adapter,
        )
    run_id = evo["experiment_id"]
    with patch("faultevolve.tasks.create_benchmark_adapter", return_value=adapter):
        res = runner.invoke(
            app,
            [
                "discover",
                "propose",
                str(task),
                "--run-id",
                run_id,
                "--mock",
                "--json",
                "--runs-dir",
                str(runs),
            ],
        )
    assert res.exit_code == 0
    payload = json.loads(res.stdout)
    assert payload["ok"] is True
    assert payload["proposals_count"] >= 1
