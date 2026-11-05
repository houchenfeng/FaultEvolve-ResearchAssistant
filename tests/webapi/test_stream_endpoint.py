"""SSE endpoint tests (phase 8, TODO §8.2's seven cases plus the two the design
document adds).

The frame-format rules are already pinned in ``test_event_stream.py`` (40
tests). What is untested until now is the part that only exists when a server
is running: that the generator reads the *live* database while a run is in
flight, stops at ``run_finished``, converges onto the stable artifacts, and
never mixes two runs together. Every test here drives the real endpoint through
``TestClient`` rather than calling the generator directly, because the bugs
worth catching (a buffered response, a missing header, an id that leaks) live
between the generator and the socket.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from faultevolve.webapi import stream_service  # noqa: E402
from faultevolve.webapi.app import create_app  # noqa: E402
from faultevolve.webapi.settings import WebSettings  # noqa: E402

RUN_A = "streama001"
RUN_B = "streamb002"

EVENT_DDL = (
    "CREATE TABLE IF NOT EXISTS event ("
    " id INTEGER PRIMARY KEY AUTOINCREMENT,"
    " experiment_id TEXT,"
    " type TEXT,"
    " payload_json TEXT,"
    " ts TEXT)"
)


# --------------------------------------------------------------------------
# fixtures / helpers
# --------------------------------------------------------------------------


@pytest.fixture
def runs_root(tmp_path: Path) -> Path:
    root = tmp_path / "runs"
    root.mkdir()
    return root


@pytest.fixture
def client(runs_root: Path) -> TestClient:
    settings = WebSettings(runs_root=runs_root, allowed_path_roots=[runs_root])
    return TestClient(create_app(settings), raise_server_exceptions=False)


def make_run(runs_root: Path, run_id: str) -> Path:
    """A run directory with only a live ``fe.db`` -- the mid-flight state."""
    run_dir = runs_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def write_events(run_dir: Path, events: list[tuple[str, dict]]) -> None:
    """Write rows into the live database the way the engine's store does."""
    with sqlite3.connect(run_dir / "fe.db") as conn:
        conn.execute(EVENT_DDL)
        for event_type, payload in events:
            conn.execute(
                "INSERT INTO event (experiment_id, type, payload_json, ts)"
                " VALUES (?, ?, ?, ?)",
                (run_dir.name, event_type, json.dumps(payload), "2026-10-03T00:00:00Z"),
            )
        conn.commit()


def finish_run(run_dir: Path, events: list[tuple[str, dict]]) -> None:
    """Write the artifacts the engine writes when it ends (``write_artifacts``).

    ``events.jsonl`` carries the same rows the live database had, with the same
    ids, so a test can assert the stream delivers each id exactly once across
    the live -> artifact boundary.
    """
    rows: list[dict] = []
    for index, (event_type, payload) in enumerate(events, start=1):
        rows.append(
            {
                "id": index,
                "experiment_id": run_dir.name,
                "type": event_type,
                "payload": payload,
                "ts": "2026-10-03T00:00:00Z",
            }
        )
    (run_dir / "run_summary.json").write_text(
        json.dumps({"experiment_id": run_dir.name, "iterations_done": 1}),
        encoding="utf-8",
    )
    (run_dir / "events.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def read_stream(client: TestClient, run_id: str, **params) -> tuple[int, str, str]:
    """Consume a whole stream; returns (status, content-type, raw body)."""
    with client.stream("GET", f"/api/runs/{run_id}/stream", params=params) as response:
        body = "".join(response.iter_text())
        return response.status_code, response.headers.get("content-type", ""), body


def frame_ids(body: str) -> list[int]:
    """Ids carried by ``id:`` lines, in order."""
    ids: list[int] = []
    for line in body.splitlines():
        if line.startswith("id: "):
            ids.append(int(line[4:]))
    return ids


def frame_events(body: str) -> list[str]:
    """Event names from ``event:`` lines, in order."""
    return [
        line[len("event: ") :]
        for line in body.splitlines()
        if line.startswith("event: ")
    ]


def frame_payloads(body: str) -> list[dict]:
    """Parsed ``data:`` payloads of *engine* events, in order.

    ``snapshot_ready`` is skipped: it is a server-side signal with no engine row
    behind it, so it has no id and no payload, and letting it through would
    make every payload assertion carry an exception.
    """
    return [
        parsed
        for parsed in (
            json.loads(line[len("data: ") :])
            for line in body.splitlines()
            if line.startswith("data: ")
        )
        if "payload" in parsed
    ]


# --------------------------------------------------------------------------
# transport basics
# --------------------------------------------------------------------------


def test_stream_sends_the_headers_a_proxy_would_otherwise_buffer(
    client: TestClient, runs_root: Path
) -> None:
    """No `Cache-Control: no-store` / `X-Accel-Buffering: no` and the stream
    looks dead until the run ends -- indistinguishable from "the push channel is
    broken", which is the failure this endpoint exists to avoid."""
    run_dir = make_run(runs_root, RUN_A)
    finish_run(run_dir, [("run_finished", {})])

    with client.stream("GET", f"/api/runs/{RUN_A}/stream") as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["x-accel-buffering"] == "no"


def test_a_finished_run_streams_its_whole_timeline_and_closes(
    client: TestClient, runs_root: Path
) -> None:
    """A stream that never ends is a socket nobody asked for: the client
    re-opens it if it needs more, and a closed one is testable at all."""
    run_dir = make_run(runs_root, RUN_A)
    finish_run(
        run_dir,
        [("init_evaluated", {"node_id": "n0"}), ("run_finished", {})],
    )

    status, _ctype, body = read_stream(client, RUN_A)

    assert status == 200
    assert frame_events(body) == [
        "init_evaluated",
        "run_finished",
        stream_service.SNAPSHOT_READY,
    ]
    # snapshot_ready carries no id: there is no engine row behind it, and an id
    # would be a resume point the client would then try to trust.
    assert frame_ids(body) == [1, 2]


# --------------------------------------------------------------------------
# case 1: after_id catch-up
# --------------------------------------------------------------------------


def test_after_id_returns_only_what_came_after(
    client: TestClient, runs_root: Path
) -> None:
    run_dir = make_run(runs_root, RUN_A)
    finish_run(run_dir, [("init_evaluated", {}), ("iteration_complete", {}), ("run_finished", {})])

    _status, _ctype, body = read_stream(client, RUN_A, after_id=1)

    # Strictly greater than 1: `>=` would replay event 1 on every reconnect.
    assert frame_ids(body) == [2, 3]


def test_last_event_id_header_and_after_id_query_mean_the_same_thing(
    client: TestClient, runs_root: Path
) -> None:
    """The design document's second added test.

    A browser reconnects with `Last-Event-ID`; a script reconnects with
    `?after_id=`. If those two paths ever disagreed, a client could not reason
    about where it resumes -- and the disagreement would be invisible until a
    run happened to drop an event in the gap.
    """
    run_dir = make_run(runs_root, RUN_A)
    finish_run(run_dir, [("init_evaluated", {}), ("iteration_complete", {}), ("run_finished", {})])

    with client.stream(
        "GET", f"/api/runs/{RUN_A}/stream", headers={"Last-Event-ID": "1"}
    ) as response:
        by_header = "".join(response.iter_text())
    _s, _c, by_query = read_stream(client, RUN_A, after_id=1)

    assert by_header == by_query
    assert frame_ids(by_header) == [2, 3]


def test_the_last_event_id_header_wins_over_the_query_cursor(
    client: TestClient, runs_root: Path
) -> None:
    """The `EventSource` auto-reconnect case, and the reason for the precedence.

    A browser reconnects to the *same URL*, so the query cursor it was opened
    with is still there while `Last-Event-ID` carries how far it actually got.
    Preferring the query would replay events 2..3 on every automatic reconnect --
    exactly the duplicate delivery PRD §16.3 rules out.
    """
    run_dir = make_run(runs_root, RUN_A)
    finish_run(
        run_dir,
        [("init_evaluated", {}), ("iteration_complete", {}), ("run_finished", {})],
    )

    with client.stream(
        "GET",
        f"/api/runs/{RUN_A}/stream",
        params={"after_id": 0},
        headers={"Last-Event-ID": "2"},
    ) as response:
        body = "".join(response.iter_text())

    assert frame_ids(body) == [3]


def test_a_garbage_cursor_is_ignored_rather_than_read_as_zero(
    client: TestClient, runs_root: Path
) -> None:
    """A cursor that silently became 0 looks like a valid resume point, and the
    client would believe it holds the complete timeline."""
    run_dir = make_run(runs_root, RUN_A)
    finish_run(run_dir, [("init_evaluated", {})])

    with client.stream(
        "GET", f"/api/runs/{RUN_A}/stream", headers={"Last-Event-ID": "not-a-number"}
    ) as response:
        body = "".join(response.iter_text())

    assert frame_ids(body) == [1]


# --------------------------------------------------------------------------
# case 2 + 3: no duplicate delivery, and reconnection
# --------------------------------------------------------------------------


def test_reconnecting_with_the_last_id_does_not_redeliver_anything(
    client: TestClient, runs_root: Path
) -> None:
    """PRD §16.3: the same event delivered twice must not produce two nodes."""
    run_dir = make_run(runs_root, RUN_A)
    finish_run(run_dir, [("init_evaluated", {}), ("iteration_complete", {}), ("run_finished", {})])

    _s, _c, first = read_stream(client, RUN_A)
    _s, _c, second = read_stream(client, RUN_A, after_id=frame_ids(first)[-1])

    assert frame_ids(second) == []
    # snapshot_ready still arrives: the client needs to know it is caught up.
    assert frame_events(second) == [stream_service.SNAPSHOT_READY]


def test_every_delivered_id_is_strictly_increasing(
    client: TestClient, runs_root: Path
) -> None:
    run_dir = make_run(runs_root, RUN_A)
    finish_run(run_dir, [("init_evaluated", {}), ("iteration_complete", {}), ("run_finished", {})])

    _s, _c, body = read_stream(client, RUN_A)
    ids = frame_ids(body)

    assert ids == sorted(ids)
    assert len(ids) == len(set(ids))


# --------------------------------------------------------------------------
# case 5: switching to the snapshot when the run ends
# --------------------------------------------------------------------------


def test_run_finished_switches_the_stream_to_the_stable_artifacts(
    client: TestClient, runs_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The live database stops being the source the moment the run ends.

    Concretely: an event that only ever reaches `events.jsonl` (the engine
    writes it after `run_finished`, and the live database row is absent) must
    still arrive. That is the whole point of the convergence step -- if the
    stream stopped at `run_finished`, the last events of every run would go
    missing.
    """
    run_dir = make_run(runs_root, RUN_A)
    write_events(run_dir, [("iteration_complete", {"n": 1})])

    # End the run from a "background thread" the way the engine would: the live
    # database gets `run_finished`, and the artifacts appear right behind it.
    original = stream_service._live_event_rows
    state = {"polls": 0}

    def rows_then_end(db_path: Path, run_id: str):
        state["polls"] += 1
        rows = original(db_path, run_id)
        if state["polls"] == 2:
            with sqlite3.connect(db_path) as conn:
                conn.execute(EVENT_DDL)
                conn.execute(
                    "INSERT INTO event (experiment_id, type, payload_json, ts)"
                    " VALUES (?, 'run_finished', '{}', '2026-10-03T00:00:01Z')",
                    (run_id,),
                )
                conn.commit()
            # `write_artifacts` order: summary first, then events.jsonl. The
            # extra event is the one that only exists in the artifact.
            finish_run(
                run_dir,
                [
                    ("iteration_complete", {"n": 1}),
                    ("run_finished", {}),
                    ("insight_extracted", {"only": "in-artifacts"}),
                ],
            )
        return rows

    monkeypatch.setattr(stream_service, "_live_event_rows", rows_then_end)
    monkeypatch.setattr(stream_service, "LIVE_POLL_SECONDS", 0.01)

    _s, _c, body = read_stream(client, RUN_A)

    names = frame_events(body)
    assert "run_finished" in names
    assert names[-1] == stream_service.SNAPSHOT_READY
    # The artifact-only event made it, and nothing was delivered twice.
    assert "insight_extracted" in names
    ids = frame_ids(body)
    assert len(ids) == len(set(ids))


def test_a_live_run_streams_from_the_database_before_any_artifact_exists(
    client: TestClient, runs_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`events.jsonl` is written once at the *end* of a run, so a stream opened
    on a fresh run has nothing to read but `fe.db`."""
    run_dir = make_run(runs_root, RUN_A)
    write_events(run_dir, [("init_evaluated", {"node_id": "n0"})])

    original = stream_service._live_event_rows
    state = {"polls": 0}

    def rows_then_finish(db_path: Path, run_id: str):
        rows = original(db_path, run_id)
        state["polls"] += 1
        if state["polls"] == 2:
            finish_run(run_dir, [("init_evaluated", {"node_id": "n0"}), ("run_finished", {})])
        return rows

    monkeypatch.setattr(stream_service, "_live_event_rows", rows_then_finish)
    monkeypatch.setattr(stream_service, "LIVE_POLL_SECONDS", 0.01)

    _s, _c, body = read_stream(client, RUN_A)

    assert frame_events(body)[0] == "init_evaluated"
    assert frame_events(body)[-1] == stream_service.SNAPSHOT_READY


# --------------------------------------------------------------------------
# case 4: a busy database must not take the stream down
# --------------------------------------------------------------------------


def test_a_locked_database_does_not_kill_the_stream(
    client: TestClient, runs_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The engine is writing to `fe.db` the whole time we read it.

    Lock contention is the normal state of a live run, not an error. If it
    propagated, every concurrent write would close every open stream, and the UI
    would fall back to polling for the whole run.

    The lock is simulated by making the reader raise, rather than by opening a
    real exclusive transaction: the production connection waits 5 s before
    giving up, and a test that waited that out would be testing sqlite.
    """
    run_dir = make_run(runs_root, RUN_A)
    finish_run(run_dir, [("init_evaluated", {}), ("run_finished", {})])

    def locked(*args, **kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(stream_service, "connect_ro", locked)

    status, _ctype, body = read_stream(client, RUN_A)

    # The run is already over, so the stream never needs the database at all.
    assert status == 200
    assert frame_events(body) == ["init_evaluated", "run_finished", stream_service.SNAPSHOT_READY]


def test_a_locked_database_does_not_stop_a_live_stream_from_converging(
    client: TestClient, runs_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Same guarantee while the run is in flight: unreadable for a tick is not
    the same as unreadable forever.

    The run here really is live (no summary yet) and the database really is
    unreadable for the whole stream. What ends it is the engine finishing, which
    this test does by writing the artifacts -- the same thing phase 2 exists to
    notice.
    """
    run_dir = make_run(runs_root, RUN_A)
    # fe.db must exist, or `_live_event_rows` short-circuits before it ever
    # reaches the (monkeypatched) connection -- and the test would then hang
    # waiting for a run that nothing ever finishes.
    write_events(run_dir, [("init_evaluated", {})])
    finish = {"called": False}

    def locked(*args, **kwargs):
        # The engine writes the summary a moment after it gives up on the
        # database; the stream must still converge when that happens.
        if not finish["called"]:
            finish["called"] = True
            finish_run(
                run_dir,
                [("init_evaluated", {}), ("run_finished", {}), ("insight_extracted", {})],
            )
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(stream_service, "connect_ro", locked)
    monkeypatch.setattr(stream_service, "LIVE_POLL_SECONDS", 0.01)

    status, _ctype, body = read_stream(client, RUN_A)

    assert status == 200
    # Nothing came from the live database, so the whole timeline arrives from
    # the artifacts -- the guarantee is that the stream still converges, not
    # that it still carries live events.
    assert frame_events(body) == [
        "init_evaluated",
        "run_finished",
        "insight_extracted",
        stream_service.SNAPSHOT_READY,
    ]


# --------------------------------------------------------------------------
# case 6: two runs must not cross
# --------------------------------------------------------------------------


def test_two_open_streams_do_not_cross_events(
    client: TestClient, runs_root: Path
) -> None:
    """PRD §16.3 / design §7: watching two runs at once must not mix them.

    Every frame's data carries `runId`, so a client can tell -- but the server
    has to not lie in the first place: run A's stream must not contain a single
    event from run B's database.
    """
    dir_a = make_run(runs_root, RUN_A)
    dir_b = make_run(runs_root, RUN_B)
    finish_run(dir_a, [("init_evaluated", {"who": "a"}), ("run_finished", {})])
    finish_run(dir_b, [("init_evaluated", {"who": "b"}), ("run_finished", {})])

    _sa, _ca, body_a = read_stream(client, RUN_A)
    _sb, _cb, body_b = read_stream(client, RUN_B)

    payloads_a = frame_payloads(body_a)
    payloads_b = frame_payloads(body_b)
    assert {p["payload"].get("who") for p in payloads_a} == {"a", None}
    assert {p["payload"].get("who") for p in payloads_b} == {"b", None}
    # And the run id is on every single event, so the client can key by it.
    for payload in payloads_a:
        assert payload["run_id"] == dir_a.name
    for payload in payloads_b:
        assert payload["run_id"] == dir_b.name


def test_an_unknown_run_is_rejected_before_the_stream_opens(
    client: TestClient, runs_root: Path
) -> None:
    """A path-traversal attempt must be refused by id validation, not turned
    into a stream that quietly reads nothing."""
    for bad in ["../secrets", "a/b", ""]:
        response = client.get(f"/api/runs/{bad}/stream")
        assert response.status_code in (400, 404, 422), bad


# --------------------------------------------------------------------------
# case 7: payloads are sanitized
# --------------------------------------------------------------------------


def test_payload_paths_are_redacted_in_the_stream(
    client: TestClient, runs_root: Path
) -> None:
    """The stream is a second way for a host path to reach a browser, so it
    goes through the same redaction the polling endpoint does -- asserted
    against the literal, not against "sanitize was called"."""
    run_dir = make_run(runs_root, RUN_A)
    finish_run(
        run_dir,
        [
            (
                "smoke_data_built",
                {"path": "/home/someone/secret-benchmark/data", "sample_fraction": 0.02},
            ),
            ("run_finished", {}),
        ],
    )

    _s, _c, body = read_stream(client, RUN_A)

    assert "/home/someone/secret-benchmark" not in body
    assert "<REDACTED_PATH>" in body
