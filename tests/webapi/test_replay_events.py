"""Event timeline paging and damage tolerance (TODO §2.3 / §2.5)."""

from __future__ import annotations

import json
import re

from fastapi.testclient import TestClient

from faultevolve.webapi.app import create_app
from faultevolve.webapi.sanitization import REDACTED_PATH

_FIXTURE_EVENT_COUNT = 19

#: A Windows drive path. Anchored on a real separator so JSON's escaped
#: ``\n`` never matches.
_DRIVE_PATH = re.compile(r"[A-Za-z]:[\\/]")


def test_all_events_are_returned_in_id_order(client: TestClient, run_id: str) -> None:
    body = client.get(f"/api/runs/{run_id}/events").json()
    ids = [event["id"] for event in body["events"]]
    assert ids == list(range(1, _FIXTURE_EVENT_COUNT + 1))
    assert body["last_event_id"] == _FIXTURE_EVENT_COUNT
    assert body["has_more"] is False


def test_after_id_and_limit_page_the_stream(client: TestClient, run_id: str) -> None:
    """The reconnection contract: "give me everything after what I saw"."""
    body = client.get(f"/api/runs/{run_id}/events", params={"after_id": 5, "limit": 3}).json()
    assert [event["id"] for event in body["events"]] == [6, 7, 8]
    assert body["has_more"] is True
    assert body["last_event_id"] == 8


def test_a_limit_above_the_ceiling_is_rejected(client: TestClient, run_id: str) -> None:
    """An unbounded page request is a request to exhaust the server."""
    response = client.get(f"/api/runs/{run_id}/events", params={"limit": 100_000})
    assert response.status_code == 422
    assert response.json()["error_code"] == "request.invalid"


def test_a_negative_after_id_is_rejected(client: TestClient, run_id: str) -> None:
    response = client.get(f"/api/runs/{run_id}/events", params={"after_id": -1})
    assert response.status_code == 422


def test_a_partially_written_line_is_skipped_with_a_warning(mutable_run) -> None:
    """One torn line must not cost the caller the other nineteen."""
    settings, run_id, run_dir = mutable_run
    events_path = run_dir / "events.jsonl"
    lines = events_path.read_text(encoding="utf-8").splitlines()
    lines.insert(5, '{"id": 999, "type": "smoke_passed"')  # truncated write
    events_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    body = TestClient(create_app(settings)).get(f"/api/runs/{run_id}/events").json()
    assert len(body["events"]) == _FIXTURE_EVENT_COUNT
    assert any("无法解析" in warning["reason"] for warning in body["warnings"])


def test_a_source_count_mismatch_is_reported_not_merged(
    client: TestClient, run_id: str
) -> None:
    """The fixture's database holds two events the jsonl never received.

    ``/events`` stays on the jsonl (TODO §2.3) and says so, rather than merging
    a second source into what looks like one complete stream.
    """
    body = client.get(f"/api/runs/{run_id}/events").json()
    assert len(body["events"]) == _FIXTURE_EVENT_COUNT
    mismatches = [w for w in body["warnings"] if w["field"] == "events"]
    assert mismatches, "the jsonl/database disagreement must be surfaced"
    assert "数据库" in mismatches[0]["reason"]


def test_the_engine_id_and_the_directory_id_are_both_present(
    client: TestClient, run_id: str, experiment_id: str
) -> None:
    """Event rows carry the engine's own id, not the directory name."""
    body = client.get(f"/api/runs/{run_id}/events", params={"limit": 1}).json()
    assert body["run_id"] == run_id
    assert body["events"][0]["run_id"] == experiment_id


def test_scores_are_read_from_the_evaluator_record(client: TestClient, run_id: str) -> None:
    points = client.get(f"/api/runs/{run_id}/scores").json()
    assert len(points) == 6
    assert points[0]["iteration"] == 0
    assert points[0]["score"] == 22.807355886970594
    assert all(point["node_id"] for point in points)


def test_event_payloads_are_sanitized(client: TestClient, run_id: str) -> None:
    """No event payload may echo a host path or a key.

    The check runs over the *parsed* payload strings, not the raw JSON text: a
    JSON body legitimately contains ``:\\`` from escaped newlines, so a naive
    substring test would always fire.
    """
    body = client.get(f"/api/runs/{run_id}/events").json()
    rendered = json.dumps(body, ensure_ascii=False)
    assert REDACTED_PATH in rendered, "the fixture has at least one redacted path"
    for text in _strings(body):
        assert not _DRIVE_PATH.search(text), f"host path leaked: {text!r}"
        assert "sk-" not in text


def _strings(node: object):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for key, value in node.items():
            yield from _strings(key)
            yield from _strings(value)
    elif isinstance(node, list):
        for item in node:
            yield from _strings(item)
