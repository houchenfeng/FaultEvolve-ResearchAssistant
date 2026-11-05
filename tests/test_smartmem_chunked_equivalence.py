"""V1-06 (part 2c): a SmartMem unit file streamed in chunks must equal the same file read whole.

The generic layer proves rows survive a chunk boundary; this proves the *domain* survives one too -
the same normalisation policy, the same declared timezone, the same history features, for every
prediction time. That is the TODO's 分块/整块一致 requirement, and it is the claim that lets V1-07
stream a huge unit file instead of loading it.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from faultevolve.data.event_sampling import (
    EventWindowConfig,
    make_prediction_times,
    select_history,
)
from faultevolve.data.event_schema import normalize_events
from faultevolve.data.external_sort import MERGED_FILE_NAME, sort_file_to_time_order
from faultevolve.data.io import iter_event_windows, iter_file_chunks
from faultevolve.tasks.smartmem_data import (
    DEFAULT_ANCHOR_FREQUENCY,
    DEFAULT_HORIZON,
    DEFAULT_LEAD,
    MCELOG_EVENT_SCHEMA,
    SmartMemDataError,
    anonymize_unit,
    history_features,
    prepare_smartmem_chunk,
    read_smartmem_file,
    read_sorted_smartmem_file,
)

UNIT = "unit-stream-000007"
OTHER_UNIT = "unit-other-000011"
START = pd.Timestamp("2024-03-01 00:00:00", tz="UTC")
LOOKBACK = pd.Timedelta(days=5)
ERROR_TYPES = ("ce", "ue")
CONFIG = EventWindowConfig(
    lookback=LOOKBACK,
    lead=DEFAULT_LEAD,
    horizon=DEFAULT_HORIZON,
    anchor_frequency=DEFAULT_ANCHOR_FREQUENCY,
    anchor_strategy="event",
)

STATIC = {
    "manufacturter": "Micron",
    "model": "MTA36ASF4G72PZ",
    "PN": "MTA36ASF4G72PZ-3G2A1",
    "Capacity": "32GB",
    "FrequencyMHz": "3200",
    "MaxSpeedMHz": "3200",
    "McaBank": "3",
    "memory_type": "DDR4",
    "region": "cn-hangzhou",
}


def event_row(index: int, *, unit: str = UNIT, when: pd.Timestamp | None = None) -> dict:
    moment = START + index * pd.Timedelta(hours=2) if when is None else when
    return {
        "serial_number": unit,
        "log_time": moment,
        "cpuid": index % 2,
        "channelid": index % 4,
        "dimmid": 0,
        "rankid": index % 2,
        "deviceid": 1,
        "bankgroupid": 0,
        "bankid": 3,
        "rowid": 1000 + index % 7,
        "columnid": index % 11,
        "retryrderrlog": "" if index % 3 else "1",
        "retryrderrlogparity": "" if index % 5 else "1",
        "burst_info": "0x8" if index % 2 else "0x10",
        "error_type": "ce" if index % 4 else "ue",
        **STATIC,
    }


def dense_frame(rows: int, *, unit: str = UNIT) -> pd.DataFrame:
    return pd.DataFrame([event_row(index, unit=unit) for index in range(rows)])


def write_unit(tmp_path: Path, frame: pd.DataFrame, *, fmt: str = "csv") -> Path:
    """Write ``train/<unit>.<fmt>`` the way the observed export spells a per-unit file."""
    directory = tmp_path / "train"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{UNIT}.{fmt}"
    body = frame.copy()
    if fmt == "csv":
        body["log_time"] = body["log_time"].dt.strftime("%Y-%m-%dT%H:%M:%S+00:00")
        body.to_csv(path, index=False)
    else:
        body.to_feather(path)
    return path


def stream(path: Path, *, chunk_rows: int, fmt: str = "csv", **policy):
    """Stream one unit file with the domain's own normalisation as the per-chunk prepare step."""
    return iter_event_windows(
        path,
        fmt=fmt,
        chunk_rows=chunk_rows,
        time_column="log_time",
        lookback=LOOKBACK,
        prepare=lambda chunk: prepare_smartmem_chunk(chunk, unit=UNIT, **policy),
    )


def features_for(history: pd.DataFrame, moment: pd.Timestamp) -> dict[str, object]:
    return history_features(
        history, prediction_time=moment, lookback=LOOKBACK, error_types=ERROR_TYPES
    )


def whole_features(whole: pd.DataFrame) -> dict[pd.Timestamp, dict[str, object]]:
    return {
        moment: features_for(select_history(whole, moment, lookback=LOOKBACK), moment)
        for moment in make_prediction_times(whole, CONFIG)
    }


def served_by_window(
    path: Path, *, chunk_rows: int, fmt: str = "csv", dedup_window: bool = False, **policy
) -> dict:
    """Each prediction time is served by the first window whose boundary reaches it."""
    whole = read_smartmem_file(path, fmt=fmt, **policy)
    moments = list(make_prediction_times(whole, CONFIG))
    served: dict[pd.Timestamp, dict[str, object]] = {}
    for window in stream(path, chunk_rows=chunk_rows, fmt=fmt, **policy):
        rows = window.rows
        if dedup_window:
            rows = normalize_events(
                rows, MCELOG_EVENT_SCHEMA, timezone="UTC", duplicate_policy="drop_exact"
            )
        for moment in moments:
            if moment in served or moment > window.boundary:
                continue
            served[moment] = features_for(
                select_history(rows, moment, lookback=LOOKBACK), moment
            )
    return served


# --------------------------------------------------------------- one policy, two paths


def test_prepare_smartmem_chunk_is_the_normalisation_the_reader_applies(tmp_path):
    path = write_unit(tmp_path, dense_frame(30))
    raw = pd.read_csv(path, dtype=str, keep_default_na=False)
    prepared = prepare_smartmem_chunk(raw, unit=UNIT)
    pd.testing.assert_frame_equal(
        prepared.reset_index(drop=True), read_smartmem_file(path, fmt="csv")
    )


def test_a_chunk_carrying_a_second_unit_is_refused_without_naming_it(tmp_path):
    rows = dense_frame(4).to_dict("records")
    rows[2]["serial_number"] = OTHER_UNIT
    path = write_unit(tmp_path, pd.DataFrame(rows))
    raw = pd.read_csv(path, dtype=str, keep_default_na=False)
    with pytest.raises(SmartMemDataError, match="distinct") as caught:
        prepare_smartmem_chunk(raw, unit=UNIT)
    assert OTHER_UNIT not in str(caught.value)
    assert anonymize_unit(OTHER_UNIT) in str(caught.value)


def test_a_naive_time_column_needs_the_declared_timezone_in_both_paths(tmp_path):
    directory = tmp_path / "train"
    directory.mkdir(parents=True, exist_ok=True)
    body = dense_frame(12).copy()
    body["log_time"] = body["log_time"].dt.tz_localize(None).dt.strftime("%Y-%m-%dT%H:%M:%S")
    path = directory / f"{UNIT}.csv"
    path.write_text(body.to_csv(index=False), encoding="utf-8")
    raw = pd.read_csv(path, dtype=str, keep_default_na=False)
    with pytest.raises(SmartMemDataError, match="timezone"):
        prepare_smartmem_chunk(raw, unit=UNIT)
    shifted = prepare_smartmem_chunk(raw, unit=UNIT, timezone="Asia/Shanghai")
    assert shifted["log_time"].min() == START - pd.Timedelta(hours=8)
    with pytest.raises(SmartMemDataError, match="timezone"):
        read_smartmem_file(path, fmt="csv")


def test_the_unparsable_time_threshold_behaves_the_same_in_both_paths(tmp_path):
    body = dense_frame(8).copy()
    body["log_time"] = body["log_time"].dt.strftime("%Y-%m-%dT%H:%M:%S+00:00")
    body.loc[0, "log_time"] = "not a time"
    directory = tmp_path / "train"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{UNIT}.csv"
    path.write_text(body.to_csv(index=False), encoding="utf-8")
    raw = pd.read_csv(path, dtype=str, keep_default_na=False)
    with pytest.raises(SmartMemDataError, match="could not be parsed"):
        prepare_smartmem_chunk(raw, unit=UNIT)
    with pytest.raises(SmartMemDataError, match="could not be parsed"):
        read_smartmem_file(path, fmt="csv")
    report: dict[str, int] = {}
    allowed = prepare_smartmem_chunk(raw, unit=UNIT, max_unparsable_rows=1.0, report=report)
    assert len(allowed) == 7 and report["unparsable_time_rows"] == 1


# --------------------------------------------------------------- chunked == whole


@pytest.mark.parametrize("chunk_rows", [5, 9, 40])
def test_streamed_history_features_equal_the_whole_file_for_every_prediction_time(
    tmp_path, chunk_rows
):
    path = write_unit(tmp_path, dense_frame(60))
    expected = whole_features(read_smartmem_file(path, fmt="csv"))
    assert len(expected) > 20, "boundaries must fall inside a lookback for this to mean anything"
    assert served_by_window(path, chunk_rows=chunk_rows) == expected


def test_a_feather_unit_streams_to_the_same_features_as_the_csv_copy(tmp_path):
    csv_path = write_unit(tmp_path, dense_frame(40))
    feather_path = write_unit(tmp_path, dense_frame(40), fmt="feather")
    expected = whole_features(read_smartmem_file(csv_path, fmt="csv"))
    assert served_by_window(feather_path, chunk_rows=7, fmt="feather") == expected


def test_every_row_of_the_file_arrives_exactly_once_through_the_stream(tmp_path):
    path = write_unit(tmp_path, dense_frame(25))
    whole = read_smartmem_file(path, fmt="csv")
    streamed = pd.concat(
        [window.new_rows for window in stream(path, chunk_rows=4)], ignore_index=True
    )
    ordered = streamed.sort_values(["log_time", "columnid"], ignore_index=True)
    pd.testing.assert_frame_equal(
        ordered, whole.sort_values(["log_time", "columnid"], ignore_index=True)
    )


def test_the_stream_holds_no_more_rows_than_one_lookback_plus_a_chunk(tmp_path):
    path = write_unit(tmp_path, dense_frame(80))
    rows_per_lookback = int(LOOKBACK / pd.Timedelta(hours=2))
    for window in stream(path, chunk_rows=6):
        assert len(window.rows) <= rows_per_lookback + 6
        assert len(window.new_rows) <= 6


# --------------------------------------------------------------- the boundary hazard


def test_a_duplicate_split_across_chunks_is_caught_when_the_window_is_assembled(tmp_path):
    """Per-chunk dedup cannot see a duplicate that straddles the boundary, so the window has to.

    Exact duplicates share an instant, so every window that holds one holds both: dropping them on
    the assembled window is the same rule the whole-file reader applies. The test shows the hole,
    then shows the repair.
    """
    rows = dense_frame(9).to_dict("records")
    rows.insert(4, dict(rows[3]))
    path = write_unit(tmp_path, pd.DataFrame(rows))
    whole = read_smartmem_file(path, fmt="csv")
    assert len(whole) == 9

    chunks = [
        prepare_smartmem_chunk(chunk, unit=UNIT)
        for chunk in iter_file_chunks(path, chunk_rows=4)
    ]
    assert sum(len(chunk) for chunk in chunks) == 10, "the duplicate pair was split by a boundary"

    expected = whole_features(whole)
    doubled = served_by_window(path, chunk_rows=4)
    differs = [
        moment
        for moment in doubled
        if doubled[moment]["event_count"] != expected[moment]["event_count"]
    ]
    assert differs, "the streamed path should have counted the split duplicate twice"
    assert all(
        doubled[moment]["event_count"] == expected[moment]["event_count"] + 1
        for moment in differs
    )

    repaired = served_by_window(path, chunk_rows=4, dedup_window=True)
    assert repaired == expected


# ------------------------------------------------- V1-06 (part 2f): the sorted tree as an input


def sort_of(path: Path, out_dir: Path, *, chunk_rows: int | None = None) -> Path:
    """Sort one unit file into a workspace of its own and return the merged file it wrote."""
    extra = {} if chunk_rows is None else {"chunk_rows": chunk_rows}
    result = sort_file_to_time_order(
        path,
        out_dir=out_dir,
        time_column="log_time",
        fmt="csv",
        prepare=lambda chunk: prepare_smartmem_chunk(chunk, unit=UNIT),
        **extra,
    )
    return result.path


def test_a_sorted_tree_reads_back_as_the_same_rows_the_raw_file_gave(tmp_path):
    scrambled = [5, 0, 9, 1, 11, 3, 7, 2, 10, 4, 8, 6]
    path = write_unit(tmp_path, dense_frame(12).iloc[scrambled].reset_index(drop=True))
    times = [str(value) for value in pd.read_csv(path)["log_time"]]
    assert times != sorted(times), "the fixture row order is no longer scrambled"

    merged = sort_of(path, tmp_path / "ws")
    assert merged.name == MERGED_FILE_NAME
    assert read_sorted_smartmem_file(merged).equals(read_smartmem_file(path, fmt="csv"))


def test_the_reader_drops_a_duplicate_pair_the_sort_could_not_see(tmp_path):
    """One row per chunk means no chunk ever held both halves of a duplicate pair.

    The merged file therefore carries the pair twice - the hole the sort leaves by design - and
    reading the assembled file is where the whole-file rule applies again.
    """
    rows = dense_frame(6).to_dict("records")
    rows.insert(3, dict(rows[2]))
    path = write_unit(tmp_path, pd.DataFrame(rows))
    merged = sort_of(path, tmp_path / "ws", chunk_rows=1)
    assert len(pd.read_csv(merged)) == 7, "the split duplicate should have survived the sort"

    whole = read_smartmem_file(path, fmt="csv")
    assert len(whole) == 6
    assert read_sorted_smartmem_file(merged).equals(whole)


def test_the_reader_refuses_a_table_that_is_not_the_canonical_shape(tmp_path):
    path = tmp_path / MERGED_FILE_NAME
    path.write_text(
        "log_time,foo\n2024-03-01T00:00:00+00:00,1\n", encoding="utf-8", newline="\n"
    )
    with pytest.raises(SmartMemDataError, match="not a readable canonical event table"):
        read_sorted_smartmem_file(path)
