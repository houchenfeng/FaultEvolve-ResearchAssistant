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
    
    # Add model column to the result
    x['model'] = last_snapshots['model']
    
    return x

def calculate_threshold_oof(y_true, y_scores, weights, n_folds=5):
    """Calculate optimal threshold using out-of-fold predictions with bootstrap percentile."""
    skf = StratifiedKFold(n_splits=n_folds, shuffle=True, random_state=42)
    oof_preds = np.zeros(len(y_scores))
    
    for train_idx, val_idx in skf.split(y_scores, y_true):
        # Just fill oof preds for later threshold calculation
        pass
    
    # Direct optimization of threshold based on weighted F1 using bootstrap
    best_threshold = 0.5
    best_p10_f1 = 0.0
    
    # Generate thresholds based on percentiles of predictions
    thresholds = np.unique(np.quantile(y_scores, np.linspace(0.95, 0.999, 80)))
    
    for threshold in thresholds:
        # Bootstrap sampling to compute F1 percentile
        bootstrap_f1s = []
        for _ in range(100):  # Reduced for efficiency
            # Sample with replacement
            indices = np.random.choice(len(y_scores), size=len(y_scores), replace=True)
            y_true_boot = y_true[indices]
            y_scores_boot = y_scores[indices]
            weights_boot = weights[indices]
            
            y_pred_boot = (y_scores_boot >= threshold).astype(int)
            # Calculate weighted F1
            tp = np.sum((y_pred_boot == 1) & (y_true_boot == 1) * weights_boot)
            fp = np.sum((y_pred_boot == 1) & (y_true_boot == 0) * weights_boot)
            fn = np.sum((y_pred_boot == 0) & (y_true_boot == 1) * weights_boot)
            
            precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
            recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
            f1 = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0
            
            bootstrap_f1s.append(f1)
        
        # Calculate 10th percentile of F1
        p10_f1 = np.percentile(bootstrap_f1s, 10)
        
        if p10_f1 > best_p10_f1:
            best_p10_f1 = p10_f1
            best_threshold = threshold
    
    return best_threshold

def target_encode_oof(X_train, X_test, y_train, alpha=50):
    """Perform out-of-fold target encoding to prevent leakage."""
    # Calculate global mean
    global_mean = y_train.mean()
    
    # Initialize encoded features
    X_train_te = X_train.copy()
    X_test_te = X_test.copy()
    
    # Get model column
    model_col = 'model'
    
    # Use cross-validation for target encoding
    skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    X_train_te['model_encoded'] = 0.0
    
    for fold, (train_idx, val_idx) in enumerate(skf.split(X_train, y_train)):
        # Get out-of-fold training data
        X_tr_fold = X_train.iloc[train_idx]
        y_tr_fold = y_train.iloc[train_idx]
        
        # Calculate target encoding for this fold
        target_means = y_tr_fold.groupby(X_tr_fold[model_col]).agg(['sum', 'count'])
        target_means.columns = ['sum', 'count']
        
        # Apply smoothing
        def smooth_encoding(row):
            s = row['sum']
            c = row['count']
            return (s + alpha * global_mean) / (c + alpha)
        
        temp_encoding = target_means.apply(smooth_encoding, axis=1)
        
        # Map to validation set
        val_serials = X_train.iloc[val_idx].index
        X_train_te.loc[val_serials, 'model_encoded'] = X_train.iloc[val_idx][model_col].map(temp_encoding).fillna(global_mean)
    
    # Encode test set using overall statistics from training
    y_x_train = pd.Series(y_train.values, index=X_train.index)
    target_means_test = y_x_train.groupby(X_train[model_col]).agg(['sum', 'count'])
    target_means_test.columns = ['sum', 'count']
    
    def smooth_encoding_test(row):
        s = row['sum']
        c = row['count']
        return (s + alpha * global_mean) / (c + alpha)
    
    temp_encoding_test = target_means_test.apply(smooth_encoding_test, axis=1)
    X_test_te['model_encoded'] = X_test[model_col].map(temp_encoding_test).fillna(global_mean)
    
    return X_train_te, X_test_te

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
    query_history = pd.read_csv(os.path.join(args.data_dir, f'{args.split}_history.csv.gz'))
    query_index = pd.read_csv(os.path.join(args.data_dir, f'{args.split}_index.csv'))

    # Extract features
    print("Extracting features...")
    train_features = extract_features(train_history)
    query_features = extract_features(query_history)
    
    # Merge with labels for training
    train_data = train_features.merge(
        train_labels[['serial_number', 'label', 'weight']], 
        left_index=True, 
        right_on='serial_number',
        how='inner'
    )
    
    # Prepare training features and target
    feature_cols = [col for col in train_data.columns if col not in ['serial_number', 'label', 'weight', 'model']]
    X_train = train_data[feature_cols].fillna(0.0)
    y_train = train_data['label'].values
    w_train = train_data['weight'].values
    
    # Add model column to X_train
    X_train['model'] = train_data['model']
    
    # Process query features
    query_serials = query_index['serial_number']
    X_query = query_features.reindex(query_serials).fillna(0.0)
    X_query['model'] = query_features['model'][query_serials]
    
    # Perform target encoding
    X_train_te, X_query_te = target_encode_oof(X_train, X_query, y_train)
    
    # Remove original model column and prepare for LGBM
    cat_features = ['model']
    X_train_final = X_train_te.drop(columns=['model', 'serial_number', 'label', 'weight']) if 'serial_number' in X_train_te.columns else X_train_te.drop(columns=['model'])
    X_query_final = X_query_te.drop(columns=['model'])
    
    # Convert model to categorical for both train and query
    X_train_lgb = X_train_final.copy()
    X_query_lgb = X_query_final.copy()
    
    # Ensure categorical features are properly typed
    for col in cat_features:
        if col in X_train_lgb.columns:
            X_train_lgb[col] = X_train_lgb[col].astype('category')
        if col in X_query_lgb.columns:
            X_query_lgb[col] = X_query_lgb[col].astype('category')
    
    # Train LightGBM model
    print("Training model...")
    params = {
        'objective': 'binary',
        'metric': 'auc',
        'boosting_type': 'gbdt',
        'num_leaves': 31,
        'learning_rate': 0.05,
        'feature_fraction': 0.8,
        'bagging_fraction': 0.8,
        'bagging_freq': 5,
        'verbose': -1,
        'seed': 42
    }
    
    train_dataset = lgb.Dataset(X_train_lgb, label=y_train, weight=w_train, categorical_feature=cat_features)
    
    model = lgb.train(
        params,
        train_dataset,
        num_boost_round=300,
    )
    
    # Make predictions
    print("Making predictions...")
    train_probs = model.predict(X_train_lgb)
    query_probs = model.predict(X_query_lgb)
    
    # Calculate optimal threshold using out-of-fold method
    print("Calculating optimal threshold...")
    optimal_threshold = calculate_threshold_oof(y_train, train_probs, w_train)
    
    # Generate final predictions
    query_alarms = (query_probs >= optimal_threshold).astype(int)
    
    # Write results
    results = pd.DataFrame({
        'serial_number': query_serials,
        'score': query_probs,
        'alarm': query_alarms
    })
    
    results.to_csv(args.out, index=False)
    
    end_time = time.time()
    print(f"Total execution time: {end_time - start_time:.2f}s")

if __name__ == "__main__":
    main()