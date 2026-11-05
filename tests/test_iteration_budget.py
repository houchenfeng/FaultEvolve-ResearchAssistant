"""Configured local iteration budgets survive the CLI unless explicitly overridden."""

import json

import pytest
import yaml
from typer.testing import CliRunner

from faultevolve.cli import app
from faultevolve.config import EvolveConfig, IslandsConfig
from faultevolve.worker.runner import FakeAdapter


@pytest.mark.parametrize("override,external_config,expected", [
    (None, False, 2),
    (None, True, 3),
    (1, False, 1),
])
def test_local_cli_honors_configured_budget(tmp_path, monkeypatch, override, external_config, expected):
    task = tmp_path / "task"
    task.mkdir()
    for name in ("evaluator.py", "init.py", "problem.md", "prompt.md"):
        (task / name).write_text("pass\n")
    config = EvolveConfig()
    config.islands = IslandsConfig.legacy_single()
    config.knowledge.enabled = False
    config.smoke_test.enabled = False
    config.stop.stop_at_target = False
    config.budget.max_iterations = 2
    (task / "evolve.yaml").write_text(yaml.safe_dump(config.model_dump()))
    monkeypatch.setattr("faultevolve.tasks.create_benchmark_adapter", lambda _: FakeAdapter())
    args = ["evolve", "local", str(task), "--mock", "--json", "--runs-dir", str(tmp_path / "runs")]
    if external_config:
        config.budget.max_iterations = 3
        path = tmp_path / "external.yaml"
        path.write_text(yaml.safe_dump(config.model_dump()))
        args += ["--config-file", str(path)]
    if override is not None:
        args += ["-n", str(override)]
    response = CliRunner().invoke(app, args)
    assert response.exit_code == 0, response.output
    result = json.loads(response.output)
    assert result["iterations_done"] == expected
