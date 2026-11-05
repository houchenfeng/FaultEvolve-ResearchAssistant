"""Initial solution: logistic regression on the cutoff-day SMART snapshot.

I/O contract:
    python init.py --data-dir <dir> --split <val|test> --out <pred.csv>

Reads   <data-dir>/train_history.csv.gz, <data-dir>/train_labels.csv,
        <data-dir>/<split>_history.csv.gz, <data-dir>/<split>_index.csv
Writes  <out> with columns serial_number, score, alarm
"""

import argparse
import os

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

FEATURES = [
    "smart_5_raw", "smart_187_raw", "smart_188_raw", "smart_197_raw", "smart_198_raw",
    "smart_199_raw", "smart_9_raw", "smart_194_raw", "smart_1_normalized", "smart_7_normalized",
]


def last_snapshot(history: pd.DataFrame) -> pd.DataFrame:
    last = history.sort_values("date").groupby("serial_number").tail(1).set_index("serial_number")
    x = last.reindex(columns=FEATURES).astype(float)
    x = np.log1p(x.clip(lower=0)).fillna(0.0)
    for vendor in ["ST", "TOSHIBA", "HGST", "WDC"]:
        x[f"vendor_{vendor}"] = last["model"].str.startswith(vendor).astype(float)
    return x


def best_f1_threshold(y: np.ndarray, p: np.ndarray, w: np.ndarray) -> float:
    best_t, best_f1 = 0.5, -1.0
    for t in np.quantile(p, np.linspace(0.90, 0.999, 60)):
        a = p >= t
        tp = np.sum(w * (y == 1) * a)
        fp = np.sum(w * (y == 0) * a)
        fn = np.sum(w * (y == 1) * ~a)
        f1 = 2 * tp / max(2 * tp + fp + fn, 1e-12)
        if f1 > best_f1:
            best_t, best_f1 = t, f1
    return float(best_t)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--split", required=True, choices=["val", "test"])
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    train_hist = pd.read_csv(os.path.join(args.data_dir, "train_history.csv.gz"), parse_dates=["date"])
    train_lab = pd.read_csv(os.path.join(args.data_dir, "train_labels.csv")).set_index("serial_number")
    query_hist = pd.read_csv(os.path.join(args.data_dir, f"{args.split}_history.csv.gz"), parse_dates=["date"])
    query_idx = pd.read_csv(os.path.join(args.data_dir, f"{args.split}_index.csv"))

    x_train = last_snapshot(train_hist).reindex(train_lab.index).fillna(0.0)
    y_train = train_lab["label"].to_numpy()
    w_train = train_lab["weight"].to_numpy()

    model = make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000, C=0.5))
    model.fit(x_train, y_train, logisticregression__sample_weight=w_train)
    threshold = best_f1_threshold(y_train, model.predict_proba(x_train)[:, 1], w_train)

    x_query = last_snapshot(query_hist).reindex(query_idx["serial_number"]).fillna(0.0)
    p = model.predict_proba(x_query)[:, 1]
    pred = pd.DataFrame({
        "serial_number": query_idx["serial_number"],
        "score": p,
        "alarm": (p >= threshold).astype(int),
    })
    pred.to_csv(args.out, index=False)


if __name__ == "__main__":
    main()
