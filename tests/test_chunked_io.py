"""V1-06 (part 2a): bounded-chunk reading and the carry-over that keeps boundary windows whole.

A 130 GB unit file may not be loaded, so it is read in chunks - but a lookback window does not know
where a chunk ends. This layer therefore carries forward exactly the rows a later window can still
reach, and refuses a file whose chunks run backwards in time rather than silently dropping a window
that would have needed a row it had already let go.
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path
from typing import Callable, Iterator

import pandas as pd
import pytest

from faultevolve.data.event_sampling import select_history
from faultevolve.data.io import (
    DEFAULT_CHUNK_ROWS,
    EventWindow,
    IoError,
    carry_forward,
    iter_event_windows,
    iter_file_chunks,
)

TIME = "event_time"
LOOKBACK = pd.Timedelta(hours=6)
STEP = pd.Timedelta(minutes=20)


def utc(text: str) -> pd.Timestamp:
    return pd.Timestamp(text).tz_localize("UTC")


def frame(rows: list[tuple[str, str, int]]) -> pd.DataFrame:
    """(unit, timestamp, value) rows with a real datetime column, as a prepared frame looks."""
    return pd.DataFrame(
        {
            "unit_id": [unit for unit, _, _ in rows],
            TIME: [utc(stamp) for _, stamp, _ in rows],
            "value": [value for _, _, value in rows],
        }
    )


def make_rows(
    count: int,
    *,
    start: str = "2024-01-01 00:00",
    unit: str = "unit-a",
) -> list[tuple[str, str, int]]:
    first = utc(start)
    return [
        (unit, (first + STEP * offset).strftime("%Y-%m-%d %H:%M"), offset)
        for offset in range(count)
    ]


def prepare(chunk: pd.DataFrame) -> pd.DataFrame:
    """What a caller hands in: the time column becomes a tz-aware stamp, nothing else changes."""
    out = chunk.copy()
    out[TIME] = pd.to_datetime(out[TIME], utc=True, format="ISO8601")
    return out


def write_csv(
    tmp_path: Path,
    rows: list[tuple[str, str, int]],
    name: str = "unit-a.csv",
) -> Path:
    path = tmp_path / name
    frame(rows).to_csv(path, index=False)
    return path


def write_feather(
    tmp_path: Path,
    rows: list[tuple[str, str, int]],
    name: str = "unit-a.feather",
) -> Path:
    path = tmp_path / name
    frame(rows).to_feather(path)
    return path


def stream(
    path: Path,
    *,
    chunk_rows: int = 3,
    lookback: pd.Timedelta = LOOKBACK,
    fmt: str = "csv",
    transform: Callable[[pd.DataFrame], pd.DataFrame] | None = None,
) -> list[EventWindow]:
    return list(
        iter_event_windows(
            path,
            fmt=fmt,
            chunk_rows=chunk_rows,
            time_column=TIME,
            lookback=lookback,
            prepare=prepare if transform is None else transform,
        )
    )


def read_all(chunks: Iterator[pd.DataFrame]) -> list[pd.DataFrame]:
    return list(chunks)


def history_in(windows: list[EventWindow], prediction_time: pd.Timestamp) -> pd.DataFrame:
    """The first streamed window that reaches this prediction time, sliced like any window is."""
    reached = [window for window in windows if window.boundary >= prediction_time]
    assert reached, f"no streamed window reaches {prediction_time}"
    return select_history(reached[0].rows, prediction_time, lookback=LOOKBACK, time_col=TIME)


def values(rows: pd.DataFrame) -> list[str]:
    return [str(value) for value in rows["value"]]


# ------------------------------------------------------------------ bounded reads


def test_a_csv_is_read_in_bounded_chunks_that_together_hold_every_row(tmp_path):
    path = write_csv(tmp_path, make_rows(10))
    chunks = read_all(iter_file_chunks(path, fmt="csv", chunk_rows=3))
    assert [len(chunk) for chunk in chunks] == [3, 3, 3, 1]
    assert values(pd.concat(chunks, ignore_index=True)) == [str(n) for n in range(10)]


def test_a_chunk_never_splits_a_row(tmp_path):
    path = write_csv(tmp_path, make_rows(5))
    for chunk in iter_file_chunks(path, fmt="csv", chunk_rows=2):
        assert list(chunk.columns) == ["unit_id", TIME, "value"]
        assert chunk.notna().all().all()


def test_a_feather_file_streams_the_same_rows_as_a_whole_read(tmp_path):
    path = write_feather(tmp_path, make_rows(7))
    whole = pd.read_feather(path)
    chunks = read_all(iter_file_chunks(path, fmt="feather", chunk_rows=2))
    assert [len(chunk) for chunk in chunks] == [2, 2, 2, 1]
    streamed = pd.concat(chunks, ignore_index=True)
    assert values(streamed) == values(whole)
    assert [str(stamp) for stamp in streamed[TIME]] == [str(s) for s in whole[TIME]]


def test_the_default_chunk_size_is_a_positive_row_count():
    assert isinstance(DEFAULT_CHUNK_ROWS, int) and DEFAULT_CHUNK_ROWS > 0


def test_an_unknown_format_is_refused_before_anything_is_read(tmp_path):
    path = write_csv(tmp_path, make_rows(2))
    with pytest.raises(IoError, match="format"):
        read_all(iter_file_chunks(path, fmt="parquet"))


def test_a_chunk_size_that_is_not_positive_is_refused(tmp_path):
    path = write_csv(tmp_path, make_rows(2))
    with pytest.raises(IoError, match="chunk_rows"):
        read_all(iter_file_chunks(path, fmt="csv", chunk_rows=0))


def test_a_missing_file_is_refused_without_naming_it(tmp_path):
    write_csv(tmp_path, make_rows(2))
    with pytest.raises(IoError) as caught:
        read_all(iter_file_chunks(tmp_path / "unit-a.absent.csv", fmt="csv"))
    assert "unit-a" not in str(caught.value)


def test_an_empty_file_yields_no_chunks_and_no_windows(tmp_path):
    empty = tmp_path / "empty.csv"
    frame([]).to_csv(empty, index=False)
    assert read_all(iter_file_chunks(empty, fmt="csv")) == []
    assert stream(empty) == []


# ------------------------------------------------------------------ carry forward


def test_carry_forward_keeps_exactly_the_rows_a_later_window_can_reach():
    rows = frame(make_rows(8))  # 00:00 .. 02:20 at 20-minute spacing
    boundary = utc("2024-01-01 02:20")
    carried = carry_forward(
        rows, boundary=boundary, lookback=pd.Timedelta(hours=1), time_column=TIME
    )
    assert values(carried) == ["5", "6", "7"]
    assert list(carried[TIME]) == [utc("2024-01-01 01:40"), utc("2024-01-01 02:00"), boundary]


def test_carry_forward_drops_rows_no_later_window_can_reach():
    rows = frame(make_rows(40))  # 00:00 .. 13:00, so a 6-hour lookback spans 07:00 onward
    boundary = rows[TIME].max()
    carried = carry_forward(rows, boundary=boundary, lookback=LOOKBACK, time_column=TIME)
    assert len(carried) == 18
    assert values(carried) == [str(n) for n in range(22, 40)]


def test_carry_forward_refuses_a_naive_boundary():
    rows = frame(make_rows(2))
    with pytest.raises(IoError, match="timezone"):
        carry_forward(
            rows,
            boundary=pd.Timestamp("2024-01-01 01:00"),
            lookback=LOOKBACK,
            time_column=TIME,
        )


def test_carry_forward_refuses_a_zero_lookback():
    rows = frame(make_rows(2))
    with pytest.raises(IoError, match="lookback"):
        carry_forward(
            rows,
            boundary=utc("2024-01-01 01:00"),
            lookback=pd.Timedelta(0),
            time_column=TIME,
        )


def test_carry_forward_refuses_a_missing_time_column():
    rows = frame(make_rows(2))
    # the message names the column that was asked for, which is schema vocabulary, not an identity
    with pytest.raises(IoError, match="log_time"):
        carry_forward(
            rows,
            boundary=utc("2024-01-01 01:00"),
            lookback=LOOKBACK,
            time_column="log_time",
        )


# ------------------------------------------------------------------ stream windows


def test_windows_cover_every_row_exactly_once_as_a_new_row(tmp_path):
    path = write_csv(tmp_path, make_rows(9))
    windows = stream(path, chunk_rows=3)
    assert [window.index for window in windows] == [0, 1, 2]
    fresh = pd.concat([window.new_rows for window in windows], ignore_index=True)
    assert values(fresh) == [str(n) for n in range(9)]


def test_a_window_that_straddles_a_chunk_boundary_sees_the_same_history(tmp_path):
    rows = make_rows(12)
    whole = frame(rows)
    windows = stream(write_csv(tmp_path, rows), chunk_rows=3)
    for prediction_time in whole[TIME][::2]:
        streamed = values(history_in(windows, prediction_time))
        expected = values(select_history(whole, prediction_time, lookback=LOOKBACK, time_col=TIME))
        assert streamed == expected


def test_the_history_a_window_reaches_never_shrinks_with_chunk_size(tmp_path):
    rows = make_rows(12)
    path = write_csv(tmp_path, rows)
    whole = frame(rows)
    for chunk_rows in (1, 2, 3, 5, 12):
        windows = stream(path, chunk_rows=chunk_rows)
        for prediction_time in whole[TIME]:
            streamed = values(history_in(windows, prediction_time))
            expected = values(
                select_history(whole, prediction_time, lookback=LOOKBACK, time_col=TIME)
            )
            assert streamed == expected, (chunk_rows, prediction_time)


def test_carried_rows_stay_bounded_by_the_lookback(tmp_path):
    path = write_csv(tmp_path, make_rows(30))
    for window in stream(path, chunk_rows=4):
        assert window.carry_count + len(window.new_rows) == len(window.rows)
        # a 6-hour lookback at 20-minute spacing reaches at most 18 earlier rows
        assert window.carry_count <= 18
        assert window.rows[TIME].is_monotonic_increasing


def test_a_file_whose_chunks_run_backwards_in_time_is_refused(tmp_path):
    rows = make_rows(9)
    scrambled = rows[:3] + rows[6:] + rows[3:6]
    with pytest.raises(IoError, match="(?i)sort"):
        stream(write_csv(tmp_path, scrambled), chunk_rows=3)


def test_rows_unordered_within_a_chunk_are_still_carried_forward(tmp_path):
    rows = make_rows(6)
    swapped = [rows[1], rows[0], rows[2], rows[4], rows[3], rows[5]]
    whole = frame(rows)
    windows = stream(write_csv(tmp_path, swapped), chunk_rows=3)
    for prediction_time in whole[TIME]:
        streamed = values(history_in(windows, prediction_time))
        expected = values(select_history(whole, prediction_time, lookback=LOOKBACK, time_col=TIME))
        assert streamed == expected


def test_a_prepared_frame_without_the_time_column_is_refused(tmp_path):
    path = write_csv(tmp_path, make_rows(3))

    def forget_time(chunk: pd.DataFrame) -> pd.DataFrame:
        return chunk.drop(columns=[TIME])

    with pytest.raises(IoError, match="event_time"):
        stream(path, transform=forget_time)


def test_a_prepared_frame_with_naive_stamps_is_refused(tmp_path):
    path = write_csv(tmp_path, make_rows(3))

    def keep_them_local(chunk: pd.DataFrame) -> pd.DataFrame:
        out = chunk.copy()
        # The file was written with an offset, so dropping the tz has to be stated explicitly:
        # this is the frame a caller would hand over after reading a naive local-time column.
        out[TIME] = pd.to_datetime(out[TIME]).dt.tz_localize(None)
        return out

    with pytest.raises(IoError, match="timezone"):
        stream(path, transform=keep_them_local)


def test_a_feather_file_streams_the_same_windows_as_the_csv_of_the_same_rows(tmp_path):
    rows = make_rows(10)
    as_csv = stream(write_csv(tmp_path, rows, name="unit-a.csv"), chunk_rows=3)
    as_feather = stream(
        write_feather(tmp_path, rows, name="unit-a.feather"), chunk_rows=3, fmt="feather"
    )
    assert [window.boundary for window in as_csv] == [window.boundary for window in as_feather]
    assert [len(window.rows) for window in as_csv] == [len(window.rows) for window in as_feather]


def test_no_chunk_or_window_holds_more_rows_than_the_bound_allows(tmp_path):
    path = write_csv(tmp_path, make_rows(200))
    sizes = [len(chunk) for chunk in iter_file_chunks(path, chunk_rows=7)]
    assert max(sizes) == 7 and len(sizes) == 29
    for window in stream(path, chunk_rows=7, lookback=pd.Timedelta(hours=1)):
        # a one-hour lookback reaches at most three earlier rows, so a window holds 7 + 3 at most
        assert len(window.rows) <= 10
    assert inspect.isgenerator(iter_file_chunks(path, chunk_rows=7))


def test_each_row_is_normalised_exactly_once(tmp_path):
    path = write_csv(tmp_path, make_rows(9))
    seen: list[int] = []

    def count(chunk: pd.DataFrame) -> pd.DataFrame:
        seen.append(len(chunk))
        return prepare(chunk)

    windows = list(
        iter_event_windows(
            path, chunk_rows=3, time_column=TIME, lookback=LOOKBACK, prepare=count
        )
    )
    assert len(windows) == 3
    assert seen == [3, 3, 3], "a carried row must not be prepared a second time"


def test_the_consumer_pulls_one_chunk_at_a_time(tmp_path, monkeypatch):
    """The stream must not drain the reader before handing over the first window.

    The only honest way to see a read is to stand in the reader's shoes, so pandas' chunked CSV
    reader is replaced with a generator that records each chunk as it is produced.
    """
    path = write_csv(tmp_path, make_rows(9))
    produced: list[int] = []
    chunks = [
        frame(make_rows(3, start=f"2024-01-01 {hour:02d}:00")) for hour in (0, 1, 2)
    ]

    def watching(*args, **kwargs):
        assert kwargs.get("chunksize"), "the file must be opened for chunked reading"

        def generate():
            for position, chunk in enumerate(chunks):
                produced.append(position)
                yield chunk

        return generate()

    monkeypatch.setattr("faultevolve.data.io.pd.read_csv", watching)
    generator = iter_event_windows(
        path, chunk_rows=3, time_column=TIME, lookback=LOOKBACK, prepare=None
    )
    first = next(generator)
    assert produced == [0], "the first window must not have read the whole file"
    assert first.index == 0
    for _ in generator:
        pass
    assert produced == [0, 1, 2]


# ------------------------------------------------------------------ vocabulary guard


def test_the_io_layer_carries_no_domain_vocabulary():
    root = Path(__file__).resolve().parents[1] / "src" / "faultevolve" / "data"
    source = (root / "io.py").read_text(encoding="utf-8")
    banned = re.findall(r"\b(DIMM|mcelog|ECC|UE|bankid|SmartMem)\b", source, re.IGNORECASE)
    assert banned == [], f"io.py leaked domain vocabulary: {banned}"
