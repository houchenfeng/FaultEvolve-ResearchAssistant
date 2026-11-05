"""Caller-supplied experiment ids: the ``--run-id`` / ``experiment_id`` path.

The Web layer needs one id space, not two. Letting the caller name a new run
keeps its registry row and the engine's run directory on the same id; without
that, the API would have to watch the runs directory and guess which new folder
is "the run I just started".

That convenience is also the reason this file exists: the id becomes a path
segment (``runs_dir / exp_id``), so an unvalidated caller-supplied value is a
traversal bug. The engine therefore refuses bad ids rather than assuming the
Web layer already did.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from faultevolve.cli import app
from faultevolve.cloud.engine import _validate_experiment_id, run_local_evolution
from faultevolve.worker.runner import FakeAdapter

runner = CliRunner()


def _minimal_task(tmp_path: Path) -> Path:
    """The four files ``evolve local`` insists on before it will start."""
    task = tmp_path / "task"
    task.mkdir()
    (task / "init.py").write_text("# init", encoding="utf-8")
    (task / "problem.md").write_text("# p", encoding="utf-8")
    (task / "prompt.md").write_text("# p", encoding="utf-8")
    (task / "evaluator.py").write_text(
        "def evaluate(p, **kw):\n"
        "    return {'validity': 1, 'combined_score': 22, 'cost_time': 1,"
        " 'error_info': '', 'metric': {}}\n",
        encoding="utf-8",
    )
    return task


# -- the guard ---------------------------------------------------------------


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "..",
        ".",
        "../escape",
        "a/b",
        "a\\b",
        "a b",
        ".hidden",  # leading dot would hide the run from the listing
        "-leading-dash",
        "a" * 65,  # longer than the pattern allows
        "run:1",  # colon is a drive separator on Windows
        "run\x00id",
    ],
)
def test_unsafe_experiment_ids_are_refused(bad: str) -> None:
    with pytest.raises(ValueError):
        _validate_experiment_id(bad)


@pytest.mark.parametrize("good", ["abc12345", "a-b_c.d", "A" * 64, "0start"])
def test_safe_experiment_ids_pass_through_unchanged(good: str) -> None:
    # Not sanitised, not lower-cased: a rewritten id would name a different run
    # than the caller's registry row claims.
    assert _validate_experiment_id(good) == good


# -- end to end --------------------------------------------------------------


def test_run_local_evolution_honours_the_supplied_id(tmp_path: Path) -> None:
    task = _minimal_task(tmp_path)
    runs = tmp_path / "runs"

    result = run_local_evolution(
        task_dir=task,
        mock=True,
        max_iterations=2,
        runs_dir=runs,
        adapter=FakeAdapter(),
        seed=11,
        experiment_id="web0001",
    )

    assert result["experiment_id"] == "web0001"
    assert (runs / "web0001").is_dir()
    assert (runs / "web0001" / "fe.db").exists()
    # The artifacts land under the same id, so the replay endpoints find them.
    assert Path(result["output_dir"]).name == "web0001"
    summary = json.loads(
        (Path(result["output_dir"]) / "run_summary.json").read_text(encoding="utf-8")
    )
    assert summary["experiment_id"] == "web0001"


def test_unsafe_id_is_refused_before_anything_is_created(tmp_path: Path) -> None:
    task = _minimal_task(tmp_path)
    runs = tmp_path / "runs"

    with pytest.raises(ValueError):
        run_local_evolution(
            task_dir=task,
            mock=True,
            max_iterations=1,
            runs_dir=runs,
            adapter=FakeAdapter(),
            experiment_id="../../escaped",
        )

    # Nothing escaped, and no half-built run was left behind.
    assert not (tmp_path / "escaped").exists()
    assert list(runs.iterdir()) == []


def test_generated_id_still_used_when_none_supplied(tmp_path: Path) -> None:
    """The old behaviour is the default: omitting the id must not break anything."""
    task = _minimal_task(tmp_path)
    result = run_local_evolution(
        task_dir=task,
        mock=True,
        max_iterations=1,
        runs_dir=tmp_path / "runs",
        adapter=FakeAdapter(),
        seed=3,
    )
    assert len(result["experiment_id"]) == 8


# -- effective config --------------------------------------------------------


def test_config_path_wins_over_the_task_directory_config(tmp_path: Path) -> None:
    """The configuration the UI showed must be the one that runs.

    The task-level file here is deliberately unparsable (``budget: 42`` is not a
    mapping). Were the engine to read it instead of ``config_path``, this test
    would error rather than pass -- so passing *is* the assertion.
    """
    task = _minimal_task(tmp_path)
    (task / "evolve.yaml").write_text("budget: 42\n", encoding="utf-8")

    effective = tmp_path / "effective.yaml"
    effective.write_text("budget:\n  max_iterations: 2\n", encoding="utf-8")

    result = run_local_evolution(
        task_dir=task,
        mock=True,
        max_iterations=2,
        runs_dir=tmp_path / "runs",
        adapter=FakeAdapter(),
        seed=5,
        config_path=effective,
    )
    assert result["status"] != "crashed"


def test_task_directory_config_is_used_when_no_override_given(tmp_path: Path) -> None:
    """No ``config_path`` means the task's own ``evolve.yaml``, as before."""
    task = _minimal_task(tmp_path)
    (task / "evolve.yaml").write_text("budget: 42\n", encoding="utf-8")
    with pytest.raises(TypeError):
        run_local_evolution(
            task_dir=task,
            mock=True,
            max_iterations=1,
            runs_dir=tmp_path / "runs",
            adapter=FakeAdapter(),
        )


# -- CLI wiring --------------------------------------------------------------


def test_cli_refuses_run_id_together_with_resume(tmp_path: Path) -> None:
    """Preferring one silently would point the registry at a run that never was."""
    task = _minimal_task(tmp_path)
    result = runner.invoke(
        app,
        [
            "evolve", "local", str(task),
            "--mock", "--resume", "abc12345", "--run-id", "web0001",
        ],
    )
    assert result.exit_code != 0
    assert "mutually exclusive" in result.output


def test_cli_passes_run_id_through_to_the_engine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    task = _minimal_task(tmp_path)
    seen: dict[str, object] = {}

    def fake_run_local_evolution(**kwargs: object) -> dict[str, object]:
        seen.update(kwargs)
        return {
            "experiment_id": kwargs.get("experiment_id"),
            "status": "ok",
            "iterations_done": 0,
            "best_score": 0.0,
            "output_dir": str(tmp_path / "out"),
            "db_dir": str(tmp_path / "out"),
            "programs_dir": str(tmp_path / "out"),
            "logs_dir": str(tmp_path / "out"),
        }

    import faultevolve.cloud.engine as engine_module

    monkeypatch.setattr(engine_module, "run_local_evolution", fake_run_local_evolution)

    result = runner.invoke(
        app,
        ["evolve", "local", str(task), "--mock", "--run-id", "web0002", "--json"],
    )

    assert result.exit_code == 0, result.output
    assert seen.get("experiment_id") == "web0002"
    # And the Web layer's registry id is what comes back out.
    assert "web0002" in result.output


def test_cli_passes_config_file_through_to_the_engine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    task = _minimal_task(tmp_path)
    effective = tmp_path / "effective.yaml"
    effective.write_text("budget:\n  max_iterations: 1\n", encoding="utf-8")
    seen: dict[str, object] = {}

    def fake_run_local_evolution(**kwargs: object) -> dict[str, object]:
        seen.update(kwargs)
        return {"experiment_id": "x", "status": "ok", "iterations_done": 0,
                "best_score": 0.0, "output_dir": str(tmp_path)}

    import faultevolve.cloud.engine as engine_module

    monkeypatch.setattr(engine_module, "run_local_evolution", fake_run_local_evolution)

    result = runner.invoke(
        app,
        ["evolve", "local", str(task), "--mock",
         "--config-file", str(effective), "--json"],
    )

    assert result.exit_code == 0, result.output
    assert Path(str(seen.get("config_path"))) == effective
