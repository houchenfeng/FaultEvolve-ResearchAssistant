"""Deterministic operator quota scheduling."""

from __future__ import annotations

from typing import Literal, Mapping

OperatorSlot = Literal["hpo", "patch", "draft"]

_ORDER: tuple[OperatorSlot, ...] = ("hpo", "patch", "draft")


def next_operator(counts: Mapping[str, int], shares: Mapping[str, int]) -> OperatorSlot:
    """Pick slot with largest quota deficit (largest remainder)."""
    total_weight = sum(shares.values())
    if total_weight <= 0:
        raise ValueError("shares must sum to > 0")
    n = sum(counts.get(k, 0) for k in shares) + 1
    best: OperatorSlot | None = None
    best_score = -1e18
    for key in _ORDER:
        weight = shares.get(key, 0)
        if weight <= 0:
            continue
        score = n * weight / total_weight - counts.get(key, 0)
        if score > best_score:
            best_score = score
            best = key
    return best or _ORDER[0]
