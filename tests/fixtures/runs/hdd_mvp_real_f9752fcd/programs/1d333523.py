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
    
    # Get all features that exist in the dataframe
    available_raw = [f for f in raw_features if f in history.columns]
    available_norm = [f for f in norm_features if f in history.columns]
    
    # Initialize result dataframe with basic info
    result = pd.DataFrame(index=last_day.index)
    
    # Add vendor features
    for vendor in ["ST", "TOSHIBA", "HGST", "WDC"]:
        result[f"vendor_{vendor}"] = last_day["model"].str.startswith(vendor).astype(float)
    
    # Add model as a categorical feature (will be converted later)
    result['model'] = last_day["model"]
    
    # Prepare all features together for efficient processing
    all_features = available_raw + available_norm
    
    # For each feature, calculate statistics over the history
    for feat in all_features:
        if feat in history.columns:
            # Current value (cutoff day)
            last_vals = last_day[feat].astype(float)
            result[f'{feat}_current'] = np.log1p(last_vals.clip(lower=0)).fillna(0.0)
            
            # Get historical values for this feature
            hist_data = history[['serial_number', 'date', feat]].dropna(subset=[feat])
            if len(hist_data) > 0:
                # Create a temporary df to hold stats for this feature
                feat_hist = hist_data.copy()
                
                # Group by serial number and compute stats over the last 14 days
                grouped_stats = hist_data.groupby('serial_number')[feat].agg(['first', 'last', 'mean', 'std', 'min', 'max']).fillna(0.0)
                grouped_stats.columns = [f'{feat}_{stat}' for stat in ['first', 'last', 'mean', 'std', 'min', 'max']]
                
                # Calculate trend (difference between last and first)
                grouped_stats[f'{feat}_trend'] = grouped_stats[f'{feat}_last'] - grouped_stats[f'{feat}_first']
                grouped_stats[f'{feat}_range'] = grouped_stats[f'{feat}_max'] - grouped_stats[f'{feat}_min']
                
                # Join back to result
                result = result.join(grouped_stats)
    
    # Fill any remaining NaN with 0
    result = result.fillna(0.0)
    
    return result


def weighted_auprc(y_true, y_scores, sample_weights):
    """Calculate weighted AUPRC"""
    from sklearn.metrics import precision_recall_curve, auc
    
    # Sort indices by scores descending
    desc_score_indices = np.argsort(y_scores)[::-1]
    y_true_sorted = y_true[desc_score_indices]
    weights_sorted = sample_weights[desc_score_indices]
    
    # Compute cumulative sums for precision and recall
    weight_sum = weights_sorted.sum()
    pos_weight_sum = (weights_sorted * y_true_sorted).sum()
    
    if pos_weight_sum == 0 or pos_weight_sum == weight_sum:
        return 1.0 if pos_weight_sum == 0 else 0.0
    
    # Calculate precision and recall at each threshold
    weight_cumsum = np.cumsum(weights_sorted)
    pos_weight_cumsum = np.cumsum(weights_sorted * y_true_sorted)
    
    recall = pos_weight_cumsum / pos_weight_sum
    precision = pos_weight_cumsum / weight_cumsum
    
    # Add point (0,1) to handle edge case
    recall = np.concatenate([[0], recall])
    precision = np.concatenate([[1], precision])
    
    # Calculate AUC using trapezoidal rule
    return auc(recall, precision)


def recall_at_far_threshold(y_true, y_scores, sample_weights, far_budget=0.002):
    """Calculate maximum recall at false alarm rate <= far_budget"""
    desc_score_indices = np.argsort(y_scores)[::-1]
    y_true_sorted = y_true[desc_score_indices]
    weights_sorted = sample_weights[desc_score_indices]
    
    total_neg_weight = (weights_sorted * (1 - y_true_sorted)).sum()
    if total_neg_weight == 0:
        return 1.0
    
    pos_weight_cumsum = np.cumsum(weights_sorted * y_true_sorted)
    neg_weight_cumsum = np.cumsum(weights_sorted * (1 - y_true_sorted))
    
    far_rates = neg_weight_cumsum / total_neg_weight
    
    # Find the highest threshold where FAR <= budget
    valid_indices = np.where(far_rates <= far_budget)[0]
    if len(valid_indices) == 0:
        return 0.0
    
    max_recall_idx = valid_indices[-1]
    recall_at_threshold = pos_weight_cumsum[max_recall_idx] / pos_weight_cumsum[-1] if pos_weight_cumsum[-1] > 0 else 0.0
    
    return recall_at_threshold


def find_best_threshold_cv(X_train, y_train, w_train, cv_folds=5):
    """Find best threshold using cross-validation"""
    skf = StratifiedKFold(n_splits=cv_folds, shuffle=True, random_state=42)
    
    thresholds = []
    for train_idx, val_idx in skf.split(X_train, y_train):
        X_tr, X_val = X_train.iloc[train_idx], X_train.iloc[val_idx]
        y_tr, y_val = y_train.iloc[train_idx], y_train.iloc[val_idx]
        w_tr, w_val = w_train.iloc[train_idx], w_train.iloc[val_idx]
        
        # Train model on fold
        train_data = lgb.Dataset(X_tr, label=y_tr, weight=w_tr)
        params = {
            'objective': 'binary',
            'metric': 'binary_logloss',
            'verbose': -1,
            'seed': 42,
            'num_leaves': 63,
            'learning_rate': 0.05,
            'feature_fraction': 0.8,
            'bagging_fraction': 0.8,
            'bagging_freq': 5
        }
        
        model = lgb.train(params, train_data, num_boost_round=100)
        
        # Predict on validation
        y_pred = model.predict(X_val)
        
        # Find best threshold based on weighted F1
        best_f1 = 0
        best_thresh = 0.5
        
        for thresh in np.arange(0.1, 0.9, 0.05):
            y_pred_binary = (y_pred >= thresh).astype(int)
            
            # Calculate weighted F1
            tp = ((y_pred_binary == 1) & (y_val == 1) * w_val).sum()
            fp = ((y_pred_binary == 1) & (y_val == 0) * w_val).sum()
            fn = ((y_pred_binary == 0) & (y_val == 1) * w_val).sum()
            
            if tp + fp > 0:
                prec = tp / (tp + fp)
            else:
                prec = 0
                
            if tp + fn > 0:
                rec = tp / (tp + fn)
            else:
                rec = 0
                
            if prec + rec > 0:
                f1 = 2 * prec * rec / (prec + rec)
            else:
                f1 = 0
            
            if f1 > best_f1:
                best_f1 = f1
                best_thresh = thresh
        
        thresholds.append(best_thresh)
    
    return np.mean(thresholds)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--data-dir', type=str, required=True)
    parser.add_argument('--split', type=str, required=True, choices=['val', 'test'])
    parser.add_argument('--out', type=str, required=True)
    args = parser.parse_args()
    
    # Load training data
    print("Loading training data...")
    train_history = pd.read_csv(os.path.join(args.data_dir, 'train_history.csv.gz'))
    train_labels = pd.read_csv(os.path.join(args.data_dir, 'train_labels.csv'))
    
    # Extract features for training
    print("Extracting training features...")
    train_features = extract_features(train_history)
    
    # Merge with labels
    train_data = train_labels.merge(train_features, left_on='serial_number', right_index=True, how='left')
    train_data = train_data.fillna(0.0)
    
    # Prepare training data
    feature_cols = [col for col in train_data.columns if col not in ['serial_number', 'model', 'cutoff_date', 'label', 'weight']]
    X_train = train_data[feature_cols]
    y_train = train_data['label'].values
    w_train = train_data['weight'].values
    
    # Convert categorical columns to numeric if needed
    X_train = X_train.astype(float)
    
    # Train model
    print("Training model...")
    train_dataset = lgb.Dataset(X_train, label=y_train, weight=w_train)
    
    params = {
        'objective': 'binary',
        'metric': 'binary_logloss',
        'verbose': -1,
        'seed': 42,
        'num_leaves': 63,
        'learning_rate': 0.05,
        'feature_fraction': 0.8,
        'bagging_fraction': 0.8,
        'bagging_freq': 5
    }
    
    model = lgb.train(params, train_dataset, num_boost_round=100)
    
    # Load test data
    print("Loading test data...")
    test_history = pd.read_csv(os.path.join(args.data_dir, f'{args.split}_history.csv.gz'))
    test_index = pd.read_csv(os.path.join(args.data_dir, f'{args.split}_index.csv'))
    
    # Extract features for test
    print("Extracting test features...")
    test_features = extract_features(test_history)
    
    # Ensure same features order
    missing_cols = set(X_train.columns) - set(test_features.columns)
    for col in missing_cols:
        test_features[col] = 0.0
    
    test_features = test_features.reindex(columns=X_train.columns, fill_value=0.0)
    
    # Predict
    print("Making predictions...")
    test_predictions = model.predict(test_features)
    
    # Find optimal threshold using cross-validation approach
    optimal_threshold = find_best_threshold_cv(X_train, pd.Series(y_train), pd.Series(w_train))
    
    # Create alarms
    test_alarms = (test_predictions >= optimal_threshold).astype(int)
    
    # Create output dataframe
    output_df = pd.DataFrame({
        'serial_number': test_index['serial_number'],
        'score': test_predictions,
        'alarm': test_alarms
    })
    
    # Write output
    output_df.to_csv(args.out, index=False)
    print(f"Predictions saved to {args.out}")


if __name__ == "__main__":
    main()