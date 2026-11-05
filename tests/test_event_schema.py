"""V1-02: canonical event schema normalisation, duplicate handling and anonymised profile."""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
import pytest

from faultevolve.data.event_schema import (
    CanonicalEventSchema,
    EventSchemaError,
    build_event_profile,
    normalize_events,
)

SCHEMA = CanonicalEventSchema(
    unit_col="unit_id",
    time_col="ts",
    event_type_col="kind",
    static_cols=("fw",),
    categorical_cols=("kind", "fw"),
    numeric_cols=("severity",),
)

SECRET = "SECRET-UNIT-DO-NOT-LOG"


def _frame(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["unit_id", "ts", "kind", "fw", "severity"])


BASE_ROWS = [
    {"unit_id": "u-a", "ts": "2024-01-01 10:00:00", "kind": "ce", "fw": "1.2", "severity": 3},
    {"unit_id": "u-a", "ts": "2024-01-02 10:00:00", "kind": "ce", "fw": "1.2", "severity": 4},
    {"unit_id": SECRET, "ts": "2024-01-03 09:30:00", "kind": "ue", "fw": "2.0", "severity": 9},
]


def test_missing_unit_or_time_column_raises():
    with pytest.raises(EventSchemaError, match="unit_id"):
        normalize_events(pd.DataFrame({"ts": ["2024-01-01"]}), SCHEMA, timezone="UTC")
    with pytest.raises(EventSchemaError, match="ts"):
        normalize_events(pd.DataFrame({"unit_id": ["a"]}), SCHEMA, timezone="UTC")


def test_blank_or_null_unit_fails_without_echoing_identities():
    rows = list(BASE_ROWS) + [{"unit_id": "", "ts": "2024-01-04 00:00:00", "kind": "ce", "fw": "", "severity": 1}]
    with pytest.raises(EventSchemaError, match="unit") as exc:
        normalize_events(_frame(rows), SCHEMA, timezone="UTC")
    assert SECRET not in str(exc.value)


def test_naive_times_are_localised_to_the_requested_timezone_then_utc():
    # 2024-01-01 10:00 in Asia/Shanghai (UTC+8) is 02:00 UTC.
    out = normalize_events(_frame(BASE_ROWS), SCHEMA, timezone="Asia/Shanghai")
    assert str(out["ts"].dtype) == "datetime64[ns, UTC]"
    assert out.loc[out["unit_id"] == "u-a", "ts"].min() == pd.Timestamp("2024-01-01 02:00:00", tz="UTC")


def test_tz_aware_input_round_trips_to_utc():
    rows = [dict(r, ts=f"{r['ts']}+08:00") for r in BASE_ROWS]
    out = normalize_events(_frame(rows), SCHEMA, timezone="UTC")
    assert str(out["ts"].dtype) == "datetime64[ns, UTC]"
    assert out.loc[out["unit_id"] == "u-a", "ts"].min() == pd.Timestamp("2024-01-01 02:00:00", tz="UTC")


def test_mixing_offsets_with_naive_times_fails():
    rows = [dict(r) for r in BASE_ROWS]
    rows[0]["ts"] = "2024-01-01T10:00:00+08:00"
    with pytest.raises(EventSchemaError):
        normalize_events(_frame(rows), SCHEMA, timezone="UTC")


def test_timezone_is_required_and_not_defaulted_to_the_local_machine():
    with pytest.raises(TypeError):
        normalize_events(_frame(BASE_ROWS), SCHEMA)


def test_ambiguous_and_nonexistent_local_times_fail_by_default():
    ambiguous = _frame(
        [{"unit_id": "u-a", "ts": "2024-10-27 01:30:00", "kind": "ce", "fw": "1", "severity": 1}]
    )
    with pytest.raises(EventSchemaError, match="ambiguous"):
        normalize_events(ambiguous, SCHEMA, timezone="Europe/London")

    nonexistent = _frame(
        [{"unit_id": "u-a", "ts": "2024-03-31 01:30:00", "kind": "ce", "fw": "1", "severity": 1}]
    )
    with pytest.raises(EventSchemaError, match="nonexistent"):
        normalize_events(nonexistent, SCHEMA, timezone="Europe/London")


def test_integer_timestamps_are_rejected_as_ambiguous_epoch_unit():
    frame = _frame(BASE_ROWS)
    frame["ts"] = [1_704_103_200, 1_704_190_000, 1_704_273_000]  # seconds? milliseconds? unstated
    with pytest.raises(EventSchemaError, match="epoch"):
        normalize_events(frame, SCHEMA, timezone="UTC")


def test_unparseable_time_raises_with_a_count_not_a_value():
    rows = [dict(r) for r in BASE_ROWS]
    rows[2]["ts"] = "not-a-time"
    with pytest.raises(EventSchemaError, match="1 row") as exc:
        normalize_events(_frame(rows), SCHEMA, timezone="UTC")
    assert "not-a-time" not in str(exc.value)


def test_exact_duplicates_drop_but_same_time_different_address_survives():
    a = dict(BASE_ROWS[0])
    same_time_other_address = dict(BASE_ROWS[0])
    same_time_other_address["kind"] = "ue"
    frame = _frame([a, dict(a), same_time_other_address])
    out = normalize_events(frame, SCHEMA, timezone="UTC")
    assert len(out) == 2
    assert sorted(out["kind"]) == ["ce", "ue"]


def test_duplicate_policy_keep_and_error():
    a = dict(BASE_ROWS[0])
    frame = _frame([a, dict(a)])
    assert len(normalize_events(frame, SCHEMA, timezone="UTC", duplicate_policy="keep")) == 2
    with pytest.raises(EventSchemaError, match="duplicate"):
        normalize_events(frame, SCHEMA, timezone="UTC", duplicate_policy="error")
    with pytest.raises(EventSchemaError, match="duplicate_policy"):
        normalize_events(frame, SCHEMA, timezone="UTC", duplicate_policy="merge")


def test_rows_are_sorted_by_unit_then_time_stably():
    rows = [
        {"unit_id": "u-b", "ts": "2024-01-05 00:00:00", "kind": "ce", "fw": "1", "severity": 1},
        {"unit_id": "u-a", "ts": "2024-01-09 00:00:00", "kind": "ce", "fw": "1", "severity": 1},
        {"unit_id": "u-a", "ts": "2024-01-02 00:00:00", "kind": "ce", "fw": "1", "severity": 1},
        {"unit_id": "u-a", "ts": "2024-01-02 00:00:00", "kind": "ue", "fw": "1", "severity": 2},
    ]
    out = normalize_events(_frame(rows), SCHEMA, timezone="UTC")
    assert out["unit_id"].tolist() == ["u-a", "u-a", "u-a", "u-b"]
    assert out["kind"].tolist() == ["ce", "ue", "ce", "ce"]  # ties keep original order


def test_input_frame_is_not_mutated():
    frame = _frame(BASE_ROWS)
    before = frame.copy()
    normalize_events(frame, SCHEMA, timezone="UTC")
    pd.testing.assert_frame_equal(frame, before)


def test_missing_numerics_stay_missing_rather_than_being_filled():
    rows = [dict(r) for r in BASE_ROWS]
    rows[1]["severity"] = None
    out = normalize_events(_frame(rows), SCHEMA, timezone="UTC")
    assert int(out["severity"].isna().sum()) == 1
    assert int(out["severity"].notna().sum()) == 2


def test_profile_reports_shapes_not_identities():
    profile = build_event_profile(normalize_events(_frame(BASE_ROWS), SCHEMA, timezone="UTC"), SCHEMA)
    text = repr(profile)
    assert SECRET not in text
    assert profile["row_count"] == 3
    assert profile["unit_count"] == 2
    assert profile["time_range"]["min"] == "2024-01-01T10:00:00+00:00"
    assert profile["columns"]["kind"]["cardinality"] == 2
    assert profile["columns"]["fw"]["missing_rate"] == 0.0
    assert set(profile["columns"]) == {"unit_id", "ts", "kind", "fw", "severity"}


def test_generic_data_module_carries_no_domain_vocabulary():
    source = Path("src/faultevolve/data/event_schema.py").read_text(encoding="utf-8")
    forbidden = re.findall(r"\b(DIMM|mcelog|ECC|UE|bankid|SmartMem)\b", source, flags=re.IGNORECASE)
    assert forbidden == []
