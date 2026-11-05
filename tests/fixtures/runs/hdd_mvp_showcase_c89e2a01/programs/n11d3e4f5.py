"""HDD failure prediction candidate (n11d3e4f5).

Fixture program for the tree showcase run. Generation 3, operator refine.
I/O contract: python n11d3e4f5.py --data-dir <dir> --split <val|test> --out <pred.csv>
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
    # 把 14 天窗口的趋势差分并进来，再重选阈值
    merged = history.merge(labels, on=["serial_number", "model", "cutoff_date"])
    feats = merged.filter(regex="smart_.*_normalized").fillna(0.0).to_numpy()
    model = LogisticRegression(class_weight="balanced", max_iter=200, C=0.679)
    model.fit(feats, merged["label"].to_numpy())
    query = index.filter(regex="smart_.*_normalized").fillna(0.0).to_numpy()
    out = index[["serial_number"]].copy()
    out["score"] = model.predict_proba(query)[:, 1]
    out["alarm"] = (out["score"] >= 0.45).astype(int)
    out.to_csv(args.out, index=False)


if __name__ == "__main__":
    main()
