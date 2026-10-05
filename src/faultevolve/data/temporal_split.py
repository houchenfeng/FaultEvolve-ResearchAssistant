"""Split labeled samples by time so that evaluation extrapolates forward, then audit the result.

Splits are half-open intervals ``[start, end)`` over ``prediction_time`` and the gap between two
neighbouring splits is expressed as exactly one rule: a sample whose ``label_window_end`` reaches
the start of the following split is marked ``embargo`` instead of being shifted sideways or silently
kept.  The final scored split has no successor, so the gap rule does not apply to it; its outcome
coverage is checked when the boundaries are suggested.  The audit recomputes every assignment from
the timestamps and reports counts only, never raw unit identifiers, so a report can be published
next to a run without leaking which device was measured.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd

#: Splits a metric is reported on, in temporal order.
SCORED_SPLITS = ("train", "dev", "val")
#: Marks a row carries instead of a scored split.
NON_SCORED_KEYS = ("embargo", "outside", "cold_audit")
#: Right edges of the scored splits, in percent of the observable time span.
SPLIT_PERCENTAGES = (70, 85, 100)

REQUIRED_COLUMNS = (
    "sample_id",
    "unit_id",
    "prediction_time",
    "history_end",
    "label_window_start",
    "label_window_end",
    "split_key",
)


class SplitError(ValueError):
    """Raised for unusable boundaries, a naive time basis, or missing columns."""


@dataclass(frozen=True)
class SplitBoundaries:
    """Right edge of each scored split plus the one gap rule that separates them."""

    train_end: pd.Timestamp
    dev_end: pd.Timestamp
    val_end: pd.Timestamp
    embargo: pd.Timedelta
    start: pd.Timestamp | None = None

    def __post_init__(self) -> None:
        named = [
            ("train_end", self.train_end),
            ("dev_end", self.dev_end),
            ("val_end", self.val_end),
        ]
        if self.start is not None:
            named.insert(0, ("start", self.start))
        stamps = {}
        for name, value in named:
            stamps[name] = _instant(value, name)
        if not isinstance(self.embargo, pd.Timedelta) or self.embargo <= pd.Timedelta(0):
            raise SplitError(f"embargo must be a positive Timedelta, got {self.embargo!r}")
        for (earlier_name, earlier), (later_name, later) in zip(
            list(stamps.items())[:-1], list(stamps.items())[1:]
        ):
            if later <= earlier:
                raise SplitError(f"{later_name} must come after {earlier_name}")

    @property
    def right_edges(self) -> tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp]:
        return (self.train_end, self.dev_end, self.val_end)


def _ns(value: pd.Timedelta) -> int:
    return int(value.to_timedelta64().astype("timedelta64[ns]").astype("int64"))


def _instant(value: object, name: str) -> pd.Timestamp:
    if not isinstance(value, pd.Timestamp):
        raise SplitError(f"{name} must be a Timestamp, got {type(value).__name__}")
    if value.tz is None:
        raise SplitError(f"{name} is timezone-naive; declare its timezone before splitting")
    return value.tz_convert("UTC")


def _utc_ns(values: pd.Series | pd.DatetimeIndex, name: str) -> np.ndarray:
    index = values if isinstance(values, pd.DatetimeIndex) else pd.DatetimeIndex(values)
    if len(index) == 0:
        return np.array([], dtype="int64")
    if getattr(index.dtype, "tz", None) is None:
        raise SplitError(f"{name} is timezone-naive; declare its timezone before splitting")
    return index.tz_convert("UTC").as_unit("ns").asi8.astype("int64")


def _floor_to(value: int, step: int) -> int:
    return (value // step) * step


def _stamp(ns: int) -> pd.Timestamp:
    return pd.Timestamp(int(ns), unit="ns", tz="UTC")


def _require_frame(samples: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(samples, pd.DataFrame):
        raise SplitError(f"samples must be a DataFrame, got {type(samples).__name__}")
    missing = [name for name in REQUIRED_COLUMNS if name not in samples.columns]
    if missing:
        raise SplitError(f"samples is missing required columns: {', '.join(missing)}")
    return samples.copy()


def _dedupe_cold(cold_units: Iterable[str] | None) -> frozenset[str]:
    if cold_units is None:
        return frozenset()
    return frozenset(str(unit) for unit in cold_units)


def _is_cold(samples: pd.DataFrame, cold_units: frozenset[str]) -> np.ndarray:
    if not cold_units:
        return np.zeros(len(samples), dtype=bool)
    return np.array([str(unit) in cold_units for unit in samples["unit_id"]], dtype=bool)


def suggest_split_boundaries(
    span_start: pd.Timestamp,
    span_end: pd.Timestamp,
    *,
    lead: pd.Timedelta,
    horizon: pd.Timedelta,
    anchor_frequency: pd.Timedelta,
    outcome_observed_until: pd.Timestamp | None = None,
) -> SplitBoundaries:
    """Cut the observable time span into 70/15/15 splits whose edges land on the anchor grid.

    The cut is taken over elapsed time, never over row counts, so a busy first month cannot claim a
    larger share of the evaluation than a quiet one.
    """
    start = _instant(span_start, "span_start")
    stop = _instant(span_end, "span_end")
    for name, value in (
        ("lead", lead),
        ("horizon", horizon),
        ("anchor_frequency", anchor_frequency),
    ):
        if not isinstance(value, pd.Timedelta) or value <= pd.Timedelta(0):
            raise SplitError(f"{name} must be a positive Timedelta, got {value!r}")
    embargo = lead + horizon
    start_ns = start.as_unit("ns").value
    total_ns = stop.as_unit("ns").value - start_ns
    if total_ns <= 0:
        raise SplitError(
            f"time span must be positive, got {start.isoformat()} .. {stop.isoformat()}"
        )
    step = _ns(anchor_frequency)
    train_end, dev_end, val_end = [
        _stamp(_floor_to(start_ns + total_ns * percent // 100, step))
        for percent in SPLIT_PERCENTAGES
    ]

    train_room_ns = train_end.as_unit("ns").value - start_ns
    if train_room_ns <= _ns(embargo):
        raise SplitError(
            f"train would have {train_room_ns / 86_400e9:.2f} days of room against a {embargo} "
            "lead+horizon gap, so no train anchor could be labeled without reaching the dev split; "
            "widen the time span or shorten lead/horizon"
        )
    if outcome_observed_until is not None:
        until = _instant(outcome_observed_until, "outcome_observed_until")
        reach_ns = val_end.as_unit("ns").value + _ns(embargo)
        if reach_ns > until.as_unit("ns").value:
            raise SplitError(
                f"outcome coverage ends at {until.isoformat()} but the last split needs "
                f"{_stamp(reach_ns).isoformat()} to close its label window; the val split would be "
                "scored against outcomes nobody observed"
            )
    return SplitBoundaries(
        train_end=train_end, dev_end=dev_end, val_end=val_end, embargo=embargo, start=start
    )


def _edges(boundaries: SplitBoundaries) -> tuple[np.ndarray, np.ndarray]:
    cuts = np.array([stamp.as_unit("ns").value for stamp in boundaries.right_edges], dtype="int64")
    # The last scored split has no successor, so the gap rule has no edge to compare against.
    return cuts, np.array([cuts[0], cuts[1], -1, -1], dtype="int64")


def _classify(
    samples: pd.DataFrame, boundaries: SplitBoundaries, cold_units: frozenset[str]
) -> np.ndarray:
    prediction_ns = _utc_ns(samples["prediction_time"], "prediction_time")
    window_end_ns = _utc_ns(samples["label_window_end"], "label_window_end")
    cuts, next_starts = _edges(boundaries)
    positions = np.searchsorted(cuts, prediction_ns, side="right")
    keys = np.array([*SCORED_SPLITS, "outside"], dtype=object)[positions]
    following = next_starts[positions]
    keys[(following >= 0) & (window_end_ns >= following)] = "embargo"
    if boundaries.start is not None:
        keys[prediction_ns < boundaries.start.as_unit("ns").value] = "outside"
    keys[(keys == "train") & _is_cold(samples, cold_units)] = "cold_audit"
    return keys


def assign_temporal_splits(
    samples: pd.DataFrame,
    boundaries: SplitBoundaries,
    *,
    cold_units: Iterable[str] | None = None,
) -> pd.DataFrame:
    """Fill ``split_key`` from the timestamps; every row ends up with exactly one mark."""
    frame = _require_frame(samples)
    frame["split_key"] = _classify(frame, boundaries, _dedupe_cold(cold_units))
    return frame


def select_cold_units(units: Iterable[str], *, fraction: float, seed: int) -> list[str]:
    """Pick units whose train-window samples are withheld, by a hash of (seed, unit).

    Sorting by the digest makes the choice blind to input order and independent of Python's own hash
    randomization, so two runs of the same task evaluate the same unseen devices.
    """
    if isinstance(fraction, bool) or not isinstance(fraction, (int, float)):
        raise SplitError(f"fraction must be a number in [0, 1], got {fraction!r}")
    if not 0.0 <= float(fraction) <= 1.0:
        raise SplitError(f"fraction must be in [0, 1], got {fraction}")
    names = sorted({str(unit) for unit in units})
    wanted = int(round(len(names) * float(fraction)))
    if wanted <= 0:
        return []
    ranked = sorted(
        names,
        key=lambda unit: (
            hashlib.sha256(f"{int(seed)}\x1f{unit}".encode("utf-8")).hexdigest(),
            unit,
        ),
    )
    return ranked[:wanted]


def audit_temporal_splits(
    samples: pd.DataFrame,
    boundaries: SplitBoundaries,
    *,
    cold_units: Iterable[str] | None = None,
) -> dict:
    """Verify a split assignment against the timestamps and return counts, never raw rows."""
    frame = _require_frame(samples)
    cold = _dedupe_cold(cold_units)
    expected = _classify(frame, boundaries, cold)
    keys = frame["split_key"].astype("object").fillna("").to_numpy(dtype=str)

    prediction_ns = _utc_ns(frame["prediction_time"], "prediction_time")
    window_start_ns = _utc_ns(frame["label_window_start"], "label_window_start")
    window_end_ns = _utc_ns(frame["label_window_end"], "label_window_end")
    cuts, next_starts = _edges(boundaries)
    following = next_starts[np.searchsorted(cuts, prediction_ns, side="right")]

    violations: dict[str, int] = {}

    def count(name: str, mask: np.ndarray) -> None:
        total = int(np.count_nonzero(mask))
        if total:
            violations[name] = total

    count(
        "history_after_prediction_time",
        _utc_ns(frame["history_end"], "history_end") > prediction_ns,
    )
    count(
        "label_window_not_ahead",
        (window_start_ns <= prediction_ns) | (window_end_ns <= window_start_ns),
    )
    # A row already marked embargo or outside is removed; only a kept row can leak.
    count(
        "label_window_crosses_split",
        np.isin(keys, SCORED_SPLITS) & (following >= 0) & (window_end_ns >= following),
    )
    count("duplicate_sample_id", frame["sample_id"].duplicated().to_numpy(dtype=bool))
    count("split_key_mismatch", keys != expected)
    count("cold_unit_in_train", _is_cold(frame, cold) & (keys == "train"))

    splits = {str(key): int(total) for key, total in frame["split_key"].value_counts().items()}
    count("empty_split", np.array([splits.get(name, 0) == 0 for name in SCORED_SPLITS], dtype=bool))

    return {
        "passed": not violations,
        "violations": violations,
        "splits": splits,
        "embargo_removed": int((keys == "embargo").sum()),
        "rows": int(len(frame)),
        "cold_units": len(cold),
        "boundaries": {
            name: None if stamp is None else stamp.tz_convert("UTC").isoformat()
            for name, stamp in (
                ("start", boundaries.start),
                ("train_end", boundaries.train_end),
                ("dev_end", boundaries.dev_end),
                ("val_end", boundaries.val_end),
            )
        },
        "embargo": str(boundaries.embargo),
    }
