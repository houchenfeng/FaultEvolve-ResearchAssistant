"""Discovery artifacts and the three-state missing/empty/corrupt rule (TODO §2.6)."""

from __future__ import annotations

import shutil

from fastapi.testclient import TestClient

from faultevolve.webapi.app import create_app


def test_empty_lists_are_available_not_missing(client: TestClient, run_id: str) -> None:
    """The fixture writes ``[]`` into each file: that is *available and empty*.

    Conflating "never written" with "written but empty" is what the third state
    exists to prevent -- the UI must be able to say "发现阶段没有产出" rather
    than "数据丢失".
    """
    body = client.get(f"/api/runs/{run_id}/discovery").json()
    assert body["enabled"] is True
    assert body["phenomena_state"] == "available"
    assert body["preregistration_state"] == "available"
    assert body["controls_state"] == "available"
    assert body["discovered_cards_state"] == "available"
    assert body["phenomena"] == []
    assert body["controls"] == []
    assert body["preregistration"] == []
    assert body["discovered_card_ids"] == []


def test_list_shaped_artifacts_stay_lists(client: TestClient, run_id: str) -> None:
    """``controls.json`` is a list in the engine's writer, not an object."""
    body = client.get(f"/api/runs/{run_id}/discovery").json()
    assert isinstance(body["controls"], list)
    assert isinstance(body["preregistration"], list)


def test_discovery_rounds_mismatch_is_reported(client: TestClient, run_id: str) -> None:
    """``discovery_rounds=0`` while the database holds round events.

    The two sources disagree; the reply carries both rather than quietly
    picking one.
    """
    body = client.get(f"/api/runs/{run_id}/discovery").json()
    assert any("discovery_round" in warning["reason"] for warning in body["warnings"])


def test_a_deleted_discovery_directory_is_missing(mutable_run) -> None:
    """Absence is reported as ``missing``, never as an empty success."""
    settings, run_id, run_dir = mutable_run
    shutil.rmtree(run_dir / "discovery")
    body = TestClient(create_app(settings)).get(f"/api/runs/{run_id}/discovery").json()
    assert body["enabled"] is False
    assert body["phenomena_state"] == "missing"
    assert body["preregistration_state"] == "missing"
    assert body["controls_state"] == "missing"
    assert body["discovered_cards_state"] == "missing"


def test_a_corrupt_discovery_file_is_a_stable_error(mutable_run) -> None:
    """Damaged JSON is a 500 with the stable code, not a silent empty list."""
    settings, run_id, run_dir = mutable_run
    (run_dir / "discovery" / "phenomena.json").write_text("{not json", encoding="utf-8")
    response = TestClient(create_app(settings)).get(f"/api/runs/{run_id}/discovery")
    assert response.status_code == 500
    assert response.json()["error_code"] == "artifact.invalid_json"


def test_insights_report_an_empty_table_as_available(client: TestClient, run_id: str) -> None:
    """The ``insight`` table exists and holds no rows."""
    body = client.get(f"/api/runs/{run_id}/insights").json()
    assert body["available"] is True
    assert body["insights"] == []


def test_insights_without_a_database_are_unavailable(mutable_run) -> None:
    settings, run_id, run_dir = mutable_run
    (run_dir / "fe.db").unlink()
    body = TestClient(create_app(settings)).get(f"/api/runs/{run_id}/insights").json()
    assert body["available"] is False
    assert body["warnings"]


def test_knowledge_cards_cover_offered_and_adopted(
    client: TestClient, run_id: str
) -> None:
    """Every card the run offered appears, with adoption/refutation counters.

    The fixture offered 17 distinct cards and adopted two of them (FE01, M01).
    """
    cards = {card["card_id"]: card for card in client.get(f"/api/runs/{run_id}/knowledge/cards").json()}
    assert len(cards) == 18
    assert cards["FE01"]["adopted_count"] == 2
    assert cards["FE01"]["refuted_count"] == 2
    assert cards["FE01"]["adopted_iterations"] == [1]
    assert cards["M01"]["adopted_count"] == 2
    # A card with no adoption keeps None, not 0.
    assert cards["E01"]["adopted_count"] is None
    assert cards["E01"]["offered_count"] == 2


def test_knowledge_card_prose_is_not_invented(client: TestClient, run_id: str) -> None:
    """Without a registered task, usage is returned and prose stays empty."""
    cards = client.get(f"/api/runs/{run_id}/knowledge/cards").json()
    assert all(card["claim"] is None for card in cards)
    assert all(card["source_kind"] is None for card in cards)
    assert all(card["title"] is None for card in cards)
    assert all(card["sources"] == [] for card in cards)
