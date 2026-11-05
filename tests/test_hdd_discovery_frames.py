"""Tests for HDD discovery_frames construction."""

from __future__ import annotations

import gzip
import json
import time
from pathlib import Path

import pandas as pd
import pytest

from faultevolve.tasks.hdd_adapter import HDDAdapter
from faultevolve.tasks.protocol import TaskSpec


def _write_synthetic_dataset(root: Path, n_serial: int, rows_per_serial: int) -> None:
    public = root / "public"
    public.mkdir(parents=True)
    label_rows = []
    hist_rows = []
    for i in range(n_serial):
        sn = f"S{i:05d}"
        cutoff = f"2024-07-{15 + (i % 10):02d}"
        label = 1 if i % 17 == 0 else 0
        model = "TOSHIBA MG07" if i % 3 else ""
        label_rows.append(
            {
                "serial_number": sn,
                "model": model,
                "cutoff_date": cutoff,
                "label": label,
                "weight": 1.0,
            }
        )
        for d in range(rows_per_serial):
            day = f"2024-07-{d + 1:02d}"
            smart187 = 1 if (i == 5 and d == 3) else 0
            hist_rows.append(
                {
                    "serial_number": sn,
                    "date": day,
                    "smart_5_raw": float(d),
                    "smart_9_raw": 0.0,
                    "smart_12_raw": 0.0,
                    "smart_187_raw": smart187,
                    "smart_188_raw": 0.0,
                    "smart_194_raw": 0.0,
                    "smart_197_raw": 0.0,
                    "smart_198_raw": 0.0,
                }
            )
    pd.DataFrame(label_rows).to_csv(public / "train_labels.csv", index=False)
    hist_df = pd.DataFrame(hist_rows)
    with gzip.open(public / "train_history.csv.gz", "wt", encoding="utf-8") as gz:
        hist_df.to_csv(gz, index=False)
    (root / "meta.json").write_text(json.dumps({"history_days": 14}), encoding="utf-8")


def _naive_censor(history: pd.DataFrame, labels: pd.DataFrame) -> list[int]:
    out: list[int] = []
    for _, row in labels.iterrows():
        sn = row["serial_number"]
        hist_sn = history[history["serial_number"] == sn]
        if "smart_187_raw" in hist_sn.columns and not hist_sn.empty:
            out.append(int((hist_sn["smart_187_raw"] > 0).any()))
        else:
            out.append(0)
    return out


def test_discovery_frames_cutoff_censor_and_tail(tmp_path: Path):
    data_root = tmp_path / "data"
    _write_synthetic_dataset(data_root, n_serial=50, rows_per_serial=20)
    task = tmp_path / "task"
    task.mkdir()
    (task / "init.py").write_text("# x", encoding="utf-8")
    (task / "evaluator.py").write_text("def evaluate(p, **kw): pass", encoding="utf-8")
    adapter = HDDAdapter()
    task_spec = TaskSpec(
        task_dir=task,
        problem_md="",
        prompt_md="",
        init_code="# x",
        evaluator_path=task / "evaluator.py",
    )
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setenv("HDD_BENCH_DATA_ROOT", str(data_root))
    try:
        frames = adapter.discovery_frames(task_spec)
    finally:
        monkeypatch.undo()
    labels = frames.labels
    assert len(labels) == 50
    assert labels["serial_number"].nunique() == len(labels)
    hist = frames.history
    cutoffs = dict(zip(labels["serial_number"].astype(str), frames.env_frame["time"].astype(str)))
    for sn, grp in hist.groupby("serial_number"):
        assert grp["date"].max() <= cutoffs[str(sn)]
    full_labels = pd.read_csv(data_root / "public" / "train_labels.csv").drop_duplicates(
        subset=["serial_number"], keep="last",
    )
    naive = _naive_censor(hist, full_labels)
    assert list(frames.env_frame["censor"]) == naive
    per_serial = hist.groupby("serial_number").size()
    assert per_serial.max() <= 16


def test_discovery_frames_performance_guard(tmp_path: Path):
    data_root = tmp_path / "data"
    _write_synthetic_dataset(data_root, n_serial=2000, rows_per_serial=20)
    task = tmp_path / "task"
    task.mkdir()
    (task / "init.py").write_text("# x", encoding="utf-8")
    (task / "evaluator.py").write_text("def evaluate(p, **kw): pass", encoding="utf-8")
    adapter = HDDAdapter()
    task_spec = TaskSpec(
        task_dir=task,
        problem_md="",
        prompt_md="",
        init_code="# x",
        evaluator_path=task / "evaluator.py",
    )
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setenv("HDD_BENCH_DATA_ROOT", str(data_root))
    adapter._discovery_cache = None
    try:
        t0 = time.time()
        adapter.discovery_frames(task_spec)
        assert time.time() - t0 < 5.0
    finally:
        monkeypatch.undo()


def _write_schema_rich_dataset(root: Path, n_serial: int = 30, rows_per_serial: int = 20) -> None:
    public = root / "public"
    public.mkdir(parents=True)
    label_rows = []
    hist_rows = []
    for i in range(n_serial):
        sn = f"R{i:05d}"
        cutoff = f"2024-07-{15 + (i % 5):02d}"
        label_rows.append(
            {
                "serial_number": sn,
                "model": "TOSHIBA MG07",
                "cutoff_date": cutoff,
                "label": 0,
                "weight": 1.0,
            }
        )
        for d in range(rows_per_serial):
            hist_rows.append(
                {
                    "serial_number": sn,
                    "date": f"2024-07-{d + 1:02d}",
                    "model": "TOSHIBA MG07",
                    "capacity_bytes": 1_000_000_000_000,
                    "smart_1_raw": 1.0,
                    "smart_1_normalized": 0.1,
                    "smart_5_raw": float(d),
                    "smart_9_raw": 0.0,
                    "smart_12_raw": 0.0,
                    "smart_187_raw": 0.0,
                    "smart_188_raw": 0.0,
                    "smart_194_raw": 0.0,
                    "smart_197_raw": 0.0,
                    "smart_198_raw": 0.0,
                    "smart_199_raw": 0.0,
                }
            )
    pd.DataFrame(label_rows).to_csv(public / "train_labels.csv", index=False)
    hist_df = pd.DataFrame(hist_rows)
    with gzip.open(public / "train_history.csv.gz", "wt", encoding="utf-8") as gz:
        hist_df.to_csv(gz, index=False)
    (root / "meta.json").write_text(json.dumps({"history_days": 14}), encoding="utf-8")


def _task_spec(tmp_path: Path) -> TaskSpec:
    task = tmp_path / "task"
    task.mkdir(exist_ok=True)
    (task / "init.py").write_text("# x", encoding="utf-8")
    (task / "evaluator.py").write_text("def evaluate(p, **kw): pass", encoding="utf-8")
    return TaskSpec(
        task_dir=task,
        problem_md="",
        prompt_md="",
        init_code="# x",
        evaluator_path=task / "evaluator.py",
    )


def _frames_with_env(tmp_path: Path, data_root: Path):
    adapter = HDDAdapter()
    adapter._discovery_cache = None
    mp = pytest.MonkeyPatch()
    mp.setenv("HDD_BENCH_DATA_ROOT", str(data_root))
    try:
        return adapter.discovery_frames(_task_spec(tmp_path))
    finally:
        mp.undo()


def test_discovery_history_contains_schema_columns(tmp_path: Path):
    data_root = tmp_path / "data"
    _write_schema_rich_dataset(data_root)
    frames = _frames_with_env(tmp_path, data_root)
    hist = frames.history
    for col in ("model", "capacity_bytes", "smart_1_raw", "smart_1_normalized", "smart_199_raw"):
        assert col in hist.columns
    assert pd.api.types.is_string_dtype(hist["model"])


def test_discovery_history_stays_multirow(tmp_path: Path):
    data_root = tmp_path / "data"
    n_serial = 30
    _write_schema_rich_dataset(data_root, n_serial=n_serial)
    frames = _frames_with_env(tmp_path, data_root)
    per_serial = frames.history.groupby("serial_number").size()
    assert per_serial.min() > 1
    assert per_serial.max() <= 16
    assert len(frames.labels) == n_serial
    assert list(frames.labels.columns) == ["serial_number", "label"]


def test_discovery_baseline_cols_unchanged(tmp_path: Path):
    from faultevolve.tasks.hdd_adapter import HDD_K0_COLUMNS

    data_root = tmp_path / "data"
    _write_schema_rich_dataset(data_root)
    frames = _frames_with_env(tmp_path, data_root)
    assert frames.baseline_cols == [c for c in HDD_K0_COLUMNS if c in frames.history.columns]


def test_discovery_schema_note_matches_frame(tmp_path: Path):
    data_root = tmp_path / "data"
    _write_schema_rich_dataset(data_root)
    frames = _frames_with_env(tmp_path, data_root)
    note = frames.schema_note
    assert len(note) <= 1500
    for col in frames.history.columns:
        if col in ("serial_number", "date"):
            continue
        assert col in note
    for token in ("serial_number", "date", "model"):
        if token in frames.history.columns:
            assert token in note


def test_schema_columns_match_hdd_data_schema():
    import re

    from faultevolve.tasks.hdd_adapter import HDD_DATA_SCHEMA, HDD_DISCOVERY_EXTRA_COLUMNS

    hist_section = HDD_DATA_SCHEMA.split("### train_labels.csv")[0]
    from_schema = set(re.findall(r"smart_\d+_(?:raw|normalized)", hist_section))
    if "model" in hist_section:
        from_schema.add("model")
    if "capacity_bytes" in hist_section:
        from_schema.add("capacity_bytes")
    assert set(HDD_DISCOVERY_EXTRA_COLUMNS) == from_schema


def test_discovery_skips_missing_header_column(tmp_path: Path):
    data_root = tmp_path / "data"
    _write_schema_rich_dataset(data_root)
    hist_path = data_root / "public" / "train_history.csv.gz"
    hist_df = pd.read_csv(hist_path, compression="gzip")
    hist_df = hist_df.drop(columns=["capacity_bytes"])
    with gzip.open(hist_path, "wt", encoding="utf-8") as gz:
        hist_df.to_csv(gz, index=False)
    frames = _frames_with_env(tmp_path, data_root)
    assert "capacity_bytes" not in frames.history.columns
    assert "model" in frames.history.columns
