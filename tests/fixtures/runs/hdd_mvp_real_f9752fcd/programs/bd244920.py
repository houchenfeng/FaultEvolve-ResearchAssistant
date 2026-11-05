"""Improved solution: Using LightGBM with cross-validation for better feature utilization and threshold selection.

I/O contract:
    python init.py --data-dir <dir> --split <val|test> --out <pred.csv>

Reads   <data-dir>/train_history.csv.gz, <data-dir>/train_labels.csv,
        <data-dir>/<split>_history.csv.gz, <data-dir>/<split>_index.csv
Writes  <out> with columns serial_number, score, alarm
"""

import argparse
import os
import time

import numpy as np
import pandas as pd
from sklearn.model_selection import StratifiedKFold
from sklearn.preprocessing import StandardScaler
import lightgbm as lgb

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


def weighted_auprc(y_true, y_scores, weights):
    """Calculate weighted AUPRC"""
    # Sort by scores descending
    idx = np.argsort(y_scores)[::-1]
    y_true_sorted = y_true[idx]
    weights_sorted = weights[idx]
    
    total_pos = np.sum(weights * y_true)
    if total_pos == 0:
        return 0.0
    
    cum_pos = np.cumsum(y_true_sorted * weights_sorted)
    cum_all = np.cumsum(weights_sorted)
    
    precisions = cum_pos / cum_all
    recalls = cum_pos / total_pos
    
    # Calculate AUPRC using trapezoidal rule
    recalls_diff = np.diff(np.concatenate(([0], recalls)))
    precisions_extended = np.concatenate(([0], precisions))
    auprc = np.sum(recalls_diff * precisions_extended)
    
    return auprc


def recall_at_far_threshold(y_true, y_scores, weights, target_far=0.002):
    """Find threshold that achieves target false alarm rate"""
    idx = np.argsort(y_scores)[::-1]
    y_true_sorted = y_true[idx]
    weights_sorted = weights[idx]
    
    total_neg = np.sum(weights * (1 - y_true))
    if total_neg == 0:
        return 0.5  # default threshold
    
    thresholds = np.unique(y_scores)
    best_threshold = 0.5
    
    for th in thresholds:
        pred = y_scores >= th
        fp = np.sum(weights * (1 - y_true) * pred)
        far = fp / total_neg
        
        if far <= target_far:
            best_threshold = th
            break
            
    return best_threshold


def bootstrap_f1(y_true, y_scores, weights, n_bootstrap=200, threshold=None):
    """Calculate bootstrap F1 scores"""
    if threshold is None:
        threshold = best_f1_threshold(y_true, y_scores, weights)
        
    f1_scores = []
    n_samples = len(y_true)
    
    for _ in range(n_bootstrap):
        # Stratified bootstrap sampling
        pos_idx = np.where(y_true == 1)[0]
        neg_idx = np.where(y_true == 0)[0]
        
        pos_samples = np.random.choice(pos_idx, size=len(pos_idx), replace=True)
        neg_samples = np.random.choice(neg_idx, size=len(neg_idx), replace=True)
        
        bootstrap_idx = np.concatenate([pos_samples, neg_samples])
        
        y_true_boot = y_true[bootstrap_idx]
        y_scores_boot = y_scores[bootstrap_idx]
        w_boot = weights[bootstrap_idx]
        
        pred = y_scores_boot >= threshold
        tp = np.sum(w_boot * (y_true_boot == 1) * pred)
        fp = np.sum(w_boot * (y_true_boot == 0) * pred)
        fn = np.sum(w_boot * (y_true_boot == 1) * ~pred)
        
        f1 = 2 * tp / max(2 * tp + fp + fn, 1e-12)
        f1_scores.append(f1)
    
    return np.percentile(f1_scores, 10)  # Return 10th percentile


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--split", required=True, choices=["val", "test"])
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    start_time = time.time()
    
    train_hist = pd.read_csv(os.path.join(args.data_dir, "train_history.csv.gz"), parse_dates=["date"])
    train_lab = pd.read_csv(os.path.join(args.data_dir, "train_labels.csv")).set_index("serial_number")
    query_hist = pd.read_csv(os.path.join(args.data_dir, f"{args.split}_history.csv.gz"), parse_dates=["date"])
    query_idx = pd.read_csv(os.path.join(args.data_dir, f"{args.split}_index.csv"))

    x_train = last_snapshot(train_hist).reindex(train_lab.index).fillna(0.0)
    y_train = train_lab["label"].to_numpy()
    w_train = train_lab["weight"].to_numpy()

    # Use 3-fold cross validation to get out-of-fold predictions
    skf = StratifiedKFold(n_splits=3, shuffle=True, random_state=42)
    oof_preds = np.zeros(len(y_train))
    
    for fold, (train_idx, val_idx) in enumerate(skf.split(x_train, y_train)):
        X_tr, X_val = x_train.iloc[train_idx], x_train.iloc[val_idx]
        y_tr, y_val = y_train[train_idx], y_train[val_idx]
        w_tr = w_train[train_idx]
        
        # Train LightGBM model
        train_data = lgb.Dataset(X_tr, label=y_tr, weight=w_tr)
        val_data = lgb.Dataset(X_val, label=y_val, weight=w_train[val_idx], reference=train_data)
        
        params = {
            'objective': 'binary',
            'metric': 'binary_logloss',
            'boosting_type': 'gbdt',
            'num_leaves': 31,
            'learning_rate': 0.05,
            'feature_fraction': 0.9,
            'bagging_fraction': 0.8,
            'bagging_freq': 5,
            'verbose': -1,
            'seed': 42
        }
        
        model = lgb.train(
            params,
            train_data,
            valid_sets=[val_data],
            num_boost_round=300,
            callbacks=[lgb.early_stopping(stopping_rounds=50), lgb.log_evaluation(period=0)]
        )
        
        oof_preds[val_idx] = model.predict(X_val)
    
    # Find optimal threshold based on OOF predictions
    threshold = best_f1_threshold(y_train, oof_preds, w_train)
    
    # Train final model on full training data
    train_data = lgb.Dataset(x_train, label=y_train, weight=w_train)
    params = {
        'objective': 'binary',
        'metric': 'binary_logloss',
        'boosting_type': 'gbdt',
        'num_leaves': 31,
        'learning_rate': 0.05,
        'feature_fraction': 0.9,
        'bagging_fraction': 0.8,
        'bagging_freq': 5,
        'verbose': -1,
        'seed': 42
    }
    
    final_model = lgb.train(
        params,
        train_data,
        num_boost_round=300,
        callbacks=[lgb.log_evaluation(period=0)]
    )

    x_query = last_snapshot(query_hist).reindex(query_idx["serial_number"]).fillna(0.0)
    p = final_model.predict(x_query)
    pred = pd.DataFrame({
        "serial_number": query_idx["serial_number"],
        "score": p,
        "alarm": (p >= threshold).astype(int),
    })
    pred.to_csv(args.out, index=False)


if __name__ == "__main__":
    main()