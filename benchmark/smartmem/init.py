"""Initial solution: logistic regression on CE trend features, one call per unit.

本仓自定的起点，不代表方案水平，也不是官方 baseline - 它只是一个能跑通 CLI 合同、只看得见
标签该看见的东西的最小种子。

I/O contract:
    python init.py --data-dir <dir> --split <dev|val> --out <pred.csv>

Reads   <data-dir>/train_samples.csv.gz, <data-dir>/train_labels.csv,
        <data-dir>/<split>_samples.csv.gz, <data-dir>/<split>_index.csv
Writes  <out> with columns sample_id, score, alarm

The query slice reaches this program without labels by construction, and no ticket file or run
directory is ever opened: the only supervision is ``train_labels.csv``.

Two choices carry the whole design. A unit is called at its single most urgent row, because the
scoring rule counts a serial number once and ignores how many rows it fires. And the alarm cut is a
**percentile** of the loudest-row distribution, fitted on the training slice and re-applied to the
query slice, because an absolute probability cut does not survive the density shift between the two
- on the 200-unit slice a train-fitted cut silenced every dev alarm.
"""

import argparse

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

FEATURES = [
    "event_count",
    "recent_half_count",
    "earlier_half_count",
    "growth_rate",
    "minutes_since_last_event",
    "ce_count",
    "ce_read_count",
    "ce_scrub_count",
    "unexpected_error_type_count",
    "distinct_rowid",
    "distinct_bankid",
    "distinct_columnid",
    "top_rowid_share",
    "rowid_repeat_rate",
    "window_fill_rate",
]
PERCENTILES = np.arange(50.0, 100.0, 1.0)


def design(frame: pd.DataFrame, medians: pd.Series) -> pd.DataFrame:
    """Numeric feature block, log1p on counts, gaps carried by the training medians."""
    x = pd.DataFrame(index=frame.index)
    for column in FEATURES:
        if column in frame.columns:
            values = pd.to_numeric(frame[column], errors="coerce").astype("float64")
        else:
            values = pd.Series(float("nan"), index=frame.index, dtype="float64")
        x[column] = np.log1p(values.clip(lower=0)) if "_count" in column else values
    # A column the training slice never carried has no median to fall back on, so it fills zero.
    return x.fillna(medians.reindex(x.columns)).fillna(0.0)


def unit_f1(loud: pd.Series, positive: pd.Series, percentile: float) -> float:
    """SN-level proxy F1 on training rows: a unit scores only if it is called and it does fail."""
    called = loud >= loud.quantile(percentile / 100)
    tp = int((called & positive).sum())
    fp = int((called & ~positive).sum())
    fn = int((~called & positive).sum())
    return 2 * tp / max(2 * tp + fp + fn, 1e-12)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--split", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    root = args.data_dir
    train = pd.read_csv(f"{root}/train_samples.csv.gz")
    labels = pd.read_csv(f"{root}/train_labels.csv")
    index = pd.read_csv(f"{root}/{args.split}_index.csv")
    query = pd.read_csv(f"{root}/{args.split}_samples.csv.gz")

    train = train.drop(columns=["label"], errors="ignore").merge(
        labels[["sample_id", "label"]], on="sample_id", how="inner"
    )
    if train.empty or int(train["label"].sum()) == 0:
        raise SystemExit("training slice carries no labelled failure rows; nothing to fit")

    medians = design(train, pd.Series(dtype=float)).median(numeric_only=True)
    model = make_pipeline(
        StandardScaler(), LogisticRegression(class_weight="balanced", max_iter=2000)
    )
    model.fit(design(train, medians), train["label"])

    trained = pd.Series(model.predict_proba(design(train, medians))[:, 1], index=train.index)
    loud_train = trained.groupby(train["unit_id"].values).max()
    positive = train.assign(fails=train["label"] == 1).groupby("unit_id")["fails"].any()
    percentile = max(PERCENTILES, key=lambda q: unit_f1(loud_train, positive, q))

    seen = query["sample_id"].astype(str)
    scores = pd.Series(0.0, index=seen, name="score")
    scores.loc[seen] = model.predict_proba(design(query, medians))[:, 1]

    # One call per unit, at its loudest row; the cut travels as a percentile, not a value.
    rows = index.assign(sample_id=index["sample_id"].astype(str), score=scores.reindex(
        index["sample_id"].astype(str)
    ).values)
    loud = rows.groupby("unit_id")["score"].idxmax()
    peaks = rows.loc[loud]
    cut = peaks["score"].quantile(percentile / 100)
    firing = set(peaks.loc[peaks["score"] >= cut, "sample_id"])
    rows["alarm"] = rows["sample_id"].isin(firing).astype(int)
    rows[["sample_id", "score", "alarm"]].to_csv(args.out, index=False)


if __name__ == "__main__":
    main()
