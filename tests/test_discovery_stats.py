"""Tests for discovery statistical helpers."""

from __future__ import annotations

import math
import time
import warnings

import numpy as np
import pandas as pd
import pytest

from faultevolve.discovery.stats import (
    auroc,
    bh_reject,
    e_from_p,
    ebh_reject,
    group_bootstrap_ci,
    incremental_auroc,
    max_abs_spearman,
    permutation_p,
    signed_effect,
)


def _reference_group_bootstrap_ci(
    x: np.ndarray,
    y: np.ndarray,
    groups: np.ndarray,
    b: int,
    alpha: float,
    rng: np.random.Generator,
) -> tuple[float, float]:
    groups = np.asarray(groups)
    unique_groups = np.unique(groups)
    effects: list[float] = []
    for _ in range(b):
        sampled = rng.choice(unique_groups, size=len(unique_groups), replace=True)
        idx_parts: list[np.ndarray] = []
        for g in sampled:
            idx_parts.append(np.where(groups == g)[0])
        if not idx_parts:
            continue
        idx = np.concatenate(idx_parts)
        ys = y[idx]
        if len(np.unique(ys)) < 2:
            continue
        effects.append(signed_effect(x[idx], ys))
    if not effects:
        return 0.0, 0.0
    lo = float(np.percentile(effects, 100 * alpha / 2))
    hi = float(np.percentile(effects, 100 * (1 - alpha / 2)))
    return lo, hi


def _reference_incremental_auroc_bootstrap(
    base_scores: np.ndarray,
    full_scores: np.ndarray,
    y: np.ndarray,
    groups: np.ndarray,
    b: int,
    alpha: float,
    rng: np.random.Generator,
) -> tuple[float, float, float]:
    y = np.asarray(y, dtype=int)
    groups = np.asarray(groups)
    gains: list[float] = []
    unique_groups = np.unique(groups)
    for _ in range(b):
        sampled = rng.choice(unique_groups, size=len(unique_groups), replace=True)
        idx_parts = [np.where(groups == g)[0] for g in sampled]
        idx = np.concatenate(idx_parts)
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


def test_bootstrap_coverage():
    """Bootstrap CI covers true signed effect for planted signal."""
    d = 0.8
    from scipy.stats import norm

    true_effect = float(norm.cdf(d / math.sqrt(2)) - 0.5)
    hits = 0
    for seed in range(20):
        rng = np.random.default_rng(seed)
        n = 400
        y = (rng.random(n) < 0.3).astype(int)
        x = rng.normal(d * y, 1.0, size=n)
        groups = np.arange(n)
        lo, hi = group_bootstrap_ci(x, y, groups, b=200, alpha=0.05, rng=rng)
        if lo <= true_effect <= hi:
            hits += 1
    assert hits >= 17


def test_group_bootstrap_ci_matches_reference():
    rng = np.random.default_rng(12345)
    n_groups = 200
    group_ids = np.repeat(np.arange(n_groups), rng.integers(1, 4, size=n_groups))
    y = (rng.random(len(group_ids)) < 0.25).astype(int)
    x = rng.normal(size=len(group_ids))
    groups = group_ids.astype(str)
    rng_ref = np.random.default_rng(99)
    rng_new = np.random.default_rng(99)
    lo_ref, hi_ref = _reference_group_bootstrap_ci(x, y, groups, 80, 0.05, rng_ref)
    lo_new, hi_new = group_bootstrap_ci(x, y, groups, 80, 0.05, rng_new)
    assert lo_new == lo_ref
    assert hi_new == hi_ref


def test_incremental_auroc_matches_reference():
    rng = np.random.default_rng(7)
    n = 120
    groups = np.array([f"g{i // 3}" for i in range(n)])
    y = (rng.random(n) < 0.3).astype(int)
    x_feat = rng.normal(size=n)
    baseline = pd.DataFrame({"b0": rng.normal(size=n), "b1": rng.normal(size=n)})
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import StratifiedKFold
    from sklearn.preprocessing import StandardScaler

    X_base = baseline.fillna(0).to_numpy(dtype=float)
    feat = np.asarray(x_feat, dtype=float).reshape(-1, 1)
    X_full = np.hstack([X_base, feat])
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
    rng_new = np.random.default_rng(42)
    rng_ref = np.random.default_rng(42)
    gain, lo, hi = incremental_auroc(x_feat, baseline, y, groups, 60, 0.05, rng_new)
    g_ref, lo_ref, hi_ref = _reference_incremental_auroc_bootstrap(
        base_scores, full_scores, y, groups, 60, 0.05, rng_ref,
    )
    assert gain == g_ref
    assert lo == lo_ref
    assert hi == hi_ref


def test_bootstrap_scales():
    n = 20_000
    y = (np.arange(n) % 7 == 0).astype(int)
    x = np.random.default_rng(0).normal(size=n)
    groups = np.array([f"u{i}" for i in range(n)])
    rng = np.random.default_rng(1)
    t0 = time.time()
    group_bootstrap_ci(x, y, groups, b=50, alpha=0.05, rng=rng)
    assert time.time() - t0 < 10.0


def test_max_abs_spearman_skips_constant_columns():
    baseline = pd.DataFrame(
        {"const": [1.0, 1.0, 1.0, 1.0], "varying": [1.0, 2.0, 3.0, 4.0]}
    )
    feature = baseline["varying"].to_numpy()
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        rho = max_abs_spearman(feature, baseline)
    assert rho == pytest.approx(1.0, abs=0.01)


def test_bh():
    out = bh_reject([0.001, 0.02, 0.04, 0.3], q=0.05)
    assert out == [True, True, False, False]


def test_ebh():
    out = ebh_reject([100, 50, 10, 1], alpha=0.05)
    assert out == [True, True, False, False]


def test_ebh_equal_pair_rejects_both():
    out = ebh_reject([39, 39], alpha=0.05)
    assert out == [True, True]


def test_e_calibrator():
    assert e_from_p(0.01) == pytest.approx(5.0)
    assert e_from_p(1.0) == pytest.approx(0.5)
    with pytest.raises(ValueError):
        e_from_p(0.5, kappa=1.0)
    with pytest.raises(ValueError):
        e_from_p(0.5, kappa=0.0)


def test_permutation_p_tail():
    rng = np.random.default_rng(42)
    n = 300
    y = (rng.random(n) < 0.3).astype(int)
    d = 1.5
    x = rng.normal(d * y, 1.0, size=n)
    p = permutation_p(x, y, b=500, rng=rng)
    e = e_from_p(p)
    assert p < 1e-6
    assert e >= 60


def test_auroc_ties():
    y = np.array([0, 0, 1, 1])
    x = np.array([1.0, 1.0, 1.0, 1.0])
    assert auroc(x, y) == pytest.approx(0.5)


def test_max_spearman():
    baseline = pd.DataFrame({"a": [1.0, 2.0, 3.0, 4.0], "b": [4.0, 3.0, 2.0, 1.0]})
    feature = baseline["a"].to_numpy()
    rho = max_abs_spearman(feature, baseline)
    assert rho == pytest.approx(1.0, abs=0.01)
