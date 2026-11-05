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
    
    # Critical error counters for trend analysis
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
    
    # Add critical counter trends and first appearance flags
    for feat in available_critical:
        hist_data = history[['serial_number', 'date', feat]].sort_values(['serial_number', 'date']).dropna()
        if len(hist_data) > 0:
            # Group by serial number to calculate deltas
            grouped = hist_data.groupby('serial_number')
            
            # Calculate different types of deltas
            first_vals = grouped.first()[feat]
            last_vals = grouped.last()[feat]
            
            # 14-day delta (last - first)
            result[f'{feat}_delta_14d'] = (last_vals - first_vals).fillna(0.0)
            
            # If there are at least 3+ observations, calculate intermediate deltas
            for name, group in grouped:
                if len(group) >= 4:  # At least 4 observations to get 3rd from last
                    # 3-day delta (last - value 3 days ago, roughly)
                    vals = group[feat].values
                    if len(vals) >= 3:
                        result.loc[name, f'{feat}_delta_3d'] = vals[-1] - vals[-3]
                    if len(vals) >= 7:
                        result.loc[name, f'{feat}_delta_7d'] = vals[-1] - vals[-7]
            
            # Handle first appearance flags for critical counters
            # Create pivot table to find when counter first became non-zero
            hist_non_nan = hist_data.copy()
            hist_non_nan['non_zero'] = hist_non_nan[feat] > 0
            
            # Pivot to get non-zero status across dates
            pivot = hist_non_nan.pivot(index='serial_number', columns='date', values='non_zero')
            pivot = pivot.fillna(False)
            
            # Determine if counter became non-zero during the window
            first_col = pivot.iloc[:, 0] if len(pivot.columns) > 0 else pd.Series(False, index=pivot.index)
            last_col = pivot.iloc[:, -1] if len(pivot.columns) > 0 else pd.Series(False, index=pivot.index)
            
            # Became non-zero inside window: was zero initially but non-zero at end
            became_nonzero = (~first_col) & last_col
            result[f'{feat}_became_nonzero'] = became_nonzero.astype(int)
            
            # Days since counter first became non-zero
            # For each serial, find first True occurrence and calculate distance from end
            days_since_start = {}
            for idx in pivot.index:
                row = pivot.loc[idx]
                true_positions = row[row].index if row.any() else []
                if len(true_positions) > 0:
                    first_true_date = true_positions[0]
                    # Calculate position from the start of the window
                    all_dates = sorted(history['date'].unique())
                    first_true_idx = all_dates.index(first_true_date) if first_true_date in all_dates else 0
                    days_since_start[idx] = len(all_dates) - first_true_idx
                else:
                    days_since_start[idx] = np.nan
            
            # Add the days since first non-zero as a feature
            result[f'{feat}_days_since_first_nonzero'] = pd.Series(days_since_start).reindex(result.index).fillna(-1)
            
            # Also add a flag for counter resets (when value decreases significantly)
            if name in grouped.groups:
                for name, group in grouped:
                    values = group[feat].values
                    if len(values) > 1:
                        diffs = np.diff(values)
                        # Flag if any negative difference (possible reset)
                        has_reset = (diffs < 0).any()
                        result.loc[name, f'{feat}_has_reset'] = int(has_reset)
    
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
    # Return 10th percentile of F1 scores
    return np.percentile(f1_scores, 10)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--data-dir', required=True, help='Data directory')
    parser.add_argument('--split', required=True, choices=['val', 'test'], help='Dataset split')
    parser.add_argument('--out', required=True, help='Output CSV file')
    args = parser.parse_args()
    
    # Load training data
    print("Loading training data...")
    train_hist = pd.read_csv(os.path.join(args.data_dir, 'train_history.csv.gz'))
    train_labels = pd.read_csv(os.path.join(args.data_dir, 'train_labels.csv'))
    
    # Load test data
    print("Loading test data...")
    test_hist = pd.read_csv(os.path.join(args.data_dir, f'{args.split}_history.csv.gz'))
    test_index = pd.read_csv(os.path.join(args.data_dir, f'{args.split}_index.csv'))
    
    # Merge labels with history to identify which history rows belong to training set
    train_sn = set(train_labels['serial_number'])
    train_hist = train_hist[train_hist['serial_number'].isin(train_sn)]
    
    # Extract features for training
    print("Extracting training features...")
    X_train_full = extract_features(train_hist)
    y_train_full = train_labels.set_index('serial_number')['label']
    w_train_full = train_labels.set_index('serial_number')['weight']
    
    # Align data
    common_sns = X_train_full.index.intersection(y_train_full.index).intersection(w_train_full.index)
    X_train_full = X_train_full.loc[common_sns]
    y_train_full = y_train_full.loc[common_sns]
    w_train_full = w_train_full.loc[common_sns]
    
    # Prepare test features
    print("Extracting test features...")
    X_test = extract_features(test_hist)
    
    # Ensure same features in train and test
    common_features = X_train_full.columns.intersection(X_test.columns)
    X_train_full = X_train_full[common_features]
    X_test = X_test[common_features]
    
    # Convert categorical columns to appropriate type for LightGBM
    cat_cols = [col for col in X_train_full.columns if 'vendor_' in col]
    for col in cat_cols:
        X_train_full[col] = X_train_full[col].astype('category')
        X_test[col] = X_test[col].astype('category')
    
    # Use cross-validation to select best threshold
    print("Cross-validation for threshold selection...")
    skf = StratifiedKFold(n_splits=3, shuffle=True, random_state=42)
    cv_scores = []
    
    for fold, (train_idx, val_idx) in enumerate(skf.split(X_train_full, y_train_full)):
        X_tr, X_val = X_train_full.iloc[train_idx], X_train_full.iloc[val_idx]
        y_tr, y_val = y_train_full.iloc[train_idx], y_train_full.iloc[val_idx]
        w_tr, w_val = w_train_full.iloc[train_idx], w_train_full.iloc[val_idx]
        
        # Train model
        train_data = lgb.Dataset(X_tr, label=y_tr, weight=w_tr)
        val_data = lgb.Dataset(X_val, label=y_val, weight=w_val, reference=train_data)
        
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
            'is_unbalance': True
        }
        
        callbacks = [lgb.log_evaluation(period=0)]
        model = lgb.train(
            params,
            train_data,
            valid_sets=[val_data],
            num_boost_round=300,
            callbacks=callbacks
        )
        
        # Predict on validation set
        y_val_pred = model.predict(X_val)
        
        # Calculate F1_p10 for this fold
        f1_p10 = bootstrap_f1(y_val.values, y_val_pred, w_val.values)
        cv_scores.append(f1_p10)
    
    # Now train final model on full training set
    print("Training final model...")
    train_data = lgb.Dataset(X_train_full, label=y_train_full, weight=w_train_full)
    
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
        'is_unbalance': True
    }
    
    callbacks = [lgb.log_evaluation(period=0)]
    final_model = lgb.train(
        params,
        train_data,
        num_boost_round=300,
        callbacks=callbacks
    )
    
    # Predict on test set
    print("Predicting on test set...")
    test_scores = final_model.predict(X_test)
    
    # Create submission dataframe
    results_df = pd.DataFrame({
        'serial_number': test_index['serial_number'],
        'score': test_scores,
        'alarm': 0  # Placeholder, we'll determine this based on optimized threshold
    })
    
    # Determine optimal threshold based on full training data
    train_preds = final_model.predict(X_train_full)
    
    # Find threshold that maximizes weighted F1 on training data
    best_threshold = 0.5
    best_f1 = -1
    
    for t in np.linspace(0.01, 0.99, 50):
        pred = train_preds >= t
        tp = np.sum(w_train_full * (y_train_full == 1) * pred)
        fp = np.sum(w_train_full * (y_train_full == 0) * pred)
        fn = np.sum(w_train_full * (y_train_full == 1) * ~pred)
        
        f1 = 2 * tp / max(2 * tp + fp + fn, 1e-12)
        if f1 > best_f1:
            best_f1 = f1
            best_threshold = t
    
    # Apply optimal threshold to test predictions
    results_df['alarm'] = (results_df['score'] >= best_threshold).astype(int)
    
    # Write output
    results_df.to_csv(args.out, index=False)
    print(f"Results written to {args.out}")


if __name__ == "__main__":
    main()