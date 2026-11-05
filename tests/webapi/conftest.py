"""Shared fixtures for the Web API tests.

Two roots are offered on purpose:

* ``settings`` points at the **committed** fixture. Tests that read use it, and
  one test asserts that reading leaves the directory byte-identical.
* ``mutable_run`` copies the fixture into ``tmp_path`` so tests can corrupt a
  file, delete an artifact or add a log without touching what is in the repo.

Constants are exposed as fixtures rather than imported, so a test module never
has to depend on pytest's sys.path layout.
"""

from __future__ import annotations

import shutil
import sys
from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from faultevolve.webapi.app import create_app  # noqa: E402
from faultevolve.webapi.settings import WebSettings  # noqa: E402

#: Directory name of the redacted replay fixture. The engine's own
#: ``experiment_id`` inside it is ``7510f100``; the two differ deliberately.
_FIXTURE_RUN_ID = "hdd_mvp_demo_7510f100"
_FIXTURE_EXPERIMENT_ID = "7510f100"

#: Node ids present in the fixture, by role.
_INIT_NODE_ID = "62d6cf09"
_REFINE_NODE_ID = "43d93d40"


def _snapshot(directory: Path) -> dict[str, tuple[int, int]]:
    """Map relative path -> (size, mtime_ns) for every file below ``directory``.

    Used to prove a read-only code path really is read-only.
    """
    out: dict[str, tuple[int, int]] = {}
    for path in sorted(directory.rglob("*")):
        if path.is_file():
            stat = path.stat()
            out[str(path.relative_to(directory))] = (stat.st_size, stat.st_mtime_ns)
    return out


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def fixture_runs_root() -> Path:
    """The committed fixture root, resolved so comparisons are stable."""
    root = (REPO_ROOT / "tests" / "fixtures" / "runs").resolve()
    assert root.is_dir(), f"fixture root missing: {root}"
    return root


@pytest.fixture
def settings(fixture_runs_root: Path) -> WebSettings:
    """Settings pointing at the committed fixture, read-only in practice."""
    return WebSettings(
        runs_root=fixture_runs_root,
        allowed_path_roots=[fixture_runs_root],
    )


@pytest.fixture
def client(settings: WebSettings) -> TestClient:
    """Test client over an app built with the committed fixture."""
    return TestClient(create_app(settings), raise_server_exceptions=False)


@pytest.fixture
def run_id() -> str:
    """The fixture's *directory* name, i.e. the ``run_id`` path parameter."""
    return _FIXTURE_RUN_ID


@pytest.fixture
def experiment_id() -> str:
    """The engine's own experiment id, as carried by events and artifacts."""
    return _FIXTURE_EXPERIMENT_ID


@pytest.fixture
def init_node_id() -> str:
    """The depth-0 node, which is also the best node in this run."""
    return _INIT_NODE_ID


@pytest.fixture
def refine_node_id() -> str:
    """One of the five depth-1 refine nodes."""
    return _REFINE_NODE_ID


@pytest.fixture
def snapshot() -> Callable[[Path], dict[str, tuple[int, int]]]:
    """The directory-fingerprint helper, as a fixture."""
    return _snapshot


@pytest.fixture
def mutable_run(tmp_path: Path) -> tuple[WebSettings, str, Path]:
    """A writable copy of the fixture, plus settings that point at it.

    Returns ``(settings, run_id, run_dir)``.
    """
    root = tmp_path / "runs"
    root.mkdir()
    target = root / _FIXTURE_RUN_ID
    shutil.copytree(REPO_ROOT / "tests" / "fixtures" / "runs" / _FIXTURE_RUN_ID, target)
    mutable_settings = WebSettings(
        runs_root=root.resolve(), allowed_path_roots=[root.resolve()]
    )
    return mutable_settings, _FIXTURE_RUN_ID, target

