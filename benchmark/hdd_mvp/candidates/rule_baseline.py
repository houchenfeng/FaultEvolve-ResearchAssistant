"""Candidate A: expert rule on the last SMART snapshot (no learning).

Alarm when any classic media-error counter is non-zero on the cutoff day.
"""

import argparse
import os

import numpy as np
import pandas as pd

ERROR_COUNTERS = ["smart_5_raw", "smart_187_raw", "smart_197_raw", "smart_198_raw"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--split", required=True, choices=["val", "test"])
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    history = pd.read_csv(os.path.join(args.data_dir, f"{args.split}_history.csv.gz"), parse_dates=["date"])
    last = history.sort_values("date").groupby("serial_number").tail(1).set_index("serial_number")
    counters = last[ERROR_COUNTERS].fillna(0).clip(lower=0)

    score = np.log1p(counters).sum(axis=1)
    pred = pd.DataFrame({
        "serial_number": score.index,
        "score": score.to_numpy(),
        "alarm": (counters.max(axis=1) > 0).astype(int).to_numpy(),
    })
    pred.to_csv(args.out, index=False)


if __name__ == "__main__":
    main()
