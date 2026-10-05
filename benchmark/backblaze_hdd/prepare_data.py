"""Build Backblaze HDD benchmark splits (hdd_mvp-isomorphic layout, parameterized quarters)."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import duckdb
import pandas as pd

HORIZON_DEFAULT = 7
HISTORY_DAYS_DEFAULT = 14
MIN_CAPACITY_BYTES_DEFAULT = 4e12

RAW_ATTRS = [1, 3, 4, 5, 7, 9, 10, 12, 187, 188, 190, 191, 192, 193, 194, 196, 197, 198, 199, 240, 241, 242]
NORM_ATTRS = [1, 3, 5, 7, 9, 187, 194, 197, 198]
SMART_COLS = [f"smart_{a}_raw" for a in RAW_ATTRS] + [f"smart_{a}_normalized" for a in NORM_ATTRS]

_QUARTER_RE = re.compile(r"^(\d{4})Q([1-4])$")
ROLE_SEED = {"train": 11, "val": 22, "test": 33}


def parse_quarter(s: str) -> tuple[int, int]:
    m = _QUARTER_RE.match(s)
    if not m:
        raise ValueError(f"invalid quarter: {s}")
    return int(m.group(1)), int(m.group(2))


def quarter_dirname(s: str) -> str:
    y, q = parse_quarter(s)
    return f"data_Q{q}_{y}"


def quarter_bounds(q: str) -> tuple[date, date]:
    y, qi = parse_quarter(q)
    starts = [date(y, 1, 1), date(y, 4, 1), date(y, 7, 1), date(y, 10, 1)]
    start = starts[qi - 1]
    if qi == 4:
        end = date(y, 12, 31)
    else:
        end = starts[qi] - timedelta(days=1)
    return start, end


def derive_windows(q: str, horizon: int, history_days: int) -> tuple[str, str]:
    q_start, q_end = quarter_bounds(q)
    cutoff_start = q_start + timedelta(days=history_days - 1)
    cutoff_end = q_end - timedelta(days=horizon)
    return cutoff_start.isoformat(), cutoff_end.isoformat()


def scan_sql(glob: str, cols: list[str]) -> str:
    select = ", ".join(cols)
    return f"(SELECT {select} FROM read_csv('{glob}', union_by_name=true, all_varchar=true, header=true))"


def _vendor_filter_sql(vendors: list[str]) -> str:
    if not vendors:
        return ""
    parts = " OR ".join(f"upper(any_value(model)) LIKE '{v.upper()}%'" for v in vendors)
    return f" AND ({parts})"


def _read_csv_columns(con: duckdb.DuckDBPyConnection, glob: str) -> set[str]:
    rows = con.execute(f"DESCRIBE SELECT * FROM read_csv('{glob}', union_by_name=true, header=true) LIMIT 0").fetchall()
    return {r[0] for r in rows}


def build_split(
    con: duckdb.DuckDBPyConnection,
    raw_dir: Path,
    quarter: str,
    role: str,
    args: argparse.Namespace,
    exclude_serials: set[str] | frozenset[str] = frozenset(),
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    qdir = raw_dir / quarter_dirname(quarter)
    if not qdir.exists() or not any(qdir.glob("*.csv")):
        raise SystemExit(f"missing raw quarter data: {qdir} (run download_data.py first)")

    glob = str(qdir / "*.csv")
    base_cols = ["date", "serial_number", "model", "capacity_bytes", "failure"]
    present = _read_csv_columns(con, glob)
    smart_select = []
    for col in SMART_COLS:
        if col in present:
            smart_select.append(col)
        else:
            smart_select.append(f"NULL AS {col}")
    scan_cols = base_cols + [c for c in SMART_COLS if c in present]

    min_cap = args.min_capacity_bytes
    max_cap = args.max_capacity_bytes
    cap_sql = f"max(TRY_CAST(capacity_bytes AS DOUBLE)) >= {min_cap}"
    if max_cap is not None:
        cap_sql += f" AND max(TRY_CAST(capacity_bytes AS DOUBLE)) <= {max_cap}"

    exclude_sql = ""
    if exclude_serials:
        quoted = ",".join(f"'{s}'" for s in exclude_serials)
        exclude_sql = f" AND serial_number NOT IN ({quoted})"

    vendor_sql = _vendor_filter_sql(args.vendors)
    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE life AS
        SELECT serial_number,
               any_value(model) AS model,
               max(TRY_CAST(capacity_bytes AS DOUBLE)) AS capacity_bytes,
               min(CAST(date AS DATE)) AS first_date,
               max(CAST(date AS DATE)) AS last_date,
               min(CASE WHEN failure = '1' THEN CAST(date AS DATE) END) AS fail_date
        FROM {scan_sql(glob, scan_cols)}
        GROUP BY serial_number
        HAVING {cap_sql}{vendor_sql}{exclude_sql}
        """
    )

    cs, ce = derive_windows(quarter, args.horizon, args.history_days)
    h, seed = args.horizon, args.seed_base + ROLE_SEED[role]

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
    n_neg = min(args.n_negatives, n_eligible)
    weight = n_eligible / n_neg if n_neg else 0.0
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

    casts = ", ".join(
        f"TRY_CAST(r.{c} AS DOUBLE) AS {c}" if c in present else f"NULL AS {c}" for c in SMART_COLS
    )
    history = con.execute(
        f"""
        SELECT CAST(r.date AS DATE) AS date, r.serial_number, r.model,
               TRY_CAST(r.capacity_bytes AS DOUBLE) AS capacity_bytes, {casts}
        FROM {scan_sql(glob, scan_cols)} r
        JOIN samples s ON r.serial_number = s.serial_number
        WHERE CAST(r.date AS DATE) BETWEEN s.cutoff_date - {args.history_days - 1} AND s.cutoff_date
        ORDER BY r.serial_number, date
        """
    ).fetchdf()
    samples = con.execute("SELECT * FROM samples ORDER BY serial_number").fetchdf()

    has_cutoff_row = history.merge(samples[["serial_number", "cutoff_date"]], on="serial_number")
    has_cutoff_row = set(
        has_cutoff_row.loc[has_cutoff_row["date"] == has_cutoff_row["cutoff_date"], "serial_number"]
    )
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


def _validate_quarters(train: str, val: str, test: str | None) -> None:
    qs = [train, val] + ([test] if test else [])
    if len(set(qs)) != len(qs):
        raise SystemExit("train/val/test quarters must be distinct")
    bounds = [quarter_bounds(q)[0] for q in qs]
    if bounds != sorted(bounds):
        raise SystemExit("quarters must be in ascending time order")


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw-dir", required=True, type=Path)
    ap.add_argument("--out-dir", default=Path(__file__).resolve().parent / "data", type=Path)
    ap.add_argument("--train-quarter", default="2024Q4")
    ap.add_argument("--val-quarter", default="2025Q1")
    ap.add_argument("--test-quarter", default="2025Q2")
    ap.add_argument("--horizon", type=int, default=HORIZON_DEFAULT)
    ap.add_argument("--history-days", type=int, default=HISTORY_DAYS_DEFAULT)
    ap.add_argument("--min-capacity-tb", type=float, default=4.0)
    ap.add_argument("--max-capacity-tb", type=float, default=None)
    ap.add_argument("--vendors", default="", help="Comma-separated model prefixes")
    ap.add_argument("--n-negatives", type=int, default=30000)
    ap.add_argument("--seed-base", type=int, default=0)
    ap.add_argument("--disjoint-disks", action="store_true")
    ap.add_argument("--holdout-dir", type=Path, default=None)
    ap.add_argument("--skip-holdout", action="store_true")
    return ap


def main(argv: list[str] | None = None) -> None:
    args = build_arg_parser().parse_args(argv)

    if not (1 <= args.horizon <= 30):
        raise SystemExit("horizon must be in [1, 30]")
    if not (1 <= args.history_days <= 60):
        raise SystemExit("history_days must be in [1, 60]")

    test_q = None if args.skip_holdout else args.test_quarter
    _validate_quarters(args.train_quarter, args.val_quarter, test_q)

    args.min_capacity_bytes = args.min_capacity_tb * 1e12
    args.max_capacity_bytes = args.max_capacity_tb * 1e12 if args.max_capacity_tb is not None else None
    args.vendors = [v.strip() for v in args.vendors.split(",") if v.strip()]

    out = args.out_dir
    holdout_root = args.holdout_dir
    if holdout_root:
        dirs = {
            "public": out / "public",
            "eval_only": out / "eval_only",
            "holdout": holdout_root / "holdout",
            "holdout_labels": holdout_root / "holdout_labels",
        }
    else:
        dirs = {k: out / k for k in ["public", "eval_only", "holdout", "holdout_labels"]}
    for d in dirs.values():
        d.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect()
    con.execute("SET threads=4")

    splits = [("train", args.train_quarter), ("val", args.val_quarter)]
    if not args.skip_holdout:
        splits.append(("test", args.test_quarter))

    meta = {
        "horizon_days": args.horizon,
        "history_days": args.history_days,
        "min_capacity_bytes": args.min_capacity_bytes,
        "vendors": args.vendors,
        "quarters": {"train": args.train_quarter, "val": args.val_quarter, "test": args.test_quarter},
        "disjoint_disks": args.disjoint_disks,
        "smart_columns": SMART_COLS,
        "splits": {},
    }

    seen_serials: set[str] = set()
    for role, quarter in splits:
        exclude = seen_serials if args.disjoint_disks else frozenset()
        history, samples, stats = build_split(con, args.raw_dir, quarter, role, args, exclude_serials=exclude)
        meta["splits"][role] = stats
        print(role, stats, flush=True)
        if args.disjoint_disks:
            seen_serials.update(samples["serial_number"].astype(str).tolist())

        samples["cutoff_date"] = pd.to_datetime(samples["cutoff_date"]).dt.date
        index = samples[["serial_number", "model", "cutoff_date"]]
        labels = samples[["serial_number", "label", "weight"]]
        if role == "train":
            history.to_csv(dirs["public"] / "train_history.csv.gz", index=False)
            history.to_csv(dirs["holdout"] / "train_history.csv.gz", index=False)
            train_labels = samples[["serial_number", "model", "cutoff_date", "label", "weight"]]
            train_labels.to_csv(dirs["public"] / "train_labels.csv", index=False)
            train_labels.to_csv(dirs["holdout"] / "train_labels.csv", index=False)
        elif role == "val":
            history.to_csv(dirs["public"] / "val_history.csv.gz", index=False)
            index.to_csv(dirs["public"] / "val_index.csv", index=False)
            labels.to_csv(dirs["eval_only"] / "val_labels.csv", index=False)
        else:
            history.to_csv(dirs["holdout"] / "test_history.csv.gz", index=False)
            index.to_csv(dirs["holdout"] / "test_index.csv", index=False)
            labels.to_csv(dirs["holdout_labels"] / "test_labels.csv", index=False)

    (out / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main(sys.argv[1:])
