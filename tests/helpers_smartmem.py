"""Deterministic synthetic SmartMem mcelog fixtures for offline data-preparation tests.

Nothing here reads real data, the current date, or Python ``hash()``. Every instant is an
offset from :data:`START`, so label and censor boundaries stay hand-computable:

===========================  =========================================  ==========================
unit                         failure relative to its anchor              why it exists
===========================  =========================================  ==========================
``unit-lead-hit``            anchor + 15 min                            left label boundary = positive
``unit-lead-miss``           anchor + 14 min 59 s                       inside lead, must be dropped
``unit-horizon-hit``         anchor + 15 min + 7 d                       right label boundary = positive
``unit-horizon-miss``        anchor + 15 min + 7 d + 1 ns                one ns past the window
``unit-followup-short``      no ticket, coverage ends mid window        censored, must be removed
``unit-dup-events``          anchor-free, has exact + near duplicates    dedupe and ordering
``unit-static-late``         no ticket, ``model`` empty before day 30    static "latest value at t"
``unit-clean``               no ticket                                   hand-countable spatial windows
``SENTINEL_UNIT``            no ticket                                   must never reach logs/summaries
===========================  =========================================  ==========================

``serial_number_type`` is deliberately *not* derivable from the events: it lives only in
:data:`SERIAL_TYPE_BY_UNIT`, standing in for the trusted static source that V1-05 still needs
from the data owner. Deriving it from tickets would leak the label.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import pandas as pd

from faultevolve.tasks.smartmem_adapter import MCELOG_COLUMNS, TICKET_COLUMNS

START = pd.Timestamp("2024-01-01 00:00:00", tz="UTC")
SPAN_DAYS = 120
END = START + pd.Timedelta(days=SPAN_DAYS)
OUTCOME_OBSERVED_UNTIL = START + pd.Timedelta(days=115)

LEAD = pd.Timedelta(minutes=15)
HORIZON = pd.Timedelta(days=7)
LOOKBACK = pd.Timedelta(days=5)
ANCHOR_FREQUENCY = pd.Timedelta(minutes=15)

SENTINEL_UNIT = "unit-sentinel-zeqdserv000000"

TIME_COLS = ("log_time",)
INT_COLS = (
    "cpuid",
    "channelid",
    "dimmid",
    "rankid",
    "deviceid",
    "bankgroupid",
    "bankid",
    "rowid",
    "columnid",
    "retryrderrlogparity",
    "retryrderrlog",
    "McaBank",
)
STR_COLS = tuple(c for c in MCELOG_COLUMNS if c not in TIME_COLS and c not in INT_COLS)


def day(n: int, hh: int = 0, mm: int = 0, ss: int = 0, ns: int = 0) -> pd.Timestamp:
    """An absolute UTC instant ``n`` days after :data:`START`, never relative to today."""
    return (
        START
        + pd.Timedelta(days=n, hours=hh, minutes=mm, seconds=ss)
        + pd.Timedelta(nanoseconds=ns)
    )


STATIC_BY_UNIT: dict[str, dict[str, str]] = {
    "unit-clean": {
        "manufacturter": "VENDORX",
        "model": "FM-DEMO-100",
        "PN": "PN-DEMO-A",
        "Capacity": "32768",
        "FrequencyMHz": "2666",
        "MaxSpeedMHz": "3200",
        "memory_type": "DDR4",
        "region": "r1",
    },
    "unit-lead-hit": {
        "manufacturter": "VENDORX",
        "model": "FM-DEMO-100",
        "PN": "PN-DEMO-A",
        "Capacity": "32768",
        "FrequencyMHz": "2666",
        "MaxSpeedMHz": "3200",
        "memory_type": "DDR4",
        "region": "r1",
    },
    "unit-lead-miss": {
        "manufacturter": "VENDORY",
        "model": "FM-DEMO-200",
        "PN": "PN-DEMO-B",
        "Capacity": "65536",
        "FrequencyMHz": "2933",
        "MaxSpeedMHz": "3200",
        "memory_type": "DDR4",
        "region": "r2",
    },
    "unit-horizon-hit": {
        "manufacturter": "VENDORX",
        "model": "FM-DEMO-100",
        "PN": "PN-DEMO-A",
        "Capacity": "32768",
        "FrequencyMHz": "2666",
        "MaxSpeedMHz": "3200",
        "memory_type": "DDR4",
        "region": "r1",
    },
    "unit-horizon-miss": {
        "manufacturter": "VENDORY",
        "model": "FM-DEMO-300",
        "PN": "PN-DEMO-C",
        "Capacity": "16384",
        "FrequencyMHz": "2400",
        "MaxSpeedMHz": "2666",
        "memory_type": "DDR4",
        "region": "r3",
    },
    "unit-followup-short": {
        "manufacturter": "VENDORY",
        "model": "FM-DEMO-200",
        "PN": "PN-DEMO-B",
        "Capacity": "65536",
        "FrequencyMHz": "2933",
        "MaxSpeedMHz": "3200",
        "memory_type": "DDR4",
        "region": "r2",
    },
    "unit-dup-events": {
        "manufacturter": "VENDORX",
        "model": "FM-DEMO-100",
        "PN": "PN-DEMO-A",
        "Capacity": "32768",
        "FrequencyMHz": "2666",
        "MaxSpeedMHz": "3200",
        "memory_type": "DDR4",
        "region": "r1",
    },
    "unit-static-late": {
        "manufacturter": "VENDORX",
        "model": "FM-DEMO-200",
        "PN": "PN-DEMO-B",
        "Capacity": "32768",
        "FrequencyMHz": "2666",
        "MaxSpeedMHz": "3200",
        "memory_type": "DDR4",
        "region": "r1",
    },
    SENTINEL_UNIT: {
        "manufacturter": "VENDORY",
        "model": "FM-DEMO-300",
        "PN": "PN-DEMO-C",
        "Capacity": "16384",
        "FrequencyMHz": "2400",
        "MaxSpeedMHz": "2666",
        "memory_type": "DDR4",
        "region": "r3",
    },
}

SERIAL_TYPE_BY_UNIT: dict[str, str] = {
    "unit-clean": "A",
    "unit-lead-hit": "A",
    "unit-lead-miss": "B",
    "unit-horizon-hit": "A",
    "unit-horizon-miss": "B",
    "unit-followup-short": "A",
    "unit-dup-events": "B",
    "unit-static-late": "A",
    SENTINEL_UNIT: "B",
}

FAILURE_TIME_BY_UNIT: dict[str, pd.Timestamp] = {
    "unit-lead-hit": day(60),
    "unit-lead-miss": day(70),
    "unit-horizon-hit": day(90, 12),
    "unit-horizon-miss": day(97, 12, ns=1),
    "unit-dup-events": day(55),
}

ANCHORS: dict[str, pd.Timestamp] = {
    "unit-clean": day(101, 8),
    "unit-lead-hit": day(60) - LEAD,
    "unit-lead-hit-post-failure": day(60, 12),
    "unit-lead-miss": day(70) - LEAD + pd.Timedelta(seconds=1),
    "unit-horizon-hit": day(90, 12) - LEAD - HORIZON,
    "unit-horizon-miss": day(97, 12) - LEAD - HORIZON,
    "unit-followup-short": day(119, 12) - LEAD - HORIZON,
}

# (time, position fields, error fields) per unit; static config is filled in by ``_static``.
_EVENT_SPEC: dict[str, list[tuple[pd.Timestamp, dict[str, int], dict[str, str]]]] = {
    "unit-clean": [
        (day(100, 8), {"rowid": 100, "columnid": 5, "bankid": 0}, {"error_type": "ce"}),
        (day(100, 16), {"rowid": 100, "columnid": 6, "bankid": 0}, {"error_type": "ce"}),
        (day(101, 8), {"rowid": 101, "columnid": 5, "bankid": 1}, {"error_type": "ce"}),
        (day(119, 23), {"rowid": 102, "columnid": 5, "bankid": 1}, {"error_type": "ce"}),
    ],
    "unit-lead-hit": [
        (day(59, 20), {"rowid": 200, "columnid": 1, "bankid": 0}, {"error_type": "ce"}),
        (day(59, 23), {"rowid": 200, "columnid": 2, "bankid": 0}, {"error_type": "ce"}),
        (day(59, 23, 30), {"rowid": 201, "columnid": 2, "bankid": 1}, {"error_type": "ue"}),
        (day(60, 0, 0, 5), {"rowid": 999, "columnid": 9, "bankid": 3}, {"error_type": "ue"}),
    ],
    "unit-lead-miss": [
        (day(69, 20), {"rowid": 300, "columnid": 1, "bankid": 0}, {"error_type": "ce"}),
        (day(69, 23, 40), {"rowid": 300, "columnid": 1, "bankid": 1}, {"error_type": "ue"}),
        (day(70, 6), {"rowid": 999, "columnid": 9, "bankid": 2}, {"error_type": "ue"}),
    ],
    "unit-horizon-hit": [
        (day(83, 11), {"rowid": 400, "columnid": 3, "bankid": 0}, {"error_type": "ce"}),
        (day(83, 11, 30), {"rowid": 401, "columnid": 3, "bankid": 0}, {"error_type": "ce"}),
        (day(90, 12, 0, 5), {"rowid": 999, "columnid": 9, "bankid": 1}, {"error_type": "ue"}),
    ],
    "unit-horizon-miss": [
        (day(90, 11), {"rowid": 500, "columnid": 4, "bankid": 0}, {"error_type": "ce"}),
        (day(97, 12, 0, 6), {"rowid": 999, "columnid": 9, "bankid": 2}, {"error_type": "ue"}),
    ],
    "unit-followup-short": [
        (day(108, 8), {"rowid": 600, "columnid": 1, "bankid": 0}, {"error_type": "ce"}),
        (day(112, 11, 45), {"rowid": 601, "columnid": 2, "bankid": 0}, {"error_type": "ce"}),
    ],
    "unit-dup-events": [
        (day(49, 20), {"rowid": 700, "columnid": 1, "bankid": 0}, {"error_type": "ce"}),
        (day(50, 6), {"rowid": 701, "columnid": 2, "bankid": 0}, {"error_type": "ce"}),
        (day(50, 6), {"rowid": 701, "columnid": 2, "bankid": 0}, {"error_type": "ce"}),
        (day(50, 12), {"rowid": 702, "columnid": 7, "bankid": 1}, {"error_type": "ce"}),
        (day(50, 12), {"rowid": 703, "columnid": 8, "bankid": 1}, {"error_type": "ce"}),
        (day(55, 6), {"rowid": 999, "columnid": 9, "bankid": 3}, {"error_type": "ue"}),
    ],
    "unit-static-late": [
        (day(0), {"rowid": 799, "columnid": 1, "bankid": 0}, {"error_type": "ce"}),
        (day(10, 8), {"rowid": 800, "columnid": 1, "bankid": 0}, {"error_type": "ce"}),
        (day(29, 23, 59), {"rowid": 800, "columnid": 1, "bankid": 0}, {"error_type": "ce"}),
        (day(30, 6), {"rowid": 801, "columnid": 2, "bankid": 1}, {"error_type": "ce"}),
        (day(95, 8), {"rowid": 802, "columnid": 2, "bankid": 1}, {"error_type": "ce"}),
    ],
    SENTINEL_UNIT: [
        (day(15, 8), {"rowid": 900, "columnid": 1, "bankid": 0}, {"error_type": "ce"}),
        (day(105, 8), {"rowid": 901, "columnid": 1, "bankid": 0}, {"error_type": "ce"}),
    ],
}

# Rows stored on disk in this order (unit-dup-events only) so readers cannot trust file order.
DISK_ROW_ORDER: dict[str, list[int]] = {"unit-dup-events": [2, 4, 0, 5, 1, 3]}

_MODEL_APPEARS_ON_DAY = 30

#: The statics the real package stores as whole numbers, spelled two different ways across units.
WHOLE_NUMBER_STATIC_COLUMNS = ("Capacity", "FrequencyMHz", "MaxSpeedMHz")
#: Units stored with a float dtype, the way a feather file whose column holds a hole is stored.
DOUBLE_STATIC_UNITS = ("unit-clean", "unit-horizon-hit")


def _typed_statics(events: pd.DataFrame, unit: str) -> pd.DataFrame:
    """Store the numeric statics the way the real mirror stores them: int64 in most units,
    float64 with a hole in others.

    The reader keeps whatever dtype the file carries, so a feature column built from a partition
    mixing the two infers float64 and writes ``4000.0`` for a value an int-stored unit wrote as
    ``4000``. The same rows reaching the sorted tree become text and write ``4000``. That is the
    divergence the declared feature dtype policy has to close, and no CSV-only fixture can show it.
    """
    frame = events.copy()
    for column in WHOLE_NUMBER_STATIC_COLUMNS:
        numbers = pd.to_numeric(frame[column], errors="coerce")
        if unit in DOUBLE_STATIC_UNITS:
            frame[column] = numbers.astype("float64")
        else:
            frame[column] = numbers.astype("int64")
    if unit in DOUBLE_STATIC_UNITS:
        frame.loc[frame.index[-1], "FrequencyMHz"] = float("nan")
    return frame


def _static(unit: str, when: pd.Timestamp) -> dict[str, str]:
    static = dict(STATIC_BY_UNIT[unit])
    if unit == "unit-static-late" and when < day(_MODEL_APPEARS_ON_DAY):
        static["model"] = ""
    return static


def _event_row(unit: str, when: pd.Timestamp, pos: dict[str, int], err: dict[str, str]) -> dict:
    row = {
        "cpuid": 0,
        "channelid": 1,
        "dimmid": 0,
        "rankid": 0,
        "deviceid": 3,
        "bankgroupid": 0,
        "bankid": 0,
        "rowid": 0,
        "columnid": 0,
        "retryrderrlogparity": 0,
        "retryrderrlog": 0,
        "burst_info": "00",
        "error_type": "ce",
        "log_time": when,
        "McaBank": 4,
    }
    row.update(pos)
    row.update(err)
    row.update(_static(unit, when))
    return {c: row[c] for c in MCELOG_COLUMNS}


def _sorted_events(unit: str, rows: list[dict]) -> pd.DataFrame:
    frame = pd.DataFrame(rows, columns=list(MCELOG_COLUMNS))
    return frame.sort_values("log_time", kind="stable", ignore_index=True)


def _build_events_by_unit() -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    for unit, spec in _EVENT_SPEC.items():
        rows = [_event_row(unit, when, pos, err) for when, pos, err in spec]
        out[unit] = _sorted_events(unit, rows)
    return out


def _canonicalize(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy()
    for col in MCELOG_COLUMNS:
        if col in TIME_COLS:
            parsed = pd.to_datetime(frame[col], utc=True, format="ISO8601")
            frame[col] = parsed.astype("datetime64[ns, UTC]")
        elif col in INT_COLS:
            frame[col] = pd.to_numeric(frame[col]).astype("Int64")
        else:
            frame[col] = frame[col].map(lambda v: "" if pd.isna(v) else str(v)).astype("object")
    return frame[list(MCELOG_COLUMNS)]


def _ticket_frame() -> pd.DataFrame:
    rows = []
    for unit, failure in FAILURE_TIME_BY_UNIT.items():
        row = {
            "serial_number": unit,
            "failure_time": failure,
            "serial_number_type": SERIAL_TYPE_BY_UNIT[unit],
        }
        rows.append(row)
        if unit == "unit-dup-events":  # the same ticket recorded twice
            rows.append(dict(row))
    frame = pd.DataFrame(rows, columns=list(TICKET_COLUMNS))
    frame["failure_time"] = pd.to_datetime(frame["failure_time"], utc=True)
    return frame.sort_values(
        ["serial_number", "failure_time"], kind="stable", ignore_index=True
    )


def fixture_facts() -> dict:
    """Ground truth a test can check by hand, without touching the filesystem."""
    tickets = _ticket_frame()
    positive_units = sorted(
        unit
        for unit in ("unit-lead-hit", "unit-horizon-hit", "unit-dup-events")
    )
    return {
        "start": START,
        "end": END,
        "span_days": SPAN_DAYS,
        "outcome_observed_until": OUTCOME_OBSERVED_UNTIL,
        "lead": LEAD,
        "horizon": HORIZON,
        "lookback": LOOKBACK,
        "anchor_frequency": ANCHOR_FREQUENCY,
        "units": sorted(EVENTS_BY_UNIT),
        "events_by_unit": EVENTS_BY_UNIT,
        "tickets": tickets,
        "failure_time_by_unit": dict(FAILURE_TIME_BY_UNIT),
        "serial_type_by_unit": dict(SERIAL_TYPE_BY_UNIT),
        "anchors": dict(ANCHORS),
        "anchor_unit_clean": ANCHORS["unit-clean"],
        "positive_units": positive_units,
    }


def read_unit_file(path: Path, *, fmt: Literal["csv", "feather"]) -> pd.DataFrame:
    """Read one per-unit event file back into the canonical dtypes, in stored row order."""
    if fmt == "csv":
        raw = pd.read_csv(path, dtype=str, keep_default_na=False)
    elif fmt == "feather":
        raw = pd.read_feather(path)
    else:  # pragma: no cover - guarded by CLI, but fail loudly rather than silently
        raise ValueError(f"unsupported format: {fmt}")
    return _canonicalize(raw)


def write_fixture(
    root: Path,
    *,
    fmt: Literal["csv", "feather"] = "csv",
    typed_statics: bool = False,
) -> Path:
    """Write ``<root>/train/<unit>.<fmt>`` plus ``<root>/tickets.csv``; returns ``root``.

    ``typed_statics=True`` stores the numeric statics with a real dtype instead of as text, which
    is what a feather package does and what makes two read paths disagree on one value's spelling.
    """
    root = Path(root)
    train = root / "train"
    train.mkdir(parents=True, exist_ok=True)

    for unit, events in EVENTS_BY_UNIT.items():
        order = DISK_ROW_ORDER.get(unit)
        rows = events if order is None else events.iloc[order].reset_index(drop=True)
        if typed_statics:
            rows = _typed_statics(rows, unit)
        out = train / f"{unit}.{fmt}"
        if fmt == "csv":
            plain = rows.copy()
            plain["log_time"] = plain["log_time"].dt.strftime("%Y-%m-%dT%H:%M:%S+00:00")
            plain.to_csv(out, index=False)
        elif fmt == "feather":
            rows.reset_index(drop=True).to_feather(out)
        else:  # pragma: no cover
            raise ValueError(f"unsupported format: {fmt}")

    _ticket_frame().to_csv(root / "tickets.csv", index=False)
    return root


EVENTS_BY_UNIT: dict[str, pd.DataFrame] = _build_events_by_unit()
