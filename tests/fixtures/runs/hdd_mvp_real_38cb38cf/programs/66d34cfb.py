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
    
    # Convert date to ordinal for numerical calculations
    history_sorted['date_ordinal'] = pd.to_datetime(history_sorted['date']).dt.toordinal()
    
    # Add log-transformed features to history for trend calculation
    for feat in BASE_FEATURES:
        col_name = feat
        if col_name in history_sorted.columns:
            # Only process non-null values
            mask = history_sorted[col_name].notna()
            history_sorted[f'{feat}_log'] = 0.0  # Initialize
            temp_series = history_sorted.loc[mask, col_name].astype(float).clip(lower=0)
            history_sorted.loc[mask, f'{feat}_log'] = np.log1p(temp_series)
    
    # Add log-transformed critical features for delta calculation
    for feat in CRITICAL_FEATURES:
        if feat in history_sorted.columns:
            mask = history_sorted[feat].notna()
            history_sorted[f'{feat}_log'] = 0.0  # Initialize
            temp_series = history_sorted.loc[mask, feat].astype(float).clip(lower=0)
            history_sorted.loc[mask, f'{feat}_log'] = np.log1p(temp_series)
    
    # Calculate statistics for each serial number using vectorized operations
    grouped = history_sorted.groupby('serial_number')
    
    # Prepare result dataframe
    result_dfs = []
    
    # For each serial number, calculate features efficiently
    for name, group in grouped:
        # Get the current group data sorted by date
        group = group.sort_values('date').reset_index(drop=True)
        
        # Initialize result row
        result_row = {'serial_number': name}
        
        # Calculate trend features using first and last values
        for feat in BASE_FEATURES:
            log_col = f'{feat}_log'
            if log_col in group.columns and len(group) > 0:
                values = group[log_col].values
                dates = group['date_ordinal'].values
                
                # Slope calculation
                if len(values) > 1 and dates[-1] != dates[0]:
                    slope = (values[-1] - values[0]) / (dates[-1] - dates[0])
                else:
                    slope = 0.0
                result_row[f'{feat}_slope'] = slope
                
                # Statistical measures
                result_row[f'{feat}_max'] = np.max(values) if len(values) > 0 else 0.0
                result_row[f'{feat}_mean'] = np.mean(values) if len(values) > 0 else 0.0
                result_row[f'{feat}_std'] = np.std(values) if len(values) > 1 else 0.0
        
        # Calculate delta features for critical SMART attributes
        for feat in CRITICAL_FEATURES:
            log_col = f'{feat}_log'
            if log_col in group.columns and len(group) > 0:
                values = group[log_col].values
                
                # 14-day delta (last - first)
                first_val = values[0] if len(values) > 0 else 0.0
                last_val = values[-1] if len(values) > 0 else 0.0
                delta_14 = max(0, last_val - first_val)
                result_row[f'{feat}_delta_14'] = delta_14
                
                # Reset flag
                reset_flag = 1 if (last_val - first_val) < 0 else 0
                result_row[f'{feat}_reset_flag'] = reset_flag
        
        # Add the result row to list
        result_dfs.append(result_row)
    
    # Combine all results
    if result_dfs:
        result_df = pd.DataFrame(result_dfs)
    else:
        # Return empty dataframe with appropriate columns
        cols = ['serial_number'] + [f'{feat}_slope' for feat in BASE_FEATURES] + \
               [f'{feat}_max' for feat in BASE_FEATURES] + \
               [f'{feat}_mean' for feat in BASE_FEATURES] + \
               [f'{feat}_std' for feat in BASE_FEATURES] + \
               [f'{feat}_delta_14' for feat in CRITICAL_FEATURES] + \
               [f'{feat}_reset_flag' for feat in CRITICAL_FEATURES]
        result_df = pd.DataFrame(columns=cols)
    
    return result_df

def prepare_features(df, features):
    """Prepare feature matrix from dataframe."""
    X = df[features].fillna(0.0).values
    return X

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--data-dir', required=True, help='Data directory path')
    parser.add_argument('--split', required=True, choices=['val', 'test'], help='Split to predict')
    parser.add_argument('--out', required=True, help='Output CSV path')
    args = parser.parse_args()

    start_time = time.time()

    # Load data
    train_history = pd.read_csv(os.path.join(args.data_dir, 'train_history.csv.gz'))
    train_labels = pd.read_csv(os.path.join(args.data_dir, 'train_labels.csv'))
    query_history = pd.read_csv(os.path.join(args.data_dir, f"{args.split}_history.csv.gz"))
    query_index = pd.read_csv(os.path.join(args.data_dir, f"{args.split}_index.csv"))

    # Extract features for both train and query sets
    print("Extracting features...")
    train_features = extract_features(train_history)
    query_features = extract_features(query_history)

    # Merge with labels for training
    train_data = train_labels.merge(train_features, on='serial_number', how='left')
    query_data = query_index.merge(query_features, on='serial_number', how='left')

    # Define features to use
    trend_features = [f'{feat}_slope' for feat in BASE_FEATURES] + \
                     [f'{feat}_max' for feat in BASE_FEATURES] + \
                     [f'{feat}_mean' for feat in BASE_FEATURES] + \
                     [f'{feat}_std' for feat in BASE_FEATURES] + \
                     [f'{feat}_delta_14' for feat in CRITICAL_FEATURES] + \
                     [f'{feat}_reset_flag' for feat in CRITICAL_FEATURES]

    all_features = trend_features

    # Prepare training data
    X_train = prepare_features(train_data, all_features)
    y_train = train_data['label'].values
    sample_weights = train_data['weight'].values
    
    # Handle missing values
    X_train = np.nan_to_num(X_train, nan=0.0, posinf=0.0, neginf=0.0)

    # Train LightGBM model
    print("Training model...")
    params = {
        'objective': 'binary',
        'metric': 'auc',
        'boosting_type': 'gbdt',
        'num_leaves': 31,
        'learning_rate': 0.05,
        'feature_fraction': 0.9,
        'bagging_fraction': 0.8,
        'bagging_freq': 5,
        'verbose': -1,
        'class_weight': 'balanced'
    }

    lgb_train = lgb.Dataset(X_train, y_train, weight=sample_weights)
    model = lgb.train(params, lgb_train, num_boost_round=100)

    # Prepare query features
    X_query = prepare_features(query_data, all_features)
    X_query = np.nan_to_num(X_query, nan=0.0, posinf=0.0, neginf=0.0)

    # Predict scores
    scores = model.predict(X_query)

    # Create submission dataframe
    submission = pd.DataFrame({
        'serial_number': query_data['serial_number'],
        'score': scores,
        'alarm': (scores > 0.5).astype(int)  # Placeholder threshold
    })

    # Write output
    submission.to_csv(args.out, index=False)
    print(f"Completed in {time.time() - start_time:.2f}s")

if __name__ == "__main__":
    main()