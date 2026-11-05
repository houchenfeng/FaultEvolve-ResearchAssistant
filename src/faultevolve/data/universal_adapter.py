"""Format agnostic data ingress for device fault prediction tasks.

The evolution engine consumes a small, stable contract: telemetry rows with ``sn`` and
``LogTime`` plus numeric features, and an optional failure table with ``sn_name`` and
``alarm_time``.  This module keeps file format and device vocabulary at the boundary so the
sampler, evaluator, and search code do not need one branch per device.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

import pandas as pd


SUPPORTED_FORMATS = frozenset(
    {"csv", "tsv", "parquet", "feather", "excel", "xlsx", "xls", "json", "jsonl", "log"}
)
_JSON_RECORD_KEYS = ("records", "data", "items", "rows", "measurement_data")


def infer_format(path: str | Path, explicit: str | None = None) -> str:
    """Return a supported format from an explicit value or the file suffix."""
    fmt = (explicit or Path(path).suffix).lower().lstrip(".")
    fmt = {".xlsx": "excel", ".xls": "excel", ".jsonl": "jsonl"}.get(fmt, fmt)
    if fmt not in SUPPORTED_FORMATS:
        raise ValueError(f"unsupported input format {fmt!r}; choose from {sorted(SUPPORTED_FORMATS)}")
    return fmt


def _dotted_get(value: Any, path: str | None) -> Any:
    if not path:
        return value
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            raise ValueError(f"records_path={path!r} does not contain {part!r}")
        value = value[part]
    return value


def _json_records(value: Any, records_path: str | None = None) -> list[dict[str, Any]]:
    value = _dotted_get(value, records_path)
    if isinstance(value, list) and all(isinstance(row, dict) for row in value):
        return value
    if isinstance(value, dict) and not records_path:
        for key in _JSON_RECORD_KEYS:
            if isinstance(value.get(key), list):
                return _json_records(value[key])
    raise ValueError("JSON does not contain an array of object records; set records_path in the manifest")


def _read_log(path: Path, spec: dict[str, Any]) -> pd.DataFrame:
    lines = [line.strip() for line in path.read_text(
        encoding=spec.get("encoding", "utf-8"), errors="replace"
    ).splitlines() if line.strip()]
    if not lines:
        return pd.DataFrame()
    records: list[dict[str, Any]] = []
    try:
        for line in lines:
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError
            records.append(row)
    except (json.JSONDecodeError, ValueError):
        pattern = spec.get("line_regex")
        if pattern:
            regex = re.compile(pattern)
            return pd.DataFrame([match.groupdict() for line in lines if (match := regex.search(line))])
        return pd.read_csv(path, sep=spec.get("sep", r"\s+"), engine="python")
    return pd.json_normalize(records)


def load_table(path: str | Path, spec: dict[str, Any] | None = None) -> pd.DataFrame:
    """Read CSV, TSV, Parquet, Feather, Excel, JSON, JSONL, or text logs."""
    spec = dict(spec or {})
    path = Path(path)
    fmt = infer_format(path, spec.get("format"))
    if fmt in {"csv", "tsv"}:
        return pd.read_csv(path, sep=spec.get("sep", "\t" if fmt == "tsv" else ","),
                           encoding=spec.get("encoding", "utf-8"))
    if fmt == "parquet":
        return pd.read_parquet(path)
    if fmt == "feather":
        return pd.read_feather(path)
    if fmt in {"excel", "xlsx", "xls"}:
        return pd.read_excel(path, sheet_name=spec.get("sheet_name", 0))
    if fmt in {"log", "jsonl"}:
        return _read_log(path, spec)
    value = json.loads(path.read_text(encoding=spec.get("encoding", "utf-8")))
    return pd.json_normalize(_json_records(value, spec.get("records_path")))


def _to_epoch_seconds(values: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    if numeric.notna().mean() >= 0.8:
        scale = 1000.0 if numeric.dropna().abs().median() > 1e11 else 1.0
        return numeric / scale
    dates = pd.to_datetime(values, errors="coerce", utc=True, format="mixed")
    return pd.Series(dates.astype("int64") / 1e9, index=values.index).where(dates.notna())


def normalize_telemetry(
    frame: pd.DataFrame,
    device_col: str,
    time_col: str,
    feature_cols: list[str] | None = None,
) -> pd.DataFrame:
    """Map arbitrary column names to ``sn``/``LogTime`` and retain numeric features."""
    if device_col not in frame or time_col not in frame:
        raise ValueError(f"telemetry needs device_col={device_col!r} and time_col={time_col!r}")
    feature_cols = feature_cols or [
        column for column in frame.columns if column not in {device_col, time_col, "sn", "LogTime"}
    ]
    values: dict[str, pd.Series] = {
        "sn": frame[device_col].astype(str),
        "LogTime": _to_epoch_seconds(frame[time_col]),
    }
    for column in feature_cols:
        if column in frame:
            numeric = pd.to_numeric(frame[column], errors="coerce")
            if numeric.notna().any():
                values[column] = numeric
    if len(values) <= 2:
        raise ValueError("telemetry has no usable numeric feature columns")
    return (
        pd.DataFrame(values, index=frame.index)
        .dropna(subset=["sn", "LogTime"])
        .sort_values(["sn", "LogTime"], kind="mergesort")
        .reset_index(drop=True)
    )


def load_manifest(path: str | Path) -> dict[str, Any]:
    manifest_path = Path(path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or not manifest.get("telemetry"):
        raise ValueError("manifest must be an object containing a non-empty telemetry list")
    manifest["_base_dir"] = str(manifest_path.parent)
    return manifest


def _source(value: str | dict[str, Any]) -> dict[str, Any]:
    return {"path": value} if isinstance(value, str) else dict(value)


def _resolve(base: Path, value: str | Path) -> Path:
    candidate = Path(value)
    return candidate if candidate.is_absolute() else base / candidate


def task_config(manifest: dict[str, Any]) -> dict[str, Any]:
    """Return task knobs understood by the existing evaluator/search contract."""
    allowed = {"window_d", "lead_min", "rows_per_sn", "group_by", "drop_window",
               "label_decay", "voting", "vote_n", "agg", "pos_weight"}
    return {key: value for key, value in manifest.get("task", {}).items() if key in allowed}


def _safe_key(value: str, used: dict[str, str]) -> str:
    base = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip(". ") or "device"
    key = base
    if key in used and used[key] != value:
        key = f"{base}__{hashlib.sha1(value.encode('utf-8')).hexdigest()[:8]}"
    used[key] = value
    return key


def materialize_dataset(
    manifest_path: str | Path, output_dir: str | Path | None = None
) -> dict[str, Any]:
    """Materialize a manifest into the stable per-device Feather contract.

    The raw files remain untouched.  Only the manifest and the generated cache are consumed by
    downstream task adapters, so changing CSV to Parquet or JSON does not change the algorithm.
    """
    manifest = load_manifest(manifest_path)
    base = Path(manifest["_base_dir"])
    output = Path(output_dir or manifest.get("output_dir", base / "features")).resolve()
    (output / "type_A").mkdir(parents=True, exist_ok=True)
    (output / "type_B").mkdir(parents=True, exist_ok=True)
    telemetry = pd.concat([
        normalize_telemetry(
            load_table(_resolve(base, spec["path"]), spec),
            spec.get("device_col", "sn"),
            spec.get("time_col", "LogTime"),
            spec.get("feature_cols"),
        )
        for spec in (_source(raw) for raw in manifest["telemetry"])
    ], ignore_index=True, sort=False)
    features = [column for column in telemetry.columns if column not in {"sn", "LogTime"}]
    telemetry[features] = telemetry[features].apply(pd.to_numeric, errors="coerce")
    telemetry = telemetry.groupby(["sn", "LogTime"], as_index=False)[features].mean()
    used: dict[str, str] = {}
    keys = {str(sn): _safe_key(str(sn), used) for sn in sorted(telemetry["sn"].unique(), key=str)}
    for sn, rows in telemetry.groupby("sn", sort=True):
        rows.drop(columns=["sn"]).to_feather(output / "type_A" / f"{keys[str(sn)]}.feather")
    pd.DataFrame([{"sn_key": key, "sn": original} for original, key in keys.items()]).to_csv(
        output / "sn_map.csv", index=False
    )

    event_spec = _source(manifest["events"]) if manifest.get("events") else None
    if event_spec:
        events = load_table(_resolve(base, event_spec["path"]), event_spec)
        device_col = event_spec.get("device_col", event_spec.get("sn_col", "sn_name"))
        time_col = event_spec.get("time_col", event_spec.get("alarm_col", "alarm_time"))
        if device_col not in events or time_col not in events:
            raise ValueError("events must declare device_col and time_col that exist in the source")
        tickets = pd.DataFrame({
            "sn_name": events[device_col].astype(str).map(keys).fillna(events[device_col].astype(str)),
            "alarm_time": _to_epoch_seconds(events[time_col]),
        })
        type_col = event_spec.get("type_col", "sn_type")
        tickets["sn_type"] = events[type_col].astype(str) if type_col in events else "A"
    else:
        tickets = pd.DataFrame(columns=["sn_name", "alarm_time", "sn_type"])
    tickets.to_csv(output / "failure_ticket.csv", index=False)

    if manifest.get("metadata"):
        metadata_spec = _source(manifest["metadata"])
        metadata = load_table(_resolve(base, metadata_spec["path"]), metadata_spec)
        metadata_col = metadata_spec.get("device_col", metadata_spec.get("sn_col", "sn"))
        if metadata_col in metadata:
            metadata = metadata.copy()
            metadata[metadata_col] = metadata[metadata_col].astype(str).map(keys).fillna(
                metadata[metadata_col].astype(str)
            )
            if metadata_col != "sn":
                metadata = metadata.rename(columns={metadata_col: "sn"})
        metadata.to_csv(output / "sn_meta.csv", index=False)
    public_manifest = {key: value for key, value in manifest.items() if not key.startswith("_")}
    (output / "dataset_manifest.json").write_text(
        json.dumps(public_manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {
        "output_dir": str(output),
        "devices": int(telemetry["sn"].nunique()),
        "rows": int(len(telemetry)),
        "features": len(features),
        "tickets": int(len(tickets)),
    }


__all__ = [
    "SUPPORTED_FORMATS",
    "infer_format",
    "load_table",
    "load_manifest",
    "normalize_telemetry",
    "materialize_dataset",
    "task_config",
]
