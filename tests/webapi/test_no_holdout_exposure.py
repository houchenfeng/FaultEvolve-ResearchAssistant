"""No evaluator-only name may leave the task catalogue (TODO 4 / PRD 7.8).

The plan's rule: ``holdout``-class names are neither listed, nor probed, nor
echoed by any phase-4 endpoint. This file scans the *responses* of every new
endpoint against the engine's own protected pattern -- behaviour, not
implementation details, is what gets pinned here.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from faultevolve.common.codecheck import FORBIDDEN_PATTERNS  # noqa: E402
from faultevolve.webapi.app import create_app  # noqa: E402
from faultevolve.webapi.settings import WebSettings  # noqa: E402

BENCHMARK_ROOT = (REPO_ROOT / "benchmark").resolve()

#: The engine's own notion of "evaluator-only". If the engine learns a new
#: protected name, this test tightens automatically.
PROTECTED_RE = re.compile(FORBIDDEN_PATTERNS["evaluator-only path"], re.IGNORECASE)

#: Every phase-4 catalogue endpoint, for every task in the committed catalogue.
PATHS = (
    "/api/tasks",
    "/api/tasks/{task_id}",
    "/api/tasks/{task_id}/readiness",
    "/api/tasks/{task_id}/card",
)

TASK_IDS = ("backblaze_hdd", "hdd_mvp", "smartmem", "ssd_alibaba")


def _client() -> TestClient:
    settings = WebSettings(
        task_roots=[BENCHMARK_ROOT], allowed_path_roots=[BENCHMARK_ROOT]
    )
    return TestClient(create_app(settings), raise_server_exceptions=False)


def _all_bodies() -> list[str]:
    client = _client()
    bodies: list[str] = []
    for path in PATHS:
        concrete = (
            [path] if "{task_id}" not in path else [path.format(task_id=t) for t in TASK_IDS]
        )
        for url in concrete:
            response = client.get(url)
            assert response.status_code == 200, url
            bodies.append(json.dumps(response.json(), ensure_ascii=False))
    return bodies


def test_no_response_mentions_a_protected_name() -> None:
    """Problem/prompt docs are served sanitised; data listings are filtered."""
    for body in _all_bodies():
        hits = PROTECTED_RE.findall(body)
        assert hits == [], f"a protected name reached the browser: {hits}"


def test_readonly_invariant_on_the_benchmark_tree(
    tmp_path: Path,
) -> None:
    """Reading the catalogue leaves the tree byte-identical.

    Copies the benchmark tree once, runs every endpoint against the copy, and
    compares a full fingerprint before/after. This is the same discipline the
    phase-2 tests apply to the run fixture.
    """
    snapshot_root = tmp_path / "benchmark"
    shutil_copy(BENCHMARK_ROOT, snapshot_root)

    def fingerprint(directory: Path) -> dict[str, tuple[int, int]]:
        out: dict[str, tuple[int, int]] = {}
        for path in sorted(directory.rglob("*")):
            if path.is_file():
                stat = path.stat()
                out[str(path.relative_to(directory))] = (
                    stat.st_size,
                    stat.st_mtime_ns,
                )
        return out

    before = fingerprint(snapshot_root)
    settings = WebSettings(
        task_roots=[snapshot_root.resolve()],
        allowed_path_roots=[snapshot_root.resolve()],
    )
    client = TestClient(create_app(settings), raise_server_exceptions=False)
    for task_id in TASK_IDS:
        for suffix in ("", "/readiness", "/card"):
            assert client.get(f"/api/tasks/{task_id}{suffix}").status_code == 200

    assert fingerprint(snapshot_root) == before


def shutil_copy(src: Path, dst: Path) -> None:
    import shutil

    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__"))
