"""S6/D6.3: the island, exchange and cost blocks of a run reach the web API.

The engine has written ``islands`` / ``exchange`` / ``cost`` into
``run_summary.json`` since S5, but no contract field carried them, so the UI could
not tell a three-island run from a single tree. These tests read the blocks through
the HTTP surface, and one fixture drives the real CLI so the payload cannot drift
away from what the engine actually writes.

Nothing here invents a value: an old single-tree run must answer "not recorded",
and a block that is present but malformed must answer "invalid", never a zero.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient

from faultevolve.webapi.app import create_app
from faultevolve.webapi.replay_groups import islands as islands_group
from faultevolve.webapi.settings import WebSettings

REPO = Path(__file__).resolve().parents[2]
TOY_TASK = REPO / "tests" / "fixtures" / "toy_task"

#: The ring the skill documents: three islands, exchange checked every attempt.
SKILL_CONFIG: dict[str, Any] = {
    "task": {"adapter": "famou"},
    "budget": {"max_iterations": 6},
    "islands": {"enabled": True, "exchange_interval": 1},
}

ISLAND_FIELDS = (
    "status",
    "profile",
    "attempts",
    "valid_evaluations",
    "invalid_evaluations",
    "best_score",
    "stop_reason",
)


def _client(settings: WebSettings) -> TestClient:
    return TestClient(create_app(settings), raise_server_exceptions=False)


@pytest.fixture(scope="module")
def island_run(tmp_path_factory) -> dict[str, Any]:
    """A real three-island run produced by the CLI, replayed through the API."""
    from typer.testing import CliRunner

    from faultevolve.cli import app

    tmp = tmp_path_factory.mktemp("island_run")
    config = tmp / "islands.yaml"
    config.write_text(
        yaml.safe_dump(SKILL_CONFIG, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    runs, artifacts = tmp / "runs", tmp / "art"
    result = CliRunner().invoke(
        app,
        ["evolve", "local", str(TOY_TASK), "--mock", "-n", "6",
         "--config-file", str(config), "--runs-dir", str(runs),
         "--artifacts-dir", str(artifacts), "--json"],
    )
    assert result.exit_code == 0, result.output + getattr(result, "stderr", "")
    payload = json.loads(result.output[result.output.index("{"):])
    run_id = payload["experiment_id"]
    summary = json.loads((artifacts / run_id / "run_summary.json").read_text(encoding="utf-8"))
    root = artifacts.resolve()
    return {
        "settings": WebSettings(runs_root=root, allowed_path_roots=[root]),
        "run_id": run_id,
        "summary": summary,
    }


@pytest.fixture
def detail(island_run) -> dict[str, Any]:
    response = _client(island_run["settings"]).get(f"/api/runs/{island_run['run_id']}")
    assert response.status_code == 200, response.text
    return response.json()


# ---------------------------------------------------------------- the recorded run


def test_the_api_returns_the_islands_the_engine_wrote(detail, island_run) -> None:
    block = detail["islands"]
    assert block["state"] == "available"
    assert block["source"] == "run_summary.json"
    assert set(block["islands"]) == set(island_run["summary"]["islands"])
    for island_id, row in island_run["summary"]["islands"].items():
        got = block["islands"][island_id]
        assert got["island_id"] == island_id
        assert {field: got[field] for field in ISLAND_FIELDS} == {
            field: row[field] for field in ISLAND_FIELDS
        }


def test_each_islands_score_is_its_own_trees_best(detail, island_run) -> None:
    """An island's best is never the run's global best unless it happens to be it."""
    summary = island_run["summary"]
    for island_id, row in detail["islands"]["islands"].items():
        assert row["best_score"] == summary["islands"][island_id]["best_score"]
        assert row["best_score"] <= summary["best_score"]


def test_the_exchange_count_stays_four_separate_facts(detail, island_run) -> None:
    exchange = detail["islands"]["exchange"]
    assert exchange == island_run["summary"]["exchange"]
    for key in ("summaries", "deliveries", "accepted", "rejected",
                "applications", "evaluated_applications"):
        assert isinstance(exchange[key], int), key
    assert exchange["accepted"] + exchange["rejected"] <= exchange["deliveries"]
    assert exchange["evaluated_applications"] <= exchange["applications"]


def test_the_island_attempts_add_up_to_the_iterations_the_run_done(detail, island_run) -> None:
    block = detail["islands"]
    assert block["attempt_total"] == sum(
        row["attempts"] for row in block["islands"].values()
    )
    assert block["attempt_total"] == detail["outcome"]["iterations_done"]
    assert detail["outcome"]["iterations_done"] == island_run["summary"]["iterations_done"]


def test_cost_is_attributed_per_island_and_balances(detail) -> None:
    cost = detail["islands"]["cost"]
    assert cost["total_tokens"] == sum(row["tokens"] for row in cost["by_island"].values()) + cost["shared_tokens"]
    for row in cost["by_island"].values():
        assert row["tokens"] is not None and row["calls"] is not None
    assert cost["cost_basis"] == "unknown"
    assert cost["cost_usd"] is None, "a model that quotes no price never gets an invented one"


def test_the_ring_is_not_silently_a_single_island(detail) -> None:
    """A three-island run must not arrive as one island with everything in it."""
    assert len(detail["islands"]["islands"]) == 3
    assert {row["profile"] for row in detail["islands"]["islands"].values()} == {
        "performance", "miss_alert", "efficiency"
    }


# ---------------------------------------------------------------- the historical run


def test_a_single_tree_run_says_the_ring_was_never_recorded(client, run_id) -> None:
    response = client.get(f"/api/runs/{run_id}")
    assert response.status_code == 200, response.text
    block = response.json()["islands"]
    assert block["state"] == "missing"
    assert block["source"] == ""
    assert block["islands"] == {}
    assert block["exchange"] is None
    assert block["cost"] is None
    assert block["attempt_total"] is None
    assert "单树" in block["detail"]


def test_no_island_of_a_single_tree_run_is_invented(client, run_id) -> None:
    """The old run's own headline numbers still come through untouched."""
    body = client.get(f"/api/runs/{run_id}").json()
    assert body["islands"]["islands"] == {}
    assert body["outcome"]["iterations_done"] is not None


# ---------------------------------------------------------------- malformed input


@pytest.fixture
def mutable_client(mutable_run) -> TestClient:
    settings, _, _ = mutable_run
    return _client(settings)


def _patch_summary(run_dir: Path, **fields: Any) -> Path:
    path = run_dir / "run_summary.json"
    summary = json.loads(path.read_text(encoding="utf-8"))
    summary.update(fields)
    path.write_text(json.dumps(summary, ensure_ascii=False), encoding="utf-8")
    return path


def test_a_malformed_islands_block_is_invalid_not_zeroed(mutable_run, mutable_client, run_id) -> None:
    _, _, run_dir = mutable_run
    _patch_summary(run_dir, islands="three islands, honestly")
    block = mutable_client.get(f"/api/runs/{run_id}").json()["islands"]
    assert block["state"] == "invalid"
    assert block["islands"] == {}
    assert block["detail"]


def test_an_empty_ring_is_reported_as_invalid(mutable_run, mutable_client, run_id) -> None:
    _, _, run_dir = mutable_run
    _patch_summary(run_dir, islands={})
    block = mutable_client.get(f"/api/runs/{run_id}").json()["islands"]
    assert block["state"] == "invalid"
    assert "空对象" in block["detail"]


def test_an_island_row_that_is_not_an_object_names_itself(mutable_run, mutable_client, run_id) -> None:
    _, _, run_dir = mutable_run
    _patch_summary(run_dir, islands={"a": 5})
    block = mutable_client.get(f"/api/runs/{run_id}").json()["islands"]
    assert block["state"] == "invalid"
    assert "islands.a" in block["detail"]


def test_exchange_without_islands_is_invalid_rather_than_a_half_shown_ring(
    mutable_run, mutable_client, run_id
) -> None:
    _, _, run_dir = mutable_run
    _patch_summary(run_dir, islands=None, exchange={"summaries": 3})
    block = mutable_client.get(f"/api/runs/{run_id}").json()["islands"]
    assert block["state"] == "invalid"
    assert block["exchange"]["summaries"] == 3, "what was recorded is still shown"


def test_absent_counters_stay_null(mutable_run, mutable_client, run_id) -> None:
    _, _, run_dir = mutable_run
    _patch_summary(run_dir, islands={"a": {"profile": "performance"}})
    row = mutable_client.get(f"/api/runs/{run_id}").json()["islands"]["islands"]["a"]
    assert row["profile"] == "performance"
    for field in ("status", "attempts", "valid_evaluations", "invalid_evaluations",
                  "best_score", "stop_reason"):
        assert row[field] is None, field


def test_a_run_without_a_summary_has_no_islands_group(mutable_run, mutable_client, run_id) -> None:
    _, _, run_dir = mutable_run
    (run_dir / "run_summary.json").unlink()
    body = mutable_client.get(f"/api/runs/{run_id}").json()
    assert body["islands"] is None, "no artifact, no group -- rather than a group full of nulls"


# ---------------------------------------------------------------- the group function


def test_a_field_of_the_wrong_type_stays_null_rather_than_a_coerced_one(
    mutable_run, mutable_client, run_id
) -> None:
    """``status: 5`` is not a status. The row still shows, with that field unreadable."""
    _, _, run_dir = mutable_run
    _patch_summary(
        run_dir,
        islands={"a": {"island_id": "a", "status": 5, "profile": ["performance"], "attempts": "12"}},
    )
    block = mutable_client.get(f"/api/runs/{run_id}").json()["islands"]
    assert block["state"] == "available"
    row = block["islands"]["a"]
    assert row["status"] is None and row["profile"] is None and row["attempts"] is None
    assert block["attempt_total"] is None, "a non-integer attempt never enters the total"


def test_the_group_function_is_what_the_endpoint_uses() -> None:
    """The endpoint must not re-shape the block on its way out."""
    recorded = islands_group(
        {"islands": {"a": {"attempts": 2, "best_score": 24.9}},
         "exchange": {"summaries": 1},
         "cost": {"total_tokens": 10, "by_island": {"a": {"tokens": 10}}, "shared_tokens": 0}}
    )
    assert recorded.state.value == "available"
    assert recorded.cost is not None
    assert recorded.cost.total_tokens == 10
    assert recorded.attempt_total == 2
    assert recorded.exchange is not None and recorded.exchange.summaries == 1
