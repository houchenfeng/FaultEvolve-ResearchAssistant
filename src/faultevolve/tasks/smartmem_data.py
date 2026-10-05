"""SmartMem domain layer: turn one unit file or the ticket table into canonical frames.

Two different schemas are in circulation for this dataset - the official 23 lowercase mcelog
names and a 24-column PascalCase export whose ``LogTime`` is int64 epoch seconds - so nothing here
guesses. Column names come from an explicit mapping, an epoch column needs its unit and timezone
declared, exact duplicate rows are the only duplicates removed, and a serial number never reaches
an error message: identifiers are masked with a short irreversible hash first.

The second half of this module builds the knowledge-pack features. ``history_features`` reads a
window the caller already sliced - it refuses any row that falls after the prediction time, so a
feature can never see the label it is meant to precede - and ``FEATURE_MANIFEST`` records, per
feature, which source columns it reads and what its missing value means.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Iterable, Literal, Mapping, MutableMapping

import pandas as pd

from faultevolve.data.event_sampling import (
    EventWindowConfig,
    SamplingError,
    build_labeled_samples,
    select_history,
)
from faultevolve.data.event_schema import (
    CanonicalEventSchema,
    EventSchemaError,
    normalize_events,
)
from faultevolve.tasks.smartmem_adapter import (
    LEAD_MINUTES,
    MCELOG_COLUMNS,
    PREDICT_WINDOW_DAYS,
    TICKET_COLUMNS,
    SmartMemAdapter,
)

READER_VERSION = "smread-v1"
SERIAL_COLUMN = "serial_number"
UNIT_EXTENSIONS = (".csv", ".feather")
CONTAINER_SUFFIXES = (".gz", ".bz2", ".zip", ".zst")
TYPE_DIRECTORIES = {"type_A": "A", "type_B": "B"}
Formats = ("csv", "feather")
EPOCH_UNITS = ("s", "ms")

#: Source columns that describe the outcome. They may reach the label function, never a frame of
#: visible features.
LABEL_ONLY_COLUMNS = (
    "failure_time",
    "alarm_time",
    "serial_number_type",
    "sn_type",
    "label",
)

#: The observed export (docs/runs/smartmem-input-evidence.template.md section 2.1) onto the
#: official names, including the official misspelling of ``manufacturter``.
EXPORT_TO_MCELOG: Mapping[str, str] = {
    "CpuId": "cpuid",
    "ChannelId": "channelid",
    "DimmId": "dimmid",
    "RankId": "rankid",
    "deviceID": "deviceid",
    "BankgroupId": "bankgroupid",
    "BankId": "bankid",
    "RowId": "rowid",
    "ColumnId": "columnid",
    "RetryRdErrLogParity": "retryrderrlogparity",
    "RetryRdErrLog": "retryrderrlog",
    "burst_info": "burst_info",
    "error_type_full_name": "error_type",
    "LogTime": "log_time",
    "Manufacturer": "manufacturter",
    "Model": "model",
    "PN": "PN",
    "Capacity": "Capacity",
    "FrequencyMHz": "FrequencyMHz",
    "MaxSpeedMHz": "MaxSpeedMHz",
    "McaBank": "McaBank",
    "memory_type": "memory_type",
    "region": "region",
}
#: Present in the export but not in the official 23; kept under an internal name, never dropped.
EXTRA_EXPORT_COLUMNS: Mapping[str, str] = {"MciAddr": "mci_addr"}

TICKET_EXPORT_TO_MCELOG: Mapping[str, str] = {
    "sn_name": "serial_number",
    "alarm_time": "failure_time",
    "sn_type": "serial_number_type",
}

NUMERIC_EVENT_COLUMNS = (
    "cpuid",
    "channelid",
    "dimmid",
    "rankid",
    "deviceid",
    "bankgroupid",
    "bankid",
    "rowid",
    "columnid",
)
CATEGORICAL_EVENT_COLUMNS = (
    "retryrderrlogparity",
    "retryrderrlog",
    "burst_info",
    "error_type",
)
STATIC_EVENT_COLUMNS = (
    "manufacturter",
    "model",
    "PN",
    "Capacity",
    "FrequencyMHz",
    "MaxSpeedMHz",
    "McaBank",
    "memory_type",
    "region",
)

MCELOG_EVENT_SCHEMA = CanonicalEventSchema(
    unit_col=SERIAL_COLUMN,
    time_col="log_time",
    event_type_col="error_type",
    static_cols=STATIC_EVENT_COLUMNS,
    categorical_cols=CATEGORICAL_EVENT_COLUMNS,
    numeric_cols=NUMERIC_EVENT_COLUMNS,
)
MCELOG_TO_EXPORT = {target: source for source, target in EXPORT_TO_MCELOG.items()}

DEFAULT_LOOKBACK = pd.Timedelta(days=5)
DEFAULT_LEAD = pd.Timedelta(minutes=LEAD_MINUTES)
DEFAULT_HORIZON = pd.Timedelta(days=PREDICT_WINDOW_DAYS)
DEFAULT_ANCHOR_FREQUENCY = pd.Timedelta(minutes=15)
ANCHOR_STRATEGIES = ("event", "grid", "hybrid")

#: The old attempt spelled its windows in days and minutes. Each alias names the Timedelta-based
#: parameter it stands for; a unit of None means "a count, not a duration".
LEGACY_WINDOW_KEYWORDS = {
    "lookback_days": ("lookback", "D"),
    "lead_minutes": ("lead", "min"),
    "predict_window_days": ("horizon", "D"),
    "sample_every_minutes": ("anchor_frequency", "min"),
    "max_samples_per_dimm": ("max_samples_per_unit", None),
}
_UNIT_WORDS = {"D": "days", "min": "minutes"}


class SmartMemDataError(ValueError):
    """Raised when a file cannot be read without guessing something the caller must declare."""


def anonymize_unit(unit: object) -> str:
    """Short irreversible id, so a report can distinguish units without exposing a serial number."""
    return hashlib.sha256(str(unit).encode("utf-8")).hexdigest()[:12]


def _file_dialect(columns) -> str:
    names = set(columns)
    export_hits = sum(name in EXPORT_TO_MCELOG or name in EXTRA_EXPORT_COLUMNS for name in names)
    canonical_hits = sum(name in MCELOG_COLUMNS for name in names)
    return "export" if export_hits >= canonical_hits else "canonical"


def _describe(path: Path) -> str:
    name = Path(path).name.lower()
    for extension in UNIT_EXTENSIONS:
        if name.endswith(extension):
            return f"unit {anonymize_unit(Path(path).name[: -len(extension)])} [{extension}]"
    return f"unit {anonymize_unit(Path(path).name)} [unknown extension]"


def unit_from_filename(path: Path) -> str:
    """Extract the unit id from ``{unit}.feather`` or ``{unit}.csv``, refusing anything else.

    A stem may not itself look like a file name: ``part-0001.csv.gz`` would otherwise hand back
    ``part-0001.csv`` as a serial number.
    """
    name = Path(path).name
    lowered = name.lower()
    extension = next((ext for ext in UNIT_EXTENSIONS if lowered.endswith(ext)), None)
    if extension is None:
        raise SmartMemDataError(
            f"{_describe(path)} does not end in a known extension {UNIT_EXTENSIONS}, so the unit "
            "id would have to be guessed"
        )
    stem = name[: -len(extension)]
    if any(stem.lower().endswith(extra) for extra in CONTAINER_SUFFIXES):
        raise SmartMemDataError(
            f"{_describe(path)} carries a further extension; decompress the container first "
            "instead of reading a unit id out of a packed file name"
        )
    if not stem.strip():
        raise SmartMemDataError(f"{_describe(path)} has an empty unit id")
    return stem


def serial_type_from_path(path: Path) -> str | None:
    """Read the queue identity from the parent directory, which is a declared source.

    ``None`` means the path does not declare one; the caller then needs another trusted source,
    because deriving it from the tickets would leak which units failed.
    """
    parent = Path(path).parent.name
    if parent in TYPE_DIRECTORIES:
        return TYPE_DIRECTORIES[parent]
    if parent.lower().startswith("type_"):
        raise SmartMemDataError(
            f"directory {parent!r} declares an unsupported serial_number_type; known: "
            f"{sorted(TYPE_DIRECTORIES)}"
        )
    return None


#: The columns of the side table carrying each unit's ``serial_number_type``.
#: ``unit_id`` is the same raw unit name the sample table uses, so the two join without a
#: second anonymisation step.
UNIT_TYPE_COLUMNS = ("unit_id", "serial_number_type", "source")
#: Where a type came from, in the order the side table trusts them.
UNIT_TYPE_SOURCES = ("queue_directory", "ticket", "unresolved")
#: The source spelling that means "no declared source covers this unit", named so callers never
#: re-type the index of the tuple above.
UNIT_TYPE_UNRESOLVED = UNIT_TYPE_SOURCES[2]


def build_unit_type_table(
    files: Sequence[Path],
    tickets: pd.DataFrame,
    *,
    unit_col: str = SERIAL_COLUMN,
    type_col: str = "serial_number_type",
) -> pd.DataFrame:
    """Give every listed unit its ``serial_number_type``, or say out loud that nobody declared one.

    The submission needs one type per unit, but tickets exist only for units that failed, so
    the queue directory is the primary source and the ticket column is a cross-check. A unit
    no directory names and no ticket covers comes back ``unresolved`` with no type: guessing
    it from error rates would be a label leak wearing a feature's clothes.

    A directory and a ticket that disagree is not a tie to break but a broken input, so the run
    stops. Both messages name only the anonymised unit, because a serial number is not something
    this repository prints.
    """
    declared: dict[str, str] = {}
    for path in files:
        kind = serial_type_from_path(path)
        if kind is None:
            continue
        unit = unit_from_filename(path)
        if declared.setdefault(unit, kind) != kind:
            raise SmartMemDataError(
                f"unit {anonymize_unit(unit)} is listed under two queue directories declaring "
                f"different types ({declared[unit]} and {kind})"
            )

    from_tickets: dict[str, str] = {}
    if len(tickets):
        for unit, kind in zip(tickets[unit_col], tickets[type_col]):
            text = _text(kind).strip()
            if not text:
                continue
            if from_tickets.setdefault(str(unit), text) != text:
                raise SmartMemDataError(
                    f"tickets for unit {anonymize_unit(str(unit))} declare two different "
                    f"{type_col} values ({from_tickets[str(unit)]} and {text})"
                )

    rows = []
    for path in files:
        unit = unit_from_filename(path)
        directory_type = declared.get(unit)
        ticket_type = from_tickets.get(unit)
        disagree = directory_type is not None and ticket_type is not None
        if disagree and directory_type != ticket_type:
            raise SmartMemDataError(
                f"unit {anonymize_unit(unit)} is declared type {directory_type} by its queue "
                f"directory and type {ticket_type} by its ticket; one of the two is wrong and this "
                "table has no way to decide which"
            )
        source = (
            UNIT_TYPE_SOURCES[0]
            if directory_type is not None
            else UNIT_TYPE_SOURCES[1]
            if ticket_type is not None
            else UNIT_TYPE_SOURCES[2]
        )
        rows.append(
            {
                "unit_id": unit,
                "serial_number_type": directory_type or ticket_type,
                "source": source,
            }
        )
    out = pd.DataFrame(rows, columns=list(UNIT_TYPE_COLUMNS))
    return out.drop_duplicates(subset=["unit_id"]).sort_values("unit_id").reset_index(drop=True)


def to_mcelog_columns(frame: pd.DataFrame) -> pd.DataFrame:
    """Rename a source frame onto the official mcelog names, refusing undeclared columns."""
    if not isinstance(frame, pd.DataFrame):
        raise SmartMemDataError(f"expected a DataFrame, got {type(frame).__name__}")
    names = list(frame.columns)
    leaked = sorted({name for name in names if name in LABEL_ONLY_COLUMNS})
    if leaked:
        raise SmartMemDataError(
            f"event frames must not carry label-only columns {leaked}; tickets are joined by the "
            "label function, not merged into visible features"
        )
    unknown = [
        name
        for name in names
        if name not in EXPORT_TO_MCELOG
        and name not in EXTRA_EXPORT_COLUMNS
        and name not in MCELOG_COLUMNS
        and name != SERIAL_COLUMN
    ]
    if unknown:
        hints = [
            (
                f"{name!r} (the official schema spells this manufacturter)"
                if name.lower() == "manufacturer"
                else repr(name)
            )
            for name in unknown
        ]
        raise SmartMemDataError(
            f"undeclared source columns {', '.join(hints)}; add them to the mapping or drop them, "
            "guessing a meaning would fabricate a feature"
        )

    dialect = _file_dialect(names)
    renamed: dict[str, pd.Series] = {}
    for name in names:
        target = (
            SERIAL_COLUMN
            if name == SERIAL_COLUMN
            else EXPORT_TO_MCELOG.get(name)
            or EXTRA_EXPORT_COLUMNS.get(name)
            or name
        )
        if target in renamed:
            raise SmartMemDataError(f"two source columns map onto {target}")
        renamed[target] = frame[name]

    missing = [column for column in MCELOG_COLUMNS if column not in renamed]
    if missing:
        wanted = [
            MCELOG_TO_EXPORT.get(column, column) if dialect == "export" else column
            for column in missing
        ]
        raise SmartMemDataError(f"required mcelog source columns are absent: {', '.join(wanted)}")

    extras = [target for target in renamed if target not in MCELOG_COLUMNS]
    out = pd.DataFrame({column: renamed[column] for column in MCELOG_COLUMNS}, index=frame.index)
    for column in extras:
        out[column] = renamed[column]
    if SERIAL_COLUMN in renamed:
        out[SERIAL_COLUMN] = renamed[SERIAL_COLUMN]
    return out


def _coerce_utc(
    values: pd.Series,
    *,
    column: str,
    timezone: str | None,
    epoch_unit: str | None,
    max_unparsable_rows: float,
    report: MutableMapping[str, int] | None,
) -> pd.Series:
    """Return the column as UTC stamps, declaring how a numeric epoch must be read.

    An int64 epoch is an absolute instant, so ``timezone`` only decides how it is displayed here;
    for naive local times the timezone really does shift the value, so it is mandatory.
    """
    if len(values) == 0:
        return pd.Series(pd.DatetimeIndex([], tz="UTC"), index=values.index)

    if isinstance(values.dtype, pd.DatetimeTZDtype) or pd.api.types.is_datetime64_any_dtype(values):
        stamps = values
    else:
        numeric = values if pd.api.types.is_numeric_dtype(values) else pd.to_numeric(
            values, errors="coerce"
        )
        if pd.api.types.is_numeric_dtype(values) or int(numeric.notna().sum()) > 0:
            if epoch_unit not in EPOCH_UNITS:
                raise SmartMemDataError(
                    f"{column} holds raw epoch numbers; declare epoch_unit as one of "
                    f"{EPOCH_UNITS} plus the timezone, because neither can be inferred from digits"
                )
            if timezone is None:
                raise SmartMemDataError(
                    f"{column} is an epoch column; declare the timezone the report is read in"
                )
            try:
                stamps = pd.to_datetime(numeric, unit=epoch_unit, utc=True, errors="coerce")
            except (ValueError, TypeError, OverflowError) as exc:
                raise SmartMemDataError(
                    f"{column} cannot be read as epoch {epoch_unit}: the values are out of range; "
                    "if they are milliseconds, declare epoch_unit='ms'"
                ) from exc
        else:
            stamps = pd.to_datetime(values, errors="coerce", format="ISO8601")
            if not pd.api.types.is_datetime64_any_dtype(stamps):
                raise SmartMemDataError(
                    f"{column} mixes timezone offsets or formats in one column; every unit file "
                    "must state time the same way"
                )

    if isinstance(stamps.dtype, pd.DatetimeTZDtype):
        utc = stamps.dt.tz_convert("UTC")
    elif timezone is None:
        raise SmartMemDataError(
            f"{column} is timezone-naive; declare the timezone before any window is computed"
        )
    else:
        try:
            utc = stamps.dt.tz_localize(timezone, ambiguous="raise", nonexistent="raise")
        except ValueError as exc:
            raise SmartMemDataError(
                f"{column} cannot be localized to {timezone} without guessing a daylight-saving "
                "resolution"
            ) from exc
        utc = utc.dt.tz_convert("UTC")

    bad = int(utc.isna().sum())
    total = int(len(utc))
    if bad and (bad / total) > max_unparsable_rows:
        raise SmartMemDataError(
            f"{bad} row(s) of {column} are out of range or could not be parsed "
            f"({bad / total:.1%} of {total} rows, threshold {max_unparsable_rows:.1%})"
        )
    if report is not None:
        report["unparsable_time_rows"] = bad
    try:
        return utc.astype("datetime64[ns, UTC]")
    except (ValueError, OverflowError) as exc:
        raise SmartMemDataError(
            f"{column} holds instants out of range for a nanosecond timestamp; the declared "
            f"epoch_unit={epoch_unit!r} is probably the wrong unit"
        ) from exc


def _read_raw(path: Path, fmt: str) -> pd.DataFrame:
    if fmt not in Formats:
        raise SmartMemDataError(f"fmt must be one of {Formats}, got {fmt!r}")
    if fmt == "csv":
        return pd.read_csv(path, dtype=str, keep_default_na=False)
    return pd.read_feather(path)


def prepare_smartmem_chunk(
    chunk: pd.DataFrame,
    *,
    unit: str,
    timezone: str | None = None,
    epoch_unit: Literal["s", "ms"] | None = None,
    max_unparsable_rows: float = 0.0,
    duplicate_policy: str = "drop_exact",
    report: MutableMapping[str, int] | None = None,
) -> pd.DataFrame:
    """Normalise one raw chunk of a per-unit file with the rules the reader applies to a whole one.

    This is the ``prepare`` step of a chunked stream, and it exists so the two paths cannot drift:
    :func:`read_smartmem_file` calls it too. One rule is worth knowing when a file is streamed:
    ``drop_exact`` can only see the rows of this chunk, so a duplicate pair split by a boundary
    survives once in each. Exact duplicates share an instant, so every window that holds one holds
    both - a consumer needing whole-file dedup applies the same policy to the assembled window and
    gets the same answer either way.
    """
    frame = to_mcelog_columns(chunk)
    declared = str(unit)
    if SERIAL_COLUMN in frame.columns and len(frame):
        observed = {str(value) for value in frame[SERIAL_COLUMN].unique()}
        if observed != {declared}:
            offenders = sorted(
                anonymize_unit(value) for value in observed if value != declared
            )
            raise SmartMemDataError(
                f"unit {anonymize_unit(declared)} [chunk] is not internally consistent: its "
                f"identity column holds {len(observed)} distinct values {offenders} besides the "
                "declared unit"
            )
    frame[SERIAL_COLUMN] = declared
    stamps = _coerce_utc(
        frame["log_time"],
        column="log_time",
        timezone=timezone,
        epoch_unit=epoch_unit,
        max_unparsable_rows=max_unparsable_rows,
        report=report,
    )
    # Only reachable when the caller declared a threshold: unparsable rows are removed, not kept
    # with a fabricated timestamp.
    keep = stamps.notna()
    frame = frame.loc[keep]
    frame["log_time"] = stamps.loc[keep]

    try:
        out = normalize_events(
            frame,
            MCELOG_EVENT_SCHEMA,
            timezone=timezone or "UTC",
            duplicate_policy=duplicate_policy,  # type: ignore[arg-type]
        )
    except EventSchemaError as exc:
        raise SmartMemDataError(str(exc)) from exc
    if report is not None:
        report["rows_kept"] = int(len(out))
        report["exact_duplicate_rows"] = int(len(frame)) - int(len(out))
    return out.reset_index(drop=True)


def read_smartmem_file(
    path: Path,
    *,
    fmt: Literal["csv", "feather"],
    timezone: str | None = None,
    epoch_unit: Literal["s", "ms"] | None = None,
    max_unparsable_rows: float = 0.0,
    duplicate_policy: str = "drop_exact",
    report: MutableMapping[str, int] | None = None,
) -> pd.DataFrame:
    """Read one per-unit event file; the returned frame always carries ``serial_number``.

    Rows are not trusted to be sorted or unique: the file is canonicalized, exact duplicate rows
    are dropped, same-timestamp-different-address rows are kept, and the result is sorted by time.
    The normalisation itself lives in :func:`prepare_smartmem_chunk`, which the streaming path calls
    per chunk, so a chunked read and a whole read cannot disagree.
    """
    path = Path(path)
    unit = unit_from_filename(path)
    if not path.name.lower().endswith(f".{fmt}"):
        raise SmartMemDataError(f"{_describe(path)} was read with fmt={fmt!r}, which disagrees")
    raw = _read_raw(path, fmt)
    out = prepare_smartmem_chunk(
        raw,
        unit=unit,
        timezone=timezone,
        epoch_unit=epoch_unit,
        max_unparsable_rows=max_unparsable_rows,
        duplicate_policy=duplicate_policy,
        report=report,
    )
    if report is not None:
        report["rows_read"] = int(len(raw))
    return out


def read_sorted_smartmem_file(path: Path) -> pd.DataFrame:
    """Read one merged file from an external-sort tree, whose rows are already canonical.

    The sort writes CSV and its prepare step has already renamed, localised and typed every row, so
    this reader takes no ``fmt`` and no ``timezone``: the instants in the file carry an offset, and
    re-declaring a zone would shift a decision the sort already made. What it does re-apply is the
    one rule a chunk could not - :func:`prepare_smartmem_chunk` only sees its own rows, so exact
    duplicates a chunk boundary split stay in the merged file - and the schema check is what turns a
    truncated copy into an error instead of a shorter history.
    """
    file_path = Path(path)
    frame = _read_raw(file_path, "csv")
    try:
        out = normalize_events(
            frame, MCELOG_EVENT_SCHEMA, timezone="UTC", duplicate_policy="drop_exact"
        )
    except EventSchemaError as exc:
        raise SmartMemDataError(
            f"{file_path.name} is not a readable canonical event table: {exc}"
        ) from exc
    return out.reset_index(drop=True)


def read_tickets(
    path: Path,
    *,
    timezone: str | None = None,
    epoch_unit: Literal["s", "ms"] | None = None,
) -> pd.DataFrame:
    """Read the failure tickets into ``TICKET_COLUMNS``; they are only ever a label source.

    There is no tolerance for an unreadable alarm time here: dropping a ticket would silently turn
    a real failure into a negative sample.
    """
    frame = pd.read_csv(Path(path))
    renamed = frame.rename(columns=TICKET_EXPORT_TO_MCELOG)
    missing = [column for column in TICKET_COLUMNS if column not in renamed.columns]
    if missing:
        raise SmartMemDataError(f"ticket file is missing columns: {', '.join(missing)}")
    out = renamed.loc[:, list(TICKET_COLUMNS)].copy()

    empty_units = int(out["serial_number"].isna().sum())
    if empty_units:
        raise SmartMemDataError(f"{empty_units} ticket row(s) have no serial number")
    out["serial_number"] = out["serial_number"].map(str)
    out["failure_time"] = _coerce_utc(
        out["failure_time"],
        column="failure_time",
        timezone=timezone,
        epoch_unit=epoch_unit,
        max_unparsable_rows=0.0,
        report=None,
    )
    try:
        SmartMemAdapter.validate_ticket_frame(out)
    except ValueError as exc:
        raise SmartMemDataError(str(exc)) from exc
    return out.reset_index(drop=True)


FEATURE_GROUPS = ("intensity", "spatial", "error_type", "retry_parity", "static", "coverage")
SPATIAL_FEATURE_COLUMNS = NUMERIC_EVENT_COLUMNS
#: The dtypes :func:`canonicalize_feature_types` knows how to render. A feature that declares
#: anything else is a manifest bug and stops the run, because an unapplied declaration is exactly
#: the silent dtype drift this function exists to close.
FEATURE_DTYPES = ("int64", "float64", "string")
#: Statics the mirror stores as whole numbers - and stores as int64 in some units, float64 with a
#: hole in others, which is why they need a declared rendering instead of the source's dtype.
WHOLE_NUMBER_STATIC_COLUMNS = ("Capacity", "FrequencyMHz", "MaxSpeedMHz")


def _entry(
    sources: tuple[str, ...],
    window: str,
    dtype: str,
    missing_rule: str,
    group: str,
    origin: str,
) -> dict[str, object]:
    return {
        "sources": sources,
        "window": window,
        "dtype": dtype,
        "missing_rule": missing_rule,
        "group": group,
        "origin": origin,
    }


def _build_manifest() -> dict[str, dict[str, object]]:
    """Name every fixed feature once, with the columns it reads and what its absence means."""
    manifest: dict[str, dict[str, object]] = {
        "event_count": _entry(
            ("log_time",), "history", "int64", "0 for an empty window", "intensity", "derived"
        ),
        "recent_half_count": _entry(
            ("log_time",),
            "history",
            "int64",
            "0 for an empty window",
            "intensity",
            "derived",
        ),
        "earlier_half_count": _entry(
            ("log_time",),
            "history",
            "int64",
            "0 for an empty window",
            "intensity",
            "derived",
        ),
        "growth_rate": _entry(
            ("log_time",),
            "history",
            "float64",
            "None for an empty window",
            "intensity",
            "derived",
        ),
        "minutes_since_last_event": _entry(
            ("log_time",),
            "history_tail",
            "float64",
            "None for an empty window: silence is not the same as a very long gap",
            "intensity",
            "derived",
        ),
        "top_rowid_share": _entry(
            ("rowid",), "history", "float64", "None for an empty window", "spatial", "derived"
        ),
        "rowid_repeat_rate": _entry(
            ("rowid",), "history", "float64", "None for an empty window", "spatial", "derived"
        ),
        "last_error_type": _entry(
            ("error_type",),
            "history_tail",
            "string",
            "None for an empty window",
            "error_type",
            "derived",
        ),
        "unexpected_error_type_count": _entry(
            ("error_type",),
            "history",
            "int64",
            "0 when every row matches a declared error type",
            "error_type",
            "derived",
        ),
        "retryrderrlog_marked_rate": _entry(
            ("retryrderrlog",),
            "history",
            "float64",
            "None when no row carries a readable value; a readable 0 counts as no mark",
            "retry_parity",
            "derived",
        ),
        "parity_marked_rate": _entry(
            ("retryrderrlogparity",),
            "history",
            "float64",
            "None when no row carries a readable value; a readable 0 counts as no mark",
            "retry_parity",
            "derived",
        ),
        "burst_info_distinct": _entry(
            ("burst_info",),
            "history",
            "int64",
            "0 for blank or empty windows",
            "retry_parity",
            "derived",
        ),
        "window_span_minutes": _entry(
            ("log_time",),
            "history",
            "float64",
            "None for an empty window",
            "coverage",
            "derived",
        ),
        "window_fill_rate": _entry(
            ("log_time",),
            "history",
            "float64",
            "None for an empty window",
            "coverage",
            "derived",
        ),
    }
    for column in SPATIAL_FEATURE_COLUMNS:
        manifest[f"distinct_{column}"] = _entry(
            (column,), "history", "int64", "0 for an empty window", "spatial", "derived"
        )
    for column in STATIC_EVENT_COLUMNS:
        manifest[column] = _entry(
            (column,),
            "history_tail",
            "int64" if column in WHOLE_NUMBER_STATIC_COLUMNS else "string",
            "None when no row in the window carries a non-empty value",
            "static",
            "carried_through",
        )
    return manifest


FEATURE_MANIFEST = _build_manifest()

#: Bump when the rendering *rules* change rather than the declarations. A renamed branch inside
#: :func:`canonicalize_feature_types` leaves the manifest untouched, so the version is the only
#: thing that makes that change visible to a stored ``config_hash``.
RENDER_POLICY_VERSION = "smartmem-render-v1"


def render_policy_fingerprint(
    manifest: Mapping[str, Mapping[str, object]] = FEATURE_MANIFEST,
) -> str:
    """Digest the declared rendering, so a policy change cannot hide behind a stable config hash.

    ``prepare_data.py`` folds this into the ``config_hash`` it writes into the manifest. Without it,
    moving ``FrequencyMHz`` from ``int64`` to ``float64`` - or teaching the canonicalizer a new
    spelling - rewrites partition bytes under a hash that says "same configuration", and a resume
    would then finish a run whose halves were rendered two different ways.
    """
    lines = sorted(
        f"{name}|{entry['dtype']}|{entry['window']}|{','.join(str(s) for s in entry['sources'])}"
        for name, entry in manifest.items()
    )
    body = f"{RENDER_POLICY_VERSION}\n" + "\n".join(lines)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()



def _require_group_names(feature_groups: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    names = tuple(feature_groups)
    unknown = [name for name in names if name not in FEATURE_GROUPS]
    if unknown:
        raise SmartMemDataError(
            f"feature_groups must be drawn from {', '.join(FEATURE_GROUPS)}; refused "
            f"unknown {', '.join(unknown)}"
        )
    return names


def _require_columns(frame: pd.DataFrame, columns: tuple[str, ...], what: str) -> None:
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise SmartMemDataError(f"{what} is missing columns: {', '.join(missing)}")


def _instant(value: object, name: str) -> pd.Timestamp:
    stamp = pd.Timestamp(value)
    if stamp.tzinfo is None:
        raise SmartMemDataError(
            f"{name} must carry a timezone; a naive prediction time would shift every window "
            "by the machine's offset"
        )
    return stamp.tz_convert("UTC")


def _text(value: object) -> str:
    return "" if value is None or (pd.api.types.is_scalar(value) and pd.isna(value)) else str(value)


def _ratio(numerator: float, denominator: float) -> float | None:
    return float(numerator) / float(denominator) if denominator else None


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_") or "blank"


def declared_error_types(names: Iterable[str]) -> tuple[str, ...]:
    """Return a declared error type domain, refusing one that cannot give each type its column.

    ``history_features`` writes one ``*_count`` column per declared name and names that column with
    ``_slug`` of the name itself, so two spellings that slug alike would leave only the later count
    on disk and the earlier one would vanish without a trace. This calls that very function instead
    of a copy of it, because a second slug rule here would certify tables the builder never makes.
    """
    columns: dict[str, str] = {}
    kept: list[str] = []
    for name in names:
        text = str(name).strip()
        if not text:
            continue
        column = f"{_slug(text)}_count"
        prior = columns.get(column)
        if prior is not None:
            raise SmartMemDataError(
                f"error types {prior!r} and {text!r} both name the column {column}; declare each "
                "type once, spelled the way the log states it"
            )
        columns[column] = text
        kept.append(text)
    if not kept:
        raise SmartMemDataError(
            "the declared error type domain is empty; an empty domain writes no error type feature "
            "and counts no row as unexpected either, so name at least one type"
        )
    return tuple(kept)


def error_type_counts(events: pd.DataFrame) -> dict[str, int]:
    """The error types one event table holds, counted the way the features read them.

    A row with no value counts under the empty name, which is also the name that makes it
    unexpected in ``unexpected_error_type_count``.
    """
    _require_columns(events, ("error_type",), "event table")
    return {
        str(value): int(rows)
        for value, rows in events["error_type"].map(_text).value_counts().items()
    }


def _marked_rate(series: pd.Series) -> float | None:
    """Share of the rows with a readable value that record a non-zero mark."""
    values = pd.to_numeric(series, errors="coerce")
    readable = values.notna()
    if not bool(readable.any()):
        return None
    return _ratio(float((values[readable] != 0).sum()), float(int(readable.sum())))


def _ordered_history(
    history: pd.DataFrame, *, prediction_time: pd.Timestamp, time_col: str
) -> tuple[pd.DataFrame, pd.Series]:
    """Sort the caller's window by time and refuse it if it reaches past ``prediction_time``."""
    _require_columns(history, (time_col,), "history window")
    stamps = pd.to_datetime(history[time_col])
    if not isinstance(stamps.dtype, pd.DatetimeTZDtype):
        raise SmartMemDataError(
            f"history window column {time_col} must already be timezone aware; read the file "
            "through read_smartmem_file()"
        )
    utc = pd.DatetimeIndex(stamps.dt.tz_convert("UTC")).as_unit("ns")
    ns = pd.Series(utc.asi8, index=stamps.index, dtype="int64")
    right = prediction_time.as_unit("ns").value
    late = int((ns > right).sum())
    if late:
        raise SmartMemDataError(
            f"{late} row(s) of the history window fall after the prediction time; a feature may "
            "read only (t - lookback, t], so refusing instead of leaking"
        )
    if not len(ns):
        return history, ns
    return history.loc[ns.sort_values(kind="stable").index], ns


def history_features(
    history: pd.DataFrame,
    *,
    prediction_time: pd.Timestamp,
    lookback: pd.Timedelta,
    error_types: tuple[str, ...] = (),
    feature_groups: tuple[str, ...] = FEATURE_GROUPS,
    static_columns: tuple[str, ...] = STATIC_EVENT_COLUMNS,
    time_col: str = "log_time",
    report: MutableMapping[str, int] | None = None,
) -> dict[str, object]:
    """One sample's features from a window the caller already sliced to ``(t - lookback, t]``.

    Nothing here re-reads the log: the window boundary is the caller's job (``select_history`` for
    a frame, V1-06's streaming path for the real files), and this function's guarantee is that it
    will not use a row it was handed that sits after ``prediction_time``.
    """
    groups = _require_group_names(feature_groups)
    moment = _instant(prediction_time, "prediction_time")
    if not isinstance(lookback, pd.Timedelta) or lookback <= pd.Timedelta(0):
        raise SmartMemDataError(f"lookback must be a positive Timedelta, got {lookback!r}")

    window, stamps = _ordered_history(history, prediction_time=moment, time_col=time_col)
    count = int(len(window))
    out: dict[str, object] = {}

    if "intensity" in groups:
        middle = (moment - lookback / 2).as_unit("ns").value
        recent = int((stamps > middle).sum()) if count else 0
        out["event_count"] = count
        out["recent_half_count"] = recent
        out["earlier_half_count"] = count - recent
        out["growth_rate"] = _ratio(recent - (count - recent), count)
        out["minutes_since_last_event"] = (
            _ratio(float(moment.as_unit("ns").value - int(stamps.max())), 60 * 10**9)
            if count
            else None
        )

    if "spatial" in groups:
        _require_columns(window, SPATIAL_FEATURE_COLUMNS, "history window")
        for column in SPATIAL_FEATURE_COLUMNS:
            out[f"distinct_{column}"] = int(window[column].nunique(dropna=True))
        top = window["rowid"].value_counts(dropna=True)
        out["top_rowid_share"] = _ratio(float(int(top.iloc[0])), count) if len(top) else None
        out["rowid_repeat_rate"] = (
            _ratio(count - int(out["distinct_rowid"]), count) if len(top) else None
        )

    if "error_type" in groups:
        _require_columns(window, ("error_type",), "history window")
        values = window["error_type"].map(_text)
        declared = tuple(str(name) for name in error_types)
        for name in declared:
            out[f"{_slug(name)}_count"] = int((values == name).sum())
        unexpected = int((~values.isin(declared)).sum()) if declared else 0
        out["unexpected_error_type_count"] = unexpected
        out["last_error_type"] = (values.iloc[-1] or None) if count else None
        if report is not None:
            report["unexpected_error_type_rows"] = (
                int(report.get("unexpected_error_type_rows", 0)) + unexpected
            )

    if "retry_parity" in groups:
        _require_columns(
            window, ("retryrderrlog", "retryrderrlogparity", "burst_info"), "history window"
        )
        out["retryrderrlog_marked_rate"] = _marked_rate(window["retryrderrlog"])
        out["parity_marked_rate"] = _marked_rate(window["retryrderrlogparity"])
        seen = {value for value in window["burst_info"].map(_text) if value}
        out["burst_info_distinct"] = len(seen)

    if "static" in groups:
        _require_columns(window, tuple(static_columns), "history window")
        for column in static_columns:
            raw = window[column]
            kept = raw[raw.notna() & raw.map(lambda value: bool(_text(value).strip()))]
            out[column] = kept.iloc[-1] if len(kept) else None

    if "coverage" in groups:
        if count:
            span_ns = int(stamps.max()) - int(stamps.min())
            out["window_span_minutes"] = _ratio(float(span_ns), 60 * 10**9)
            out["window_fill_rate"] = _ratio(
                float(span_ns), float(lookback.total_seconds()) * 10**9
            )
        else:
            out["window_span_minutes"] = None
            out["window_fill_rate"] = None

    return out


def _blank_mask(values: pd.Series) -> pd.Series:
    """Rows carrying no value at all: ``None``, ``NaN``, or text that is only whitespace."""
    return values.isna() | values.map(lambda value: not _text(value).strip())


def _as_declared_number(values: pd.Series, column: str, *, whole: bool) -> pd.Series:
    """Read one feature column as a number, refusing a cell this layer cannot read that way.

    ``errors="coerce"`` on its own would drop ``32GB`` into an empty cell and hand back a feature
    table with one fewer number and no error anywhere, so a non-blank cell that does not read as a
    number stops the run. The whole-number case refuses a fraction for the same reason: rounding is
    a decision about the data, and this layer does not get to make it silently.
    """
    numbers = pd.to_numeric(values, errors="coerce")
    blank = _blank_mask(values)
    lost = int((numbers.isna() & ~blank).sum())
    if lost:
        kind = "int64" if whole else "float64"
        raise SmartMemDataError(
            f"feature {column!r} declares {kind}, but {lost} non-blank cell(s) do not read as a "
            "number; fix the declared dtype or the column it reads, because an empty cell here "
            "would be a value this pipeline invented"
        )
    if not whole:
        return numbers.astype("float64")
    held = numbers[~blank]
    if len(held) and not bool((held % 1 == 0).all()):
        raise SmartMemDataError(
            f"feature {column!r} declares int64 but holds a value with a fractional part; declare "
            "it float64 rather than truncating what the log states"
        )
    return numbers.astype("Int64")


def canonicalize_feature_types(
    samples: pd.DataFrame,
    *,
    manifest: Mapping[str, Mapping[str, object]] = FEATURE_MANIFEST,
) -> pd.DataFrame:
    """Give every declared feature one spelling, whichever dtype the source file carried.

    A feather file stores ``FrequencyMHz`` as int64 for some units and float64 for others, and the
    sorted tree stores either spelling as text; the feature column then takes whatever dtype one
    partition's mix of scalars infers, so the same logical row leaves ``4000.0`` down one path and
    ``4000`` down the other. The tree is a transport, not a second experiment, so the rendering is
    decided here - before the split audit, and before the partition writer sees the frame.

    A column the manifest does not name is left alone: the sample rows themselves and the
    per-error-type counts are declared elsewhere and rendered by their own builders.
    """
    out = samples.copy()
    for name in out.columns:
        entry = manifest.get(name)
        if entry is None:
            continue
        dtype = str(entry["dtype"])
        if dtype == "int64":
            out[name] = _as_declared_number(out[name], name, whole=True)
        elif dtype == "float64":
            out[name] = _as_declared_number(out[name], name, whole=False)
        elif dtype == "string":
            out[name] = out[name].map(lambda value: _text(value).strip() or None)
        else:
            raise SmartMemDataError(
                f"feature {name!r} declares dtype {dtype!r}, which is not one of "
                f"{', '.join(FEATURE_DTYPES)}; a declaration nobody applies is how a dtype drift "
                "starts"
            )
    return out


def add_history_features(
    samples: pd.DataFrame,
    events: pd.DataFrame,
    *,
    lookback: pd.Timedelta,
    error_types: tuple[str, ...] = (),
    feature_groups: tuple[str, ...] = FEATURE_GROUPS,
    static_columns: tuple[str, ...] = STATIC_EVENT_COLUMNS,
    unit_col: str = SERIAL_COLUMN,
    unit_id_col: str = "unit_id",
    prediction_time_col: str = "prediction_time",
    time_col: str = "log_time",
    report: MutableMapping[str, int] | None = None,
) -> pd.DataFrame:
    """Append the history features to every sample row, keeping the sample rows untouched.

    A sample whose unit has no event, or no event inside the window, still gets a row: dropping it
    here would quietly change the denominator of the official F1. Grouping the whole log in memory
    is the small-fixture path; the 130 GB case streams one unit at a time through V1-06.
    """
    groups = _require_group_names(feature_groups)
    _require_columns(samples, (unit_id_col, prediction_time_col), "samples")
    _require_columns(events, (unit_col, time_col), "event log")

    logs = {str(unit): frame for unit, frame in events.groupby(unit_col, sort=False)}
    empty = events.iloc[0:0]
    rows = []
    for unit, moment in zip(samples[unit_id_col], samples[prediction_time_col]):
        log = logs.get(str(unit), empty)
        history = select_history(log, moment, lookback=lookback, time_col=time_col)
        rows.append(
            history_features(
                history,
                prediction_time=moment,
                lookback=lookback,
                error_types=error_types,
                feature_groups=groups,
                static_columns=static_columns,
                time_col=time_col,
                report=report,
            )
        )

    out = samples.reset_index(drop=True).copy()
    for name in rows[0] if rows else ():
        out[name] = [row[name] for row in rows]
    return canonicalize_feature_types(out)


_UNSET = object()


def _declare_instant(value: object, timezone: str | None, name: str) -> pd.Timestamp:
    stamp = pd.Timestamp(value)
    if stamp.tzinfo is not None:
        return stamp.tz_convert("UTC")
    if timezone is None:
        raise SmartMemDataError(
            f"{name} is timezone-naive; pass timezone=... so the report states the basis it was "
            "computed in"
        )
    try:
        return stamp.tz_localize(timezone, ambiguous="raise", nonexistent="raise").tz_convert("UTC")
    except (ValueError, TypeError) as exc:
        raise SmartMemDataError(f"{name} could not be localised to {timezone}") from exc


def _declare_column(
    frame: pd.DataFrame, column: str, *, timezone: str | None, what: str
) -> pd.Series:
    series = frame[column]
    if pd.api.types.is_numeric_dtype(series):
        raise SmartMemDataError(
            f"{what} column {column} holds numeric epoch values; neither the unit nor the timezone "
            "can be inferred here, so read the file with read_smartmem_file(epoch_unit=..., "
            "timezone=...)"
        )
    try:
        if pd.api.types.is_datetime64_any_dtype(series):
            stamps = series
        else:
            stamps = pd.to_datetime(series, format="ISO8601")
    except (ValueError, TypeError) as exc:
        raise SmartMemDataError(f"{what} column {column} cannot be parsed as timestamps") from exc
    if stamps.dt.tz is not None:
        return stamps.dt.tz_convert("UTC")
    if timezone is None:
        raise SmartMemDataError(
            f"{what} column {column} is timezone-naive; pass timezone=... or read the file through "
            "read_smartmem_file(), which localises on the declared zone"
        )
    try:
        localised = stamps.dt.tz_localize(timezone, ambiguous="raise", nonexistent="raise")
        return localised.dt.tz_convert("UTC")
    except (ValueError, TypeError) as exc:
        raise SmartMemDataError(
            f"{what} column {column} could not be localised to {timezone}"
        ) from exc


def _resolve_windows(provided: dict[str, object]) -> dict[str, object]:
    """Translate the day/minute aliases, refusing a window spelled twice."""
    resolved: dict[str, object] = {
        name: value for name, value in provided.items() if value is not _UNSET
    }
    for legacy, (modern, unit) in LEGACY_WINDOW_KEYWORDS.items():
        value = provided[legacy]
        if value is _UNSET:
            continue
        if modern in resolved:
            raise SmartMemDataError(
                f"both {modern} and its legacy alias {legacy} were passed; they cannot disagree, "
                "so keep exactly one spelling"
            )
        if unit is None:
            if value is None:
                resolved[modern] = None
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise SmartMemDataError(
                    f"{legacy} must be a sample count or None, got {type(value).__name__}"
                )
            resolved[modern] = int(value)
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise SmartMemDataError(
                f"{legacy} must be a number of {_UNIT_WORDS[unit]}, got {type(value).__name__}"
            )
        resolved[modern] = pd.Timedelta(float(value), unit=unit)
    return resolved


def aggregate_events_to_samples(  # noqa: PLR0913 - one wide keyword surface on purpose
    events: pd.DataFrame,
    tickets: pd.DataFrame,
    *,
    outcome_observed_until: pd.Timestamp,
    timezone: str | None = None,
    lookback: object = _UNSET,
    lead: object = _UNSET,
    horizon: object = _UNSET,
    anchor_frequency: object = _UNSET,
    anchor_strategy: str = "event",
    max_samples_per_unit: object = _UNSET,
    seed: int = 0,
    error_types: tuple[str, ...] = (),
    feature_groups: tuple[str, ...] = FEATURE_GROUPS,
    static_columns: tuple[str, ...] = STATIC_EVENT_COLUMNS,
    add_features: bool = True,
    report: MutableMapping[str, int] | None = None,
    lookback_days: object = _UNSET,
    lead_minutes: object = _UNSET,
    predict_window_days: object = _UNSET,
    sample_every_minutes: object = _UNSET,
    max_samples_per_dimm: object = _UNSET,
) -> pd.DataFrame:
    """Turn one unit's event log plus the tickets into labeled samples with history features.

    This is the SmartMem-shaped caller of the generic sampler: it builds the schema and the window
    config, calls :func:`faultevolve.data.event_sampling.build_labeled_samples`, then attaches
    :func:`add_history_features`. It deliberately contains no windowing, labelling or splitting
    arithmetic of its own, and ``split_key`` comes back empty because the temporal split step owns
    it. ``outcome_observed_until`` is required because a negative sample is only honest once
    follow-up coverage reached the end of its label window.

    Windows are :class:`pandas.Timedelta` in ``lookback`` / ``lead`` / ``horizon`` /
    ``anchor_frequency``, or the legacy numbers ``lookback_days`` / ``lead_minutes`` /
    ``predict_window_days`` / ``sample_every_minutes`` / ``max_samples_per_dimm``. Passing both
    spellings of one window is refused.
    """
    windows = _resolve_windows(
        {
            "lookback": lookback,
            "lead": lead,
            "horizon": horizon,
            "anchor_frequency": anchor_frequency,
            "max_samples_per_unit": max_samples_per_unit,
            "lookback_days": lookback_days,
            "lead_minutes": lead_minutes,
            "predict_window_days": predict_window_days,
            "sample_every_minutes": sample_every_minutes,
            "max_samples_per_dimm": max_samples_per_dimm,
        }
    )
    try:
        config = EventWindowConfig(
            lookback=windows.get("lookback", DEFAULT_LOOKBACK),
            lead=windows.get("lead", DEFAULT_LEAD),
            horizon=windows.get("horizon", DEFAULT_HORIZON),
            anchor_frequency=windows.get("anchor_frequency", DEFAULT_ANCHOR_FREQUENCY),
            anchor_strategy=anchor_strategy,
            max_samples_per_unit=windows.get("max_samples_per_unit"),
            seed=int(seed),
        )
    except SamplingError as exc:
        raise SmartMemDataError(f"the window config is invalid: {exc}") from exc

    _require_columns(events, (SERIAL_COLUMN, "log_time"), "event log")
    _require_columns(tickets, TICKET_COLUMNS, "tickets")
    prepared_events = events.copy()
    prepared_events["log_time"] = _declare_column(
        prepared_events, "log_time", timezone=timezone, what="event log"
    )
    prepared_tickets = tickets.loc[:, list(TICKET_COLUMNS)].copy()
    prepared_tickets["failure_time"] = _declare_column(
        prepared_tickets, "failure_time", timezone=timezone, what="tickets"
    )
    prepared_tickets["serial_number"] = prepared_tickets["serial_number"].map(str)
    try:
        SmartMemAdapter.validate_ticket_frame(prepared_tickets)
    except ValueError as exc:
        raise SmartMemDataError(str(exc)) from exc
    until = _declare_instant(outcome_observed_until, timezone, "outcome_observed_until")

    try:
        samples = build_labeled_samples(
            prepared_events,
            prepared_tickets,
            MCELOG_EVENT_SCHEMA,
            config,
            failure_unit_col=SERIAL_COLUMN,
            failure_time_col="failure_time",
            outcome_observed_until=until,
            report=report,
        )
    except SamplingError as exc:
        raise SmartMemDataError(str(exc)) from exc

    if add_features and len(samples):
        samples = add_history_features(
            samples,
            prepared_events,
            lookback=config.lookback,
            error_types=error_types,
            feature_groups=feature_groups,
            static_columns=static_columns,
            report=report,
        )
    return samples.reset_index(drop=True)


__all__ = [
    "ANCHOR_STRATEGIES",
    "DEFAULT_ANCHOR_FREQUENCY",
    "DEFAULT_HORIZON",
    "DEFAULT_LEAD",
    "DEFAULT_LOOKBACK",
    "FEATURE_DTYPES",
    "FEATURE_GROUPS",
    "FEATURE_MANIFEST",
    "LEGACY_WINDOW_KEYWORDS",
    "READER_VERSION",
    "SERIAL_COLUMN",
    "SmartMemDataError",
    "UNIT_TYPE_COLUMNS",
    "UNIT_TYPE_SOURCES",
    "UNIT_TYPE_UNRESOLVED",
    "add_history_features",
    "aggregate_events_to_samples",
    "anonymize_unit",
    "build_unit_type_table",
    "canonicalize_feature_types",
    "declared_error_types",
    "error_type_counts",
    "history_features",
    "prepare_smartmem_chunk",
    "read_smartmem_file",
    "read_sorted_smartmem_file",
    "read_tickets",
    "serial_type_from_path",
    "to_mcelog_columns",
    "unit_from_filename",
    "WHOLE_NUMBER_STATIC_COLUMNS",
]
