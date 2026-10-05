"""Baseline feature matrix for incremental novelty checks."""

from __future__ import annotations

import pandas as pd


def build_baseline_features(
    history: pd.DataFrame,
    unit_col: str,
    time_col: str,
    cols: list[str],
    lag_rows: int = 14,
) -> pd.DataFrame:
    rows: dict[str, dict[str, float]] = {}
    for unit, grp in history.sort_values(time_col).groupby(unit_col):
        g = grp
        feat: dict[str, float] = {}
        for c in cols:
            if c not in g.columns:
                continue
            series = g[c]
            last = float(series.iloc[-1]) if len(series) else 0.0
            if pd.isna(last):
                last = 0.0
            feat[f"{c}__last"] = last
            if len(series) > lag_rows:
                prev = series.iloc[-1 - lag_rows]
                diff = last - (float(prev) if pd.notna(prev) else 0.0)
            else:
                diff = 0.0
            feat[f"{c}__diff{lag_rows}"] = diff
            nz = ((series != 0) & series.notna()).sum()
            feat[f"{c}__nz"] = float(nz)
        rows[str(unit)] = feat
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame.from_dict(rows, orient="index")
    return df.fillna(0.0)
