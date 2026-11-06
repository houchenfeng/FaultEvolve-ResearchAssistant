"""Filesystem locations used by the edge demo."""

from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
TASK_DIR = REPO_ROOT / "benchmark" / "hdd_mvp"
DATA_ROOT = Path(os.environ.get("HDD_BENCH_DATA_ROOT", TASK_DIR / "data")).resolve()
PUBLIC_DIR = DATA_ROOT / "public"
LABELS_DIR = DATA_ROOT / "eval_only"
EVALUATOR = TASK_DIR / "evaluator.py"
BASELINE_PROGRAM = TASK_DIR / "init.py"

CLOUD_RUN_ID = "hdd_mvp_formal2b_20261009"
CLOUD_RUN_DIR = REPO_ROOT / "showcase" / "edge" / CLOUD_RUN_ID
EVOLVED_NODE_ID = "4016914b"
EVOLVED_PROGRAM = CLOUD_RUN_DIR / "programs" / f"{EVOLVED_NODE_ID}.py"

TABLET_DIST = REPO_ROOT / "edge-tablet" / "dist"
CACHE_DIR = Path(os.environ.get("FE_EDGE_CACHE", REPO_ROOT / ".fe" / "edge")).resolve()
