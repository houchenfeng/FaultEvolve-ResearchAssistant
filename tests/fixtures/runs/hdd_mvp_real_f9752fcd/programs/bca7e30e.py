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
    
    # Add model as a feature
    result['model'] = last_day['model']
    
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
    return f1_scores


def compute_target_encoding(train_df, feature_col, target_col, weight_col, alpha=50):
    """Compute out-of-fold target encoding with smoothing"""
    # Calculate global mean
    total_weight = train_df[weight_col].sum()
    global_mean = (train_df[target_col] * train_df[weight_col]).sum() / total_weight
    
    # Group statistics for each value in the feature column
    grouped = train_df.groupby(feature_col).agg({
        target_col: lambda x: (x * train_df.loc[x.index, weight_col]).sum(),
        weight_col: 'sum'
    }).rename(columns={target_col: 'pos_weight_sum', weight_col: 'weight_sum'})
    
    # Apply smoothing formula: (pos_in_category + alpha*global_rate) / (total_in_category + alpha)
    grouped['smoothed_target'] = (
        (grouped['pos_weight_sum'] + alpha * global_mean) / 
        (grouped['weight_sum'] + alpha)
    )
    
    return grouped['smoothed_target']


def fit_model_with_cv_threshold_selection(X_train, y_train, w_train, X_val, 
                                          serial_numbers_train, serial_numbers_val):
    """Fit model and select threshold using CV on training data"""
    # Convert model column to category for LightGBM
    model_col_idx = None
    feature_names = X_train.columns.tolist()
    categorical_features = []
    
    for i, col in enumerate(feature_names):
        if col == 'model':
            model_col_idx = i
            categorical_features.append(col)
            X_train[col] = X_train[col].astype('category')
            if X_val is not None and col in X_val.columns:
                X_val[col] = X_val[col].astype('category')
    
    # Prepare data
    train_data = lgb.Dataset(X_train, label=y_train, weight=w_train, 
                             categorical_feature=categorical_features)
    
    # Train model
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
        'learning_rate': 0.05
    }
    
    # Use fewer estimators to save time
    model = lgb.train(params, train_data, num_boost_round=200)
    
    # Get OOF predictions using stratified K-fold
    skf = StratifiedKFold(n_splits=3, shuffle=True, random_state=42)
    oof_preds = np.zeros(len(X_train))
    
    for fold, (train_idx, val_idx) in enumerate(skf.split(X_train, y_train)):
        X_tr_fold = X_train.iloc[train_idx]
        y_tr_fold = y_train[train_idx]
        w_tr_fold = w_train[train_idx]
        
        X_val_fold = X_train.iloc[val_idx]
        y_val_fold = y_train[val_idx]
        w_val_fold = w_train[val_idx]
        
        # Ensure model column is categorical
        if model_col_idx is not None:
            X_tr_fold = X_tr_fold.copy()
            X_val_fold = X_val_fold.copy()
            X_tr_fold.iloc[:, model_col_idx] = X_tr_fold.iloc[:, model_col_idx].astype('category')
            X_val_fold.iloc[:, model_col_idx] = X_val_fold.iloc[:, model_col_idx].astype('category')
        
        tr_data = lgb.Dataset(X_tr_fold, label=y_tr_fold, weight=w_tr_fold,
                              categorical_feature=categorical_features)
        val_data = lgb.Dataset(X_val_fold, label=y_val_fold, weight=w_val_fold,
                               categorical_feature=categorical_features, 
                               reference=tr_data)
        
        fold_model = lgb.train(params, tr_data, valid_sets=[val_data], 
                               num_boost_round=200, 
                               callbacks=[lgb.early_stopping(stopping_rounds=30),
                                         lgb.log_evaluation(period=0)])
        
        oof_preds[val_idx] = fold_model.predict(X_val_fold)
    
    # Calculate optimal threshold using bootstrap on OOF predictions
    thresholds = np.quantile(oof_preds, np.linspace(0.90, 0.999, 50))
    f1_percentiles = []
    
    for thresh in thresholds:
        boot_f1s = bootstrap_f1(y_train, oof_preds, w_train, n_bootstrap=100, threshold=thresh)
        p10_f1 = np.percentile(boot_f1s, 10)
        f1_percentiles.append(p10_f1)
    
    # Select threshold that maximizes 10th percentile of F1
    best_idx = np.argmax(f1_percentiles)
    best_threshold = thresholds[best_idx]
    
    # If multiple thresholds give similar results, pick the middle one to avoid extreme thresholds
    max_p10 = f1_percentiles[best_idx]
    similar_thresh_idxs = [i for i, p10 in enumerate(f1_percentiles) 
                           if p10 >= 0.97 * max_p10]
    if len(similar_thresh_idxs) > 1:
        mid_idx = similar_thresh_idxs[len(similar_thresh_idxs) // 2]
        best_threshold = thresholds[mid_idx]
    
    # Make final predictions
    val_preds = model.predict(X_val) if X_val is not None else None
    
    return model, val_preds, best_threshold


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
    
    # Extract features for training set
    print("Extracting training features...")
    train_features = extract_features(train_history)
    
    # Merge with labels
    train_data = train_features.merge(
        train_labels[['serial_number', 'label', 'weight']], 
        left_index=True, right_on='serial_number'
    )
    
    # Compute target encoding for model feature out-of-fold
    print("Computing target encodings...")
    te_map = compute_target_encoding(train_data, 'model', 'label', 'weight', alpha=50)
    
    # Apply target encoding to training data
    train_data['model_te'] = train_data['model'].map(te_map).fillna(train_data['label'].mean())
    
    # Load query data
    print(f"Loading {args.split} data...")
    query_history = pd.read_csv(os.path.join(args.data_dir, f"{args.split}_history.csv.gz"))
    query_index = pd.read_csv(os.path.join(args.data_dir, f"{args.split}_index.csv"))
    
    # Extract features for query set
    print("Extracting query features...")
    query_features = extract_features(query_history)
    
    # Apply the same target encoding to query data
    query_features['model_te'] = query_features['model'].map(te_map).fillna(train_data['label'].mean())
    
    # Prepare training data
    feature_cols = [c for c in train_data.columns if c not in ['serial_number', 'label', 'weight', 'model']]
    X_train = train_data[feature_cols]
    y_train = train_data['label'].values
    w_train = train_data['weight'].values
    sn_train = train_data['serial_number'].values
    
    # Prepare validation data (if needed for threshold selection)
    feature_cols_query = [c for c in query_features.columns if c not in ['serial_number', 'model']]
    feature_cols_train_filtered = [c for c in feature_cols if c in feature_cols_query]
    X_query = query_features[feature_cols_train_filtered]
    
    # Fit model and select threshold using CV
    print("Training model and selecting threshold...")
    model, preds, threshold = fit_model_with_cv_threshold_selection(
        X_train[feature_cols_train_filtered], y_train, w_train, X_query, 
        sn_train, query_features['serial_number'].values
    )
    
    # Generate predictions for query set
    if preds is None:
        preds = model.predict(X_query)
    
    # Create alarms based on selected threshold
    alarms = (preds >= threshold).astype(int)
    
    # Write output
    output_df = pd.DataFrame({
        'serial_number': query_features.index,
        'score': preds,
        'alarm': alarms
    })
    output_df.to_csv(args.out, index=False)
    
    print(f"Predictions saved to {args.out}")


if __name__ == "__main__":
    main()