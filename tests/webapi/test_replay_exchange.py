"""S6/D6.3: the exchange layer and island ids reach the tree and summary APIs.

The engine records publishing, delivery and application as three separate tables.
These tests read them back through HTTP and check that the API keeps them separate,
that a graft edge never pretends to be parenthood, and that no response carries a
filesystem path (TODO D6.3's "不提供越权的源文件路径读取能力").

The runs are the CLI's own on the toy task with ``--mock``; ``--runs-dir`` and
``--artifacts-dir`` deliberately point at the **same** directory so one run is one
directory, which is also the layout the committed fixture uses.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from faultevolve.cli import app
from faultevolve.webapi.app import create_app
from faultevolve.webapi.settings import WebSettings

REPO = Path(__file__).resolve().parents[2]
TOY_TASK = REPO / "tests" / "fixtures" / "toy_task"

ISLANDS_CONFIG: dict[str, Any] = {
    "task": {"adapter": "famou"},
    "budget": {"max_iterations": 4},
    "islands": {"enabled": True, "exchange_interval": 1},
}


def _run(tmp: Path, config: dict[str, Any] | None, iterations: int) -> tuple[WebSettings, str]:
    root = tmp / "runs"
    root.mkdir(parents=True, exist_ok=True)
    argv = ["evolve", "local", str(TOY_TASK), "--mock", "-n", str(iterations)]
    if config is not None:
        file = tmp / "config.yaml"
        file.write_text(
            yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )
        argv += ["--config-file", str(file)]
    argv += ["--runs-dir", str(root), "--artifacts-dir", str(root), "--json"]
    result = CliRunner().invoke(app, argv)
    assert result.exit_code == 0, result.output + getattr(result, "stderr", "")
    run_id = json.loads(result.output[result.output.index("{"):])["experiment_id"]
    allowed = root.resolve()
    return WebSettings(runs_root=allowed, allowed_path_roots=[allowed]), run_id


@pytest.fixture(scope="module")
def exchange_run(tmp_path_factory) -> dict[str, Any]:
    tmp = tmp_path_factory.mktemp("exchange")
    settings, run_id = _run(tmp, ISLANDS_CONFIG, 4)
    client = TestClient(create_app(settings), raise_server_exceptions=False)
    run_dir = settings.runs_root / run_id
    connection = sqlite3.connect(f"file:{(run_dir / 'fe.db').as_posix()}?mode=ro", uri=True)
    try:
        tables = {
            name: [dict(zip((d[0] for d in cursor.description), row))
                   for row in cursor]
            for name, cursor in [
                (
                    "summaries",
                    connection.execute("SELECT * FROM exchange_summary"),
                ),
                (
                    "deliveries",
                    connection.execute("SELECT * FROM exchange_delivery"),
                ),
                (
                    "applications",
                    connection.execute("SELECT * FROM summary_application"),
                ),
                ("nodes", connection.execute("SELECT id, island_id FROM node")),
            ]
        }
    finally:
        connection.close()
    return {
        "client": client,
        "run_id": run_id,
        "tables": tables,
        "island_of": {str(r["id"]): str(r["island_id"]) for r in tables["nodes"]},
    }


def _payload(client: TestClient, path: str) -> dict[str, Any]:
    response = client.get(path)
    assert response.status_code == 200, response.text
    return response.json()


# ---------------------------------------------------------------------- the list


def test_the_exchange_layer_is_available_on_an_island_run(exchange_run) -> None:
    body = _payload(exchange_run["client"], f"/api/runs/{exchange_run['run_id']}/summaries")
    assert body["state"] == "available"
    assert body["summary_count"] == len(exchange_run["tables"]["summaries"])
    assert body["delivery_count"] == len(exchange_run["tables"]["deliveries"])
    assert body["application_count"] == len(exchange_run["tables"]["applications"])
    assert body["summaries"], "the drill run exchanged, so there is something to show"


def test_the_four_exchange_counts_stay_separate(exchange_run) -> None:
    """Published, delivered, applied and evaluated are four facts, never one."""
    body = _payload(exchange_run["client"], f"/api/runs/{exchange_run['run_id']}/summaries")
    evaluated = sum(
        1
        for summary in body["summaries"]
        for application in summary["applications"]
        if application["evaluated"]
    )
    assert body["evaluated_application_count"] == evaluated
    assert evaluated <= body["application_count"]
    assert (
        body["summary_count"] <= body["delivery_count"]
    ), "one summary goes to several islands, never the other way round"
    # The counts come from the tables, the per-summary lists come from a join. If
    # the join drops rows the two disagree, and every loop below would silently
    # iterate nothing -- so the join has to be proven to carry all of them.
    attached = sum(len(summary["applications"]) for summary in body["summaries"])
    assert attached == body["application_count"], (
        "every application row has to be reachable from the summary that was "
        f"applied: {attached} attached, {body['application_count']} in the table"
    )
    assert attached > 0, "this run grafted, so there is an application to reach"


def test_a_summary_never_delivers_to_its_own_island(exchange_run) -> None:
    body = _payload(exchange_run["client"], f"/api/runs/{exchange_run['run_id']}/summaries")
    for summary in body["summaries"]:
        assert summary["source_island_id"]
        for delivery in summary["deliveries"]:
            assert delivery["summary_id"] == summary["summary_id"]
            assert delivery["target_island_id"] != summary["source_island_id"]


def test_an_application_belongs_to_the_island_it_was_delivered_to(exchange_run) -> None:
    body = _payload(exchange_run["client"], f"/api/runs/{exchange_run['run_id']}/summaries")
    for summary in body["summaries"]:
        targets = {d["target_island_id"] for d in summary["deliveries"]}
        for application in summary["applications"]:
            assert application["target_island_id"] in targets
            assert exchange_run["island_of"][application["candidate_node_id"]] == (
                application["target_island_id"]
            ), "the candidate is a node of the island that accepted the summary"


def test_the_summary_detail_carries_evidence_not_paths(exchange_run) -> None:
    body = _payload(exchange_run["client"], f"/api/runs/{exchange_run['run_id']}/summaries")
    summary_id = body["summaries"][0]["summary_id"]
    detail = _payload(
        exchange_run["client"],
        f"/api/runs/{exchange_run['run_id']}/summaries/{summary_id}",
    )
    assert detail["state"] == "available"
    assert detail["summary"]["summary_id"] == summary_id
    assert detail["summary"]["summary_text"]
    assert detail["summary"]["confidence_status"] == "single_observation", (
        "one run cannot confirm a rule"
    )
    assert detail["summary"]["evidence"], "the conclusion arrives with the nodes it came from"


def test_an_unknown_summary_is_a_structured_missing(client_and_run) -> None:
    client, run_id = client_and_run
    body = _payload(client, f"/api/runs/{run_id}/summaries/sum-does-not-exist")
    assert body["state"] == "missing"
    assert body["summary"] is None
    assert body["detail"]


@pytest.fixture(scope="module")
def client_and_run(exchange_run) -> tuple[TestClient, str]:
    return exchange_run["client"], exchange_run["run_id"]


def test_no_exchange_response_leaks_a_filesystem_path(client_and_run) -> None:
    client, run_id = client_and_run
    for path in (f"/api/runs/{run_id}/summaries",):
        text = json.dumps(_payload(client, path), ensure_ascii=False)
        for marker in (".db", ".jsonl", "runs\\\\", "/", "\\", "holdout"):
            assert marker not in text, (path, marker)


# ------------------------------------------------------------------- the tree edges


def test_tree_nodes_carry_their_island(exchange_run) -> None:
    tree = _payload(exchange_run["client"], f"/api/runs/{exchange_run['run_id']}/tree")
    for node in tree["nodes"]:
        assert node["island_id"] == exchange_run["island_of"][node["id"]]
    assert {node["island_id"] for node in tree["nodes"]} == {"a", "b", "c"}


def test_graft_edges_cross_islands_and_are_not_parenthood(exchange_run) -> None:
    tree = _payload(exchange_run["client"], f"/api/runs/{exchange_run['run_id']}/tree")
    grafts = [e for e in tree["edges"] if e["kind"] == "summary_cross"]
    assert grafts, "the drill run applied summaries, so graft edges exist"
    for edge in grafts:
        assert edge["source"] in exchange_run["island_of"]
        assert edge["target"] in exchange_run["island_of"]
        assert exchange_run["island_of"][edge["source"]] != exchange_run["island_of"][edge["target"]]
    by_id = {node["id"]: node for node in tree["nodes"]}
    for edge in grafts:
        assert by_id[edge["target"]]["parent_id"] != edge["source"], (
            "a graft source is never reported as the candidate's parent"
        )


# ---------------------------------------------------------------------- no exchange


def test_a_ring_that_exchanged_nothing_is_available_with_zero_summaries(tmp_path) -> None:
    """Two islands' worth of attempts, no summary published: a fact, not an absence.

    The engine starts its islands with one node each, so a short run has a ring but
    an empty exchange layer. That must read as "available, zero rows" -- the same
    statement the skill's D5.3 branch makes -- and not as "no exchange layer ever
    existed", which is what a pre-island database means.
    """
    settings, run_id = _run(tmp_path, None, 2)
    client = TestClient(create_app(settings), raise_server_exceptions=False)
    body = _payload(client, f"/api/runs/{run_id}/summaries")
    assert body["state"] == "available"
    assert body["summaries"] == []
    assert body["summary_count"] == body["delivery_count"] == body["application_count"] == 0
    tree = _payload(client, f"/api/runs/{run_id}/tree")
    assert [e for e in tree["edges"] if e["kind"] == "summary_cross"] == []


def test_the_committed_fixture_answers_missing(client, run_id) -> None:
    """The shipped pre-island database has no ring, and is not given one."""
    body = _payload(client, f"/api/runs/{run_id}/summaries")
    assert body["state"] == "missing"
    assert "单树" in body["detail"]
    assert body["summary_count"] == 0
