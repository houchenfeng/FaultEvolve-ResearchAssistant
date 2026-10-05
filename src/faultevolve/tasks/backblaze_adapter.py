"""Backblaze HDD variant adapter (hdd_mvp-isomorphic evaluator, separate data/knowledge)."""

from __future__ import annotations

import os
from pathlib import Path

from faultevolve.tasks.hdd_adapter import HDDAdapter
from faultevolve.tasks.protocol import DataStatus, TaskSpec


class BackblazeAdapter(HDDAdapter):
    """HDD adapter with Backblaze task directory and prepare_data hints."""

    DATASET_NAME = "backblaze_hdd"

    def data_status(self, task_dir: Path) -> DataStatus:
        task_dir = task_dir.resolve()
        evaluator_path = task_dir / "evaluator.py"
        task_spec = TaskSpec(
            task_dir=task_dir,
            problem_md="",
            prompt_md="",
            init_code="",
            evaluator_path=evaluator_path,
        )
        data_dir = self._get_data_dir(task_spec)
        required = [
            "train_history.csv.gz",
            "train_labels.csv",
            "val_history.csv.gz",
            "val_index.csv",
        ]
        missing = [name for name in required if not (data_dir / name).exists()]
        ok = not missing
        message = f"data dir {data_dir}"
        if missing:
            message += f"; missing: {missing}"
            prepare = task_dir / "prepare_data.py"
            if prepare.exists():
                message += f"; run: python {prepare}"
            message += "; see docs/datasets/backblaze.md"
        env_val = os.environ.get("HDD_BENCH_DATA_ROOT")
        if env_val:
            message += f" (HDD_BENCH_DATA_ROOT={env_val})"
        return DataStatus(
            ok=ok,
            data_dir=str(data_dir),
            missing=missing,
            message=message,
        )
