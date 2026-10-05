#!/usr/bin/env python3
"""Validate tournament-related fields in run_summary.json."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    art = Path(sys.argv[1])
    summary_path = art / "run_summary.json"
    if not summary_path.exists():
        print("missing run_summary.json", file=sys.stderr)
        return 1
    data = json.loads(summary_path.read_text(encoding="utf-8"))
    mech = int(data.get("mechanism_tokens", 0) or 0)
    tour = int(data.get("tournament_tokens", 0) or 0)
    if mech != tour:
        print("mechanism_tokens must equal tournament_tokens", file=sys.stderr)
        return 1
    total = int(data.get("total_tokens", 0) or 0)
    if mech > total:
        print("mechanism_tokens exceeds total_tokens", file=sys.stderr)
        return 1
    proposed = int(data.get("mechanisms_proposed", 0) or 0)
    if proposed == 0:
        return 0
    est = int(data.get("mechanisms_established", 0) or 0)
    ref = int(data.get("mechanisms_refuted", 0) or 0)
    und = proposed - est - ref
    if und < 0:
        print("mechanism status counts inconsistent", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
