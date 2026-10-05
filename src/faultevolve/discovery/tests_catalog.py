"""Statistical tests for mechanism tournament."""

from __future__ import annotations

from typing import Callable

import numpy as np
import pandas as pd
from scipy import stats

from faultevolve.config import DiscoveryConfig, TournamentConfig
from faultevolve.discovery.schemas import Mechanism
from faultevolve.discovery.splits import temporal_halves
from faultevolve.discovery.stats import e_from_p, signed_effect

TEST_TYPES = (
    "env_invariance",
    "temporal",
    "dose_response",
    "mediation",
    "heterogeneity",
)

_PRIOR_EFFECT = {
    "env_invariance": 1.0,
    "heterogeneity": 0.9,
    "temporal": 0.7,
    "dose_response": 0.6,
    "mediation": 0.5,
}


def available_tests(env_frame: pd.DataFrame | None, min_env_pos: int = 5) -> list[str]:
    avail = ["dose_response"]
    if env_frame is None:
        return avail
    if "env" in env_frame.columns:
        env = env_frame["env"].astype(str)
        y_pos_by_env = env_frame.groupby(env)["y"].sum() if "y" in env_frame.columns else None
        if y_pos_by_env is not None:
            good_envs = (y_pos_by_env >= min_env_pos).sum()
            if good_envs >= 2:
                avail.extend(["env_invariance", "heterogeneity"])
    if "time" in env_frame.columns:
        avail.append("temporal")
    if "conf" in env_frame.columns:
        avail.append("mediation")
    return sorted(set(avail), key=lambda t: TEST_TYPES.index(t) if t in TEST_TYPES else 99)


def bootstrap_dist(
    stat_fn: Callable[[], float],
    b: int,
    rng: np.random.Generator,
) -> np.ndarray:
    return np.array([stat_fn() for _ in range(b)], dtype=float)


def _group_bootstrap(
    x: np.ndarray,
    y: np.ndarray,
    groups: np.ndarray,
    b: int,
    rng: np.random.Generator,
    stat_fn: Callable[[np.ndarray, np.ndarray], float],
) -> np.ndarray:
    groups = np.asarray(groups)
    uniq = np.unique(groups)

    def one() -> float:
        sampled = rng.choice(uniq, size=len(uniq), replace=True)
        idx = np.concatenate([np.where(groups == g)[0] for g in sampled])
        if len(idx) < 2 or len(np.unique(y[idx])) < 2:
            return 0.0
        return stat_fn(x[idx], y[idx])

    return bootstrap_dist(one, b, rng)


def _env_invariance_stat(
    x: np.ndarray,
    y: np.ndarray,
    env: np.ndarray,
    min_env_pos: int,
) -> float:
    effects = []
    weights = []
    for e in np.unique(env):
        mask = env == e
        if y[mask].sum() < min_env_pos:
            continue
        if len(np.unique(y[mask])) < 2:
            continue
        effects.append(signed_effect(x[mask], y[mask]))
        weights.append(mask.sum())
    if not effects:
        return 0.0
    w = np.array(weights, dtype=float)
    w /= w.sum()
    return float(np.dot(w, effects))


def _heterogeneity_stat(
    x: np.ndarray,
    y: np.ndarray,
    env: np.ndarray,
    min_env_pos: int,
) -> float:
    pooled = signed_effect(x, y)
    within = _env_invariance_stat(x, y, env, min_env_pos)
    return pooled - within


def _temporal_stat(x: np.ndarray, y: np.ndarray, time: np.ndarray, direction: str) -> float:
    first, second = temporal_halves(pd.Series(np.asarray(time)))
    e1 = signed_effect(x[first], y[first]) if first.any() else 0.0
    e2 = signed_effect(x[second], y[second]) if second.any() else 0.0
    sign = 1.0 if direction == "+" else -1.0
    return sign * (e2 - e1)


def _dose_response_stat(x: np.ndarray, y: np.ndarray, direction: str) -> float:
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=int)
    if len(x) < 10:
        return 0.0
    try:
        bins = pd.qcut(x, 5, duplicates="drop")
    except ValueError:
        return 0.0
    rates = []
    ranks = []
    for i, cat in enumerate(bins.categories):
        mask = bins == cat
        if mask.sum() == 0:
            continue
        rates.append(y[mask].mean())
        ranks.append(i)
    if len(rates) < 2:
        return 0.0
    corr, _ = stats.spearmanr(ranks, rates)
    if np.isnan(corr):
        return 0.0
    return -float(corr) if direction == "-" else float(corr)


def _mediation_stat(x: np.ndarray, y: np.ndarray, conf: np.ndarray, min_env_pos: int) -> float:
    effects = []
    weights = []
    for c in np.unique(conf):
        mask = conf == c
        if y[mask].sum() < min_env_pos:
            continue
        if len(np.unique(y[mask])) < 2:
            continue
        effects.append(signed_effect(x[mask], y[mask]))
        weights.append(mask.sum())
    if not effects:
        return signed_effect(x, y)
    w = np.array(weights, dtype=float)
    w /= w.sum()
    return float(np.dot(w, effects))


def run_test(
    test_type: str,
    x: np.ndarray,
    y: np.ndarray,
    groups: np.ndarray,
    env_frame_slice: pd.DataFrame,
    cfg: DiscoveryConfig,
    tcfg: TournamentConfig,
    rng: np.random.Generator,
    direction: str = "+",
) -> tuple[float, float, float, float, float]:
    """Return stat, ci_low, ci_high, p_pos, p_null."""
    b = cfg.bootstrap_b
    alpha = cfg.alpha
    margin = tcfg.equiv_margin
    min_env_pos = tcfg.min_env_pos

    env = env_frame_slice.get("env", pd.Series(["0"] * len(y))).to_numpy()
    time = env_frame_slice.get("time", pd.Series(range(len(y)))).to_numpy()
    conf = env_frame_slice.get("conf", pd.Series(["0"] * len(y))).to_numpy()

    if test_type == "env_invariance":
        stat_fn = lambda a, b_: _env_invariance_stat(a, b_, env, min_env_pos)
    elif test_type == "heterogeneity":
        stat_fn = lambda a, b_: _heterogeneity_stat(a, b_, env, min_env_pos)
    elif test_type == "temporal":
        stat_fn = lambda a, b_: _temporal_stat(a, b_, time, direction)
    elif test_type == "dose_response":
        stat_fn = lambda a, b_: _dose_response_stat(a, b_, direction)
    elif test_type == "mediation":
        stat_fn = lambda a, b_: _mediation_stat(a, b_, conf, min_env_pos)
    else:
        return 0.0, 0.0, 0.0, 1.0, 1.0

    stat = stat_fn(x, y)
    boot = _group_bootstrap(x, y, groups, b, rng, stat_fn)
    ci_low = float(np.percentile(boot, 100 * alpha / 2))
    ci_high = float(np.percentile(boot, 100 * (1 - alpha / 2)))
    p_pos = (1 + np.sum(boot <= 0)) / (1 + b)
    p_null = (1 + np.sum(boot >= margin)) / (1 + b)
    return stat, ci_low, ci_high, float(p_pos), float(p_null)


def derive_tests(ma: Mechanism, mb: Mechanism, avail: list[str]) -> list[str]:
    tests = [
        t
        for t in avail
        if ma.predictions.get(t, -1) * mb.predictions.get(t, -1) == -1
    ]
    return sorted(tests, key=lambda t: (-abs(_PRIOR_EFFECT.get(t, 0.0)), t))
