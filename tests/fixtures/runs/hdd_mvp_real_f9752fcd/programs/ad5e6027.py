"""Improved solution: LightGBM on engineered window features with trend analysis.

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
from sklearn.preprocessing import StandardScaler
import lightgbm as lgb

FEATURES = [
    "smart_5_raw", "smart_187_raw", "smart_188_raw", "smart_197_raw", "smart_198_raw",
    "smart_199_raw", "smart_9_raw", "smart_194_raw", "smart_1_normalized", "smart_7_normalized",
]

def extract_window_features(history: pd.DataFrame) -> pd.DataFrame:
    """Extract features from 14-day window of SMART data"""
    history_sorted = history.sort_values(["serial_number", "date"])
    
    # Group by serial number to process each disk separately
    def process_disk(disk_data):
        disk_data = disk_data.sort_values("date")
        
        # Compute trends for key features
        features = {}
        
        for col in FEATURES:
            if col in disk_data.columns:
                vals = disk_data[col].dropna()
                if len(vals) > 0:
                    # Basic stats
                    features[f'{col}_last'] = vals.iloc[-1] if len(vals) > 0 else 0
                    features[f'{col}_mean'] = vals.mean()
                    features[f'{col}_std'] = vals.std() if len(vals) > 1 else 0
                    features[f'{col}_min'] = vals.min()
                    features[f'{col}_max'] = vals.max()
                    
                    # Trends (only if we have at least 2 points)
                    if len(vals) >= 2:
                        x_vals = np.arange(len(vals))
                        # Linear trend (slope)
                        coeffs = np.polyfit(x_vals, vals.values, 1)
                        features[f'{col}_trend'] = coeffs[0]  # slope
                        features[f'{col}_change'] = vals.iloc[-1] - vals.iloc[0]  # total change
                        features[f'{col}_change_pct'] = (vals.iloc[-1] - vals.iloc[0]) / (abs(vals.iloc[0]) + 1e-8)  # relative change
                    else:
                        features[f'{col}_trend'] = 0
                        features[f'{col}_change'] = 0
                        features[f'{col}_change_pct'] = 0
                else:
                    # Fill missing features with zeros
                    features[f'{col}_last'] = 0
                    features[f'{col}_mean'] = 0
                    features[f'{col}_std'] = 0
                    features[f'{col}_min'] = 0
                    features[f'{col}_max'] = 0
                    features[f'{col}_trend'] = 0
                    features[f'{col}_change'] = 0
                    features[f'{col}_change_pct'] = 0
        
        # Add vendor features based on model prefix
        model_name = disk_data['model'].iloc[-1] if 'model' in disk_data.columns and len(disk_data) > 0 else ""
        for vendor in ["ST", "TOSHIBA", "HGST", "WDC"]:
            features[f'vendor_{vendor}'] = float(model_name.startswith(vendor))
        
        # Add model as a categorical feature
        features['model'] = model_name
        
        # Add basic features that are always available
        if 'capacity_bytes' in disk_data.columns:
            features['capacity_bytes'] = disk_data['capacity_bytes'].iloc[-1] if len(disk_data) > 0 else 0
        else:
            features['capacity_bytes'] = 0
            
        return pd.Series(features)
    
    # Apply to each disk group
    result = history_sorted.groupby('serial_number').apply(process_disk).reset_index()
    result.set_index('serial_number', inplace=True)
    
    return result

def prepare_features(df):
    """Prepare features by filling missing values and applying transformations"""
    # Log transform positive features
    for col in df.columns:
        if col.startswith('smart_') and col.endswith(('_last', '_mean', '_min', '_max', '_change', '_change_pct')):
            df[col] = np.log1p(np.abs(df[col])) if df[col].dtype != 'object' else df[col]
    
    # Fill remaining NaN with 0
    df = df.fillna(0.0)
    
    # Ensure model column is categorical
    if 'model' in df.columns:
        df['model'] = df['model'].astype('category')
    
    return df

def best_f1_threshold(y: np.ndarray, p: np.ndarray, w: np.ndarray) -> float:
    best_t, best_f1 = 0.5, -1.0
    for t in np.quantile(p, np.linspace(0.90, 0.999, 60)):
        a = p >= t
        tp = np.sum(w * (y == 1) * a)
        fp = np.sum(w * (y == 0) * a)
        fn = np.sum(w * (y == 1) * ~a)
        f1 = 2 * tp / max(2 * tp + fp + fn, 1e-12)
        if f1 > best_f1:
            best_t, best_f1 = t, f1
    return float(best_t)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--split", required=True, choices=["val", "test"])
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    train_hist = pd.read_csv(os.path.join(args.data_dir, "train_history.csv.gz"), parse_dates=["date"])
    train_lab = pd.read_csv(os.path.join(args.data_dir, "train_labels.csv")).set_index("serial_number")
    query_hist = pd.read_csv(os.path.join(args.data_dir, f"{args.split}_history.csv.gz"), parse_dates=["date"])
    query_idx = pd.read_csv(os.path.join(args.data_dir, f"{args.split}_index.csv"))

    # Extract features from history data
    x_train_full = extract_window_features(train_hist)
    x_train = x_train_full.reindex(train_lab.index)
    x_train = prepare_features(x_train)
    
    # Separate categorical and numerical features for LightGBM
    cat_cols = ['model']
    num_cols = [col for col in x_train.columns if col not in cat_cols]
    
    # Prepare training data
    X_train = x_train[num_cols].fillna(0.0)  # Fill any remaining NaN
    X_train_cat = x_train[cat_cols] if all(col in x_train.columns for col in cat_cols) else None
    
    # If we have categorical features, concatenate with numerical
    if X_train_cat is not None and len(cat_cols) > 0:
        X_train = pd.concat([X_train, X_train_cat], axis=1)
    
    y_train = train_lab["label"].to_numpy()
    w_train = train_lab["weight"].to_numpy()

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
        verbose=-1,
        categorical_feature=cat_cols if all(col in X_train.columns for col in cat_cols) else 'auto'
    )
    
    model.fit(X_train, y_train, sample_weight=w_train)
    
    # Find optimal threshold using training data
    p_train = model.predict_proba(X_train)[:, 1]
    threshold = best_f1_threshold(y_train, p_train, w_train)

    # Process query data
    x_query_full = extract_window_features(query_hist)
    x_query = x_query_full.reindex(query_idx["serial_number"])
    x_query = prepare_features(x_query)
    
    # Align features with training
    X_query = x_query[num_cols].fillna(0.0)  # Fill any remaining NaN
    if X_train_cat is not None and len(cat_cols) > 0:
        X_query = pd.concat([X_query, x_query[cat_cols]], axis=1)
    
    # Predict on query set
    p = model.predict_proba(X_query)[:, 1]
    pred = pd.DataFrame({
        "serial_number": query_idx["serial_number"],
        "score": p,
        "alarm": (p >= threshold).astype(int),
    })
    pred.to_csv(args.out, index=False)


if __name__ == "__main__":
    main()