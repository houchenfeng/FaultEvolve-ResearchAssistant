"""Trial models for structured HPO."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from faultevolve.optimization.candidate_spec import CandidateSpec


@dataclass
class Trial:
    trial_id: str
    structure_id: str
    index: int
    spec: CandidateSpec
    seed: int
    fidelity: Literal["dev"]
    status: Literal["proposed", "refused", "running", "ok", "failed", "timeout"] = "proposed"
    fit_count: int = 0
    dev_proxy: float | None = None
    dev_metrics: dict | None = None
    cache_hit: bool = False
    failure_reason: str = ""
