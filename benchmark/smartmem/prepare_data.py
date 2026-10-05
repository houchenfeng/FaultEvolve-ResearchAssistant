"""Build SmartMem samples into one resumable run directory: the pipeline that ties V1 together.

Three rules shape this file. A per-unit event file is read once per run, so the work is cut into
partitions of ``--units-per-partition`` units and each partition holds its own slice of memory.
Every output is identified by the digest of its bytes, so a rerun resumes from content rather than
from whichever temp files a crash left behind. Nothing a public log, manifest or ``--json`` summary
prints may name a device: unit identifiers are counted, hashed, or replaced by a partition name.

The run directory is created by the manifest layer, which refuses to overwrite a directory this
code did not make and refuses to extend a run whose config changed - see
``docs/plans/SMARTMEM_PHASE1_IMPL_PLAN.md`` section 7 for the flag list and the exit codes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo

import pandas as pd
import yaml

from faultevolve.data.event_schema import build_event_profile
from faultevolve.data.external_sort import (
    MERGED_FILE_NAME,
    SORT_SIDECAR_NAME,
    SortError,
    estimate_space_bytes,
    sort_file_to_time_order,
)
from faultevolve.data.io import FORMATS, IoError, PartitionJob, write_partitions
from faultevolve.data.manifest import (
    ConfigChangedError,
    ManifestError,
    prepare_run,
    sha256_file,
)
from faultevolve.data.temporal_split import (
    REQUIRED_COLUMNS,
    SplitBoundaries,
    SplitError,
    assign_temporal_splits,
    audit_temporal_splits,
    select_cold_units,
    suggest_split_boundaries,
)
from faultevolve.tasks.smartmem_adapter import SmartMemAdapter
from faultevolve.tasks.smartmem_data import (
    ANCHOR_STRATEGIES,
    DEFAULT_ANCHOR_FREQUENCY,
    DEFAULT_HORIZON,
    DEFAULT_LEAD,
    DEFAULT_LOOKBACK,
    EPOCH_UNITS,
    MCELOG_EVENT_SCHEMA,
    SERIAL_COLUMN,
    SmartMemDataError,
    UNIT_TYPE_UNRESOLVED,
    aggregate_events_to_samples,
    anonymize_unit,
    build_unit_type_table,
    declared_error_types,
    error_type_counts,
    prepare_smartmem_chunk,
    read_smartmem_file,
    read_sorted_smartmem_file,
    read_tickets,
    render_policy_fingerprint,
    unit_from_filename,
)

PREP_VERSION = "smartmem-prep-v1"

#: The four outcomes section 7 defines. 1 and 2 differ on purpose: a bad input is the operator's
#: mistake now, a changed config means the run directory belongs to another experiment.
EXIT_OK = 0
EXIT_INPUT = 1
EXIT_CONFIG = 2
EXIT_PARTIAL = 3

EVENT_QUEUES = ("train", "type_A", "type_B")
TICKET_NAMES = ("ticket.csv", "failure_ticket.csv", "tickets.csv")
SAMPLES_DIR = "samples"
PROFILE_PARTITION = "profile"
AUDIT_PARTITION = "audit/summary"
#: One row per listed unit: the type the submission columns are grouped by,
#: with its declared source.
UNIT_TYPE_PARTITION = "units/serial_type"
#: The instants a split config must confirm before any sample is written.
BOUND_KEYS = ("start", "train_until", "dev_until", "val_until", "outcome_observed_until")
SAMPLE_COLUMNS = (
    "prediction_time",
    "history_start",
    "history_end",
    "label_window_start",
    "label_window_end",
)
#: A dry run has to estimate the time span, and reading every file to do it would cost the run.
SPAN_SAMPLE_FILES = 3
#: The ledger a sorted tree leaves behind, so a later step can find each unit's workspace without
#: the file names carrying a unit identifier.
SORT_LAYOUT_NAME = "layout.csv"
SORT_LAYOUT_COLUMNS = (
    "queue",
    "unit",
    "workspace",
    "rows",
    "runs",
    "reused",
    "source_bytes",
)
DEFAULT_UNITS_PER_PARTITION = 64
#: The error type domain measured on a 460-file sample of the shipped package on 2026-10-03 (that
#: sample holds 6 245 208 event rows; the mirror itself is 62 224 unit files). The sample spells its
#: types in exactly these three ways, and no event row spells one as UE. UE reaches the pipeline
#: from the failure ticket instead, so declaring it here would leave every error type feature
#: reading zero. A synthetic fixture that writes lowercase abbreviations has to declare its own
#: domain.
DEFAULT_ERROR_TYPES = ("CE.READ", "CE.SCRUB", "CE")
#: How many observed error types a refusal names: the message should point at the mismatch, not
#: inventory the tree.
DOMAIN_SHOWN = 5
#: Which reader produced the rows, recorded in every payload: a sorted tree and the raw files are
#: two different ways of reaching the same bytes, and a reader should be able to tell them apart.
EVENTS_RAW = "raw-files"
EVENTS_SORTED = "sorted-tree"
_EPOCH_LOOKING = re.compile(r"^\d{9,}$")


class PrepareError(ValueError):
    """A stop condition an operator can act on; its message is safe to print."""


class _ArgsError(Exception):
    """A command-line mistake; argparse would exit 2, which here means something else."""


class _Parser(argparse.ArgumentParser):
    """Parser that reports bad arguments through ``main`` so exit code 1 stays the input code."""

    def error(self, message: str) -> None:  # type: ignore[override]
        raise _ArgsError(message)


@dataclass(frozen=True)
class Options:
    """Everything the run needs, already converted to the types the data layer expects."""

    raw_dir: Path
    #: Every mode but ``--sort-inputs`` needs a run directory; the sort writes only ``--sort-dir``.
    out_dir: Path | None
    fmt: str
    timezone: str
    #: How a bare-number time column is read; ``None`` means the files state their own format.
    epoch_unit: str | None
    lookback: pd.Timedelta
    lead: pd.Timedelta
    horizon: pd.Timedelta
    anchor_frequency: pd.Timedelta
    anchor_strategy: str
    max_samples_per_unit: int
    seed: int
    cold_unit_fraction: float
    workers: int
    units_per_partition: int
    sort_dir: Path | None
    sort_inputs: bool
    #: A tree ``--sort-inputs`` wrote, read instead of the raw files; ``None`` reads the raw tree.
    from_sorted: Path | None
    max_files: int | None
    min_free_gb: float
    error_types: tuple[str, ...]
    bounds: dict[str, str]
    profile_only: bool
    dry_run: bool
    resume: bool
    hash_inputs: bool
    json_mode: bool


class Console:
    """Where each kind of output goes.

    Progress and errors always go to stderr. Stdout carries the human summary of a successful run,
    or - when ``--json`` was asked for - exactly one machine-readable object for every outcome,
    including the failed ones, so a caller can parse it without reading the exit code first.
    """

    def __init__(self, json_mode: bool) -> None:
        self.json_mode = json_mode

    def progress(self, message: str) -> None:
        print(f"[smartmem] {message}", file=sys.stderr)

    def emit(self, payload: dict, lines: Sequence[str]) -> None:
        if self.json_mode:
            print(json.dumps(payload, sort_keys=True, default=str))
            return
        for line in lines:
            print(line)

    def fail(self, code: int, message: str, payload: dict | None = None) -> None:
        print(message, file=sys.stderr)
        if not self.json_mode:
            return
        body = {"error": message} if payload is None else dict(payload)
        body["exit_code"] = int(code)
        print(json.dumps(body, sort_keys=True, default=str))


# ------------------------------------------------------------------- input discovery


def list_mcelog_files(raw_dir: Path, fmt: str) -> list[Path]:
    """Find the per-unit event files, in the layout the official package ships or a local ``train``.

    Sorted within each queue and queued in a fixed order, so two listings of the same directory
    produce the same partitions.
    """
    if fmt not in FORMATS:
        raise ValueError(f"unknown format: {fmt}")
    root = Path(raw_dir)
    found: list[Path] = []
    for queue in EVENT_QUEUES:
        directory = root / queue
        if directory.is_dir():
            found.extend(sorted(directory.glob(f"*.{fmt}")))
    if found:
        return found
    raise FileNotFoundError(
        f"no *.{fmt} event files under {root}; expected them in {', '.join(EVENT_QUEUES)}"
    )


def load_tickets(path: Path) -> pd.DataFrame:
    """Read the ticket table and check its shape; it is the only label source there is."""
    frame = pd.read_csv(path)
    SmartMemAdapter.validate_ticket_frame(frame)
    return frame


def _find_tickets(raw_dir: Path) -> Path:
    for name in TICKET_NAMES:
        candidate = raw_dir / name
        if candidate.is_file():
            return candidate
    raise PrepareError(
        f"no ticket file under {raw_dir}; looked for {', '.join(TICKET_NAMES)}. Without tickets "
        "every unit would be labeled negative, so this is not a gap to run through"
    )


def _units_of(files: Sequence[Path]) -> list[str]:
    units: list[str] = []
    seen: dict[str, int] = {}
    for path in files:
        unit = unit_from_filename(path)
        if unit in seen:
            raise PrepareError(
                f"unit {anonymize_unit(unit)} is listed twice, so its events would be read into "
                "two partitions; keep one file per unit"
            )
        seen[unit] = 1
        units.append(unit)
    return units


def _listing_fingerprint(files: Sequence[Path]) -> str:
    """One digest for the whole event listing, from names and sizes, without reading a byte.

    The strict alternative - hashing every file - costs a full pass over the dataset, so it is a
    flag. A fingerprint here still stops a resume from silently describing a different set of units.
    """
    digest = hashlib.sha256()
    for path in files:
        line = f"{anonymize_unit(unit_from_filename(path))}\x1f{path.stat().st_size}\n"
        digest.update(line.encode("utf-8"))
    return digest.hexdigest()


def _total_bytes(files: Sequence[Path]) -> int:
    return int(sum(int(path.stat().st_size) for path in files))


def _groups(items: Sequence[Path], size: int) -> list[list[Path]]:
    return [list(items[start : start + size]) for start in range(0, len(items), int(size))]


# ------------------------------------------------------------------- time boundaries


def _require_zone(timezone: str) -> str:
    try:
        ZoneInfo(timezone)
    except Exception as exc:  # zoneinfo raises different names across its backends
        raise PrepareError(
            f"--timezone {timezone!r} is not a known timezone; name an IANA zone such as UTC or "
            "Asia/Shanghai. Assuming one would move every label window by hours without saying so"
        ) from exc
    return timezone


def _instant(value: str, name: str, timezone: str) -> pd.Timestamp:
    text = str(value).strip()
    if _EPOCH_LOOKING.match(text):
        raise PrepareError(
            f"{name} looks like an epoch number ({text}); it carries neither a unit nor a "
            "timezone, so a split config must spell an ISO instant instead"
        )
    try:
        stamp = pd.Timestamp(text)
    except ValueError as exc:
        raise PrepareError(f"{name} is not an instant: {text!r}") from exc
    if stamp is pd.NaT:
        raise PrepareError(f"{name} is empty; every boundary must be confirmed before a run")
    if stamp.tz is None:
        stamp = stamp.tz_localize(timezone)
    return stamp.tz_convert("UTC")


def _read_split_config(path: Path) -> dict[str, str]:
    if not path.is_file():
        raise PrepareError(f"--split-config {path} is not a file")
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise PrepareError(
            f"--split-config {path} could not be read as YAML ({type(exc).__name__})"
        ) from exc
    if not isinstance(loaded, dict):
        raise PrepareError("--split-config must hold a mapping of boundary names to instants")
    bounds: dict[str, str] = {}
    for key, value in loaded.items():
        name = str(key)
        if name not in BOUND_KEYS:
            raise PrepareError(
                f"--split-config has an unknown key {name!r}; the recognized names are "
                f"{', '.join(BOUND_KEYS)}"
            )
        if value is not None:
            bounds[name] = str(value)
    return bounds


def _boundaries(bounds: dict[str, str], options: Options) -> tuple[SplitBoundaries, pd.Timestamp]:
    """Turn the confirmed instants into split edges, refusing a gap nobody observed.

    A real dataset often arrives without a follow-up cutoff; defaulting the zone or the coverage
    date would hide that, so a missing item stops the run by name.
    """
    missing = [key for key in BOUND_KEYS if key not in bounds]
    if missing:
        raise PrepareError(
            "the time boundaries must be confirmed before samples are written: --split-config is "
            f"missing {', '.join(missing)}"
        )
    instants = {key: _instant(bounds[key], key, options.timezone) for key in BOUND_KEYS}
    until = instants["outcome_observed_until"]
    try:
        limits = SplitBoundaries(
            train_end=instants["train_until"],
            dev_end=instants["dev_until"],
            val_end=instants["val_until"],
            embargo=options.lead + options.horizon,
            start=instants["start"],
        )
    except SplitError as exc:
        raise PrepareError(f"the confirmed boundaries are unusable: {exc}") from exc
    reach = limits.val_end + limits.embargo
    if reach > until:
        raise PrepareError(
            f"follow-up coverage ends at {until.isoformat()} but the last scored split needs "
            f"{reach.isoformat()} to close its label window; move val_until earlier or extend "
            "outcome_observed_until, because scoring that split would grade it against outcomes "
            "nobody observed"
        )
    return limits, until


def _bounds_payload(limits: SplitBoundaries) -> dict[str, str]:
    return {
        "start": limits.start.isoformat() if limits.start is not None else None,
        "train_end": limits.train_end.isoformat(),
        "dev_end": limits.dev_end.isoformat(),
        "val_end": limits.val_end.isoformat(),
        "embargo": str(limits.embargo),
    }


# ------------------------------------------------------------------- frames


def _event_reader(
    options: Options, sources: Mapping[Path, Path] | None
) -> Callable[[Path], pd.DataFrame]:
    """How one unit file becomes rows: read it as shipped, or read its verified sorted copy."""
    if sources is None:
        return lambda path: read_smartmem_file(
            path, fmt=options.fmt, timezone=options.timezone, epoch_unit=options.epoch_unit
        )
    return lambda path: read_sorted_smartmem_file(sources[path])


def _events_for(files: Sequence[Path], reader: Callable[[Path], pd.DataFrame]) -> pd.DataFrame:
    """Read one partition's units once, each with the same column and time policy."""
    frames = [reader(path) for path in files]
    return pd.concat(frames, ignore_index=True)


def _sample_build(
    files: Sequence[Path],
    options: Options,
    reader: Callable[[Path], pd.DataFrame],
    tickets: pd.DataFrame,
    limits: SplitBoundaries,
    until: pd.Timestamp,
    cold_units: Sequence[str],
) -> Callable[[], pd.DataFrame]:
    def build() -> pd.DataFrame:
        events = _events_for(files, reader)
        samples = aggregate_events_to_samples(
            events,
            tickets,
            outcome_observed_until=until,
            timezone=options.timezone,
            lookback=options.lookback,
            lead=options.lead,
            horizon=options.horizon,
            anchor_frequency=options.anchor_frequency,
            anchor_strategy=options.anchor_strategy,
            max_samples_per_unit=options.max_samples_per_unit,
            seed=options.seed,
            error_types=options.error_types,
        )
        return assign_temporal_splits(samples, limits, cold_units=cold_units)

    return build


def _read_partition(out_dir: Path, name: str) -> pd.DataFrame:
    """Read a written sample partition back with only the columns the audit inspects."""
    wanted = set(REQUIRED_COLUMNS) | set(SAMPLE_COLUMNS) | {"label"}
    frame = pd.read_csv(Path(out_dir) / "partitions" / name, usecols=lambda c: c in wanted)
    for column in SAMPLE_COLUMNS:
        frame[column] = pd.to_datetime(frame[column], format="ISO8601", utc=True)
    return frame


def _kv_frame(entries: Iterable[tuple[str, str, str, object]]) -> pd.DataFrame:
    """A small tidy table, which is the only shape that survives the partition writer."""
    rows = sorted(entries, key=lambda entry: (entry[0], entry[1], entry[2]))
    return pd.DataFrame(
        [(scope, name, metric, value) for scope, name, metric, value in rows],
        columns=["scope", "name", "metric", "value"],
    )


def _audit_entries(audit: dict) -> list[tuple[str, str, str, object]]:
    entries: list[tuple[str, str, str, object]] = [
        ("run", "", "passed", bool(audit["passed"])),
        ("run", "", "rows", int(audit["rows"])),
        ("run", "", "embargo_removed", int(audit["embargo_removed"])),
        ("run", "", "cold_units", int(audit["cold_units"])),
        ("run", "", "embargo", str(audit["embargo"])),
    ]
    for name, value in sorted(audit["boundaries"].items()):
        entries.append(("boundary", name, "instant", value))
    for key, count in sorted(audit["splits"].items()):
        entries.append(("split", key, "rows", int(count)))
    for violation, count in sorted(audit["violations"].items()):
        entries.append(("violation", violation, "rows", int(count)))
    return entries


def _profile_entries(
    files: Sequence[Path], options: Options
) -> tuple[list[tuple[str, str, str, object]], dict[str, int]]:
    """Merge per-file profiles, stating what a merged number means.

    Cardinality cannot be summed exactly across files, so the field says ``distinct_upper_bound``
    rather than pretending the value is exact. The second return value is the error type domain the
    tree holds, which the caller checks against the declared one before anything is written.
    """
    columns: dict[str, dict[str, object]] = {}
    domain: dict[str, int] = {}
    units: set[str] = set()
    rows = 0
    empty_files = 0
    time_min: pd.Timestamp | None = None
    time_max: pd.Timestamp | None = None
    for path in files:
        frame = read_smartmem_file(
            path, fmt=options.fmt, timezone=options.timezone, epoch_unit=options.epoch_unit
        )
        if not len(frame):
            empty_files += 1
            continue
        for value, counted in error_type_counts(frame).items():
            domain[value] = domain.get(value, 0) + int(counted)
        units.update(str(unit) for unit in frame[SERIAL_COLUMN].unique())
        profile = build_event_profile(frame, MCELOG_EVENT_SCHEMA)
        file_rows = int(profile["row_count"])
        rows += file_rows
        low = pd.Timestamp(profile["time_range"]["min"])
        high = pd.Timestamp(profile["time_range"]["max"])
        time_min = low if time_min is None or low < time_min else time_min
        time_max = high if time_max is None or high > time_max else time_max
        for name, stats in profile["columns"].items():
            state = columns.setdefault(
                str(name),
                {
                    "dtype": str(stats["dtype"]),
                    "dtype_varies": False,
                    "missing_rows": 0,
                    "rows": 0,
                    "distinct": 0,
                },
            )
            if state["dtype"] != str(stats["dtype"]):
                state["dtype_varies"] = True
            state["rows"] = int(state["rows"]) + file_rows
            state["missing_rows"] = int(state["missing_rows"]) + round(
                float(stats["missing_rate"]) * file_rows
            )
            cardinality = 0 if stats["cardinality"] is None else int(stats["cardinality"])
            state["distinct"] = int(state["distinct"]) + cardinality

    entries: list[tuple[str, str, str, object]] = [
        ("run", "", "row_count", rows),
        ("run", "", "unit_count", len(units)),
        ("run", "", "file_count", len(files)),
        ("run", "", "empty_files", empty_files),
        ("run", "", "time_min", None if time_min is None else time_min.isoformat()),
        ("run", "", "time_max", None if time_max is None else time_max.isoformat()),
    ]
    for name, state in columns.items():
        counted = int(state["rows"])
        entries.append(("column", name, "dtype", str(state["dtype"])))
        entries.append(("column", name, "dtype_varies", bool(state["dtype_varies"])))
        entries.append(("column", name, "missing_rows", int(state["missing_rows"])))
        entries.append(
            (
                "column",
                name,
                "missing_rate",
                None if counted == 0 else round(int(state["missing_rows"]) / counted, 6),
            )
        )
        entries.append(("column", name, "distinct_upper_bound", int(state["distinct"])))
    # a declared name the tree never shows gets its own zero row, so a gap is printed not inferred
    for name in sorted(set(domain) | set(options.error_types)):
        entries.append(("error_type", name, "rows", int(domain.get(name, 0))))
    return entries, domain


# ------------------------------------------------------------------- planning


def _sampled_for_span(files: Sequence[Path]) -> list[Path]:
    """First, middle and last file, which is the cheapest honest look at the time span."""
    picks = {0, len(files) // 2, len(files) - 1}
    return [files[index] for index in sorted(picks) if index < len(files)]


def _estimate_span(
    files: Sequence[Path], reader: Callable[[Path], pd.DataFrame]
) -> tuple[pd.Timestamp, pd.Timestamp]:
    time_column = MCELOG_EVENT_SCHEMA.time_col
    low: pd.Timestamp | None = None
    high: pd.Timestamp | None = None
    for path in _sampled_for_span(files):
        frame = reader(path)
        if not len(frame):
            continue
        stamps = frame[time_column]
        first = stamps.min()
        last = stamps.max()
        low = first if low is None or first < low else low
        high = last if high is None or last > high else high
    if low is None or high is None:
        raise PrepareError(
            "the sampled unit files hold no rows, so the time span cannot be estimated; confirm "
            "the boundaries in --split-config instead of letting a run guess them"
        )
    return pd.Timestamp(low), pd.Timestamp(high)


def _space_needed(files: Sequence[Path], out_dir: Path) -> tuple[int, int]:
    free = shutil.disk_usage(_space_probe(out_dir)).free
    return _total_bytes(files), int(free)


def _space_probe(out_dir: Path) -> Path:
    """A directory that exists on the filesystem the output will live on."""
    candidate = Path(out_dir)
    while not candidate.exists() and candidate.parent != candidate:
        candidate = candidate.parent
    return candidate


def _require_space(out_dir: Path, min_free_gb: float) -> None:
    if float(min_free_gb) <= 0:
        return
    free = float(shutil.disk_usage(_space_probe(out_dir)).free)
    if free < float(min_free_gb) * 1_000_000_000:
        raise PrepareError(
            f"only {free / 1_000_000_000:.2f} GB free at the output location, below the declared "
            f"--min-free-gb {float(min_free_gb):g}; a run that fills the disk leaves a "
            "half-written partition nobody can trust"
        )


def _unit_type_fingerprint(unit_types: pd.DataFrame) -> str:
    """Digest the unit -> type side table, so a resume cannot pair new samples with a stale table.

    ``_listing_fingerprint`` records only names and sizes, which is what makes a 130 GB resume
    affordable - and what lets the same 200 units move from ``type_A`` to ``type_B`` without
    changing it. The declared type travels with the queue directory, so this digest is the half
    of that check the listing cannot make.
    """
    lines = [
        f"{row.unit_id}|{row.serial_number_type}|{row.source}"
        for row in unit_types.itertuples(index=False)
    ]
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def _config_payload(
    options: Options, files: Sequence[Path], fingerprint: str, unit_types: pd.DataFrame
) -> dict[str, object]:
    """The part of the invocation that changes the bytes of an output.

    The rendering policy is in because it decides bytes: the declared dtype of a feature and the
    way ``canonicalize_feature_types`` spells it are as much a part of "which run made this
    partition" as the lookback window is, and its digest goes in rather than the table itself so
    the hash stays a fixed size.

    ``workers``, ``--resume``, ``--json`` and ``--min-free-gb`` stay out on purpose: they decide
    how a run happens, not what a partition holds, and raising the worker count must never make a
    resume look like a new experiment. ``--from-sorted`` stays out for the same reason: a tree whose
    digests still match the raw files is a different route to the same bytes, and the two runs
    should record the same config hash.
    """
    return {
        "anchor_frequency": str(options.anchor_frequency),
        "anchor_strategy": options.anchor_strategy,
        "cold_unit_fraction": float(options.cold_unit_fraction),
        "error_types": list(options.error_types),
        "epoch_unit": options.epoch_unit,
        "event_listing": fingerprint,
        "format": options.fmt,
        "horizon": str(options.horizon),
        "inputs_hashed": bool(options.hash_inputs),
        "lead": str(options.lead),
        "lookback": str(options.lookback),
        "max_files": None if options.max_files is None else int(options.max_files),
        "max_samples_per_unit": int(options.max_samples_per_unit),
        "render_policy_fingerprint": render_policy_fingerprint(),
        "seed": int(options.seed),
        "split": {key: options.bounds.get(key) for key in BOUND_KEYS},
        "timezone": options.timezone,
        "unit_type_fingerprint": _unit_type_fingerprint(unit_types),
        "units_per_partition": int(options.units_per_partition),
        "files": len(files),
    }


# ------------------------------------------------------------------- run modes


def _events_label(options: Options) -> str:
    return EVENTS_SORTED if options.from_sorted is not None else EVENTS_RAW


def _dry_run(
    options: Options,
    files: Sequence[Path],
    reader: Callable[[Path], pd.DataFrame],
    console: Console,
) -> int:
    """Validate the inputs and report a plan; writes nothing, so it cannot damage a run."""
    groups = _groups(files, options.units_per_partition)
    total_bytes, free_bytes = _space_needed(files, options.out_dir)
    low, high = _estimate_span(files, reader)
    missing = [key for key in BOUND_KEYS if key not in options.bounds]
    configured: SplitBoundaries | None = None
    if not missing:
        configured, _ = _boundaries(options.bounds, options)
    # The estimate is checked on its own, without a coverage cutoff, so a dry run can report a
    # suggestion even while the operator is still deciding how far the follow-up reaches.
    suggested = suggest_split_boundaries(
        low,
        high,
        lead=options.lead,
        horizon=options.horizon,
        anchor_frequency=options.anchor_frequency,
        outcome_observed_until=None,
    )
    payload = {
        "exit_code": EXIT_OK,
        "mode": "dry-run",
        "algorithm_version": PREP_VERSION,
        "files": len(files),
        "events": _events_label(options),
        "bytes": total_bytes,
        "free_bytes": free_bytes,
        "partitions": len(groups),
        "workers": int(options.workers),
        "span_sampled_files": len(_sampled_for_span(files)),
        "span": {"min": low.isoformat(), "max": high.isoformat()},
        "suggested_bounds": _bounds_payload(suggested),
        "confirmed_bounds": None if configured is None else _bounds_payload(configured),
        "missing_bounds": missing,
    }
    lines = [
        f"dry run: {len(files)} unit files ({total_bytes} bytes) would form {len(groups)} "
        f"partitions of up to {options.units_per_partition} units",
        f"event span sampled from {payload['span_sampled_files']} files: "
        f"{low.isoformat()} .. {high.isoformat()}",
        "suggested bounds (an estimate from that sample; confirm them in --split-config before "
        f"a real run): train_end={suggested.train_end.isoformat()} "
        f"dev_end={suggested.dev_end.isoformat()} val_end={suggested.val_end.isoformat()}",
        f"free space at the output location: {free_bytes} bytes",
    ]
    if missing:
        lines.append(f"still missing from --split-config: {', '.join(missing)}")
    console.emit(payload, lines)
    return EXIT_OK


def _profile_run(options: Options, files: Sequence[Path], console: Console) -> int:
    """One partition of anonymous schema facts, cheap enough to run before the boundaries exist."""
    ticket_path = _find_tickets(options.raw_dir)
    tickets = read_tickets(
        ticket_path, timezone=options.timezone, epoch_unit=options.epoch_unit
    )
    manifest = _open_run(options, files, [ticket_path], build_unit_type_table(files, tickets))
    entries, domain = _profile_entries(files, options)
    _require_declared_domain(options, domain)
    job = PartitionJob(PROFILE_PARTITION, lambda: _kv_frame(entries))
    result = write_partitions(options.out_dir, [job], workers=1, owner=_owner())
    payload = {
        "exit_code": EXIT_PARTIAL if result["failed"] else EXIT_OK,
        "mode": "profile-only",
        "algorithm_version": PREP_VERSION,
        "config_hash": manifest["config_hash"],
        "files": len(files),
        "ticket_rows": int(len(tickets)),
        **{key: value for key, value in result.items()},
    }
    lines = [
        f"profiled {len(files)} unit files into {result['written'] + result['reused']}",
        f"failed partitions: {len(result['failed'])}",
    ]
    console.emit(payload, lines)
    return EXIT_PARTIAL if result["failed"] else EXIT_OK


def _owner() -> str:
    return f"prepare-{os.getpid()}"


def _require_declared_domain(options: Options, domain: Mapping[str, int]) -> None:
    """Refuse a profile whose declared error type domain covers not one row of the events.

    A misspelled domain still writes a complete sample table: every error type column reads zero
    and the only trace is a large ``unexpected_error_type_count`` nobody compares. The package this
    pipeline is pointed at spells its types in uppercase with dots, so a case difference alone is
    enough to empty the features without an error anywhere.
    """
    declared = set(options.error_types)
    if any(rows for name, rows in domain.items() if name in declared):
        return
    if domain:
        shown = ", ".join(repr(name) for name in sorted(domain)[:DOMAIN_SHOWN])
        if len(domain) > DOMAIN_SHOWN:
            shown += f", plus {len(domain) - DOMAIN_SHOWN} more"
    else:
        shown = "no error_type value at all"
    raise PrepareError(
        f"the declared error types {options.error_types!r} cover no event row, which holds "
        f"{shown}; the domain is compared as spelled, so fix --error-types rather than the files"
    )


def _open_run(
    options: Options, files: Sequence[Path], extra_inputs: Sequence[Path], unit_types: pd.DataFrame
) -> dict:
    paths = list(extra_inputs)
    if options.hash_inputs:
        paths = sorted(paths, key=str) + list(files)
    config = _config_payload(options, files, _listing_fingerprint(files), unit_types)
    manifest = prepare_run(
        options.out_dir,
        raw_dir=options.raw_dir,
        paths=paths,
        config=config,
        algorithm_version=PREP_VERSION,
    )
    if manifest["partitions"] and not options.resume:
        raise PrepareError(
            f"the run directory already records {len(manifest['partitions'])} partition(s); pass "
            "--resume to reuse the ones whose digest still matches instead of starting over"
        )
    return manifest


def _coverage_entries(
    tickets: pd.DataFrame, until: pd.Timestamp, samples: pd.DataFrame
) -> dict[str, object]:
    """Say how far the tickets actually reach, beside the frontier that claims they cover all of it.

    ``audit_temporal_splits`` checks leakage and that every split holds rows; it has no view
    on which dates the label source covers. So a frontier past the last alarm passes the audit
    while every later row is a negative nobody observed - measured on 200 real units as 1 866
    rows, 9.5% of the table. These three fields turn that into a number in the run payload
    instead of a claim in a doc.
    """
    alarms = tickets["failure_time"].dropna()
    coverage_end = None if alarms.empty else pd.Timestamp(alarms.max())
    beyond = (
        int(samples["prediction_time"].notna().sum())
        if coverage_end is None
        else int((samples["prediction_time"] > coverage_end).sum())
    )
    return {
        "ticket_coverage_end": None if coverage_end is None else coverage_end.isoformat(),
        "outcome_observed_until": until.isoformat(),
        "rows_beyond_coverage": beyond,
    }


def _sample_run(
    options: Options,
    files: Sequence[Path],
    units: Sequence[str],
    reader: Callable[[Path], pd.DataFrame],
    console: Console,
) -> int:
    limits, until = _boundaries(options.bounds, options)
    ticket_path = _find_tickets(options.raw_dir)
    tickets = read_tickets(
        ticket_path, timezone=options.timezone, epoch_unit=options.epoch_unit
    )
    unit_types = build_unit_type_table(files, tickets)
    manifest = _open_run(options, files, [ticket_path], unit_types)
    cold_units = select_cold_units(units, fraction=options.cold_unit_fraction, seed=options.seed)
    groups = _groups(files, options.units_per_partition)
    sample_jobs = [
        PartitionJob(
            f"{SAMPLES_DIR}/part-{index:05d}",
            _sample_build(group, options, reader, tickets, limits, until, cold_units),
        )
        for index, group in enumerate(groups)
    ]
    jobs = sample_jobs + [PartitionJob(UNIT_TYPE_PARTITION, lambda: unit_types)]
    console.progress(f"{len(files)} unit files planned as {len(sample_jobs)} sample partitions")
    result = write_partitions(
        options.out_dir, jobs, workers=options.workers, owner=_owner()
    )
    payload: dict[str, object] = {
        "algorithm_version": PREP_VERSION,
        "config_hash": manifest["config_hash"],
        "files": len(files),
        "events": _events_label(options),
        "partitions": len(jobs),
        "cold_units": len(cold_units),
        "unit_types": {
            "rows": int(len(unit_types)),
            "declared": int((unit_types["source"] != UNIT_TYPE_UNRESOLVED).sum()),
            "unresolved": int((unit_types["source"] == UNIT_TYPE_UNRESOLVED).sum()),
        },
        **{key: value for key, value in result.items()},
    }
    if result["failed"]:
        names = ", ".join(sorted(entry["name"] for entry in result["failed"]))
        console.fail(
            EXIT_PARTIAL,
            f"{len(result['failed'])} of {len(jobs)} partition(s) failed ({names}); the "
            "written outputs stay for diagnosis but the run is not complete and no audit is "
            "recorded",
            payload,
        )
        return EXIT_PARTIAL

    assembled = pd.concat(
        [_read_partition(options.out_dir, job.name) for job in sample_jobs], ignore_index=True
    )
    # coverage comes first because the case it describes is exactly the one the audit calls fine
    payload["coverage"] = _coverage_entries(tickets, until, assembled)
    audit = audit_temporal_splits(assembled, limits, cold_units=cold_units)
    payload["audit"] = audit
    if not audit["passed"]:
        detail = ", ".join(f"{key}={value}" for key, value in sorted(audit["violations"].items()))
        console.fail(
            EXIT_INPUT,
            f"the split audit found violations ({detail}), so these samples are not a usable "
            "evaluation set; the partitions stay on disk for inspection",
            payload,
        )
        return EXIT_INPUT

    audit_job = PartitionJob(AUDIT_PARTITION, lambda: _kv_frame(_audit_entries(audit)))
    audit_result = write_partitions(options.out_dir, [audit_job], workers=1, owner=_owner())
    payload["exit_code"] = EXIT_OK
    payload["audit_reused"] = AUDIT_PARTITION in audit_result["reused"]
    coverage = payload["coverage"]
    beyond = int(coverage["rows_beyond_coverage"])
    lines = [
        f"wrote {len(sample_jobs)} sample partition(s) plus {UNIT_TYPE_PARTITION}, reused "
        f"{len(result['reused'])}; {len(assembled)} sample row(s)",
        "splits: " + ", ".join(f"{key}={count}" for key, count in sorted(audit["splits"].items())),
        f"unit types: {payload['unit_types']['declared']} of "
        f"{payload['unit_types']['rows']} unit(s) carry a declared serial_number_type, "
        f"{payload['unit_types']['unresolved']} unresolved",
        f"audit {AUDIT_PARTITION}: passed",
    ]
    if beyond:
        end = coverage["ticket_coverage_end"]
        lines.append(
            f"coverage: the latest ticket is {end} and {beyond} of {len(assembled)} row(s) are "
            "anchored later, so those labels are assumed rather than observed"
        )
    if options.from_sorted is not None:
        lines.append("events read from the sorted tree, after its layout and every digest matched")
    console.emit(payload, lines)
    return EXIT_OK


# ------------------------------------------------------------------- entry point


def _positive_int(value: str) -> int:
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("must be a positive whole number")
    return number


def _ratio(value: str) -> float:
    number = float(value)
    if not 0.0 <= number <= 1.0:
        raise argparse.ArgumentTypeError("must be a fraction between 0 and 1")
    return number


def _build_parser() -> argparse.ArgumentParser:
    parser = _Parser(
        prog="prepare_data.py", description="Build SmartMem samples into a run directory."
    )
    parser.add_argument("--raw-dir", required=True, type=Path)
    # The sort mode writes into --sort-dir only, so --out-dir stays optional at the parser and is
    # demanded by the modes that need it - see _require_out_dir.
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--format", default="csv", choices=FORMATS)
    parser.add_argument("--timezone", required=True)
    # The shipped package writes log_time and failure_time as bare integers, which cannot tell a
    # second from a millisecond; the unit is declared rather than guessed.
    parser.add_argument("--epoch-unit", default=None, choices=EPOCH_UNITS)
    parser.add_argument("--lookback-days", type=float, default=float(DEFAULT_LOOKBACK.days))
    parser.add_argument(
        "--lead-minutes", type=float, default=float(DEFAULT_LEAD / pd.Timedelta(minutes=1))
    )
    parser.add_argument(
        "--horizon-days", type=float, default=float(DEFAULT_HORIZON / pd.Timedelta(days=1))
    )
    parser.add_argument(
        "--sample-every-minutes",
        type=float,
        default=float(DEFAULT_ANCHOR_FREQUENCY / pd.Timedelta(minutes=1)),
    )
    parser.add_argument("--anchor-strategy", default="event", choices=ANCHOR_STRATEGIES)
    parser.add_argument("--max-samples-per-dimm", type=_positive_int, default=200)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--cold-unit-fraction", type=_ratio, default=0.0)
    parser.add_argument("--error-types", default=",".join(DEFAULT_ERROR_TYPES))
    parser.add_argument("--workers", type=_positive_int, default=1)
    parser.add_argument(
        "--units-per-partition", type=_positive_int, default=DEFAULT_UNITS_PER_PARTITION
    )
    parser.add_argument("--max-files", type=_positive_int, default=None)
    parser.add_argument("--sort-dir", type=Path, default=None)
    parser.add_argument("--sort-inputs", action="store_true")
    parser.add_argument("--from-sorted", type=Path, default=None)
    parser.add_argument("--min-free-gb", type=float, default=0.0)
    parser.add_argument("--outcome-observed-until", default=None)
    parser.add_argument("--split-config", type=Path, default=None)
    parser.add_argument("--profile-only", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--hash-inputs", action="store_true")
    return parser


def _sort_space(files: Sequence[Path], sort_dir: Path, fmt: str) -> tuple[int, int, int]:
    """Bytes the whole tree needs, bytes the volume has, and the gap between them.

    Computed before any workspace exists, so an operator learns the size rather than the failure.
    """
    needed = sum(estimate_space_bytes(path, fmt=fmt) for path in files)
    free = int(shutil.disk_usage(_space_probe(sort_dir)).free)
    return int(needed), free, max(0, needed - free)


def _require_sort_dir(options: Options) -> Path:
    if options.sort_dir is None:
        raise PrepareError(
            "--sort-dir is required with --sort-inputs: the sort writes one workspace per unit and "
            "needs a directory of its own, never the raw tree it is reading"
        )
    if options.profile_only:
        raise PrepareError(
            "--sort-inputs and --profile-only ask for one mode at a time; profile the raw tree "
            "first, then sort the files it says are unordered"
        )
    sort_dir = Path(options.sort_dir)
    raw = options.raw_dir.resolve()
    resolved = sort_dir.resolve()
    if resolved == raw or raw in resolved.parents:
        raise PrepareError(
            "the sort directory is inside the raw tree, so a later listing would read the sorted "
            "copies as if they were inputs and count every unit twice; keep them apart"
        )
    return sort_dir


def _sort_units(
    files: Sequence[Path], sort_dir: Path, options: Options
) -> list[dict[str, object]]:
    """Sort every listed unit file into its own workspace and return the ledger rows.

    The workspace path carries only the anonymized unit, while the sorted rows keep the declared
    unit inside their own column: a file name may be a serial number, and a sorted tree is the kind
    of artefact that ends up in a screenshot.
    """
    column = MCELOG_EVENT_SCHEMA.time_col
    entries: list[dict[str, object]] = []
    for path in files:
        unit = unit_from_filename(path)

        def prepare(chunk: pd.DataFrame) -> pd.DataFrame:
            # Declaring the unit lets the normaliser check a chunk against the file it came from.
            # One closure per file is enough: the sort consumes it inside this same call, so a
            # mis-bound unit raises there rather than reordering a stranger's rows.
            return prepare_smartmem_chunk(
                chunk, unit=unit, timezone=options.timezone, epoch_unit=options.epoch_unit
            )

        workspace = sort_dir / path.parent.name / anonymize_unit(unit)
        result = sort_file_to_time_order(
            path,
            out_dir=workspace,
            time_column=column,
            fmt=options.fmt,
            prepare=prepare,
        )
        entries.append(
            {
                "queue": path.parent.name,
                "unit": anonymize_unit(unit),
                "workspace": str(workspace.relative_to(sort_dir)),
                "rows": int(result.rows),
                "runs": int(result.runs),
                "reused": bool(result.reused),
                "source_bytes": int(path.stat().st_size),
            }
        )
    return entries


def _write_layout(sort_dir: Path, entries: Sequence[dict[str, object]]) -> None:
    """The index that lets a later step find each unit without a unit id in a file name."""
    frame = pd.DataFrame(list(entries), columns=list(SORT_LAYOUT_COLUMNS))
    target = sort_dir / SORT_LAYOUT_NAME
    temporary = target.with_name(f"{target.name}.tmp")
    frame.to_csv(temporary, index=False, lineterminator="\n")
    os.replace(temporary, target)


def _sort_run(options: Options, files: Sequence[Path], console: Console) -> int:
    """Sort mode: one bounded external sort per unit file, into a tree this step owns."""
    sort_dir = _require_sort_dir(options)
    needed, free, shortfall = _sort_space(files, sort_dir, options.fmt)
    space = {
        "needed_bytes": needed,
        "free_bytes": free,
        "shortfall_bytes": shortfall,
        "sufficient": shortfall == 0,
    }
    if options.dry_run:
        payload = {
            "exit_code": EXIT_OK,
            "mode": "sort-inputs",
            "algorithm_version": PREP_VERSION,
            "files": len(files),
            "space": space,
            "written": False,
        }
        lines = [
            f"sort plan: {len(files)} unit files would need {needed} bytes on a volume with "
            f"{free} free",
            "nothing was written; drop --dry-run to run the sorts",
        ]
        console.emit(payload, lines)
        return EXIT_OK
    if shortfall:
        raise PrepareError(
            f"the sort needs {needed} bytes, the volume holds {free} free, {shortfall} bytes are "
            "missing; point --sort-dir at a larger volume instead of starting a run that cannot "
            "finish its merge"
        )
    console.progress("sorting unit files into a tree under --sort-dir")
    entries = _sort_units(files, sort_dir, options)
    _write_layout(sort_dir, entries)
    rows = sum(int(entry["rows"]) for entry in entries)
    reused = sum(1 for entry in entries if entry["reused"])
    payload = {
        "exit_code": EXIT_OK,
        "mode": "sort-inputs",
        "algorithm_version": PREP_VERSION,
        "files": len(files),
        "rows": rows,
        "reused": reused,
        "space": space,
        "layout": SORT_LAYOUT_NAME,
    }
    lines = [
        f"sorted {len(files)} unit files into {sort_dir} "
        f"({rows} rows, {reused} reused from a checkpoint)",
        f"layout index: {SORT_LAYOUT_NAME}",
    ]
    console.emit(payload, lines)
    return EXIT_OK


def _require_sorted_entry(options: Options) -> Path:
    """Refuse a consume run that is really two modes, then hand back the tree to read."""
    if options.sort_inputs:
        raise PrepareError(
            "one mode at a time: --from-sorted reads a tree that --sort-inputs has already written"
        )
    if options.profile_only:
        raise PrepareError(
            "one mode at a time: --profile-only describes the raw files as shipped, and a sorted "
            "tree is a derived artefact, not the input a profile is about"
        )
    return Path(options.from_sorted)


def _sorted_layout(root: Path) -> dict[tuple[str, str], str]:
    """Read the tree's index back as the ``(queue, unit)`` to workspace map it is meant to be."""
    path = root / SORT_LAYOUT_NAME
    if not path.is_file():
        raise PrepareError(
            f"{root} holds no {SORT_LAYOUT_NAME}; only --sort-inputs writes one, so run that step "
            "with --sort-dir pointed here before asking a sample run to read it"
        )
    frame = pd.read_csv(path)
    if list(frame.columns) != list(SORT_LAYOUT_COLUMNS):
        raise PrepareError(
            f"{path} does not hold the columns this step writes: expected "
            f"{', '.join(SORT_LAYOUT_COLUMNS)}, found {', '.join(str(c) for c in frame.columns)}"
        )
    lookup: dict[tuple[str, str], str] = {}
    for _, row in frame.iterrows():
        key = (str(row["queue"]), str(row["unit"]))
        if key in lookup:
            raise PrepareError(
                f"{SORT_LAYOUT_NAME} names unit {key[1]} of queue {key[0]} twice, so the run "
                "cannot tell which workspace to read"
            )
        lookup[key] = str(row["workspace"])
    return lookup


def _verified_workspace(root: Path, relative: str, unit: str, source: Path) -> Path:
    """One workspace of the tree, checked against the two digests the sort recorded for it."""
    directory = root / relative
    merged = directory / MERGED_FILE_NAME
    sidecar = directory / SORT_SIDECAR_NAME
    if not merged.is_file():
        raise PrepareError(
            f"the workspace {relative} named by {SORT_LAYOUT_NAME} holds no {MERGED_FILE_NAME}"
        )
    if not sidecar.is_file():
        raise PrepareError(
            f"the workspace {relative} named by {SORT_LAYOUT_NAME} holds no {SORT_SIDECAR_NAME}, "
            "so its contents cannot be checked"
        )
    try:
        recorded = json.loads(sidecar.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise PrepareError(
            f"{relative}/{SORT_SIDECAR_NAME} is not readable JSON: {type(exc).__name__}"
        ) from exc
    if not isinstance(recorded, dict) or not {"input_sha256", "output_sha256"} <= set(recorded):
        raise PrepareError(
            f"{relative}/{SORT_SIDECAR_NAME} records no input and output digest, so this run "
            "cannot tell what the sorted copy was made from"
        )
    if str(recorded["input_sha256"]) != sha256_file(source):
        raise PrepareError(
            f"unit {unit} changed after it was sorted: the raw file's digest is not the one "
            f"{SORT_SIDECAR_NAME} recorded, so re-run --sort-inputs before reading this tree"
        )
    if str(recorded["output_sha256"]) != sha256_file(merged):
        raise PrepareError(
            f"the sorted file of unit {unit} no longer matches the digest written beside it; "
            "the tree was edited or truncated after the sort wrote it"
        )
    return merged


def _sorted_event_files(options: Options, files: Sequence[Path]) -> dict[Path, Path]:
    """Map every requested unit file onto its verified sorted copy, or refuse the tree.

    The checks run over the whole listing before a row is read: a run that sampled from a tree
    which no longer matches the raw files would report what the inputs cannot back up. A digest
    is the only claim about a file that survives being copied somewhere else.
    """
    root = _require_sorted_entry(options)
    lookup = _sorted_layout(root)
    sources: dict[Path, Path] = {}
    uncovered: list[str] = []
    for path in files:
        unit = anonymize_unit(unit_from_filename(path))
        relative = lookup.get((path.parent.name, unit))
        if relative is None:
            uncovered.append(unit)
            continue
        sources[path] = _verified_workspace(root, relative, unit, path)
    if uncovered:
        raise PrepareError(
            f"{len(uncovered)} of {len(files)} unit file(s) have no row in {SORT_LAYOUT_NAME} "
            f"(for instance unit {uncovered[0]}); the tree does not cover this listing, so "
            "re-run --sort-inputs over it"
        )
    return sources


def _require_out_dir(options: Options) -> Path:
    """Resolve the run directory for the modes that write one.

    Returning the path instead of only checking keeps a caller from reaching for the optional field
    again after the guard has already resolved it.
    """
    if options.out_dir is None:
        raise _ArgsError(
            "--out-dir is required for every mode except --sort-inputs, which writes --sort-dir"
        )
    return Path(options.out_dir)


def _read_options(args: argparse.Namespace) -> Options:
    bounds = _read_split_config(args.split_config) if args.split_config is not None else {}
    if args.outcome_observed_until:
        bounds["outcome_observed_until"] = str(args.outcome_observed_until)
    timezone = _require_zone(str(args.timezone))
    error_types = declared_error_types(str(args.error_types).split(","))
    return Options(
        raw_dir=Path(args.raw_dir),
        out_dir=None if args.out_dir is None else Path(args.out_dir),
        fmt=str(args.format),
        timezone=timezone,
        epoch_unit=None if args.epoch_unit is None else str(args.epoch_unit),
        lookback=pd.Timedelta(days=float(args.lookback_days)),
        lead=pd.Timedelta(minutes=float(args.lead_minutes)),
        horizon=pd.Timedelta(days=float(args.horizon_days)),
        anchor_frequency=pd.Timedelta(minutes=float(args.sample_every_minutes)),
        anchor_strategy=str(args.anchor_strategy),
        max_samples_per_unit=int(args.max_samples_per_dimm),
        seed=int(args.seed),
        cold_unit_fraction=float(args.cold_unit_fraction),
        workers=int(args.workers),
        units_per_partition=int(args.units_per_partition),
        sort_dir=None if args.sort_dir is None else Path(args.sort_dir),
        sort_inputs=bool(args.sort_inputs),
        from_sorted=None if args.from_sorted is None else Path(args.from_sorted),
        max_files=None if args.max_files is None else int(args.max_files),
        min_free_gb=float(args.min_free_gb),
        error_types=error_types,
        bounds=bounds,
        profile_only=bool(args.profile_only),
        dry_run=bool(args.dry_run),
        resume=bool(args.resume),
        hash_inputs=bool(args.hash_inputs),
        json_mode=bool(args.json),
    )


def _fail(console: Console, error: BaseException, code: int) -> int:
    console.fail(code, f"{type(error).__name__}: {error}")
    return code


def _code_for(error: BaseException) -> int:
    return EXIT_CONFIG if isinstance(error, ConfigChangedError) else EXIT_INPUT


def main(argv: list[str] | None = None) -> int:
    words = list(sys.argv[1:] if argv is None else argv)
    console = Console("--json" in words)
    try:
        options = _read_options(_build_parser().parse_args(words))
        if options.from_sorted is not None:
            _require_sorted_entry(options)
        files = list_mcelog_files(options.raw_dir, options.fmt)
        if options.max_files is not None:
            files = files[: options.max_files]
        if not files:
            raise PrepareError(f"{options.raw_dir} holds no *.{options.fmt} unit file")
        units = _units_of(files)
        if options.sort_inputs:
            return _sort_run(options, files, console)
        sources = None
        if options.from_sorted is not None:
            sources = _sorted_event_files(options, files)
        reader = _event_reader(options, sources)
        out_dir = _require_out_dir(options)
        _require_space(out_dir, options.min_free_gb)
        if options.dry_run:
            return _dry_run(options, files, reader, console)
        if options.profile_only:
            return _profile_run(options, files, console)
        return _sample_run(options, files, units, reader, console)
    except (
        _ArgsError,
        PrepareError,
        SplitError,
        SmartMemDataError,
        ManifestError,
        IoError,
        SortError,
        OSError,
    ) as exc:
        return _fail(console, exc, _code_for(exc))


__all__ = [
    "EXIT_CONFIG",
    "EXIT_INPUT",
    "EXIT_OK",
    "EXIT_PARTIAL",
    "PREP_VERSION",
    "Options",
    "PrepareError",
    "list_mcelog_files",
    "load_tickets",
    "main",
]


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
