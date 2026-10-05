"""Canonical event-stream schema normalisation shared by every event-based task.

This module is deliberately task agnostic: it knows about a unit column, a time column and
per-field dtypes, and nothing about any particular hardware vocabulary. Domain mapping lives
in the dataset adapters.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import pandas as pd

DuplicatePolicy = Literal["keep", "drop_exact", "error"]


class EventSchemaError(ValueError):
    """Raised when an event frame cannot be normalised safely.

    Messages carry column names and row counts only, never field values, because a unit
    identifier may be a real production serial number.
    """


@dataclass(frozen=True)
class CanonicalEventSchema:
    unit_col: str
    time_col: str
    event_type_col: str | None = None
    static_cols: tuple[str, ...] = ()
    categorical_cols: tuple[str, ...] = ()
    numeric_cols: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("unit_col", "time_col"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise EventSchemaError(f"{name} must be a non-empty column name")
        for name in ("static_cols", "categorical_cols", "numeric_cols"):
            columns = getattr(self, name)
            if not isinstance(columns, tuple) or not all(isinstance(c, str) for c in columns):
                raise EventSchemaError(f"{name} must be a tuple of column names")
        if self.time_col in self.numeric_cols:
            raise EventSchemaError("time_col must not be declared numeric")


def _require_columns(frame: pd.DataFrame, schema: CanonicalEventSchema) -> None:
    for column in (schema.unit_col, schema.time_col):
        if column not in frame.columns:
            raise EventSchemaError(f"required column missing from the frame: {column}")
    known = set(frame.columns)
    for column in (*schema.static_cols, *schema.categorical_cols, *schema.numeric_cols):
        if column not in known:
            raise EventSchemaError(f"declared column missing from the frame: {column}")


def _validate_units(frame: pd.DataFrame, schema: CanonicalEventSchema) -> pd.Series:
    units = frame[schema.unit_col].map(lambda v: "" if pd.isna(v) else str(v))
    illegal = units.map(lambda v: not v.strip())
    if illegal.any():
        raise EventSchemaError(
            f"{int(illegal.sum())} row(s) have an empty or null {schema.unit_col}"
        )
    return units


def _looks_like_local_epoch(values: pd.Series) -> bool:
    return pd.api.types.is_integer_dtype(values) or pd.api.types.is_float_dtype(values)


def _to_utc(series: pd.Series, timezone: str, column: str) -> pd.Series:
    if _looks_like_local_epoch(series):
        raise EventSchemaError(
            f"{column} holds raw numbers; the epoch unit (seconds vs milliseconds) and the "
            "timezone cannot be inferred, so refusing to guess"
        )

    if isinstance(series.dtype, pd.DatetimeTZDtype):
        utc = series.dt.tz_convert("UTC")
    elif pd.api.types.is_datetime64_any_dtype(series):
        if getattr(series.dtype, "tz", None) is not None:
            utc = series.dt.tz_convert("UTC")
        else:
            utc = _localise(series, timezone, column)
    else:
        try:
            parsed = pd.to_datetime(series, errors="coerce")
        except (ValueError, TypeError) as exc:
            raise EventSchemaError(f"{column} cannot be parsed as timestamps: {type(exc).__name__}") from exc
        if isinstance(parsed.dtype, pd.DatetimeTZDtype):
            utc = parsed.dt.tz_convert("UTC")
        else:
            utc = _localise(parsed, timezone, column)

    unparsed = int(utc.isna().sum())
    if unparsed:
        raise EventSchemaError(
            f"{unparsed} row(s) of {column} could not be parsed, or mix timezone offsets "
            "with naive values"
        )
    return utc.astype("datetime64[ns, UTC]")


def _localise(series: pd.Series, timezone: str, column: str) -> pd.Series:
    try:
        return series.dt.tz_localize(timezone, ambiguous="raise", nonexistent="raise").dt.tz_convert(
            "UTC"
        )
    except ValueError as exc:
        message = str(exc).lower()
        if "cannot infer dst" in message or "ambiguous" in message:
            reason = "are ambiguous local times (daylight saving fold)"
        elif "nonexistent" in message:
            reason = "are nonexistent local times (daylight saving gap)"
        else:
            raise EventSchemaError(f"{column} could not be localised to {timezone}") from exc
        raise EventSchemaError(
            f"one or more {column} values {reason} in {timezone}; resolving them must be an "
            "explicit decision, not a default"
        ) from exc


def _apply_field_dtypes(frame: pd.DataFrame, schema: CanonicalEventSchema) -> pd.DataFrame:
    for column in schema.numeric_cols:
        try:
            frame[column] = pd.to_numeric(frame[column], errors="raise")
        except (ValueError, TypeError) as exc:
            raise EventSchemaError(
                f"{column} is declared numeric but {int(frame[column].notna().sum())} row(s) "
                "cannot be converted"
            ) from exc
    for column in schema.categorical_cols:
        frame[column] = frame[column].map(lambda v: v if pd.isna(v) else str(v))
    return frame


def normalize_events(
    frame: pd.DataFrame,
    schema: CanonicalEventSchema,
    *,
    timezone: str,
    duplicate_policy: DuplicatePolicy = "drop_exact",
) -> pd.DataFrame:
    """Return a sorted, UTC-timestamped copy of ``frame`` without inventing values.

    ``timezone`` is mandatory for naive local times: falling back to the machine's zone would
    silently shift every prediction window.
    """
    if duplicate_policy not in ("keep", "drop_exact", "error"):
        raise EventSchemaError(
            f"duplicate_policy must be keep, drop_exact or error, got {duplicate_policy!r}"
        )

    _require_columns(frame, schema)
    work = frame.copy()
    work[schema.unit_col] = _validate_units(work, schema)
    work[schema.time_col] = _to_utc(work[schema.time_col], timezone, schema.time_col)
    work = _apply_field_dtypes(work, schema)

    exact = work.duplicated(keep=False)
    if int(exact.sum()):
        if duplicate_policy == "error":
            raise EventSchemaError(f"{int(exact.sum())} rows are exact duplicates")
        if duplicate_policy == "drop_exact":
            work = work[~work.duplicated(keep="first")]

    return work.sort_values(
        [schema.unit_col, schema.time_col], kind="stable", ignore_index=True
    )


def build_event_profile(frame: pd.DataFrame, schema: CanonicalEventSchema) -> dict:
    """Summarise shape and coverage only: dtypes, missing rates, cardinality, time range.

    Category values are counted, never listed, because a category can carry a real device
    identity.
    """
    _require_columns(frame, schema)
    time_column = frame[schema.time_col]
    columns: dict[str, dict] = {}
    for column in frame.columns:
        series = frame[column]
        is_time = column == schema.time_col
        columns[column] = {
            "dtype": str(series.dtype),
            "missing_rate": round(float(series.isna().mean()), 6),
            "cardinality": None if is_time else int(series.nunique(dropna=True)),
        }
    return {
        "row_count": int(len(frame)),
        "unit_count": int(frame[schema.unit_col].nunique()),
        "time_range": {
            "min": pd.Timestamp(time_column.min()).isoformat(),
            "max": pd.Timestamp(time_column.max()).isoformat(),
        },
        "columns": columns,
    }
