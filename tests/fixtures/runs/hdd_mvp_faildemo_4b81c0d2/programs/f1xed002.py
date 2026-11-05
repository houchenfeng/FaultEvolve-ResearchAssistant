"""HDD failure prediction candidate (fixture, synthetic).

I/O contract: python f1xed002.py --data-dir <dir> --split <val|test> --out <pred.csv>
"""

import argparse
import os

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--split", default="val")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    history = pd.read_csv(os.path.join(args.data_dir, "train_history.csv.gz"))
    labels = pd.read_csv(os.path.join(args.data_dir, "train_labels.csv"))
    index = pd.read_csv(os.path.join(args.data_dir, f"{args.split}_index.csv"))

    merged = history.merge(labels, on=["serial_number", "model", "cutoff_date"])
    feats = merged.filter(regex="smart_.*_raw").fillna(0.0).to_numpy()
    model = LogisticRegression(class_weight="balanced", max_iter=5000)
    model.fit(feats, merged["label"].to_numpy())
    threshold = 0.5
    feats = index.filter(regex="smart_.*_raw").fillna(0.0).to_numpy()

    out = index[["serial_number"]].copy()
    out["score"] = model.predict_proba(feats)[:, 1]
    out["alarm"] = (out["score"] >= threshold).astype(int)
    out.to_csv(args.out, index=False)


if __name__ == "__main__":
    main()
