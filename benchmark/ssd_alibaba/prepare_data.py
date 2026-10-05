"""Alibaba SSD data converter skeleton (stub)."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import pandas as pd

from faultevolve.tasks.ssd_alibaba_adapter import AlibabaSSDAdapter

_MONTH_RANGE_RE = re.compile(r"^(\d{4}-\d{2}):(\d{4}-\d{2})$")


def parse_month_range(s: str) -> tuple[str, str]:
    m = _MONTH_RANGE_RE.match(s)
    if not m:
        raise ValueError(f"invalid month range: {s}")
    return m.group(1), m.group(2)


def load_failure_labels(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    AlibabaSSDAdapter.validate_failure_labels(df)
    out = df.rename(columns={"disk_id": "serial_number"})
    out["failure_date"] = pd.to_datetime(out["failure_time"]).dt.normalize().dt.date
    return out[["serial_number", "model", "failure_date"]]


def build_split(*_args, **_kwargs):
    raise NotImplementedError("build_split not implemented; see docs/datasets/alibaba_ssd.md")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw-dir", required=True, type=Path)
    ap.add_argument("--out-dir", default=Path(__file__).resolve().parent / "data", type=Path)
    ap.add_argument("--variant", choices=["smart_logs", "open_data"], default="smart_logs")
    ap.add_argument("--horizon", type=int, default=7)
    ap.add_argument("--history-days", type=int, default=14)
    ap.add_argument("--train-months", required=True)
    ap.add_argument("--val-months", required=True)
    ap.add_argument("--test-months", required=True)
    ap.add_argument("--n-negatives", type=int, default=30000)
    ap.add_argument("--skip-holdout", action="store_true")
    args = ap.parse_args(argv)

    parse_month_range(args.train_months)
    parse_month_range(args.val_months)
    if not args.skip_holdout:
        parse_month_range(args.test_months)

    label_path = args.raw_dir / "ssd_failure_label.csv"
    if not label_path.exists():
        raise SystemExit(f"missing {label_path}")
    load_failure_labels(label_path)
    raise NotImplementedError(
        "ssd_alibaba prepare_data not implemented; see docs/datasets/alibaba_ssd.md"
    )


if __name__ == "__main__":
    main(sys.argv[1:])
