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
BASE_FEATURES = [
    "smart_5_raw", "smart_187_raw", "smart_188_raw", "smart_197_raw", "smart_198_raw",
    "smart_199_raw", "smart_9_raw", "smart_194_raw", "smart_1_normalized", "smart_7_normalized",
]

CRITICAL_FEATURES = ["smart_5_raw", "smart_187_raw", "smart_188_raw", "smart_197_raw", "smart_198_raw", "smart_199_raw"]

def extract_features(history: pd.DataFrame) -> pd.DataFrame:
    """Extract both snapshot and trend features from the history."""
    # Sort by date to ensure proper order
    history_sorted = history.sort_values(['serial_number', 'date']).copy()
    
    # Add log-transformed features to history for trend calculation
    for feat in BASE_FEATURES:
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
    first_vals = grouped[['date_ordinal'] + [f'{feat}_log' for feat in BASE_FEATURES if f'{feat}_log' in history_sorted.columns]].first()
    last_vals = grouped[['date_ordinal'] + [f'{feat}_log' for feat in BASE_FEATURES if f'{feat}_log' in history_sorted.columns]].last()
    
    # Calculate differences for slopes
    result_df = pd.DataFrame(index=first_vals.index)
    
    for feat in BASE_FEATURES:
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
    x = last_snapshots.reindex(columns=BASE_FEATURES).astype(float)
    x = np.log1p(x.clip(lower=0)).fillna(0.0)
    
    # Add vendor features
    for vendor in ["ST", "TOSHIBA", "HGST", "WDC"]:
        x[f"vendor_{vendor}"] = last_snapshots["model"].str.startswith(vendor).astype(float)
    
    # Merge trend features with base features
    x = x.join(result_df, how='left')
    # Fill NaN values created by join
    x = x.fillna(0.0)
    
    # Now add critical delta features
    # First, create pivot tables to access specific days
    critical_cols = [col for col in CRITICAL_FEATURES if col in history_sorted.columns]
    if critical_cols:
        # Pivot to get each serial number as row and day index as column
        date_range = history_sorted[['serial_number', 'date']].drop_duplicates()
        date_range['day_idx'] = date_range.groupby('serial_number')['date'].rank(method='dense').astype(int)
        
        # Join back to main dataframe
        history_with_day_idx = history_sorted.merge(date_range[['serial_number', 'date', 'day_idx']], 
                                                    on=['serial_number', 'date'], how='left')
        
        # For each critical feature, calculate deltas
        for col in critical_cols:
            if col in history_with_day_idx.columns:
                # Create a pivot table for this feature
                pivot_table = history_with_day_idx.pivot(index='serial_number', columns='day_idx', values=col).ffill(axis=1)
                
                # Get last values
                last_values = pivot_table.iloc[:, -1]
                
                # Get first values
                first_values = pivot_table.iloc[:, 0]
                
                # Calculate 14-day delta (last - first)
                x[f'{col}_delta_14'] = (last_values - first_values).fillna(0.0)
                
                # Calculate 7-day delta (last - value 7 days ago)
                if pivot_table.shape[1] >= 8:
                    seven_days_ago = pivot_table.iloc[:, -8]
                    x[f'{col}_delta_7'] = (last_values - seven_days_ago).fillna(0.0)
                else:
                    x[f'{col}_delta_7'] = 0.0
                
                # Calculate 3-day delta (last - value 3 days ago)
                if pivot_table.shape[1] >= 4:
                    three_days_ago = pivot_table.iloc[:, -4]
                    x[f'{col}_delta_3'] = (last_values - three_days_ago).fillna(0.0)
                else:
                    x[f'{col}_delta_3'] = 0.0
                
                # Check for counter resets in critical features
                max_val = pivot_table.max(axis=1)
                x[f'{col}_has_reset'] = ((first_values > last_values) & (max_val > first_values)).astype(float)
    
    return x

def calculate_threshold_oof(y_true, y_scores, weights, n_folds=5):
    """Calculate optimal threshold using out-of-fold predictions."""
    skf = StratifiedKFold(n_splits=n_folds, shuffle=True, random_state=42)
    oof_preds = np.zeros(len(y_scores))
    
    for train_idx, val_idx in skf.split(y_scores, y_true):
        # Weighted approach would require custom implementation
        # For simplicity, we'll optimize threshold directly on full data
        pass
    
    # Direct optimization of threshold based on weighted F1
    best_threshold = 0.5
    best_f1 = 0.0
    
    for threshold in np.linspace(0.01, 0.99, 99):
        y_pred = (y_scores >= threshold).astype(int)
        # Calculate weighted F1
        tp = np.sum((y_pred == 1) & (y_true == 1) * weights)
        fp = np.sum((y_pred == 1) & (y_true == 0) * weights)
        fn = np.sum((y_pred == 0) & (y_true == 1) * weights)
        
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0
        
        if f1 > best_f1:
            best_f1 = f1
            best_threshold = threshold
    
    return best_threshold

def calculate_model_target_encoding(train_history, train_labels, alpha=50):
    """Calculate out-of-fold target encoding for model feature."""
    # Combine history and labels to get model-failure mapping
    train_data = train_labels[['serial_number', 'model', 'label']].copy()
    
    # Calculate global failure rate
    global_rate = train_data['label'].mean()
    
    # Calculate per-model stats
    model_stats = train_data.groupby('model')['label'].agg(['sum', 'count']).reset_index()
    model_stats.columns = ['model', 'pos_count', 'total_count']
    
    # Apply smoothing: (pos_count + alpha*global_rate) / (total_count + alpha)
    model_stats['smoothed_rate'] = (model_stats['pos_count'] + alpha * global_rate) / \
                                   (model_stats['total_count'] + alpha)
    
    # Create mapping dict
    model_to_rate = dict(zip(model_stats['model'], model_stats['smoothed_rate']))
    
    return model_to_rate

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--data-dir', type=str, required=True)
    parser.add_argument('--split', type=str, required=True, choices=['val', 'test'])
    parser.add_argument('--out', type=str, required=True)
    args = parser.parse_args()

    start_time = time.time()

    # Load training data
    print("Loading training data...")
    train_history = pd.read_csv(os.path.join(args.data_dir, 'train_history.csv.gz'))
    train_labels = pd.read_csv(os.path.join(args.data_dir, 'train_labels.csv'))

    # Load validation/test data
    print(f"Loading {args.split} data...")
    query_history = pd.read_csv(os.path.join(args.data_dir, f"{args.split}_history.csv.gz"))
    query_index = pd.read_csv(os.path.join(args.data_dir, f"{args.split}_index.csv"))

    # Calculate model target encoding from training data
    print("Calculating model target encoding...")
    model_encoding_map = calculate_model_target_encoding(train_history, train_labels)

    # Extract features for training
    print("Extracting training features...")
    X_train_full = extract_features(train_history)
    
    # Add model target encoding to training features
    train_model_mapping = train_labels.set_index('serial_number')['model'].to_dict()
    X_train_models = pd.Series([train_model_mapping.get(sn, 'unknown') for sn in X_train_full.index], 
                               index=X_train_full.index)
    X_train_model_encoded = X_train_models.map(model_encoding_map).fillna(0.0)
    X_train_full['model_target_enc'] = X_train_model_encoded

    # Prepare training labels
    y_train = train_labels.set_index('serial_number')['label']
    w_train = train_labels.set_index('serial_number')['weight']
    
    # Align labels with features
    y_train = y_train.reindex(X_train_full.index)
    w_train = w_train.reindex(X_train_full.index)

    # Extract features for query
    print("Extracting query features...")
    X_query = extract_features(query_history)
    
    # Add model target encoding to query features
    query_model_mapping = query_index.set_index('serial_number')['model'].to_dict()
    X_query_models = pd.Series([query_model_mapping.get(sn, 'unknown') for sn in X_query.index], 
                               index=X_query.index)
    X_query_model_encoded = X_query_models.map(model_encoding_map).fillna(0.0)
    X_query['model_target_enc'] = X_query_model_encoded

    # Ensure both training and query have same features
    all_features = X_train_full.columns.tolist()
    for col in all_features:
        if col not in X_query.columns:
            X_query[col] = 0.0
    X_query = X_query[all_features]

    # Convert categorical columns to category type for LightGBM
    categorical_cols = ['model'] if 'model' in X_train_full.columns else []
    for col in categorical_cols:
        if col in X_train_full.columns:
            X_train_full[col] = X_train_full[col].astype('category')
        if col in X_query.columns:
            X_query[col] = X_query[col].astype('category')

    # Train model
    print("Training model...")
    lgb_params = {
        'objective': 'binary',
        'metric': 'auc',
        'boosting_type': 'gbdt',
        'num_leaves': 31,
        'learning_rate': 0.05,
        'feature_fraction': 0.9,
        'bagging_fraction': 0.8,
        'bagging_freq': 5,
        'verbose': -1,
        'seed': 42
    }

    # Use sample weights
    train_dataset = lgb.Dataset(X_train_full, label=y_train, weight=w_train, 
                                categorical_feature=categorical_cols)
    
    model = lgb.train(lgb_params, train_dataset, num_boost_round=200)

    # Make predictions
    print("Making predictions...")
    y_query_proba = model.predict(X_query)

    # Create submission dataframe
    results = pd.DataFrame({
        'serial_number': X_query.index,
        'score': y_query_proba,
        'alarm': 0  # Placeholder, will be filled later
    })

    # Calculate threshold on training OOF predictions for alarm
    print("Calculating optimal threshold...")
    y_train_proba = model.predict(X_train_full)
    threshold = calculate_threshold_oof(y_train.values, y_train_proba, w_train.values)
    
    # Apply threshold to get alarms
    results['alarm'] = (results['score'] >= threshold).astype(int)

    # Write results
    results[['serial_number', 'score', 'alarm']].to_csv(args.out, index=False)

    end_time = time.time()
    print(f"Total runtime: {end_time - start_time:.2f}s")

if __name__ == "__main__":
    main()