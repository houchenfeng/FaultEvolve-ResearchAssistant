"""Build the HDD failure-prediction benchmark from raw Backblaze Drive Stats CSVs.

Sampling design (one sample per disk per split, so a disk's history always ends at
its own cutoff and "disk disappeared" can never leak the label):

* positive: a disk that fails on day F gets cutoff c = F - k, k in [1, HORIZON]
* negative: a disk that never fails in the quarter gets a random cutoff c with the
  disk still observed alive at c + HORIZON
* history: all daily SMART snapshots in [c - HISTORY_DAYS + 1, c]
* label: 1 if the disk fails in (c, c + HORIZON]

Negatives are subsampled; each sampled negative carries weight
N_eligible_negatives / n_sampled so metrics reflect the real fleet prevalence.

Usage:
    python prepare_data.py --raw-dir /path/to/backblaze_csvs --out-dir ./data
where raw-dir contains data_Q3_2024/, data_Q4_2024/, data_Q1_2025/ (unzipped).
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

import duckdb
import pandas as pd

HORIZON = 7
HISTORY_DAYS = 14
MIN_CAPACITY_BYTES = 4e12

RAW_ATTRS = [1, 3, 4, 5, 7, 9, 10, 12, 187, 188, 190, 191, 192, 193, 194, 196, 197, 198, 199, 240, 241, 242]
NORM_ATTRS = [1, 3, 5, 7, 9, 187, 194, 197, 198]
SMART_COLS = [f"smart_{a}_raw" for a in RAW_ATTRS] + [f"smart_{a}_normalized" for a in NORM_ATTRS]


@dataclass(frozen=True)
class Split:
    name: str
    quarter_dir: str
    cutoff_start: str
    cutoff_end: str
    n_negatives: int
    seed: int


SPLITS = [
    Split("train", "data_Q3_2024", "2024-07-14", "2024-09-23", 30000, 11),
    Split("val", "data_Q4_2024", "2024-10-14", "2024-12-24", 30000, 22),
    Split("test", "data_Q1_2025", "2025-01-14", "2025-03-24", 30000, 33),
]


def scan_sql(glob: str, cols: list[str]) -> str:
    select = ", ".join(cols)
    return f"(SELECT {select} FROM read_csv('{glob}', union_by_name=true, all_varchar=true, header=true))"


def build_split(con: duckdb.DuckDBPyConnection, raw_dir: Path, split: Split) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    glob = str(raw_dir / split.quarter_dir / "*.csv")
    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE life AS
        SELECT serial_number,
               any_value(model) AS model,
               max(TRY_CAST(capacity_bytes AS DOUBLE)) AS capacity_bytes,
               min(CAST(date AS DATE)) AS first_date,
               max(CAST(date AS DATE)) AS last_date,
               min(CASE WHEN failure = '1' THEN CAST(date AS DATE) END) AS fail_date
        FROM {scan_sql(glob, ['date', 'serial_number', 'model', 'capacity_bytes', 'failure'])}
        GROUP BY serial_number
        HAVING max(TRY_CAST(capacity_bytes AS DOUBLE)) >= {MIN_CAPACITY_BYTES}
        """
    )
    cs, ce, h, seed = split.cutoff_start, split.cutoff_end, HORIZON, split.seed
    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE pos AS
        SELECT serial_number, model,
               fail_date - CAST(1 + (hash(serial_number || '{seed}') % {h}) AS INTEGER) AS cutoff_date,
               1 AS label, 1.0 AS weight
        FROM life
        WHERE fail_date IS NOT NULL
        """
    )
    con.execute(
        f"""
        DELETE FROM pos
        WHERE cutoff_date < DATE '{cs}' OR cutoff_date > DATE '{ce}'
           OR cutoff_date < (SELECT first_date FROM life l WHERE l.serial_number = pos.serial_number)
        """
    )
    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE neg_pool AS
        SELECT serial_number, model,
               greatest(DATE '{cs}', first_date) AS lo,
               least(DATE '{ce}', last_date - {h}) AS hi
        FROM life
        WHERE fail_date IS NULL
          AND least(DATE '{ce}', last_date - {h}) >= greatest(DATE '{cs}', first_date)
        """
    )
    n_eligible = con.execute("SELECT count(*) FROM neg_pool").fetchone()[0]
    n_neg = min(split.n_negatives, n_eligible)
    weight = n_eligible / n_neg
    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE neg AS
        SELECT serial_number, model,
               lo + CAST(hash(serial_number || 'c{seed}') % (hi - lo + 1) AS INTEGER) AS cutoff_date,
               0 AS label, {weight} AS weight
        FROM neg_pool
        ORDER BY hash(serial_number || 's{seed}')
        LIMIT {n_neg}
        """
    )
    con.execute("CREATE OR REPLACE TEMP TABLE samples AS SELECT * FROM pos UNION ALL SELECT * FROM neg")

    cols = ["date", "serial_number", "model", "capacity_bytes"] + SMART_COLS
    casts = ", ".join(f"TRY_CAST(r.{c} AS DOUBLE) AS {c}" for c in SMART_COLS)
    history = con.execute(
        f"""
        SELECT CAST(r.date AS DATE) AS date, r.serial_number, r.model,
               TRY_CAST(r.capacity_bytes AS DOUBLE) AS capacity_bytes, {casts}
        FROM {scan_sql(glob, cols)} r
        JOIN samples s ON r.serial_number = s.serial_number
        WHERE CAST(r.date AS DATE) BETWEEN s.cutoff_date - {HISTORY_DAYS - 1} AND s.cutoff_date
        ORDER BY r.serial_number, date
        """
    ).fetchdf()
    samples = con.execute("SELECT * FROM samples ORDER BY serial_number").fetchdf()

    has_cutoff_row = history.merge(samples[["serial_number", "cutoff_date"]], on="serial_number")
    has_cutoff_row = set(has_cutoff_row.loc[has_cutoff_row["date"] == has_cutoff_row["cutoff_date"], "serial_number"])
    samples = samples[samples["serial_number"].isin(has_cutoff_row)].reset_index(drop=True)
    history = history[history["serial_number"].isin(has_cutoff_row)].reset_index(drop=True)

    stats = {
        "cutoff_range": [cs, ce],
        "n_samples": int(len(samples)),
        "n_positive": int(samples["label"].sum()),
        "n_negative": int((samples["label"] == 0).sum()),
        "n_eligible_negative_disks": int(n_eligible),
        "negative_weight": float(weight),
        "history_rows": int(len(history)),
        "n_models": int(samples["model"].nunique()),
    }
    return history, samples, stats


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw-dir", required=True, type=Path)
    ap.add_argument("--out-dir", default=Path(__file__).resolve().parent / "data", type=Path)
    args = ap.parse_args()

    out = args.out_dir
    dirs = {k: out / k for k in ["public", "eval_only", "holdout", "holdout_labels"]}
    for d in dirs.values():
        d.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect()
    con.execute("SET threads=4")
    meta = {"horizon_days": HORIZON, "history_days": HISTORY_DAYS, "min_capacity_bytes": MIN_CAPACITY_BYTES,
            "smart_columns": SMART_COLS, "splits": {}}

    for split in SPLITS:
        history, samples, stats = build_split(con, args.raw_dir, split)
        meta["splits"][split.name] = stats
        print(split.name, stats, flush=True)
        samples["cutoff_date"] = pd.to_datetime(samples["cutoff_date"]).dt.date
        index = samples[["serial_number", "model", "cutoff_date"]]
        labels = samples[["serial_number", "label", "weight"]]
        if split.name == "train":
            history.to_csv(dirs["public"] / "train_history.csv.gz", index=False)
            history.to_csv(dirs["holdout"] / "train_history.csv.gz", index=False)
            train_labels = samples[["serial_number", "model", "cutoff_date", "label", "weight"]]
            train_labels.to_csv(dirs["public"] / "train_labels.csv", index=False)
            train_labels.to_csv(dirs["holdout"] / "train_labels.csv", index=False)
        elif split.name == "val":
            history.to_csv(dirs["public"] / "val_history.csv.gz", index=False)
            index.to_csv(dirs["public"] / "val_index.csv", index=False)
            labels.to_csv(dirs["eval_only"] / "val_labels.csv", index=False)
        else:
            history.to_csv(dirs["holdout"] / "test_history.csv.gz", index=False)
            index.to_csv(dirs["holdout"] / "test_index.csv", index=False)
            labels.to_csv(dirs["holdout_labels"] / "test_labels.csv", index=False)

    (out / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
