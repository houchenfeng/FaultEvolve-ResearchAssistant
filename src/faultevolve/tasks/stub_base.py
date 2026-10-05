"""Base adapter for dataset stubs (interface + docs, no evaluator yet)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from faultevolve.tasks.famou_adapter import FamouAdapter
from faultevolve.tasks.protocol import DataStatus, EvalResult, TaskSpec


class DataNotPreparedError(NotImplementedError):
    """Raised when stub task data or evaluator is not available."""


class StubDatasetAdapter(FamouAdapter):
    """Famou-style stub: validates layout, defers evaluation to a future PR."""

    DATASET_NAME: str = ""
    DOC_PATH: str = ""
    DATA_ROOT_ENV: str = ""
    REQUIRED_DATA_FILES: tuple[str, ...] = ()

    def __init__(self, min_noise_delta: float = 0.5) -> None:
        super().__init__(min_noise_delta=min_noise_delta)

    def _not_ready(self, what: str) -> DataNotPreparedError:
        return DataNotPreparedError(
            f"{self.DATASET_NAME}: {what} not implemented / data not prepared. "
            f"See {self.DOC_PATH}"
        )

    def data_root(self, task_dir: Path) -> Path:
        env_val = os.environ.get(self.DATA_ROOT_ENV)
        if env_val:
            return Path(env_val)
        return task_dir / "data"

    def data_status(self, task_dir: Path) -> DataStatus:
        root = self.data_root(task_dir)
        missing: list[str] = []
        for rel in self.REQUIRED_DATA_FILES:
            if not (root / rel).exists():
                missing.append(rel)
        ok = len(missing) == 0
        message = f"data dir {root}; missing: {missing}" if missing else f"data dir {root}; ok"
        env_val = os.environ.get(self.DATA_ROOT_ENV)
        if env_val:
            message += f" ({self.DATA_ROOT_ENV}={env_val})"
        return DataStatus(ok=ok, data_dir=str(root), missing=missing, message=message)

    def load_task(self, task_dir: Path) -> TaskSpec:
        task_dir = task_dir.resolve()
        missing = [f for f in self.REQUIRED_FILES if not (task_dir / f).exists()]
        if missing:
            raise self._not_ready("task files")
        return super().load_task(task_dir)

    def evaluate(self, code: str, task_spec: TaskSpec, timeout: int = 900) -> EvalResult:
        raise self._not_ready("evaluator")

    def smoke_test(
        self,
        code: str,
        task_spec: TaskSpec,
        timeout: int = 60,
        sample_fraction: float = 0.02,
        smoke_data_dir: Path | None = None,
    ) -> EvalResult:
        raise self._not_ready("evaluator")

    def build_smoke_data_dir(
        self,
        task_spec: TaskSpec,
        sample_fraction: float = 0.02,
        min_positives: int = 20,
        seed: int = 20260926,
        cache_dir: Path | None = None,
    ) -> Path | None:
        raise self._not_ready("evaluator")

    def constraints(self, task_spec: TaskSpec) -> str:
        return (
            f"本任务为 {self.DATASET_NAME} 数据集 stub：评估器与数据准备尚未完成，"
            f"暂不可用于真实进化。请参阅 {self.DOC_PATH} 了解后续步骤。"
        )
