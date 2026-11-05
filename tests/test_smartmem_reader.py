"""V1-05 (part 1): read one SmartMem unit file into canonical mcelog columns.

The probe evidence (docs/runs/smartmem-input-evidence.template.md) shows two different schemas in
the wild - the official 23 lowercase names and a 24-column PascalCase export with int64 epoch
seconds - so the mapping has to be explicit, the timezone and epoch unit have to be declared, and
a serial number must never reach an error message.
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
import pytest

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from helpers_smartmem import EVENTS_BY_UNIT, SENTINEL_UNIT, write_fixture  # noqa: E402

from faultevolve.tasks.smartmem_adapter import MCELOG_COLUMNS, TICKET_COLUMNS  # noqa: E402
from faultevolve.tasks.smartmem_data import (  # noqa: E402
    SmartMemDataError,
    anonymize_unit,
    build_unit_type_table,
    read_smartmem_file,
    read_tickets,
    serial_type_from_path,
    to_mcelog_columns,
    unit_from_filename,
)

UTC = "UTC"
EXPORT_COLUMNS = (
    "BankId",
    "BankgroupId",
    "Capacity",
    "ChannelId",
    "ColumnId",
    "CpuId",
    "DimmId",
    "FrequencyMHz",
    "LogTime",
    "Manufacturer",
    "MaxSpeedMHz",
    "McaBank",
    "MciAddr",
    "Model",
    "PN",
    "RankId",
    "RetryRdErrLog",
    "RetryRdErrLogParity",
    "RowId",
    "burst_info",
    "deviceID",
    "error_type_full_name",
    "memory_type",
    "region",
)
BASE = pd.Timestamp("2024-03-01 00:00:00", tz=UTC)


def export_rows(count: int = 3, *, start: pd.Timestamp = BASE) -> dict:
    seconds = int(start.timestamp())
    return {
        "BankId": list(range(count)),
        "BankgroupId": [0] * count,
        "Capacity": ["32GB"] * count,
        "ChannelId": [1] * count,
        "ColumnId": [7] * count,
        "CpuId": [0] * count,
        "DimmId": [2] * count,
        "FrequencyMHz": ["4800"] * count,
        "LogTime": [seconds + 60 * i for i in range(count)],
        "Manufacturer": ["VENDORX"] * count,
        "MaxSpeedMHz": ["4800"] * count,
        "McaBank": ["0xff"] * count,
        "MciAddr": ["0x10", "0x20", "0x30"][:count],
        "Model": ["MODEL-A"] * count,
        "PN": ["PN-1"] * count,
        "RankId": [0] * count,
        "RetryRdErrLog": ["rrl"] * count,
        "RetryRdErrLogParity": ["01"] * count,
        "RowId": [100] * count,
        "burst_info": ["00"] * count,
        "deviceID": [3] * count,
        "error_type_full_name": ["CE.READ"] * count,
        "memory_type": ["DDR5"] * count,
        "region": ["cn"] * count,
    }


def export_frame(**overrides) -> pd.DataFrame:
    rows = {**export_rows(), **overrides}
    return pd.DataFrame(rows, columns=list(EXPORT_COLUMNS))


def export_file(root: Path, unit: str, *, fmt: str = "feather", **overrides) -> Path:
    path = root / "type_A" / f"{unit}.{fmt}"
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = export_frame(**overrides)
    if fmt == "feather":
        frame.to_feather(path)
    else:
        frame.to_csv(path, index=False)
    return path


# ---------------------------------------------------------------- the filename rule


def test_unit_id_is_the_basename_without_its_extension():
    assert unit_from_filename(Path("/data/type_A/28CC0234A1.feather")) == "28CC0234A1"
    assert unit_from_filename(Path("/data/train/unit-clean.csv")) == "unit-clean"


def test_a_further_extension_is_refused_not_stripped():
    with pytest.raises(SmartMemDataError, match="extension"):
        unit_from_filename(Path("/data/type_A/part-0001.csv.gz"))
    with pytest.raises(SmartMemDataError, match="extension"):
        unit_from_filename(Path("/data/type_A/no_extension"))
    with pytest.raises(SmartMemDataError, match="unit id"):
        unit_from_filename(Path("/data/type_A/.feather"))


def test_a_blank_or_path_like_unit_id_is_refused():
    for name in ("   .feather",):
        with pytest.raises(SmartMemDataError):
            unit_from_filename(Path("/data/type_A") / name)


def test_serial_type_comes_from_the_directory_not_the_ticket():
    assert serial_type_from_path(Path("/data/type_A/x.feather")) == "A"
    assert serial_type_from_path(Path("/data/type_B/x.feather")) == "B"
    assert serial_type_from_path(Path("/data/train/x.csv")) is None


def test_an_unknown_type_directory_is_refused():
    with pytest.raises(SmartMemDataError, match="serial_number_type"):
        serial_type_from_path(Path("/data/type_C/x.feather"))


# ------------------------------------------------------- the unit -> serial_number_type side table


def tickets_frame(pairs: list[tuple[str, str]]) -> pd.DataFrame:
    """A ticket table with only what the side table reads; the failure time is not looked at."""
    return pd.DataFrame(
        {
            "serial_number": [unit for unit, _ in pairs],
            "failure_time": pd.to_datetime(["2024-01-01"] * len(pairs), utc=True),
            "serial_number_type": [kind for _, kind in pairs],
        },
        columns=list(TICKET_COLUMNS),
    )


def unit_file(unit: str, *, queue: str = "type_A") -> Path:
    return Path("/data") / queue / f"{unit}.feather"


def test_the_queue_directory_declares_the_type_and_the_ticket_only_confirms_it():
    out = build_unit_type_table(
        [unit_file("28CC0234A1"), unit_file("28CC0234B2", queue="type_B")],
        tickets_frame([("28CC0234A1", "A")]),
    )
    assert list(out.columns) == ["unit_id", "serial_number_type", "source"]
    assert out["unit_id"].tolist() == ["28CC0234A1", "28CC0234B2"]
    assert out["serial_number_type"].tolist() == ["A", "B"]
    assert out["source"].tolist() == ["queue_directory", "queue_directory"]


def test_a_unit_the_directories_do_not_name_falls_back_to_its_ticket():
    """``train/`` declares nothing, and the official package has no type column in the events."""
    out = build_unit_type_table(
        [unit_file("unit-clean", queue="train")], tickets_frame([("unit-clean", "B")])
    )
    assert out.loc[0, "serial_number_type"] == "B"
    assert out.loc[0, "source"] == "ticket"


def test_a_unit_nobody_declares_comes_back_unresolved_rather_than_guessed():
    out = build_unit_type_table(
        [unit_file("unit-clean", queue="train"), unit_file("sn-quiet", queue="train")],
        tickets_frame([("unit-clean", "A")]),
    )
    assert dict(zip(out["unit_id"], out["source"])) == {
        "sn-quiet": "unresolved",
        "unit-clean": "ticket",
    }
    assert out.loc[out["unit_id"] == "sn-quiet", "serial_number_type"].isna().all()


def test_a_directory_and_a_ticket_that_disagree_stop_the_run():
    with pytest.raises(SmartMemDataError, match="queue directory"):
        build_unit_type_table([unit_file("28CC0234A1")], tickets_frame([("28CC0234A1", "B")]))


def test_two_queue_directories_for_one_unit_stop_the_run_too():
    with pytest.raises(SmartMemDataError, match="two queue directories"):
        build_unit_type_table(
            [unit_file("28CC0234A1"), unit_file("28CC0234A1", queue="type_B")],
            tickets_frame([]),
        )


def test_the_side_table_never_prints_a_serial_number():
    with pytest.raises(SmartMemDataError) as caught:
        build_unit_type_table([unit_file(SENTINEL_UNIT)], tickets_frame([(SENTINEL_UNIT, "B")]))
    assert SENTINEL_UNIT not in str(caught.value)
    assert anonymize_unit(SENTINEL_UNIT) in str(caught.value)


def test_the_side_table_does_not_depend_on_the_listing_order():
    files = [unit_file("sn-b"), unit_file("sn-a"), unit_file("sn-c", queue="train")]
    tickets = tickets_frame([("sn-a", "A"), ("sn-c", "B")])
    forward = build_unit_type_table(files, tickets)
    backward = build_unit_type_table(list(reversed(files)), tickets)
    pd.testing.assert_frame_equal(forward, backward)
    assert forward["unit_id"].tolist() == ["sn-a", "sn-b", "sn-c"]


def test_the_unit_id_never_appears_in_a_message():
    path = Path("/data/type_A") / f"{SENTINEL_UNIT}.feather"
    with pytest.raises(SmartMemDataError, match="extension") as caught:
        unit_from_filename(path.with_suffix(".csv.gz"))
    assert SENTINEL_UNIT not in str(caught.value)
    assert anonymize_unit(SENTINEL_UNIT) != SENTINEL_UNIT
    assert re.fullmatch(r"[0-9a-f]{12}", anonymize_unit(SENTINEL_UNIT))


# ---------------------------------------------------------------- the column mapping


def test_the_export_schema_maps_onto_the_official_names():
    out = to_mcelog_columns(export_frame())
    for column in MCELOG_COLUMNS:
        assert column in out.columns
    assert "manufacturter" in out.columns and "Manufacturer" not in out.columns
    assert out["error_type"].tolist() == ["CE.READ"] * 3
    assert out["mci_addr"].tolist() == ["0x10", "0x20", "0x30"]


def test_a_frame_that_already_uses_the_official_names_passes_through():
    canonical = EVENTS_BY_UNIT["unit-clean"]
    out = to_mcelog_columns(canonical.assign(serial_number="unit-clean"))
    assert list(out.columns[: len(MCELOG_COLUMNS)]) == list(MCELOG_COLUMNS)


def test_an_undeclared_extra_column_is_refused():
    frame = export_frame().assign(SomeNewField=["x"] * 3)
    with pytest.raises(SmartMemDataError, match="SomeNewField"):
        to_mcelog_columns(frame)


def test_the_correctly_spelled_manufacturer_is_not_accepted_silently():
    frame = export_frame().drop(columns=["Manufacturer"]).assign(manufacturer=["V"] * 3)
    with pytest.raises(SmartMemDataError, match="manufacturter|manufacturer"):
        to_mcelog_columns(frame)


def test_a_missing_export_column_is_reported_by_name():
    with pytest.raises(SmartMemDataError, match="RowId"):
        to_mcelog_columns(export_frame().drop(columns=["RowId", "MciAddr"]))


def test_ticket_columns_are_refused_inside_an_event_frame():
    frame = export_frame().assign(failure_time=[BASE] * 3)
    with pytest.raises(SmartMemDataError, match="label"):
        to_mcelog_columns(frame)


# ---------------------------------------------------------------- reading a file


def test_fixture_csv_reads_back_sorted_and_deduplicated(tmp_path):
    write_fixture(tmp_path, fmt="csv")
    report: dict = {}
    out = read_smartmem_file(
        tmp_path / "train" / "unit-dup-events.csv",
        fmt="csv",
        timezone="Asia/Shanghai",
        report=report,
    )
    # six stored rows, one of them an exact duplicate of another; two rows share a timestamp but
    # differ in address and must both survive.
    assert len(out) == 5
    assert out["log_time"].is_monotonic_increasing
    assert out["serial_number"].nunique() == 1
    assert report["exact_duplicate_rows"] == 1


def test_fixture_feather_matches_the_in_memory_frame(tmp_path):
    write_fixture(tmp_path, fmt="feather")
    out = read_smartmem_file(
        tmp_path / "train" / "unit-clean.feather",
        fmt="feather",
        timezone="Asia/Shanghai",
    )
    expected = EVENTS_BY_UNIT["unit-clean"].reset_index(drop=True)
    assert out["log_time"].tolist() == expected["log_time"].tolist()
    assert out["rowid"].tolist() == [int(v) for v in expected["rowid"]]


def test_the_epoch_unit_and_timezone_must_be_declared(tmp_path):
    path = export_file(tmp_path, "unit-a")
    with pytest.raises(SmartMemDataError, match="epoch_unit"):
        read_smartmem_file(path, fmt="feather", timezone="Asia/Shanghai")
    with pytest.raises(SmartMemDataError, match="timezone"):
        read_smartmem_file(path, fmt="feather", epoch_unit="s")


def test_declared_epoch_seconds_become_utc_instants(tmp_path):
    path = export_file(tmp_path, "unit-a")
    out = read_smartmem_file(
        path, fmt="feather", timezone="Asia/Shanghai", epoch_unit="s"
    )
    assert out["log_time"].iloc[0] == BASE
    assert str(out["log_time"].dtype).endswith("UTC]")
    assert serial_type_from_path(path) == "A"


def test_milliseconds_are_not_guessed_from_seconds(tmp_path):
    millis = [int(BASE.timestamp()) * 1000 + i for i in range(3)]
    path = export_file(tmp_path, "unit-a", LogTime=millis)
    out = read_smartmem_file(path, fmt="feather", timezone="UTC", epoch_unit="ms")
    assert out["log_time"].iloc[0] == BASE
    with pytest.raises(SmartMemDataError, match="out of range|epoch"):
        read_smartmem_file(path, fmt="feather", timezone="UTC", epoch_unit="s")


def test_the_format_must_agree_with_the_extension(tmp_path):
    path = export_file(tmp_path, "unit-a", fmt="feather")
    with pytest.raises(SmartMemDataError, match="fmt"):
        read_smartmem_file(path, fmt="csv", timezone="UTC", epoch_unit="s")


def test_unparsable_times_fail_unless_a_threshold_is_declared(tmp_path):
    path = export_file(tmp_path, "unit-a", fmt="csv")
    broken = pd.read_csv(path, dtype=str, keep_default_na=False)
    broken.loc[1, "LogTime"] = "not-a-time"
    broken.to_csv(path, index=False)
    with pytest.raises(SmartMemDataError, match="1 row"):
        read_smartmem_file(path, fmt="csv", timezone="UTC", epoch_unit="s")
    report: dict = {}
    out = read_smartmem_file(
        path,
        fmt="csv",
        timezone="UTC",
        epoch_unit="s",
        max_unparsable_rows=0.5,
        report=report,
    )
    assert len(out) == 2
    assert report["unparsable_time_rows"] == 1


def test_a_unit_column_inside_the_file_must_agree_with_the_filename(tmp_path):
    path = export_file(tmp_path, "unit-a")
    frame = export_frame().assign(serial_number=["unit-a"] * 3)
    frame.to_feather(path)
    assert len(read_smartmem_file(path, fmt="feather", timezone="UTC", epoch_unit="s")) == 3

    disagree = export_frame().assign(serial_number=["unit-a", "unit-b", "unit-b"])
    disagree.to_feather(path)
    other = anonymize_unit("unit-b")
    with pytest.raises(SmartMemDataError, match="identity") as caught:
        read_smartmem_file(path, fmt="feather", timezone="UTC", epoch_unit="s")
    assert "unit-b" not in str(caught.value) and other in str(caught.value)


def test_an_empty_file_returns_an_empty_canonical_frame(tmp_path):
    path = tmp_path / "type_A" / "unit-empty.feather"
    path.parent.mkdir(parents=True)
    export_frame().iloc[0:0].to_feather(path)
    out = read_smartmem_file(path, fmt="feather", timezone="UTC", epoch_unit="s")
    assert out.empty
    assert {"serial_number", "log_time", "manufacturter"} <= set(out.columns)


def test_the_reader_refuses_a_frame_that_is_not_a_dataframe():
    with pytest.raises(SmartMemDataError, match="DataFrame"):
        to_mcelog_columns(["not", "a", "frame"])


def test_every_error_message_stays_anonymous():
    for call in (
        lambda: unit_from_filename(Path("/data/type_A") / f"{SENTINEL_UNIT}.txt"),
        lambda: read_smartmem_file(
            Path("/data/type_A") / f"{SENTINEL_UNIT}.feather", fmt="csv", timezone="UTC"
        ),
    ):
        with pytest.raises(SmartMemDataError) as caught:
            call()
        assert SENTINEL_UNIT not in str(caught.value)


# ---------------------------------------------------------------- tickets


def test_real_ticket_columns_are_mapped_and_times_made_utc(tmp_path):
    path = tmp_path / "ticket.csv"
    pd.DataFrame(
        {
            "sn_name": ["unit-a", "unit-b"],
            "alarm_time": [int(BASE.timestamp()), int(BASE.timestamp()) + 60],
            "sn_type": ["A", "B"],
        }
    ).to_csv(path, index=False)
    out = read_tickets(path, timezone="Asia/Shanghai", epoch_unit="s")
    assert list(out.columns) == list(TICKET_COLUMNS)
    assert out["failure_time"].dt.tz is not None
    assert out["failure_time"].iloc[0] == BASE


def test_the_fixture_ticket_file_uses_the_documented_names(tmp_path):
    write_fixture(tmp_path, fmt="csv")
    out = read_tickets(tmp_path / "tickets.csv", timezone="UTC")
    assert len(out) == 6  # five failing units, one of them ticketed twice
    assert set(out["serial_number_type"]) <= {"A", "B"}


def test_an_unknown_serial_type_is_refused(tmp_path):
    path = tmp_path / "ticket.csv"
    pd.DataFrame(
        {
            "serial_number": ["unit-a"],
            "failure_time": [BASE.isoformat()],
            "serial_number_type": ["C"],
        }
    ).to_csv(path, index=False)
    with pytest.raises(ValueError, match="serial_number_type"):
        read_tickets(path, timezone="UTC")


def test_a_ticket_without_a_failure_time_is_refused(tmp_path):
    path = tmp_path / "ticket.csv"
    pd.DataFrame(
        {
            "sn_name": [SENTINEL_UNIT],
            "alarm_time": [""],
            "sn_type": ["A"],
        }
    ).to_csv(path, index=False)
    with pytest.raises(SmartMemDataError, match="failure_time") as caught:
        read_tickets(path, timezone="UTC")
    assert SENTINEL_UNIT not in str(caught.value)
