"""Redaction of paths, keys and serials, and the read-only guarantee (TODO §17.3)."""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient

from faultevolve.webapi import replay_service
from faultevolve.webapi.app import create_app
from faultevolve.webapi.sanitization import (
    REDACTED_PATH,
    REDACTED_SECRET,
    REDACTED_SERIAL,
    sanitize,
    sanitize_value,
    truncate_log,
)
from faultevolve.webapi.settings import WebSettings

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

_FIXTURE_RUN = "hdd_mvp_demo_7510f100"


def _snapshot(directory: Path) -> dict[str, tuple[int, int]]:
    out: dict[str, tuple[int, int]] = {}
    for path in sorted(directory.rglob("*")):
        if path.is_file():
            stat = path.stat()
            out[str(path.relative_to(directory))] = (stat.st_size, stat.st_mtime_ns)
    return out


# ---------------------------------------------------------------- unit level


def test_a_windows_path_is_redacted() -> None:
    cleaned, report = sanitize(r"failed to open C:\Users\reimu\data\train.csv")
    assert REDACTED_PATH in cleaned
    assert "reimu" not in cleaned
    assert report.paths == 1


def test_a_unc_path_is_redacted() -> None:
    cleaned, _ = sanitize(r"copying to \\fileserver\share\run")
    assert REDACTED_PATH in cleaned
    assert "fileserver" not in cleaned


def test_a_posix_path_is_redacted() -> None:
    cleaned, _ = sanitize("reading /home/hcf/nas_hcf_data/faultevolve/runs")
    assert REDACTED_PATH in cleaned
    assert "hcf" not in cleaned


def test_a_route_is_not_mistaken_for_a_path() -> None:
    """Contract text like ``/api/runs`` must survive redaction."""
    cleaned, report = sanitize("GET /api/runs returned 200")
    assert cleaned == "GET /api/runs returned 200"
    assert report.paths == 0


def test_an_api_key_is_redacted() -> None:
    cleaned, report = sanitize("using key sk-abcdefghijklmnop for the call")
    assert REDACTED_SECRET in cleaned
    assert "abcdefghijklmnop" not in cleaned
    assert report.secrets == 1


def test_a_key_assignment_is_redacted() -> None:
    cleaned, _ = sanitize("api_key = supersecretvalue")
    assert "supersecretvalue" not in cleaned


def test_a_long_serial_is_redacted_but_a_timestamp_is_not() -> None:
    cleaned, report = sanitize("disk 1234567890123456 at 1759100000000 ms")
    assert REDACTED_SERIAL in cleaned
    assert "1759100000000" in cleaned, "13-digit epoch millis must survive"
    assert report.serials == 1


def test_sanitize_value_walks_nested_structures_and_keys() -> None:
    payload = {
        "C:\\Users\\reimu\\x": ["sk-abcdefghijklmnop", {"n": 1759100000000}],
        "plain": "ok",
    }
    cleaned, report = sanitize_value(payload)
    assert REDACTED_PATH in next(iter(cleaned))
    assert cleaned["plain"] == "ok"
    assert report.total >= 2


def test_truncate_log_keeps_the_tail() -> None:
    text = "a" * 100 + "FAILURE"
    cleaned, truncated = truncate_log(text, max_chars=10)
    assert truncated is True
    assert cleaned.endswith("FAILURE")


# ------------------------------------------------------------ end to end


def test_a_log_with_secrets_is_redacted_before_it_leaves(mutable_run) -> None:
    """The fixture ships an empty ``logs/``, so craft one and replay it.

    This is the only way to exercise the real read -> sanitize -> serialise path
    end to end.
    """
    settings, run_id, run_dir = mutable_run
    logs = run_dir / "logs"
    logs.mkdir(exist_ok=True)
    node_id = "62d6cf09"
    (logs / f"{node_id}.log").write_text(
        "ERROR cannot open C:\\Users\\reimu\\secret.csv\n"
        "WARN  api_key = sk-abcdefghijklmnop\n"
        "INFO  serial 1234567890123456\n",
        encoding="utf-8",
    )

    body = TestClient(create_app(settings)).get(
        f"/api/runs/{run_id}/nodes/{node_id}"
    ).json()
    assert body["log_state"] == "available"
    excerpt = body["log_excerpt"]
    assert excerpt
    assert "reimu" not in excerpt
    assert "sk-abcdefghijklmnop" not in excerpt
    assert "1234567890123456" not in excerpt
    assert REDACTED_PATH in excerpt
    assert REDACTED_SECRET in excerpt
    assert REDACTED_SERIAL in excerpt


def test_a_log_artifact_is_redacted_on_download(mutable_run) -> None:
    """A raw log file is not downloadable; it is engine-internal like the db."""
    settings, run_id, run_dir = mutable_run
    logs = run_dir / "logs"
    logs.mkdir(exist_ok=True)
    (logs / "62d6cf09.log").write_text("hello", encoding="utf-8")

    client = TestClient(create_app(settings))
    catalog = {
        artifact["artifact_id"]: artifact
        for artifact in client.get(f"/api/runs/{run_id}/artifacts").json()["artifacts"]
    }
    assert catalog["log-62d6cf09"]["downloadable"] is False
    response = client.get(f"/api/runs/{run_id}/artifacts/log-62d6cf09")
    assert response.status_code == 403
    assert response.json()["error_code"] == "artifact.not_downloadable"


def test_replay_reads_leave_the_fixture_byte_identical() -> None:
    """The regression guard for the whole ``Store``-free design.

    Reading through ``Store`` would create ``fe.db-wal``/``-shm`` and rewrite the
    fixture; this asserts nothing at all changed.
    """
    run_dir = (REPO_ROOT / "tests" / "fixtures" / "runs" / _FIXTURE_RUN).resolve()
    settings = WebSettings(
        runs_root=run_dir.parent, allowed_path_roots=[run_dir.parent]
    )
    before = _snapshot(run_dir)
    replay_service.list_runs(settings)
    replay_service.run_detail(settings, _FIXTURE_RUN)
    replay_service.tree(settings, _FIXTURE_RUN)
    replay_service.events_page(settings, _FIXTURE_RUN)
    replay_service.knowledge_cards(settings, _FIXTURE_RUN)
    replay_service.insights(settings, _FIXTURE_RUN)
    replay_service.discovery(settings, _FIXTURE_RUN)
    replay_service.artifact_catalog(settings, _FIXTURE_RUN)
    replay_service.report_manifest(settings, _FIXTURE_RUN)
    assert _snapshot(run_dir) == before
