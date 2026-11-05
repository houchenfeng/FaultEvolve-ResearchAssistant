"""Evolution tree, node detail and leaderboard (TODO §2.5)."""

from __future__ import annotations

import json
import re

from fastapi.testclient import TestClient

from faultevolve.webapi.app import create_app


def test_tree_has_the_six_nodes_and_five_edges(
    client: TestClient, run_id: str
) -> None:
    """Exactly the structure tree.json records -- no inferred extras."""
    tree = client.get(f"/api/runs/{run_id}/tree").json()
    assert len(tree["nodes"]) == 6
    assert len(tree["edges"]) == 5
    assert tree["data_state"] == "complete"
    assert tree["best_node_id"] == "62d6cf09"


def test_parent_is_derived_from_the_single_incoming_edge(
    client: TestClient, run_id: str, init_node_id: str, refine_node_id: str
) -> None:
    """``node_parents`` is empty, so the edge list is the only honest source."""
    nodes = {
        node["id"]: node for node in client.get(f"/api/runs/{run_id}/tree").json()["nodes"]
    }
    assert nodes[init_node_id]["parent_id"] is None
    assert nodes[refine_node_id]["parent_id"] == init_node_id
    assert all(node["depth"] == 1 for node in nodes.values() if node["id"] != init_node_id)


def test_second_parent_and_repair_parent_are_never_invented(
    client: TestClient, run_id: str
) -> None:
    """No crossover happened and no repair column holds a value: both stay empty."""
    nodes = client.get(f"/api/runs/{run_id}/tree").json()["nodes"]
    assert all(node["second_parent_ids"] == [] for node in nodes)
    assert all(node["repair_parent_id"] is None for node in nodes)


def test_an_unscored_node_reports_none_not_zero(mutable_run) -> None:
    """A missing score must never be flattened to 0.

    Zero is a real, meaningful ROS value; ``None`` means "never evaluated".
    """
    settings, run_id, run_dir = mutable_run
    tree_path = run_dir / "tree.json"
    payload = json.loads(tree_path.read_text(encoding="utf-8"))
    target = next(node for node in payload["nodes"] if node["operator"] == "refine")
    target["score"] = None
    tree_path.write_text(json.dumps(payload), encoding="utf-8")

    body = TestClient(create_app(settings)).get(f"/api/runs/{run_id}/tree").json()
    updated = next(node for node in body["nodes"] if node["id"] == target["id"])
    assert updated["score"] is None

    board = TestClient(create_app(settings)).get(
        f"/api/runs/{run_id}/leaderboard"
    ).json()
    assert board[-1]["node_id"] == target["id"], "an unscored node sorts last"
    assert board[-1]["score"] is None


def test_leaderboard_ranks_the_best_node_first(
    client: TestClient, run_id: str, init_node_id: str
) -> None:
    board = client.get(f"/api/runs/{run_id}/leaderboard").json()
    assert board[0]["node_id"] == init_node_id
    assert board[0]["is_best"] is True
    scores = [row["score"] for row in board]
    assert scores == sorted(scores, reverse=True)
    assert [row["rank"] for row in board] == list(range(1, len(board) + 1))


def test_node_detail_carries_code_and_a_missing_log(
    client: TestClient, run_id: str, init_node_id: str
) -> None:
    """Code comes from ``programs/``; an empty ``logs/`` is reported missing."""
    detail = client.get(f"/api/runs/{run_id}/nodes/{init_node_id}").json()
    assert detail["node"]["id"] == init_node_id
    assert detail["artifact"] is not None
    assert detail["artifact"]["code"]
    assert detail["artifact"]["state"] == "available"
    assert detail["log_state"] == "missing"
    assert detail["log_excerpt"] is None
    assert detail["evaluation"] is not None


def test_unknown_node_is_a_structured_404(client: TestClient, run_id: str) -> None:
    response = client.get(f"/api/runs/{run_id}/nodes/deadbeef")
    assert response.status_code == 404
    assert response.json()["error_code"] == "node.not_found"
    assert response.json()["field"] == "node_id"


def test_code_survives_losing_the_program_file(mutable_run) -> None:
    """The database also carries the code, so losing ``programs/`` must not blank it.

    Source priority is DB-then-file (TODO §2.5); this pins the fallback so a
    missing side-car never silently reports "no code".
    """
    settings, run_id, run_dir = mutable_run
    program = next((run_dir / "programs").glob("*.py"))
    client = TestClient(create_app(settings))

    before = client.get(f"/api/runs/{run_id}/nodes/{program.stem}").json()
    assert before["artifact"]["code"]

    program.unlink()
    after = client.get(f"/api/runs/{run_id}/nodes/{program.stem}").json()
    assert after["artifact"]["code"] == before["artifact"]["code"]
    assert after["artifact"]["state"] == "available"

    catalog = client.get(f"/api/runs/{run_id}/artifacts").json()["artifacts"]
    assert f"program-{program.stem}" not in {a["artifact_id"] for a in catalog}


def test_code_diff_is_computed_against_the_primary_parent(
    client: TestClient, run_id: str, init_node_id: str, refine_node_id: str
) -> None:
    """A single-parent diff is derivable: both programs are on disk.

    Phase 2's only "unimplemented" item that was reachable without inventing
    data, so it is delivered rather than downgraded.
    """
    detail = client.get(f"/api/runs/{run_id}/nodes/{refine_node_id}").json()
    diff = detail["code_diff"]
    assert diff, "a refuted refine node must differ from its parent"
    assert diff.startswith("--- ")
    assert f"--- {init_node_id}.py" in diff
    assert f"+++ {refine_node_id}.py" in diff
    assert detail["code_diff_truncated"] is False


def test_a_node_without_a_parent_has_no_diff(client: TestClient, run_id: str, init_node_id: str) -> None:
    """The root has nothing to diff against; that is not an error."""
    detail = client.get(f"/api/runs/{run_id}/nodes/{init_node_id}").json()
    assert detail["code_diff"] is None
    assert detail["code_diff_truncated"] is False
    assert not [w for w in detail["warnings"] if w["field"] == "code_diff"]


#: A host path. Checked against parsed strings, because raw JSON legitimately
#: contains ``:\\`` from every escaped newline.
_HOST_PATH = re.compile(
    r"[A-Za-z]:[\\/]|/(?:home|root|mnt|media|Users|var|opt|srv)/"
)


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


def test_tree_and_node_detail_do_not_leak_paths(
    client: TestClient, run_id: str, init_node_id: str
) -> None:
    """No host path may appear in the tree or the node drawer."""
    for url in (
        f"/api/runs/{run_id}/tree",
        f"/api/runs/{run_id}/nodes/{init_node_id}",
    ):
        for text in _strings(client.get(url).json()):
            assert not _HOST_PATH.search(text), f"{url} leaked: {text!r}"
