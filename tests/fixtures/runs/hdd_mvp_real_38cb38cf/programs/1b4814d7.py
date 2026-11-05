"""Enhanced solution: LightGBM with temporal features and cross-validation threshold selection.

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
from sklearn.model_selection import GroupKFold
from sklearn.preprocessing import StandardScaler
import lightgbm as lgb
from sklearn.metrics import average_precision_score
from scipy import stats

# Critical SMART attributes for failure prediction
CRITICAL_FEATURES = [
    "smart_5_raw", "smart_187_raw", "smart_188_raw", "smart_197_raw", "smart_198_raw",
    "smart_199_raw", "smart_9_raw", "smart_194_raw", "smart_1_normalized", "smart_7_normalized",
]

DELTA_FEATURES = [
    "smart_5_raw", "smart_187_raw", "smart_188_raw", "smart_197_raw", "smart_198_raw", "smart_199_raw"
]

VENDOR_LIST = ["ST", "TOSHIBA", "HGST", "WDC"]


def engineer_features(history: pd.DataFrame) -> pd.DataFrame:
    """Engineer temporal features from history."""
    # Sort by date for each disk
    history = history.sort_values(["serial_number", "date"])
    
    # Create pivot table for date-based operations
    all_dates = history[['serial_number', 'date'] + DELTA_FEATURES].copy()
    all_dates['date_idx'] = all_dates.groupby('serial_number')['date'].rank(method='dense').astype(int)
    max_date_idx = all_dates.groupby('serial_number')['date_idx'].transform('max')
    all_dates = all_dates[all_dates['date_idx'] <= 14]  # Only use up to 14 days
    
    # Pivot to get values per day index
    pivoted_data = {}
    for feat in DELTA_FEATURES:
        subset = all_dates[['serial_number', 'date_idx', feat]].dropna()
        pivot_table = subset.pivot(index='serial_number', columns='date_idx', values=feat)
        pivoted_data[feat] = pivot_table
    
    # Get last snapshot features
    last_snap = history.groupby('serial_number').last()
    x = last_snap.reindex(columns=CRITICAL_FEATURES).astype(float)
    
    # Log transform positive values and handle NaN
    x = np.log1p(x.clip(lower=0)).fillna(0.0)
    
    # Vendor features
    for vendor in VENDOR_LIST:
        x[f"vendor_{vendor}"] = last_snap["model"].str.startswith(vendor).astype(float)
    
    # Add delta features (change over time window)
    for feat in DELTA_FEATURES:
        if feat in pivoted_data:
            pivot_table = pivoted_data[feat]
            
            # Last value
            last_vals = pivot_table.iloc[:, -1] if pivot_table.shape[1] > 0 else pd.Series(dtype=float)
            
            # First value
            first_vals = pivot_table.iloc[:, 0] if pivot_table.shape[1] > 0 else pd.Series(dtype=float)
            
            # Calculate delta (last - first)
            delta_14 = last_vals - first_vals
            x[f"{feat}_delta_14"] = delta_14.fillna(0.0).clip(lower=0)
            
            # If we have enough days, calculate 7-day and 3-day deltas
            if pivot_table.shape[1] >= 8:
                day_7_vals = pivot_table.iloc[:, -7] if pivot_table.shape[1] >= 7 else first_vals
                x[f"{feat}_delta_7"] = (last_vals - day_7_vals).fillna(0.0).clip(lower=0)
                
            if pivot_table.shape[1] >= 4:
                day_11_vals = pivot_table.iloc[:, -3] if pivot_table.shape[1] >= 3 else first_vals
                x[f"{feat}_delta_3"] = (last_vals - day_11_vals).fillna(0.0).clip(lower=0)
    
    # Add first appearance features for critical counters
    for feat in ["smart_5_raw", "smart_197_raw", "smart_198_raw", "smart_187_raw"]:
        if feat in pivoted_data:
            pivot_table = pivoted_data[feat]
            # Convert to boolean: whether value is non-zero
            nz = pivot_table > 0
            
            # Became non-zero in window: was zero initially but non-zero at end
            if pivot_table.shape[1] > 1:
                became_nonzero = (~nz.iloc[:, 0]).fillna(True) & nz.iloc[:, -1].fillna(False)
                x[f"{feat}_became_nonzero"] = became_nonzero.astype(float)
                
                # Days since first non-zero
                days_since_first = []
                for idx in range(len(nz)):
                    row = nz.iloc[idx, :]
                    first_nz_pos = row.idxmax() if row.any() else None
                    if first_nz_pos is not None:
                        days_since_first.append(pivot_table.shape[1] - first_nz_pos)
                    else:
                        days_since_first.append(np.nan)
                x[f"{feat}_days_since_first"] = pd.Series(days_since_first, index=nz.index).fillna(-1).astype(float)
            else:
                x[f"{feat}_became_nonzero"] = 0.0
                x[f"{feat}_days_since_first"] = -1.0
    
    # Additional vendor-specific features
    for vendor in VENDOR_LIST:
        vendor_mask = last_snap["model"].str.startswith(vendor)
        for feat in ["smart_187_raw", "smart_188_raw", "smart_190_raw", "smart_197_raw", "smart_198_raw"]:
            if feat in last_snap.columns:
                feat_vals = last_snap[feat].astype(float)
                x[f"{vendor}_{feat}_log"] = np.log1p(feat_vals.where(vendor_mask, 0.0)).fillna(0.0)
                
    # Add trend features using linear regression slope
    for feat in DELTA_FEATURES:
        if feat in pivoted_data:
            pivot_table = pivoted_data[feat]
            slopes = []
            for idx in pivot_table.index:
                row = pivot_table.loc[idx, :].dropna()
                if len(row) > 1:
                    x_coords = np.arange(len(row))
                    slope, _, _, _, _ = stats.linregress(x_coords, row.values)
                    slopes.append(slope)
                else:
                    slopes.append(0.0)
            x[f"{feat}_trend"] = pd.Series(slopes, index=pivot_table.index).fillna(0.0)
    
    return x


def weighted_auprc(y_true, y_scores, weights):
    """Compute weighted AUPRC."""
    # Sort by scores in descending order
    desc_score_indices = np.argsort(y_scores)[::-1]
    y_true_sorted = y_true[desc_score_indices]
    weights_sorted = weights[desc_score_indices]
    
    # Compute precision and recall at each threshold
    weight_sum = np.sum(weights_sorted)
    pos_weight_sum = np.sum(weights_sorted[y_true_sorted == 1])
    
    if pos_weight_sum == 0:
        return 0.0
        
    precisions = []
    recalls = []
    
    cum_tp = 0.0
    cum_fp = 0.0
    cum_weights = 0.0
    
    for i in range(len(y_true_sorted)):
        cum_weights += weights_sorted[i]
        if y_true_sorted[i] == 1:
            cum_tp += weights_sorted[i]
        else:
            cum_fp += weights_sorted[i]
            
        precision = cum_tp / (cum_tp + cum_fp) if (cum_tp + cum_fp) > 0 else 1.0
        recall = cum_tp / pos_weight_sum if pos_weight_sum > 0 else 0.0
        
        precisions.append(precision)
        recalls.append(recall)
    
    # Convert to numpy arrays
    precisions = np.array(precisions)
    recalls = np.array(recalls)
    
    # Compute AUPRC using trapezoidal rule
    # Insert (recall=0, precision=positive_ratio) at beginning
    pos_ratio = pos_weight_sum / weight_sum
    precisions = np.concatenate([[pos_ratio], precisions])
    recalls = np.concatenate([[0.0], recalls])
    
    return np.trapz(precisions, recalls)


def recall_at_far(y_true, y_scores, weights, target_far=0.002):
    """Compute recall at target false alarm rate."""
    # Sort by scores in descending order
    desc_score_indices = np.argsort(y_scores)[::-1]
    y_true_sorted = y_true[desc_score_indices]
    weights_sorted = weights[desc_score_indices]
    
    weight_sum = np.sum(weights_sorted)
    neg_weight_sum = np.sum(weights_sorted[y_true_sorted == 0])
    
    if neg_weight_sum == 0:
        return 0.0
    
    cum_neg_weights = 0.0
    threshold_idx = len(y_scores)
    
    for i in range(len(y_true_sorted)):
        if y_true_sorted[i] == 0:
            cum_neg_weights += weights_sorted[i]
        
        current_far = cum_neg_weights / neg_weight_sum
        if current_far >= target_far:
            threshold_idx = i
            break
    
    # Calculate recall at this threshold
    relevant_pos_weights = np.sum(weights_sorted[:threshold_idx][y_true_sorted[:threshold_idx] == 1])
    total_pos_weights = np.sum(weights_sorted[y_true_sorted == 1])
    
    return relevant_pos_weights / total_pos_weights if total_pos_weights > 0 else 0.0


def bootstrap_f1(y_true, y_pred, weights, n_bootstrap=200):
    """Compute F1 percentiles via stratified bootstrap."""
    n_total = len(y_true)
    pos_indices = np.where(y_true == 1)[0]
    neg_indices = np.where(y_true == 0)[0]
    
    f1_scores = []
    
    for _ in range(n_bootstrap):
        # Sample positive and negative cases separately
        pos_sample = np.random.choice(pos_indices, size=len(pos_indices), replace=True)
        neg_sample = np.random.choice(neg_indices, size=len(neg_indices), replace=True)
        
        sample_indices = np.concatenate([pos_sample, neg_sample])
        
        y_true_boot = y_true[sample_indices]
        y_pred_boot = y_pred[sample_indices]
        w_boot = weights[sample_indices]
        
        tp = np.sum(w_boot * (y_true_boot == 1) * (y_pred_boot == 1))
        fp = np.sum(w_boot * (y_true_boot == 0) * (y_pred_boot == 1))
        fn = np.sum(w_boot * (y_true_boot == 1) * (y_pred_boot == 0))
        
        f1 = 2 * tp / max(2 * tp + fp + fn, 1e-12)
        f1_scores.append(f1)
    
    f1_scores = np.array(f1_scores)
    return np.percentile(f1_scores, 10)  # Return 10th percentile


def best_f1_threshold_cv(y: np.ndarray, p: np.ndarray, w: np.ndarray, groups: np.ndarray) -> float:
    """Find best F1 threshold using cross-validation."""
    best_t, best_f1 = 0.5, -1.0
    
    # Use GroupKFold to avoid data leakage
    gkf = GroupKFold(n_splits=5)
    
    # Since we're using OOF predictions directly, we can optimize threshold on them
    for t in np.quantile(p, np.linspace(0.90, 0.999, 60)):
        a = p >= t
        tp = np.sum(w * (y == 1) * a)
        fp = np.sum(w * (y == 0) * a)
        fn = np.sum(w * (y == 1) * ~a)
        f1 = 2 * tp / max(2 * tp + fp + fn, 1e-12)
        if f1 > best_f1:
            best_t, best_f1 = t, f1
    return float(best_t)


def get_oof_predictions(X, y, w, groups, model_params):
    """Get out-of-fold predictions using GroupKFold."""
    oof_preds = np.zeros(len(X))
    gkf = GroupKFold(n_splits=5)
    
    for fold, (train_idx, val_idx) in enumerate(gkf.split(X, y, groups)):
        X_train_fold = X.iloc[train_idx]
        y_train_fold = y[train_idx]
        w_train_fold = w[train_idx]
        
        X_val_fold = X.iloc[val_idx]
        
        model = lgb.LGBMClassifier(
            n_estimators=model_params['n_estimators'],
            learning_rate=model_params['learning_rate'],
            num_leaves=model_params['num_leaves'],
            min_child_samples=model_params['min_child_samples'],
            subsample=model_params['subsample'],
            subsample_freq=1,
            colsample_bytree=model_params['colsample_bytree'],
            reg_lambda=model_params['reg_lambda'],
            n_jobs=1,  # Using 1 to avoid potential multiprocessing issues
            random_state=42+fold,
            verbosity=-1
        )
        
        model.fit(
            X_train_fold, 
            y_train_fold, 
            sample_weight=w_train_fold
        )
        
        oof_preds[val_idx] = model.predict_proba(X_val_fold)[:, 1]
    
    return oof_preds


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--split", required=True, choices=["val", "test"])
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    start_time = time.time()

    train_hist = pd.read_csv(os.path.join(args.data_dir, "train_history.csv.gz"), parse_dates=["date"])
    train_lab = pd.read_csv(os.path.join(args.data_dir, "train_labels.csv")).set_index("serial_number")
    query_hist = pd.read_csv(os.path.join(args.data_dir, f"{args.split}_history.csv.gz"), parse_dates=["date"])
    query_idx = pd.read_csv(os.path.join(args.data_dir, f"{args.split}_index.csv"))

    # Engineer features for training
    x_train = engineer_features(train_hist).reindex(train_lab.index).fillna(0.0)
    y_train = train_lab["label"].to_numpy()
    w_train = train_lab["weight"].to_numpy()
    groups_train = train_lab.index.values  # For GroupKFold

    # Define model parameters
    model_params = {
        'n_estimators': 200,
        'learning_rate': 0.05,
        'num_leaves': 63,
        'min_child_samples': 20,
        'subsample': 0.8,
        'colsample_bytree': 0.8,
        'reg_lambda': 1.0
    }

    # Get out-of-fold predictions for threshold selection
    oof_preds = get_oof_predictions(x_train, y_train, w_train, groups_train, model_params)

    # Find optimal threshold using OOF predictions
    threshold = best_f1_threshold_cv(y_train, oof_preds, w_train, groups_train)

    # Retrain model on full training data
    final_model = lgb.LGBMClassifier(
        n_estimators=model_params['n_estimators'],
        learning_rate=model_params['learning_rate'],
        num_leaves=model_params['num_leaves'],
        min_child_samples=model_params['min_child_samples'],
        subsample=model_params['subsample'],
        subsample_freq=1,
        colsample_bytree=model_params['colsample_bytree'],
        reg_lambda=model_params['reg_lambda'],
        n_jobs=1,
        random_state=42,
        verbosity=-1
    )

    final_model.fit(x_train, y_train, sample_weight=w_train)

    # Engineer features for query set
    x_query = engineer_features(query_hist).reindex(query_idx["serial_number"]).fillna(0.0)

    # Make predictions
    query_scores = final_model.predict_proba(x_query)[:, 1]
    query_alarms = (query_scores >= threshold).astype(int)

    # Write results
    result_df = pd.DataFrame({
        "serial_number": query_idx["serial_number"],
        "score": query_scores,
        "alarm": query_alarms
    })
    result_df.to_csv(args.out, index=False)

    end_time = time.time()
    print(f"Runtime: {end_time - start_time:.2f}s")


if __name__ == "__main__":
    main()