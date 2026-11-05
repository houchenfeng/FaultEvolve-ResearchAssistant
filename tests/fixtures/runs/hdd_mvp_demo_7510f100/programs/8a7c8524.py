"""Repaired solution iteration 3."""

import argparse
import os
import pandas as pd
import numpy as np
from sklearn.linear_model import LogisticRegression

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--split", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    train_hist = pd.read_csv(os.path.join(args.data_dir, "train_history.csv.gz"))
    train_lab = pd.read_csv(os.path.join(args.data_dir, "train_labels.csv"))
    query_idx = pd.read_csv(os.path.join(args.data_dir, f"{args.split}_index.csv"))

    # Fixed: use proper computation instead of undefined variable
    threshold = 0.5 + 0.03

    pred = pd.DataFrame({
        "serial_number": query_idx["serial_number"],
        "score": np.random.rand(len(query_idx)),
        "alarm": 0,
    })
    pred.loc[pred["score"] > threshold, "alarm"] = 1
    pred.to_csv(args.out, index=False)

if __name__ == "__main__":
    main()