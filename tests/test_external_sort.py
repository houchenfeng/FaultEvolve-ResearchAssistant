"""V1-06 (part 2d): sorting an out-of-order unit file without loading it.

The streaming reader refuses a file whose chunks run backwards in time, because a carried window
only reaches back one lookback. The refusal is correct but it is not a workaround: a real unit file
arrives out of order, so it has to become time-ordered first, and a 40-130 GB file may not be sorted
in memory. This module is the external sort that does it - bounded split runs, a k-way merge, a
runtime directory it owns, and a space report that fires before the first byte is written rather
than after the disk is full.

Two properties carry the whole step and each gets a test that can bite: the result must equal what a
stable in-memory sort produces (so ties keep file order, chunk after chunk), and no step may hold
more rows than its bound allows.
"""

from __future__ import annotations

import json
import math
import re
import shutil
from pathlib import Path
from typing import Callable

import pandas as pd
import pytest

from faultevolve.data import external_sort as es
from faultevolve.data.external_sort import (
    MERGED_FILE_NAME,
    RUNS_DIR_NAME,
    SEQUENCE_COLUMN,
    SORT_SIDECAR_NAME,
    SORT_VERSION,
    SortError,
    SpaceReport,
    estimate_space_bytes,
    sort_file_to_time_order,
    space_report,
)
from faultevolve.data.io import IoError, iter_event_windows

TIME = "event_time"
STEP = pd.Timedelta(minutes=1)


def utc(text: str) -> pd.Timestamp:
    return pd.Timestamp(text).tz_localize("UTC")


def timed_rows(count: int, *, start: str = "2024-01-01 00:00") -> list[tuple[str, int]]:
    """(timestamp, original row number) pairs, strictly increasing in time."""
    first = utc(start)
    return [
        ((first + STEP * offset).strftime("%Y-%m-%d %H:%M"), offset) for offset in range(count)
    ]


def shuffled(rows: list[tuple[str, int]], *, seed: int = 7) -> list[tuple[str, int]]:
    order = list(range(len(rows)))
    rng = __import__("random").Random(seed)
    rng.shuffle(order)
    return [rows[index] for index in order]


def block_reversed(rows: list[tuple[str, int]], *, blocks: int) -> list[tuple[str, int]]:
    """Blocks written back-to-front: every chunk starts before the previous one ended.

    A shuffled file only trips the streaming reader by luck of its chunk boundaries; reversed blocks
    aligned to the chunk size trip it by construction, which is what makes the refusal testable.
    """
    size = -(-len(rows) // blocks)
    blocks_rows = [rows[start : start + size] for start in range(0, len(rows), size)]
    return [row for block in reversed(blocks_rows) for row in block]


def tie_rows(count: int) -> list[tuple[str, int]]:
    """Rows sharing a timestamp in blocks of four, so a sort must break ties by file order."""
    rows: list[tuple[str, int]] = []
    for block in range(count // 4):
        stamp = (utc("2024-01-01 00:00") + STEP * block).strftime("%Y-%m-%d %H:%M")
        rows.extend((stamp, len(rows) + slot) for slot in range(4))
    return rows


def write_csv(path: Path, rows: list[tuple[str, int]]) -> Path:
    frame = pd.DataFrame({"unit_id": "unit-a", TIME: [stamp for stamp, _ in rows],
                          "value": [str(value) for _, value in rows]})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(frame.to_csv(index=False), encoding="utf-8", newline="")
    return path


def make_input(tmp_path: Path, count: int, *, seed: int = 7, shuffled_input: bool = True) -> Path:
    rows = timed_rows(count)
    return write_csv(tmp_path / "raw" / "unit-a.csv", shuffled(rows) if shuffled_input else rows)


def prepare(chunk: pd.DataFrame) -> pd.DataFrame:
    out = chunk.copy()
    out[TIME] = pd.to_datetime(out[TIME], utc=True)
    out["value"] = out["value"].astype("int64")
    return out


def counted_prepare() -> tuple[Callable[[pd.DataFrame], pd.DataFrame], dict[str, int]]:
    """A prepare that reports how many rows it has seen and the largest frame it was handed."""
    seen = {"rows": 0, "max_frame": 0, "calls": 0}

    def probe(chunk: pd.DataFrame) -> pd.DataFrame:
        seen["rows"] += int(len(chunk))
        seen["max_frame"] = max(seen["max_frame"], int(len(chunk)))
        seen["calls"] += 1
        return prepare(chunk)

    return probe, seen


def read_out(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype={TIME: "str"})


def stamps(frame: pd.DataFrame) -> pd.Series:
    return pd.to_datetime(frame[TIME], utc=True)


def bound_spies(monkeypatch) -> tuple[dict[str, list], dict[str, bool]]:
    """Watch every read and write the sort performs, so a memory claim can be asserted as a number.

    Three separate questions are worth asking, because killing them needs different evidence: did
    the sort ever read a file whole, did any single read step hold more than ``chunk_rows`` rows,
    and did any single written block exceed the bound. Only the merge can answer the third, and it
    only gets the chance when a group is read with no row limit - which needs several passes.
    """
    seen: dict[str, list] = {"reads": [], "writes": [], "whole": []}
    state = {"inside": False}

    real_chunks = es.iter_file_chunks

    def spy_chunks(path, **kwargs):
        for frame in real_chunks(path, **kwargs):
            if state["inside"]:
                seen["reads"].append(int(len(frame)))
            yield frame

    monkeypatch.setattr(es, "iter_file_chunks", spy_chunks)

    real_read_csv = pd.read_csv

    def spy_read_csv(path, **kwargs):
        if state["inside"] and kwargs.get("nrows") is None and kwargs.get("chunksize") is None:
            seen["whole"].append("unbounded read")
        return real_read_csv(path, **kwargs)

    monkeypatch.setattr(es.pd, "read_csv", spy_read_csv)

    real_to_csv = es.pd.DataFrame.to_csv

    def spy_to_csv(self, *args, **kwargs):
        # Only rows the sort itself writes are in scope: the test fixture writes the input file
        # with the same method, and its size is not a claim about the sort.
        if state["inside"]:
            seen["writes"].append(int(len(self)))
        return real_to_csv(self, *args, **kwargs)

    monkeypatch.setattr(es.pd.DataFrame, "to_csv", spy_to_csv)
    return seen, state


def assert_within_bound(seen: dict[str, list], bound: int, rows: int) -> None:
    assert rows, "nothing was sorted, so no bound was exercised"
    assert seen["reads"], "the sort read a file without going through the chunked reader"
    assert max(seen["reads"]) <= bound, (
        f"a read step held {max(seen['reads'])} rows against a bound of {bound}"
    )
    assert seen["whole"] == [], "the sort read a whole file into memory"
    assert max(seen["writes"]) <= bound, f"a written block held {max(seen['writes'])} rows"


# ---------------------------------------------------------------- ordering and completeness


def test_a_single_chunk_file_goes_through_the_same_path(tmp_path: Path):
    source = make_input(tmp_path, 30)
    result = sort_file_to_time_order(
        source, out_dir=tmp_path / "sort", time_column=TIME, chunk_rows=1_000, prepare=prepare
    )
    assert result.rows == 30
    assert result.runs == 1
    assert result.reused is False
    assert result.path == tmp_path / "sort" / MERGED_FILE_NAME


def test_a_multi_chunk_file_merges_its_runs_and_frees_them(tmp_path: Path):
    source = make_input(tmp_path, 250)
    out = tmp_path / "sort"
    result = sort_file_to_time_order(
        source, out_dir=out, time_column=TIME, chunk_rows=60, prepare=prepare
    )
    assert result.rows == 250
    assert result.runs == 5
    # Runs are a second copy of the input, so keeping them would double the space the sort used to
    # report as its peak.
    assert not (out / RUNS_DIR_NAME).exists()
    assert sorted(p.name for p in out.iterdir()) == sorted([MERGED_FILE_NAME, SORT_SIDECAR_NAME])


def test_the_output_equals_a_stable_in_memory_sort(tmp_path: Path):
    """The sort must not reorder rows a whole-file stable sort would have left alone."""
    rows = shuffled(tie_rows(120), seed=11)
    source = write_csv(tmp_path / "raw" / "unit-a.csv", rows)
    result = sort_file_to_time_order(
        source, out_dir=tmp_path / "sort", time_column=TIME, chunk_rows=16, prepare=prepare
    )
    whole = prepare(read_out(source))
    expected = whole.sort_values(TIME, kind="stable", ignore_index=True)
    got = prepare(read_out(result.path))
    assert got[TIME].tolist() == expected[TIME].tolist()
    assert got["value"].tolist() == expected["value"].tolist()


def test_every_input_row_appears_exactly_once(tmp_path: Path):
    source = make_input(tmp_path, 400)
    result = sort_file_to_time_order(
        source, out_dir=tmp_path / "sort", time_column=TIME, chunk_rows=45, prepare=prepare
    )
    values = read_out(result.path)["value"].tolist()
    assert sorted(values) == list(range(400))


def test_the_time_column_is_non_decreasing_in_the_output(tmp_path: Path):
    source = make_input(tmp_path, 400)
    result = sort_file_to_time_order(
        source, out_dir=tmp_path / "sort", time_column=TIME, chunk_rows=45, prepare=prepare
    )
    series = stamps(read_out(result.path))
    assert (series.diff().dropna() >= pd.Timedelta(0)).all()


def test_more_runs_than_open_files_still_sort_correctly(tmp_path: Path, monkeypatch):
    """Forcing several merge passes is the difference between a demo and a 130 GB file.

    This shape is also the only one where the merge can grab an over-sized block: with one cursor
    left in a group there is no next key to stop at, so the row bound alone has to do the work.
    """
    seen, state = bound_spies(monkeypatch)
    source = make_input(tmp_path, 600)
    state["inside"] = True
    try:
        result = sort_file_to_time_order(
            source, out_dir=tmp_path / "sort", time_column=TIME, chunk_rows=10, prepare=prepare
        )
    finally:
        state["inside"] = False
    assert result.runs == 60
    assert result.runs > es.MAX_OPEN_RUNS
    values = read_out(result.path)["value"].tolist()
    assert sorted(values) == list(range(600))
    series = stamps(read_out(result.path))
    assert (series.diff().dropna() >= pd.Timedelta(0)).all()
    assert_within_bound(seen, 10, result.rows)


def test_the_sequence_column_is_not_left_in_the_output(tmp_path: Path):
    source = make_input(tmp_path, 120)
    result = sort_file_to_time_order(
        source, out_dir=tmp_path / "sort", time_column=TIME, chunk_rows=25, prepare=prepare
    )
    assert list(read_out(result.path).columns) == ["unit_id", TIME, "value"]
    assert SEQUENCE_COLUMN not in result.path.read_text(encoding="utf-8")


def test_no_step_holds_more_rows_than_the_bound_allows(tmp_path: Path, monkeypatch):
    """Both phases are bounded: reads go through the chunker, writes never exceed one chunk."""
    seen, state = bound_spies(monkeypatch)
    source = make_input(tmp_path, 300)
    state["inside"] = True
    try:
        result = sort_file_to_time_order(
            source, out_dir=tmp_path / "sort", time_column=TIME, chunk_rows=20, prepare=prepare
        )
    finally:
        state["inside"] = False
    assert result.rows == 300
    assert_within_bound(seen, 20, result.rows)


def test_the_callers_prepare_runs_once_per_row(tmp_path: Path):
    source = make_input(tmp_path, 130)
    probe, seen = counted_prepare()
    sort_file_to_time_order(
        source, out_dir=tmp_path / "sort", time_column=TIME, chunk_rows=30, prepare=probe
    )
    assert seen["rows"] == 130
    assert seen["calls"] == 5
    assert seen["max_frame"] <= 30


def test_an_empty_file_sorts_to_an_empty_output(tmp_path: Path):
    source = write_csv(tmp_path / "raw" / "unit-a.csv", [])
    result = sort_file_to_time_order(
        source, out_dir=tmp_path / "sort", time_column=TIME, chunk_rows=20, prepare=prepare
    )
    assert result.rows == 0
    assert result.runs == 0
    assert result.path.is_file()


def test_a_missing_time_column_is_refused(tmp_path: Path):
    source = tmp_path / "raw" / "unit-a.csv"
    source.parent.mkdir(parents=True)
    source.write_text("unit_id,value\nunit-a,1\n", encoding="utf-8", newline="")
    with pytest.raises(SortError, match=TIME):
        sort_file_to_time_order(
            source, out_dir=tmp_path / "sort", time_column=TIME, chunk_rows=20
        )


def test_a_timezone_naive_time_column_is_refused(tmp_path: Path):
    source = make_input(tmp_path, 20)

    def naive(chunk: pd.DataFrame) -> pd.DataFrame:
        out = chunk.copy()
        out[TIME] = pd.to_datetime(out[TIME])
        return out

    with pytest.raises(SortError, match="timezone"):
        sort_file_to_time_order(
            source, out_dir=tmp_path / "sort", time_column=TIME, chunk_rows=5, prepare=naive
        )


@pytest.mark.parametrize("column", [SEQUENCE_COLUMN, es.SORT_NS_COLUMN])
def test_an_input_that_already_carries_a_sort_column_is_refused(tmp_path: Path, column: str):
    source = tmp_path / "raw" / "unit-a.csv"
    source.parent.mkdir(parents=True)
    source.write_text(
        f"unit_id,{TIME},value,{column}\nu,2024-01-01 00:00,1,9\n",
        encoding="utf-8",
        newline="",
    )
    with pytest.raises(SortError, match=re.escape(column)):
        sort_file_to_time_order(
            source, out_dir=tmp_path / "sort", time_column=TIME, chunk_rows=20, prepare=prepare
        )


# ---------------------------------------------------------------- runtime directory rules


def test_an_occupied_runtime_directory_is_not_overwritten(tmp_path: Path):
    out = tmp_path / "sort"
    out.mkdir()
    (out / "someone-elses.csv").write_text("keep me\n", encoding="utf-8", newline="")
    source = make_input(tmp_path, 40)
    with pytest.raises(SortError, match="runtime directory"):
        sort_file_to_time_order(
            source, out_dir=out, time_column=TIME, chunk_rows=10, prepare=prepare
        )
    assert (out / "someone-elses.csv").read_text(encoding="utf-8") == "keep me\n"
    assert not (out / MERGED_FILE_NAME).exists()


def test_the_input_may_not_live_inside_the_runtime_directory(tmp_path: Path):
    out = tmp_path / "sort"
    source = write_csv(out / "unit-a.csv", shuffled(timed_rows(30)))
    with pytest.raises(SortError, match="inside"):
        sort_file_to_time_order(
            source, out_dir=out, time_column=TIME, chunk_rows=10, prepare=prepare
        )
    assert source.is_file()


def test_a_completed_sort_is_reused_when_input_and_config_match(tmp_path: Path):
    source = make_input(tmp_path, 90)
    first, seen = counted_prepare()
    built = sort_file_to_time_order(
        source, out_dir=tmp_path / "sort", time_column=TIME, chunk_rows=30, prepare=first
    )
    bytes_before = built.path.read_bytes()
    again_probe, again_seen = counted_prepare()
    second = sort_file_to_time_order(
        source, out_dir=tmp_path / "sort", time_column=TIME, chunk_rows=30, prepare=again_probe
    )
    assert second.reused is True
    assert second.rows == built.rows == 90
    assert second.runs == built.runs == 3
    assert again_seen["rows"] == 0, "a reused sort must not re-read the input"
    assert second.path.read_bytes() == bytes_before


def test_a_different_chunk_size_is_not_reused(tmp_path: Path):
    source = make_input(tmp_path, 90)
    sort_file_to_time_order(
        source, out_dir=tmp_path / "sort", time_column=TIME, chunk_rows=30, prepare=prepare
    )
    with pytest.raises(es.ConfigChangedError) as caught:
        sort_file_to_time_order(
            source, out_dir=tmp_path / "sort", time_column=TIME, chunk_rows=31, prepare=prepare
        )
    assert caught.value.exit_code == 2
    assert not (tmp_path / "sort" / "runs" / "chunk-00000.csv.tmp").exists()


def test_a_modified_input_is_not_reused(tmp_path: Path):
    source = make_input(tmp_path, 90)
    sort_file_to_time_order(
        source, out_dir=tmp_path / "sort", time_column=TIME, chunk_rows=30, prepare=prepare
    )
    source.write_text(
        source.read_text(encoding="utf-8") + "unit-a,2024-01-01 05:00,999\n",
        encoding="utf-8",
        newline="",
    )
    with pytest.raises(SortError, match="different"):
        sort_file_to_time_order(
            source, out_dir=tmp_path / "sort", time_column=TIME, chunk_rows=30, prepare=prepare
        )


def test_a_tampered_output_is_not_reused(tmp_path: Path):
    """A runtime directory whose bytes no longer match its own checkpoint is not a completed sort."""
    source = make_input(tmp_path, 90)
    first = sort_file_to_time_order(
        source, out_dir=tmp_path / "sort", time_column=TIME, chunk_rows=30, prepare=prepare
    )
    first.path.write_bytes(first.path.read_bytes() + b"unit-a,2024-01-01 06:00,999\n")
    with pytest.raises(SortError, match="digest"):
        sort_file_to_time_order(
            source, out_dir=tmp_path / "sort", time_column=TIME, chunk_rows=30, prepare=prepare
        )


def test_orphan_files_from_an_interrupted_sort_are_replaced(tmp_path: Path):
    """A crash after the merge but before the checkpoint must not wedge the runtime directory."""
    out = tmp_path / "sort"
    out.mkdir()
    (out / MERGED_FILE_NAME).write_text("unit_id,event_time,value\norphan,row\n",
                                        encoding="utf-8", newline="")
    source = make_input(tmp_path, 90)
    result = sort_file_to_time_order(
        source, out_dir=out, time_column=TIME, chunk_rows=30, prepare=prepare
    )
    assert result.reused is False
    assert result.rows == 90
    assert read_out(result.path)["value"].tolist() != ["row"]


def test_the_sidecar_records_the_digests_and_counts(tmp_path: Path):
    source = make_input(tmp_path, 75)
    sort_file_to_time_order(
        source, out_dir=tmp_path / "sort", time_column=TIME, chunk_rows=30, prepare=prepare
    )
    sidecar = json.loads((tmp_path / "sort" / SORT_SIDECAR_NAME).read_text(encoding="utf-8"))
    assert sidecar["sort_version"] == SORT_VERSION
    assert sidecar["rows"] == 75
    assert sidecar["runs"] == 3
    assert sidecar["input_sha256"] == es.sha256_file(source)
    assert sidecar["output_sha256"] == es.sha256_file(tmp_path / "sort" / MERGED_FILE_NAME)
    assert sidecar["config_hash"]
    assert sorted(sidecar["config"]) == ["chunk_rows", "fmt", "sort_version", "time_column"]
    text = json.dumps(sidecar)
    assert "unit-a" not in text, "a file name may be a real unit identifier"
    assert str(tmp_path) not in text


def test_no_temporary_file_survives_a_failed_merge(tmp_path: Path, monkeypatch):
    source = make_input(tmp_path, 200)
    real = es.pd.DataFrame.to_csv
    calls = {"n": 0}

    def failing(self, *args, **kwargs):
        calls["n"] += 1
        if calls["n"] > 6:
            raise OSError(28, "No space left on device")
        return real(self, *args, **kwargs)

    monkeypatch.setattr(es.pd.DataFrame, "to_csv", failing)
    with pytest.raises(OSError):
        sort_file_to_time_order(
            source, out_dir=tmp_path / "sort", time_column=TIME, chunk_rows=20, prepare=prepare
        )
    left = sorted(p.name for p in (tmp_path / "sort").rglob("*.tmp"))
    assert left == []
    assert not (tmp_path / "sort" / SORT_SIDECAR_NAME).exists()


def test_a_failed_sort_leaves_no_file_that_looks_finished(tmp_path: Path, monkeypatch):
    """A crash must not leave a plausible sorted.csv behind without a checkpoint to trust it."""
    out = tmp_path / "sort"
    out.mkdir()
    (out / MERGED_FILE_NAME).write_text("unit_id,event_time,value\nfrom,an,earlier,run\n",
                                        encoding="utf-8", newline="")
    source = make_input(tmp_path, 200)
    real = es.pd.DataFrame.to_csv
    calls = {"n": 0}

    def failing(self, *args, **kwargs):
        calls["n"] += 1
        if calls["n"] > 6:
            raise OSError(28, "No space left on device")
        return real(self, *args, **kwargs)

    monkeypatch.setattr(es.pd.DataFrame, "to_csv", failing)
    with pytest.raises(OSError):
        sort_file_to_time_order(
            source, out_dir=out, time_column=TIME, chunk_rows=20, prepare=prepare
        )
    assert not (out / MERGED_FILE_NAME).exists()
    assert not (out / RUNS_DIR_NAME).exists()
    assert not (out / SORT_SIDECAR_NAME).exists()
    assert sorted(p.name for p in out.rglob("*")) == []


# ---------------------------------------------------------------- space


def test_the_estimate_covers_the_runs_and_the_merged_output(tmp_path: Path):
    source = make_input(tmp_path, 500)
    size = source.stat().st_size
    needed = estimate_space_bytes(source, fmt="csv")
    # One copy of the input cannot hold the split runs, the largest intermediate pass and the
    # merged output, all of which can be on the disk at the same time.
    assert needed >= 3 * size, f"{needed} bytes leaves no room for three copies of {size} bytes"
    assert needed == math.ceil(size * es.COPIES_AT_PEAK * es.SPACE_HEADROOM_RATIO)


def test_a_feather_input_is_estimated_bigger_than_the_same_csv(tmp_path: Path):
    source = make_input(tmp_path, 500)
    assert estimate_space_bytes(source, fmt="feather") == 2 * estimate_space_bytes(
        source, fmt="csv"
    )


def test_the_space_report_carries_needed_free_and_shortfall(tmp_path: Path):
    source = make_input(tmp_path, 200)
    out = tmp_path / "sort"
    report = space_report(source, out, fmt="csv")
    assert isinstance(report, SpaceReport)
    assert report.needed_bytes == estimate_space_bytes(source, fmt="csv")
    assert report.free_bytes == shutil.disk_usage(out.parent).free
    assert report.shortfall_bytes == max(0, report.needed_bytes - report.free_bytes)
    assert report.sufficient is (report.shortfall_bytes == 0)


def test_an_insufficient_disk_is_refused_before_anything_is_written(tmp_path: Path, monkeypatch):
    source = make_input(tmp_path, 200)
    out = tmp_path / "sort"
    needed = estimate_space_bytes(source, fmt="csv")
    monkeypatch.setattr(
        es.shutil, "disk_usage", lambda path: type("U", (), {"free": needed - 1})()
    )
    with pytest.raises(SortError, match="space"):
        sort_file_to_time_order(
            source, out_dir=out, time_column=TIME, chunk_rows=20, prepare=prepare
        )
    assert not out.exists() or sorted(p.name for p in out.rglob("*")) == []


def test_the_space_failure_names_no_path_but_carries_the_numbers(tmp_path: Path, monkeypatch):
    source = make_input(tmp_path, 200)
    out = tmp_path / "sort"
    needed = estimate_space_bytes(source, fmt="csv")
    monkeypatch.setattr(
        es.shutil, "disk_usage", lambda path: type("U", (), {"free": 123})()
    )
    with pytest.raises(SortError) as caught:
        sort_file_to_time_order(
            source, out_dir=out, time_column=TIME, chunk_rows=20, prepare=prepare
        )
    message = str(caught.value)
    # All three numbers, because the one a caller acts on is the shortfall: "needed 9 MB, 123 bytes
    # free" says a sort cannot run here, "you are 9 MB short" says what to change.
    assert str(needed) in message and "123" in message
    assert str(needed - 123) in message
    assert message.count("bytes") == 3
    assert "unit-a" not in message and str(tmp_path) not in message
    assert "\\" not in message and "/" not in message


# ---------------------------------------------------------------- the sort is worth its name


def test_the_package_exports_the_sort_surface():
    from faultevolve import data

    for name in (
        "SEQUENCE_COLUMN",
        "SORT_NS_COLUMN",
        "SORT_VERSION",
        "SortError",
        "SortResult",
        "SpaceReport",
        "estimate_space_bytes",
        "sort_file_to_time_order",
        "space_report",
    ):
        assert hasattr(data, name), f"{name} is not re-exported"
        assert name in data.__all__, f"{name} is imported but not promised"


def test_the_sorted_output_streams_through_the_window_reader(tmp_path: Path):
    """The point of sorting is that the streaming reader stops refusing the file."""
    source = write_csv(
        tmp_path / "raw" / "unit-a.csv", block_reversed(timed_rows(240), blocks=8)
    )
    with pytest.raises(IoError, match="not ordered by time"):
        list(iter_event_windows(source, fmt="csv", chunk_rows=30, time_column=TIME,
                                lookback=pd.Timedelta(hours=1), prepare=prepare))
    result = sort_file_to_time_order(
        source, out_dir=tmp_path / "sort", time_column=TIME, chunk_rows=30, prepare=prepare
    )
    windows = list(
        iter_event_windows(
            result.path, fmt="csv", chunk_rows=30, time_column=TIME,
            lookback=pd.Timedelta(hours=1),
        )
    )
    assert sum(int(len(w.new_rows)) for w in windows) == 240
    assert [int(w.index) for w in windows] == list(range(len(windows)))


def test_the_temp_file_a_crash_left_behind_is_not_an_occupier(tmp_path: Path):
    """A two-hour sort killed mid-write must not wedge its workspace.

    The atomic write names its temp file after the target, so the leftover carries this sort's own
    name. Refusing the directory over it would mean an interrupted run needs a human holding a
    deletion list, which is the opposite of a resumable pipeline.
    """
    source = make_input(tmp_path, 90)
    out = tmp_path / "sort"
    out.mkdir()
    (out / f"{MERGED_FILE_NAME}.tmp").write_text("half a file" + chr(10), encoding="utf-8", newline="")
    result = sort_file_to_time_order(
        source, out_dir=out, time_column=TIME, chunk_rows=30, prepare=prepare
    )
    assert result.rows == 90
    assert sorted(path.name for path in out.iterdir()) == sorted([MERGED_FILE_NAME, SORT_SIDECAR_NAME])


def test_a_foreign_temporary_file_is_still_refused(tmp_path: Path):
    """Only this sort's own temp name is forgiven, not anything else ending in .tmp."""
    source = make_input(tmp_path, 90)
    out = tmp_path / "sort"
    out.mkdir()
    (out / ("someone-else" + ".tmp")).write_text("not ours" + chr(10), encoding="utf-8", newline="")
    with pytest.raises(SortError, match="runtime directory"):
        sort_file_to_time_order(
            source, out_dir=out, time_column=TIME, chunk_rows=30, prepare=prepare
        )
