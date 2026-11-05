"""V1-04: time-extrapolation splits, a single embargo rule, and a fail-closed audit.

Split boundaries come from the observable time span, never from row counts, and a sample whose
label window reaches the next split is removed once and marked rather than shifted sideways.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

from faultevolve.data.event_sampling import EventWindowConfig, build_labeled_samples, make_sample_id
from faultevolve.data.event_schema import CanonicalEventSchema
from faultevolve.data.temporal_split import (
    SplitBoundaries,
    SplitError,
    assign_temporal_splits,
    audit_temporal_splits,
    select_cold_units,
    suggest_split_boundaries,
)

UTC = "UTC"
DAY0 = pd.Timestamp("2024-01-01 00:00:00", tz=UTC)
FIFTEEN = pd.Timedelta(minutes=15)
WEEK = pd.Timedelta(days=7)
EMBARGO = FIFTEEN + WEEK
QUARTER_NS = int(FIFTEEN.to_timedelta64().astype("timedelta64[ns]").astype("int64"))
SENTINEL = "unit-zeqdserv000000-private"
COLUMNS = (
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
TRAIN_DAYS = [1, 10, 20, 30, 40, 50, 60]
DEV_DAYS = [72, 76]
VAL_DAYS = [88, 92]


def boundaries(**overrides) -> SplitBoundaries:
    base = dict(
        train_end=DAY0 + pd.Timedelta(days=70),
        dev_end=DAY0 + pd.Timedelta(days=85),
        val_end=DAY0 + pd.Timedelta(days=100),
        embargo=EMBARGO,
    )
    base.update(overrides)
    return SplitBoundaries(**base)


def sample(
    unit: str,
    prediction_time: pd.Timestamp,
    *,
    label: int = 0,
    split: object = pd.NA,
) -> dict:
    return {
        "sample_id": make_sample_id(unit, prediction_time),
        "unit_id": unit,
        "prediction_time": prediction_time,
        "label": label,
        "split_key": split,
        "history_start": prediction_time - pd.Timedelta(days=5),
        "history_end": prediction_time,
        "label_window_start": prediction_time + FIFTEEN,
        "label_window_end": prediction_time + FIFTEEN + WEEK,
    }


def at(day: int, unit: str = "u", **kw) -> dict:
    return sample(unit, DAY0 + pd.Timedelta(days=day, hours=1), **kw)


def frame(*rows: dict) -> pd.DataFrame:
    out = pd.DataFrame(list(rows), columns=list(COLUMNS))
    for column in (
        "prediction_time",
        "history_start",
        "history_end",
        "label_window_start",
        "label_window_end",
    ):
        out[column] = pd.DatetimeIndex(out[column])
    return out


def clean_assignment() -> pd.DataFrame:
    rows = [at(day, unit=f"u-{day}") for day in TRAIN_DAYS + DEV_DAYS + VAL_DAYS]
    return assign_temporal_splits(frame(*rows), boundaries())


# ---------------------------------------------------------------- suggested boundaries


def test_suggestion_splits_the_time_span_not_the_rows():
    cut = suggest_split_boundaries(
        DAY0, DAY0 + pd.Timedelta(days=100), lead=FIFTEEN, horizon=WEEK, anchor_frequency=FIFTEEN
    )
    assert cut.train_end == DAY0 + pd.Timedelta(days=70)
    assert cut.dev_end == DAY0 + pd.Timedelta(days=85)
    assert cut.val_end == DAY0 + pd.Timedelta(days=100)
    assert cut.embargo == EMBARGO


def test_suggestion_lands_on_the_anchor_frequency():
    cut = suggest_split_boundaries(
        DAY0 + pd.Timedelta(minutes=7),
        DAY0 + pd.Timedelta(days=40, hours=13),
        lead=FIFTEEN,
        horizon=WEEK,
        anchor_frequency=FIFTEEN,
    )
    for name in ("train_end", "dev_end", "val_end"):
        stamp = getattr(cut, name)
        assert stamp.tz is not None
        assert stamp.as_unit("ns").value % QUARTER_NS == 0


def test_suggestion_refuses_a_span_too_short_for_the_embargo():
    with pytest.raises(SplitError, match="train"):
        suggest_split_boundaries(
            DAY0,
            DAY0 + pd.Timedelta(days=10),
            lead=FIFTEEN,
            horizon=WEEK,
            anchor_frequency=FIFTEEN,
        )


def test_suggestion_refuses_an_empty_span():
    with pytest.raises(SplitError, match="span"):
        suggest_split_boundaries(
            DAY0, DAY0, lead=FIFTEEN, horizon=WEEK, anchor_frequency=FIFTEEN
        )


def test_suggestion_checks_outcome_coverage_of_the_last_split():
    with pytest.raises(SplitError, match="outcome"):
        suggest_split_boundaries(
            DAY0,
            DAY0 + pd.Timedelta(days=100),
            lead=FIFTEEN,
            horizon=WEEK,
            anchor_frequency=FIFTEEN,
            outcome_observed_until=DAY0 + pd.Timedelta(days=95),
        )


def test_suggestion_rejects_naive_endpoints():
    with pytest.raises(SplitError, match="timezone"):
        suggest_split_boundaries(
            DAY0.tz_localize(None),
            DAY0 + pd.Timedelta(days=100),
            lead=FIFTEEN,
            horizon=WEEK,
            anchor_frequency=FIFTEEN,
        )


# ---------------------------------------------------------------- assignment


def test_split_intervals_are_half_open_on_the_left():
    edge = DAY0 + pd.Timedelta(days=70)
    out = assign_temporal_splits(
        frame(sample("u-a", edge), sample("u-b", edge - FIFTEEN)), boundaries()
    )
    assert out.loc[out["unit_id"] == "u-a", "split_key"].item() == "dev"
    assert out.loc[out["unit_id"] == "u-b", "split_key"].item() == "embargo"


def test_embargo_is_one_gap_rule_applied_once():
    edge = DAY0 + pd.Timedelta(days=70)
    crossing = sample("u-a", edge - pd.Timedelta(minutes=1))
    inside = sample("u-b", edge - EMBARGO - FIFTEEN)
    out = assign_temporal_splits(frame(crossing, inside), boundaries())
    assert out.loc[out["unit_id"] == "u-a", "split_key"].item() == "embargo"
    assert out.loc[out["unit_id"] == "u-b", "split_key"].item() == "train"
    assert len(out) == 2


def test_a_label_window_one_nanosecond_early_stays_in_train():
    edge = DAY0 + pd.Timedelta(days=70)
    out = assign_temporal_splits(
        frame(sample("u-a", edge - EMBARGO - pd.Timedelta(1))), boundaries()
    )
    assert out["split_key"].item() == "train"


def test_reaching_the_next_split_start_is_already_a_crossing():
    edge = DAY0 + pd.Timedelta(days=70)
    exact = sample("u-a", edge - EMBARGO)  # label window ends exactly on dev_start
    out = assign_temporal_splits(frame(exact), boundaries())
    assert out["split_key"].item() == "embargo"


def test_dev_samples_too_close_to_the_val_start_are_embargoed():
    dev_edge = DAY0 + pd.Timedelta(days=85)
    out = assign_temporal_splits(
        frame(
            sample("u-a", dev_edge - pd.Timedelta(minutes=1)),
            sample("u-b", dev_edge - 2 * EMBARGO),
        ),
        boundaries(),
    )
    assert out["split_key"].tolist() == ["embargo", "dev"]


def test_the_last_split_needs_no_embargo_because_its_coverage_is_checked_upfront():
    val_edge = DAY0 + pd.Timedelta(days=100)
    rows = frame(sample("u-a", val_edge - pd.Timedelta(minutes=1)))
    out = assign_temporal_splits(rows, boundaries())
    assert out["split_key"].item() == "val"
    assert out["label_window_end"].item() > val_edge


def test_samples_at_or_after_the_val_end_are_not_scored():
    out = assign_temporal_splits(frame(sample("u-a", DAY0 + pd.Timedelta(days=100))), boundaries())
    assert out["split_key"].item() == "outside"


def test_one_unit_may_cross_splits_over_time():
    out = assign_temporal_splits(
        frame(at(1, "u-a"), at(76, "u-a"), at(90, "u-a")), boundaries()
    )
    assert sorted(out["split_key"].tolist()) == ["dev", "train", "val"]


def test_assignment_never_leaves_a_missing_split_key():
    out = assign_temporal_splits(
        frame(at(1, "u-a"), at(69, "u-b"), at(99, "u-c")), boundaries()
    )
    assert out["split_key"].notna().all()
    assert out["sample_id"].is_unique


def test_assignment_rejects_naive_prediction_times():
    rows = frame(sample("u-a", DAY0 + pd.Timedelta(days=3)))
    rows["prediction_time"] = rows["prediction_time"].dt.tz_localize(None)
    with pytest.raises(SplitError, match="timezone"):
        assign_temporal_splits(rows, boundaries())


# ---------------------------------------------------------------- cold unit audit


def test_cold_unit_selection_is_deterministic_and_order_blind():
    units = [f"u-{i}" for i in range(40)]
    first = select_cold_units(units, fraction=0.25, seed=3)
    again = select_cold_units(list(reversed(units)), fraction=0.25, seed=3)
    assert sorted(first) == sorted(again)
    assert len(first) == 10
    assert select_cold_units(units, fraction=0.25, seed=4) != first


def test_cold_unit_selection_survives_another_hash_seed():
    units = [f"u-{i}" for i in range(20)]
    first = sorted(select_cold_units(units, fraction=0.2, seed=5))
    code = (
        "from faultevolve.data.temporal_split import select_cold_units\n"
        "print(sorted(select_cold_units([f'u-{i}' for i in range(20)], fraction=0.2, seed=5)))\n"
    )
    env = dict(os.environ, PYTHONHASHSEED="1")
    done = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, env=env, check=True
    )
    assert eval(done.stdout.strip()) == first


def test_cold_units_are_dropped_from_train_but_still_evaluated():
    cold = "u-cold"
    out = assign_temporal_splits(
        frame(at(1, cold), at(90, cold), at(1, "u-normal")),
        boundaries(),
        cold_units=[cold],
    )
    cold_rows = out[out["unit_id"] == cold]
    assert cold_rows["split_key"].tolist() == ["cold_audit", "val"]
    assert "train" not in cold_rows["split_key"].tolist()
    assert out.loc[out["unit_id"] == "u-normal", "split_key"].item() == "train"


def test_a_label_window_that_crosses_two_splits_is_marked_once():
    edge = DAY0 + pd.Timedelta(days=70)
    far = sample("u-a", edge - pd.Timedelta(days=1))  # reaches both train_end and dev_end
    out = assign_temporal_splits(frame(far), boundaries())
    assert out["split_key"].item() == "embargo"
    assert len(out) == 1


def test_assignment_is_blind_to_row_order():
    rows = [at(day, unit=f"u-{day}") for day in TRAIN_DAYS + DEV_DAYS + VAL_DAYS]
    forward = assign_temporal_splits(frame(*rows), boundaries())
    backward = assign_temporal_splits(frame(*reversed(rows)), boundaries())
    left = forward.set_index("sample_id")["split_key"]
    right = backward.set_index("sample_id")["split_key"]
    assert left.sort_index().equals(right.sort_index())


def test_samples_before_the_observed_span_are_outside():
    shifted = boundaries(start=DAY0 + pd.Timedelta(days=5))
    out = assign_temporal_splits(frame(at(1, "u-a"), at(10, "u-b")), shifted)
    assert out["split_key"].tolist() == ["outside", "train"]


def test_boundaries_reject_a_naive_edge():
    with pytest.raises(SplitError, match="timezone"):
        SplitBoundaries(
            train_end=(DAY0 + pd.Timedelta(days=70)).tz_localize(None),
            dev_end=DAY0 + pd.Timedelta(days=85),
            val_end=DAY0 + pd.Timedelta(days=100),
            embargo=EMBARGO,
        )


def test_boundaries_reject_edges_out_of_order():
    with pytest.raises(SplitError, match="dev_end"):
        SplitBoundaries(
            train_end=DAY0 + pd.Timedelta(days=85),
            dev_end=DAY0 + pd.Timedelta(days=70),
            val_end=DAY0 + pd.Timedelta(days=100),
            embargo=EMBARGO,
        )


def test_boundaries_reject_a_missing_gap():
    with pytest.raises(SplitError, match="embargo"):
        SplitBoundaries(
            train_end=DAY0 + pd.Timedelta(days=70),
            dev_end=DAY0 + pd.Timedelta(days=85),
            val_end=DAY0 + pd.Timedelta(days=100),
            embargo=pd.Timedelta(0),
        )


def test_suggestion_rejects_a_non_positive_gap():
    with pytest.raises(SplitError, match="horizon"):
        suggest_split_boundaries(
            DAY0,
            DAY0 + pd.Timedelta(days=100),
            lead=FIFTEEN,
            horizon=pd.Timedelta(0),
            anchor_frequency=FIFTEEN,
        )


def test_cold_unit_selection_rejects_an_out_of_range_fraction():
    with pytest.raises(SplitError, match="fraction"):
        select_cold_units(["u-a"], fraction=1.5, seed=1)


# ---------------------------------------------------------------- audit


def test_a_clean_assignment_passes_with_no_violations():
    report = audit_temporal_splits(clean_assignment(), boundaries())
    assert report["passed"] is True
    assert report["violations"] == {}


def test_audit_flags_history_that_ends_after_the_prediction_time():
    rows = clean_assignment()
    # The column stores microseconds on this pandas build, so the overshoot has to be coarser than
    # a nanosecond to survive the assignment at all.
    rows.loc[rows.index[-1], "history_end"] = rows["prediction_time"].iloc[-1] + pd.Timedelta(
        microseconds=1
    )
    report = audit_temporal_splits(rows, boundaries())
    assert report["passed"] is False
    assert report["violations"]["history_after_prediction_time"] == 1


def test_audit_flags_a_label_window_that_reaches_the_next_split():
    rows = clean_assignment()
    idx = rows.index[rows["split_key"] == "train"][0]
    rows.loc[idx, "label_window_end"] = boundaries().dev_end
    report = audit_temporal_splits(rows, boundaries())
    assert report["passed"] is False
    assert report["violations"]["label_window_crosses_split"] == 1


def test_audit_flags_a_label_window_that_starts_at_the_prediction_time():
    rows = clean_assignment()
    rows.loc[rows.index[0], "label_window_start"] = rows["prediction_time"].iloc[0]
    report = audit_temporal_splits(rows, boundaries())
    assert report["violations"]["label_window_not_ahead"] == 1


def test_audit_flags_the_same_sample_id_in_two_splits():
    rows = clean_assignment()
    twin = rows.iloc[[0]].copy()
    twin["split_key"] = "val"
    report = audit_temporal_splits(pd.concat([rows, twin], ignore_index=True), boundaries())
    assert report["violations"]["duplicate_sample_id"] == 1


def test_audit_flags_a_split_key_that_disagrees_with_the_timestamp():
    rows = clean_assignment()
    rows.loc[rows.index[0], "split_key"] = "val"  # a train-window instant labelled val
    report = audit_temporal_splits(rows, boundaries())
    assert report["violations"]["split_key_mismatch"] == 1


def test_audit_flags_a_cold_unit_that_reached_training():
    rows = clean_assignment()
    rows.loc[rows["split_key"] == "train", "unit_id"] = SENTINEL
    report = audit_temporal_splits(rows, boundaries(), cold_units=[SENTINEL])
    assert report["violations"]["cold_unit_in_train"] == len(TRAIN_DAYS)


def test_audit_flags_an_empty_split():
    report = audit_temporal_splits(frame(at(1, "u-a")), boundaries())
    assert report["passed"] is False
    assert "empty_split" in report["violations"]


def test_audit_report_stays_anonymous():
    rows = clean_assignment()
    rows["unit_id"] = SENTINEL
    report = audit_temporal_splits(rows, boundaries(), cold_units=[SENTINEL])
    assert SENTINEL not in str(report)


def test_audit_report_is_json_friendly():
    report = audit_temporal_splits(clean_assignment(), boundaries())
    json.dumps(report)
    assert set(report) >= {"passed", "violations", "splits", "embargo_removed"}


def test_audit_report_records_the_interval_it_used():
    cut = boundaries()
    report = audit_temporal_splits(clean_assignment(), cut)
    assert report["boundaries"]["train_end"] == cut.train_end.isoformat()
    assert report["boundaries"]["start"] is None
    assert report["splits"] == {"train": 7, "dev": 2, "val": 2}


# ---------------------------------------------------------------- integration


def test_sampler_output_splits_and_audits_clean():
    schema = CanonicalEventSchema(
        unit_col="unit_id", time_col="log_time", event_type_col="error_type"
    )
    stamps = pd.DatetimeIndex(
        [DAY0 + pd.Timedelta(days=day, hours=6) for day in range(0, 109, 3)], tz=UTC
    )
    events = pd.DataFrame(
        {
            "unit_id": ["u-a"] * len(stamps) + ["u-b"] * len(stamps),
            "log_time": list(stamps) + list(stamps + pd.Timedelta(hours=1)),
            "error_type": ["ce"] * (2 * len(stamps)),
        }
    )
    until = DAY0 + pd.Timedelta(days=120)
    cut = suggest_split_boundaries(
        stamps.min(),
        DAY0 + pd.Timedelta(days=112),
        lead=FIFTEEN,
        horizon=WEEK,
        anchor_frequency=FIFTEEN,
        outcome_observed_until=until,
    )
    samples = build_labeled_samples(
        events,
        pd.DataFrame({"unit_id": [], "failure_time": pd.DatetimeIndex([], tz=UTC)}),
        schema,
        EventWindowConfig(
            lookback=pd.Timedelta(days=5),
            lead=FIFTEEN,
            horizon=WEEK,
            anchor_frequency=FIFTEEN,
            anchor_strategy="event",
            max_samples_per_unit=None,
            seed=0,
        ),
        failure_unit_col="unit_id",
        failure_time_col="failure_time",
        outcome_observed_until=until,
    )
    assigned = assign_temporal_splits(samples, cut)
    report = audit_temporal_splits(assigned, cut)
    assert report["passed"] is True, report
    assert set(assigned["split_key"]) <= {"train", "dev", "val", "embargo", "outside"}
    assert {"train", "dev", "val"} <= set(assigned["split_key"])


def test_generic_layer_stays_domain_free():
    source = (
        Path(__file__).resolve().parents[1] / "src" / "faultevolve" / "data" / "temporal_split.py"
    ).read_text(encoding="utf-8")
    assert re.findall(r"\b(DIMM|mcelog|ECC|UE|bankid|SmartMem)\b", source, re.IGNORECASE) == []
