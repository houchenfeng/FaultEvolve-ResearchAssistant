"""Self-contained HDD candidate templates (string constants)."""

HDD_LOGREG_V1 = '''"""FE structured logreg candidate."""
import argparse
import json
import os

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

PARAMS = {{PARAMS_JSON}}
TRAIN = {{TRAIN_JSON}}
CALIBRATION = {{CALIBRATION_JSON}}
FEATURE_GROUPS = {{FEATURE_GROUPS_JSON}}
FITS_PER_RUN = 2

# FE-BLOCK-BEGIN feature
FEATURES = [
    "smart_5_raw", "smart_187_raw", "smart_188_raw", "smart_197_raw", "smart_198_raw",
    "smart_199_raw", "smart_9_raw", "smart_194_raw", "smart_1_normalized", "smart_7_normalized",
]


def build_features(history: pd.DataFrame) -> pd.DataFrame:
    last = history.sort_values("date").groupby("serial_number").tail(1).set_index("serial_number")
    x = last.reindex(columns=FEATURES).astype(float)
    x = np.log1p(x.clip(lower=0)).fillna(0.0)
    if "vendor_onehot" in FEATURE_GROUPS:
        for vendor in ["ST", "TOSHIBA", "HGST", "WDC"]:
            x[f"vendor_{vendor}"] = last["model"].str.startswith(vendor).astype(float)
    return x
# FE-BLOCK-END feature

# FE-BLOCK-BEGIN train
def best_f1_threshold(y, p, w):
    best_t, best_f1 = 0.5, -1.0
    for t in np.quantile(p, np.linspace(0.90, 0.999, CALIBRATION.get("quantile_grid", 60))):
        a = p >= t
        tp = np.sum(w * (y == 1) * a)
        fp = np.sum(w * (y == 0) * a)
        fn = np.sum(w * (y == 1) * ~a)
        f1 = 2 * tp / max(2 * tp + fp + fn, 1e-12)
        if f1 > best_f1:
            best_t, best_f1 = t, f1
    return float(best_t)
# FE-BLOCK-END train

# FE-BLOCK-BEGIN model
def fit_model(x_train, y_train, w_train):
    wp = PARAMS.get("weight_policy", TRAIN.get("weight_policy", "sample_weight_only"))
    kwargs = {"max_iter": int(PARAMS.get("max_iter", 2000)), "C": float(PARAMS.get("C", 1.0)), "penalty": PARAMS.get("penalty", "l2"), "solver": PARAMS.get("solver", "lbfgs")}
    if wp == "class_weight_only":
        kwargs["class_weight"] = "balanced"
    model = make_pipeline(StandardScaler(), LogisticRegression(**kwargs))
    if wp == "sample_weight_only":
        model.fit(x_train, y_train, logisticregression__sample_weight=w_train)
    else:
        model.fit(x_train, y_train)
    return model
# FE-BLOCK-END model

# FE-BLOCK-BEGIN calibration
def calibrate_threshold(model, x_train, y_train, w_train):
    p = model.predict_proba(x_train)[:, 1]
    return best_f1_threshold(y_train, p, w_train)
# FE-BLOCK-END calibration


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
    x_train = build_features(train_hist).reindex(train_lab.index).fillna(0.0)
    y_train = train_lab["label"].to_numpy()
    w_train = train_lab["weight"].to_numpy()
    model = fit_model(x_train, y_train, w_train)
    threshold = calibrate_threshold(model, x_train, y_train, w_train)
    x_query = build_features(query_hist).reindex(query_idx["serial_number"]).fillna(0.0)
    p = model.predict_proba(x_query)[:, 1]
    pred = pd.DataFrame({"serial_number": query_idx["serial_number"], "score": p, "alarm": (p >= threshold).astype(int)})
    pred.to_csv(args.out, index=False)


if __name__ == "__main__":
    main()
'''

HDD_LIGHTGBM_V1 = HDD_LOGREG_V1.replace(
    "from sklearn.linear_model import LogisticRegression",
    "import lightgbm as lgb",
).replace(
    "# FE-BLOCK-BEGIN model",
    "# FE-BLOCK-BEGIN model\n# lightgbm family",
).replace(
    '''def fit_model(x_train, y_train, w_train):
    wp = PARAMS.get("weight_policy", TRAIN.get("weight_policy", "sample_weight_only"))
    kwargs = {"max_iter": int(PARAMS.get("max_iter", 2000)), "C": float(PARAMS.get("C", 1.0)), "penalty": PARAMS.get("penalty", "l2"), "solver": PARAMS.get("solver", "lbfgs")}
    if wp == "class_weight_only":
        kwargs["class_weight"] = "balanced"
    model = make_pipeline(StandardScaler(), LogisticRegression(**kwargs))
    if wp == "sample_weight_only":
        model.fit(x_train, y_train, logisticregression__sample_weight=w_train)
    else:
        model.fit(x_train, y_train)
    return model''',
    '''def fit_model(x_train, y_train, w_train):
    wp = PARAMS.get("weight_policy", TRAIN.get("weight_policy", "none"))
    params = {
        "num_leaves": int(PARAMS.get("num_leaves", 31)),
        "learning_rate": float(PARAMS.get("learning_rate", 0.05)),
        "n_estimators": int(PARAMS.get("n_estimators", 200)),
        "min_child_samples": int(PARAMS.get("min_child_samples", 20)),
        "subsample": float(PARAMS.get("subsample", 0.8)),
        "colsample_bytree": float(PARAMS.get("colsample_bytree", 0.8)),
        "reg_lambda": float(PARAMS.get("reg_lambda", 1.0)),
        "max_depth": int(PARAMS.get("max_depth", -1)),
        "n_jobs": int(PARAMS.get("n_jobs", 1)),
        "verbosity": -1,
    }
    if wp == "none" and "scale_pos_weight" in PARAMS:
        params["scale_pos_weight"] = float(PARAMS["scale_pos_weight"])
    model = lgb.LGBMClassifier(**params)
    if wp == "sample_weight_only":
        model.fit(x_train, y_train, sample_weight=w_train)
    elif wp == "class_weight_only":
        model.fit(x_train, y_train, class_weight="balanced")
    else:
        model.fit(x_train, y_train)
    return model''',
).replace(
    "make_pipeline(StandardScaler(), LogisticRegression(**kwargs))",
    "model",
).replace(
    "model.predict_proba(x_train)[:, 1]",
    "model.predict_proba(x_train)[:, 1]",
).replace('template_id="hdd.logreg.v1"', 'template_id="hdd.lightgbm.v1"')

TEMPLATE_MAP = {
    "hdd.logreg.v1": HDD_LOGREG_V1,
    "hdd.lightgbm.v1": HDD_LIGHTGBM_V1,
}
