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
import time


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
    
    # Add model as categorical feature
    result["model"] = last_day["model"]
    
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
        # Bootstrap sampling
        sample_indices = np.random.choice(n_samples, size=n_samples, replace=True)
        
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
            threshold = best_thresh
            
        pred = y_scores_boot >= threshold
        tp = np.sum(w_boot * (y_true_boot == 1) * pred)
        fp = np.sum(w_boot * (y_true_boot == 0) * pred)
        fn = np.sum(w_boot * (y_true_boot == 1) * ~pred)
        
        f1 = 2 * tp / max(2 * tp + fp + fn, 1e-12)
        f1_scores.append(f1)
    
    return np.percentile(f1_scores, 10)  # Return 10th percentile


def compute_target_encoding(train_history, train_labels, query_history):
    """Compute out-of-fold target encoding for model feature"""
    # Combine train and query to get all unique models
    all_models = pd.concat([
        train_history[['model']].drop_duplicates(),
        query_history[['model']].drop_duplicates()
    ]).drop_duplicates()
    
    # Calculate global failure rate
    global_rate = train_labels['label'].mean()
    
    # Count failures and totals per model in training data
    model_stats = train_labels.groupby('model').agg({
        'label': ['count', 'sum']
    }).round(0).astype(int)
    model_stats.columns = ['total', 'failures']
    model_stats['failure_rate'] = model_stats['failures'] / model_stats['total']
    
    # Apply smoothing: (failures + alpha*global_rate) / (total + alpha)
    alpha = 50
    model_stats['smoothed_rate'] = (model_stats['failures'] + alpha * global_rate) / (model_stats['total'] + alpha)
    
    # Create mapping
    model_to_rate = model_stats['smoothed_rate'].to_dict()
    
    # For models not in training data, use global rate
    def map_rate(model):
        return model_to_rate.get(model, global_rate)
    
    return map_rate


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
    
    # Load query data
    print("Loading query data...")
    query_history = pd.read_csv(os.path.join(args.data_dir, f'{args.split}_history.csv.gz'))
    query_index = pd.read_csv(os.path.join(args.data_dir, f'{args.split}_index.csv'))
    
    # Extract features
    print("Extracting features...")
    X_train_raw = extract_features(train_history)
    X_query_raw = extract_features(query_history)
    
    # Merge with labels for training set
    train_df = X_train_raw.merge(train_labels[['serial_number', 'label', 'weight']], on='serial_number')
    
    # Compute target encoding
    print("Computing target encodings...")
    model_rate_map = compute_target_encoding(train_history, train_labels, query_history)
    
    # Apply target encoding to both sets
    X_train_raw['model_failure_rate'] = X_train_raw.reset_index()['model'].map(model_rate_map).values
    X_query_raw['model_failure_rate'] = X_query_raw.reset_index()['model'].map(model_rate_map).values
    
    # Prepare training data
    X_train = X_train_raw.drop(columns=['model'])  # Remove model string for training
    X_train['model_cat'] = pd.Categorical(X_train_raw.reset_index()['model']).values
    y_train = train_df['label'].values
    w_train = train_df['weight'].values
    
    # Prepare query data
    X_query = X_query_raw.drop(columns=['model'])  # Remove model string for query
    X_query['model_cat'] = pd.Categorical(X_query_raw.reset_index()['model'], 
                                         categories=X_train['model_cat'].cat.categories).values
    
    # Set model_cat as categorical for LightGBM
    categorical_features = ['model_cat']
    
    # Perform cross-validation to find optimal threshold
    print("Performing cross-validation...")
    skf = StratifiedKFold(n_splits=3, shuffle=True, random_state=42)
    oof_scores = np.zeros(len(X_train))
    
    for fold, (train_idx, val_idx) in enumerate(skf.split(X_train, y_train)):
        X_tr = X_train.iloc[train_idx]
        y_tr = y_train[train_idx]
        w_tr = w_train[train_idx]
        
        X_val = X_train.iloc[val_idx]
        y_val = y_train[val_idx]
        w_val = w_train[val_idx]
        
        # Train model
        train_dataset = lgb.Dataset(X_tr, label=y_tr, weight=w_tr, categorical_feature=categorical_features)
        val_dataset = lgb.Dataset(X_val, label=y_val, weight=w_val, categorical_feature=categorical_features)
        
        params = {
            'objective': 'binary',
            'metric': 'binary_logloss',
            'verbose': -1,
            'seed': 42,
            'num_leaves': 63,
            'max_depth': 7,
            'min_child_samples': 20,
            'subsample': 0.8,
            'colsample_bytree': 0.8,
            'reg_alpha': 0.1,
            'reg_lambda': 0.1,
            'learning_rate': 0.1
        }
        
        model = lgb.train(
            params,
            train_dataset,
            valid_sets=[val_dataset],
            num_boost_round=300,
            callbacks=[lgb.early_stopping(stopping_rounds=50), lgb.log_evaluation(period=0)]
        )
        
        # Predict on validation set
        oof_scores[val_idx] = model.predict(X_val)
    
    # Find optimal threshold using bootstrap F1
    print("Finding optimal threshold...")
    # Create a grid of thresholds based on quantiles of OOF scores
    threshold_candidates = np.quantile(oof_scores, np.linspace(0.95, 0.999, 80))
    
    best_p10_f1 = -1
    best_threshold = 0.5
    
    for thresh in threshold_candidates:
        p10_f1 = bootstrap_f1(y_train, oof_scores, w_train, n_bootstrap=100, threshold=thresh)
        if p10_f1 > best_p10_f1:
            best_p10_f1 = p10_f1
            best_threshold = thresh
    
    print(f"Best threshold: {best_threshold}, Bootstrap F1 p10: {best_p10_f1}")
    
    # Train final model on full training set
    print("Training final model...")
    train_dataset = lgb.Dataset(X_train, label=y_train, weight=w_train, categorical_feature=categorical_features)
    
    params = {
        'objective': 'binary',
        'metric': 'binary_logloss',
        'verbose': -1,
        'seed': 42,
        'num_leaves': 63,
        'max_depth': 7,
        'min_child_samples': 20,
        'subsample': 0.8,
        'colsample_bytree': 0.8,
        'reg_alpha': 0.1,
        'reg_lambda': 0.1,
        'learning_rate': 0.1
    }
    
    final_model = lgb.train(
        params,
        train_dataset,
        num_boost_round=300
    )
    
    # Predict on query set
    print("Predicting on query set...")
    query_scores = final_model.predict(X_query)
    
    # Generate alarms based on optimal threshold
    query_alarms = (query_scores >= best_threshold).astype(int)
    
    # Create submission dataframe
    results_df = pd.DataFrame({
        'serial_number': X_query.index,
        'score': query_scores,
        'alarm': query_alarms
    })
    
    # Write results
    print("Writing results...")
    results_df.to_csv(args.out, index=False)
    
    end_time = time.time()
    print(f"Total runtime: {end_time - start_time:.2f}s")


if __name__ == '__main__':
    main()