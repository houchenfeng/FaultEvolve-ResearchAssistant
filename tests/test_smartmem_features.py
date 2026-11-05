"""V1-05 (part 2): features aggregated strictly inside the history window.

Every value here is hand-checkable against ``tests/helpers_smartmem.py``. The rule the tests hold
tightest: a feature may read ``(t - lookback, t]`` and nothing later, so appending future rows to a
unit's log cannot change a single number of an earlier sample.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from helpers_smartmem import EVENTS_BY_UNIT, STATIC_BY_UNIT, day  # noqa: E402

from faultevolve.tasks.smartmem_data import (  # noqa: E402
    FEATURE_DTYPES,
    FEATURE_GROUPS,
    FEATURE_MANIFEST,
    SmartMemDataError,
    add_history_features,
    canonicalize_feature_types,
    declared_error_types,
    error_type_counts,
    history_features,
)

TWO_DAYS = pd.Timedelta(days=2)
CLEAN = EVENTS_BY_UNIT["unit-clean"]
T = day(101, 12)


def feats(history: pd.DataFrame, *, prediction_time: pd.Timestamp = T, **overrides) -> dict:
    kwargs = {"prediction_time": prediction_time, "lookback": TWO_DAYS, "error_types": ("ce", "ue")}
    kwargs.update(overrides)
    return history_features(history, **kwargs)


def clean_history(t: pd.Timestamp = T, lookback: pd.Timedelta = TWO_DAYS) -> pd.DataFrame:
    left = t - lookback
    return CLEAN.loc[(CLEAN["log_time"] > left) & (CLEAN["log_time"] <= t)]


def unit_log(unit: str = "unit-clean") -> pd.DataFrame:
    """The fixture log for one unit, carrying the column the sample frame joins on."""
    return EVENTS_BY_UNIT[unit].assign(serial_number=unit)


# ---------------------------------------------------------------- the hand-counted numbers


def test_counts_and_gaps_are_read_from_the_window_only():
    history = clean_history()
    assert len(history) == 3  # 100d08, 100d16, 101d08; the 119d23 event is in the future
    out = feats(history)
    assert out["event_count"] == 3
    assert out["ce_count"] == 3
    assert out["ue_count"] == 0
    assert out["minutes_since_last_event"] == 240.0  # 101d08 -> 101d12


def test_recent_half_and_growth_rate_split_the_lookback():
    out = feats(clean_history())
    assert out["recent_half_count"] == 2  # (100d12, 101d12]
    assert out["earlier_half_count"] == 1
    assert out["growth_rate"] == pytest.approx(1 / 3)  # (2 - 1) / 3


def test_spatial_concentration_is_hand_computable():
    out = feats(clean_history())
    assert out["distinct_rowid"] == 2  # 100, 101
    assert out["distinct_columnid"] == 2  # 5, 6
    assert out["distinct_bankid"] == 2
    assert out["rowid_repeat_rate"] == pytest.approx(1 / 3)  # (3 rows - 2 distinct) / 3
    assert out["top_rowid_share"] == pytest.approx(2 / 3)  # rowid 100 appears twice


def test_coverage_reports_how_much_of_the_window_was_seen():
    out = feats(clean_history())
    assert out["window_span_minutes"] == 1440.0  # 100d08 -> 101d08
    assert out["window_fill_rate"] == pytest.approx(1440 / (2 * 24 * 60))


# ---------------------------------------------------------------- empty windows and unknowns


def test_an_empty_window_counts_zero_and_leaves_gaps_unknown():
    out = feats(CLEAN.iloc[0:0])
    assert out["event_count"] == 0
    assert out["ce_count"] == 0 and out["ue_count"] == 0
    assert out["distinct_rowid"] == 0
    assert pd.isna(out["minutes_since_last_event"])
    assert pd.isna(out["growth_rate"])
    assert pd.isna(out["top_rowid_share"])
    assert pd.isna(out["window_span_minutes"])


def test_a_static_field_uses_the_last_non_empty_value_at_or_before_the_prediction_time():
    late = EVENTS_BY_UNIT["unit-static-late"]
    model = STATIC_BY_UNIT["unit-static-late"]["model"]
    assert pd.isna(feats(late.loc[late["log_time"] <= day(20)])["model"])
    window = late.loc[(late["log_time"] > day(25)) & (late["log_time"] <= day(35))]
    assert feats(window)["model"] == model


def test_an_unseen_category_is_counted_not_turned_into_a_new_column():
    report: dict = {}
    out = feats(
        clean_history().assign(error_type=["ce", "ce", "scrub"]),
        error_types=("ce",),
        report=report,
    )
    assert out["ce_count"] == 2
    assert out["unexpected_error_type_count"] == 1
    assert "scrub_count" not in out
    assert report["unexpected_error_type_rows"] == 1


def test_events_at_the_same_address_are_not_merged_away():
    same = pd.DataFrame(
        [
            {**CLEAN.iloc[0].to_dict(), "log_time": day(100, 15), "error_type": "ce"},
            {**CLEAN.iloc[0].to_dict(), "log_time": day(100, 15), "error_type": "ue"},
        ]
    )
    out = feats(same)
    assert out["event_count"] == 2
    assert out["ce_count"] == 1 and out["ue_count"] == 1
    assert out["distinct_rowid"] == 1


def test_retry_and_parity_rates_treat_a_zero_record_as_no_mark():
    out = feats(clean_history())
    assert set(out) >= {"retryrderrlog_marked_rate", "parity_marked_rate", "burst_info_distinct"}
    assert out["retryrderrlog_marked_rate"] == 0.0
    assert out["burst_info_distinct"] == 1


def test_a_row_after_the_prediction_time_is_refused_instead_of_quietly_used():
    leaked = clean_history().copy()
    leaked["log_time"] = leaked["log_time"] + pd.Timedelta(days=1)
    with pytest.raises(SmartMemDataError, match="after the prediction time"):
        feats(leaked)


def test_a_window_without_the_time_column_is_refused():
    with pytest.raises(SmartMemDataError, match="log_time"):
        history_features(
            CLEAN.drop(columns=["log_time"]),
            prediction_time=T,
            lookback=TWO_DAYS,
        )


def test_a_naive_prediction_time_is_refused():
    with pytest.raises(SmartMemDataError, match="timezone"):
        feats(clean_history(), prediction_time=T.tz_localize(None))


# ---------------------------------------------------------------- the driver over samples


def sample_rows() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "sample_id": ["s-1", "s-2"],
            "unit_id": ["unit-clean", "unit-clean"],
            "prediction_time": [day(101, 12), day(100, 12)],
            "label": [0, 0],
        }
    )


def test_add_history_features_keeps_every_sample_and_appends_columns():
    out = add_history_features(sample_rows(), unit_log(), lookback=TWO_DAYS, error_types=("ce",))
    assert len(out) == 2
    assert out["event_count"].tolist() == [3, 1]  # (98d12, 100d12] holds only the 100d08 event
    assert list(out.columns[:4]) == ["sample_id", "unit_id", "prediction_time", "label"]


def test_appending_future_rows_does_not_change_an_earlier_sample():
    log = unit_log()
    before = add_history_features(sample_rows(), log, lookback=TWO_DAYS, error_types=("ce",))
    future = pd.concat(
        [log, log.assign(log_time=log["log_time"] + pd.Timedelta(days=8), rowid=999)],
        ignore_index=True,
    )
    after = add_history_features(sample_rows(), future, lookback=TWO_DAYS, error_types=("ce",))
    pd.testing.assert_frame_equal(before, after)


def test_a_sample_without_a_single_event_in_window_still_gets_a_row():
    samples = sample_rows().assign(prediction_time=day(150))
    out = add_history_features(samples, unit_log(), lookback=TWO_DAYS, error_types=("ce",))
    assert out["event_count"].tolist() == [0, 0]
    assert [pd.isna(value) for value in out["minutes_since_last_event"]] == [True, True]
    assert out["ce_count"].tolist() == [0, 0]


def test_a_sample_of_an_unknown_unit_gets_empty_windows_not_a_missing_row():
    samples = sample_rows().assign(unit_id=["unit-clean", "unit-never-seen"])
    out = add_history_features(samples, unit_log(), lookback=TWO_DAYS, error_types=("ce",))
    assert out["event_count"].tolist() == [3, 0]


def test_events_without_the_join_column_are_refused():
    with pytest.raises(SmartMemDataError, match="serial_number"):
        add_history_features(sample_rows(), CLEAN, lookback=TWO_DAYS, error_types=("ce",))


def test_groups_can_be_switched_off():
    narrow = add_history_features(
        sample_rows(),
        unit_log(),
        lookback=TWO_DAYS,
        error_types=("ce",),
        feature_groups=("intensity",),
    )
    assert "distinct_rowid" not in narrow.columns
    assert "event_count" in narrow.columns


def test_the_group_list_is_the_documented_families():
    assert FEATURE_GROUPS == (
        "intensity",
        "spatial",
        "error_type",
        "retry_parity",
        "static",
        "coverage",
    )


def test_an_unknown_group_name_is_refused():
    with pytest.raises(ValueError, match="feature_groups"):
        add_history_features(
            sample_rows(),
            unit_log(),
            lookback=TWO_DAYS,
            error_types=("ce",),
            feature_groups=("magic",),
        )


def test_assignment_is_blind_to_the_row_order_of_the_event_log():
    log = unit_log()
    shuffled = log.iloc[::-1].reset_index(drop=True)
    kwargs = {"lookback": TWO_DAYS, "error_types": ("ce",)}
    forward = add_history_features(sample_rows(), log, **kwargs)
    backward = add_history_features(sample_rows(), shuffled, **kwargs)
    pd.testing.assert_frame_equal(forward, backward)


# ---------------------------------------------------------------- the manifest


def _double_stored_log(unit: str = "unit-clean") -> pd.DataFrame:
    """One unit's log with the numeric statics stored as float64, the way a feather file does."""
    log = unit_log(unit).copy()
    for column in ("Capacity", "FrequencyMHz", "MaxSpeedMHz"):
        log[column] = pd.to_numeric(log[column]).astype("float64")
    log.loc[log.index[-1], "FrequencyMHz"] = float("nan")
    return log


def typed_features(log: pd.DataFrame) -> pd.DataFrame:
    return add_history_features(sample_rows(), log, lookback=TWO_DAYS, error_types=("ce",))


def test_a_double_stored_frequency_is_written_as_whole_mhz():
    """One value, one spelling: the stored dtype does not get to vote.

    A column holding ``4000.0`` because the file stored float64 renders differently from the same
    4000 read out of the sorted tree as text, so the same sample row leaves two different bytes on
    disk depending on which path fed it. Measured on 200 real units: 9 612 cells, 0 values changed.
    """
    out = typed_features(_double_stored_log())
    assert str(out["FrequencyMHz"].dtype) == "Int64"
    body = out[["Capacity", "FrequencyMHz", "MaxSpeedMHz"]].to_csv(index=False)
    assert "2666.0" not in body and "32768.0" not in body and "3200.0" not in body


def test_a_frequency_that_is_not_whole_mhz_is_refused_rather_than_truncated():
    log = _double_stored_log()
    log["FrequencyMHz"] = 2666.5
    with pytest.raises(SmartMemDataError, match="FrequencyMHz"):
        typed_features(log)


def test_a_capacity_spelled_with_a_unit_suffix_is_refused_not_dropped():
    """``errors="coerce"`` would quietly turn ``32GB`` into an empty cell; that is fabricated data."""
    log = _double_stored_log()
    log["Capacity"] = "32GB"
    with pytest.raises(SmartMemDataError, match="Capacity"):
        typed_features(log)


def test_a_rate_that_stops_reading_as_a_number_is_refused_not_emptied():
    """The one guard a float feature has: a text cell would otherwise vanish into an empty cell.

    A whole-number column gets a second chance - a value that does not read as a number is also a
    value that is not whole - so this case names a ``float64`` feature and holds the loss check alone.
    """
    out = typed_features(_double_stored_log())
    out["growth_rate"] = out["growth_rate"].astype("object")
    out.iloc[0, out.columns.get_loc("growth_rate")] = "n/a"
    with pytest.raises(SmartMemDataError, match="growth_rate"):
        canonicalize_feature_types(out)


def test_a_dtype_the_renderer_cannot_apply_stops_the_run():
    """A declared dtype this layer forgets to apply is how the next spelling drift arrives."""
    out = typed_features(_double_stored_log())
    with pytest.raises(SmartMemDataError, match="event_count"):
        canonicalize_feature_types(out, manifest={"event_count": {"dtype": "uint32"}})


@pytest.mark.parametrize("column", ["Capacity", "FrequencyMHz", "MaxSpeedMHz"])
def test_a_static_that_diverged_on_disk_declares_a_numeric_dtype(column: str):
    assert FEATURE_MANIFEST[column]["dtype"] == "int64"


@pytest.mark.parametrize("column", ["manufacturter", "model", "PN", "McaBank", "region"])
def test_a_static_that_holds_text_declares_a_string_dtype(column: str):
    assert FEATURE_MANIFEST[column]["dtype"] == "string"


def test_every_declared_feature_dtype_is_one_this_layer_applies():
    """No feature may declare a dtype and then be left to whatever the source file carried."""
    for name, entry in FEATURE_MANIFEST.items():
        assert entry["dtype"] in FEATURE_DTYPES, name



def test_every_emitted_feature_is_documented():
    out = add_history_features(
        sample_rows(), unit_log(), lookback=TWO_DAYS, error_types=("ce", "ue")
    )
    produced = [c for c in out.columns if c not in sample_rows().columns]
    per_error_type = {"ce_count", "ue_count"}
    assert set(produced) <= set(FEATURE_MANIFEST) | per_error_type
    for name, entry in FEATURE_MANIFEST.items():
        assert {"sources", "window", "dtype", "missing_rule", "group", "origin"} <= set(entry)
        assert entry["window"] in ("history", "history_tail"), name
        assert entry["sources"], name
        assert entry["group"] in FEATURE_GROUPS


def test_no_feature_reads_the_label_or_the_split():
    for entry in FEATURE_MANIFEST.values():
        assert "failure_time" not in entry["sources"]
        assert "label" not in entry["sources"]
        assert "split" not in entry["sources"]


# ------------------------------------------------- the declared error type domain


def type_columns(names: tuple[str, ...]) -> set[str]:
    """The per-type columns the builder itself writes for one declared domain."""
    out = feats(clean_history(), error_types=names, feature_groups=("error_type",))
    return {name for name in out if name.endswith("_count")} - {"unexpected_error_type_count"}


def test_the_domain_check_refuses_exactly_the_pairs_that_would_share_a_column():
    """Two spellings that reach one column are one refusal, and the column is the builder's own.

    Naming the columns here from ``history_features`` rather than from a rule written again is what
    makes the check mean something: a validator with its own slug rule would certify tables the
    builder never produces.
    """
    for pair in (("CE.READ", "CE_READ"), ("ce", "CE"), ("ue", "UE!")):
        assert len(type_columns(pair)) == 1, pair
        with pytest.raises(SmartMemDataError, match="both name the column"):
            declared_error_types(pair)
    for pair in (("CE.READ", "CE.SCRUB"), ("ce", "ue")):
        assert len(type_columns(pair)) == 2, pair
        assert declared_error_types(pair) == pair


def test_padding_is_not_part_of_a_declared_name():
    assert declared_error_types((" CE.READ ", "CE.SCRUB")) == ("CE.READ", "CE.SCRUB")


def test_an_empty_domain_is_refused_because_it_would_leave_no_trace():
    # these are the shapes a comma split leaves behind, e.g. ``--error-types ", ,"``
    for names in ((), ("",), (" ",), (" ", " "), ("", "")):
        with pytest.raises(SmartMemDataError, match="empty"):
            declared_error_types(names)


def test_the_observed_domain_is_counted_the_way_the_features_read_it():
    window = clean_history()
    assert error_type_counts(window) == {"ce": 3}
    blank = window.copy()
    blank.iloc[0, blank.columns.get_loc("error_type")] = None
    assert error_type_counts(blank) == {"ce": 2, "": 1}
    # the row counted under the empty name is the very row the features report as unexpected
    assert feats(blank, error_types=("ce",))["unexpected_error_type_count"] == 1


def test_a_table_without_an_error_type_column_is_named_rather_than_guessed():
    with pytest.raises(SmartMemDataError, match="error_type"):
        error_type_counts(clean_history().drop(columns=["error_type"]))
