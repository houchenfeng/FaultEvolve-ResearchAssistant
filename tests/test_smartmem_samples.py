"""V1-05 (part 3): the SmartMem adapter is a thin wrapper, not a second sampler.

The numbers below are hand-derived from ``tests/helpers_smartmem.py``: every unit there is built so
that one anchor strategy gives one predictable sample set. If this module ever re-implements
windowing, labelling or feature slicing, these tests are the tripwire.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from helpers_smartmem import (  # noqa: E402
    EVENTS_BY_UNIT,
    HORIZON,
    LEAD,
    LOOKBACK,
    OUTCOME_OBSERVED_UNTIL,
    SENTINEL_UNIT,
    STATIC_BY_UNIT,
    _ticket_frame,
    day,
)

from faultevolve.data.event_sampling import OUTPUT_COLUMNS  # noqa: E402
from faultevolve.data.temporal_split import (  # noqa: E402
    assign_temporal_splits,
    audit_temporal_splits,
    suggest_split_boundaries,
)
from faultevolve.tasks.smartmem_adapter import SmartMemAdapter  # noqa: E402
from faultevolve.tasks.smartmem_data import (  # noqa: E402
    SmartMemDataError,
    add_history_features,
    aggregate_events_to_samples,
)

TICKETS = _ticket_frame()


def unit_frame(unit: str) -> pd.DataFrame:
    """One unit's log, exactly as ``read_smartmem_file`` returns it: with the join column."""
    return EVENTS_BY_UNIT[unit].assign(serial_number=unit)


def one_unit(unit: str, **kwargs) -> pd.DataFrame:
    events = unit_frame(unit) if unit in EVENTS_BY_UNIT else unit_frame(SENTINEL_UNIT)
    tickets = TICKETS[TICKETS["serial_number"] == unit].reset_index(drop=True)
    return aggregate_events_to_samples(events, tickets, **kwargs)


def test_default_windows_are_the_official_lead_and_horizon():
    out = one_unit("unit-clean", outcome_observed_until=OUTCOME_OBSERVED_UNTIL)
    assert len(out) == 3  # 100d08, 100d16, 101d08; the 119d23 anchor is censored
    assert (out["prediction_time"] + LEAD == out["label_window_start"]).all()
    assert (out["label_window_end"] - out["label_window_start"] == HORIZON).all()
    assert (out["prediction_time"] - out["history_start"] == LOOKBACK).all()
    assert out["label"].tolist() == [0, 0, 0]


def test_a_failure_inside_the_window_is_a_positive_and_nothing_else_is_emitted():
    out = one_unit("unit-lead-hit", outcome_observed_until=OUTCOME_OBSERVED_UNTIL)
    assert out["label"].tolist() == [1, 1, 1]  # failure at 60d00 sits 15 min after the last anchor
    assert set(out["prediction_time"]) == {day(59, 20), day(59, 23), day(59, 23, 30)}


def test_the_censor_rule_is_visible_in_the_report():
    report: dict = {}
    out = one_unit("unit-clean", outcome_observed_until=OUTCOME_OBSERVED_UNTIL, report=report)
    assert len(out) == 3
    assert report["censored"] == 1  # the 119d23 anchor cannot close its label window
    assert report["post_failure_event"] == 0


def test_tickets_never_reach_the_sample_frame():
    out = one_unit("unit-lead-hit", outcome_observed_until=OUTCOME_OBSERVED_UNTIL)
    for column in ("failure_time", "serial_number_type", "sn_name", "alarm_time", "sn_type"):
        assert column not in out.columns
    assert "unit_id" in out.columns


def test_features_are_appended_after_the_generic_sample_columns():
    out = one_unit("unit-clean", outcome_observed_until=OUTCOME_OBSERVED_UNTIL)
    assert list(out.columns[: len(OUTPUT_COLUMNS)]) == list(OUTPUT_COLUMNS)
    assert out["event_count"].tolist() == [1, 2, 3]
    assert out["model"].tolist() == [STATIC_BY_UNIT["unit-clean"]["model"]] * 3


def test_the_wrapper_does_not_assign_a_split():
    out = one_unit("unit-clean", outcome_observed_until=OUTCOME_OBSERVED_UNTIL)
    assert out["split_key"].isna().all()


def test_the_features_match_a_direct_call_to_add_history_features():
    events = unit_frame("unit-clean")
    out = one_unit("unit-clean", outcome_observed_until=OUTCOME_OBSERVED_UNTIL, error_types=("ce",))
    reference = add_history_features(
        out[list(OUTPUT_COLUMNS)], events, lookback=LOOKBACK, error_types=("ce",)
    )
    produced = [column for column in out.columns if column not in OUTPUT_COLUMNS]
    assert produced
    pd.testing.assert_frame_equal(out[produced], reference[produced])


def test_add_features_false_returns_only_the_generic_contract():
    reference = aggregate_events_to_samples(
        unit_frame("unit-clean"),
        TICKETS.iloc[0:0],
        outcome_observed_until=OUTCOME_OBSERVED_UNTIL,
        add_features=False,
    )
    assert list(reference.columns) == list(OUTPUT_COLUMNS)


def test_legacy_day_and_minute_keywords_still_work_and_mean_the_same():
    modern = one_unit(
        "unit-clean",
        outcome_observed_until=OUTCOME_OBSERVED_UNTIL,
        lookback=pd.Timedelta(days=5),
        anchor_frequency=pd.Timedelta(minutes=15),
        max_samples_per_unit=200,
    )
    legacy = one_unit(
        "unit-clean",
        outcome_observed_until=OUTCOME_OBSERVED_UNTIL,
        lookback_days=5,
        sample_every_minutes=15,
        max_samples_per_dimm=200,
    )
    pd.testing.assert_frame_equal(modern, legacy)


def test_spelling_the_same_window_two_ways_is_refused():
    with pytest.raises(SmartMemDataError, match="lookback_days"):
        one_unit(
            "unit-clean",
            outcome_observed_until=OUTCOME_OBSERVED_UNTIL,
            lookback=pd.Timedelta(days=5),
            lookback_days=4,
        )


def test_a_third_positional_argument_fails_with_a_readable_message():
    with pytest.raises(TypeError, match="positional"):
        SmartMemAdapter.aggregate_events_to_samples(
            unit_frame("unit-clean"), TICKETS, 5
        )


def test_naive_times_need_an_explicit_timezone():
    events = unit_frame("unit-clean").copy()
    events["log_time"] = events["log_time"].dt.tz_localize(None)
    with pytest.raises(SmartMemDataError, match="timezone"):
        aggregate_events_to_samples(
            events, TICKETS.iloc[0:0], outcome_observed_until=OUTCOME_OBSERVED_UNTIL
        )
    declared = aggregate_events_to_samples(
        events,
        TICKETS.iloc[0:0],
        outcome_observed_until=OUTCOME_OBSERVED_UNTIL,
        timezone="UTC",
    )
    assert len(declared) == 3


def test_events_without_the_unit_column_are_refused():
    with pytest.raises(SmartMemDataError, match="serial_number"):
        aggregate_events_to_samples(
            EVENTS_BY_UNIT["unit-clean"],
            TICKETS.iloc[0:0],
            outcome_observed_until=OUTCOME_OBSERVED_UNTIL,
        )


def test_the_adapter_static_method_is_the_same_wrapper():
    out = SmartMemAdapter.aggregate_events_to_samples(
        unit_frame("unit-clean"),
        TICKETS[TICKETS["serial_number"] == "unit-clean"],
        outcome_observed_until=OUTCOME_OBSERVED_UNTIL,
    )
    assert len(out) == 3
    assert out["sample_id"].tolist() == aggregate_events_to_samples(
        unit_frame("unit-clean"),
        TICKETS[TICKETS["serial_number"] == "unit-clean"],
        outcome_observed_until=OUTCOME_OBSERVED_UNTIL,
    )["sample_id"].tolist()


def test_a_grid_strategy_produces_more_anchors_than_the_event_strategy():
    events = unit_frame("unit-clean")
    grid = aggregate_events_to_samples(
        events,
        TICKETS.iloc[0:0],
        outcome_observed_until=OUTCOME_OBSERVED_UNTIL,
        anchor_strategy="grid",
    )
    event = aggregate_events_to_samples(
        events,
        TICKETS.iloc[0:0],
        outcome_observed_until=OUTCOME_OBSERVED_UNTIL,
    )
    assert len(grid) > len(event)
    assert set(event["prediction_time"]) <= set(grid["prediction_time"])


def test_the_sample_set_is_blind_to_event_row_order():
    events = unit_frame("unit-lead-hit").iloc[::-1].reset_index(drop=True)
    tickets = TICKETS[TICKETS["serial_number"] == "unit-lead-hit"]
    out = aggregate_events_to_samples(
        events, tickets, outcome_observed_until=OUTCOME_OBSERVED_UNTIL
    )
    assert out["label"].tolist() == [1, 1, 1]
    assert set(out["prediction_time"]) == {day(59, 20), day(59, 23), day(59, 23, 30)}


def test_a_unit_with_no_ticket_still_builds_rows_from_its_own_events():
    out = one_unit(SENTINEL_UNIT, outcome_observed_until=OUTCOME_OBSERVED_UNTIL)
    assert out["label"].tolist() == [0, 0]
    assert out["unit_id"].unique().tolist() == [SENTINEL_UNIT]
    assert set(out["prediction_time"]) == {day(15, 8), day(105, 8)}


def test_an_unknown_anchor_strategy_is_refused_before_anything_is_read():
    with pytest.raises(SmartMemDataError, match="anchor_strategy"):
        aggregate_events_to_samples(
            unit_frame("unit-clean"),
            TICKETS.iloc[0:0],
            outcome_observed_until=OUTCOME_OBSERVED_UNTIL,
            anchor_strategy="whenever",
        )


def test_a_non_numeric_legacy_cap_is_refused():
    with pytest.raises(SmartMemDataError, match="max_samples_per_dimm"):
        aggregate_events_to_samples(
            unit_frame("unit-clean"),
            TICKETS.iloc[0:0],
            outcome_observed_until=OUTCOME_OBSERVED_UNTIL,
            max_samples_per_dimm="many",
        )


def test_a_ticket_with_an_unknown_serial_type_is_refused():
    bad = TICKETS.assign(serial_number_type="C")
    with pytest.raises(SmartMemDataError, match="serial_number_type"):
        aggregate_events_to_samples(
            unit_frame("unit-lead-hit"), bad, outcome_observed_until=OUTCOME_OBSERVED_UNTIL
        )


def test_the_full_fixture_composes_with_the_split_and_the_leakage_audit():
    # 9 synthetic units, so concatenating is fine here; the real 130 GB case streams one unit file
    # at a time through V1-06 and never builds one frame like this.
    events = pd.concat(
        [unit_frame(unit) for unit in sorted(EVENTS_BY_UNIT)], ignore_index=True
    )
    samples = aggregate_events_to_samples(
        events,
        TICKETS,
        outcome_observed_until=OUTCOME_OBSERVED_UNTIL,
        max_samples_per_unit=None,
        error_types=("ce", "ue"),
    )
    assert len(samples) > 0
    boundaries = suggest_split_boundaries(
        day(20),
        day(105),
        lead=LEAD,
        horizon=HORIZON,
        anchor_frequency=pd.Timedelta(minutes=15),
        outcome_observed_until=OUTCOME_OBSERVED_UNTIL,
    )
    assigned = assign_temporal_splits(samples, boundaries)
    report = audit_temporal_splits(assigned, boundaries)
    assert report["passed"], report["violations"]
    assert report["embargo_removed"] >= 1  # a window that reaches the next split is removed
    assert report["splits"].get("outside", 0) >= 1  # anchors past the declared span are not scored


def test_a_run_that_produces_no_sample_still_produces_the_generic_columns():
    out = aggregate_events_to_samples(
        unit_frame("unit-followup-short"),
        TICKETS.iloc[0:0],
        outcome_observed_until=day(30),
    )
    assert len(out) == 0
    assert list(out.columns) == list(OUTPUT_COLUMNS)


def test_horizon_days_and_lead_minutes_are_legacy_aliases_too():
    modern = one_unit(
        "unit-horizon-hit",
        outcome_observed_until=OUTCOME_OBSERVED_UNTIL,
        lead=pd.Timedelta(minutes=15),
        horizon=pd.Timedelta(days=7),
    )
    legacy = one_unit(
        "unit-horizon-hit",
        outcome_observed_until=OUTCOME_OBSERVED_UNTIL,
        lead_minutes=15,
        predict_window_days=7,
    )
    pd.testing.assert_frame_equal(modern, legacy)
