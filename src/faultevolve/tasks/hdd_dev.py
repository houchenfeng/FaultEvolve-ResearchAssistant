"""HDD dev proxy scoring (train-only public data)."""

from __future__ import annotations

import importlib.util
import tempfile
from pathlib import Path
from typing import Any

import pandas as pd

from faultevolve.optimization.dev_split import DevSplit, make_time_blocked_split


def score_dev(
    pred: pd.DataFrame,
    dev_labels: pd.DataFrame,
    evaluator_path: Path,
) -> dict[str, Any]:
    spec = importlib.util.spec_from_file_location("hdd_evaluator", evaluator_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load evaluator")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    merged = pred.merge(dev_labels, on="serial_number", how="inner")
    y = merged["label"].to_numpy()
    w = merged["weight"].to_numpy()
    scores = merged["score"].to_numpy()
    auprc = mod.weighted_auprc(y, scores, w)
    recall = mod.recall_at_far(y, scores, w, getattr(mod, "FAR_BUDGET", 0.002))
    alarms = merged["alarm"].to_numpy()
    tp = (w * (y == 1) * (alarms == 1)).sum()
    fp = (w * (y == 0) * (alarms == 1)).sum()
    fn = (w * (y == 1) * (alarms == 0)).sum()
    f1 = 2 * tp / max(2 * tp + fp + fn, 1e-12)
    proxy = 0.4 * auprc + 0.3 * recall + 0.3 * f1
    serial_scores = dict(zip(merged["serial_number"].astype(str), scores.astype(float)))
    return {
        "fidelity": "dev",
        "dev_proxy": float(proxy),
        "auprc": float(auprc),
        "recall_at_far": float(recall),
        "f1_p10": float(f1),
        "serial_scores": serial_scores,
    }


def build_dev_task_dir(
    task_dir: Path,
    split: DevSplit,
    history_path: Path,
) -> Path:
    """Materialize pseudo task dir for dev evaluation (no dev labels on disk)."""
    out = Path(tempfile.mkdtemp(prefix="fe_hpo_dev_"))
    split.train_labels.to_csv(out / "train_labels.csv", index=False)
    dev_index = split.dev_labels[["serial_number", "model", "cutoff_date"]]
    dev_index.to_csv(out / "val_index.csv", index=False)
    train_serials = set(split.train_labels["serial_number"])
    dev_serials = set(split.dev_labels["serial_number"])
    import gzip

    def _stream(serials: set[str], name: str) -> None:
        first = True
        with gzip.open(history_path, "rt", encoding="utf-8") as src:
            for chunk in pd.read_csv(src, chunksize=100_000):
                filt = chunk[chunk["serial_number"].isin(serials)]
                if filt.empty:
                    continue
                with gzip.open(out / name, "at" if not first else "wt", encoding="utf-8", newline="") as dst:
                    filt.to_csv(dst, index=False, header=first)
                first = False

    _stream(train_serials, "train_history.csv.gz")
    _stream(dev_serials, "val_history.csv.gz")
    return out


def make_hdd_dev_split(task_dir: Path, *, late_fraction: float, purge_days: int) -> DevSplit:
    from faultevolve.optimization.dev_split import assert_public_train_only

    labels_path = assert_public_train_only(task_dir / "data" / "public" / "train_labels.csv")
    labels = pd.read_csv(labels_path)
    return make_time_blocked_split(
        labels,
        serial_col="serial_number",
        cutoff_col="cutoff_date",
        label_col="label",
        horizon_days=7,
        late_fraction=late_fraction,
        purge_days=purge_days,
        min_pos_train=1,
        min_pos_dev=1,
    )
