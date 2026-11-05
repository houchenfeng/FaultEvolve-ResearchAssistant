def feature(history):
    import pandas as pd
    import numpy as np
    from scipy import stats

    # Assume VENDOR_LIST and DELTA_FEATURES are defined as in the original code
    VENDOR_LIST = ['ST', 'WD', 'SE']  # example vendors; adjust if needed
    DELTA_FEATURES = [
        'smart_1_raw', 'smart_3_raw', 'smart_4_raw', 'smart_5_raw', 'smart_7_raw',
        'smart_9_raw', 'smart_10_raw', 'smart_12_raw', 'smart_187_raw', 'smart_188_raw',
        'smart_190_raw', 'smart_191_raw', 'smart_192_raw', 'smart_193_raw', 'smart_194_raw',
        'smart_196_raw', 'smart_197_raw', 'smart_198_raw', 'smart_199_raw', 'smart_240_raw',
        'smart_241_raw', 'smart_242_raw'
    ]

    # Pivot history to wide format by serial_number
    pivoted = history.set_index(['serial_number', 'date']).sort_index()
    
    # Get last snapshot per drive
    last_snap = history.loc[history.groupby('serial_number')['date'].idxmax()].set_index('serial_number')
    
    # Initialize output DataFrame indexed by serial_number
    x = pd.DataFrame(index=last_snap.index)
    
    # Vendor-specific log features
    for vendor in VENDOR_LIST:
        vendor_mask = last_snap['model'].str.startswith(vendor)
        for feat in ['smart_187_raw', 'smart_188_raw', 'smart_190_raw', 'smart_197_raw', 'smart_198_raw']:
            if feat in last_snap.columns:
                feat_vals = last_snap[feat].astype(float)
                x[f"{vendor}_{feat}_log"] = np.log1p(feat_vals.where(vendor_mask, 0.0)).fillna(0.0)
    
    # Trend features using slope
    for feat in DELTA_FEATURES:
        if feat in pivoted.columns:
            pivot_table = pivoted[feat].unstack(level='date').T  # serial_number as columns, date as index
            pivot_table = pivot_table.T  # now serial_number as index, date as columns
            slopes = []
            for idx in pivot_table.index:
                row = pivot_table.loc[idx].dropna()
                if len(row) > 1:
                    x_coords = np.arange(len(row))
                    slope, _, _, _, _ = stats.linregress(x_coords, row.values)
                    slopes.append(slope)
                else:
                    slopes.append(0.0)
            x[f"{feat}_trend"] = pd.Series(slopes, index=pivot_table.index).fillna(0.0)
    
    return x