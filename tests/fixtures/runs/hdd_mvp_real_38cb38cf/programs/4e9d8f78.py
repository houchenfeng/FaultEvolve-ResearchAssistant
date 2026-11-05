"""Improved solution: LightGBM with temporal trend features and OOF threshold selection.

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

# Selected SMART features that show good predictive power
FEATURES = [
    "smart_5_raw", "smart_187_raw", "smart_188_raw", "smart_197_raw", "smart_198_raw",
    "smart_199_raw", "smart_9_raw", "smart_194_raw", "smart_1_normalized", "smart_7_normalized",
]

def extract_features(history: pd.DataFrame) -> pd.DataFrame:
    """Extract both snapshot and trend features from the history."""
    # Sort by date to ensure proper order
    history_sorted = history.sort_values(['serial_number', 'date']).copy()
    
    # Add log-transformed features to history for trend calculation
    for feat in FEATURES:
        col_name = feat
        if col_name in history_sorted.columns:
            history_sorted[f'{feat}_log'] = np.log1p(
                history_sorted[col_name].astype(float).clip(lower=0)
            ).fillna(0.0)
    
    # Calculate statistics for each serial number using vectorized operations
    trend_features_list = []
    
    # Convert date to ordinal for numerical calculations
    history_sorted['date_ordinal'] = pd.to_datetime(history_sorted['date']).apply(lambda x: x.toordinal())
    
    # Group by serial number and compute trend features
    grouped = history_sorted.groupby('serial_number')
    
    # Compute first and last values for each feature per disk
    first_vals = grouped[['date_ordinal'] + [f'{feat}_log' for feat in FEATURES if f'{feat}_log' in history_sorted.columns]].first()
    last_vals = grouped[['date_ordinal'] + [f'{feat}_log' for feat in FEATURES if f'{feat}_log' in history_sorted.columns]].last()
    
    # Calculate differences for slopes
    result_df = pd.DataFrame(index=first_vals.index)
    
    for feat in FEATURES:
        log_col = f'{feat}_log'
        if log_col in history_sorted.columns:
            # Calculate slope features
            diff_dates = last_vals['date_ordinal'] - first_vals['date_ordinal']
            diff_vals = last_vals[log_col] - first_vals[log_col]
            
            # Avoid division by zero
            slope = np.divide(diff_vals, diff_dates, out=np.zeros_like(diff_vals), where=diff_dates!=0)
            result_df[f'{feat}_slope'] = slope
            
            # Calculate other stats using agg
            temp_group = grouped[log_col].agg(['max', 'mean', 'std']).fillna(0.0)
            temp_group.columns = [f'{feat}_{stat}' for stat in ['max', 'mean', 'std']]
            result_df = result_df.join(temp_group)
    
    # Get last snapshots for base features
    last_snapshots = history_sorted.groupby('serial_number').tail(1).copy()
    last_snapshots.set_index('serial_number', inplace=True)
    
    # Create base feature matrix with snapshot values
    x = last_snapshots.reindex(columns=FEATURES).astype(float)
    x = np.log1p(x.clip(lower=0)).fillna(0.0)
    
    # Add vendor features
    for vendor in ["ST", "TOSHIBA", "HGST", "WDC"]:
        x[f"vendor_{vendor}"] = last_snapshots["model"].str.startswith(vendor).astype(float)
    
    # Merge trend features with base features
    x = x.join(result_df, how='left')
    # Fill NaN values created by join
    x = x.fillna(0.0)
    
    return x

def weighted_auprc(y_true, y_scores, weights):
    """Compute weighted AUPRC"""
    # Sort by scores in descending order
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
    
    # Handle edge case where there are no positive samples
    if len(precisions) == 0:
        return 0.0
    
    # Compute area under precision-recall curve
    # Using trapezoidal rule
    unique_recalls, unique_indices = np.unique(recalls, return_index=True)
    unique_precisions = np.maximum.accumulate(precisions[unique_indices][::-1])[::-1]
    
    if len(unique_recalls) > 1:
        return np.trapz(unique_precisions, unique_recalls)
    else:
        return precisions[0] if len(precisions) > 0 else 0.0

def recall_at_far(y_true, y_scores, weights, far_threshold=0.002):
    """Compute recall at given false positive rate threshold"""
    # Sort by scores in descending order
    idx = np.argsort(y_scores)[::-1]
    y_true_sorted = y_true[idx]
    weights_sorted = weights[idx]
    
    total_neg = np.sum(weights * (1 - y_true))
    total_pos = np.sum(weights * y_true)
    
    if total_neg == 0 or total_pos == 0:
        return 0.0
    
    cum_neg = np.cumsum((1 - y_true_sorted) * weights_sorted)
    cum_pos = np.cumsum(y_true_sorted * weights_sorted)
    
    far = cum_neg / total_neg
    recall = cum_pos / total_pos
    
    # Find the highest recall where FAR <= threshold
    valid_indices = np.where(far <= far_threshold)[0]
    if len(valid_indices) == 0:
        return 0.0
    
    return recall[valid_indices[-1]]

def compute_f1_weighted(y_true, y_pred, weights):
    """Compute weighted F1 score"""
    tp = np.sum(weights * y_true * y_pred)
    fp = np.sum(weights * (1 - y_true) * y_pred)
    fn = np.sum(weights * y_true * (1 - y_pred))
    
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0
    
    return 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--data-dir', required=True)
    parser.add_argument('--split', required=True, choices=['val', 'test'])
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    
    start_time = time.time()
    
    # Load data
    train_history = pd.read_csv(os.path.join(args.data_dir, 'train_history.csv.gz'), 
                                parse_dates=['date'])
    train_labels = pd.read_csv(os.path.join(args.data_dir, 'train_labels.csv'))
    query_history = pd.read_csv(os.path.join(args.data_dir, f'{args.split}_history.csv.gz'),
                                parse_dates=['date'])
    query_index = pd.read_csv(os.path.join(args.data_dir, f'{args.split}_index.csv'))
    
    # Extract features for training
    X_train_base = extract_features(train_history)
    X_query = extract_features(query_history)
    
    # Align features between train and query sets
    all_features = set(X_train_base.columns) & set(X_query.columns)
    X_train = X_train_base.reindex(columns=sorted(all_features), fill_value=0.0)
    X_query_aligned = X_query.reindex(columns=sorted(all_features), fill_value=0.0)
    
    # Prepare training labels
    y_train = train_labels.set_index('serial_number')['label']
    w_train = train_labels.set_index('serial_number')['weight']
    
    # Ensure same ordering
    y_train_aligned = y_train.reindex(X_train.index, fill_value=0)
    w_train_aligned = w_train.reindex(X_train.index, fill_value=1.0)
    
    # Train LightGBM model
    params = {
        'objective': 'binary',
        'metric': 'binary_logloss',
        'boosting_type': 'gbdt',
        'num_leaves': 255,
        'learning_rate': 0.05,
        'feature_fraction': 0.9,
        'bagging_fraction': 0.8,
        'bagging_freq': 5,
        'verbose': -1,
        'seed': 42
    }
    
    train_data = lgb.Dataset(X_train, label=y_train_aligned, weight=w_train_aligned)
    
    model = lgb.train(
        params,
        train_data,
        num_boost_round=100
    )
    
    # Predict on query set
    scores = model.predict(X_query_aligned)
    
    # Determine optimal threshold using training set (OOF approach)
    train_preds = model.predict(X_train)
    
    best_threshold = 0.5
    best_f1 = 0.0
    
    # Try different thresholds
    for threshold in np.linspace(0.01, 0.99, 50):
        train_alarms = (train_preds >= threshold).astype(int)
        f1 = compute_f1_weighted(y_train_aligned.values, train_alarms, w_train_aligned.values)
        
        if f1 > best_f1:
            best_f1 = f1
            best_threshold = threshold
    
    alarms = (scores >= best_threshold).astype(int)
    
    # Create output DataFrame
    results = pd.DataFrame({
        'serial_number': X_query_aligned.index,
        'score': scores,
        'alarm': alarms
    })
    
    # Ensure all query disks are included
    results = query_index[['serial_number']].merge(results, on='serial_number', how='left').fillna({'score': 0.0, 'alarm': 0})
    
    # Write results
    results.to_csv(args.out, index=False)
    
    end_time = time.time()
    print(f"Execution time: {end_time - start_time:.2f}s")

if __name__ == '__main__':
    main()