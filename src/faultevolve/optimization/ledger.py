"""Cost ledger for autotune / evolution budgeting."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

Stage = Literal[
    "cold_start",
    "generate",
    "reflect",
    "repair",
    "self_fix",
    "smoke",
    "hpo_fit",
    "hpo_trial",
    "hpo_dev_eval",
    "ablation",
    "analysis",
    "crossover",
    "full_eval",
    "other",
]
Fidelity = Literal["none", "smoke", "dev", "full_val"]


@dataclass(frozen=True)
class CostRecord:
    seq: int
    stage: Stage
    fidelity: Fidelity
    node_id: str | None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    model_fit_count: int = 0
    evaluator_calls: int = 0
    cpu_seconds: float | None = None
    rss_peak_mb: float | None = None
    wall_s: float = 0.0
    cache_hit: bool = False
    status: Literal["ok", "failed", "timeout", "rejected"] = "ok"
    reservation_id: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Reservation:
    id: str
    stage: Stage
    est_tokens: int
    est_evaluator_calls: int
    est_model_fits: int


@dataclass
class LedgerTotals:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    model_fit_count: int = 0
    evaluator_calls: int = 0
    full_eval_calls: int = 0
    cache_hits: int = 0
    by_stage: dict[str, dict[str, int]] = field(default_factory=dict)
    outstanding_evaluator_calls: int = 0
    outstanding_model_fits: int = 0
    outstanding_tokens: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "model_fit_count": self.model_fit_count,
            "evaluator_calls": self.evaluator_calls,
            "full_eval_calls": self.full_eval_calls,
            "cache_hits": self.cache_hits,
            "by_stage": self.by_stage,
            "outstanding_evaluator_calls": self.outstanding_evaluator_calls,
            "outstanding_model_fits": self.outstanding_model_fits,
            "outstanding_tokens": self.outstanding_tokens,
        }


class CostLedger:
    """In-memory cost ledger with optional full-eval cap."""

    def __init__(self, *, full_eval_cap: int | None = None) -> None:
        self._full_eval_cap = full_eval_cap
        self._seq = 0
        self._records: list[CostRecord] = []
        self._open: dict[str, Reservation] = {}

    def reserve(
        self,
        stage: Stage,
        *,
        est_tokens: int = 0,
        est_evaluator_calls: int = 0,
        est_model_fits: int = 0,
    ) -> Reservation:
        res = Reservation(
            id=uuid.uuid4().hex,
            stage=stage,
            est_tokens=est_tokens,
            est_evaluator_calls=est_evaluator_calls,
            est_model_fits=est_model_fits,
        )
        self._open[res.id] = res
        return res

    def settle(self, reservation: Reservation, record: CostRecord) -> CostRecord:
        self._open.pop(reservation.id, None)
        rec = CostRecord(
            seq=self._next_seq(),
            stage=record.stage,
            fidelity=record.fidelity,
            node_id=record.node_id,
            prompt_tokens=record.prompt_tokens,
            completion_tokens=record.completion_tokens,
            model_fit_count=record.model_fit_count,
            evaluator_calls=record.evaluator_calls,
            cpu_seconds=record.cpu_seconds,
            rss_peak_mb=record.rss_peak_mb,
            wall_s=record.wall_s,
            cache_hit=record.cache_hit,
            status=record.status,
            reservation_id=reservation.id,
            meta=record.meta,
        )
        self._records.append(rec)
        return rec

    def record(self, record: CostRecord) -> CostRecord:
        rec = CostRecord(
            seq=self._next_seq(),
            stage=record.stage,
            fidelity=record.fidelity,
            node_id=record.node_id,
            prompt_tokens=record.prompt_tokens,
            completion_tokens=record.completion_tokens,
            model_fit_count=record.model_fit_count,
            evaluator_calls=record.evaluator_calls,
            cpu_seconds=record.cpu_seconds,
            rss_peak_mb=record.rss_peak_mb,
            wall_s=record.wall_s,
            cache_hit=record.cache_hit,
            status=record.status,
            reservation_id=record.reservation_id,
            meta=record.meta,
        )
        self._records.append(rec)
        return rec

    def records(self) -> list[CostRecord]:
        return list(self._records)

    def totals(self) -> LedgerTotals:
        totals = LedgerTotals()
        by_stage: dict[str, dict[str, int]] = {}
        for rec in self._records:
            totals.prompt_tokens += rec.prompt_tokens
            totals.completion_tokens += rec.completion_tokens
            if rec.cache_hit:
                totals.cache_hits += 1
            else:
                totals.model_fit_count += rec.model_fit_count
                totals.evaluator_calls += rec.evaluator_calls
            if rec.stage == "full_eval" and rec.evaluator_calls > 0 and not rec.cache_hit:
                totals.full_eval_calls += rec.evaluator_calls
            bucket = by_stage.setdefault(rec.stage, {"count": 0, "evaluator_calls": 0, "model_fit_count": 0})
            bucket["count"] += 1
            bucket["evaluator_calls"] += rec.evaluator_calls
            bucket["model_fit_count"] += rec.model_fit_count
        for res in self._open.values():
            totals.outstanding_tokens += res.est_tokens
            totals.outstanding_evaluator_calls += res.est_evaluator_calls
            totals.outstanding_model_fits += res.est_model_fits
        totals.by_stage = by_stage
        return totals

    def would_exceed(self, *, full_evals: int = 0, tokens: int = 0) -> bool:
        if self._full_eval_cap is None:
            return False
        t = self.totals()
        projected = (
            t.full_eval_calls
            + t.outstanding_evaluator_calls
            + full_evals
        )
        return projected > self._full_eval_cap

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq
