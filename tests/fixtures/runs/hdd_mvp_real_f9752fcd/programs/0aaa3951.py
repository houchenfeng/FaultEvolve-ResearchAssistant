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
    
    # Process raw features
    for feat in available_raw:
        # Value at cutoff
        last_vals = last_day[feat].astype(float)
        result[f'{feat}_current'] = np.log1p(last_vals.clip(lower=0)).fillna(0.0)
        
        # Get historical values for this feature
        hist_data = history[['serial_number', 'date', feat]].dropna()
        if len(hist_data) > 0:
            # Group by serial number and compute stats over the last 14 days
            grouped = hist_data.groupby('serial_number')[feat].agg(['first', 'last', 'mean', 'std', 'min', 'max']).fillna(0.0)
            grouped.columns = [f'{feat}_{stat}' for stat in ['first', 'last', 'mean', 'std', 'min', 'max']]
            
            # Calculate trend (difference between last and first)
            grouped[f'{feat}_trend'] = grouped[f'{feat}_last'] - grouped[f'{feat}_first']
            grouped[f'{feat}_range'] = grouped[f'{feat}_max'] - grouped[f'{feat}_min']
            
            # Only merge back for serial numbers in result
            result = result.join(grouped)
    
    # Process normalized features
    for feat in available_norm:
        last_vals = last_day[feat].astype(float)
        result[f'{feat}_current'] = np.log1p(last_vals.clip(lower=0)).fillna(0.0)
        
        # Get historical values for this feature
        hist_data = history[['serial_number', 'date', feat]].dropna()
        if len(hist_data) > 0:
            grouped = hist_data.groupby('serial_number')[feat].agg(['first', 'last', 'mean', 'std', 'min', 'max']).fillna(0.0)
            grouped.columns = [f'{feat}_{stat}' for stat in ['first', 'last', 'mean', 'std', 'min', 'max']]
            grouped[f'{feat}_trend'] = grouped[f'{feat}_last'] - grouped[f'{feat}_first']
            grouped[f'{feat}_range'] = grouped[f'{feat}_max'] - grouped[f'{feat}_min']
            
            result = result.join(grouped)
    
    # Model-specific rank normalization for key raw attributes (FE08)
    key_raw_features = ["smart_1_raw", "smart_7_raw", "smart_9_raw", "smart_193_raw", "smart_240_raw", "smart_241_raw", "smart_242_raw"]
    for feat in key_raw_features:
        if feat in last_day.columns:
            # Create a temporary series with model and feature value
            temp_df = last_day[[feat, 'model']].copy()
            temp_df[feat] = pd.to_numeric(temp_df[feat], errors='coerce')
            
            # Compute rank within each model group
            temp_df[f'model_rank_{feat}'] = temp_df.groupby('model')[feat].rank(pct=True, method='average')
            
            # Fill NaN values (in case some models don't have enough samples)
            temp_df[f'model_rank_{feat}'] = temp_df[f'model_rank_{feat}'].fillna(0.5)
            
            # Add the normalized feature to result
            result[f'model_rank_{feat}'] = temp_df[f'model_rank_{feat}']
    
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
    
    weight_cumsum = np.cumsum(weights_sorted)
    pos_weight_cumsum = np.cumsum(weights_sorted * y_true_sorted)
    neg_weight_cumsum = np.cumsum(weights_sorted * (1 - y_true_sorted))
    
    # Calculate FAR at each threshold
    far = neg_weight_cumsum / total_neg_weight
    
    # Find the highest threshold where FAR <= budget
    valid_indices = np.where(far <= far_budget)[0]
    if len(valid_indices) == 0:
        return 0.0
    
    # Get the recall at the highest valid threshold
    max_valid_idx = valid_indices[-1]
    recall_at_max_valid = pos_weight_cumsum[max_valid_idx] / pos_weight_cumsum[-1] if pos_weight_cumsum[-1] > 0 else 0.0
    
    return recall_at_max_valid


def bootstrap_f1(y_true, y_scores, sample_weights, n_bootstrap=200, threshold=None):
    """Calculate bootstrap F1 scores and return percentiles"""
    f1_scores = []
    
    n_samples = len(y_true)
    for _ in range(n_bootstrap):
        # Stratified bootstrap sampling
        pos_indices = np.where(y_true == 1)[0]
        neg_indices = np.where(y_true == 0)[0]
        
        # Sample with replacement maintaining class balance approximately
        n_pos = len(pos_indices)
        n_neg = len(neg_indices)
        
        pos_sample = np.random.choice(pos_indices, size=n_pos, replace=True)
        neg_sample = np.random.choice(neg_indices, size=n_neg, replace=True)
        
        sample_indices = np.concatenate([pos_sample, neg_sample])
        
        y_true_boot = y_true[sample_indices]
        y_scores_boot = y_scores[sample_indices]
        w_boot = sample_weights[sample_indices]
        
        if threshold is None:
            # Find best threshold for this bootstrap sample
            best_f1 = -1
            best_thresh = 0.5
            for t in np.unique(y_scores_boot):
                pred = y_scores_boot >= t
                tp = np.sum(w_boot * (y_true_boot == 1) * pred)
                fp = np.sum(w_boot * (y_true_boot == 0) * pred)
                fn = np.sum(w_boot * (y_true_boot == 1) * ~pred)
                
                f1 = 2 * tp / max(2 * tp + fp + fn, 1e-12)
                if f1 > best_f1:
                    best_f1 = f1
                    best_thresh = t
        else:
            pred = y_scores_boot >= threshold
            tp = np.sum(w_boot * (y_true_boot == 1) * pred)
            fp = np.sum(w_boot * (y_true_boot == 0) * pred)
            fn = np.sum(w_boot * (y_true_boot == 1) * ~pred)
            
            f1 = 2 * tp / max(2 * tp + fp + fn, 1e-12)
        
        f1_scores.append(f1)
    
    f1_scores = np.array(f1_scores)
    p10 = np.percentile(f1_scores, 10)
    return p10


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--data-dir', required=True)
    parser.add_argument('--split', required=True, choices=['val', 'test'])
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    
    # Load training data
    print("Loading training data...")
    train_history_path = os.path.join(args.data_dir, 'train_history.csv.gz')
    train_labels_path = os.path.join(args.data_dir, 'train_labels.csv')
    
    # Load training history with selected columns to save memory
    train_history_cols = ['date', 'serial_number', 'model', 'capacity_bytes'] + \
                         [f"smart_{i}_raw" for i in [1,3,4,5,7,9,10,12,187,188,190,191,192,193,194,196,197,198,199,240,241,242]] + \
                         [f"smart_{i}_normalized" for i in [1,3,5,7,9,187,194,197,198]]
    
    train_history = pd.read_csv(train_history_path, usecols=train_history_cols)
    train_labels = pd.read_csv(train_labels_path)
    
    # Merge to get cutoff dates
    train_history = train_history.merge(
        train_labels[['serial_number', 'cutoff_date']], 
        left_on='serial_number', 
        right_on='serial_number'
    )
    
    # Filter to 14 days before cutoff
    train_history['date'] = pd.to_datetime(train_history['date'])
    train_history['cutoff_date'] = pd.to_datetime(train_history['cutoff_date'])
    train_history = train_history[train_history['date'] >= (train_history['cutoff_date'] - pd.Timedelta(days=13))]
    
    # Extract features for training
    print("Extracting training features...")
    X_train_full = extract_features(train_history)
    y_train_full = train_labels.set_index('serial_number')['label']
    w_train_full = train_labels.set_index('serial_number')['weight']
    
    # Align indices
    common_idx = X_train_full.index.intersection(y_train_full.index)
    X_train_full = X_train_full.loc[common_idx]
    y_train_full = y_train_full.loc[common_idx]
    w_train_full = w_train_full.loc[common_idx]
    
    # Load query data
    print("Loading query data...")
    query_history_path = os.path.join(args.data_dir, f"{args.split}_history.csv.gz")
    query_index_path = os.path.join(args.data_dir, f"{args.split}_index.csv")
    
    query_history = pd.read_csv(query_history_path, usecols=train_history_cols)
    query_index = pd.read_csv(query_index_path)
    
    # Prepare query history
    query_history = query_history.merge(
        query_index[['serial_number', 'cutoff_date']], 
        left_on='serial_number', 
        right_on='serial_number'
    )
    
    query_history['date'] = pd.to_datetime(query_history['date'])
    query_history['cutoff_date'] = pd.to_datetime(query_history['cutoff_date'])
    query_history = query_history[query_history['date'] >= (query_history['cutoff_date'] - pd.Timedelta(days=13))]
    
    # Extract features for query
    print("Extracting query features...")
    X_query = extract_features(query_history)
    
    # Ensure same features in both sets
    all_features = X_train_full.columns.union(X_query.columns)
    X_train_full = X_train_full.reindex(columns=all_features, fill_value=0.0)
    X_query = X_query.reindex(columns=all_features, fill_value=0.0)
    
    # Use stratified k-fold for threshold selection
    print("Training model and selecting threshold...")
    skf = StratifiedKFold(n_splits=3, shuffle=True, random_state=42)
    
    cv_scores = []
    best_model = None
    best_cv_score = -1
    
    for fold, (train_idx, val_idx) in enumerate(skf.split(X_train_full, y_train_full)):
        X_tr, X_val = X_train_full.iloc[train_idx], X_train_full.iloc[val_idx]
        y_tr, y_val = y_train_full.iloc[train_idx], y_train_full.iloc[val_idx]
        w_tr, w_val = w_train_full.iloc[train_idx], w_train_full.iloc[val_idx]
        
        # Train LightGBM model
        train_data = lgb.Dataset(X_tr, label=y_tr, weight=w_tr)
        valid_data = lgb.Dataset(X_val, label=y_val, weight=w_val, reference=train_data)
        
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
            'is_unbalance': True
        }
        
        callbacks = [lgb.early_stopping(stopping_rounds=50), lgb.log_evaluation(period=0)]
        model = lgb.train(params, train_data, valid_sets=[valid_data], callbacks=callbacks)
        
        # Predict on validation set
        val_scores = model.predict(X_val)
        
        # Calculate validation metrics for this fold
        f1_p10 = bootstrap_f1(y_val.values, val_scores, w_val.values, n_bootstrap=50)
        auprc = weighted_auprc(y_val.values, val_scores, w_val.values)
        recall_at_far = recall_at_far_threshold(y_val.values, val_scores, w_val.values)
        
        cv_score = 0.5 * f1_p10 + 0.3 * auprc + 0.2 * recall_at_far
        cv_scores.append(cv_score)
        
        if cv_score > best_cv_score:
            best_cv_score = cv_score
            best_model = model
    
    print(f"Average CV score: {np.mean(cv_scores):.4f}")
    
    # Final training on full dataset
    train_data = lgb.Dataset(X_train_full, label=y_train_full, weight=w_train_full)
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
        'is_unbalance': True
    }
    
    final_model = lgb.train(params, train_data, num_boost_round=best_model.best_iteration if hasattr(best_model, 'best_iteration') else 100)
    
    # Generate predictions for query set
    query_scores = final_model.predict(X_query)
    
    # Select optimal threshold based on training data
    best_threshold = 0.5
    best_f1 = -1
    for t in np.linspace(0.01, 0.99, 50):
        y_pred = (query_scores >= t).astype(int)
        # Simple F1 calculation for threshold selection
        tp = np.sum((y_train_full == 1) & (query_scores >= t))
        fp = np.sum((y_train_full == 0) & (query_scores >= t))
        fn = np.sum((y_train_full == 1) & (query_scores < t))
        f1 = 2 * tp / max(2 * tp + fp + fn, 1e-12)
        if f1 > best_f1:
            best_f1 = f1
            best_threshold = t
    
    # Create predictions dataframe
    results = pd.DataFrame({
        'serial_number': X_query.index,
        'score': query_scores,
        'alarm': (query_scores >= best_threshold).astype(int)
    })
    
    # Write output
    results.to_csv(args.out, index=False)
    print(f"Predictions saved to {args.out}")


if __name__ == "__main__":
    main()