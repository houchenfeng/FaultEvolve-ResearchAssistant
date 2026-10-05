"""Turning an out-of-order unit file into a time-ordered one without loading it.

The streaming reader refuses a file whose chunks run backwards in time, because a carried window
reaches back only one lookback. That refusal is right and it is also a dead end for a real unit file,
which arrives unordered: the file has to be sorted first, and a 40-130 GB file may not be sorted in
memory. This module is that sort - a bounded split into run files, a k-way merge over them, and a
workspace-space check that fires before the first byte is written rather than after the disk is full.

Three properties hold the design up. The merged result equals what a stable in-memory sort produces,
because every row carries the position it had in the prepared stream and ties break on it. No step
holds more rows than ``chunk_rows``, because both phases read through ``iter_file_chunks``. And the
runs are deleted as they are consumed, because otherwise the sort would silently leave a second copy
of the input on the disk it just measured.

Error messages here name no file: an input file name may itself be a device identifier.
"""

from __future__ import annotations

import json
import math
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

import pandas as pd

from faultevolve.data.io import DEFAULT_CHUNK_ROWS, FORMATS, iter_file_chunks
from faultevolve.data.manifest import ConfigChangedError, config_hash, sha256_file

SORT_VERSION = "esort-v1"

#: The two columns a run file carries so the merge can order rows it cannot see all at once: the
#: instant as nanoseconds, and the row's position in the prepared stream, which makes the sort
#: stable across runs. Both are stripped from the merged output.
SORT_NS_COLUMN = "__sort_ns"
SEQUENCE_COLUMN = "__sort_seq"
_HELPER_COLUMNS = (SORT_NS_COLUMN, SEQUENCE_COLUMN)

MERGED_FILE_NAME = "sorted.csv"
RUNS_DIR_NAME = "runs"
SORT_SIDECAR_NAME = "sort_manifest.json"

#: One open reader per run during a merge. Past this the runs are merged in passes instead.
MAX_OPEN_RUNS = 32

#: The split runs, the largest intermediate pass and the merged output each cost about the input,
#: and they can all be on the disk at the same time.
COPIES_AT_PEAK = 3
SPACE_HEADROOM_RATIO = 1.1

#: A feather column is binary on disk and text in a run file, so the same rows need more room.
FEATHER_TEXT_RATIO = 2.0


class SortError(ValueError):
    """Raised when a file cannot be sorted within its bounds.

    Messages carry counts, indices and byte sizes only; an input file name may be a unit identifier.
    """


@dataclass(frozen=True)
class SpaceReport:
    """What the sort needs, what the volume has, and the gap between them.

    ``shortfall_bytes`` is zero when there is room, so a caller can report the same object whether or
    not the run went ahead.
    """

    needed_bytes: int
    free_bytes: int
    shortfall_bytes: int

    @property
    def sufficient(self) -> bool:
        return self.shortfall_bytes == 0


@dataclass(frozen=True)
class SortResult:
    """Where the time-ordered copy is, how many rows it holds, and whether this call built it."""

    path: Path
    rows: int
    runs: int
    reused: bool


def _require_format(fmt: str) -> str:
    if fmt not in FORMATS:
        raise SortError(f"the input format must be one of {FORMATS}, got an unsupported format")
    return fmt


def _require_input(path: Path, fmt: str) -> Path:
    _require_format(fmt)
    file_path = Path(path)
    if not file_path.is_file():
        raise SortError(
            "the input file does not exist; its name is not printed because a file name may be a "
            "unit identifier"
        )
    return file_path


def _require_chunk_rows(chunk_rows: int) -> int:
    if isinstance(chunk_rows, bool) or not isinstance(chunk_rows, int):
        raise SortError(f"chunk_rows must be a whole number of rows, got {type(chunk_rows).__name__}")
    if chunk_rows <= 0:
        raise SortError(f"chunk_rows must be positive, got {chunk_rows}")
    return int(chunk_rows)


def _stamps(frame: pd.DataFrame, time_column: str) -> pd.DatetimeIndex:
    if time_column not in frame.columns:
        raise SortError(
            f"a prepared chunk has no time column called {time_column!r}; prepare() must produce it"
        )
    try:
        index = pd.DatetimeIndex(frame[time_column])
    except (ValueError, TypeError) as exc:
        raise SortError(
            f"a prepared chunk's time column {time_column!r} is not made of timestamps"
        ) from exc
    if index.tz is None:
        raise SortError(
            f"a prepared chunk's time column {time_column!r} is timezone-naive; prepare() must "
            "localise it, because nanoseconds on a naive wall clock are not one instant"
        )
    return index.tz_convert("UTC")


def estimate_space_bytes(path: Path, *, fmt: str = "csv") -> int:
    """Bytes the sort projects it needs, from the input's own size."""
    file_path = _require_input(path, fmt)
    size = int(file_path.stat().st_size)
    per_copy = size * (FEATHER_TEXT_RATIO if fmt == "feather" else 1.0)
    return math.ceil(per_copy * COPIES_AT_PEAK * SPACE_HEADROOM_RATIO)


def _volume_of(directory: Path) -> Path:
    """The nearest existing ancestor, whose free space is the one the directory would use."""
    probe = Path(directory)
    while not probe.exists():
        parent = probe.parent
        if parent == probe:
            return probe
        probe = parent
    return probe


def space_report(path: Path, out_dir: Path, *, fmt: str = "csv") -> SpaceReport:
    needed = estimate_space_bytes(path, fmt=fmt)
    free = int(shutil.disk_usage(_volume_of(out_dir)).free)
    return SpaceReport(
        needed_bytes=needed, free_bytes=free, shortfall_bytes=max(0, needed - free)
    )


def _require_room(path: Path, out: Path, fmt: str) -> SpaceReport:
    report = space_report(path, out, fmt=fmt)
    if not report.sufficient:
        raise SortError(
            "the runtime directory has no free space for this sort: "
            f"{report.needed_bytes} bytes are needed, {report.free_bytes} bytes are free, "
            f"{report.shortfall_bytes} bytes are missing"
        )
    return report


def _header_columns(path: Path, fmt: str, time_column: str) -> list[str]:
    if fmt == "csv":
        return [str(column) for column in pd.read_csv(path, nrows=0).columns]
    # A feather header lives in a columnar schema that only pyarrow can read, and this branch is
    # reached solely for a zero-row input, so the time column alone is what the output can promise.
    return [time_column]


def _write_frame(frame: pd.DataFrame, target: Path, *, columns: Sequence[str] | None = None) -> int:
    """Write one frame atomically; a half-written run is not a run."""
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f"{target.name}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            frame.to_csv(handle, index=False, columns=list(columns) if columns else None,
                         lineterminator="\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return int(len(frame))


class _RunCursor:
    """One run file, read ``chunk_rows`` at a time, positioned at its first unconsumed row."""

    def __init__(self, path: Path, chunk_rows: int) -> None:
        self._frames = iter_file_chunks(path, fmt="csv", chunk_rows=chunk_rows)
        self._frame = pd.DataFrame()
        self._ns: list[int] = []
        self._seq: list[int] = []
        self._position = 0
        self.exhausted = False
        self._load()

    def _load(self) -> None:
        while True:
            frame = next(self._frames, None)
            if frame is None:
                self.exhausted = True
                self._frame = pd.DataFrame()
                self._ns = []
                self._seq = []
                self._position = 0
                return
            if len(frame):
                self._frame = frame
                self._ns = [int(value) for value in frame[SORT_NS_COLUMN]]
                self._seq = [int(value) for value in frame[SEQUENCE_COLUMN]]
                self._position = 0
                return

    @property
    def key(self) -> tuple[int, int]:
        return (self._ns[self._position], self._seq[self._position])

    def take(self, limit: tuple[int, int] | None, max_rows: int) -> pd.DataFrame:
        """Rows up to ``limit``, at most ``max_rows`` of them, advancing past chunk boundaries."""
        parts: list[pd.DataFrame] = []
        taken = 0
        while taken < max_rows:
            size = len(self._frame)
            end = self._position
            while end < size and taken + (end - self._position) < max_rows:
                if limit is not None and (self._ns[end], self._seq[end]) >= limit:
                    break
                end += 1
            if end > self._position:
                parts.append(self._frame.iloc[self._position : end])
                taken += end - self._position
                self._position = end
            if self._position < size:
                break
            self._load()
            if self.exhausted:
                break
        if not parts:
            return self._frame.iloc[:0]
        if len(parts) == 1:
            return parts[0].reset_index(drop=True)
        return pd.concat(parts, ignore_index=True)


def _merge_group(
    paths: Sequence[Path],
    target: Path,
    columns: Sequence[str],
    chunk_rows: int,
    *,
    keep_helpers: bool,
) -> int:
    """Merge up to ``MAX_OPEN_RUNS`` ordered runs into one ordered file.

    ``keep_helpers`` is true for every pass except the last: an intermediate file is still input to
    a merge, so it has to carry the instant and the tie-break the next pass orders by.
    """
    written = list(columns) + (list(_HELPER_COLUMNS) if keep_helpers else [])
    cursors = [cursor for cursor in (_RunCursor(path, chunk_rows) for path in paths)
               if not cursor.exhausted]
    temporary = target.with_name(f"{target.name}.tmp")
    rows = 0
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            while cursors:
                pick = min(cursors, key=lambda cursor: cursor.key)
                limit = min(
                    (cursor.key for cursor in cursors if cursor is not pick), default=None
                )
                block = pick.take(limit, chunk_rows)
                if not keep_helpers:
                    block = block.drop(columns=list(_HELPER_COLUMNS))
                block.to_csv(handle, index=False, header=rows == 0, columns=written,
                             lineterminator="\n")
                rows += int(len(block))
                cursors = [cursor for cursor in cursors if not cursor.exhausted]
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return rows


def _split(
    path: Path,
    runs_dir: Path,
    *,
    fmt: str,
    chunk_rows: int,
    time_column: str,
    prepare: Callable[[pd.DataFrame], pd.DataFrame] | None,
) -> tuple[list[Path], list[str]]:
    """One ordered run file per input chunk, each holding at most ``chunk_rows`` rows."""
    runs: list[Path] = []
    rows = 0
    columns: list[str] = []
    for chunk in iter_file_chunks(path, fmt=fmt, chunk_rows=chunk_rows):
        for helper in _HELPER_COLUMNS:
            if helper in chunk.columns:
                raise SortError(
                    f"the input already has a column called {helper!r}; the sort uses it as its own "
                    "key and would silently reorder the file"
                )
        frame = chunk if prepare is None else prepare(chunk)
        if not len(frame):
            continue
        prepared = frame.reset_index(drop=True).copy()
        stamps = _stamps(prepared, time_column)
        if not columns:
            columns = [str(column) for column in prepared.columns]
        prepared[SORT_NS_COLUMN] = stamps.astype("int64").tolist()
        prepared[SEQUENCE_COLUMN] = list(range(rows, rows + len(prepared)))
        rows += int(len(prepared))
        # Stability, not the sequence column, is what keeps file order inside one run: the sequence
        # is already positional here. It earns its place in the merge, where two runs can no longer
        # see each other's positions.
        prepared = prepared.sort_values(SORT_NS_COLUMN, kind="stable", ignore_index=True)
        target = runs_dir / f"chunk-{len(runs):05d}.csv"
        _write_frame(prepared, target)
        runs.append(target)
    return runs, columns


def _merge_in_passes(
    runs: Sequence[Path], runs_dir: Path, target: Path, columns: Sequence[str], chunk_rows: int
) -> int:
    """Merge the runs into ``target``, in successive passes when there are more than the cap."""
    pending = list(runs)
    pass_index = 0
    rows = 0
    while len(pending) > MAX_OPEN_RUNS:
        next_pass: list[Path] = []
        for start in range(0, len(pending), MAX_OPEN_RUNS):
            group = pending[start : start + MAX_OPEN_RUNS]
            intermediate = runs_dir / f"pass-{pass_index:05d}-{len(next_pass):05d}.csv"
            _merge_group(group, intermediate, columns, chunk_rows, keep_helpers=True)
            for path in group:
                path.unlink(missing_ok=True)
            next_pass.append(intermediate)
        pending = next_pass
        pass_index += 1
    if not pending:
        return _write_frame(pd.DataFrame(columns=list(columns)), target)
    rows = _merge_group(pending, target, columns, chunk_rows, keep_helpers=False)
    for path in pending:
        path.unlink(missing_ok=True)
    return rows


def _discard(runs_dir: Path) -> None:
    """Leave no second copy of the input behind, not even after a failure."""
    if runs_dir.is_dir():
        shutil.rmtree(runs_dir, ignore_errors=True)


def _sort_config(chunk_rows: int, fmt: str, time_column: str) -> dict[str, object]:
    return {
        "chunk_rows": int(chunk_rows),
        "fmt": str(fmt),
        "sort_version": SORT_VERSION,
        "time_column": str(time_column),
    }


def _read_sidecar(path: Path) -> dict:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SortError(f"the sort checkpoint cannot be read: {type(exc).__name__}") from exc
    if not isinstance(raw, dict) or not {"config_hash", "input_sha256", "output_sha256"} <= set(raw):
        raise SortError("the sort checkpoint is missing the fields a reuse decision needs")
    return raw


def _reuse_or_refuse(
    out: Path, source: Path, *, chunk_rows: int, fmt: str, time_column: str
) -> SortResult | None:
    """Decide what an existing runtime directory means, before anything is written."""
    sidecar = out / SORT_SIDECAR_NAME
    if not sidecar.is_file():
        return None
    recorded = _read_sidecar(sidecar)
    digest = config_hash(
        _sort_config(chunk_rows, fmt, time_column), algorithm_version=SORT_VERSION
    )
    if recorded["config_hash"] != digest:
        raise ConfigChangedError(
            "the runtime directory was sorted with a different configuration; use a new runtime "
            "directory instead of mixing two sorts of the same file"
        )
    if recorded["input_sha256"] != sha256_file(source):
        raise SortError(
            "the runtime directory sorted a different input, so its result does not describe this "
            "file; use a new runtime directory"
        )
    merged = out / MERGED_FILE_NAME
    if not merged.is_file():
        raise SortError(
            "the sort checkpoint is complete but the sorted file is gone; start a new runtime "
            "directory instead of trusting a checkpoint with no bytes behind it"
        )
    if recorded["output_sha256"] != sha256_file(merged):
        raise SortError(
            "the sorted file no longer matches the digest in its own checkpoint, so it was edited "
            "after the sort; start a new runtime directory"
        )
    return SortResult(
        path=merged,
        rows=int(recorded["rows"]),
        runs=int(recorded["runs"]),
        reused=True,
    )


_OWNED_NAMES = (MERGED_FILE_NAME, SORT_SIDECAR_NAME, RUNS_DIR_NAME)

#: The atomic write renames ``<target>.tmp`` over the target, so a run killed mid-write leaves that
#: name behind. It is this sort's own file, and refusing a directory over it would make an
#: interrupted multi-hour run need a human with a deletion list.
_OWNED_TEMPORARY = f"{MERGED_FILE_NAME}.tmp"


def _require_writable(out: Path) -> None:
    """Refuse a directory that holds something this sort did not produce."""
    if not out.exists():
        return
    owned = frozenset({*_OWNED_NAMES, _OWNED_TEMPORARY})
    unexpected = [entry for entry in out.iterdir() if entry.name not in owned]
    if unexpected:
        raise SortError(
            f"the runtime directory already holds {len(unexpected)} entries this sort did not "
            "produce; choose an empty runtime directory instead of overwriting them"
        )


def sort_file_to_time_order(
    path: Path,
    *,
    out_dir: Path,
    time_column: str,
    fmt: str = "csv",
    chunk_rows: int = DEFAULT_CHUNK_ROWS,
    prepare: Callable[[pd.DataFrame], pd.DataFrame] | None = None,
) -> SortResult:
    """Sort one event file by ``time_column`` using bounded memory, into a directory it owns.

    ``prepare`` is the caller's declared normalisation, run over each input chunk exactly once - the
    same contract the streaming reader uses, so a row is never normalised twice or not at all. The
    merged file is ordered by instant, with ties in the order the rows reached the prepared stream,
    which is what a stable whole-file sort would have produced.

    A directory carrying a checkpoint of this same input and configuration is reused instead of
    re-sorted, so an interrupted run can be finished without paying for the hours again. Anything the
    sort did not write in there is refused.
    """
    source = _require_input(path, fmt)
    out = Path(out_dir)
    count = _require_chunk_rows(chunk_rows)
    if not str(time_column):
        raise SortError("time_column must name a column")
    if prepare is not None and not callable(prepare):
        raise SortError("prepare must be a callable that takes a chunk and returns a chunk")

    resolved_source = source.resolve()
    resolved_out = out.resolve()
    if resolved_out in resolved_source.parents or resolved_source == resolved_out:
        raise SortError(
            "the input file is inside the runtime directory, so the sort would read the file it is "
            "writing into; keep the raw data and the runtime directory apart"
        )

    existing = (
        _reuse_or_refuse(out, source, chunk_rows=count, fmt=fmt, time_column=time_column)
        if out.is_dir()
        else None
    )
    if existing is not None:
        return existing
    _require_writable(out)

    _require_room(source, out, fmt)
    out.mkdir(parents=True, exist_ok=True)
    runs_dir = out / RUNS_DIR_NAME
    merged = out / MERGED_FILE_NAME
    if merged.exists():
        merged.unlink()
    # The rename below would overwrite it anyway; removing it here is what keeps a finished sort's
    # directory holding exactly the two files it owns.
    (out / _OWNED_TEMPORARY).unlink(missing_ok=True)

    try:
        runs, columns = _split(
            source, runs_dir, fmt=fmt, chunk_rows=count, time_column=time_column, prepare=prepare
        )
        if not columns:
            columns = _header_columns(source, fmt, time_column)
        rows = _merge_in_passes(runs, runs_dir, merged, columns, count)
        _discard(runs_dir)
    except BaseException:
        # Only the run files can exist at this point: the merged output and the checkpoint are
        # written after this block, so an interrupted sort cannot leave either behind.
        _discard(runs_dir)
        raise

    config = _sort_config(count, fmt, time_column)
    payload = {
        "sort_version": SORT_VERSION,
        "rows": int(rows),
        "runs": int(len(runs)),
        "config": config,
        "config_hash": config_hash(config, algorithm_version=SORT_VERSION),
        "input_sha256": sha256_file(source),
        "output_sha256": sha256_file(merged),
    }
    temporary = out / f"{SORT_SIDECAR_NAME}.tmp"
    temporary.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n",
                         encoding="utf-8", newline="\n")
    os.replace(temporary, out / SORT_SIDECAR_NAME)
    return SortResult(path=merged, rows=int(rows), runs=int(len(runs)), reused=False)


__all__ = [
    "COPIES_AT_PEAK",
    "FEATHER_TEXT_RATIO",
    "MAX_OPEN_RUNS",
    "MERGED_FILE_NAME",
    "RUNS_DIR_NAME",
    "SEQUENCE_COLUMN",
    "SORT_NS_COLUMN",
    "SORT_SIDECAR_NAME",
    "SORT_VERSION",
    "SPACE_HEADROOM_RATIO",
    "ConfigChangedError",
    "SortError",
    "SortResult",
    "SpaceReport",
    "estimate_space_bytes",
    "sort_file_to_time_order",
    "space_report",
]
