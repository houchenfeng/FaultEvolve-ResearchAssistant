#!/usr/bin/env python3
"""Generate baseline manifest JSON."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from faultevolve.optimization.manifest import build_manifest


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-root", type=Path, default=Path("."))
    ap.add_argument("--task-dir", type=Path, required=True)
    ap.add_argument("--config", type=Path, default=None)
    ap.add_argument("--run-dir", type=Path, default=None)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    manifest = build_manifest(
        args.repo_root.resolve(),
        args.task_dir.resolve(),
        args.config,
        args.run_dir,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
