#!/usr/bin/env python3
"""Validate budget-related fields in run_summary.json."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: check_budget_summary.py <artifacts_dir>", file=sys.stderr)
        sys.exit(2)

    art = Path(sys.argv[1])
    summaries = list(art.glob("*/run_summary.json"))
    if not summaries:
        summaries = [art / "run_summary.json"]
    path = summaries[0]
    if not path.is_file():
        print(f"Missing run_summary.json under {art}", file=sys.stderr)
        sys.exit(1)

    summary = json.loads(path.read_text(encoding="utf-8"))
    gain = summary.get("best_score", 0) - summary.get("initial_score", 0)
    assert "tokens_per_ros_point" in summary
    if gain > 0:
        assert summary["tokens_per_ros_point"] is not None
        assert summary["tokens_per_ros_point"] > 0
    assert summary.get("value_mode") == "multi"
    hits = summary.get("stage_cap_hits") or {}
    assert hits.get("reflect", 0) > 0
    assert summary.get("budget_stop_reason", "") in (
        "",
        "stagnation",
        "tokens_per_point_cap",
    )
    elite = summary.get("elite_archive_sizes") or {}
    assert "rank" in elite and "threshold" in elite
    assert isinstance(summary.get("best_score"), (int, float))
    print(json.dumps({
        "ok": True,
        "tokens_per_ros_point": summary.get("tokens_per_ros_point"),
        "value_mode": summary.get("value_mode"),
        "stage_cap_hits": hits,
        "budget_stop_reason": summary.get("budget_stop_reason"),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
