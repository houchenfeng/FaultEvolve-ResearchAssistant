"""Run listing exposes a task id only when the registry recorded one."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from faultevolve.webapi.app import create_app
from faultevolve.webapi.run_registry import RunRecord, insert_record
from faultevolve.webapi.settings import WebSettings


def _run(root: Path, run_id: str) -> None:
    directory = root / run_id
    directory.mkdir(parents=True)
    (directory / "run_summary.json").write_text(
        json.dumps({"status": "finished", "iterations_done": 1, "best_score": 1.0}),
        encoding="utf-8",
    )


def _record(run_id: str, task_dir: str, artifacts: str) -> RunRecord:
    return RunRecord(
        run_id=run_id,
        execution_backend="local_cloud",
        server_profile_id=None,
        pid=None,
        status="completed",
        task_dir=task_dir,
        db_dir=artifacts,
        artifacts_dir=artifacts,
        log_dir=None,
    )


def test_task_id_is_the_directory_name_not_the_path(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    _run(runs, "run-a")
    _run(runs, "run-b")
    task_dir = tmp_path / "private" / "hdd_mvp"
    registry = tmp_path / "registry.sqlite"
    settings = WebSettings(
        runs_root=runs,
        allowed_path_roots=[runs],
        run_registry=registry,
    )
    insert_record(
        settings,
        _record("run-a", str(task_dir), str(runs / "run-a")),
    )

    body = TestClient(create_app(settings)).get("/api/runs").text
    rows = json.loads(body)
    by_id = {row["run_id"]: row for row in rows}
    assert by_id["run-a"]["task_id"] == "hdd_mvp"
    assert by_id["run-b"]["task_id"] is None
    assert "private" not in body
    assert str(task_dir) not in body
