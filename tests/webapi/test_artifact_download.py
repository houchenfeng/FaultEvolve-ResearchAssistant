"""Artifact listing, download and the report manifest (TODO §2.6)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from faultevolve.webapi.app import create_app


def test_catalog_lists_the_runs_real_files(client: TestClient, run_id: str) -> None:
    """14 files exist in the fixture: 4 root artifacts, 6 programs, 4 discovery."""
    body = client.get(f"/api/runs/{run_id}/artifacts").json()
    assert body["run_id"] == run_id
    by_kind: dict[str, int] = {}
    for artifact in body["artifacts"]:
        by_kind[artifact["kind"]] = by_kind.get(artifact["kind"], 0) + 1
    assert by_kind["program"] == 6
    assert by_kind["discovery"] == 4
    assert by_kind.get("log", 0) == 0, "logs/ is empty, so no log artifact exists"


def test_artifact_ids_are_minted_not_paths(client: TestClient, run_id: str) -> None:
    """Every id is id-shaped, so no id can ever carry a separator."""
    for artifact in client.get(f"/api/runs/{run_id}/artifacts").json()["artifacts"]:
        assert "/" not in artifact["artifact_id"]
        assert "\\" not in artifact["artifact_id"]


def test_a_download_works_and_never_names_the_host_path(
    client: TestClient, run_id: str
) -> None:
    response = client.get(f"/api/runs/{run_id}/artifacts/run_summary")
    assert response.status_code == 200
    disposition = response.headers["content-disposition"]
    assert "run_summary.json" in disposition
    assert ":\\" not in disposition
    assert "/" not in disposition.split("filename=")[-1]
    assert response.json()["status"] == "finished"


def test_engine_internals_are_listed_but_not_downloadable(
    client: TestClient, run_id: str
) -> None:
    """The database is an engine internal (PRD §13.4), not a deliverable."""
    catalog = {
        artifact["artifact_id"]: artifact
        for artifact in client.get(f"/api/runs/{run_id}/artifacts").json()["artifacts"]
    }
    assert catalog["database"]["downloadable"] is False
    assert catalog["database"]["state"] == "available"

    response = client.get(f"/api/runs/{run_id}/artifacts/database")
    assert response.status_code == 403
    assert response.json()["error_code"] == "artifact.not_downloadable"


def test_an_unknown_artifact_id_is_a_structured_404(
    client: TestClient, run_id: str
) -> None:
    response = client.get(f"/api/runs/{run_id}/artifacts/not-a-real-artifact")
    assert response.status_code == 404
    assert response.json()["error_code"] == "artifact.missing"
    assert response.json()["field"] == "artifact_id"


def test_a_program_download_matches_the_stored_file(
    client: TestClient, run_id: str, init_node_id: str
) -> None:
    response = client.get(f"/api/runs/{run_id}/artifacts/program-{init_node_id}")
    assert response.status_code == 200
    assert "def " in response.text


def test_the_report_manifest_is_empty_and_says_so(
    client: TestClient, run_id: str
) -> None:
    """No export ran, so the manifest is unavailable rather than fabricated."""
    body = client.get(f"/api/runs/{run_id}/reports/manifest").json()
    assert body["available"] is False
    assert body["files"] == []
    assert body["warnings"]


def test_a_report_file_that_exists_is_listed_and_downloadable(
    mutable_run,
) -> None:
    """The manifest surfaces an export a prior run left behind."""
    settings, run_id, run_dir = mutable_run
    reports = run_dir / "reports"
    reports.mkdir()
    (reports / "run_report.md").write_text("# report\n", encoding="utf-8")

    client = TestClient(create_app(settings))
    body = client.get(f"/api/runs/{run_id}/reports/manifest").json()
    assert body["available"] is True
    assert [entry["display_name"] for entry in body["files"]] == ["run_report.md"]
    download = client.get(f"/api/runs/{run_id}/artifacts/report-run_report.md")
    assert download.status_code == 200
    # Compared stripped: a CRLF worktree would otherwise fail on git's doing.
    assert download.text.strip() == "# report"
