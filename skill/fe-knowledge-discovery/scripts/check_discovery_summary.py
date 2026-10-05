#!/usr/bin/env python3
"""Assert discovery fields in run_summary.json or discover-only artifacts."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

_DISCOVERY_FILES = (
    "phenomena.json",
    "preregistration.json",
    "controls.json",
    "discovered_cards.snapshot.jsonl",
)

_BARE_EXIT_RE = re.compile(r"^exit \d+$")


def _check_sandbox_errors(payload: dict) -> None:
    failed = int(payload.get("claims_sandbox_failed") or 0)
    if failed <= 0:
        return
    errors = payload.get("sandbox_errors") or []
    assert len(errors) >= failed, "sandbox_errors missing entries for failed claims"
    for entry in errors:
        tail = (entry.get("error_tail") or "").strip()
        assert not _BARE_EXIT_RE.match(tail), f"bare exit code in error_tail: {tail!r}"


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: check_discovery_summary.py <artifacts_dir>", file=sys.stderr)
        sys.exit(2)
    art = Path(sys.argv[1])
    summ_path = art / "run_summary.json"
    disc = art / "discovery"
    discover_payload: dict | None = None
    if summ_path.exists():
        data = json.loads(summ_path.read_text(encoding="utf-8"))
        assert data.get("discovery_tokens", 0) >= 0
        if data.get("discovery_tokens", 0) > 0:
            assert data["discovery_tokens"] <= data.get("total_tokens", 0)
        if data.get("discovery_rounds", 0) > 0:
            for name in _DISCOVERY_FILES:
                assert (disc / name).exists(), name
        discover_payload = data
    else:
        for name in _DISCOVERY_FILES:
            assert (disc / name).exists(), name
    funnel_path = disc / "funnel.json"
    if funnel_path.exists():
        funnel = json.loads(funnel_path.read_text(encoding="utf-8"))
        assert isinstance(funnel, list)
        if funnel:
            detail = funnel[0].get("detail") or {}
            for key in ("explore_effect", "power_gate_pass", "lane"):
                assert key in detail or funnel[0].get("stage_reached") == "proposed", key
    audit_path = disc / "data_audit.json"
    if audit_path.exists():
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        assert "min_explore_effect" in audit
        assert "explore_only" in audit
    if discover_payload is not None:
        _check_sandbox_errors(discover_payload)
    print("ok")


if __name__ == "__main__":
    main()
