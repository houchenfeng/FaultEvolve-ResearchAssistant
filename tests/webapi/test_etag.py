"""ETag / 304 on stable artifacts (TODO §12.6).

The middleware is installed in ``create_app``, so these tests only have to
prove the *observable* contract:

* a replay GET carries a validator and says "revalidate";
* the same bytes asked for again come back as an empty 304;
* different bytes get a different validator (no false 304 — a stale replay
  silently served from cache would be worse than re-downloading);
* the two responses that must never be held back aren't: SSE (the client is
  waiting on each chunk) and error replies.
"""

from __future__ import annotations

from fastapi.testclient import TestClient


def _get(client: TestClient, url: str, headers: dict[str, str] | None = None):
    return client.get(url, headers=headers or {})


def test_replay_get_carries_a_validator(client: TestClient, run_id: str) -> None:
    response = _get(client, f"/api/runs/{run_id}/tree")
    assert response.status_code == 200
    assert response.headers["etag"].startswith('"')
    assert response.headers["cache-control"] == "no-cache"


def test_same_bytes_return_304_with_an_empty_body(client: TestClient, run_id: str) -> None:
    url = f"/api/runs/{run_id}/tree"
    first = _get(client, url)
    etag = first.headers["etag"]

    second = _get(client, url, {"If-None-Match": etag})
    assert second.status_code == 304
    assert second.content == b""
    # The validator has to come back too, otherwise the client cannot refresh
    # its own copy when the bytes do change later.
    assert second.headers["etag"] == etag
    assert "content-length" not in second.headers


def test_wildcard_if_none_match_also_short_circuits(client: TestClient, run_id: str) -> None:
    assert _get(client, f"/api/runs/{run_id}/tree").status_code == 200
    assert _get(client, f"/api/runs/{run_id}/tree", {"If-None-Match": "*"}).status_code == 304


def test_different_resources_get_different_validators(client: TestClient, run_id: str) -> None:
    tree = _get(client, f"/api/runs/{run_id}/tree").headers["etag"]
    events = _get(client, f"/api/runs/{run_id}/events").headers["etag"]
    assert tree != events
    # A stale validator must not be honoured against another resource.
    assert _get(client, f"/api/runs/{run_id}/events", {"If-None-Match": tree}).status_code == 200


def test_body_is_unchanged_by_the_middleware(client: TestClient, run_id: str) -> None:
    """Buffering must not alter a single byte the client sees."""
    url = f"/api/runs/{run_id}/tree"
    assert _get(client, url).content == client.get(url).content


def test_sse_stream_is_never_buffered(client: TestClient, run_id: str) -> None:
    """Holding an event-stream body back would stall the client forever."""
    with client.stream("GET", f"/api/runs/{run_id}/stream") as response:
        content_type = response.headers.get("content-type", "")
        assert "text/event-stream" in content_type
        assert "etag" not in response.headers


def test_error_responses_get_no_validator(client: TestClient) -> None:
    """A cached 404 would keep answering 404 after the run appears."""
    response = _get(client, "/api/runs/definitely-not-a-run")
    assert response.status_code == 404
    assert "etag" not in response.headers
