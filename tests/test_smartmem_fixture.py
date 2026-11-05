"""V1-01: the synthetic SmartMem fixture must be explicit, deterministic and round-trippable."""

from __future__ import annotations

import pandas as pd
import pytest

from faultevolve.data.event_schema import CanonicalEventSchema, normalize_events
from faultevolve.tasks.smartmem_adapter import TICKET_COLUMNS, MCELOG_COLUMNS, SmartMemAdapter
from tests.helpers_smartmem import (
    ANCHORS,
    EVENTS_BY_UNIT,
    FAILURE_TIME_BY_UNIT,
    INT_COLS,
    OUTCOME_OBSERVED_UNTIL,
    SERIAL_TYPE_BY_UNIT,
    SENTINEL_UNIT,
    SPAN_DAYS,
    STR_COLS,
    fixture_facts,
    read_unit_file,
    write_fixture,
)


def _units_dir(tmp_path, fmt):
    return write_fixture(tmp_path / f"raw-{fmt}", fmt=fmt)


def test_fixture_covers_all_23_official_columns_per_unit():
    for unit, events in EVENTS_BY_UNIT.items():
        assert list(events.columns) == list(MCELOG_COLUMNS), unit
        assert len(events) >= 1, unit
    assert len(EVENTS_BY_UNIT) >= 6


def test_fixture_spans_at_least_120_days_from_a_fixed_epoch():
    all_times = pd.concat([e["log_time"] for e in EVENTS_BY_UNIT.values()])
    assert all_times.min() == fixture_facts()["start"]
    assert (all_times.max() - all_times.min()).days >= SPAN_DAYS - 1
    assert all_times.max() < fixture_facts()["end"]


def test_fixture_never_uses_the_current_date():
    # A fixture that drifts with today's date cannot pin label boundaries.
    facts = fixture_facts()
    assert facts["start"] == pd.Timestamp("2024-01-01 00:00:00", tz="UTC")
    assert facts["end"].tz == facts["outcome_observed_until"].tz == pd.Timestamp("2024-01-01", tz="UTC").tz
    assert OUTCOME_OBSERVED_UNTIL < facts["end"]


def test_required_case_variants_are_present():
    units = set(EVENTS_BY_UNIT)
    assert units >= {
        "unit-clean",
        "unit-lead-hit",
        "unit-lead-miss",
        "unit-horizon-hit",
        "unit-horizon-miss",
        "unit-followup-short",
        "unit-dup-events",
        "unit-static-late",
        SENTINEL_UNIT,
    }
    assert "unit-clean" not in FAILURE_TIME_BY_UNIT
    assert "unit-followup-short" not in FAILURE_TIME_BY_UNIT


def test_label_boundary_offsets_are_hand_computable():
    for unit, offset in (
        ("unit-lead-hit", pd.Timedelta(minutes=15)),
        ("unit-lead-miss", pd.Timedelta(minutes=15) - pd.Timedelta(seconds=1)),
        ("unit-horizon-hit", pd.Timedelta(minutes=15) + pd.Timedelta(days=7)),
        (
            "unit-horizon-miss",
            pd.Timedelta(minutes=15) + pd.Timedelta(days=7) + pd.Timedelta(nanoseconds=1),
        ),
    ):
        anchor = ANCHORS[unit]
        gap = FAILURE_TIME_BY_UNIT[unit] - anchor
        assert gap == offset, f"{unit}: {gap} != {offset}"


def test_an_anchor_after_the_first_failure_exists_for_removal_tests():
    anchor = ANCHORS["unit-lead-hit-post-failure"]
    assert anchor >= FAILURE_TIME_BY_UNIT["unit-lead-hit"]


def test_one_unit_carries_exact_duplicate_and_same_time_different_address_rows():
    events = EVENTS_BY_UNIT["unit-dup-events"]
    exact = events.duplicated(keep=False)
    assert exact.sum() == 2  # one pair identical across all 23 raw fields
    same_time = events.groupby("log_time")["columnid"].nunique()
    assert (same_time > 1).sum() == 1
    collision_time = same_time[same_time > 1].index[0]
    collision = events[events["log_time"] == collision_time]
    assert sorted(collision["columnid"]) == [7, 8]


def test_disk_row_order_is_scrambled_deterministically(tmp_path):
    root = _units_dir(tmp_path, "csv")
    path = root / "train" / "unit-dup-events.csv"
    on_disk = pd.read_csv(path, dtype=str)
    parsed = pd.to_datetime(on_disk["log_time"], utc=True, format="ISO8601")
    assert not parsed.is_monotonic_increasing


def test_static_field_is_missing_before_a_known_day():
    events = EVENTS_BY_UNIT["unit-static-late"]
    early = events[events["log_time"] < pd.Timestamp("2024-01-01", tz="UTC") + pd.Timedelta(days=30)]
    late = events[events["log_time"] >= pd.Timestamp("2024-01-01", tz="UTC") + pd.Timedelta(days=30)]
    assert set(early["model"]) == {""}
    assert set(late["model"]) == {"FM-DEMO-200"}
    assert not (set(events["manufacturter"]) - {"VENDORX", ""})


def test_serial_types_come_from_a_static_source_not_from_tickets():
    assert set(SERIAL_TYPE_BY_UNIT) == set(EVENTS_BY_UNIT)
    assert set(SERIAL_TYPE_BY_UNIT.values()) == {"A", "B"}
    # A unit with no ticket still has a type, proving type is not derived from failure records.
    assert "unit-clean" not in FAILURE_TIME_BY_UNIT
    assert "unit-clean" in SERIAL_TYPE_BY_UNIT


def test_spatial_counts_are_hand_computable():
    events = EVENTS_BY_UNIT["unit-clean"]
    window = events[events["log_time"] > fixture_facts()["anchor_unit_clean"] - pd.Timedelta(days=5)]
    window = window[window["log_time"] <= fixture_facts()["anchor_unit_clean"]]
    assert len(window) == 3
    assert sorted(window["rowid"]) == [100, 100, 101]
    assert window["rowid"].nunique() == 2
    assert window["bankid"].nunique() == 2


def test_tickets_include_a_duplicate_and_pass_adapter_validation():
    facts = fixture_facts()
    tickets = facts["tickets"]
    assert list(tickets.columns) == list(TICKET_COLUMNS)
    SmartMemAdapter.validate_ticket_frame(tickets)
    dup = tickets[tickets.duplicated(subset=["serial_number", "failure_time"], keep=False)]
    assert len(dup) == 2


def test_no_unit_id_looks_like_a_production_serial():
    for unit in EVENTS_BY_UNIT:
        assert unit.startswith("unit-")
        assert unit == unit.lower()
    assert SENTINEL_UNIT.startswith("unit-")


def test_sentinel_unit_is_isolated_from_facts_summaries():
    facts = fixture_facts()
    assert SENTINEL_UNIT in EVENTS_BY_UNIT
    assert SENTINEL_UNIT not in FAILURE_TIME_BY_UNIT
    assert facts["positive_units"] and SENTINEL_UNIT not in facts["positive_units"]


@pytest.mark.parametrize("fmt", ["csv", "feather"])
def test_fixture_writes_and_reads_back_one_file_per_unit(tmp_path, fmt):
    root = _units_dir(tmp_path, fmt)
    train = root / "train"
    written = sorted(p.name for p in train.iterdir())
    assert len(written) == len(EVENTS_BY_UNIT)
    for unit in EVENTS_BY_UNIT:
        path = train / f"{unit}.{fmt}"
        assert path.exists(), path.name
        back = read_unit_file(path, fmt=fmt)
        assert list(back.columns) == list(MCELOG_COLUMNS)
        assert len(back) == len(EVENTS_BY_UNIT[unit])


def test_csv_and_feather_carry_the_same_logical_events(tmp_path):
    csv_root = _units_dir(tmp_path, "csv")
    feather_root = _units_dir(tmp_path, "feather")
    for unit, events in EVENTS_BY_UNIT.items():
        a = read_unit_file(csv_root / "train" / f"{unit}.csv", fmt="csv")
        b = read_unit_file(feather_root / "train" / f"{unit}.feather", fmt="feather")
        pd.testing.assert_frame_equal(a, b, check_freq=False)


def test_generic_normalizer_keeps_the_fixture_boundary_rows(tmp_path):
    """The V1-02 generic layer must consume the 23-column fixture without inventing values."""
    root = _units_dir(tmp_path, "csv")
    events = read_unit_file(root / "train" / "unit-dup-events.csv", fmt="csv")
    assert len(events) == 6
    events.insert(0, "unit_id", "unit-dup-events")

    schema = CanonicalEventSchema(
        unit_col="unit_id",
        time_col="log_time",
        event_type_col="error_type",
        static_cols=("model", "PN", "Capacity"),
        categorical_cols=tuple(STR_COLS),
        numeric_cols=tuple(INT_COLS),
    )
    out = normalize_events(events, schema, timezone="UTC")

    assert len(out) == 5  # only the exact duplicate pair collapses
    assert out["log_time"].is_monotonic_increasing
    assert str(out["log_time"].dtype) == "datetime64[ns, UTC]"

    counts = out.groupby("log_time")["columnid"].nunique()
    collision_time = counts[counts > 1].index[0]
    collision = out[out["log_time"] == collision_time]
    assert sorted(collision["columnid"]) == [7, 8]
    assert out["manufacturter"].unique().tolist() == ["VENDORX"]
