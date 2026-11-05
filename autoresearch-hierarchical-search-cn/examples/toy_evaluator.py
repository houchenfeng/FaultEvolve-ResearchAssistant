from __future__ import annotations

import argparse
import json
from pathlib import Path


def score_candidate(route_id: str, parameters: dict[str, float], phase: str) -> float:
    if route_id == "method_a":
        score = 0.50 + 0.08 * float(parameters["depth"]) + 0.15 * float(parameters["weight"])
    elif route_id == "method_b":
        score = 0.55 + 0.25 * float(parameters["alpha"])
    else:
        raise ValueError(f"未知路线: {route_id}")
    if phase == "holdout":
        score -= 0.02
    return round(score, 6)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    candidate = json.loads(args.candidate.read_text(encoding="utf-8"))
    score = score_candidate(candidate["route_id"], candidate["parameters"], candidate["phase"])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            {
                "score": score,
                "integrity_passed": True,
                "details": {"deterministic_toy_evaluator": True},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
