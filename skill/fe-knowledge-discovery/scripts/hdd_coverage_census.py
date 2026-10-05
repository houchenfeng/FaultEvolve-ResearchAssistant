#!/usr/bin/env python3
"""Label-free SMART coverage census for HDD train units (KD1-H §1)."""

from __future__ import annotations

import argparse
import gzip
import json
import os
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[3]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from faultevolve.tasks.hdd_adapter import HDD_DISCOVERY_COLUMNS

META_COLS = ("serial_number", "model", "cutoff_date")
FORBIDDEN_LABEL_COLS = ("label", "weight")


def resolve_public_dir(data_root: Path | None, task_dir: Path) -> Path:
    if data_root is not None:
        return data_root / "public"
    env = os.environ.get("HDD_BENCH_DATA_ROOT")
    if env:
        return Path(env) / "public"
    task_public = task_dir / "data" / "public"
    if task_public.exists():
        return task_public
    return task_dir / "data" / "public"


def load_unit_cutoffs(public_dir: Path) -> pd.DataFrame:
    labels_path = public_dir / "train_labels.csv"
    usecols = list(META_COLS)
    labels = pd.read_csv(labels_path, usecols=usecols)
    labels = labels.drop_duplicates(subset=["serial_number"], keep="last")
    return labels


def tail_history_for_units(
    public_dir: Path,
    cutoffs: pd.Series,
    serials: set,
    tail_rows: int,
) -> pd.DataFrame:
    history_path = public_dir / "train_history.csv.gz"
    meta_path = public_dir.parent / "meta.json"
    history_days = 14
    if meta_path.exists():
        with meta_path.open(encoding="utf-8") as mf:
            history_days = int(json.load(mf).get("history_days", 14))
    lag_rows = 14
    tail_rows = max(int(history_days), lag_rows + 1) + 1
    with gzip.open(history_path, "rt", encoding="utf-8") as src:
        header = src.readline()
    header_cols = header.strip().split(",")
    usecols = [c for c in HDD_DISCOVERY_COLUMNS if c in header_cols]
    chunks: list[pd.DataFrame] = []
    with gzip.open(history_path, "rt", encoding="utf-8") as src:
        for chunk in pd.read_csv(src, usecols=usecols, chunksize=200_000):
            chunk = chunk[chunk["serial_number"].isin(serials)]
            if chunk.empty:
                continue
            cut = chunk["serial_number"].map(cutoffs)
            cut = cut.fillna(chunk["date"])
            chunk = chunk[chunk["date"] <= cut]
            chunks.append(chunk)
    if not chunks:
        return pd.DataFrame(columns=usecols)
    history = pd.concat(chunks, ignore_index=True)
    history = history.sort_values(["serial_number", "date"])
    return history.groupby("serial_number", sort=False).tail(tail_rows).reset_index(drop=True)


def census(history: pd.DataFrame, labels: pd.DataFrame) -> dict:
    n_units = len(labels)
    smart_cols = [c for c in history.columns if c.startswith("smart_")]
    per_column: dict[str, dict] = {}
    for col in smart_cols:
        last_vals = history.groupby("serial_number", sort=False)[col].last()
        covered = last_vals.notna().mean()
        per_column[col] = {
            "unit_coverage_last_row": round(float(covered), 4),
            "nunique_last_row": int(last_vals.dropna().nunique()),
        }
    per_model: dict[str, dict[str, float]] = {}
    if "model" in labels.columns:
        model_map = labels.set_index("serial_number")["model"].astype(str)
        for col in smart_cols:
            last_vals = history.groupby("serial_number", sort=False)[col].last()
            df = pd.DataFrame({"model": model_map.reindex(last_vals.index), "v": last_vals.notna().astype(float)})
            rates = df.groupby("model")["v"].mean()
            per_model[col] = {str(m): round(float(r), 4) for m, r in rates.items()}
    return {
        "n_labeled_units": n_units,
        "n_models": int(labels["model"].nunique()) if "model" in labels.columns else 0,
        "per_column": per_column,
        "per_model_nonnull_rate": per_model,
    }


def assert_no_label_reads(source: str) -> None:
    lowered = source.lower()
    for bad in FORBIDDEN_LABEL_COLS:
        if f'"{bad}"' in lowered or f"'{bad}'" in lowered:
            raise ValueError(f"census script must not reference column {bad!r}")


def main() -> int:
    assert_no_label_reads(Path(__file__).read_text(encoding="utf-8"))
    parser = argparse.ArgumentParser(description="HDD train coverage census (no labels)")
    parser.add_argument("--task-dir", type=Path, default=REPO / "benchmark/hdd_mvp")
    parser.add_argument("--data-root", type=Path, default=None)
    parser.add_argument("--json-out", type=Path, default=None)
    args = parser.parse_args()
    public = resolve_public_dir(args.data_root, args.task_dir.resolve())
    labels = load_unit_cutoffs(public)
    cutoffs = labels.set_index("serial_number")["cutoff_date"]
    serials = set(labels["serial_number"])
    history = tail_history_for_units(public, cutoffs, serials, tail_rows=16)
    report = census(history, labels)
    report["public_dir"] = str(public)
    text = json.dumps(report, indent=2, ensure_ascii=False)
    if args.json_out:
        args.json_out.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
