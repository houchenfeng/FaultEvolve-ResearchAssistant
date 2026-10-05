"""Turn a normalised event stream into labeled prediction samples.

The sampler never invents an anchor from a failure record: prediction times come from the
events themselves or from a fixed grid, history is always ``(t - lookback, t]``, and a sample is
kept only when its outcome is knowable by ``t``.  Every removal is counted by reason so a run can
be audited without storing raw rows.

Interface note (requirement 16.4): ``build_labeled_samples`` takes the boundaries as keyword
arguments and fills the caller's ``report`` mapping instead of returning a second object, so the
public return type stays a single DataFrame.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Literal, MutableMapping

import numpy as np
import pandas as pd

from faultevolve.data.event_schema import CanonicalEventSchema

SAMPLER_VERSION = "evs-v1"
ANCHOR_STRATEGIES = ("event", "grid", "hybrid")
LabelDecision = Literal["positive", "negative", "insufficient_lead", "post_failure", "unknown"]
CensorDecision = Literal["keep", "censored"]

#: Reasons a candidate sample or event can disappear.  A report always carries every key (zero
#: when unused) so two runs can be diffed without guessing which reasons a dataset produced.
DROP_REASONS = (
    "post_failure_event",
    "no_history_candidate",
    "empty_history",
    "post_failure",
    "insufficient_lead",
    "censored",
    "max_samples_dropped",
)

OUTPUT_COLUMNS = (
    "sample_id",
    "unit_id",
    "prediction_time",
    "label",
    "split_key",
    "history_start",
    "history_end",
    "label_window_start",
    "label_window_end",
)


class SamplingError(ValueError):
    """Raised for invalid windows, an ambiguous time basis, or missing columns."""


@dataclass(frozen=True)
class EventWindowConfig:
    lookback: pd.Timedelta
    lead: pd.Timedelta
    horizon: pd.Timedelta
    anchor_frequency: pd.Timedelta
    anchor_strategy: Literal["event", "grid", "hybrid"]
    max_samples_per_unit: int | None = None
    seed: int = 0

    def __post_init__(self) -> None:
        for name in ("lookback", "lead", "horizon", "anchor_frequency"):
            value = getattr(self, name)
            if not isinstance(value, pd.Timedelta):
                raise SamplingError(f"{name} must be a Timedelta, got {type(value).__name__}")
            if value <= pd.Timedelta(0):
                raise SamplingError(f"{name} must be positive, got {value}")
        if self.anchor_strategy not in ANCHOR_STRATEGIES:
            raise SamplingError(
                f"anchor_strategy must be one of {ANCHOR_STRATEGIES}, got {self.anchor_strategy!r}"
            )
        if self.max_samples_per_unit is not None and int(self.max_samples_per_unit) <= 0:
            raise SamplingError(
                f"max_samples_per_unit must be positive or None, got {self.max_samples_per_unit}"
            )


def _ns(value: pd.Timedelta) -> int:
    return int(value.to_timedelta64().astype("timedelta64[ns]").astype("int64"))


def _require_utc_instant(value: pd.Timestamp, name: str) -> pd.Timestamp:
    if not isinstance(value, pd.Timestamp):
        raise SamplingError(f"{name} must be a Timestamp, got {type(value).__name__}")
    if value.tz is None:
        raise SamplingError(f"{name} is timezone-naive; declare its timezone before sampling")
    return value.tz_convert("UTC")


def _utc_ns(values: pd.Series | pd.DatetimeIndex, name: str) -> np.ndarray:
    """int64 nanosecond stamps on the UTC axis, refusing to guess a numeric epoch."""
    index = values if isinstance(values, pd.DatetimeIndex) else pd.DatetimeIndex(values)
    if len(index) == 0:
        return np.array([], dtype="int64")
    if getattr(index.dtype, "tz", None) is None:
        raise SamplingError(
            f"{name} is timezone-naive; declare its timezone before sampling (numeric epoch "
            "columns cannot carry one either)"
        )
    return index.tz_convert("UTC").as_unit("ns").asi8.astype("int64")


def _utc_series(values: pd.Series, name: str) -> pd.Series:
    if pd.api.types.is_numeric_dtype(values):
        raise SamplingError(
            f"{name} holds numeric epoch values; neither the unit (seconds or milliseconds) nor "
            "the timezone can be inferred, so the adapter must declare both"
        )
    index = pd.DatetimeIndex(values)
    if len(index) == 0:
        return pd.Series(pd.DatetimeIndex([], tz="UTC"), index=values.index)
    if getattr(index.dtype, "tz", None) is None:
        raise SamplingError(f"{name} is timezone-naive; declare its timezone before sampling")
    return index.tz_convert("UTC").to_series(index=values.index)


def _ceil_to(value: int, step: int) -> int:
    return ((value + step - 1) // step) * step


def _anchors_from(stamps: np.ndarray, config: EventWindowConfig) -> np.ndarray:
    step = _ns(config.anchor_frequency)
    parts = []
    if config.anchor_strategy in ("event", "hybrid"):
        parts.append(np.array([_ceil_to(int(s), step) for s in stamps], dtype="int64"))
    if config.anchor_strategy in ("grid", "hybrid"):
        start = (int(stamps.min()) // step) * step
        stop = _ceil_to(int(stamps.max()), step)
        count = int((stop - start) // step) + 1
        parts.append(start + np.arange(count, dtype="int64") * step)
    return np.unique(np.concatenate(parts))


def _index_from_ns(stamps: np.ndarray | pd.Series) -> pd.DatetimeIndex:
    return pd.DatetimeIndex(
        pd.to_datetime(pd.Series(np.asarray(stamps, dtype="int64")), unit="ns", utc=True)
    )


def make_prediction_times(
    events: pd.DataFrame,
    config: EventWindowConfig,
    *,
    time_col: str = "log_time",
) -> pd.DatetimeIndex:
    """Candidate prediction instants from events or the grid, never from outcomes.

    The ``event`` strategy ceils each event time onto the sampling frequency and then
    de-duplicates, so an event at 10:07 first becomes usable at 10:15.  Flooring would let the
    10:00 sample read an event that had not happened yet.
    """
    if time_col not in events.columns:
        raise SamplingError(f"events are missing the time column {time_col!r}")
    stamps = _utc_ns(events[time_col], time_col)
    if stamps.size == 0:
        return pd.DatetimeIndex([], tz="UTC")
    return pd.DatetimeIndex(_index_from_ns(_anchors_from(stamps, config)), tz="UTC")


def select_history(
    events: pd.DataFrame,
    prediction_time: pd.Timestamp,
    *,
    lookback: pd.Timedelta,
    time_col: str = "log_time",
) -> pd.DataFrame:
    """Rows inside ``(prediction_time - lookback, prediction_time]``."""
    if time_col not in events.columns:
        raise SamplingError(f"events are missing the time column {time_col!r}")
    anchor = _require_utc_instant(prediction_time, "prediction_time")
    if not isinstance(lookback, pd.Timedelta) or lookback <= pd.Timedelta(0):
        raise SamplingError(f"lookback must be a positive Timedelta, got {lookback!r}")
    if len(events) == 0:
        return events.copy()
    stamps = _utc_ns(events[time_col], time_col)
    right = anchor.as_unit("ns").value
    left = (anchor - lookback).as_unit("ns").value
    return events.loc[(stamps > left) & (stamps <= right)]


def label_at_time(
    prediction_time: pd.Timestamp,
    failure_time: pd.Timestamp | None,
    *,
    lead: pd.Timedelta,
    horizon: pd.Timedelta,
) -> LabelDecision:
    """Five-way decision on the exact ``[t + lead, t + lead + horizon]`` boundary."""
    start = _require_utc_instant(prediction_time, "prediction_time")
    if failure_time is None:
        return "unknown"
    failure = _require_utc_instant(failure_time, "failure_time")
    if failure <= start:
        return "post_failure"
    window_start = start + lead
    if failure < window_start:
        return "insufficient_lead"
    if failure <= window_start + horizon:
        return "positive"
    return "negative"


def censor_at_time(
    prediction_time: pd.Timestamp,
    *,
    lead: pd.Timedelta,
    horizon: pd.Timedelta,
    outcome_observed_until: pd.Timestamp,
    is_confirmed_positive: bool = False,
) -> CensorDecision:
    """A negative is only honest once follow-up reached the end of the label window."""
    start = _require_utc_instant(prediction_time, "prediction_time")
    until = _require_utc_instant(outcome_observed_until, "outcome_observed_until")
    if is_confirmed_positive:
        return "keep"
    return "keep" if start + lead + horizon <= until else "censored"


def make_sample_id(
    unit_id: str,
    prediction_time: pd.Timestamp,
    *,
    version: str = SAMPLER_VERSION,
) -> str:
    """Stable sha256 over version, unit and the UTC instant in nanoseconds."""
    if not str(unit_id):
        raise SamplingError("unit_id must be a non-empty string")
    stamp = _require_utc_instant(prediction_time, "prediction_time").as_unit("ns").value
    payload = f"{version}\x1f{unit_id}\x1f{stamp}".encode("utf-8")
    return f"{version}-{hashlib.sha256(payload).hexdigest()[:32]}"


def _first_failures(
    failures: pd.DataFrame, failure_unit_col: str, failure_time_col: str
) -> dict[str, int]:
    for column in (failure_unit_col, failure_time_col):
        if column not in failures.columns:
            raise SamplingError(f"failures are missing the column {column!r}")
    if len(failures) == 0:
        return {}
    times = _utc_series(failures[failure_time_col], failure_time_col)
    grouped = (
        pd.DataFrame({"unit": failures[failure_unit_col].astype(str), "ns": _utc_ns(times, failure_time_col)})
        .groupby("unit")["ns"]
        .min()
    )
    return {str(unit): int(stamp) for unit, stamp in grouped.items()}


def _sorted_events(events: pd.DataFrame, schema: CanonicalEventSchema) -> pd.DataFrame:
    for column in (schema.unit_col, schema.time_col):
        if column not in events.columns:
            raise SamplingError(f"events are missing the column {column!r}")
    usable = events.loc[events[schema.unit_col].notna() & (events[schema.unit_col].astype(str) != "")]
    return usable.sort_values(schema.time_col, kind="stable")


def _spaced_indices(total: int, cap: int) -> np.ndarray:
    return np.unique(np.rint(np.linspace(0, total - 1, cap)).astype("int64"))


def _decide(
    anchors: np.ndarray,
    usable: np.ndarray,
    cutoff: int | None,
    *,
    lookback_ns: int,
    lead_ns: int,
    horizon_ns: int,
    until_ns: int,
    counts: dict[str, int],
) -> tuple[np.ndarray, np.ndarray]:
    """Return the kept anchors and which of them are positive, crediting every removal."""
    right = np.searchsorted(usable, anchors, side="right")
    left = np.searchsorted(usable, anchors - lookback_ns, side="right")
    usable_history = right > left
    counts["empty_history"] += int((~usable_history).sum())
    keep = usable_history.copy()

    positive = np.zeros(anchors.size, dtype=bool)
    if cutoff is not None:
        after = anchors >= cutoff
        too_soon = (~after) & (cutoff < anchors + lead_ns)
        positive = (~after) & (~too_soon) & (cutoff <= anchors + lead_ns + horizon_ns)
        counts["post_failure"] += int((after & usable_history).sum())
        counts["insufficient_lead"] += int((too_soon & usable_history).sum())
        keep &= ~(after | too_soon)

    window_end = anchors + lead_ns + horizon_ns
    censored = keep & ~positive & (window_end > until_ns)
    counts["censored"] += int(censored.sum())
    keep &= ~censored
    return anchors[keep], positive[keep]


def build_labeled_samples(
    events: pd.DataFrame,
    failures: pd.DataFrame,
    schema: CanonicalEventSchema,
    config: EventWindowConfig,
    *,
    failure_unit_col: str,
    failure_time_col: str,
    outcome_observed_until: pd.Timestamp,
    report: MutableMapping[str, int] | None = None,
) -> pd.DataFrame:
    """Labeled samples for every unit, with removal counts written into ``report``.

    ``split_key`` stays empty here; the temporal split step owns it.  Real unit identifiers may
    live in the returned frame because later steps must join features on them, but the frame is
    not a report: it must never be logged, committed, or pasted into a model prompt.
    """
    until_ns = _require_utc_instant(outcome_observed_until, "outcome_observed_until").as_unit("ns").value
    lead_ns, horizon_ns, lookback_ns = _ns(config.lead), _ns(config.horizon), _ns(config.lookback)

    cutoffs = _first_failures(failures, failure_unit_col, failure_time_col)
    frame = _sorted_events(events, schema)
    stamps = _utc_ns(frame[schema.time_col], schema.time_col)
    units = frame[schema.unit_col].astype(str).to_numpy()

    kept_units: list[str] = []
    kept_times: list[int] = []
    kept_labels: list[int] = []
    counts: dict[str, int] = {reason: 0 for reason in DROP_REASONS}

    for unit in pd.unique(units):
        positions = np.flatnonzero(units == unit)
        ordered = np.sort(stamps[positions])
        cutoff = cutoffs.get(unit)
        if cutoff is None:
            usable = ordered
        else:
            usable = ordered[ordered < cutoff]
            counts["post_failure_event"] += int(ordered.size - usable.size)
        if usable.size == 0:
            counts["no_history_candidate"] += 1
            continue
        anchors = _anchors_from(usable, config)
        if config.max_samples_per_unit is not None and anchors.size > config.max_samples_per_unit:
            anchors = anchors[_spaced_indices(int(anchors.size), int(config.max_samples_per_unit))]
        survivors, positives = _decide(
            anchors,
            usable,
            cutoff,
            lookback_ns=lookback_ns,
            lead_ns=lead_ns,
            horizon_ns=horizon_ns,
            until_ns=until_ns,
            counts=counts,
        )
        kept_units.extend([unit] * int(survivors.size))
        kept_times.extend(int(value) for value in survivors)
        kept_labels.extend(int(value) for value in positives)

    if report is not None:
        report.update(counts)
    if not kept_times:
        return _empty_output()

    prediction = _index_from_ns(np.asarray(kept_times, dtype="int64"))
    return pd.DataFrame(
        {
            "sample_id": [
                make_sample_id(unit, instant) for unit, instant in zip(kept_units, prediction, strict=True)
            ],
            "unit_id": np.asarray(kept_units, dtype=object),
            "prediction_time": prediction,
            "label": np.asarray(kept_labels, dtype="int8"),
            "split_key": pd.Series([pd.NA] * prediction.size, dtype="object"),
            "history_start": prediction - pd.Timedelta(nanoseconds=lookback_ns),
            "history_end": prediction,
            "label_window_start": prediction + config.lead,
            "label_window_end": prediction + config.lead + config.horizon,
        }
    )


def _empty_output() -> pd.DataFrame:
    empty = pd.DatetimeIndex([], tz="UTC")
    return pd.DataFrame(
        {
            "sample_id": pd.Series([], dtype=object),
            "unit_id": pd.Series([], dtype=object),
            "prediction_time": empty,
            "label": pd.Series([], dtype="int8"),
            "split_key": pd.Series([], dtype=object),
            "history_start": empty,
            "history_end": empty,
            "label_window_start": empty,
            "label_window_end": empty,
        }
    )
