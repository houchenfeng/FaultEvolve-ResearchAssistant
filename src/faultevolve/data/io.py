"""Bounded-memory streaming for event files too large to load, and the partitions they produce.

Two facts drive this module. A single source file can be tens of gigabytes, so it must be read in
bounded pieces and never all at once. And a lookback window does not care where a chunk ends: a
prediction time two rows into the next chunk still needs the rows just before the boundary. Reading
in chunks is therefore only correct if the rows a later window can still reach are carried forward,
which is what ``iter_event_windows`` guarantees and what ``carry_forward`` computes.

Writing is held to the same shape: a run directory is too expensive to rebuild from scratch, so
``write_partitions`` lets each worker publish only its own file and lets the one coordinator holding
the writer lock be the only thing that stamps a partition complete.

Error messages here name no file, because a source file name may itself be a device identifier.
"""

from __future__ import annotations

import os
from collections.abc import Iterator, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import pandas as pd

from faultevolve.data.event_sampling import SamplingError, select_history
from faultevolve.data.manifest import (
    PARTITIONS_DIR,
    ConfigChangedError,
    ManifestError,
    check_partition_name,
    config_hash,
    finish_partition,
    input_digests,
    read_manifest,
    verify_partitions,
    writer_lock,
)

#: Chunk size in rows. The bound has to be in rows, not bytes, because the windows are in time.
DEFAULT_CHUNK_ROWS = 1 << 14

FORMATS = ("csv", "feather")

_PYARROW_HINT = (
    "the feather format needs pyarrow, which is not installed; declare the dependency instead of "
    "silently switching the on-disk format"
)


class IoError(ValueError):
    """Raised when a file cannot be streamed within its bounds.

    Messages carry counts, indices and shapes only; an input file name may be a real identifier.
    """


@dataclass(frozen=True)
class EventWindow:
    """One streamed chunk, plus the earlier rows its own windows can still reach.

    ``rows`` is exactly what a consumer may slice: every row with a stamp at or before
    ``boundary`` that is still inside ``lookback`` of it. ``new_rows`` is the part of ``rows`` this
    chunk contributed, which is how a consumer knows which prediction times are still its to emit.
    """

    index: int
    rows: pd.DataFrame
    new_rows: pd.DataFrame
    boundary: pd.Timestamp
    carry_count: int


def _require_chunk_rows(chunk_rows: int) -> int:
    if isinstance(chunk_rows, bool) or not isinstance(chunk_rows, int):
        raise IoError(f"chunk_rows must be a whole number of rows, got {type(chunk_rows).__name__}")
    if chunk_rows <= 0:
        raise IoError(f"chunk_rows must be positive, got {chunk_rows}")
    return int(chunk_rows)


def _require_format(fmt: str) -> str:
    if fmt not in FORMATS:
        raise IoError(f"the input format must be one of {FORMATS}, got an unsupported format")
    return fmt


def _require_existing(path: Path) -> Path:
    file_path = Path(path)
    if not file_path.is_file():
        raise IoError(
            "an input file does not exist; its name is not printed because a file name may be a "
            "unit identifier"
        )
    return file_path


def _csv_chunks(path: Path, chunk_rows: int) -> Iterator[pd.DataFrame]:
    # A chunked CSV cannot be type-inferred per chunk: the same column can look numeric in one
    # chunk and blank in the next. Text is the only dtype that is stable across boundaries, so the
    # caller's prepare() step is where types are declared.
    reader = pd.read_csv(path, chunksize=chunk_rows, dtype=str, keep_default_na=False)
    try:
        for chunk in reader:
            # A header-only file makes pandas hand back one empty frame; an empty chunk is not a
            # chunk, and a consumer that counted it would count a row that is not there.
            if len(chunk):
                yield chunk
    finally:
        close = getattr(reader, "close", None)
        if close is not None:
            close()


def _feather_chunks(path: Path, chunk_rows: int) -> Iterator[pd.DataFrame]:
    try:
        import pyarrow as pa
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise IoError(_PYARROW_HINT) from exc
    source = pa.OSFile(str(path), "rb")
    try:
        reader = pa.ipc.open_file(source)
        for batch_index in range(reader.num_record_batches):
            batch = reader.get_batch(batch_index)
            # A slice is zero-copy, so only the chunk_rows rows converted below are ever read.
            for offset in range(0, int(batch.num_rows), chunk_rows):
                yield batch.slice(offset, chunk_rows).to_pandas()
    finally:
        source.close()


def iter_file_chunks(
    path: Path, *, fmt: str = "csv", chunk_rows: int = DEFAULT_CHUNK_ROWS
) -> Iterator[pd.DataFrame]:
    """Yield at most ``chunk_rows`` rows at a time, reading the file exactly once."""
    size = _require_chunk_rows(chunk_rows)
    kind = _require_format(fmt)
    file_path = _require_existing(path)
    if kind == "csv":
        return _csv_chunks(file_path, size)
    return _feather_chunks(file_path, size)


def _utc_stamps(rows: pd.DataFrame, time_column: str) -> pd.DatetimeIndex:
    if time_column not in rows.columns:
        raise IoError(
            f"a prepared chunk has no time column called {time_column!r}; prepare() must produce it"
        )
    try:
        index = pd.DatetimeIndex(rows[time_column])
    except (ValueError, TypeError) as exc:
        raise IoError(
            f"a prepared chunk's time column {time_column!r} is not made of timestamps"
        ) from exc
    if index.tz is None:
        raise IoError(
            f"a prepared chunk's time column {time_column!r} is timezone-naive; prepare() must "
            "localise it, because a lookback window across a daylight-saving boundary is wrong by "
            "an hour otherwise"
        )
    return index.tz_convert("UTC")


def _ordered(rows: pd.DataFrame, time_column: str) -> pd.DataFrame:
    if not len(rows):
        return rows.copy()
    return rows.sort_values(time_column, kind="stable", ignore_index=True)


def carry_forward(
    rows: pd.DataFrame,
    *,
    boundary: pd.Timestamp,
    lookback: pd.Timedelta,
    time_column: str = "log_time",
) -> pd.DataFrame:
    """Rows still reachable by a window opening at or after ``boundary``.

    This is deliberately ``select_history`` and nothing else: the carry rule and the window rule are
    the same rule, so a chunk boundary cannot be the reason a row went missing.
    """
    try:
        return select_history(rows, boundary, lookback=lookback, time_col=time_column)
    except SamplingError as exc:
        raise IoError(str(exc)) from exc


def iter_event_windows(
    path: Path,
    *,
    fmt: str = "csv",
    chunk_rows: int = DEFAULT_CHUNK_ROWS,
    time_column: str = "log_time",
    lookback: pd.Timedelta,
    prepare: Callable[[pd.DataFrame], pd.DataFrame] | None = None,
) -> Iterator[EventWindow]:
    """Stream one file as windows that never lose a row a later lookback still needs.

    ``prepare`` is the caller's declared normalisation (types, timezone, dedup policy). Chunks may
    be internally unordered, but a chunk that starts before the previous one ended is refused: the
    carry rule only keeps rows down to ``boundary - lookback``, so backwards chunks would need rows
    that had already been dropped.
    """
    if prepare is not None and not callable(prepare):
        raise IoError("prepare must be a callable that takes a chunk and returns a chunk")
    boundaries: pd.Timestamp | None = None
    held = pd.DataFrame(columns=[time_column])
    index = 0
    for chunk in iter_file_chunks(path, fmt=fmt, chunk_rows=chunk_rows):
        prepared = chunk if prepare is None else prepare(chunk)
        if not len(prepared):
            continue
        stamps = _utc_stamps(prepared, time_column)
        first = stamps.min()
        last = stamps.max()
        if boundaries is not None and first < boundaries:
            raise IoError(
                f"chunk {index} of the input starts before the previous chunk ends, so the file is "
                "not ordered by time across chunks; carried rows reach back only one lookback, so "
                "streaming it anyway would silently drop rows a window still needs. Sort the file "
                "into time order before streaming it."
            )
        fresh = _ordered(prepared, time_column)
        carry_count = int(len(held))
        rows = fresh
        if carry_count:
            rows = _ordered(pd.concat([held, fresh], ignore_index=True), time_column)
        yield EventWindow(
            index=index,
            rows=rows,
            new_rows=fresh,
            boundary=last,
            carry_count=carry_count,
        )
        held = _ordered(
            carry_forward(rows, boundary=last, lookback=lookback, time_column=time_column),
            time_column,
        )
        boundaries = last
        index += 1


@dataclass(frozen=True)
class PartitionJob:
    """One named output partition and the callable that produces its rows.

    ``build`` runs in a worker thread and may be retried from scratch after a crash, so it may not
    depend on state another job left behind.
    """

    name: str
    build: Callable[[], pd.DataFrame]


def _require_workers(workers: int) -> int:
    if isinstance(workers, bool) or not isinstance(workers, int):
        raise IoError(f"workers must be a whole number, got {type(workers).__name__}")
    if workers <= 0:
        raise IoError(f"workers must be positive, got {workers}")
    return int(workers)


def _partition_path(out: Path, name: str) -> Path:
    return out / PARTITIONS_DIR / name


def _write_one(out: Path, job: PartitionJob, name: str) -> int:
    """Produce one partition on disk and return its row count. Touches no manifest."""
    frame = job.build()
    if not isinstance(frame, pd.DataFrame):
        raise IoError(
            f"partition {name} was built as a {type(frame).__name__}; a build() must return a "
            "DataFrame so its shape can be checked"
        )
    target = _partition_path(out, name)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f"{target.name}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            frame.to_csv(handle, index=False, lineterminator="\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    except BaseException:
        # A half-written temp file is not a partition; leaving it behind would let a later reader
        # mistake bytes that were never hashed for output.
        temporary.unlink(missing_ok=True)
        raise
    return int(len(frame))


def write_partitions(
    out_dir: Path,
    jobs: Sequence[PartitionJob],
    *,
    workers: int,
    owner: str,
    config: Mapping[str, object] | None = None,
    paths: Sequence[Path] | None = None,
    algorithm_version: str | None = None,
) -> dict:
    """Write a partition set into a run directory, then checkpoint each finished file.

    Workers only ever name their own output file; the manifest is written by this caller's thread,
    one partition at a time, after that partition's bytes were hashed. A rerun therefore resumes
    from digests rather than from whichever temp files a crash left behind, and ``workers`` changes
    the order of production but never the bytes or the reuse decision.

    Passing ``config`` plus ``algorithm_version``, and ``paths``, asks the run directory to confirm
    them before anything is produced, so a stale experiment cannot be extended by accident.
    """
    out = Path(out_dir)
    count = _require_workers(workers)
    requested = list(jobs)
    names = [check_partition_name(job.name) for job in requested]
    seen: set[str] = set()
    for name in names:
        if name in seen:
            raise IoError(
                f"two jobs both write partition {name!r}; the second would overwrite the first "
                "and its checkpoint would describe whichever finished last"
            )
        seen.add(name)

    with writer_lock(out, owner=owner):
        manifest = read_manifest(out)
        if config is not None:
            if algorithm_version is None:
                raise IoError(
                    "a config comparison needs algorithm_version too, or the hash would describe "
                    "the config without saying which code reads it"
                )
            if manifest["config_hash"] != config_hash(config, algorithm_version=algorithm_version):
                raise ConfigChangedError(
                    "the config differs from the one that produced this run directory; start a new "
                    "runtime directory instead of mixing partitions from two configurations"
                )
        if paths is not None and manifest["inputs"]["sha256"] != input_digests(list(paths)):
            raise ManifestError(
                "the input files differ from the ones this run directory was built from; its "
                "partitions describe a different dataset"
            )

        verified = set(verify_partitions(out)["ok"])
        recorded = manifest["partitions"]
        pending: list[tuple[PartitionJob, str]] = []
        reused: list[str] = []
        for job, name in zip(requested, names):
            complete = recorded.get(name, {}).get("status") == "complete"
            if complete and name in verified:
                reused.append(name)
            else:
                pending.append((job, name))

        outcomes: list[tuple[str, int | BaseException]] = []
        if count == 1:
            for job, name in pending:
                try:
                    outcomes.append((name, _write_one(out, job, name)))
                except Exception as exc:
                    outcomes.append((name, exc))
        else:
            with ThreadPoolExecutor(max_workers=count) as pool:
                futures = {
                    name: pool.submit(_write_one, out, job, name) for job, name in pending
                }
                for name, future in futures.items():
                    try:
                        outcomes.append((name, future.result()))
                    except Exception as exc:
                        outcomes.append((name, exc))

        written: list[str] = []
        failed: list[dict[str, str]] = []
        for name, outcome in sorted(outcomes, key=lambda pair: pair[0]):
            if isinstance(outcome, BaseException):
                # The message may quote a path, and a path may be a unit identifier.
                failed.append({"name": name, "error": type(outcome).__name__})
                continue
            finish_partition(
                out, name=name, path=_partition_path(out, name), rows=int(outcome)
            )
            written.append(name)
        return {"written": written, "reused": sorted(reused), "failed": failed}


__all__ = [
    "DEFAULT_CHUNK_ROWS",
    "EventWindow",
    "FORMATS",
    "IoError",
    "PartitionJob",
    "carry_forward",
    "iter_event_windows",
    "iter_file_chunks",
    "write_partitions",
]
