"""Identifier whitelist and two-gate path safety (TODO §2.3 / §2.5)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from faultevolve.webapi import paths
from faultevolve.webapi.app import create_app
from faultevolve.webapi.errors import InvalidIdentifierError, RunNotFoundError
from faultevolve.webapi.settings import WebSettings

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

#: Shapes that must never be accepted as an identifier. ``%2f``-encoded
#: separators are covered at the route level; these are the decoded forms.
_BAD_IDS = [
    "../etc",
    "..",
    "a/b",
    "a\\b",
    "C:",
    "C:\\Windows",
    "a b",
    ".hidden",
    "a" * 65,
    "",
]


@pytest.mark.parametrize("bad", _BAD_IDS)
def test_the_whitelist_refuses_every_dangerous_shape(bad: str) -> None:
    assert paths.is_valid_id(bad) is False
    with pytest.raises(InvalidIdentifierError):
        paths.validate_id(bad, kind="run_id")


def test_a_well_formed_id_is_accepted() -> None:
    for good in ("hdd_mvp_demo_7510f100", "62d6cf09", "run-1.2", "A"):
        assert paths.is_valid_id(good) is True


def test_run_child_rejects_a_segment_that_is_a_path() -> None:
    run_dir = (REPO_ROOT / "tests" / "fixtures" / "runs" / "hdd_mvp_demo_7510f100").resolve()
    with pytest.raises(InvalidIdentifierError):
        paths.resolve_run_child(run_dir, "..", "secrets.txt")
    with pytest.raises(InvalidIdentifierError):
        paths.resolve_run_child(run_dir, "a/b")


def test_a_traversal_run_id_is_refused_at_the_route(client: TestClient) -> None:
    """``%2e%2e`` decodes to ``..``; the whitelist rejects it before any join."""
    response = client.get("/api/runs/%2e%2e")
    assert response.status_code in (400, 404)
    assert response.json()["error_code"] in ("request.invalid", "run.not_found")


def test_a_drive_letter_run_id_is_refused(client: TestClient) -> None:
    response = client.get("/api/runs/C%3A")
    assert response.status_code == 400
    assert response.json()["error_code"] == "request.invalid"


def test_a_traversal_node_id_is_refused(client: TestClient, run_id: str) -> None:
    response = client.get(f"/api/runs/{run_id}/nodes/%2e%2e")
    assert response.status_code == 400
    assert response.json()["error_code"] == "request.invalid"


def test_a_traversal_artifact_id_is_refused(client: TestClient, run_id: str) -> None:
    response = client.get(f"/api/runs/{run_id}/artifacts/%2e%2e")
    assert response.status_code == 400
    assert response.json()["error_code"] == "request.invalid"


def test_a_run_directory_outside_the_root_is_unreachable(tmp_path: Path) -> None:
    """A directory that exists but sits outside the allow-list is invisible.

    This is the second gate: even a perfectly id-shaped name must not reach a
    sibling of the configured root.
    """
    root = tmp_path / "runs"
    root.mkdir()
    holdout = tmp_path / "protected"
    holdout.mkdir()
    (holdout / "run_summary.json").write_text("{}", encoding="utf-8")

    settings = WebSettings(runs_root=root, allowed_path_roots=[root])
    client = TestClient(create_app(settings), raise_server_exceptions=False)

    assert client.get("/api/runs").json() == []
    assert client.get("/api/runs/protected").status_code == 404


def test_no_configured_root_reaches_nothing(tmp_path: Path) -> None:
    """Default settings expose no path at all -- not even the cwd."""
    settings = WebSettings()
    with pytest.raises(RunNotFoundError):
        paths.resolve_run_dir(settings, "anything")


def test_ensure_allowed_rejects_a_sibling_directory(tmp_path: Path) -> None:
    root = tmp_path / "runs"
    root.mkdir()
    sibling = tmp_path / "elsewhere"
    sibling.mkdir()
    settings = WebSettings(runs_root=root, allowed_path_roots=[root])
    assert settings.is_allowed(root / "run1") is True
    assert settings.is_allowed(sibling) is False
