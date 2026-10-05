"""Statistical helpers for claim testing."""

from __future__ import annotations

import math

import numpy as np
from scipy import stats
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedKFold
from sklearn.preprocessing import StandardScaler

from faultevolve.config import DiscoveryConfig
from faultevolve.discovery.schemas import ClaimTestResult


def auroc(x: np.ndarray, y: np.ndarray) -> float:
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=int)
    mask = np.isfinite(x)
    x, y = x[mask], y[mask]
    if len(x) == 0 or len(np.unique(y)) < 2:
        return 0.5
    ranks = stats.rankdata(x, method="average")
    pos = y == 1
    n_pos = pos.sum()
    n_neg = (~pos).sum()
    if n_pos == 0 or n_neg == 0:
        return 0.5
    rank_sum_pos = ranks[pos].sum()
    return (rank_sum_pos - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg)


def signed_effect(x: np.ndarray, y: np.ndarray) -> float:
    return auroc(x, y) - 0.5


def _group_index_parts(groups: np.ndarray) -> tuple[np.ndarray, list[np.ndarray]]:
    groups = np.asarray(groups)
    uniq, inverse = np.unique(groups, return_inverse=True)
    order = np.argsort(inverse, kind="stable")
    counts = np.bincount(inverse)
    if len(counts) == 0:
        return uniq, []
    cuts = np.cumsum(counts)[:-1]
    parts = list(np.split(order, cuts)) if len(cuts) else [order]
    return uniq, parts


def _resample_index(
    parts: list[np.ndarray],
    unique_groups: np.ndarray,
    rng: np.random.Generator,
) -> np.ndarray | None:
    sampled = rng.choice(unique_groups, size=len(unique_groups), replace=True)
    pos = np.searchsorted(unique_groups, sampled)
    idx_parts = [parts[i] for i in pos]
    if not idx_parts:
        return None
    return np.concatenate(idx_parts)


def group_bootstrap_ci(
    x: np.ndarray,
    y: np.ndarray,
    groups: np.ndarray,
    b: int,
    alpha: float,
    rng: np.random.Generator,
) -> tuple[float, float]:
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=int)
    groups = np.asarray(groups)
    unique_groups, parts = _group_index_parts(groups)
    effects: list[float] = []
    for _ in range(b):
        idx = _resample_index(parts, unique_groups, rng)
        if idx is None:
            continue
        ys = y[idx]
        if len(np.unique(ys)) < 2:
            continue
        effects.append(signed_effect(x[idx], ys))
    if not effects:
        return 0.0, 0.0
    lo = float(np.percentile(effects, 100 * alpha / 2))
    hi = float(np.percentile(effects, 100 * (1 - alpha / 2)))
    return lo, hi


def permutation_p(x: np.ndarray, y: np.ndarray, b: int, rng: np.random.Generator) -> float:
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=int)
    mask = np.isfinite(x)
    x, y = x[mask], y[mask]
    if len(x) < 2 or len(np.unique(y)) < 2:
        return 1.0
    t_obs = signed_effect(x, y)
    count = 0
    stats_list: list[float] = []
    for _ in range(b):
        y_perm = rng.permutation(y)
        t = signed_effect(x, y_perm)
        stats_list.append(t)
        if abs(t) >= abs(t_obs):
            count += 1
    if count >= 5:
        return (1 + count) / (1 + b)
    sd = float(np.std(stats_list, ddof=1)) if len(stats_list) > 1 else 0.0
    if sd <= 0:
        return 1.0
    z = abs(t_obs) / sd
    p = 2 * (1 - stats.norm.cdf(z))
    return max(p, 1e-300)


def e_from_p(p: float, kappa: float = 0.5) -> float:
    if kappa <= 0 or kappa >= 1:
        raise ValueError("kappa must be in (0, 1)")
    return kappa * max(p, 1e-300) ** (kappa - 1)


def bh_reject(pvals: list[float], q: float) -> list[bool]:
    m = len(pvals)
    if m == 0:
        return []
    order = np.argsort(pvals)
    rejected = [False] * m
    max_k = -1
    for k, idx in enumerate(order, start=1):
        if pvals[idx] <= q * k / m:
            max_k = k
    if max_k >= 0:
        for idx in order[:max_k]:
            rejected[idx] = True
    return rejected


def ebh_reject(evals: list[float], alpha: float) -> list[bool]:
    m = len(evals)
    if m == 0:
        return []
    order = np.argsort(evals)[::-1]
    rejected = [False] * m
    max_k = 0
    for k, idx in enumerate(order, start=1):
        if evals[idx] >= m / (k * alpha):
            max_k = k
    for idx in order[:max_k]:
        rejected[idx] = True
    return rejected


def rate_ratio_top_quantile(x: np.ndarray, y: np.ndarray, q: float = 0.9) -> float:
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=int)
    mask = np.isfinite(x)
    x, y = x[mask], y[mask]
    if len(x) == 0:
        return 0.0
    thr = np.quantile(x, q)
    top = x >= thr
    rate_top = y[top].mean() if top.any() else 0.0
    rate_all = y.mean() if len(y) else 0.0
    if rate_all <= 0:
        return 0.0
    return float(rate_top / rate_all)


def max_abs_spearman(feature: np.ndarray, baseline_df) -> float:
    import pandas as pd

    f = np.asarray(feature, dtype=float)
    if baseline_df is None or len(baseline_df.columns) == 0:
        return 0.0
    best = 0.0
    for col in baseline_df.columns:
        b = baseline_df[col].to_numpy(dtype=float)
        mask = np.isfinite(f) & np.isfinite(b)
        if mask.sum() < 3:
            continue
        if np.ptp(b[mask]) == 0:
            continue
        rho, _ = stats.spearmanr(f[mask], b[mask])
        if np.isfinite(rho):
            best = max(best, abs(float(rho)))
    return best


def incremental_auroc(
    feature: np.ndarray,
    baseline_df,
    y: np.ndarray,
    groups: np.ndarray,
    b: int,
    alpha: float,
    rng: np.random.Generator,
) -> tuple[float, float, float]:
    import pandas as pd

    y = np.asarray(y, dtype=int)
    groups = np.asarray(groups)
    X_base = baseline_df.fillna(0).to_numpy(dtype=float)
    feat = np.asarray(feature, dtype=float)
    if feat.ndim == 1:
        feat = feat.reshape(-1, 1)
    X_full = np.hstack([X_base, feat])
    if len(np.unique(y)) < 2 or X_base.shape[0] < 10:
        return 0.0, 0.0, 0.0
    skf = StratifiedKFold(n_splits=min(3, len(np.unique(y))), shuffle=True, random_state=0)
    base_scores = np.zeros(len(y), dtype=float)
    full_scores = np.zeros(len(y), dtype=float)
    for train_idx, test_idx in skf.split(X_base, y):
        scaler_b = StandardScaler()
        scaler_f = StandardScaler()
        Xb_tr = scaler_b.fit_transform(X_base[train_idx])
        Xb_te = scaler_b.transform(X_base[test_idx])
        Xf_tr = scaler_f.fit_transform(X_full[train_idx])
        Xf_te = scaler_f.transform(X_full[test_idx])
        m0 = LogisticRegression(max_iter=200)
        m1 = LogisticRegression(max_iter=200)
        m0.fit(Xb_tr, y[train_idx])
        m1.fit(Xf_tr, y[train_idx])
        base_scores[test_idx] = m0.predict_proba(Xb_te)[:, 1]
        full_scores[test_idx] = m1.predict_proba(Xf_te)[:, 1]
    gains: list[float] = []
    unique_groups, parts = _group_index_parts(groups)
    for _ in range(b):
        idx = _resample_index(parts, unique_groups, rng)
        if idx is None:
            continue
        ys = y[idx]
        if len(np.unique(ys)) < 2:
            continue
        g0 = auroc(base_scores[idx], ys)
        g1 = auroc(full_scores[idx], ys)
        gains.append(g1 - g0)
    if not gains:
        point = auroc(full_scores, y) - auroc(base_scores, y)
        return point, point, point
    lo = float(np.percentile(gains, 100 * alpha / 2))
    hi = float(np.percentile(gains, 100 * (1 - alpha / 2)))
    return float(np.mean(gains)), lo, hi


def test_feature(
    x: np.ndarray,
    y: np.ndarray,
    groups: np.ndarray,
    direction: str,
    cfg: DiscoveryConfig,
    rng: np.random.Generator,
) -> ClaimTestResult:
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=int)
    groups = np.asarray(groups)
    effect = signed_effect(x, y)
    lo, hi = group_bootstrap_ci(x, y, groups, cfg.bootstrap_b, cfg.alpha, rng)
    p = permutation_p(x, y, cfg.bootstrap_b, rng)
    e = e_from_p(p, cfg.e_calibrator_kappa)
    direction_ok = np.sign(effect) == (1 if direction == "+" else -1)
    n_pos = int((y == 1).sum())
    n_neg = int((y == 0).sum())
    return ClaimTestResult(
        split="confirm",
        n=len(y),
        n_pos=n_pos,
        n_neg=n_neg,
        effect=float(effect),
        ci_low=lo,
        ci_high=hi,
        p=float(p),
        e=float(e),
        direction_ok=bool(direction_ok),
    )
