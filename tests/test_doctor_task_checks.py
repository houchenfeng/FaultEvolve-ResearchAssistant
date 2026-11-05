"""CLI doctor task-dir checks."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from faultevolve.cli import app

runner = CliRunner()


def test_doctor_without_task_dir_unchanged():
    result = runner.invoke(app, ["doctor", "--json"])
    names = {c["name"] for c in json.loads(result.stdout)["checks"]}
    assert not any(n.startswith("task_") for n in names)


def test_doctor_hdd_task_checks():
    result = runner.invoke(app, ["doctor", "--json", "--task-dir", "benchmark/hdd_mvp"])
    data = json.loads(result.stdout)
    names = {c["name"] for c in data["checks"]}
    assert {"task_files", "task_adapter", "task_data"} <= names
    adapter_msg = next(c["message"] for c in data["checks"] if c["name"] == "task_adapter")
    assert "HDDAdapter" in adapter_msg


def test_doctor_backblaze_missing_data(tmp_path, monkeypatch):
    monkeypatch.setenv("HDD_BENCH_DATA_ROOT", str(tmp_path))
    result = runner.invoke(app, ["doctor", "--json", "--task-dir", "benchmark/backblaze_hdd"])
    data = json.loads(result.stdout)
    task_data = next(c for c in data["checks"] if c["name"] == "task_data")
    assert task_data["ok"] is False
    assert "prepare_data.py" in task_data["message"]
    assert any(c["name"] == "task_data_root_env" for c in data["checks"])


def test_doctor_stub_dir():
    result = runner.invoke(app, ["doctor", "--json", "--task-dir", "benchmark/ssd_alibaba"])
    assert result.exit_code == 1
    data = json.loads(result.stdout)
    tf = next(c for c in data["checks"] if c["name"] == "task_files")
    assert tf["ok"] is False
    assert "docs/datasets/alibaba_ssd.md" in tf["message"]
    ta = next(c for c in data["checks"] if c["name"] == "task_adapter")
    assert ta["ok"] is True


def test_evolve_local_stub_dir_message():
    result = runner.invoke(app, ["evolve", "local", "benchmark/ssd_alibaba", "--mock"])
    assert result.exit_code == 1
    assert "docs/datasets/alibaba_ssd.md" in result.stderr


def _write_config(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "islands.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_doctor_config_file_selects_the_same_adapter_as_the_run(tmp_path):
    """A preflight that ignored --config-file would check the wrong adapter.

    The toy task has no evolve.yaml, so without the config file doctor resolves
    the default `hdd` adapter and reports HDD data files as missing.
    """
    cfg = _write_config(tmp_path, "task:\n  adapter: famou\n")
    fallback = runner.invoke(
        app, ["doctor", "--json", "--task-dir", "tests/fixtures/toy_task"]
    )
    default_msg = next(
        c["message"]
        for c in json.loads(fallback.stdout)["checks"]
        if c["name"] == "task_adapter"
    )
    assert "HDDAdapter" in default_msg

    result = runner.invoke(
        app, ["doctor", "--json", "--task-dir", "tests/fixtures/toy_task",
              "--config-file", str(cfg)]
    )
    checks = {c["name"]: c for c in json.loads(result.stdout)["checks"]}
    assert "FamouAdapter" in checks["task_adapter"]["message"]
    assert checks["config_keys"]["ok"] is True


def test_doctor_names_the_islands_the_run_will_use():
    result = runner.invoke(
        app, ["doctor", "--json", "--task-dir", "benchmark/hdd_mvp"]
    )
    islands = next(
        c for c in json.loads(result.stdout)["checks"] if c["name"] == "config_islands"
    )
    assert islands["ok"] is True
    assert "3 tree(s)" in islands["message"]
    assert "a:performance" in islands["message"]
    assert "exchange every 5 attempts" in islands["message"]


def test_doctor_reports_a_config_key_the_engine_would_ignore(tmp_path):
    """`island:` instead of `islands:` is silently dropped, so doctor must say so.

    Otherwise the operator writes one typo, gets the default island ring, and
    reads the run as if their own config had taken effect.
    """
    cfg = _write_config(tmp_path, "island:\n  exchange_intervals: 2\n")
    result = runner.invoke(
        app, ["doctor", "--json", "--task-dir", "tests/fixtures/toy_task",
              "--config-file", str(cfg)]
    )
    checks = {c["name"]: c for c in json.loads(result.stdout)["checks"]}
    assert checks["config_keys"]["ok"] is False
    assert "island" in checks["config_keys"]["message"]
    assert result.exit_code == 1


def test_doctor_rejects_a_config_file_it_cannot_resolve(tmp_path):
    missing = tmp_path / "absent.yaml"
    result = runner.invoke(app, ["doctor", "--config-file", str(missing)])
    assert result.exit_code == 2
    assert "needs --task-dir" in result.stderr

    result = runner.invoke(
        app, ["doctor", "--task-dir", "tests/fixtures/toy_task",
              "--config-file", str(missing)]
    )
    assert result.exit_code == 2
    assert "config file not found" in result.stderr
