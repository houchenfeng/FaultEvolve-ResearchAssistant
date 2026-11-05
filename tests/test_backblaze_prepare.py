"""Backblaze prepare_data and download_data offline tests."""

from __future__ import annotations

import importlib.util
import io
import zipfile
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

pytest.importorskip("duckdb")

from benchmark.hdd_mvp.prepare_data import (
    HISTORY_DAYS,
    HORIZON,
    MIN_CAPACITY_BYTES,
    SMART_COLS as HDD_SMART_COLS,
    SPLITS,
)
from benchmark.backblaze_hdd import download_data as dl
from benchmark.backblaze_hdd import prepare_data as prep
from tests.helpers_backblaze import make_tiny_raw

_PREP = Path(__file__).resolve().parents[1] / "benchmark/backblaze_hdd/prepare_data.py"


def test_prepare_data_params_default_unchanged():
    assert prep.derive_windows("2024Q3", 7, 14) == (SPLITS[0].cutoff_start, SPLITS[0].cutoff_end)
    assert prep.derive_windows("2024Q4", 7, 14) == (SPLITS[1].cutoff_start, SPLITS[1].cutoff_end)
    assert prep.derive_windows("2025Q1", 7, 14) == (SPLITS[2].cutoff_start, SPLITS[2].cutoff_end)
    assert HORIZON == 7 and HISTORY_DAYS == 14 and MIN_CAPACITY_BYTES == 4e12
    assert prep.SMART_COLS == HDD_SMART_COLS
    defaults = prep.build_arg_parser().parse_args(["--raw-dir", "/tmp"])
    assert defaults.horizon == 7 and defaults.history_days == 14 and defaults.min_capacity_tb == 4.0


def test_quarter_parsing():
    assert dl.parse_quarter("2025Q1") == (2025, 1)
    with pytest.raises(ValueError):
        dl.parse_quarter("2025Q5")
    with pytest.raises(ValueError):
        dl.parse_quarter("25Q1")
    assert prep.quarter_bounds("2024Q4") == (date(2024, 10, 1), date(2024, 12, 31))


def _run_prepare(raw_dir: Path, out_dir: Path, **extra: object):
    args = [
        "--raw-dir",
        str(raw_dir),
        "--out-dir",
        str(out_dir),
        "--train-quarter",
        "2024Q4",
        "--val-quarter",
        "2025Q1",
        "--test-quarter",
        "2025Q2",
        "--n-negatives",
        "25",
        "--seed-base",
        "0",
    ]
    for k, v in extra.items():
        if isinstance(v, bool) and v:
            args.append(f"--{k.replace('_', '-')}")
        else:
            args.extend([f"--{k.replace('_', '-')}", str(v)])
    prep.main(args)


def test_prepare_tiny_outputs_schema(tmp_path):
    raw = tmp_path / "raw"
    out = tmp_path / "out"
    make_tiny_raw(raw, ["2024Q4", "2025Q1", "2025Q2"], n_fail=10)
    _run_prepare(raw, out)
    pub = out / "public"
    assert (pub / "train_history.csv.gz").exists()
    labels = pd.read_csv(pub / "train_labels.csv")
    assert list(labels.columns) == ["serial_number", "model", "cutoff_date", "label", "weight"]
    index = pd.read_csv(pub / "val_index.csv")
    assert list(index.columns) == ["serial_number", "model", "cutoff_date"]
    val_labels = pd.read_csv(out / "eval_only" / "val_labels.csv")
    assert list(val_labels.columns) == ["serial_number", "label", "weight"]
    hist = pd.read_csv(pub / "train_history.csv.gz")
    assert list(hist.columns[:2]) == ["date", "serial_number"]
    for c in prep.SMART_COLS:
        assert c in hist.columns
    assert set(labels["label"]).issubset({0, 1})


def test_prepare_label_and_history_rules(tmp_path):
    raw = tmp_path / "raw"
    out = tmp_path / "out"
    meta = make_tiny_raw(raw, ["2024Q4", "2025Q1", "2025Q2"], n_fail=10)
    _run_prepare(raw, out)
    labels = pd.read_csv(out / "public" / "train_labels.csv")
    fail_map = meta["fail_date_by_serial"]
    for _, row in labels[labels["label"] == 1].iterrows():
        fd = fail_map[str(row["serial_number"])]
        cd = pd.to_datetime(row["cutoff_date"]).date()
        delta = (fd - cd).days
        assert 1 <= delta <= 7
    hist = pd.read_csv(out / "public" / "train_history.csv.gz", parse_dates=["date"])
    for sn, g in hist.groupby("serial_number"):
        cutoff = labels.loc[labels["serial_number"] == sn, "cutoff_date"].iloc[0]
        cutoff_d = pd.to_datetime(cutoff).date()
        assert g["date"].dt.date.max() <= cutoff_d
        assert len(g) <= 14
    meta_j = json_load(out / "meta.json")
    w = meta_j["splits"]["train"]["negative_weight"]
    for _, row in labels[labels["label"] == 0].iterrows():
        assert abs(row["weight"] - w) < 1e-6
    out30 = tmp_path / "out30"
    _run_prepare(raw, out30, horizon=30)
    labels30 = pd.read_csv(out30 / "public" / "train_labels.csv")
    for _, row in labels30[labels30["label"] == 1].iterrows():
        fd = fail_map[str(row["serial_number"])]
        cd = pd.to_datetime(row["cutoff_date"]).date()
        assert 1 <= (fd - cd).days <= 30


def json_load(path: Path):
    import json

    return json.loads(path.read_text(encoding="utf-8"))


def test_prepare_capacity_and_vendor_filters(tmp_path):
    raw = tmp_path / "raw"
    make_tiny_raw(raw, ["2024Q4", "2025Q1", "2025Q2"])
    out = tmp_path / "out"
    _run_prepare(raw, out)
    labels = pd.read_csv(out / "public" / "train_labels.csv")
    assert not labels["model"].str.contains("WD30").any()
    out_v = tmp_path / "outv"
    _run_prepare(raw, out_v, vendors="ST")
    labels_v = pd.read_csv(out_v / "public" / "train_labels.csv")
    assert labels_v["model"].str.startswith("ST").all()
    out_c = tmp_path / "outc"
    _run_prepare(raw, out_c, min_capacity_tb=10)
    labels_c = pd.read_csv(out_c / "public" / "train_labels.csv")
    assert labels_c["model"].str.contains("MG07").any()
    assert not labels_c["model"].str.contains("WD30").any()


def test_prepare_disjoint_disks(tmp_path):
    raw = tmp_path / "raw"
    make_tiny_raw(raw, ["2024Q4", "2025Q1", "2025Q2"], n_stay=0)
    out = tmp_path / "out"
    _run_prepare(raw, out)
    tr = set(pd.read_csv(out / "public" / "train_labels.csv")["serial_number"])
    va = set(pd.read_csv(out / "public" / "val_index.csv")["serial_number"])
    assert "cross-0" in tr and "cross-0" in va
    out_d = tmp_path / "outd"
    _run_prepare(raw, out_d, disjoint_disks=True)
    tr2 = set(pd.read_csv(out_d / "public" / "train_labels.csv")["serial_number"])
    va2 = set(pd.read_csv(out_d / "public" / "val_index.csv")["serial_number"])
    te2 = set(pd.read_csv(out_d / "holdout" / "test_index.csv")["serial_number"])
    assert not (tr2 & va2)
    assert not (tr2 & te2)
    assert not (va2 & te2)


def test_prepare_holdout_separate(tmp_path):
    raw = tmp_path / "raw"
    make_tiny_raw(raw, ["2024Q4", "2025Q1", "2025Q2"])
    out = tmp_path / "out"
    hold = tmp_path / "hold"
    _run_prepare(raw, out, holdout_dir=str(hold))
    assert not (out / "holdout").exists()
    assert (hold / "holdout" / "test_history.csv.gz").exists()
    raw2 = tmp_path / "raw2"
    make_tiny_raw(raw2, ["2024Q4", "2025Q1"])
    out2 = tmp_path / "out2"
    _run_prepare(raw2, out2, skip_holdout=True)


def test_prepare_deterministic(tmp_path):
    raw = tmp_path / "raw"
    make_tiny_raw(raw, ["2024Q4", "2025Q1", "2025Q2"])
    out1, out2 = tmp_path / "o1", tmp_path / "o2"
    _run_prepare(raw, out1)
    _run_prepare(raw, out2)
    assert (out1 / "public" / "train_labels.csv").read_bytes() == (
        out2 / "public" / "train_labels.csv"
    ).read_bytes()
    h1 = pd.read_csv(out1 / "public" / "train_history.csv.gz")
    h2 = pd.read_csv(out2 / "public" / "train_history.csv.gz")
    pd.testing.assert_frame_equal(h1, h2)


def test_prepare_missing_smart_column_filled(tmp_path):
    raw = tmp_path / "raw"
    make_tiny_raw(raw, ["2024Q4", "2025Q1", "2025Q2"])
    qdir = raw / "data_Q4_2024"
    for p in qdir.glob("*.csv"):
        df = pd.read_csv(p)
        df = df.drop(columns=["smart_1_raw"])
        df.to_csv(p, index=False)
    out = tmp_path / "out"
    _run_prepare(raw, out)
    hist = pd.read_csv(out / "public" / "train_history.csv.gz")
    assert hist["smart_1_raw"].isna().all()


def test_prepare_bad_args(tmp_path):
    raw = tmp_path / "raw"
    make_tiny_raw(raw, ["2024Q4"])
    with pytest.raises(SystemExit):
        prep.main(["--raw-dir", str(raw), "--out-dir", str(tmp_path / "o"), "--horizon", "0"])
    with pytest.raises(SystemExit):
        prep.main(
            [
                "--raw-dir",
                str(raw),
                "--out-dir",
                str(tmp_path / "o2"),
                "--train-quarter",
                "2024Q4",
                "--val-quarter",
                "2024Q4",
                "--test-quarter",
                "2025Q1",
            ]
        )
    with pytest.raises(SystemExit):
        prep.main(["--raw-dir", str(tmp_path / "missing"), "--out-dir", str(tmp_path / "o3")])


def test_download_plan_and_urls(tmp_path):
    assert dl.zip_url("2025Q1") == (
        "https://f001.backblazeb2.com/file/Backblaze-Hard-Drive-Data/data_Q1_2025.zip"
    )
    qdir = tmp_path / "data_Q1_2025"
    qdir.mkdir()
    (qdir / "a.csv").write_text("date,serial_number\n", encoding="utf-8")
    plans = dl.plan_downloads(["2025Q1"], tmp_path)
    assert plans[0]["skip"] is True


def test_extract_zip_local_fixture(tmp_path):
    zpath = tmp_path / "z.zip"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("__MACOSX/x", b"x")
        zf.writestr("a/b.csv", "date,serial_number\n")
    zpath.write_bytes(buf.getvalue())
    dl.extract_zip(zpath, tmp_path, "2025Q1")
    assert (tmp_path / "data_Q1_2025" / "b.csv").exists()
    evil = tmp_path / "evil.zip"
    buf2 = io.BytesIO()
    with zipfile.ZipFile(buf2, "w") as zf:
        zf.writestr("../evil.csv", "x")
    evil.write_bytes(buf2.getvalue())
    with pytest.raises(ValueError):
        dl.extract_zip(evil, tmp_path, "2025Q1")


def test_download_dry_run_no_network(tmp_path, monkeypatch):
    import socket

    monkeypatch.setattr(socket, "socket", lambda *a, **k: (_ for _ in ()).throw(OSError("no net")))
    dl.main(["--quarters", "2025Q1", "--raw-dir", str(tmp_path), "--dry-run"])
