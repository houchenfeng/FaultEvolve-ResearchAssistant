"""Enhanced solution: LightGBM with temporal features and cross-validation threshold selection.

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
from sklearn.model_selection import GroupKFold
from sklearn.preprocessing import StandardScaler
import lightgbm as lgb
from sklearn.metrics import average_precision_score
from scipy import stats

# Critical SMART attributes for failure prediction
CRITICAL_FEATURES = [
    "smart_5_raw", "smart_187_raw", "smart_188_raw", "smart_197_raw", "smart_198_raw",
    "smart_199_raw", "smart_9_raw", "smart_194_raw", "smart_1_normalized", "smart_7_normalized",
]

DELTA_FEATURES = [
    "smart_5_raw", "smart_187_raw", "smart_188_raw", "smart_197_raw", "smart_198_raw", "smart_199_raw"
]

VENDOR_LIST = ["ST", "TOSHIBA", "HGST", "WDC"]


def engineer_features(history: pd.DataFrame) -> pd.DataFrame:
    """Engineer temporal features from history."""
    # Sort by date for each disk
    history = history.sort_values(["serial_number", "date"])
    
    # Create pivot table for date-based operations
    all_dates = history[['serial_number', 'date'] + DELTA_FEATURES].copy()
    all_dates['date_idx'] = all_dates.groupby('serial_number')['date'].rank(method='dense').astype(int)
    max_date_idx = all_dates.groupby('serial_number')['date_idx'].transform('max')
    all_dates = all_dates[all_dates['date_idx'] <= 14]  # Only use up to 14 days
    
    # Pivot to get values per day index
    pivoted_data = {}
    for feat in DELTA_FEATURES:
        subset = all_dates[['serial_number', 'date_idx', feat]].dropna()
        pivot_table = subset.pivot(index='serial_number', columns='date_idx', values=feat)
        pivoted_data[feat] = pivot_table
    
    # Get last snapshot features
    last_snap = history.groupby('serial_number').last()
    x = last_snap.reindex(columns=CRITICAL_FEATURES).astype(float)
    
    # Log transform positive values and handle NaN
    x = np.log1p(x.clip(lower=0)).fillna(0.0)
    
    # Vendor features
    for vendor in VENDOR_LIST:
        x[f"vendor_{vendor}"] = last_snap["model"].str.startswith(vendor).astype(float)
    
    # Add delta features (change over time window)
    for feat in DELTA_FEATURES:
        if feat in pivoted_data:
            pivot_table = pivoted_data[feat]
            
            # Last value
            last_vals = pivot_table.iloc[:, -1] if pivot_table.shape[1] > 0 else pd.Series(dtype=float)
            
            # First value
            first_vals = pivot_table.iloc[:, 0] if pivot_table.shape[1] > 0 else pd.Series(dtype=float)
            
            # Calculate delta (last - first)
            delta_14 = last_vals - first_vals
            x[f"{feat}_delta_14"] = delta_14.fillna(0.0).clip(lower=0)
            
            # If we have enough days, calculate 7-day and 3-day deltas
            if pivot_table.shape[1] >= 8:
                day_7_vals = pivot_table.iloc[:, -7] if pivot_table.shape[1] >= 7 else first_vals
                x[f"{feat}_delta_7"] = (last_vals - day_7_vals).fillna(0.0).clip(lower=0)
                
            if pivot_table.shape[1] >= 4:
                day_11_vals = pivot_table.iloc[:, -3] if pivot_table.shape[1] >= 3 else first_vals
                x[f"{feat}_delta_3"] = (last_vals - day_11_vals).fillna(0.0).clip(lower=0)
    
    # Add first appearance features for critical counters
    for feat in ["smart_5_raw", "smart_197_raw", "smart_198_raw", "smart_187_raw"]:
        if feat in pivoted_data:
            pivot_table = pivoted_data[feat]
            # Convert to boolean: whether value is non-zero
            nz = pivot_table > 0
            
            # Became non-zero in window: was zero initially but non-zero at end
            if pivot_table.shape[1] > 1:
                became_nonzero = (~nz.iloc[:, 0]).fillna(True) & nz.iloc[:, -1].fillna(False)
                x[f"{feat}_became_nonzero"] = became_nonzero.astype(float)
                
                # Days since first non-zero
                days_since_first = []
                for idx in range(len(nz)):
                    row = nz.iloc[idx, :]
                    first_nz_pos = row.idxmax() if row.any() else None
                    if first_nz_pos is not None:
                        days_since_first.append(pivot_table.shape[1] - first_nz_pos)
                    else:
                        days_since_first.append(np.nan)
                x[f"{feat}_days_since_first"] = pd.Series(days_since_first, index=nz.index).fillna(-1).astype(float)
            else:
                x[f"{feat}_became_nonzero"] = 0.0
                x[f"{feat}_days_since_first"] = -1.0
    
    # Additional vendor-specific features
    for vendor in VENDOR_LIST:
        vendor_mask = last_snap["model"].str.startswith(vendor)
        for feat in ["smart_187_raw", "smart_188_raw", "smart_190_raw", "smart_197_raw", "smart_198_raw"]:
            if feat in last_snap.columns:
                feat_vals = last_snap[feat].astype(float)
                x[f"{vendor}_{feat}_log"] = np.log1p(feat_vals.where(vendor_mask, 0.0)).fillna(0.0)
                
    # Add trend features using linear regression slope
    for feat in DELTA_FEATURES:
        if feat in pivoted_data:
            pivot_table = pivoted_data[feat]
            slopes = []
            for idx in pivot_table.index:
                row = pivot_table.loc[idx, :].dropna()
                if len(row) > 1:
                    x_coords = np.arange(len(row))
                    slope, _, _, _, _ = stats.linregress(x_coords, row.values)
                    slopes.append(slope)
                else:
                    slopes.append(0.0)
            x[f"{feat}_trend"] = pd.Series(slopes, index=pivot_table.index).fillna(0.0).astype(float)
    
    return x


def compute_optimal_threshold(y_true, y_pred_proba, weights):
    """Find threshold that maximizes weighted F1."""
    # Use multiple thresholds to find optimal
    thresholds = np.linspace(0, 1, 101)
    best_f1 = 0
    best_thresh = 0.5
    
    for thresh in thresholds:
        y_pred_binary = (y_pred_proba >= thresh).astype(int)
        
        # Calculate weighted precision and recall
        tp = np.sum(weights * y_true * y_pred_binary)
        fp = np.sum(weights * (1 - y_true) * y_pred_binary)
        fn = np.sum(weights * y_true * (1 - y_pred_binary))
        
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0
        
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0
        
        if f1 > best_f1:
            best_f1 = f1
            best_thresh = thresh
            
    return best_thresh


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", required=True, help="Data directory")
    parser.add_argument("--split", required=True, choices=["val", "test"], help="Split to predict")
    parser.add_argument("--out", required=True, help="Output CSV path")
    args = parser.parse_args()

    start_time = time.time()

    # Load data
    print("Loading data...")
    train_hist = pd.read_csv(os.path.join(args.data_dir, "train_history.csv.gz"))
    train_labels = pd.read_csv(os.path.join(args.data_dir, "train_labels.csv"))
    query_hist = pd.read_csv(os.path.join(args.data_dir, f"{args.split}_history.csv.gz"))
    query_index = pd.read_csv(os.path.join(args.data_dir, f"{args.split}_index.csv"))

    # Engineer features
    print("Engineering features...")
    X_train = engineer_features(train_hist)
    X_query = engineer_features(query_hist)

    # Align feature sets
    all_cols = set(X_train.columns) | set(X_query.columns)
    for col in all_cols:
        if col not in X_train.columns:
            X_train[col] = 0.0
        if col not in X_query.columns:
            X_query[col] = 0.0

    X_train = X_train.reindex(columns=sorted(all_cols), fill_value=0.0)
    X_query = X_query.reindex(columns=sorted(all_cols), fill_value=0.0)

    # Prepare training data
    y_train = train_labels.set_index("serial_number")["label"]
    sample_weights = train_labels.set_index("serial_number")["weight"]
    models = train_labels.set_index("serial_number")["model"]

    # Ensure all training samples have features
    valid_train_sn = X_train.index.intersection(y_train.index)
    X_train = X_train.loc[valid_train_sn]
    y_train = y_train.loc[valid_train_sn]
    sample_weights = sample_weights.loc[valid_train_sn]
    models = models.loc[valid_train_sn]

    # Train model with cross-validation for threshold selection
    print("Training model...")
    gkf = GroupKFold(n_splits=5)
    oof_preds = np.zeros(len(X_train))

    # Define model parameters
    params = {
        'objective': 'binary',
        'metric': 'binary_logloss',
        'boosting_type': 'gbdt',
        'num_leaves': 31,
        'learning_rate': 0.05,
        'feature_fraction': 0.8,
        'bagging_fraction': 0.8,
        'bagging_freq': 5,
        'verbose': -1,
        'is_unbalance': True,
    }

    # Train with K-Fold CV to get OOF predictions for threshold selection
    for fold, (train_idx, val_idx) in enumerate(gkf.split(X_train, y_train, groups=models)):
        X_tr = X_train.iloc[train_idx]
        y_tr = y_train.iloc[train_idx]
        w_tr = sample_weights.iloc[train_idx]
        
        X_val = X_train.iloc[val_idx]
        y_val = y_train.iloc[val_idx]
        w_val = sample_weights.iloc[val_idx]
        
        # Train model without categorical_feature to avoid the error
        dtrain = lgb.Dataset(X_tr, label=y_tr, weight=w_tr)
        dval = lgb.Dataset(X_val, label=y_val, weight=w_val, reference=dtrain)
        
        model = lgb.train(
            params,
            dtrain,
            valid_sets=[dval],
            num_boost_round=1000,
            callbacks=[lgb.early_stopping(stopping_rounds=50)],
        )
        
        oof_preds[val_idx] = model.predict(X_val)

    # Find optimal threshold based on OOF predictions
    opt_threshold = compute_optimal_threshold(y_train.values, oof_preds, sample_weights.values)

    # Retrain final model on full dataset
    dtrain_full = lgb.Dataset(X_train, label=y_train, weight=sample_weights)
    final_model = lgb.train(
        params,
        dtrain_full,
        num_boost_round=1000,
    )

    # Make predictions on query set
    query_scores = final_model.predict(X_query)

    # Generate alarms based on optimized threshold
    query_alarms = (query_scores >= opt_threshold).astype(int)

    # Create submission dataframe
    submission = pd.DataFrame({
        'serial_number': X_query.index,
        'score': query_scores,
        'alarm': query_alarms
    })

    # Ensure all query disks are included
    submission = query_index[['serial_number']].merge(submission, on='serial_number', how='left').fillna({'score': 0, 'alarm': 0})
    submission['alarm'] = submission['alarm'].astype(int)

    # Save results
    submission.to_csv(args.out, index=False)
    print(f"Predictions saved to {args.out}")
    print(f"Runtime: {time.time() - start_time:.2f}s")


if __name__ == "__main__":
    main()