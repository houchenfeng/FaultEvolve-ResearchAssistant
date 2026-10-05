"""Dev-set ablation for module attribution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Literal

import numpy as np

from faultevolve.optimization.candidate_spec import CandidateSpec
from faultevolve.optimization.ledger import CostLedger, CostRecord


@dataclass
class AblationEntry:
    unit: str
    kind: Literal["remove", "replace"]
    dev_proxy: float | None
    delta: float | None
    ci: tuple[float, float] | None


@dataclass
class AblationReport:
    baseline_dev_proxy: float
    entries: list[AblationEntry]
    fits_charged: int
    resamples: int
    method: str
    skipped_budget: list[str]


def run_ablation(
    spec: CandidateSpec,
    *,
    units: list[str],
    dev_runner: Callable[[CandidateSpec], tuple[float, dict]],
    ledger: CostLedger,
    max_units: int,
    paired_resamples: int,
    seed: int,
    fits_per_run: int,
) -> AblationReport:
    baseline_proxy, baseline_metrics = dev_runner(spec)
    entries: list[AblationEntry] = []
    charged = 0
    skipped: list[str] = []
    rng = np.random.default_rng(seed)
    for unit in units:
        if len(entries) >= max_units:
            skipped.append(unit)
            continue
        variant = spec.model_copy(deep=True)
        if unit in variant.feature_groups:
            variant.feature_groups = [g for g in variant.feature_groups if g != unit]
            kind: Literal["remove", "replace"] = "remove"
        else:
            kind = "replace"
        res = ledger.reserve("ablation", est_model_fits=fits_per_run)
        proxy, var_metrics = dev_runner(variant)
        ledger.settle(
            res,
            CostRecord(
                seq=0,
                stage="ablation",
                fidelity="dev",
                node_id=None,
                model_fit_count=fits_per_run,
                status="ok",
            ),
        )
        charged += fits_per_run
        delta = proxy - baseline_proxy
        ci = _paired_ci(baseline_metrics, var_metrics, paired_resamples, rng)
        entries.append(
            AblationEntry(unit=unit, kind=kind, dev_proxy=proxy, delta=delta, ci=ci)
        )
    return AblationReport(
        baseline_dev_proxy=baseline_proxy,
        entries=entries,
        fits_charged=charged,
        resamples=paired_resamples,
        method="paired_serial_bootstrap(dev_proxy)",
        skipped_budget=skipped,
    )


def _paired_ci(
    base_metrics: dict,
    var_metrics: dict,
    resamples: int,
    rng: np.random.Generator,
) -> tuple[float, float] | None:
    base_scores = base_metrics.get("serial_scores")
    var_scores = var_metrics.get("serial_scores")
    if not base_scores or not var_scores:
        return None
    common = sorted(set(base_scores) & set(var_scores))
    if not common:
        return None
    diffs = np.array([var_scores[s] - base_scores[s] for s in common], dtype=float)
    boots = []
    n = len(diffs)
    for _ in range(resamples):
        idx = rng.integers(0, n, size=n)
        boots.append(float(diffs[idx].mean()))
    low, high = np.percentile(boots, [2.5, 97.5])
    return float(low), float(high)
