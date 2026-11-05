"""Synthetic fixtures for autotune tests."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


def make_synthetic_hdd(tmp_path: Path, n_serials: int = 40, n_dates: int = 4) -> Path:
    data = tmp_path / "data" / "public"
    data.mkdir(parents=True, exist_ok=True)
    serials = [f"S{i:04d}" for i in range(n_serials)]
    dates = pd.date_range("2020-01-01", periods=n_dates, freq="7D")
    split_idx = max(1, min(len(dates) - 1, int(round(0.6 * len(dates)))))
    early_dates = set(dates[:split_idx])
    late_dates = set(dates[split_idx:])
    early_serials = serials[: n_serials // 2]
    late_serials = serials[n_serials // 2 :]
    rows = []
    for i, s in enumerate(early_serials):
        for d in early_dates:
            rows.append(
                {
                    "serial_number": s,
                    "model": "ST3000",
                    "cutoff_date": d.strftime("%Y-%m-%d"),
                    "label": 1 if i < max(22, len(early_serials) - 2) else 0,
                    "weight": 1.0,
                }
            )
    for i, s in enumerate(late_serials):
        for d in late_dates:
            rows.append(
                {
                    "serial_number": s,
                    "model": "ST3000",
                    "cutoff_date": d.strftime("%Y-%m-%d"),
                    "label": 1 if i < max(22, len(late_serials) - 2) else 0,
                    "weight": 1.0,
                }
            )
    labels = pd.DataFrame(rows)
    labels.to_csv(data / "train_labels.csv", index=False)
    hist_rows = []
    smart_cols = [
        "smart_5_raw",
        "smart_187_raw",
        "smart_188_raw",
        "smart_197_raw",
        "smart_198_raw",
        "smart_199_raw",
        "smart_9_raw",
        "smart_194_raw",
        "smart_1_normalized",
        "smart_7_normalized",
    ]
    for s in early_serials + late_serials:
        for di, d in enumerate(dates):
            if s in early_serials and d not in early_dates:
                continue
            if s in late_serials and d not in late_dates:
                continue
            row = {
                "serial_number": s,
                "date": d,
                "model": "ST3000",
                "capacity_bytes": 1_000_000_000_000,
            }
            for c in smart_cols:
                row[c] = float(di + 1)
            hist_rows.append(row)
    hist = pd.DataFrame(hist_rows)
    hist.to_csv(data / "train_history.csv.gz", index=False, compression="gzip")
    late = labels[labels["cutoff_date"] == labels["cutoff_date"].max()]
    late[["serial_number", "model", "cutoff_date"]].to_csv(data / "val_index.csv", index=False)
    vh = hist[hist["serial_number"].isin(late["serial_number"])]
    vh.to_csv(data / "val_history.csv.gz", index=False, compression="gzip")
    return tmp_path
