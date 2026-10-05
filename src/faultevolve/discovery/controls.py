"""Negative and planted controls for discovery rounds."""

from __future__ import annotations

import hashlib

import numpy as np

from faultevolve.config import DiscoveryConfig
from faultevolve.discovery.schemas import ClaimTestResult, ControlReport
from faultevolve.discovery.stats import group_bootstrap_ci, permutation_p, signed_effect, test_feature


def is_stat_positive(res: ClaimTestResult, alpha: float) -> bool:
    if res.ci_low <= 0 <= res.ci_high:
        return False
    if not res.direction_ok:
        return False
    return res.p <= alpha


def _control_seed(cfg: DiscoveryConfig, claim_id: str, round_idx: int) -> int:
    return int(hashlib.sha256(f"{cfg.split_salt}|{claim_id}|{round_idx}".encode()).hexdigest()[:8], 16)


def run_negative_controls(
    features: dict[str, np.ndarray],
    y: np.ndarray,
    groups: np.ndarray,
    strata: np.ndarray,
    direction_by_id: dict[str, str],
    cfg: DiscoveryConfig,
    seed: int,
) -> tuple[int, int]:
    rng = np.random.default_rng(seed)
    false_pos = 0
    trials = 0
    y = np.asarray(y, dtype=int)
    groups = np.asarray(groups)
    strata = np.asarray(strata)
    for fid, x in features.items():
        direction = direction_by_id.get(fid, "+")
        for _ in range(cfg.neg_control_repeats):
            y_perm = y.copy()
            for s in np.unique(strata):
                idx = np.where(strata == s)[0]
                y_perm[idx] = rng.permutation(y_perm[idx])
            res = test_feature(x, y_perm, groups, direction, cfg, rng)
            trials += 1
            if is_stat_positive(res, cfg.alpha):
                false_pos += 1
    return false_pos, trials


def run_planted_controls(
    y: np.ndarray,
    groups: np.ndarray,
    cfg: DiscoveryConfig,
    seed: int,
    strengths: list[float] | None = None,
    repeats: int | None = None,
) -> dict[str, dict[str, float]]:
    rng = np.random.default_rng(seed)
    y = np.asarray(y, dtype=float)
    groups = np.asarray(groups)
    strengths = strengths if strengths is not None else list(cfg.planted_strengths)
    repeats = repeats if repeats is not None else cfg.neg_control_repeats
    out: dict[str, dict[str, float]] = {}
    for d in strengths:
        recovered = 0
        for _ in range(repeats):
            noise = rng.normal(0, 1, size=len(y))
            x = noise + float(d) * y
            direction = "+" if d >= 0 else "-"
            res = test_feature(x, y.astype(int), groups, direction, cfg, rng)
            if is_stat_positive(res, cfg.alpha):
                recovered += 1
        key = str(d)
        out[key] = {
            "trials": float(repeats),
            "recovered": float(recovered),
            "rate": recovered / max(repeats, 1),
        }
    return out


def run_controls(
    features: dict[str, np.ndarray],
    y: np.ndarray,
    groups: np.ndarray,
    strata: np.ndarray,
    direction_by_id: dict[str, str],
    cfg: DiscoveryConfig,
    round_idx: int,
    claim_ids: list[str],
) -> ControlReport:
    seed_base = _control_seed(cfg, claim_ids[0] if claim_ids else "none", round_idx)
    fp, trials = run_negative_controls(
        features, y, groups, strata, direction_by_id, cfg, seed_base + 1,
    )
    planted = run_planted_controls(y.astype(int), groups, cfg, seed_base + 2)
    neg_fpr = fp / max(trials, 1)
    passed = neg_fpr <= cfg.max_neg_control_fpr
    return ControlReport(
        neg_trials=trials,
        neg_false_positives=fp,
        neg_fpr=neg_fpr,
        planted=planted,
        passed=passed,
    )
