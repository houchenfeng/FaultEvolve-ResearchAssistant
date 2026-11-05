"""Run discovery and run detail (TODO §2.4)."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from fastapi.testclient import TestClient

from faultevolve.webapi.app import create_app
from faultevolve.webapi.settings import WebSettings


def test_listing_finds_the_fixture_run(client: TestClient, run_id: str) -> None:
    """The fixture is discovered, and reported as complete.

    按 **run_id 查找**而不是拿整个列表做相等断言：``tests/fixtures/runs`` 下面
    现在还有第二份 fixture（E2E-04 用的「故意失败候选」运行，见
    ``scripts/make_failure_fixture.py``）。这条测试关心的是「demo 运行有没有被
    发现、状态对不对」，不是「旁边恰好放着几个运行」—— 后者是 fixture 集合的
    事实，不该由这条测试来钉死。
    """
    rows = client.get("/api/runs").json()
    row = next(item for item in rows if item["run_id"] == run_id)
    assert row["data_state"] == "complete"
    assert row["status"] == "finished"
    assert row["iterations_done"] == 5
    assert row["best_score"] == 22.807355886970594
    # Replay fixtures are not in the run registry, so they have no task identity.
    assert row["task_id"] is None


def test_run_id_is_the_directory_and_experiment_id_stays_separate(
    client: TestClient, run_id: str, experiment_id: str
) -> None:
    """The directory name is the id; the engine's own id is untouched.

    They coincide in production (``.fe/runs/{experiment_id}``) but the fixture
    deliberately differs, which keeps the two concepts from being conflated.
    """
    assert run_id != experiment_id
    detail = client.get(f"/api/runs/{run_id}").json()
    assert detail["run_id"] == run_id
    # The engine's id is what the events carry.
    event = client.get(f"/api/runs/{run_id}/events?limit=1").json()["events"][0]
    assert event["run_id"] == experiment_id


def test_detail_groups_are_populated_from_the_summary(
    client: TestClient, run_id: str, init_node_id: str
) -> None:
    """Each group reads its own slice of the 116-field summary."""
    detail = client.get(f"/api/runs/{run_id}").json()
    assert detail["outcome"]["best_node_id"] == init_node_id
    assert detail["outcome"]["improvement"] == 0.0
    assert detail["budget"]["total_tokens"] == 3050
    assert detail["discovery"]["discovery_rounds"] == 0
    assert [c["card_id"] for c in detail["knowledge"]["card_stats"]] == ["FE01", "M01"]
    assert detail["operators"]["operator_counts"] == {"refine": 5}


def test_detail_marks_an_empty_log_directory_as_missing(
    client: TestClient, run_id: str
) -> None:
    """``logs/`` exists but holds only ``.gitkeep``; that is not ``available``."""
    detail = client.get(f"/api/runs/{run_id}").json()
    assert detail["artifact_states"]["logs"] == "missing"
    assert detail["artifact_states"]["run_summary"] == "available"


def test_a_nested_directory_without_run_artifacts_is_not_a_run(mutable_run) -> None:
    """A stray folder is not a run -- but the reason is its files, not its depth.

    §2.4 used to guard this by scanning only direct children; D6.1 needs real NAS
    layouts several levels deep, so the guard moved to artifact markers.
    """
    settings, run_id, run_dir = mutable_run
    nested = run_dir / "nested" / "deeper"
    nested.mkdir(parents=True)
    (nested / "raw_rows.csv").write_text("a,b\n", encoding="utf-8")
    body = TestClient(create_app(settings)).get("/api/runs").json()
    assert [row["run_id"] for row in body] == [run_id]


def test_a_nested_run_is_found_within_the_configured_depth(mutable_run) -> None:
    """Date and batch folders are walked (D6.1); ``discovery_max_depth=1`` is the
    escape hatch back to the old one-level behaviour.
    """
    settings, run_id, _run_dir = mutable_run
    batch = settings.runs_root / "2026-10" / "batch-3" / "deep_run"
    batch.mkdir(parents=True)
    (batch / "run_summary.json").write_text("{}", encoding="utf-8")

    deep = [row["run_id"] for row in TestClient(create_app(settings)).get("/api/runs").json()]
    assert deep == ["deep_run", run_id]

    shallow_settings = WebSettings(
        runs_root=settings.runs_root,
        allowed_path_roots=[settings.runs_root],
        discovery_max_depth=1,
    )
    shallow = [
        row["run_id"]
        for row in TestClient(create_app(shallow_settings)).get("/api/runs").json()
    ]
    assert shallow == [run_id]


def test_a_run_with_only_a_database_is_live(mutable_run) -> None:
    """No summary but a database means the run was observed mid-flight."""
    settings, run_id, run_dir = mutable_run
    (run_dir / "run_summary.json").unlink()
    body = TestClient(create_app(settings)).get("/api/runs").json()
    assert body[0]["data_state"] == "live"
    assert body[0]["status"] == "finished"  # read from the experiment row
    assert body[0]["best_score"] == 22.807355886970594


def test_a_run_with_nothing_readable_is_reported_unreadable(mutable_run) -> None:
    """An unreadable run still appears, flagged -- it must not vanish."""
    settings, run_id, run_dir = mutable_run
    (run_dir / "run_summary.json").unlink()
    (run_dir / "fe.db").unlink()
    body = TestClient(create_app(settings)).get("/api/runs").json()
    assert body[0]["data_state"] == "unreadable"
    assert body[0]["warnings"], "an unreadable run must explain itself"


def test_corrupt_summary_is_reported_not_hidden(mutable_run) -> None:
    """Broken JSON downgrades the row to live instead of raising."""
    settings, run_id, run_dir = mutable_run
    (run_dir / "run_summary.json").write_text("{not json", encoding="utf-8")
    body = TestClient(create_app(settings)).get("/api/runs").json()
    assert body[0]["data_state"] == "live"
    assert any("run_summary" in w["field"] for w in body[0]["warnings"])


def test_tree_on_corrupt_json_reports_a_damaged_artifact(mutable_run) -> None:
    """A malformed tree.json yields the stable damaged-artifact code."""
    settings, run_id, run_dir = mutable_run
    (run_dir / "tree.json").write_text("{not json", encoding="utf-8")
    response = TestClient(create_app(settings)).get(f"/api/runs/{run_id}/tree")
    assert response.status_code == 500
    assert response.json()["error_code"] == "artifact.invalid_json"


def test_unknown_run_is_a_structured_404(client: TestClient) -> None:
    """A missing run uses the domain code, not a bare 404."""
    response = client.get("/api/runs/nope")
    assert response.status_code == 404
    assert response.json()["error_code"] == "run.not_found"
    assert response.json()["field"] == "run_id"


def test_listing_does_not_need_a_pre_existing_root(tmp_path: Path) -> None:
    """An unconfigured or absent root yields an empty list, not an exception."""
    missing = tmp_path / "not-there"
    settings = WebSettings(runs_root=missing, allowed_path_roots=[missing])
    assert TestClient(create_app(settings)).get("/api/runs").json() == []


def test_no_root_configured_reaches_nothing() -> None:
    """Default settings must not expose the host filesystem."""
    assert TestClient(create_app(WebSettings())).get("/api/runs").json() == []


def test_reading_the_fixture_leaves_it_untouched(
    fixture_runs_root: Path,
    run_id: str,
    init_node_id: str,
    client: TestClient,
    snapshot: Callable[[Path], dict[str, tuple[int, int]]],
) -> None:
    """Replay is read-only: no sidecar, no mtime change, no new file.

    This is the regression guard for the whole ``Store``-free design. Opening
    the database through ``Store`` would create ``fe.db-wal``/``-shm`` here.
    """
    run_dir = fixture_runs_root / run_id
    before = snapshot(run_dir)
    for url in (
        "/api/runs",
        f"/api/runs/{run_id}",
        f"/api/runs/{run_id}/tree",
        f"/api/runs/{run_id}/events",
        f"/api/runs/{run_id}/scores",
        f"/api/runs/{run_id}/leaderboard",
        f"/api/runs/{run_id}/nodes/{init_node_id}",
        f"/api/runs/{run_id}/knowledge/cards",
        f"/api/runs/{run_id}/insights",
        f"/api/runs/{run_id}/discovery",
        f"/api/runs/{run_id}/artifacts",
        f"/api/runs/{run_id}/artifacts/run_summary",
        f"/api/runs/{run_id}/artifacts/database",
        f"/api/runs/{run_id}/reports/manifest",
    ):
        assert client.get(url).status_code in (200, 403), url
    assert snapshot(run_dir) == before


def test_mutable_fixture_is_really_a_copy(
    mutable_run, repo_root: Path
) -> None:
    """Guard: the writable fixture must not be the committed one."""
    _settings, _run_id, run_dir = mutable_run
    committed = repo_root / "tests" / "fixtures" / "runs" / run_dir.name
    assert run_dir.resolve() != committed.resolve()
    assert json.loads((run_dir / "run_summary.json").read_text(encoding="utf-8"))
