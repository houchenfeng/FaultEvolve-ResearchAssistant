#!/usr/bin/env python3
"""Rebuild baseline metrics from run artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from faultevolve.optimization.baseline_metrics import compute_baseline_metrics


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, required=True)
    ap.add_argument("--events", type=Path, default=None)
    ap.add_argument("--run-summary", type=Path, default=None)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()
    metrics = compute_baseline_metrics(
        args.db,
        events_path=args.events,
        run_summary_path=args.run_summary,
    )
    text = json.dumps(metrics, indent=2, ensure_ascii=False)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    else:
        print(text)


if __name__ == "__main__":
    main()
