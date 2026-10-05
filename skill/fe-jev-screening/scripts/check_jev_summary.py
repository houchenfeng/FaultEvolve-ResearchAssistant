#!/usr/bin/env python3
"""Validate the newest mock Jev run without printing sensitive content."""

from __future__ import annotations

import json
import sys
from pathlib import Path


root = Path(sys.argv[1] if len(sys.argv) > 1 else ".fe-jev-mock")
summaries = sorted(root.glob("**/run_summary.json"), key=lambda path: path.stat().st_mtime)
if not summaries:
    raise SystemExit("未找到 run_summary.json")
summary = json.loads(summaries[-1].read_text(encoding="utf-8"))
assert summary["jev_calls"] > 0
assert summary["jev_tokens"] > 0
assert summary["candidates_screened"] > 0
assert summary["evaluations_saved"] > 0
assert summary["screening_precision"] is not None
assert summary["jev_prior_active"] is True
keys = [
    "jev_calls", "jev_tokens", "candidates_screened", "evaluations_saved",
    "screening_precision", "jev_prior_active",
]
print(json.dumps({key: summary[key] for key in keys}, ensure_ascii=False))
