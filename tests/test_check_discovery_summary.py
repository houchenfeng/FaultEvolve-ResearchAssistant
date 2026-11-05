"""Tests for check_discovery_summary skill script."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def _run_script(art_dir: Path) -> subprocess.CompletedProcess[str]:
    script = Path(__file__).resolve().parents[1] / "skill/fe-knowledge-discovery/scripts/check_discovery_summary.py"
    return subprocess.run(
        [sys.executable, str(script), str(art_dir)],
        capture_output=True,
        text=True,
        check=False,
    )


def test_check_discovery_summary_rejects_bare_exit(tmp_path: Path):
    art = tmp_path / "run"
    art.mkdir()
    disc = art / "discovery"
    disc.mkdir()
    for name in (
        "phenomena.json",
        "preregistration.json",
        "controls.json",
        "discovered_cards.snapshot.jsonl",
    ):
        (disc / name).write_text("{}", encoding="utf-8")
    (art / "run_summary.json").write_text(
        json.dumps(
            {
                "discovery_tokens": 1,
                "total_tokens": 10,
                "discovery_rounds": 1,
                "claims_sandbox_failed": 1,
                "sandbox_errors": [{"claim_id": "C-x", "error_tail": "exit 3"}],
            }
        ),
        encoding="utf-8",
    )
    proc = _run_script(art)
    assert proc.returncode != 0
