#!/usr/bin/env python3
"""Validate operator bandit fields in run_summary.json."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: check_operator_summary.py <artifacts_dir>", file=sys.stderr)
        sys.exit(2)

    art = Path(sys.argv[1])
    summaries = list(art.glob("*/run_summary.json"))
    if not summaries:
        summaries = [art / "run_summary.json"]
    summary_path = summaries[0]
    if not summary_path.is_file():
        raise SystemExit(f"Missing run_summary.json under {art}")
    data = json.loads(summary_path.read_text(encoding="utf-8"))
    required = (
        "operator_counts",
        "operator_valid_rate",
        "operator_mean_delta",
        "operator_posteriors",
        "operator_tokens",
        "generative_valid_rate",
        "bandit_active",
    )
    for key in required:
        if key not in data:
            raise SystemExit(f"missing field: {key}")
    if not data["bandit_active"]:
        raise SystemExit("bandit_active must be true")
    counts = data["operator_counts"]
    if not counts:
        raise SystemExit("operator_counts is empty")
    if sum(counts.values()) <= 0:
        raise SystemExit("sum(operator_counts) must be > 0")
    print(json.dumps({"ok": True, "operator_counts": counts}, ensure_ascii=False))


if __name__ == "__main__":
    main()
