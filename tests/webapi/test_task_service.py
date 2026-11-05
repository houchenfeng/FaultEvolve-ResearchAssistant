"""Task catalogue tests (TODO 4.1 / 4.2, phase-4 plan section 6).

Two data sources, on purpose:

* the **committed** ``benchmark/`` tree -- it is the real catalogue the demo
  runs against, so the four-dataset listing is asserted against reality, not
  against a copy that could drift;
* ``tmp_path`` copies of ``tests/fixtures/toy_task`` -- for the destructive
  cases (delete the evaluator, delete init), which must never touch the repo.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from faultevolve.common.codecheck import FORBIDDEN_PATTERNS  # noqa: E402
from faultevolve.config import TaskConfig  # noqa: E402
from faultevolve.webapi import task_service  # noqa: E402
from faultevolve.webapi.app import create_app  # noqa: E402
from faultevolve.webapi.errors import TaskNotFoundError, WebApiError  # noqa: E402
from faultevolve.webapi.settings import WebSettings  # noqa: E402

BENCHMARK_ROOT = (REPO_ROOT / "benchmark").resolve()
TOY_TASK = REPO_ROOT / "tests" / "fixtures" / "toy_task"


def benchmark_settings() -> WebSettings:
    return WebSettings(
        task_roots=[BENCHMARK_ROOT], allowed_path_roots=[BENCHMARK_ROOT]
    )


@pytest.fixture
def bench_client() -> TestClient:
    return TestClient(create_app(benchmark_settings()), raise_server_exceptions=False)


# --------------------------------------------------------------------------
# listing against the real catalogue
# --------------------------------------------------------------------------


def test_benchmark_listing_finds_exactly_four_datasets(
    bench_client: TestClient,
) -> None:
    response = bench_client.get("/api/tasks")
    assert response.status_code == 200
    tasks = response.json()
    assert [task["task_id"] for task in tasks] == [
        "backblaze_hdd",
        "hdd_mvp",
        "smartmem",
        "ssd_alibaba",
    ]
    by_id = {task["task_id"]: task for task in tasks}
    # The plan's rule 8: stubs are listed, never hidden and never an error.
    assert by_id["hdd_mvp"]["is_stub"] is False
    assert by_id["smartmem"]["is_stub"] is False
    assert by_id["ssd_alibaba"]["is_stub"] is True
    # Adapter comes from evolve.yaml / the engine default, not a lookup table.
    assert by_id["hdd_mvp"]["adapter"] == TaskConfig().adapter
    assert by_id["ssd_alibaba"]["adapter"] == "alibaba_ssd"


def test_stub_tasks_are_marked_with_docs_and_blocked_reason(
    bench_client: TestClient,
) -> None:
    card = bench_client.get("/api/tasks/ssd_alibaba/card").json()
    assert card["is_stub"] is True
    assert card["doc_path"] == "docs/datasets/alibaba_ssd.md"
    assert card["blocked_reason"] is not None
    assert "示例" in card["blocked_reason"]

    readiness = bench_client.get("/api/tasks/ssd_alibaba/readiness").json()
    assert readiness["ready"] is False
    fields = {check["field"] for check in readiness["checks"]}
    assert {"evaluator.py", "init.py"} <= fields


def test_smartmem_has_evaluator_but_data_is_not_prepared(
    bench_client: TestClient,
) -> None:
    card = bench_client.get("/api/tasks/smartmem/card").json()
    assert card["is_stub"] is False
    assert card["evaluator_ready"] is True
    assert card["init_ready"] is True
    assert card["data_ready"] is False
    assert card["blocked_reason"] is not None

    readiness = bench_client.get("/api/tasks/smartmem/readiness").json()
    assert readiness["ready"] is False
    fields = {check["field"] for check in readiness["checks"]}
    assert fields == {"data"}


def test_hdd_mvp_is_fully_ready(bench_client: TestClient) -> None:
    readiness = bench_client.get("/api/tasks/hdd_mvp/readiness").json()
    assert readiness["ready"] is True
    assert readiness["checks"] == []

    card = bench_client.get("/api/tasks/hdd_mvp/card").json()
    assert card["data_ready"] is True
    assert card["evaluator_ready"] is True
    assert card["init_ready"] is True
    assert card["blocked_reason"] is None
    assert card["metrics"]["primary_metric"] == "ROS"
    assert card["metrics"]["target_score"] == pytest.approx(33.7)
    # No run is joined in phase 4: an untried init must say 待评估, not 22.81.
    assert card["metrics"]["initial_score"] is None
    assert card["metrics"]["score_source"] == "unavailable"


def test_stub_cards_do_not_promise_a_metric(bench_client: TestClient) -> None:
    card = bench_client.get("/api/tasks/ssd_alibaba/card").json()
    assert card["metrics"]["primary_metric"] == ""
    assert card["metrics"]["target_score"] is None


# --------------------------------------------------------------------------
# unconfigured / hostile input
# --------------------------------------------------------------------------


def test_unconfigured_task_roots_list_nothing() -> None:
    settings = WebSettings()
    assert task_service.list_task_dirs(settings) == []
    assert task_service.task_catalog_available(settings) is False


def test_non_task_directories_are_not_listed(tmp_path: Path) -> None:
    """A task root that happens to hold the repo layout stays clean."""
    root = tmp_path / "root"
    (root / "web").mkdir(parents=True)
    (root / "src").mkdir()
    (root / "__pycache__").mkdir()
    (root / "plain_dir").mkdir()  # valid id, no task markers
    shutil.copytree(TOY_TASK, root / "toy_task")

    settings = WebSettings(
        task_roots=[root.resolve()], allowed_path_roots=[root.resolve()]
    )
    listed = [d.name for d in task_service.list_task_dirs(settings)]
    assert listed == ["toy_task"]


@pytest.mark.parametrize("bad", ["..", "../etc", "a/b", "web", "nope", ""])
def test_bad_task_ids_are_rejected(bad: str) -> None:
    settings = benchmark_settings()
    with pytest.raises(WebApiError) as excinfo:
        task_service.resolve_task_dir(settings, bad)
    assert excinfo.value.http_status in (400, 404)
    assert not isinstance(excinfo.value, TaskNotFoundError) or bad in {
        "web",
        "nope",
        "",
    }


def test_unknown_task_is_a_clean_404(bench_client: TestClient) -> None:
    response = bench_client.get("/api/tasks/nope/card")
    assert response.status_code == 404
    assert response.json()["error_code"] == "task.not_found"


# --------------------------------------------------------------------------
# readiness blocking, on a mutable copy
# --------------------------------------------------------------------------


def _toy_settings(tmp_path: Path) -> tuple[WebSettings, Path]:
    root = tmp_path / "tasks"
    root.mkdir()
    shutil.copytree(TOY_TASK, root / "toy_task")
    settings = WebSettings(
        task_roots=[root.resolve()], allowed_path_roots=[root.resolve()]
    )
    return settings, root / "toy_task"


def test_missing_evaluator_blocks_readiness(tmp_path: Path) -> None:
    settings, toy = _toy_settings(tmp_path)
    (toy / "evaluator.py").unlink()

    client = TestClient(create_app(settings), raise_server_exceptions=False)
    readiness = client.get("/api/tasks/toy_task/readiness").json()
    assert readiness["ready"] is False
    fields = {check["field"] for check in readiness["checks"]}
    assert "evaluator.py" in fields

    card = client.get("/api/tasks/toy_task/card").json()
    assert card["evaluator_ready"] is False
    assert card["blocked_reason"] is not None


def test_missing_init_blocks_readiness(tmp_path: Path) -> None:
    settings, toy = _toy_settings(tmp_path)
    (toy / "init.py").unlink()

    client = TestClient(create_app(settings), raise_server_exceptions=False)
    readiness = client.get("/api/tasks/toy_task/readiness").json()
    assert readiness["ready"] is False
    fields = {check["field"] for check in readiness["checks"]}
    assert "init.py" in fields


def test_missing_data_directory_blocks_readiness(tmp_path: Path) -> None:
    """toy_task has all four files but no ``data/`` at all."""
    settings, _toy = _toy_settings(tmp_path)
    client = TestClient(create_app(settings), raise_server_exceptions=False)

    readiness = client.get("/api/tasks/toy_task/readiness").json()
    assert readiness["ready"] is False
    data_checks = [c for c in readiness["checks"] if c["field"] == "data"]
    assert data_checks, "a missing data dir must surface as a data check"

    card = client.get("/api/tasks/toy_task/card").json()
    assert card["data_ready"] is False
    assert card["data_missing"], "the missing public files must be named"


def test_broken_syntax_is_reported_not_raised(tmp_path: Path) -> None:
    settings, toy = _toy_settings(tmp_path)
    (toy / "evaluator.py").write_text("def broken(:\n", encoding="utf-8")

    client = TestClient(create_app(settings), raise_server_exceptions=False)
    response = client.get("/api/tasks/toy_task/readiness")
    assert response.status_code == 200
    fields = {check["field"] for check in response.json()["checks"]}
    assert "evaluator.py" in fields


# --------------------------------------------------------------------------
# safety properties
# --------------------------------------------------------------------------


def test_evaluator_is_never_imported(tmp_path: Path) -> None:
    """Importing foreign code is a phase-7 concern; phase 4 only parses.

    The evaluator below is valid Python that detonates on import. If any code
    path in the catalogue imported it, this test would not survive.
    """
    settings, toy = _toy_settings(tmp_path)
    (toy / "evaluator.py").write_text(
        'raise RuntimeError("the catalogue must never import task code")\n',
        encoding="utf-8",
    )

    client = TestClient(create_app(settings), raise_server_exceptions=False)
    for path in (
        "/api/tasks/toy_task",
        "/api/tasks/toy_task/readiness",
        "/api/tasks/toy_task/card",
    ):
        response = client.get(path)
        assert response.status_code == 200, path


def test_adapter_data_status_message_is_discarded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The engine's DataStatus.message can carry an env-var *value*.

    ``HDD_BENCH_DATA_ROOT`` is host configuration; it must not reach the
    browser through the readiness response.
    """
    settings, toy = _toy_settings(tmp_path)
    monkeypatch.setenv("HDD_BENCH_DATA_ROOT", "C:/SENTINEL-DATA-ROOT")

    client = TestClient(create_app(settings), raise_server_exceptions=False)
    for path in (
        "/api/tasks/toy_task/readiness",
        "/api/tasks/toy_task/card",
        "/api/tasks/toy_task",
    ):
        body = client.get(path).text
        assert "SENTINEL-DATA-ROOT" not in body, path


def test_protected_pattern_is_imported_not_redeclared() -> None:
    """Single source of truth: the web filter *is* the engine's pattern."""
    assert (
        task_service.PROTECTED_NAME_RE.pattern
        == FORBIDDEN_PATTERNS["evaluator-only path"]
    )


def test_hdd_mvp_data_dirs_skip_the_evaluator_only_area(
    bench_client: TestClient,
) -> None:
    detail = bench_client.get("/api/tasks/hdd_mvp").json()
    assert detail["data_dirs"] == ["public"]
