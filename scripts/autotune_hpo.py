#!/usr/bin/env python3
"""CLI wrapper for structured HPO."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from faultevolve.config import EvolveConfig
from faultevolve.optimization.hpo_runner import run_hpo


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task-dir", type=Path, required=True)
    ap.add_argument("--config", type=Path, required=True)
    ap.add_argument("--runs-dir", type=Path, required=True)
    ap.add_argument("--artifacts-dir", type=Path, required=True)
    ap.add_argument("--mock-eval", action="store_true")
    args = ap.parse_args()
    cfg = EvolveConfig.from_yaml(args.config)
    if not cfg.autotune.hpo.enabled:
        print("autotune.hpo.enabled is false; exiting", file=sys.stderr)
        return 2
    run_hpo(
        args.task_dir,
        cfg,
        runs_dir=args.runs_dir,
        artifacts_dir=args.artifacts_dir,
        mock_eval=args.mock_eval,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
