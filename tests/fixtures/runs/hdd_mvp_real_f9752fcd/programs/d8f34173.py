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
            best_thresh = threshold
            f1 = 2 * tp / max(2 * tp + fp + fn, 1e-12)
        
        f1_scores.append(f1)
    
    return np.percentile(f1_scores, [10, 50])  # Return 10th and 50th percentiles


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--split", required=True, choices=["val", "test"])
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    # Load data
    train_hist = pd.read_csv(os.path.join(args.data_dir, "train_history.csv.gz"), parse_dates=["date"])
    train_lab = pd.read_csv(os.path.join(args.data_dir, "train_labels.csv")).set_index("serial_number")
    query_hist = pd.read_csv(os.path.join(args.data_dir, f"{args.split}_history.csv.gz"), parse_dates=["date"])
    query_idx = pd.read_csv(os.path.join(args.data_dir, f"{args.split}_index.csv"))

    # Extract features
    print("Extracting training features...")
    x_train_all = extract_features(train_hist)
    x_train = x_train_all.reindex(train_lab.index).fillna(0.0)
    
    print("Extracting query features...")
    x_query = extract_features(query_hist).reindex(query_idx["serial_number"]).fillna(0.0)
    
    y_train = train_lab["label"].to_numpy()
    w_train = train_lab["weight"].to_numpy()

    # Cross-validation setup
    skf = StratifiedKFold(n_splits=3, shuffle=True, random_state=42)
    
    oof_preds = np.zeros(len(y_train))
    models = []
    
    print("Training models with cross-validation...")
    for fold, (tr_idx, val_idx) in enumerate(skf.split(x_train, y_train)):
        X_tr, X_val = x_train.iloc[tr_idx], x_train.iloc[val_idx]
        y_tr, y_val = y_train[tr_idx], y_train[val_idx]
        w_tr, w_val = w_train[tr_idx], w_train[val_idx]
        
        # Train LightGBM model
        model = lgb.LGBMClassifier(
            n_estimators=300,
            learning_rate=0.03,
            num_leaves=31,
            min_child_samples=30,
            subsample=0.8,
            subsample_freq=1,
            colsample_bytree=0.7,
            reg_lambda=1.0,
            n_jobs=-1,
            verbose=-1
        )
        
        model.fit(X_tr, y_tr, sample_weight=w_tr)
        models.append(model)
        
        # Get OOF predictions
        oof_preds[val_idx] = model.predict_proba(X_val)[:, 1]
    
    # Find best threshold using OOF predictions
    print("Finding optimal threshold...")
    best_thresh = 0.5
    best_metric = -1.0
    
    # Try different thresholds
    for thresh in np.quantile(oof_preds, np.linspace(0.8, 0.999, 50)):
        # Calculate F1 for this threshold
        y_pred_binary = (oof_preds >= thresh).astype(int)
        tp = np.sum(w_train * (y_train == 1) * y_pred_binary)
        fp = np.sum(w_train * (y_train == 0) * y_pred_binary)
        fn = np.sum(w_train * (y_train == 1) * (1 - y_pred_binary))
        f1 = 2 * tp / max(2 * tp + fp + fn, 1e-12)
        
        if f1 > best_metric:
            best_metric = f1
            best_thresh = thresh

    # Final predictions using ensemble of all models
    print("Making final predictions...")
    final_scores = np.zeros(len(x_query))
    for model in models:
        final_scores += model.predict_proba(x_query)[:, 1]
    final_scores /= len(models)  # Average ensemble predictions

    # Create submission
    pred = pd.DataFrame({
        "serial_number": query_idx["serial_number"],
        "score": final_scores,
        "alarm": (final_scores >= best_thresh).astype(int),
    })
    
    pred.to_csv(args.out, index=False)


if __name__ == "__main__":
    main()