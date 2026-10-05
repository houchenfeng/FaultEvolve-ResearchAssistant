#!/usr/bin/env python3
"""Validate crossover fields in run_summary.json."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python check_crossover_summary.py <artifacts_dir>", file=sys.stderr)
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
        "crossover_count",
        "crossover_valid_rate",
        "crossover_mean_delta",
        "crossover_best_gain",
        "crossover_tokens",
    )
    for key in required:
        if key not in data:
            print(f"missing field: {key}", file=sys.stderr)
            sys.exit(1)

    if data["crossover_count"] <= 0:
        print("crossover_count must be > 0", file=sys.stderr)
        sys.exit(1)
    if data["crossover_tokens"] <= 0:
        print("crossover_tokens must be > 0", file=sys.stderr)
        sys.exit(1)
    rate = data["crossover_valid_rate"]
    if rate is None or not (0.0 <= rate <= 1.0):
        print("crossover_valid_rate must be in [0,1]", file=sys.stderr)
        sys.exit(1)

    print(json.dumps({k: data[k] for k in required}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
