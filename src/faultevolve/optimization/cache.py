"""Evaluation result cache keys."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


def env_fingerprint(threads: int) -> dict[str, Any]:
    import importlib.metadata as md

    def _ver(name: str) -> str:
        try:
            return md.version(name)
        except Exception:
            return "unknown"

    return {
        "python": sys.version.split()[0],
        "numpy": np.__version__,
        "pandas": pd.__version__,
        "scikit-learn": _ver("scikit-learn"),
        "lightgbm": _ver("lightgbm"),
        "threads": threads,
        "platform": platform.machine(),
        "cpu_count": os.cpu_count(),
        "OMP_NUM_THREADS": os.environ.get("OMP_NUM_THREADS"),
        "OPENBLAS_NUM_THREADS": os.environ.get("OPENBLAS_NUM_THREADS"),
        "MKL_NUM_THREADS": os.environ.get("MKL_NUM_THREADS"),
    }


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def cache_key(
    *,
    source_hash: str,
    config_hash: str,
    data_version: str,
    evaluator_hash: str,
    fidelity: str,
    seed: int,
    env_fingerprint: dict[str, Any],
) -> str:
    payload = {
        "source_hash": source_hash,
        "config_hash": config_hash,
        "data_version": data_version,
        "evaluator_hash": evaluator_hash,
        "fidelity": fidelity,
        "seed": seed,
        "env": env_fingerprint,
    }
    digest = hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def data_version_from_paths(paths: list[Path]) -> str:
    parts = []
    for p in paths:
        rp = p.resolve()
        stat = rp.stat()
        parts.append({"path": str(rp), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns})
    digest = hashlib.sha256(_canonical(parts).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"
