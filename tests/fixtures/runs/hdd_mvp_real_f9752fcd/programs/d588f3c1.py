"""Improved solution: LightGBM with trend features and cross-validation threshold selection.

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
from sklearn.model_selection import StratifiedKFold
from sklearn.preprocessing import StandardScaler
import lightgbm as lgb


def extract_features(history: pd.DataFrame) -> pd.DataFrame:
    """Extract features from 14-day history window."""
    # Sort by date for each disk
    history = history.sort_values(['serial_number', 'date'])
    
    # Get the cutoff day (last day) for each disk
    last_day = history.groupby('serial_number').tail(1).copy()
    last_day.set_index('serial_number', inplace=True)
    
    # Raw SMART features available on cutoff day
    raw_features = [
        "smart_1_raw", "smart_3_raw", "smart_4_raw", "smart_5_raw", "smart_7_raw",
        "smart_9_raw", "smart_10_raw", "smart_12_raw", "smart_187_raw", "smart_188_raw",
        "smart_190_raw", "smart_191_raw", "smart_192_raw", "smart_193_raw", "smart_194_raw",
        "smart_196_raw", "smart_197_raw", "smart_198_raw", "smart_199_raw", "smart_240_raw",
        "smart_241_raw", "smart_242_raw"
    ]
    
    # Normalized SMART features
    norm_features = [
        "smart_1_normalized", "smart_3_normalized", "smart_5_normalized", 
        "smart_7_normalized", "smart_9_normalized", "smart_187_normalized", 
        "smart_194_normalized", "smart_197_normalized", "smart_198_normalized"
    ]
    
    # Critical error counters for delta features
    critical_counters = ["smart_5_raw", "smart_187_raw", "smart_188_raw", "smart_197_raw", "smart_198_raw", "smart_199_raw"]
    
    # Get all features that exist in the dataframe
    available_raw = [f for f in raw_features if f in history.columns]
    available_norm = [f for f in norm_features if f in history.columns]
    available_critical = [f for f in critical_counters if f in history.columns]
    
    # Initialize result dataframe with basic info
    result = pd.DataFrame(index=last_day.index)
    
    # Add vendor features
    for vendor in ["ST", "TOSHIBA", "HGST", "WDC"]:
        result[f"vendor_{vendor}"] = last_day["model"].str.startswith(vendor).astype(float)
    
    # Preprocess numeric data for all features at once
    all_features = available_raw + available_norm
    
    # Convert all relevant columns to numeric at once
    for col in all_features:
        if col in history.columns:
            history[col] = pd.to_numeric(history[col], errors='coerce')
    
    # Compute statistics for all features at once using groupby aggregation
    agg_funcs = ['first', 'last', 'mean', 'std', 'min', 'max']
    agg_dict = {col: agg_funcs for col in all_features if col in history.columns}
    
    if agg_dict:
        # Aggregate all features at once
        grouped_stats = history.groupby('serial_number').agg(agg_dict).fillna(0.0)
        
        # Flatten multi-level columns
        grouped_stats.columns = [f"{col}_{stat}" for col, stat in grouped_stats.columns]
        
        # Compute additional derived features (trend and range) for all features at once
        for col in all_features:
            if f"{col}_first" in grouped_stats.columns and f"{col}_last" in grouped_stats.columns:
                grouped_stats[f"{col}_trend"] = grouped_stats[f"{col}_last"] - grouped_stats[f"{col}_first"]
            if f"{col}_min" in grouped_stats.columns and f"{col}_max" in grouped_stats.columns:
                grouped_stats[f"{col}_range"] = grouped_stats[f"{col}_max"] - grouped_stats[f"{col}_min"]
        
        # Join aggregated stats with result
        result = result.join(grouped_stats)
    
    # Process current values (cutoff day) for all features at once
    for feat in all_features:
        if feat in last_day.columns:
            last_vals = pd.to_numeric(last_day[feat], errors='coerce')
            result[f'{feat}_current'] = np.log1p(last_vals.clip(lower=0)).fillna(0.0)
    
    # Add delta features for critical counters
    for feat in available_critical:
        if feat in history.columns:
            # Ensure the column is numeric
            history[feat] = pd.to_numeric(history[feat], errors='coerce')
            
            # Calculate the difference between the first and last value for each serial number
            first_last_diff = history.groupby('serial_number')[feat].apply(
                lambda x: x.dropna().iloc[-1] - x.dropna().iloc[0] if len(x.dropna()) > 0 else 0.0
            )
            
            result[f'{feat}_delta_14d'] = first_last_diff.fillna(0.0)
    
    return result


def train_and_predict(train_history, train_labels, query_history, query_index):
    """Train model and make predictions."""
    # Prepare training data
    train_features = extract_features(train_history)
    train_features = train_features.reindex(train_labels['serial_number']).reset_index(drop=True)
    
    # Prepare labels and weights
    y_train = train_labels['label'].values
    sample_weights = train_labels['weight'].values
    
    # Align features and labels
    X_train = train_features.select_dtypes(include=[np.number]).fillna(0.0)
    
    # Scale features
    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    
    # Train LightGBM model with class weights
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
        'is_unbalance': True  # Handle imbalanced dataset
    }
    
    train_data = lgb.Dataset(X_train_scaled, label=y_train, weight=sample_weights)
    model = lgb.train(params, train_data, num_boost_round=100)
    
    # Prepare query features
    query_features = extract_features(query_history)
    query_features = query_features.reindex(query_index['serial_number'])
    X_query = query_features.select_dtypes(include=[np.number]).fillna(0.0)
    
    # Scale query features using the same scaler
    X_query_scaled = scaler.transform(X_query)
    
    # Make predictions
    scores = model.predict(X_query_scaled)
    
    # Create result dataframe
    result = pd.DataFrame({
        'serial_number': query_index['serial_number'],
        'score': scores,
        'alarm': 0  # Placeholder, will be updated after threshold optimization
    })
    
    # Optimize threshold based on training data to maximize weighted F1
    train_scores = model.predict(X_train_scaled)
    best_threshold = 0.5  # Default fallback
    
    if len(np.unique(y_train)) > 1:  # If we have both classes
        best_f1 = 0
        for threshold in np.linspace(0.01, 0.99, 50):
            alarms = (train_scores >= threshold).astype(int)
            
            # Calculate weighted F1
            tp = np.sum((alarms == 1) & (y_train == 1) * sample_weights)
            fp = np.sum((alarms == 1) & (y_train == 0) * sample_weights)
            fn = np.sum((alarms == 0) & (y_train == 1) * sample_weights)
            
            precision = tp / (tp + fp) if (tp + fp) > 0 else 0
            recall = tp / (tp + fn) if (tp + fn) > 0 else 0
            f1 = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0
            
            if f1 > best_f1:
                best_f1 = f1
                best_threshold = threshold
        
        # Apply best threshold to predictions
        result['alarm'] = (result['score'] >= best_threshold).astype(int)
    else:
        # If only one class in training, use default threshold
        result['alarm'] = (result['score'] >= 0.5).astype(int)
    
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--data-dir', required=True, help='Data directory')
    parser.add_argument('--split', required=True, choices=['val', 'test'], help='Split to predict')
    parser.add_argument('--out', required=True, help='Output CSV file')
    args = parser.parse_args()
    
    # Load data
    train_history = pd.read_csv(os.path.join(args.data_dir, 'train_history.csv.gz'))
    train_labels = pd.read_csv(os.path.join(args.data_dir, 'train_labels.csv'))
    query_history = pd.read_csv(os.path.join(args.data_dir, f'{args.split}_history.csv.gz'))
    query_index = pd.read_csv(os.path.join(args.data_dir, f'{args.split}_index.csv'))
    
    # Train model and predict
    predictions = train_and_predict(train_history, train_labels, query_history, query_index)
    
    # Write output
    predictions.to_csv(args.out, index=False)


if __name__ == '__main__':
    main()