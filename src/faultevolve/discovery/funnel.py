"""Discovery funnel tracking for factor runs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np


def json_native(obj: Any) -> Any:
    """Convert numpy scalars/arrays to JSON-safe native types."""
    if isinstance(obj, dict):
        return {k: json_native(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [json_native(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, np.generic):
        return obj.item()
    return obj


@dataclass
class FunnelRecord:
    factor_id: str
    comparison_index: int
    stage_reached: str
    primary_failure: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "factor_id": self.factor_id,
            "comparison_index": self.comparison_index,
            "stage_reached": self.stage_reached,
            "primary_failure": self.primary_failure,
            "detail": json_native(self.detail),
        }


def funnel_summary_dict(
    records: list[FunnelRecord],
    track_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    counts = build_funnel_counts(records)
    power_pass = sum(
        1
        for r in records
        if r.stage_reached in {"power_gate", "frozen", "confirmed_stats", "discovered_or_confirmed"}
        or (r.detail or {}).get("power_gate_pass")
    )
    out: dict[str, Any] = {
        **counts,
        "literature_dedup": "not_done",
        "records": len(records),
        "power_gate_pass": power_pass,
        "mde_explore_effect_floor": 0.05,
    }
    if track_meta:
        out.update(track_meta)
    return out


def build_funnel_counts(records: list[FunnelRecord]) -> dict[str, int]:
    stages = (
        "proposed",
        "executable",
        "coverage_ok",
        "deduped",
        "explore_incr",
        "power_gate",
        "frozen",
        "confirmed_stats",
        "discovered_or_confirmed",
    )
    counts = {s: 0 for s in stages}
    for rec in records:
        reached = rec.stage_reached
        order = list(stages)
        if reached not in order:
            continue
        idx = order.index(reached)
        for s in order[: idx + 1]:
            counts[s] += 1
    return counts
