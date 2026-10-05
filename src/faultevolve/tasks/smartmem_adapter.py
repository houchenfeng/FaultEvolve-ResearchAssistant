"""SmartMem DRAM failure prediction adapter (official schema validators + sampling delegation)."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pandas as pd

from faultevolve.tasks.protocol import EvalResult, TaskSpec
from faultevolve.tasks.stub_base import StubDatasetAdapter

MCELOG_COLUMNS = (
    "cpuid",
    "channelid",
    "dimmid",
    "rankid",
    "deviceid",
    "bankgroupid",
    "bankid",
    "rowid",
    "columnid",
    "retryrderrlogparity",
    "retryrderrlog",
    "burst_info",
    "error_type",
    "log_time",
    "manufacturter",
    "model",
    "PN",
    "Capacity",
    "FrequencyMHz",
    "MaxSpeedMHz",
    "McaBank",
    "memory_type",
    "region",
)
TICKET_COLUMNS = ("serial_number", "failure_time", "serial_number_type")
SUBMISSION_COLUMNS = ("sn_name", "prediction_timestamp", "serial_number_type")
LEAD_MINUTES = 15
PREDICT_WINDOW_DAYS = 7
SERIAL_TYPES = ("A", "B")

#: Injected into refine and repair prompts. Every line is a rule the task's own evaluator enforces;
#: the wording of the third point is the provisional reading recorded from the official pages.
SMARTMEM_CONSTRAINTS = """以下是 SmartMem DRAM 故障预测任务的硬约束，违反任何一条都会让 validity 归 0：

1. **只能读公开快照的四个文件**：`train_samples.csv.gz`、`train_labels.csv`、`<split>_index.csv`、
   `<split>_samples.csv.gz`，路径一律由 `--data-dir` 拼出来。工单表（标签来源）与原始事件流
   （`.feather` / mcelog）在静态检查里就是关键词。

2. **输出合同**：`--out` 写的 CSV 必须含 `sample_id,score,alarm` 三列；`alarm` 只能是 0 或 1；
   每个 `sample_id` 只能出现一次，且必须来自本次 `--data-dir` 里的 `<split>_index.csv`。
   告警时刻由 evaluator 从 index join 得到，候选不得自己声明时刻，也不得报别的切片的行。

3. **判分口径（暂定）**：SN 级去重 + 落窗——同一序列号报多次只算一次，命中必须落在
   `[alarm-7d, alarm-15min]` 之内。多报几乎免费，漏报与报错同样致命，所以报警预算才是问题。

4. **运行时间**：默认 900 秒超时，超时即 validity=0；切片可达数万行，避免逐行 Python 循环。

5. **允许的依赖**：pandas、numpy、scikit-learn、scipy、lightgbm。"""


class SmartMemAdapter(StubDatasetAdapter):
    DATASET_NAME = "smartmem"
    DOC_PATH = "docs/datasets/smartmem.md"
    DATA_ROOT_ENV = "SMARTMEM_DATA_ROOT"
    #: What ``prepare_data.py`` in sample mode actually writes. The list used to name a
    #: ``public/`` layout no tool ever produced, which made the readiness check report a contract
    #: the repository does not hold.
    REQUIRED_DATA_FILES = (
        "manifest.json",
        "partitions/samples",
        "partitions/units/serial_type",
        "partitions/audit/summary",
    )
    #: The loop grades candidates on dev; a val number is what the command line reports at the end.
    EVALUATE_SPLIT = "dev"

    def evaluate(self, code: str, task_spec: TaskSpec, timeout: int = 900) -> EvalResult:
        """Run one candidate through this task's own evaluator and hand back its verdict.

        ``data_root`` travels as an argument rather than as the environment: the workers of one run
        share a process, and a global each of them rewrote would decide which candidate saw which
        data.
        """
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, encoding="utf-8"
        ) as handle:
            handle.write(code)
            candidate = Path(handle.name)
        try:
            evaluator = self._load_evaluator(task_spec.evaluator_path)
            result = evaluator.evaluate(
                str(candidate),
                timeout=timeout,
                split=self.EVALUATE_SPLIT,
                data_root=str(self.data_root(task_spec.task_dir)),
            )
            return EvalResult(
                validity=float(result.get("validity", 0)),
                combined_score=float(result.get("combined_score", 0)),
                cost_time=float(result.get("cost_time", 0)),
                error_info=str(result.get("error_info", "")),
                metric=dict(result.get("metric") or {}),
            )
        except Exception as exc:  # noqa: BLE001 - a broken candidate must not break the loop
            return EvalResult(
                validity=0.0,
                combined_score=0.0,
                cost_time=0.0,
                error_info=f"Evaluation failed: {type(exc).__name__}: {exc}",
                metric={},
            )
        finally:
            candidate.unlink(missing_ok=True)

    def constraints(self, task_spec: TaskSpec) -> str:
        """Return the hard rules a candidate has to satisfy; the evaluator enforces every one."""
        return SMARTMEM_CONSTRAINTS

    @staticmethod
    def validate_mcelog_frame(df: pd.DataFrame) -> None:
        missing = [c for c in MCELOG_COLUMNS if c not in df.columns]
        if missing:
            raise ValueError(f"missing mcelog columns: {missing}")

    @staticmethod
    def validate_ticket_frame(df: pd.DataFrame) -> None:
        missing = [c for c in TICKET_COLUMNS if c not in df.columns]
        if missing:
            raise ValueError(f"missing ticket columns: {missing}")
        bad = df[~df["serial_number_type"].isin(SERIAL_TYPES)]
        if not bad.empty:
            raise ValueError(
                f"invalid serial_number_type values: {bad['serial_number_type'].unique().tolist()}"
            )

    @staticmethod
    def validate_submission_frame(df: pd.DataFrame) -> None:
        missing = [c for c in SUBMISSION_COLUMNS if c not in df.columns]
        if missing:
            raise ValueError(f"missing submission columns: {missing}")
        bad = df[~df["serial_number_type"].isin(SERIAL_TYPES)]
        if not bad.empty:
            raise ValueError(
                f"invalid serial_number_type values: {bad['serial_number_type'].unique().tolist()}"
            )

    @staticmethod
    def aggregate_events_to_samples(
        events: pd.DataFrame, tickets: pd.DataFrame, **kwargs
    ) -> pd.DataFrame:
        """Build labeled samples with history features; the rules live in ``smartmem_data``.

        Thin delegation on purpose: windowing, the five-way label decision, censoring and the
        feature families are implemented once in
        :func:`faultevolve.tasks.smartmem_data.aggregate_events_to_samples`, whose keyword-only
        surface (``outcome_observed_until``, ``timezone``, ``lookback`` / ``lead`` / ``horizon`` /
        ``anchor_frequency``, the legacy ``*_days`` / ``*_minutes`` aliases, ``error_types``,
        ``feature_groups``, ``add_features``, ``report``) is forwarded here untouched.
        """
        from faultevolve.tasks.smartmem_data import (
            aggregate_events_to_samples as _aggregate,
        )

        return _aggregate(events, tickets, **kwargs)
