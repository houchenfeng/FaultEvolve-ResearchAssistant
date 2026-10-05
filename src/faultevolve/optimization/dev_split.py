"""Time-blocked dev split with path guards."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

FORBIDDEN_PATH_TOKENS = ("eval_only",)
FORBIDDEN_FILENAMES = {
    "val_labels.csv",
    "val_index.csv",
    "val_history.csv.gz",
}
ALLOWED_TRAIN_FILES = {"train_labels.csv", "train_history.csv.gz"}


class DevSplitError(RuntimeError):
    """Dev split could not be constructed."""


class DataAccessError(RuntimeError):
    """Forbidden data path."""


def assert_public_train_only(path: Path) -> Path:
    resolved = path.resolve()
    parts = {p.lower() for p in resolved.parts}
    if "eval_only" in parts:
        raise DataAccessError(f"forbidden path component eval_only: {resolved}")
    for part in resolved.parts:
        if part.lower().startswith("holdout"):
            raise DataAccessError(f"forbidden holdout path: {resolved}")
    if path.name not in ALLOWED_TRAIN_FILES:
        raise DataAccessError(f"only public train files allowed, got {path.name}")
    return resolved


@dataclass(frozen=True)
class DevSplit:
    train_labels: pd.DataFrame
    dev_labels: pd.DataFrame
    report: dict


def make_time_blocked_split(
    labels: pd.DataFrame,
    *,
    serial_col: str,
    cutoff_col: str,
    label_col: str,
    horizon_days: int,
    late_fraction: float,
    purge_days: int,
    min_pos_train: int,
    min_pos_dev: int,
) -> DevSplit:
    dates = sorted(labels[cutoff_col].unique())
    if len(dates) < 2:
        raise DevSplitError("need at least two cutoff dates")
    split_idx = max(1, min(len(dates) - 1, int(round((1 - late_fraction) * len(dates)))))
    early_dates = set(dates[:split_idx])
    late_dates = set(dates[split_idx:])
    early = labels[labels[cutoff_col].isin(early_dates)].copy()
    dev = labels[labels[cutoff_col].isin(late_dates)].copy()
    dropped_overlap = 0
    dropped_purge = 0
    dev_serials = set(dev[serial_col])
    before = len(early)
    early = early[~early[serial_col].isin(dev_serials)].copy()
    dropped_overlap = before - len(early)
    if dev.empty or early.empty:
        raise DevSplitError("empty partition after device isolation")
    dev_min_cutoff = pd.to_datetime(dev[cutoff_col]).min()
    cutoffs = pd.to_datetime(early[cutoff_col])
    purge_mask = cutoffs + pd.Timedelta(days=horizon_days + purge_days) >= dev_min_cutoff
    before_purge = len(early)
    early = early.loc[~purge_mask].copy()
    dropped_purge = before_purge - len(early)
    pos_train = int((early[label_col] == 1).sum())
    pos_dev = int((dev[label_col] == 1).sum())
    if pos_train < min_pos_train or pos_dev < min_pos_dev:
        raise DevSplitError("insufficient positives in train or dev")
    report = {
        "early_cutoff_dates": len(early_dates),
        "late_cutoff_dates": len(late_dates),
        "train_rows": len(early),
        "dev_rows": len(dev),
        "train_pos": pos_train,
        "dev_pos": pos_dev,
        "dropped_for_device_overlap": dropped_overlap,
        "dropped_for_purge": dropped_purge,
        "dev_earliest_cutoff": str(dev_min_cutoff.date()),
    }
    return DevSplit(train_labels=early, dev_labels=dev, report=report)
