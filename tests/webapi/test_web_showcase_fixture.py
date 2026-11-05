"""Guards for the unified Web showcase replay fixture."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

REPO = Path(__file__).resolve().parents[2]
SHOWCASE_RUN_ID = "hdd_mvp_showcase_c89e2a01"
CLAIM_C89 = "C-89f4bdd1-0010"
BEST_SCORE = 38.139345971596875


def test_showcase_fixture_files_on_disk() -> None:
    root = REPO / "tests" / "fixtures" / "runs" / SHOWCASE_RUN_ID
    assert root.is_dir()
    summary = json.loads((root / "run_summary.json").read_text(encoding="utf-8"))
    assert abs(summary["best_score"] - BEST_SCORE) < 0.02
    assert summary.get("fixture_showcase") is True

    phenomena = json.loads((root / "discovery/phenomena.json").read_text(encoding="utf-8"))
    row = next(p for p in phenomena if p["claim_id"] == CLAIM_C89)
    assert row["grade"] == "confirmed"
    assert "smart_194_normalized" in json.dumps(row["payload"])


def test_showcase_discovery_api(client: TestClient) -> None:
    """Requires conftest ``settings`` to include the showcase run directory."""
    detail = client.get(f"/api/runs/{SHOWCASE_RUN_ID}").json()
    assert detail["data_state"] == "complete"
    assert abs((detail.get("outcome") or {}).get("best_score", 0) - BEST_SCORE) < 0.02

    discovery = client.get(f"/api/runs/{SHOWCASE_RUN_ID}/discovery").json()
    grades = {p["claim_id"]: p["grade"] for p in discovery.get("phenomena") or []}
    assert grades.get(CLAIM_C89) == "confirmed"
    assert discovery.get("certificates")
