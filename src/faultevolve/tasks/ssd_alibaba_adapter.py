"""Alibaba Cloud SSD dataset adapter (stub; schema helpers for future converter)."""

from __future__ import annotations

import re
from typing import Any

import pandas as pd

from faultevolve.tasks.stub_base import StubDatasetAdapter

SMARTLOG_ID_COLS = ("disk_id", "ds", "model")
# 51 ids per format; verify against dcbrain readme when implementing
SMARTLOG_ATTR_PATTERN = re.compile(r"^[nr]_\d+$")
FAILURE_LABEL_COLUMNS = ("model", "disk_id", "failure_time")
OPEN_DATA_TAG_COLUMNS = (
    "model",
    "failure_time",
    "failure",
    "app",
    "machine_room_id",
    "rack_id",
    "node_id",
    "disk_id",
)


class AlibabaSSDAdapter(StubDatasetAdapter):
    DATASET_NAME = "alibaba_ssd"
    DOC_PATH = "docs/datasets/alibaba_ssd.md"
    DATA_ROOT_ENV = "ALIBABA_SSD_DATA_ROOT"
    REQUIRED_DATA_FILES = (
        "public/train_history.csv.gz",
        "public/train_labels.csv",
        "public/val_history.csv.gz",
        "public/val_index.csv",
    )

    @staticmethod
    def validate_smartlog_frame(df: pd.DataFrame) -> None:
        missing = [c for c in SMARTLOG_ID_COLS if c not in df.columns]
        if missing:
            raise ValueError(f"missing required smartlog columns: {missing}")
        extra = [
            c
            for c in df.columns
            if c not in SMARTLOG_ID_COLS and not SMARTLOG_ATTR_PATTERN.match(c)
        ]
        if extra:
            raise ValueError(f"invalid smartlog columns: {extra}")

    @staticmethod
    def validate_failure_labels(df: pd.DataFrame) -> None:
        missing = [c for c in FAILURE_LABEL_COLUMNS if c not in df.columns]
        if missing:
            raise ValueError(f"missing failure label columns: {missing}")

    @staticmethod
    def rename_to_task_schema(df: pd.DataFrame) -> pd.DataFrame:
        AlibabaSSDAdapter.validate_smartlog_frame(df)
        out = df.copy()
        out["serial_number"] = out["disk_id"].astype(str)
        ds = out["ds"].astype(str).str.zfill(8)
        out["date"] = pd.to_datetime(ds, format="%Y%m%d").dt.strftime("%Y-%m-%d")
        smart_cols: list[str] = []
        for col in sorted(
            [c for c in df.columns if SMARTLOG_ATTR_PATTERN.match(c)],
            key=lambda x: (x[0], int(x[2:])),
        ):
            attr_id = col.split("_", 1)[1]
            if col.startswith("n_"):
                name = f"smart_{attr_id}_normalized"
                out[name] = out[col]
                smart_cols.append(name)
            elif col.startswith("r_"):
                name = f"smart_{attr_id}_raw"
                out[name] = out[col]
                smart_cols.append(name)
        return out[["date", "serial_number", "model"] + smart_cols]

    def context_keywords(self, code: str) -> list[str]:
        ids = {m.group(1) for m in re.finditer(r"smart_(\d+)", code)}
        return [f"ssd_smart_{i}" for i in sorted(ids, key=int)]
