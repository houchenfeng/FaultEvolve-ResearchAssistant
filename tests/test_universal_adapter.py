"""Contract tests for format agnostic device data ingress."""

from __future__ import annotations

import json

import pandas as pd
import pytest

from faultevolve.data.universal_adapter import (
    infer_format,
    load_table,
    materialize_dataset,
    normalize_telemetry,
)


def _telemetry() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "device_id": ["amp-1", "amp-1", "amp-2"],
            "timestamp": [
                "2026-01-01T00:00:00Z",
                "2026-01-01T01:00:00Z",
                "2026-01-01T00:00:00Z",
            ],
            "input_power_dbm": [-10.0, -9.5, -11.0],
            "output_power_dbm": [5.0, 5.1, 4.8],
        }
    )


def test_infer_format_accepts_dot_prefixed_manifest_values(tmp_path):
    assert infer_format(tmp_path / "telemetry.xlsx") == "xlsx"
    assert infer_format("telemetry.bin", ".parquet") == "parquet"


@pytest.mark.parametrize("kind", ["csv", "parquet", "feather", "excel", "json"])
def test_load_table_supports_common_formats(tmp_path, kind):
    frame = _telemetry()
    suffix = {"csv": ".csv", "parquet": ".parquet", "feather": ".feather", "excel": ".xlsx", "json": ".json"}[kind]
    path = tmp_path / f"telemetry{suffix}"
    if kind == "csv":
        frame.to_csv(path, index=False)
    elif kind == "parquet":
        frame.to_parquet(path)
    elif kind == "feather":
        frame.to_feather(path)
    elif kind == "excel":
        frame.to_excel(path, index=False)
    else:
        path.write_text(json.dumps({"records": frame.to_dict("records")}), encoding="utf-8")
    loaded = load_table(path, {"records_path": "records"} if kind == "json" else None)
    assert len(loaded) == len(frame)
    assert {"device_id", "timestamp"} <= set(loaded.columns)


def test_load_table_supports_json_lines_and_regex_logs(tmp_path):
    json_log = tmp_path / "telemetry.jsonl"
    json_log.write_text(
        '{"device_id":"a","timestamp":1700000000,"x":1}\n'
        '{"device_id":"b","timestamp":1700000001,"x":2}\n',
        encoding="utf-8",
    )
    assert len(load_table(json_log)) == 2
    plain_log = tmp_path / "telemetry.log"
    plain_log.write_text("device=a time=1700000000 x=1\ndevice=b time=1700000001 x=2\n", encoding="utf-8")
    loaded = load_table(
        plain_log,
        {"line_regex": r"device=(?P<device_id>\w+) time=(?P<timestamp>\d+) x=(?P<x>\d+)"},
    )
    assert loaded.to_dict("records")[1]["device_id"] == "b"


def test_materialize_manifest_keeps_algorithm_contract(tmp_path):
    telemetry = tmp_path / "telemetry.csv"
    events = tmp_path / "events.json"
    _telemetry().to_csv(telemetry, index=False)
    events.write_text(
        json.dumps({"events": [{"device_id": "amp-1", "failure_time": "2026-01-01T02:00:00Z"}]}),
        encoding="utf-8",
    )
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "telemetry": [{
                    "path": "telemetry.csv",
                    "format": "csv",
                    "device_col": "device_id",
                    "time_col": "timestamp",
                }],
                "events": {
                    "path": "events.json",
                    "format": "json",
                    "records_path": "events",
                    "device_col": "device_id",
                    "time_col": "failure_time",
                },
                "task": {"window_d": 3, "lead_min": 30, "group_by": "vendor_model"},
            }
        ),
        encoding="utf-8",
    )
    result = materialize_dataset(manifest, tmp_path / "features")
    assert result["devices"] == 2
    assert result["tickets"] == 1
    assert (tmp_path / "features" / "type_A" / "amp-1.feather").is_file()
    assert list(pd.read_csv(tmp_path / "features" / "failure_ticket.csv")["sn_name"]) == ["amp-1"]


def test_normalize_telemetry_rejects_missing_numeric_features():
    with pytest.raises(ValueError, match="numeric feature"):
        normalize_telemetry(
            pd.DataFrame({"device": ["a"], "when": ["2026-01-01"], "state": ["ok"]}),
            "device",
            "when",
        )
