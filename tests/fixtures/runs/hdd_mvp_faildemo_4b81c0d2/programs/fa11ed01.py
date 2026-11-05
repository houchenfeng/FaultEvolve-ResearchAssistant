"""HDD failure prediction candidate (fixture, synthetic).

I/O contract: python fa11ed01.py --data-dir <dir> --split <val|test> --out <pred.csv>
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

    import lightgbm as lgb

    merged = history.merge(labels, on=["serial_number", "model", "cutoff_date"])
    feats = merged.filter(regex="smart_.*_normalized").fillna(0.0).to_numpy()
    # 故意写错的参数名：正确拼写是 num_leaves
    model = lgb.LGBMClassifier(num_leavs=63, learning_rate=0.05)
    model.fit(feats, merged["label"].to_numpy())
    threshold = 0.5
    feats = index.filter(regex="smart_.*_normalized").fillna(0.0).to_numpy()

    out = index[["serial_number"]].copy()
    out["score"] = model.predict_proba(feats)[:, 1]
    out["alarm"] = (out["score"] >= threshold).astype(int)
    out.to_csv(args.out, index=False)


if __name__ == "__main__":
    main()
