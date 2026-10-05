"""Invariant causal prediction check for mechanism establishment."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from faultevolve.discovery.stats import signed_effect


@dataclass
class IcpResult:
    passed: bool
    reason: str
    env_effects: dict[str, float]
    het_p: float | None
    gate_p: float | None


def _eta_squared(x: np.ndarray, env: np.ndarray) -> float:
    ranks = np.argsort(np.argsort(x))
    groups = [ranks[env == e] for e in np.unique(env)]
    groups = [g for g in groups if len(g) > 0]
    if not groups:
        return 0.0
    all_vals = np.concatenate(groups)
    grand = all_vals.mean()
    ss_tot = ((all_vals - grand) ** 2).sum()
    if ss_tot <= 0:
        return 0.0
    ss_between = sum(len(g) * (g.mean() - grand) ** 2 for g in groups)
    return float(ss_between / ss_tot)


def icp_check(
    x: np.ndarray,
    y: np.ndarray,
    env: np.ndarray,
    direction: str,
    alpha: float,
    b: int,
    gate_p: float,
    min_env_pos: int,
    rng: np.random.Generator,
) -> IcpResult:
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=int)
    env = np.asarray(env).astype(str)
    eta_x = _eta_squared(x, env)
    rates = []
    for e in np.unique(env):
        mask = env == e
        rates.append(y[mask].mean() if mask.any() else 0.0)
    rate_var = float(np.var(rates)) if rates else 0.0

    perm_x = []
    perm_y = []
    for _ in range(b):
        perm = rng.permutation(env)
        perm_x.append(_eta_squared(x, perm))
        pr = []
        for e in np.unique(perm):
            mask = perm == e
            pr.append(y[mask].mean() if mask.any() else 0.0)
        perm_y.append(float(np.var(pr)) if pr else 0.0)
    p_x = (1 + sum(p >= eta_x for p in perm_x)) / (1 + b)
    p_y = (1 + sum(p >= rate_var for p in perm_y)) / (1 + b)
    gate = min(p_x, p_y)
    if gate > gate_p:
        return IcpResult(False, "env_uninformative", {}, None, float(gate))

    env_effects: dict[str, float] = {}
    for e in np.unique(env):
        mask = env == e
        if y[mask].sum() < min_env_pos:
            continue
        if len(np.unique(y[mask])) < 2:
            continue
        env_effects[str(e)] = signed_effect(x[mask], y[mask])

    if len(env_effects) < 2:
        return IcpResult(False, "too_few_envs", env_effects, None, gate)

    sign = 1 if direction == "+" else -1
    for eff in env_effects.values():
        if np.sign(eff) != sign and eff != 0:
            return IcpResult(False, "sign_flip", env_effects, None, gate)

    vals = list(env_effects.values())
    weights = np.array([1.0] * len(vals))
    weights /= weights.sum()
    het = float(np.average((vals - np.average(vals, weights=weights)) ** 2, weights=weights))
    het_perm = []
    for _ in range(b):
        perm = rng.permutation(env)
        effs = []
        for e in np.unique(perm):
            mask = perm == e
            if y[mask].sum() < min_env_pos:
                continue
            if len(np.unique(y[mask])) < 2:
                continue
            effs.append(signed_effect(x[mask], y[mask]))
        if len(effs) < 2:
            het_perm.append(0.0)
            continue
        w = np.ones(len(effs)) / len(effs)
        het_perm.append(float(np.average((effs - np.average(effs, weights=w)) ** 2, weights=w)))
    het_p = (1 + sum(h >= het for h in het_perm)) / (1 + b)
    if het_p <= alpha:
        return IcpResult(False, "heterogeneous", env_effects, het_p, gate)
    return IcpResult(True, "ok", env_effects, het_p, gate)
