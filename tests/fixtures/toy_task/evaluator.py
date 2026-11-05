"""Toy evaluator for testing.

This evaluator returns deterministic scores based on code content
to enable testing of the evolution loop without actual data.
"""

from __future__ import annotations

import hashlib
import re
import tempfile
from pathlib import Path


def static_check(source: str) -> str:
    """Check for forbidden patterns."""
    forbidden = [
        (r"\.parent\b|\.\./", "path climbing"),
        (r"\bglob\b|\blistdir\b", "directory listing"),
        (r"\bsubprocess\b", "subprocess"),
    ]
    for pattern, reason in forbidden:
        if re.search(pattern, source):
            return f"Forbidden: {reason}"
    return ""


def evaluate(path_user_py: str, task_name: str = "default", timeout: int = 60, split: str = "val") -> dict:
    """Evaluate a toy candidate.

    Score is deterministic based on code hash, with bonuses for certain patterns.
    """
    try:
        code = Path(path_user_py).read_text(encoding="utf-8")
    except Exception as e:
        return {
            "validity": 0.0,
            "combined_score": 0.0,
            "cost_time": 0.0,
            "error_info": f"Cannot read file: {e}",
            "metric": {},
        }

    violation = static_check(code)
    if violation:
        return {
            "validity": 0.0,
            "combined_score": 0.0,
            "cost_time": 0.1,
            "error_info": violation,
            "metric": {},
        }

    code_hash = hashlib.sha256(code.encode()).hexdigest()
    base_score = (int(code_hash[:8], 16) % 1000) / 100.0 + 15.0

    if "lightgbm" in code.lower() or "lgbm" in code.lower():
        base_score += 3.0
    if "vendor" in code.lower() or "厂商" in code:
        base_score += 2.0
    if "trend" in code.lower() or "diff" in code.lower():
        base_score += 1.5
    if "threshold" in code.lower():
        base_score += 1.0

    base_score = min(base_score, 35.0)

    return {
        "validity": 1.0,
        "combined_score": round(base_score, 2),
        "cost_time": 0.5,
        "error_info": "",
        "metric": {
            "f1": round(base_score / 100, 4),
            "f1_p10": round(base_score / 100 * 0.95, 4),
            "f1_boot_std": 0.02,
            "auprc": round(base_score / 100 * 0.8, 4),
            "recall_at_far": round(base_score / 100 * 0.6, 4),
            "false_alarm_rate": 0.002,
            "split": split,
        },
    }


if __name__ == "__main__":
    import json
    import sys

    if len(sys.argv) > 1:
        result = evaluate(sys.argv[1])
        print(json.dumps(result, indent=2))
