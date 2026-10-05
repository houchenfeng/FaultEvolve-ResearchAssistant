"""Baseline manifest builder."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from faultevolve.config import EvolveConfig


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return f"sha256:{h.hexdigest()}"


def _package_versions() -> dict[str, str]:
    import importlib.metadata as md

    names = ["numpy", "pandas", "scikit-learn", "lightgbm", "pydantic", "PyYAML"]
    out: dict[str, str] = {}
    for name in names:
        try:
            out[name] = md.version(name)
        except Exception:
            out[name] = "unknown"
    return out


def _scan_secrets(payload: str, env: dict[str, str]) -> None:
    for key in ("DASHSCOPE_API_KEY", "TYPESAFE_API_KEY", "FE_API_KEY"):
        val = env.get(key)
        if val and val in payload:
            raise ValueError(f"manifest contains secret from {key}")


def build_manifest(
    repo_root: Path,
    task_dir: Path,
    config_path: Path | None,
    run_dir: Path | None = None,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    env = env or dict(os.environ)
    cfg = EvolveConfig.from_yaml(config_path) if config_path and config_path.exists() else EvolveConfig()
    effective = cfg.model_dump()
    config_hash = hashlib.sha256(
        json.dumps(effective, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    data_dir = task_dir / "data" / "public"
    real_symlink = (task_dir / "data").is_symlink()
    files = {
        "train_labels.csv": data_dir / "train_labels.csv",
        "train_history.csv.gz": data_dir / "train_history.csv.gz",
        "val_history.csv.gz": data_dir / "val_history.csv.gz",
        "val_index.csv": data_dir / "val_index.csv",
    }
    data_meta: dict[str, Any] = {"realpath_is_symlink": real_symlink}
    for name, path in files.items():
        if path.exists():
            data_meta[name] = {"sha256": _sha256_file(path), "rows": None}
    protected = {
        "evaluator.py": task_dir / "evaluator.py",
        "init.py": task_dir / "init.py",
        "problem.md": task_dir / "problem.md",
        "prompt.md": task_dir / "prompt.md",
    }
    task_files = {k: _sha256_file(v) for k, v in protected.items() if v.exists()}
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo_root, text=True).strip()
    dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=repo_root, text=True).strip())
    base_url = cfg.llm.base_url or ""
    host = re.sub(r"^https?://", "", base_url).split("/")[0] if base_url else ""
    manifest: dict[str, Any] = {
        "schema": 1,
        "git": {"commit": commit, "dirty": dirty},
        "python": sys.version.split()[0],
        "packages": _package_versions(),
        "effective_config": effective,
        "config_hash": f"sha256:{config_hash}",
        "task": {"adapter": cfg.task.adapter, "files": task_files},
        "data": data_meta,
        "evaluator_hash": task_files.get("evaluator.py", ""),
        "models": {
            "generate_model": cfg.llm.generate_model,
            "reason_model": cfg.llm.reason_model,
            "base_url_host": host or "dashscope.aliyuncs.com",
        },
        "seed": cfg.seed,
        "threads": {
            "OMP_NUM_THREADS": env.get("OMP_NUM_THREADS"),
            "OPENBLAS_NUM_THREADS": env.get("OPENBLAS_NUM_THREADS"),
            "MKL_NUM_THREADS": env.get("MKL_NUM_THREADS"),
            "LIGHTGBM_NUM_THREADS": env.get("LIGHTGBM_NUM_THREADS"),
        },
        "budget": {
            "max_iterations": cfg.budget.max_iterations,
            "max_tokens": cfg.budget.max_tokens,
            "max_wall_hours": cfg.budget.max_wall_hours,
            "full_eval_cap": cfg.autotune.ledger.full_eval_cap if hasattr(cfg, "autotune") else None,
        },
        "artifacts": {},
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    if run_dir:
        manifest["artifacts"]["run_dir"] = str(run_dir)
        db = run_dir / "fe.db"
        if db.exists():
            manifest["artifacts"]["db_sha256"] = _sha256_file(db)
        rs = run_dir / "run_summary.json"
        if rs.exists():
            manifest["artifacts"]["run_summary_sha256"] = _sha256_file(rs)
    text = json.dumps(manifest, ensure_ascii=False)
    if "holdout" in text or "eval_only" in text:
        raise ValueError("manifest must not reference holdout/eval_only")
    _scan_secrets(text, env)
    return manifest
