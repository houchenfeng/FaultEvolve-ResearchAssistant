"""V1-03: prediction times, labels and censoring are derived without reading the answer.

Every boundary in the requirement table is pinned to the nanosecond, and the anchor trap
proves that a 10:07 event can only be used by a prediction time of 10:15.
"""

from __future__ import annotations

import inspect
import os
import re
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

from faultevolve.data.event_schema import CanonicalEventSchema
from faultevolve.data.event_sampling import (
    SAMPLER_VERSION,
    EventWindowConfig,
    SamplingError,
    build_labeled_samples,
    censor_at_time,
    label_at_time,
    make_prediction_times,
    make_sample_id,
    select_history,
)

UTC = "UTC"
T0 = pd.Timestamp("2024-03-01 00:00:00", tz=UTC)
FIFTEEN = pd.Timedelta(minutes=15)
NANO = pd.Timedelta(1)
WEEK = pd.Timedelta(days=7)
FIVEDAYS = pd.Timedelta(days=5)

SCHEMA = CanonicalEventSchema(
    unit_col="unit_id",
    time_col="log_time",
    event_type_col="error_type",
    numeric_cols=("row_id",),
)
REQUIRED_COLUMNS = (
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


def config(**overrides) -> EventWindowConfig:
    base = dict(
        lookback=FIVEDAYS,
        lead=FIFTEEN,
        horizon=WEEK,
        anchor_frequency=FIFTEEN,
        anchor_strategy="event",
        max_samples_per_unit=None,
        seed=0,
    )
    base.update(overrides)
    return EventWindowConfig(**base)


def events(rows: list[tuple[str, pd.Timestamp, int]]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "unit_id": [r[0] for r in rows],
            "log_time": pd.DatetimeIndex([r[1] for r in rows]),
            "error_type": ["read" for _ in rows],
            "row_id": [r[2] for r in rows],
        }
    )


def failures(rows: list[tuple[str, pd.Timestamp]]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "unit_id": [r[0] for r in rows],
            "failure_time": pd.DatetimeIndex([r[1] for r in rows]),
        }
    )


def build(ev: pd.DataFrame, tickets: pd.DataFrame, cfg: EventWindowConfig, until, **kw):
    return build_labeled_samples(
        ev,
        tickets,
        SCHEMA,
        cfg,
        failure_unit_col="unit_id",
        failure_time_col="failure_time",
        outcome_observed_until=until,
        **kw,
    )


# ---------------------------------------------------------------- config validation


@pytest.mark.parametrize("field", ["lookback", "lead", "horizon", "anchor_frequency"])
def test_non_positive_windows_are_rejected(field):
    with pytest.raises(SamplingError, match=field):
        config(**{field: pd.Timedelta(seconds=-1)})


def test_zero_anchor_frequency_is_rejected():
    with pytest.raises(SamplingError, match="anchor_frequency"):
        config(anchor_frequency=pd.Timedelta(0))


def test_unknown_anchor_strategy_is_rejected():
    with pytest.raises(SamplingError, match="anchor_strategy"):
        config(anchor_strategy="label")


def test_max_samples_must_be_positive_or_none():
    with pytest.raises(SamplingError, match="max_samples_per_unit"):
        config(max_samples_per_unit=0)
    assert config(max_samples_per_unit=None).max_samples_per_unit is None


# ---------------------------------------------------------------- anchor generation


def test_event_anchor_ceils_within_the_bucket_never_floors():
    """The 10:07 trap: 15-minute buckets must yield 10:15, never 10:00."""
    ts = pd.Timestamp("2024-03-01 10:07:00", tz=UTC)
    times = make_prediction_times(events([("u-a", ts, 1)]), config())
    assert list(times) == [pd.Timestamp("2024-03-01 10:15:00", tz=UTC)]


def test_event_anchor_on_an_exact_multiple_stays_there():
    ts = pd.Timestamp("2024-03-01 10:15:00", tz=UTC)
    times = make_prediction_times(events([("u-a", ts, 1)]), config())
    assert list(times) == [ts]


def test_event_anchor_dedupes_within_a_bucket():
    rows = [
        ("u-a", pd.Timestamp("2024-03-01 10:01:00", tz=UTC), 1),
        ("u-a", pd.Timestamp("2024-03-01 10:07:00", tz=UTC), 2),
        ("u-a", pd.Timestamp("2024-03-01 10:20:00", tz=UTC), 3),
    ]
    times = make_prediction_times(events(rows), config())
    assert list(times) == [
        pd.Timestamp("2024-03-01 10:15:00", tz=UTC),
        pd.Timestamp("2024-03-01 10:30:00", tz=UTC),
    ]


def test_event_anchor_is_monotonic_across_units():
    rows = [
        ("u-a", pd.Timestamp("2024-03-01 10:07:00", tz=UTC), 1),
        ("u-b", pd.Timestamp("2024-03-01 09:00:00", tz=UTC), 2),
    ]
    times = make_prediction_times(events(rows), config())
    assert times.is_monotonic_increasing


def test_grid_anchor_covers_the_span_on_the_frequency():
    rows = [
        ("u-a", pd.Timestamp("2024-03-01 10:07:00", tz=UTC), 1),
        ("u-a", pd.Timestamp("2024-03-01 10:40:00", tz=UTC), 2),
    ]
    times = make_prediction_times(events(rows), config(anchor_strategy="grid"))
    assert times[0] == pd.Timestamp("2024-03-01 10:00:00", tz=UTC)
    assert times[-1] == pd.Timestamp("2024-03-01 10:45:00", tz=UTC)
    assert (times.to_series().diff().dropna() == FIFTEEN).all()


def test_hybrid_anchor_is_the_sorted_union_of_both():
    rows = [
        ("u-a", pd.Timestamp("2024-03-01 10:07:00", tz=UTC), 1),
        ("u-a", pd.Timestamp("2024-03-01 10:40:00", tz=UTC), 2),
    ]
    ev = events(rows)
    hybrid = make_prediction_times(ev, config(anchor_strategy="hybrid"))
    grid = make_prediction_times(ev, config(anchor_strategy="grid"))
    event = make_prediction_times(ev, config(anchor_strategy="event"))
    assert hybrid.tolist() == sorted(set(grid) | set(event))
    assert len(hybrid) == len(set(hybrid))


def test_anchor_generation_never_inspects_failures():
    assert "failure" not in inspect.signature(make_prediction_times).parameters


# ---------------------------------------------------------------- history selection


def test_history_interval_excludes_left_endpoint_and_includes_right():
    t = pd.Timestamp("2024-03-06 12:00:00", tz=UTC)
    rows = [
        ("u-a", t - FIVEDAYS, 1),
        ("u-a", t - FIVEDAYS + NANO, 2),
        ("u-a", t, 3),
        ("u-a", t + NANO, 4),
    ]
    hist = select_history(events(rows), t, lookback=FIVEDAYS)
    assert hist["row_id"].tolist() == [2, 3]


def test_history_of_the_ceiled_anchor_holds_the_original_event():
    ev = events([("u-a", pd.Timestamp("2024-03-01 10:07:00", tz=UTC), 1)])
    anchor = pd.Timestamp("2024-03-01 10:15:00", tz=UTC)
    assert len(select_history(ev, anchor, lookback=FIVEDAYS)) == 1
    earlier = pd.Timestamp("2024-03-01 10:00:00", tz=UTC)
    assert len(select_history(ev, earlier, lookback=FIVEDAYS)) == 0


# ---------------------------------------------------------------- label boundaries


@pytest.mark.parametrize(
    "offset, expected",
    [
        (pd.Timedelta(-1), "post_failure"),
        (pd.Timedelta(0), "post_failure"),
        (FIFTEEN - NANO, "insufficient_lead"),
        (FIFTEEN, "positive"),
        (FIFTEEN + WEEK, "positive"),
        (FIFTEEN + WEEK + NANO, "negative"),
    ],
)
def test_label_at_time_matches_the_requirement_boundary_table(offset, expected):
    t = pd.Timestamp("2024-03-01 12:00:00", tz=UTC)
    assert label_at_time(t, t + offset, lead=FIFTEEN, horizon=WEEK) == expected


def test_label_at_time_without_a_ticket_defers_to_censoring():
    t = pd.Timestamp("2024-03-01 12:00:00", tz=UTC)
    assert label_at_time(t, None, lead=FIFTEEN, horizon=WEEK) == "unknown"


def test_label_at_time_rejects_naive_times():
    with pytest.raises(SamplingError, match="timezone"):
        label_at_time(pd.Timestamp("2024-03-01 12:00:00"), T0 + FIFTEEN, lead=FIFTEEN, horizon=WEEK)


# ---------------------------------------------------------------- censoring


def test_negative_is_kept_only_when_follow_up_reaches_the_label_window_end():
    t = pd.Timestamp("2024-03-01 12:00:00", tz=UTC)
    end = t + FIFTEEN + WEEK
    assert censor_at_time(t, lead=FIFTEEN, horizon=WEEK, outcome_observed_until=end) == "keep"
    assert (
        censor_at_time(t, lead=FIFTEEN, horizon=WEEK, outcome_observed_until=end - NANO)
        == "censored"
    )


def test_confirmed_positive_is_never_censored():
    t = pd.Timestamp("2024-03-01 12:00:00", tz=UTC)
    assert (
        censor_at_time(
            t, lead=FIFTEEN, horizon=WEEK, outcome_observed_until=t, is_confirmed_positive=True
        )
        == "keep"
    )


# ---------------------------------------------------------------- sample id


def test_sample_id_is_stable_and_version_prefixed():
    t = pd.Timestamp("2024-03-01 10:15:00", tz=UTC)
    assert make_sample_id("unit-a", t) == make_sample_id("unit-a", t)
    assert re.fullmatch(rf"{SAMPLER_VERSION}-[0-9a-f]{{32}}", make_sample_id("unit-a", t))


def test_sample_id_separates_unit_and_time():
    t = pd.Timestamp("2024-03-01 10:15:00", tz=UTC)
    assert make_sample_id("unit-a", t) != make_sample_id("unit-b", t)
    assert make_sample_id("unit-a", t) != make_sample_id("unit-a", t + NANO)


def test_sample_id_changes_with_the_algorithm_version():
    assert make_sample_id("unit-a", T0) != make_sample_id("unit-a", T0, version="evs-v2")


def test_sample_id_rejects_a_naive_instant():
    with pytest.raises(SamplingError, match="timezone"):
        make_sample_id("unit-a", pd.Timestamp("2024-03-01 10:15:00"))


def test_sample_id_survives_a_fresh_interpreter_with_another_hash_seed():
    """Proves the id is sha256 of an explicit payload, not Python's randomised hash()."""
    expected = make_sample_id("unit-a", T0)
    code = (
        "import pandas as pd\n"
        "from faultevolve.data.event_sampling import make_sample_id\n"
        "print(make_sample_id('unit-a', pd.Timestamp('2024-03-01 00:00:00', tz='UTC')))\n"
    )
    env = dict(os.environ, PYTHONHASHSEED="1")
    done = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, env=env, check=True
    )
    assert done.stdout.strip().splitlines()[-1] == expected


# ---------------------------------------------------------------- build_labeled_samples


def test_output_carries_the_required_columns_and_no_naive_labels():
    t = pd.Timestamp("2024-03-01 10:15:00", tz=UTC)
    out = build(events([("u-a", t, 1)]), failures([("u-a", t + FIFTEEN + WEEK)]), config(), t + pd.Timedelta(days=30))
    for column in REQUIRED_COLUMNS:
        assert column in out.columns
    assert out["label"].tolist() == [1]
    assert out["split_key"].isna().all()
    assert (out["history_end"] <= out["prediction_time"]).all()


def test_post_failure_events_cannot_seed_anchors():
    """Events logged after the first failure must not create prediction times."""
    failure = pd.Timestamp("2024-03-05 12:00:00", tz=UTC)
    ev = events(
        [
            ("u-a", failure - pd.Timedelta(minutes=20), 1),
            ("u-a", failure + pd.Timedelta(hours=5), 2),
            ("u-a", failure + pd.Timedelta(days=2), 3),
        ]
    )
    out = build(ev, failures([("u-a", failure)]), config(), failure + pd.Timedelta(days=30))
    assert not out.empty
    assert (out["prediction_time"] < failure).all()
    assert (out["history_end"] < failure).all()


def test_unit_without_ticket_is_kept_only_inside_observed_coverage():
    ev = events(
        [
            ("u-a", pd.Timestamp("2024-03-01 10:00:00", tz=UTC), 1),
            ("u-a", pd.Timestamp("2024-06-01 10:00:00", tz=UTC), 2),
        ]
    )
    cutoff = pd.Timestamp("2024-03-08 10:15:00", tz=UTC)
    out = build(ev, failures([]), config(), cutoff)
    assert len(out) == 1
    assert out["prediction_time"].iloc[0] == pd.Timestamp("2024-03-01 10:00:00", tz=UTC)
    assert out["label"].iloc[0] == 0


def test_drop_reason_counts_are_reported_without_raw_rows():
    failure = pd.Timestamp("2024-03-05 12:07:00", tz=UTC)
    ev = events(
        [
            ("u-a", failure - pd.Timedelta(minutes=12), 1),  # anchors 12:00, lead too short
            ("u-a", failure - pd.Timedelta(minutes=2), 2),  # anchors 12:15, after the failure
            ("u-a", failure + pd.Timedelta(hours=3), 3),  # dropped as a post-failure event
            ("u-b", failure + pd.Timedelta(hours=3), 4),  # unit left without any event
        ]
    )
    report: dict[str, int] = {}
    out = build(
        ev,
        failures([("u-a", failure), ("u-b", failure)]),
        config(),
        failure + pd.Timedelta(days=30),
        report=report,
    )
    assert out.empty
    assert report["insufficient_lead"] == 1
    assert report["post_failure"] == 1
    assert report["post_failure_event"] == 2
    assert report["no_history_candidate"] == 1
    joined = " ".join(report)
    assert "u-a" not in joined and str(int(failure.timestamp())) not in joined


def test_empty_history_is_dropped_and_counted():
    ev = events(
        [
            ("u-a", pd.Timestamp("2024-03-01 10:00:00", tz=UTC), 1),
            ("u-a", pd.Timestamp("2024-03-01 10:40:00", tz=UTC), 2),
        ]
    )
    report: dict[str, int] = {}
    out = build(
        ev,
        failures([]),
        config(anchor_strategy="grid", lookback=pd.Timedelta(minutes=1)),
        pd.Timestamp("2024-03-31 00:00:00", tz=UTC),
        report=report,
    )
    assert len(out) == 1  # a one-minute lookback only sees the 10:00 event, at anchor 10:00
    assert report["empty_history"] == 3


def test_max_samples_per_unit_is_deterministic_and_label_blind():
    rows = [
        ("u-a", pd.Timestamp("2024-03-01 10:00:00", tz=UTC) + pd.Timedelta(minutes=15 * i), i)
        for i in range(10)
    ]
    ev = events(rows)
    tickets = failures([("u-a", pd.Timestamp("2024-03-01 13:00:00", tz=UTC))])
    until = pd.Timestamp("2024-03-31 00:00:00", tz=UTC)
    capped = build(ev, tickets, config(max_samples_per_unit=4, seed=7), until)
    again = build(ev, tickets, config(max_samples_per_unit=4, seed=7), until)
    assert capped["prediction_time"].tolist() == again["prediction_time"].tolist()
    assert len(capped) == 4
    full = build(ev, tickets, config(), until)
    assert len(full) == 10
    assert set(capped["prediction_time"]) <= set(full["prediction_time"])


def test_numeric_failure_times_are_refused_not_guessed():
    frame = pd.DataFrame({"unit_id": ["u-a"], "failure_time": [1709294400]})
    with pytest.raises(SamplingError, match="timezone|epoch"):
        build(events([("u-a", T0, 1)]), frame, config(), T0 + pd.Timedelta(days=30))


def test_duplicate_tickets_for_one_unit_use_the_first_failure():
    failure = pd.Timestamp("2024-03-02 00:00:00", tz=UTC)
    ev = events([("u-a", failure - FIFTEEN - WEEK, 1)])
    dupes = pd.DataFrame(
        {
            "unit_id": ["u-a", "u-a"],
            "failure_time": [failure, failure + pd.Timedelta(days=40)],
        }
    )
    out = build(ev, dupes, config(), failure + pd.Timedelta(days=30))
    assert out["label"].tolist() == [1]


def test_generic_layer_stays_domain_free():
    source = (
        Path(__file__).resolve().parents[1] / "src" / "faultevolve" / "data" / "event_sampling.py"
    ).read_text(encoding="utf-8")
    assert re.findall(r"\b(DIMM|mcelog|ECC|UE|bankid|SmartMem)\b", source, re.IGNORECASE) == []


# ---------------------------------------------------------------- L0 fixture integration


def fixture_events_frame() -> pd.DataFrame:
    from helpers_smartmem import EVENTS_BY_UNIT

    frames = []
    for unit, frame in EVENTS_BY_UNIT.items():
        piece = frame.copy()
        piece.insert(0, "unit_id", unit)
        frames.append(piece[["unit_id", "log_time", "error_type", "rowid"]])
    return pd.concat(frames, ignore_index=True)


def fixture_failures_frame() -> pd.DataFrame:
    from helpers_smartmem import FAILURE_TIME_BY_UNIT

    units = sorted(FAILURE_TIME_BY_UNIT)
    return pd.DataFrame(
        {
            "unit_id": units,
            "failure_time": pd.DatetimeIndex([FAILURE_TIME_BY_UNIT[u] for u in units]),
        }
    )


FIXTURE_SCHEMA = CanonicalEventSchema(
    unit_col="unit_id",
    time_col="log_time",
    event_type_col="error_type",
    numeric_cols=("rowid",),
)


@pytest.mark.parametrize(
    "unit, expected",
    [
        ("unit-lead-hit", "positive"),
        ("unit-horizon-hit", "positive"),
        ("unit-lead-miss", "insufficient_lead"),
        ("unit-horizon-miss", "negative"),
        ("unit-followup-short", "unknown"),
    ],
)
def test_the_designed_fixture_anchors_get_their_hand_computed_decision(unit, expected):
    """V1-01 pinned these anchors on paper; the sampler must reach the same decision."""
    from helpers_smartmem import ANCHORS, FAILURE_TIME_BY_UNIT

    anchor = ANCHORS[unit]
    failure = FAILURE_TIME_BY_UNIT.get(unit)
    assert label_at_time(anchor, failure, lead=FIFTEEN, horizon=WEEK) == expected


def test_the_short_follow_up_anchor_is_the_one_sample_censoring_removes():
    from helpers_smartmem import ANCHORS, OUTCOME_OBSERVED_UNTIL

    anchor = ANCHORS["unit-followup-short"]
    assert (
        censor_at_time(
            anchor, lead=FIFTEEN, horizon=WEEK, outcome_observed_until=OUTCOME_OBSERVED_UNTIL
        )
        == "censored"
    )
    earlier = anchor - FIFTEEN - WEEK  # follow-up complete by exactly one day
    assert (
        censor_at_time(
            earlier, lead=FIFTEEN, horizon=WEEK, outcome_observed_until=OUTCOME_OBSERVED_UNTIL
        )
        == "keep"
    )


def test_fixture_units_never_reference_their_own_post_failure_events():
    from helpers_smartmem import FAILURE_TIME_BY_UNIT, OUTCOME_OBSERVED_UNTIL

    out = build(
        fixture_events_frame(),
        fixture_failures_frame(),
        config(),
        OUTCOME_OBSERVED_UNTIL,
    )
    assert not out.empty
    for unit, failure in FAILURE_TIME_BY_UNIT.items():
        rows = out[out["unit_id"] == unit]
        assert (rows["history_end"] < failure).all(), unit
        assert (rows["prediction_time"] < failure).all(), unit


def test_fixture_clean_unit_keeps_only_fully_observed_negatives():
    from helpers_smartmem import OUTCOME_OBSERVED_UNTIL

    ev = fixture_events_frame()
    out = build(
        ev[ev["unit_id"] == "unit-clean"],
        fixture_failures_frame(),
        config(),
        OUTCOME_OBSERVED_UNTIL,
    )
    cutoff = OUTCOME_OBSERVED_UNTIL - FIFTEEN - WEEK
    assert out["label"].tolist() == [0, 0, 0], [str(x) for x in out["prediction_time"]]
    assert (out["prediction_time"] <= cutoff).all()


def test_whole_fixture_keeps_window_arithmetic_and_unique_ids():
    from helpers_smartmem import OUTCOME_OBSERVED_UNTIL

    out = build(
        fixture_events_frame(),
        fixture_failures_frame(),
        config(anchor_strategy="hybrid"),
        OUTCOME_OBSERVED_UNTIL,
    )
    assert not out.empty
    assert (out["history_end"] <= out["prediction_time"]).all()
    assert (out["history_start"] == out["prediction_time"] - FIVEDAYS).all()
    assert (out["label_window_start"] == out["prediction_time"] + FIFTEEN).all()
    assert (out["label_window_end"] == out["label_window_start"] + WEEK).all()
    assert out["sample_id"].is_unique
    assert set(out["label"]) <= {0, 1}
