"""Improved solution: LightGBM with temporal features on SMART history.

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

def extract_temporal_features(history_df):
    """Extract temporal features from 14-day history."""
    # Sort by date to ensure correct chronological order
    history_df = history_df.sort_values(['serial_number', 'date'])
    
    # Group by serial number to process each disk separately
    grouped = history_df.groupby('serial_number')
    
    # Get the last 14 days of data for each disk
    last_14_days = grouped.tail(14)
    grouped_14 = last_14_days.groupby('serial_number')
    
    # Initialize result dataframe
    result = pd.DataFrame(index=grouped_14.groups.keys())
    
    # Basic features: value at cutoff (last day)
    last_values = grouped_14.last().reindex(columns=FEATURES, fill_value=0.0)
    last_values = last_values.astype(float)
    last_values = np.log1p(last_values.clip(lower=0)).fillna(0.0)
    
    # Add vendor features
    last_models = grouped_14.last()[['model']].copy()
    for vendor in ["ST", "TOSHIBA", "HGST", "WDC"]:
        last_values[f"vendor_{vendor}"] = last_models["model"].iloc[:,0].str.startswith(vendor).astype(float)
    
    # Compute trend features: difference between last and first in 14-day window
    first_values = grouped_14.first().reindex(columns=FEATURES, fill_value=0.0)
    first_values = first_values.astype(float)
    first_values = np.log1p(first_values.clip(lower=0)).fillna(0.0)
    
    # Difference features (change over 14 days)
    for col in FEATURES:
        diff_col_name = f"{col}_diff"
        last_val = last_values[col] if col in last_values.columns else 0.0
        first_val = first_values[col] if col in first_values.columns else 0.0
        last_values[diff_col_name] = last_val - first_val
    
    # Additional trend features: mean, std over 14 days
    for col in FEATURES:
        if col in last_14_days.columns:
            col_data = last_14_days[col].astype(float)
            col_data = np.log1p(col_data.clip(lower=0)).fillna(0.0)
            
            # Mean over 14 days
            means = col_data.groupby('serial_number').mean()
            last_values[f"{col}_mean"] = means
            
            # Std over 14 days
            stds = col_data.groupby('serial_number').std().fillna(0.0)
            last_values[f"{col}_std"] = stds
    
    return last_values

def last_snapshot(history: pd.DataFrame) -> pd.DataFrame:
    """Extract features from the last 14 days of SMART history."""
    return extract_temporal_features(history)

def weighted_auprc(y_true, y_scores, weights):
    """Compute weighted AUPRC"""
    # Sort by scores descending
    idx = np.argsort(-y_scores)
    y_true_sorted = y_true[idx]
    weights_sorted = weights[idx]
    
    pos_weights = weights_sorted * y_true_sorted
    total_pos_weights = np.sum(pos_weights)
    if total_pos_weights == 0:
        return 0.0
    
    cum_pos_weights = np.cumsum(pos_weights)
    cum_all_weights = np.cumsum(weights_sorted)
    
    precisions = cum_pos_weights / cum_all_weights
    recalls = cum_pos_weights / total_pos_weights
    
    # Append start point (recall=0, precision=positive_ratio)
    precisions = np.concatenate([[np.sum(weights * y_true) / np.sum(weights)], precisions])
    recalls = np.concatenate([[0.0], recalls])
    
    # Calculate area under curve using trapezoidal rule
    return np.trapz(precisions, recalls)

def recall_at_far(y_true, y_scores, weights, target_far):
    """Compute recall at given false positive rate"""
    # Sort by scores descending
    idx = np.argsort(-y_scores)
    y_true_sorted = y_true[idx]
    weights_sorted = weights[idx]
    
    total_neg_weights = np.sum(weights * (1 - y_true))
    if total_neg_weights == 0:
        return 0.0
    
    cum_neg_weights = np.cumsum(weights_sorted * (1 - y_true_sorted))
    cum_pos_weights = np.cumsum(weights_sorted * y_true_sorted)
    
    far = cum_neg_weights / total_neg_weights
    target_idx = np.searchsorted(far, target_far, side='right')
    if target_idx == 0:
        return 0.0
    return cum_pos_weights[target_idx - 1] / np.sum(weights * y_true)

def bootstrap_f1(y_true, y_scores, weights, n_bootstrap=200, threshold=None):
    """Compute bootstrap F1 scores"""
    if threshold is None:
        # Use optimal threshold based on F1
        best_t, best_f1 = 0.5, -1.0
        for t in np.quantile(y_scores, np.linspace(0.90, 0.999, 60)):
            a = y_scores >= t
            tp = np.sum(weights * (y_true == 1) * a)
            fp = np.sum(weights * (y_true == 0) * a)
            fn = np.sum(weights * (y_true == 1) * ~a)
            f1 = 2 * tp / max(2 * tp + fp + fn, 1e-12)
            if f1 > best_f1:
                best_t, best_f1 = t, f1
        threshold = best_t
    
    f1_scores = []
    n_samples = len(y_true)
    
    for _ in range(n_bootstrap):
        # Sample with replacement
        bootstrap_indices = np.random.choice(n_samples, size=n_samples, replace=True)
        y_true_boot = y_true[bootstrap_indices]
        y_scores_boot = y_scores[bootstrap_indices]
        weights_boot = weights[bootstrap_indices]
        
        a = y_scores_boot >= threshold
        tp = np.sum(weights_boot * (y_true_boot == 1) * a)
        fp = np.sum(weights_boot * (y_true_boot == 0) * a)
        fn = np.sum(weights_boot * (y_true_boot == 1) * ~a)
        f1 = 2 * tp / max(2 * tp + fp + fn, 1e-12)
        f1_scores.append(f1)
    
    return np.array(f1_scores)

def get_oof_predictions_and_threshold(model_params, X, y, w, groups, n_splits=3):
    """Get out-of-fold predictions and find optimal threshold"""
    skf = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=42)
    oof_preds = np.zeros(len(X))
    
    for fold, (train_idx, val_idx) in enumerate(skf.split(X, y)):
        X_tr, X_val = X.iloc[train_idx], X.iloc[val_idx]
        y_tr, y_val = y[train_idx], y[val_idx]
        w_tr = w[train_idx]
        
        model = lgb.LGBMClassifier(**model_params)
        model.fit(
            X_tr, y_tr,
            sample_weight=w_tr,
            verbose=-1
        )
        oof_preds[val_idx] = model.predict_proba(X_val)[:, 1]
    
    # Find threshold using OOF predictions
    best_t, best_f1 = 0.5, -1.0
    for t in np.quantile(oof_preds, np.linspace(0.90, 0.999, 60)):
        a = oof_preds >= t
        tp = np.sum(w * (y == 1) * a)
        fp = np.sum(w * (y == 0) * a)
        fn = np.sum(w * (y == 1) * ~a)
        f1 = 2 * tp / max(2 * tp + fp + fn, 1e-12)
        if f1 > best_f1:
            best_t, best_f1 = t, f1
    
    return oof_preds, best_t

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--split", required=True, choices=["val", "test"])
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    start_time = time.time()
    
    # Load data
    train_hist = pd.read_csv(os.path.join(args.data_dir, "train_history.csv.gz"), parse_dates=["date"])
    train_lab = pd.read_csv(os.path.join(args.data_dir, "train_labels.csv")).set_index("serial_number")
    query_hist = pd.read_csv(os.path.join(args.data_dir, f"{args.split}_history.csv.gz"), parse_dates=["date"])
    query_idx = pd.read_csv(os.path.join(args.data_dir, f"{args.split}_index.csv"))

    # Extract features
    x_train = last_snapshot(train_hist).reindex(train_lab.index).fillna(0.0)
    y_train = train_lab["label"].to_numpy()
    w_train = train_lab["weight"].to_numpy()

    # Model parameters
    model_params = {
        'n_estimators': 300,
        'learning_rate': 0.03,
        'num_leaves': 31,
        'min_child_samples': 30,
        'subsample': 0.8,
        'subsample_freq': 1,
        'colsample_bytree': 0.7,
        'reg_lambda': 1.0,
        'n_jobs': -1,
        'verbose': -1,
        'random_state': 42
    }

    # Get OOF predictions and threshold
    oof_preds, threshold = get_oof_predictions_and_threshold(
        model_params, x_train, y_train, w_train, train_lab.index
    )

    # Train final model on full training data
    final_model = lgb.LGBMClassifier(**model_params)
    final_model.fit(x_train, y_train, sample_weight=w_train, verbose=-1)

    # Predict on query set
    x_query = last_snapshot(query_hist).reindex(query_idx["serial_number"]).fillna(0.0)
    p = final_model.predict_proba(x_query)[:, 1]
    
    # Create predictions dataframe
    pred = pd.DataFrame({
        "serial_number": query_idx["serial_number"],
        "score": p,
        "alarm": (p >= threshold).astype(int),
    })
    pred.to_csv(args.out, index=False)

    end_time = time.time()
    print(f"Total execution time: {end_time - start_time:.2f}s")

if __name__ == "__main__":
    main()