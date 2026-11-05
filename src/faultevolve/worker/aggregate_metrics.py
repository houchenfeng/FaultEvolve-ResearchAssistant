"""Supplement prediction scoring with aggregate counts without changing its score."""

from __future__ import annotations

from functools import wraps
from typing import Any


def add_aggregate_metrics(module: Any) -> None:
    original = getattr(module, "score_predictions", None)
    if original is None or not hasattr(module, "weighted_confusion") or getattr(original, "_fe_aggregates", False):
        return

    @wraps(original)
    def score_predictions(pred, labels):
        quality, metric = original(pred, labels)
        frame = labels.merge(pred, on="serial_number", how="left")
        y = frame["label"].to_numpy(dtype=int)
        alarm = frame["alarm"].to_numpy(dtype=int)
        weights = frame["weight"].to_numpy(dtype=float)
        tp, fp, fn, tn = module.weighted_confusion(y, alarm, weights)
        total = tp + fp + fn + tn
        return quality, {**metric,
            "accuracy": float((tp + tn) / total) if total else 0.,
            "unweighted_accuracy": float((y == alarm).mean()) if len(y) else 0.,
            "true_positives": float(tp), "false_positives": float(fp),
            "false_negatives": float(fn), "true_negatives": float(tn),
            "sample_count": int(len(y)), "weighted_population": float(total),
        }

    score_predictions._fe_aggregates = True
    module.score_predictions = score_predictions
