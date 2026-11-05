"""Knowledge-card prose is copied from the registered task catalog only."""

from __future__ import annotations

import shutil
from pathlib import Path

from fastapi.testclient import TestClient

from faultevolve.webapi.app import create_app
from faultevolve.webapi.run_registry import RunRecord, insert_record
from faultevolve.webapi.settings import WebSettings

_FIXTURE = (
    Path(__file__).resolve().parents[1] / "fixtures" / "runs" / "hdd_mvp_demo_7510f100"
)
_RUN_ID = "hdd_mvp_demo_7510f100"


def test_registered_task_fills_matching_cards_only(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    shutil.copytree(_FIXTURE, runs / _RUN_ID)
    task = tmp_path / "tasks" / "hdd_mvp"
    knowledge = task / "knowledge"
    knowledge.mkdir(parents=True)
    (task / "problem.md").write_text("task", encoding="utf-8")
    (knowledge / "cards.jsonl").write_text(
        "\n".join(
            [
                '{"id":"FE01","title":"Window deltas","category":"feature_engineering",'
                '"claim":"Deltas help. See C:\\\\Secret\\\\holdout.csv",'
                '"source_ids":["paper_a","note_b"],"tags":["smart_5"],'
                '"applicability":"All vendors","priority":1,"evidence":"paper"}',
                '{"id":"NOT_IN_RUN","title":"Unused","category":"model",'
                '"claim":"must not appear","source_ids":[],"tags":[]}',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (knowledge / "sources.yaml").write_text(
        "\n".join(
            [
                "- id: paper_a",
                "  title: A real paper",
                "  url: https://example.com/paper",
                "  takeaway: Deltas of cumulative counters predict failure.",
                "- id: note_b",
                "  title: Not a link",
                "  url: javascript:alert(1)",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    settings = WebSettings(
        runs_root=runs,
        task_roots=[tmp_path / "tasks"],
        allowed_path_roots=[runs, tmp_path / "tasks"],
        run_registry=tmp_path / "registry.sqlite",
    )
    insert_record(
        settings,
        RunRecord(
            run_id=_RUN_ID,
            execution_backend="local_cloud",
            server_profile_id=None,
            pid=None,
            status="completed",
            task_dir=str(task),
            db_dir=str(runs / _RUN_ID),
            artifacts_dir=str(runs / _RUN_ID),
            log_dir=None,
        ),
    )

    body = TestClient(create_app(settings)).get(
        f"/api/runs/{_RUN_ID}/knowledge/cards"
    ).json()
    by_id = {card["card_id"]: card for card in body}
    matched = by_id["FE01"]
    assert matched["title"] == "Window deltas"
    assert matched["category"] == "feature_engineering"
    assert matched["source_kind"] == "paper"
    assert matched["conditions"] == "All vendors"
    assert matched["priority"] == 1
    assert "<REDACTED_PATH>" in matched["claim"]
    assert "Secret" not in matched["claim"]
    assert matched["sources"] == [
        {
            "source_id": "paper_a",
            "title": "A real paper",
            "url": "https://example.com/paper",
            "takeaway": "Deltas of cumulative counters predict failure.",
        },
        {"source_id": "note_b", "title": "Not a link", "url": None, "takeaway": None},
    ]
    assert "javascript:" not in str(body)
    assert by_id["E01"]["claim"] is None
    assert by_id["E01"]["title"] is None
    assert by_id["E01"]["priority"] is None
    assert "NOT_IN_RUN" not in by_id
    assert "must not appear" not in str(body)
