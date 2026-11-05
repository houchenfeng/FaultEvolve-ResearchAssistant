"""S6/D6.4: the committed three-island HDD fixture replays through the API as island data.

``tests/fixtures/runs/hdd_mvp_islands_15l4nd01`` is the only run in the repository
that the island UI is allowed to be built against: real engine, real evaluator,
mocked language model (its ``PROVENANCE.md`` records what that does and does not
prove). These tests pin what the endpoints actually answer for it, because the
front end is written against those shapes -- and one of them caught a live defect:
summary applications were joined on the delivery's *target island*, so
``summary.applications`` came back empty while ``application_count`` said twelve.

A fixture is honest about its own limits, and two of these tests assert the limits:
mock candidates never beat the initial score, so the tree has no rising best path,
and every island's recorded status outlives the run.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from faultevolve.webapi.app import create_app
from faultevolve.webapi.settings import WebSettings

REPO = Path(__file__).resolve().parents[2]
RUN_ID = "hdd_mvp_islands_15l4nd01"
LEGACY_RUN_ID = "hdd_mvp_demo_7510f100"
SUMMARY_ID = "sum-89d09670"


@pytest.fixture(scope="module")
def client() -> TestClient:
    root = (REPO / "tests" / "fixtures" / "runs").resolve()
    settings = WebSettings(runs_root=root, allowed_path_roots=[root.parent])
    return TestClient(create_app(settings), raise_server_exceptions=False)


def _body(client: TestClient, path: str) -> dict:
    response = client.get(path)
    assert response.status_code == 200, response.text
    return response.json()


# ---------------------------------------------------------------- the listing


def test_the_island_fixture_is_listed_with_its_discovery_origin(client) -> None:
    rows = _body(client, "/api/runs")
    row = next(item for item in rows if item["external_id"] == RUN_ID)
    assert row["run_type"] == "evolve"
    # Nothing in the configuration says this run is real, so nothing may claim it.
    assert row["origin"] == "unverified"
    assert row["data_state"] == "complete"


def test_no_host_path_leaks_out_of_the_island_endpoints(client) -> None:
    for path in (
        f"/api/runs/{RUN_ID}",
        f"/api/runs/{RUN_ID}/tree",
        f"/api/runs/{RUN_ID}/summaries",
        f"/api/runs/{RUN_ID}/summaries/{SUMMARY_ID}",
        "/api/runs/provenance",
    ):
        body = client.get(path)
        assert body.status_code == 200, path
        assert str(REPO) not in body.text, path
        assert "<REDACTED_PATH>" not in body.text, path


# ---------------------------------------------------------------- islands block


def test_three_islands_are_read_with_their_own_lifecycle(client) -> None:
    islands = _body(client, f"/api/runs/{RUN_ID}")["islands"]
    assert islands["state"] == "available"
    assert islands["source"] == "run_summary.json"
    assert sorted(islands["islands"]) == ["a", "b", "c"]
    for view in islands["islands"].values():
        assert view["profile"]
        assert view["attempts"] == 6
        assert view["valid_evaluations"] == 7
        assert view["best_score"] is not None
    # The engine's identity: attempts per island sum to the run's iterations.
    assert islands["attempt_total"] == 6 * 3


def test_island_status_and_run_status_stay_what_the_engine_recorded(client) -> None:
    """A finished run can still leave islands saying ``running`` -- shown, not fixed.

    The engine writes an island's own lifecycle and never rewrites it when the run
    ends, so the API must report both facts as they are instead of reconciling them
    into a story the run never recorded.
    """
    detail = _body(client, f"/api/runs/{RUN_ID}")
    assert detail["outcome"]["status"] == "finished"
    assert {row["status"] for row in detail["islands"]["islands"].values()} == {"running"}
    assert {row["stop_reason"] for row in detail["islands"]["islands"].values()} == {""}


def test_cost_is_attributed_per_island_and_never_invents_a_price(client) -> None:
    cost = _body(client, f"/api/runs/{RUN_ID}")["islands"]["cost"]
    assert cost["cost_basis"] == "unknown"
    assert cost["cost_usd"] is None
    by_island = cost["by_island"]
    attributed = sum(row["tokens"] for row in by_island.values())
    assert attributed + cost["shared_tokens"] == cost["total_tokens"]
    for row in by_island.values():
        assert row["by_stage"], "a stage the island paid for has to be named"


def test_exchange_keeps_four_separate_facts(client) -> None:
    exchange = _body(client, f"/api/runs/{RUN_ID}")["islands"]["exchange"]
    assert exchange["summaries"] == 1
    assert exchange["deliveries"] == exchange["accepted"] == 2
    assert exchange["rejected"] == 0
    assert exchange["applications"] == 12
    assert exchange["evaluated_applications"] == 12
    assert exchange["by_kind"]["best"] == 1
    # Publishing and applying are different counts: one accepted summary produced
    # twelve candidates.
    assert exchange["applications"] > exchange["accepted"]


# ---------------------------------------------------------------- tree shape


def test_the_tree_carries_three_islands_and_cross_island_edges(client) -> None:
    tree = _body(client, f"/api/runs/{RUN_ID}/tree")
    island_of = {node["id"]: node["island_id"] for node in tree["nodes"]}
    assert len(tree["nodes"]) == 21
    assert sorted({value for value in island_of.values() if value}) == ["a", "b", "c"]
    grafts = [edge for edge in tree["edges"] if edge["kind"] == "summary_cross"]
    assert len(grafts) == 12
    for edge in grafts:
        assert island_of[edge["source"]] != island_of[edge["target"]], (
            "a cross-island edge that stays inside one island is not a graft"
        )


def test_a_mock_run_that_never_beat_its_baseline_shows_no_best_path_growth(client) -> None:
    """Honest limit of this fixture: the best path is the single initial node.

    Mock candidates score around 0.3 while the initial program scores 22.8, so no
    island improved. Asserting it keeps anyone from later "fixing" the demo by
    hand-writing scores.
    """
    tree = _body(client, f"/api/runs/{RUN_ID}/tree")
    assert len(tree["best_path"]) == 1
    scores = [
        node["score"] for node in tree["nodes"] if node["score"] is not None
    ]
    assert max(scores) == pytest.approx(22.807355886970594)
    assert min(scores) < 1.0


# ---------------------------------------------------------------- summaries


def test_every_application_is_reachable_from_its_summary(client) -> None:
    body = _body(client, f"/api/runs/{RUN_ID}/summaries")
    assert body["state"] == "available"
    assert body["summary_count"] == 1
    assert body["application_count"] == 12
    assert body["evaluated_application_count"] == 12
    attached = [app for summary in body["summaries"] for app in summary["applications"]]
    assert len(attached) == body["application_count"], (
        "the per-summary list and the table count may not disagree"
    )
    summary = body["summaries"][0]
    assert summary["source_island_id"] == "a"
    assert {d["target_island_id"] for d in summary["deliveries"]} == {"b", "c"}
    for application in attached:
        assert application["evaluated"] is True
        assert application["score"] is not None
        assert application["target_island_id"] in {"b", "c"}
        assert application["target_island_id"] != summary["source_island_id"]


def test_the_summary_carries_evidence_and_its_own_confidence(client) -> None:
    summary = _body(client, f"/api/runs/{RUN_ID}/summaries/{SUMMARY_ID}")["summary"]
    assert summary["kind"] == "best"
    assert len(summary["evidence"]) == 3
    assert summary["metrics"]["combined_score"] > 0
    # The API reports the ladder value it was given; the UI must not relabel it.
    assert summary["confidence_status"] == "statistically_confirmed"


def test_an_unknown_summary_id_is_answered_as_missing(client) -> None:
    body = _body(client, f"/api/runs/{RUN_ID}/summaries/sum-doesnotexist")
    assert body["state"] == "missing"


# ---------------------------------------------------------------- legacy runs


def test_a_pre_island_run_still_answers_missing_for_every_island_block(client) -> None:
    detail = _body(client, f"/api/runs/{LEGACY_RUN_ID}")
    assert detail["islands"]["state"] == "missing"
    assert detail["islands"]["islands"] == {}
    assert detail["islands"]["exchange"] is None

    summaries = _body(client, f"/api/runs/{LEGACY_RUN_ID}/summaries")
    assert summaries["state"] == "missing"
    assert "摘要交换层" in summaries["detail"]

    tree = _body(client, f"/api/runs/{LEGACY_RUN_ID}/tree")
    # ``""`` is the contract's "this run never recorded an island", not a fourth
    # island called empty string.
    assert {node["island_id"] for node in tree["nodes"]} == {""}
    assert not [edge for edge in tree["edges"] if edge["kind"] == "summary_cross"]
