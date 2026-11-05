"""CLI tests for discover and data checkup commands."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from faultevolve.cli import app
from faultevolve.cloud.engine import run_local_evolution
from faultevolve.worker.runner import FakeAdapter


runner = CliRunner()


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
        "discovery:\n  enabled: true\n  min_insight_z: 0.1\n  bootstrap_b: 100\n",
        encoding="utf-8",
    )
    return task


def test_discover_run_and_report(tmp_path, monkeypatch):
    task = _task(tmp_path)
    adapter = FakeAdapter()
    adapter.set_results(
        [{"validity": 1.0, "combined_score": 22.0 + i, "cost_time": 1.0, "metric": {}} for i in range(8)]
    )
    runs = task / ".fe" / "runs"
    adapter.set_results(
        [{"validity": 1.0, "combined_score": 22.0 + i, "cost_time": 1.0, "metric": {}} for i in range(8)]
    )
    with patch("faultevolve.tasks.create_benchmark_adapter", return_value=adapter):
        evo = run_local_evolution(
            task_dir=task,
            mock=True,
            max_iterations=4,
            runs_dir=runs,
            adapter=adapter,
        )
    run_id = evo["experiment_id"]

    with patch("faultevolve.tasks.create_benchmark_adapter", return_value=adapter):
        run_res = runner.invoke(
            app,
            ["discover", "run", str(task), "--run-id", run_id, "--mock", "--json", "--runs-dir", str(runs)],
        )
    assert run_res.exit_code == 0
    payload = json.loads(run_res.stdout)
    assert payload["ok"] is True
    for key in (
        "claims_proposed",
        "claims_tested",
        "neg_control_fpr",
        "promoted_cards",
        "claims_sandbox_failed",
        "round_finished",
        "artifacts_dir",
        "sandbox_errors",
    ):
        assert key in payload
    assert payload["round_finished"] is True
    if payload["promoted_cards"]:
        assert payload["promoted_cards"][0]["id"].startswith("D-")

    with patch("faultevolve.tasks.create_benchmark_adapter", return_value=adapter):
        rep_res = runner.invoke(
            app,
            ["discover", "report", str(task), "--run-id", run_id, "--json"],
        )
    assert rep_res.exit_code == 0
    report = json.loads(rep_res.stdout)
    assert report["ok"] is True
    assert "grades" in report
    assert "promoted_cards" in report


def test_discover_run_not_found(tmp_path):
    task = _task(tmp_path)
    res = runner.invoke(
        app,
        ["discover", "run", str(task), "--run-id", "missing", "--mock", "--json"],
    )
    assert res.exit_code == 1
    payload = json.loads(res.stdout)
    assert payload["ok"] is False
    assert payload["error_type"] == "RunNotFound"


def test_discover_run_writes_artifacts(tmp_path, monkeypatch):
    task = _task(tmp_path)
    adapter = FakeAdapter()
    adapter.set_results(
        [{"validity": 1.0, "combined_score": 22.0 + i, "cost_time": 1.0, "metric": {}} for i in range(8)]
    )
    runs = task / ".fe" / "runs"
    with patch("faultevolve.tasks.create_benchmark_adapter", return_value=adapter):
        evo = run_local_evolution(
            task_dir=task,
            mock=True,
            max_iterations=4,
            runs_dir=runs,
            adapter=adapter,
        )
    run_id = evo["experiment_id"]
    art_base = tmp_path / "artifacts"
    with patch("faultevolve.tasks.create_benchmark_adapter", return_value=adapter):
        run_res = runner.invoke(
            app,
            [
                "discover",
                "run",
                str(task),
                "--run-id",
                run_id,
                "--mock",
                "--json",
                "--runs-dir",
                str(runs),
                "--artifacts-dir",
                str(art_base),
                "--max-claims",
                "2",
            ],
        )
    assert run_res.exit_code == 0
    payload = json.loads(run_res.stdout)
    assert payload["round_finished"] is True
    disc = art_base / run_id / "discovery"
    for name in ("phenomena.json", "preregistration.json", "controls.json", "discovered_cards.snapshot.jsonl"):
        assert (disc / name).exists(), name


def test_discover_sandbox_error_tail_in_json(tmp_path):
    from faultevolve.cloud.engine import EvolutionEngine

    task = _task(tmp_path)
    (task / "evolve.yaml").write_text(
        "discovery:\n  enabled: false\n  min_insight_z: 0.1\n  bootstrap_b: 100\n",
        encoding="utf-8",
    )
    adapter = FakeAdapter()
    adapter.set_results(
        [{"validity": 1.0, "combined_score": 22.0 + i, "cost_time": 1.0, "metric": {}} for i in range(8)]
    )
    runs = task / ".fe" / "runs"
    with patch("faultevolve.tasks.create_benchmark_adapter", return_value=adapter):
        evo = run_local_evolution(
            task_dir=task,
            mock=True,
            max_iterations=4,
            runs_dir=runs,
            adapter=adapter,
        )
    run_id = evo["experiment_id"]

    def _fake_harvest(_self):
        return [
            (
                "node-test-1",
                "",
                "",
                {},
                "insight",
                {
                    "title": "bad feature",
                    "condition": "always",
                    "feature_code": (
                        "def feature(history):\n"
                        "    pad = 'z' * 1500\n"
                        "    raise KeyError('needle_cli')"
                    ),
                    "outcome": "fail",
                    "direction": "+",
                    "scope": "all",
                    "falsifier": "none",
                },
            )
        ]

    with patch("faultevolve.tasks.create_benchmark_adapter", return_value=adapter):
        with patch.object(EvolutionEngine, "_harvest_discovery_candidates", _fake_harvest):
            run_res = runner.invoke(
                app,
                [
                    "discover",
                    "run",
                    str(task),
                    "--run-id",
                    run_id,
                    "--mock",
                    "--json",
                    "--runs-dir",
                    str(runs),
                    "--max-claims",
                    "1",
                ],
            )
    assert run_res.exit_code == 0
    payload = json.loads(run_res.stdout)
    assert payload["claims_sandbox_failed"] >= 1
    assert payload["sandbox_errors"]
    assert "needle_cli" in payload["sandbox_errors"][0]["error_tail"]


def test_discover_model_column_and_dataframe_errors(tmp_path):
    import re

    from faultevolve.cloud.engine import EvolutionEngine

    class ModelColumnAdapter(FakeAdapter):
        def discovery_frames(self, task_spec):
            frames = super().discovery_frames(task_spec)
            hist = frames.history.copy()
            hist["model"] = "M1"
            frames.history = hist
            return frames

    task = _task(tmp_path)
    adapter = ModelColumnAdapter()
    adapter.set_results(
        [{"validity": 1.0, "combined_score": 22.0 + i, "cost_time": 1.0, "metric": {}} for i in range(8)]
    )
    runs = task / ".fe" / "runs"
    with patch("faultevolve.tasks.create_benchmark_adapter", return_value=adapter):
        evo = run_local_evolution(
            task_dir=task,
            mock=True,
            max_iterations=4,
            runs_dir=runs,
            adapter=adapter,
        )
    run_id = evo["experiment_id"]

    def _fake_harvest(_self):
        base_claim = {
            "condition": "always",
            "outcome": "fail",
            "direction": "+",
            "scope": "all",
            "falsifier": "none",
        }
        return [
            (
                "node-model-1",
                "",
                "",
                {},
                "insight",
                {
                    **base_claim,
                    "title": "uses model column",
                    "feature_code": (
                        "def feature(history):\n"
                        "    _ = history['model'].iloc[0]\n"
                        "    return history.groupby('unit')['m1'].last()\n"
                    ),
                },
            ),
            (
                "node-df-1",
                "",
                "",
                {},
                "insight",
                {
                    **base_claim,
                    "title": "returns dataframe",
                    "feature_code": (
                        "def feature(history):\n"
                        "    return history.groupby('unit')[['m1']].last()\n"
                    ),
                },
            ),
        ]

    with patch("faultevolve.tasks.create_benchmark_adapter", return_value=adapter):
        with patch.object(EvolutionEngine, "_harvest_discovery_candidates", _fake_harvest):
            run_res = runner.invoke(
                app,
                [
                    "discover",
                    "run",
                    str(task),
                    "--run-id",
                    run_id,
                    "--mock",
                    "--json",
                    "--runs-dir",
                    str(runs),
                    "--max-claims",
                    "2",
                ],
            )
    assert run_res.exit_code == 0
    payload = json.loads(run_res.stdout)
    assert payload["round_finished"] is True
    assert payload["claims_tested"] >= 1
    assert payload["claims_sandbox_failed"] >= 1
    for err in payload["sandbox_errors"]:
        assert not re.match(r"^exit \d+$", err["error_tail"])
    assert any("DataFrame" in e["error_tail"] for e in payload["sandbox_errors"])


def test_data_checkup_outputs(tmp_path, monkeypatch):
    task = _task(tmp_path)
    adapter = FakeAdapter()

    class TinyHistAdapter(FakeAdapter):
        def discovery_frames(self, task_spec):
            frames = super().discovery_frames(task_spec)
            hist = frames.history.head(5).copy()
            hist.loc[0, "m0"] = None
            frames.history = hist
            return frames

        def checkup_extras(self):
            import pandas as pd

            return pd.DataFrame([{"subset": "tiny", "stat": "<10"}])

    adapter = TinyHistAdapter()
    out_dir = tmp_path / "check"
    with patch("faultevolve.tasks.create_benchmark_adapter", return_value=adapter):
        res = runner.invoke(
            app,
            ["data", "checkup", str(task), "--json", "--out", str(out_dir)],
        )
    assert res.exit_code == 0
    payload = json.loads(res.stdout)
    assert payload["ok"] is True
    assert (out_dir / "data_facts.json").exists()
    assert (out_dir / "field_coverage.csv").exists()
    assert (out_dir / "silent_subset_stats.csv").exists()
    silent = (out_dir / "silent_subset_stats.csv").read_text(encoding="utf-8")
    assert "<10" in silent or "subset" in silent.lower()
