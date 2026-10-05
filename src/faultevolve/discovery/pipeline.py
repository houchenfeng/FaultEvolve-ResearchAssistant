"""Discovery round orchestration."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd

from faultevolve.cloud.store import Store
from faultevolve.config import DiscoveryConfig
from faultevolve.discovery.baseline_features import build_baseline_features
from faultevolve.discovery.claims import preregister, translate_claim
from faultevolve.discovery.controls import run_controls
from faultevolve.discovery.grading import (
    FDR_MODE_BH_EBH,
    GradeInputs,
    grade_claim,
)
from faultevolve.discovery.novelty import functional_novel, judge_entailment
from faultevolve.discovery.promotion import promote_claims
from faultevolve.discovery.sandbox import STDERR_TAIL_CHARS, run_feature
from faultevolve.discovery.schemas import Claim, ControlReport, DiscoveryStats, Grade, KD2Handoff
from faultevolve.discovery.funnel import FunnelRecord
from faultevolve.discovery.seed_util import seed_from
from faultevolve.discovery.splits import label_times, split_masks, temporal_halves
from faultevolve.discovery.stats import (
    bh_reject,
    e_from_p,
    ebh_reject,
    group_bootstrap_ci,
    incremental_auroc,
    max_abs_spearman,
    signed_effect,
    test_feature,
)
from faultevolve.knowledge.loader import load_all_cards
from faultevolve.tasks.protocol import DiscoveryDataProvider, TaskSpec

Candidate = tuple[Any, str, str, dict | None, str, dict | None]


@dataclass
class _ExplorePrepared:
    claim: Claim
    feat: np.ndarray
    rho_max_abs: float
    incr_gain: float
    incr_ci_low: float
    incr_ci_high: float
    factor_id: str
    comparison_index: int
    explore_effect: float
    explore_ci_low: float
    explore_ci_high: float
    coverage: float


def _impute_feature_matrix(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=float)
    miss = ~np.isfinite(x)
    med = float(np.nanmedian(x)) if np.any(np.isfinite(x)) else 0.0
    filled = np.where(np.isfinite(x), x, med)
    return np.column_stack([filled, miss.astype(float)])


EXPLORE_INCR_RULE_CI_LOW = "ci_low"
EXPLORE_INCR_RULE_POINT_GAIN = "point_gain"
VALID_EXPLORE_INCR_RULES = frozenset(
    {EXPLORE_INCR_RULE_CI_LOW, EXPLORE_INCR_RULE_POINT_GAIN}
)


def explore_increment_pass(
    incr_ci_low: float,
    incr_gain: float,
    rule: str,
    min_incr_ci_low: float = 0.0,
) -> bool:
    if rule == EXPLORE_INCR_RULE_POINT_GAIN:
        return incr_gain > 0
    return incr_ci_low > min_incr_ci_low


def _explore_detail(
    *,
    coverage: float,
    rho_max_abs: float,
    incr_gain: float,
    incr_ci_low: float,
    incr_ci_high: float,
    explore_effect: float,
    explore_ci: tuple[float, float],
    explore_sign: str,
    power_gate_pass: bool,
    lane: str,
    confirm_eligible: bool,
    explore_incr_rule: str = EXPLORE_INCR_RULE_CI_LOW,
    min_incr_ci_low: float = 0.0,
) -> dict[str, Any]:
    lo, hi = explore_ci
    return {
        "coverage": float(coverage),
        "rho_max_abs": float(rho_max_abs),
        "incr_gain": float(incr_gain),
        "incr_ci_low": float(incr_ci_low),
        "incr_ci_high": float(incr_ci_high),
        "explore_effect": float(explore_effect),
        "explore_ci_low": float(lo),
        "explore_ci_high": float(hi),
        "explore_sign": explore_sign,
        "power_gate_pass": bool(power_gate_pass),
        "lane": lane,
        "confirm_eligible": bool(confirm_eligible),
        "explore_incr_rule": explore_incr_rule,
        "min_incr_ci_low": float(min_incr_ci_low),
    }


def _grade_primary_failure(
    grade: Grade,
    inp: GradeInputs,
    ent: Any,
    fdr_mode: str = FDR_MODE_BH_EBH,
) -> str:
    if grade == Grade.REFUTED:
        if not inp.direction_ok:
            return "grade_refuted:direction"
        if inp.ci_low <= 0 <= inp.ci_high:
            return "grade_refuted:ci"
        if inp.temporal_ok is False:
            return "grade_refuted:temporal"
        return f"grade_{grade.value}"
    if grade == Grade.UNDETERMINED:
        if inp.temporal_ok is None:
            return "grade_undetermined:temporal_none"
        if ent.relation == "unknown":
            return "grade_undetermined:entailment_unknown"
        if not inp.bh_pass:
            return "grade_undetermined:bh"
        if not inp.ebh_pass:
            return "grade_undetermined:ebh"
        return f"grade_{grade.value}"
    return f"grade_{grade.value}"


def _origin_factor_id(origin: Any) -> str:
    text = str(origin)
    if text.startswith("factor:"):
        return text.split(":", 1)[1]
    return text


@dataclass
class RoundResult:
    promoted_ids: list[str]
    graded: list[dict]
    controls: ControlReport | None
    skipped_reason: str
    extras: dict


class DiscoveryRound:
    def __init__(
        self,
        cfg: DiscoveryConfig,
        store: Store,
        adapter: Any,
        task_spec: TaskSpec,
        experiment_id: str,
        card_path: Path,
        knowledge_dir: Path | None,
        llm_call: Callable[[list[dict[str, str]]], str],
        log_event: Callable[[str, dict], None],
        stats: DiscoveryStats,
        entailment_llm_call: Callable[[list[dict[str, str]]], str] | None = None,
    ) -> None:
        self.cfg = cfg
        self.store = store
        self.adapter = adapter
        self.task_spec = task_spec
        self.experiment_id = experiment_id
        self.card_path = card_path
        self.knowledge_dir = knowledge_dir
        self.llm_call = llm_call
        self.entailment_llm_call = entailment_llm_call or llm_call
        self.log_event = log_event
        self.stats = stats
        self._frames = None
        self.phenomena: list[dict] = []
        self.preregistrations: list[dict] = []
        self.controls_history: list[dict] = []
        self._claim_seq = store.max_claim_seq(experiment_id)

    def _insert_claim_with_retry(self, claim: Claim, round_idx: int) -> None:
        last_exc: sqlite3.IntegrityError | None = None
        for _attempt in range(5):
            try:
                self.store.create_claim(self.experiment_id, claim.model_dump(), round_idx)
                return
            except sqlite3.IntegrityError as exc:
                last_exc = exc
                if "UNIQUE constraint failed" not in str(exc):
                    raise
                self._claim_seq += 1
                claim.id = f"C-{self.experiment_id}-{self._claim_seq:04d}"
        raise RuntimeError(
            f"UNIQUE constraint failed: claim.id={claim.id} after 5 insert attempts"
        ) from last_exc

    def _is_claim_write_error(self, exc: BaseException) -> bool:
        if isinstance(exc, sqlite3.IntegrityError):
            return "UNIQUE constraint failed" in str(exc)
        msg = str(exc)
        return msg.startswith("UNIQUE constraint failed: claim.id=")

    def _record_llm_error(self, exc: Exception) -> None:
        self.stats.discovery_llm_errors += 1
        if self.stats.discovery_llm_error_first is None:
            self.stats.discovery_llm_error_first = str(exc)[:200]

    def _log_funnel(
        self,
        funnel_records: list[FunnelRecord] | None,
        factor_id: str,
        comparison_index: int,
        stage: str,
        primary_failure: str | None = None,
        detail: dict | None = None,
    ) -> None:
        if funnel_records is None:
            return
        funnel_records.append(
            FunnelRecord(
                factor_id=factor_id,
                comparison_index=comparison_index,
                stage_reached=stage,
                primary_failure=primary_failure,
                detail=detail or {},
            )
        )

    def run(
        self,
        round_idx: int,
        final: bool,
        candidates: list[Candidate],
        explore_gate_max_confirm: int | None = None,
        funnel_records: list[FunnelRecord] | None = None,
        coverage_min_explore: float = 0.30,
        min_explore_effect: float = 0.05,
        explore_only: bool = False,
        track_label: str = "",
        explore_incr_rule: str = EXPLORE_INCR_RULE_CI_LOW,
        min_incr_ci_low: float = 0.0,
        fdr_mode: str = FDR_MODE_BH_EBH,
    ) -> RoundResult:
        if explore_incr_rule not in VALID_EXPLORE_INCR_RULES:
            raise ValueError(f"unsupported explore_incr_rule: {explore_incr_rule}")
        try:
            if not isinstance(self.adapter, DiscoveryDataProvider):
                self.stats.rounds_skipped += 1
                self.log_event("discovery_skipped", {"reason": "no_provider"})
                return RoundResult([], [], None, "no_provider", {})
            if self.cfg.use_jev_entailment:
                self.log_event("discovery_jev_entailment_unavailable", {})
            self.log_event("discovery_round_started", {"round": round_idx, "final": final})
            if self._frames is None:
                self._frames = self.adapter.discovery_frames(self.task_spec)
            frames = self._frames
            labels = frames.labels
            if not isinstance(labels, pd.DataFrame):
                labels = pd.DataFrame(labels)
            unit_col = frames.unit_col
            label_col = frames.label_col
            y_all = labels[label_col].to_numpy(dtype=int)
            groups_all = labels[unit_col].astype(str).to_numpy()
            explore_mask, confirm_mask = split_masks(
                labels, unit_col, self.cfg.split_salt, self.cfg.confirmation_fraction,
            )
            baseline_df = build_baseline_features(
                frames.history,
                unit_col,
                frames.time_col,
                frames.baseline_cols,
                frames.baseline_lag_rows,
            )
            tested_claims: list[tuple[Claim, dict]] = []
            pvals: list[float] = []
            evals: list[float] = []
            feature_map: dict[str, np.ndarray] = {}
            direction_by_id: dict[str, str] = {}
            claim_ids: list[str] = []
            use_explore_gate = explore_gate_max_confirm is not None
            if not use_explore_gate:
              for origin, parent_code, child_code, insight, source, raw_claim in candidates[: self.cfg.max_claims_per_round]:
                try:
                    if raw_claim:
                        data = raw_claim
                        claim = Claim(
                            source=source,
                            title=str(data["title"]),
                            condition=str(data["condition"]),
                            feature_code=str(data["feature_code"]),
                            outcome=str(data["outcome"]),
                            direction=data["direction"],
                            scope=str(data["scope"]),
                            falsifier=str(data["falsifier"]),
                            category=str(data.get("category", "feature_engineering")),
                            tags=list(data.get("tags") or []),
                            origin_node_id=str(origin),
                        )
                    else:
                        claim = translate_claim(
                            parent_code,
                            child_code,
                            insight or {},
                            frames.schema_note,
                            self.llm_call,
                        )
                        if claim is None:
                            continue
                        claim.source = source  # type: ignore[assignment]
                        claim.origin_node_id = str(origin)
                    self._claim_seq += 1
                    claim.id = f"C-{self.experiment_id}-{self._claim_seq:04d}"
                    claim.experiment_id = self.experiment_id
                    claim.prereg_hash = preregister(claim, self.cfg)
                    self._insert_claim_with_retry(claim, round_idx)
                    self.stats.claims_proposed += 1
                    self.log_event("claim_proposed", {"claim_id": claim.id, "source": source})
                    self.preregistrations.append({"claim_id": claim.id, "hash": claim.prereg_hash})
                    t_sandbox = time.time()
                    sb = run_feature(
                        claim.feature_code,
                        frames.history,
                        unit_col,
                        groups_all,
                        self.cfg.sandbox_timeout_s,
                    )
                    if not sb.ok or sb.series is None:
                        self.stats.claims_sandbox_failed += 1
                        err_tail = (sb.error or "")[-STDERR_TAIL_CHARS:]
                        self.log_event(
                            "claim_sandbox_failed",
                            {
                                "claim_id": claim.id,
                                "error_type": sb.error_type or "SandboxFailure",
                                "error": err_tail,
                                "stage": "sandbox",
                                "duration_s": round(sb.duration_s, 3),
                            },
                        )
                        self.store.update_claim(
                            claim.id,
                            status="sandbox_failed",
                            payload_json=json.dumps({"error": sb.error}),
                        )
                        continue
                    self.log_event(
                        "claim_sandbox_finished",
                        {
                            "claim_id": claim.id,
                            "duration_s": round(time.time() - t_sandbox, 3),
                        },
                    )
                    feat = sb.series.reindex(labels[unit_col].astype(str)).to_numpy(dtype=float)
                    feature_map[claim.id] = feat
                    direction_by_id[claim.id] = claim.direction
                    claim_ids.append(claim.id)
                    # Seeded from the preregistration content, never from Python's
                    # str hash(): that one is PYTHONHASHSEED-randomised, which made
                    # the bootstrap CI, p-value and e-value irreproducible.
                    rng = np.random.default_rng(seed_from("claim_stats", claim.prereg_hash))
                    confirm_idx = confirm_mask
                    x_c = feat[confirm_idx]
                    y_c = y_all[confirm_idx]
                    g_c = groups_all[confirm_idx]
                    self.log_event("claim_stats_started", {"claim_id": claim.id})
                    t_stats = time.time()
                    res = test_feature(x_c, y_c, g_c, claim.direction, self.cfg, rng)
                    all_times = label_times(
                        labels,
                        unit_col,
                        frames.time_col,
                        getattr(frames, "env_frame", None),
                        frames.history if isinstance(frames.history, pd.DataFrame) else None,
                    )
                    if all_times is None or all_times.loc[confirm_idx].dropna().empty:
                        res.temporal_ok = None
                    else:
                        times = all_times.loc[confirm_idx].reset_index(drop=True)
                        first, second = temporal_halves(times)
                        if first.any() and second.any():
                            e1 = signed_effect(x_c[first], y_c[first])
                            e2 = signed_effect(x_c[second], y_c[second])
                            sign_ok = claim.direction == "+"
                            res.temporal_ok = bool(
                                (e1 > 0 and e2 > 0) if sign_ok else (e1 < 0 and e2 < 0)
                            )
                        else:
                            res.temporal_ok = None
                    explore_idx = explore_mask
                    x_e = feat[explore_idx]
                    base_e = baseline_df.reindex(labels.loc[explore_idx, unit_col].astype(str)).fillna(0)
                    y_e = y_all[explore_idx]
                    g_e = groups_all[explore_idx]
                    res.rho_max_abs = max_abs_spearman(x_e, base_e)
                    gain, ilo, ihi = incremental_auroc(
                        x_e, base_e, y_e, g_e, self.cfg.bootstrap_b, self.cfg.alpha, rng,
                    )
                    self.log_event(
                        "claim_stats_finished",
                        {"claim_id": claim.id, "duration_s": round(time.time() - t_stats, 3)},
                    )
                    res.incr_gain = gain
                    res.incr_ci_low = ilo
                    res.incr_ci_high = ihi
                    test_payload = res.model_dump(mode="json")
                    self.store.create_claim_test(
                        claim.id, self.experiment_id, "confirm", test_payload,
                    )
                    self.stats.claims_tested += 1
                    self.log_event("claim_tested", {"claim_id": claim.id})
                    pvals.append(res.p)
                    evals.append(res.e)
                    tested_claims.append((claim, test_payload))
                except Exception as exc:
                    if self._is_claim_write_error(exc):
                        self.log_event("claim_write_error", {"error": str(exc)[:200]})
                        raise
                    self._record_llm_error(exc)
                    self.log_event("discovery_llm_error", {"error": str(exc)[:200]})
                    continue
            if use_explore_gate:
                gate_out = self._run_explore_gated(
                    candidates,
                    round_idx,
                    frames,
                    labels,
                    unit_col,
                    label_col,
                    y_all,
                    groups_all,
                    explore_mask,
                    confirm_mask,
                    baseline_df,
                    int(explore_gate_max_confirm),
                    funnel_records,
                    coverage_min_explore,
                    min_explore_effect=min_explore_effect,
                    explore_only=explore_only,
                    explore_incr_rule=explore_incr_rule,
                    min_incr_ci_low=min_incr_ci_low,
                    track_label=track_label,
                )
                tested_claims = gate_out["tested_claims"]
                pvals = gate_out["pvals"]
                evals = gate_out["evals"]
                feature_map = gate_out["feature_map"]
                direction_by_id = gate_out["direction_by_id"]
                claim_ids = gate_out["claim_ids"]
                if explore_only:
                    return RoundResult([], [], None, "explore_only", {})
            if not tested_claims:
                return RoundResult([], [], None, "no_tests", {})
            bh = bh_reject(pvals, self.cfg.alpha)
            eb = ebh_reject(evals, self.cfg.alpha)
            # Unit-level labels: shuffle across all units (single stratum).
            neg_strata = np.zeros(len(y_all), dtype=int)
            controls = run_controls(
                feature_map,
                y_all,
                groups_all,
                neg_strata,
                direction_by_id,
                self.cfg,
                round_idx,
                claim_ids,
            )
            self.controls_history.append(controls.model_dump())
            self.log_event("discovery_controls", controls.model_dump())
            if not controls.passed:
                self.log_event("discovery_controls_failed", {"neg_fpr": controls.neg_fpr})
            cards, _ = load_all_cards(self.knowledge_dir, [])
            lit_cards = [c for c in cards if not c.id.startswith("D-")]
            m_tested = len(tested_claims)
            order_by_e = sorted(range(m_tested), key=lambda j: evals[j], reverse=True)
            ebh_required_by_idx: dict[int, float] = {}
            for rank, j in enumerate(order_by_e, start=1):
                ebh_required_by_idx[j] = m_tested / (rank * self.cfg.alpha)

            graded_items: list[tuple[Claim, dict]] = []
            for i, (claim, payload) in enumerate(tested_claims):
                ent = judge_entailment(claim, lit_cards, self.entailment_llm_call)
                self.log_event(
                    "claim_entailment",
                    {
                        "claim_id": claim.id,
                        "relation": ent.relation,
                        "card_id": ent.card_id,
                        "attempts": ent.attempts,
                        "reply_tail": (ent.reply_tail or "")[:200],
                    },
                )
                fn = functional_novel(
                    payload.get("rho_max_abs") or 0.0,
                    payload.get("incr_ci_low") or -1.0,
                    self.cfg,
                )
                inp = GradeInputs(
                    ci_low=payload["ci_low"],
                    ci_high=payload["ci_high"],
                    direction_ok=payload["direction_ok"],
                    temporal_ok=payload.get("temporal_ok"),
                    bh_pass=bh[i],
                    ebh_pass=eb[i],
                    functional_novel=fn,
                    entailment=ent,
                    controls_ok=controls.passed,
                )
                grade, confirms, revises = grade_claim(inp, fdr_mode=fdr_mode)
                claim.grade = grade
                claim.confirms = confirms
                claim.revises = revises
                claim.status = "graded"
                self.store.update_claim(
                    claim.id,
                    status="graded",
                    grade=grade.value,
                    payload_json=json.dumps({**payload, "grade": grade.value}),
                )
                self.log_event("claim_graded", {"claim_id": claim.id, "grade": grade.value})
                if funnel_records is not None and use_explore_gate:
                    fid = _origin_factor_id(claim.origin_node_id)
                    grade_detail = {
                        "bh_pass": bh[i],
                        "ebh_pass": eb[i],
                        "ebh_required_e": ebh_required_by_idx.get(i),
                        "e1": payload.get("e1"),
                        "e2": payload.get("e2"),
                        "temporal_ok": payload.get("temporal_ok"),
                        "relation": ent.relation,
                        "controls_ok": controls.passed,
                        "functional_novel": fn,
                    }
                    for rec in funnel_records:
                        if rec.factor_id == fid:
                            rec.detail.update(grade_detail)
                            if grade in {Grade.CONFIRMED, Grade.REVISED, Grade.DISCOVERED}:
                                rec.stage_reached = "discovered_or_confirmed"
                                rec.primary_failure = None
                            else:
                                rec.stage_reached = "confirmed_stats"
                                rec.primary_failure = _grade_primary_failure(
                                    grade, inp, ent, fdr_mode=fdr_mode
                                )
                            break
                if grade == Grade.CONFIRMED:
                    self.stats.confirmed += 1
                elif grade == Grade.REVISED:
                    self.stats.revised += 1
                elif grade == Grade.DISCOVERED:
                    self.stats.discovered += 1
                elif grade == Grade.REFUTED:
                    self.stats.refuted += 1
                else:
                    self.stats.undetermined += 1
                graded_items.append((claim, payload))
                self.phenomena.append({"claim_id": claim.id, "grade": grade.value, "payload": payload})
            promoted = promote_claims(
                graded_items,
                controls,
                self.card_path,
                self.experiment_id,
                0.0,
                frames.baseline_cols,
                log_event=self.log_event,
            )
            promoted_ids: list[str] = []
            for card in promoted:
                promoted_ids.append(card["id"])
                claim_id = card["source_ids"][-1].replace("claim:", "") if card.get("source_ids") else ""
                self.store.record_discovered_card(
                    card["id"], claim_id, self.experiment_id, card.get("grade", ""),
                )
                self.log_event("card_promoted", {"card_id": card["id"]})
                self.stats.cards_promoted += 1
            self.stats.neg_control_false_positives = controls.neg_false_positives
            self.stats.neg_control_trials = controls.neg_trials
            for k, v in controls.planted.items():
                self.stats.planted_trials[k] = int(v.get("trials", 0))
                self.stats.planted_recovered[k] = int(v.get("recovered", 0))
            extras: dict = {}
            if self.cfg.tournament.enabled and controls.passed:
                handoff_claims: list[Claim] = []
                payloads: dict[str, dict] = {}
                for claim, payload in graded_items:
                    if claim.grade not in {
                        Grade.CONFIRMED,
                        Grade.REVISED,
                        Grade.DISCOVERED,
                    }:
                        continue
                    handoff_claims.append(claim)
                    payloads[claim.id] = payload
                if handoff_claims:
                    extras["kd2"] = KD2Handoff(
                        claims=handoff_claims,
                        payloads=payloads,
                        feature_map=feature_map,
                        y=y_all,
                        groups=groups_all,
                        unit_ids=labels[unit_col].astype(str).to_numpy(),
                        confirm_mask=confirm_mask,
                        env_frame=getattr(frames, "env_frame", None),
                        schema_note=frames.schema_note,
                        round_idx=round_idx,
                    )
            return RoundResult(
                promoted_ids,
                [g for _, g in graded_items],
                controls,
                "",
                extras,
            )
        except Exception as exc:
            self.log_event("discovery_error", {"error": str(exc)[:300]})
            return RoundResult([], [], None, "error", {"error": str(exc)[:300]})

    def _run_explore_gated(
        self,
        candidates: list[Candidate],
        round_idx: int,
        frames: Any,
        labels: pd.DataFrame,
        unit_col: str,
        label_col: str,
        y_all: np.ndarray,
        groups_all: np.ndarray,
        explore_mask: np.ndarray,
        confirm_mask: np.ndarray,
        baseline_df: pd.DataFrame,
        max_confirm: int,
        funnel_records: list[FunnelRecord] | None,
        coverage_min_explore: float,
        min_explore_effect: float = 0.05,
        explore_only: bool = False,
        explore_incr_rule: str = EXPLORE_INCR_RULE_CI_LOW,
        min_incr_ci_low: float = 0.0,
        track_label: str = "",
    ) -> dict[str, Any]:
        tested_claims: list[tuple[Claim, dict]] = []
        pvals: list[float] = []
        evals: list[float] = []
        feature_map: dict[str, np.ndarray] = {}
        direction_by_id: dict[str, str] = {}
        claim_ids: list[str] = []
        seen_hashes: set[str] = set()
        explore_prepared: list[_ExplorePrepared] = []
        funnel_by_id: dict[str, FunnelRecord] = {}

        def touch(
            factor_id: str,
            comparison_index: int,
            stage: str,
            primary_failure: str | None = None,
            detail: dict | None = None,
        ) -> None:
            rec = funnel_by_id.get(factor_id)
            if rec is None:
                rec = FunnelRecord(
                    factor_id=factor_id,
                    comparison_index=comparison_index,
                    stage_reached=stage,
                    primary_failure=primary_failure,
                    detail=detail or {},
                )
                funnel_by_id[factor_id] = rec
            else:
                rec.stage_reached = stage
                if primary_failure is not None:
                    rec.primary_failure = primary_failure
                if detail:
                    rec.detail.update(detail)

        comparison_index = 0
        for origin, parent_code, child_code, insight, source, raw_claim in candidates[: self.cfg.max_claims_per_round]:
            comparison_index += 1
            factor_id = _origin_factor_id(origin)
            touch(factor_id, comparison_index, "proposed")
            try:
                entry_lane = "confirm"
                entry_confirm_eligible = True
                if raw_claim:
                    data = raw_claim
                    entry_lane = str(data.get("lane", "confirm"))
                    entry_confirm_eligible = bool(
                        data.get("confirm_eligible", entry_lane == "confirm")
                    )
                    claim = Claim(
                        source=source,
                        title=str(data["title"]),
                        condition=str(data["condition"]),
                        feature_code=str(data["feature_code"]),
                        outcome=str(data["outcome"]),
                        direction=data["direction"],
                        scope=str(data["scope"]),
                        falsifier=str(data["falsifier"]),
                        category=str(data.get("category", "feature_engineering")),
                        tags=list(data.get("tags") or []),
                        origin_node_id=str(origin),
                    )
                else:
                    claim = translate_claim(
                        parent_code,
                        child_code,
                        insight or {},
                        frames.schema_note,
                        self.llm_call,
                    )
                    if claim is None:
                        touch(factor_id, comparison_index, "proposed", "translate_failed")
                        continue
                    claim.source = source  # type: ignore[assignment]
                    claim.origin_node_id = str(origin)
                self._claim_seq += 1
                claim.id = f"C-{self.experiment_id}-{self._claim_seq:04d}"
                claim.experiment_id = self.experiment_id
                claim.prereg_hash = preregister(claim, self.cfg)
                self._insert_claim_with_retry(claim, round_idx)
                self.stats.claims_proposed += 1
                self.log_event("claim_proposed", {"claim_id": claim.id, "source": source})
                self.preregistrations.append({"claim_id": claim.id, "hash": claim.prereg_hash})
                sb = run_feature(
                    claim.feature_code,
                    frames.history,
                    unit_col,
                    groups_all,
                    self.cfg.sandbox_timeout_s,
                )
                if not sb.ok or sb.series is None:
                    self.stats.claims_sandbox_failed += 1
                    err_tail = (sb.error or "")[-STDERR_TAIL_CHARS:]
                    self.log_event(
                        "claim_sandbox_failed",
                        {
                            "claim_id": claim.id,
                            "error_type": sb.error_type or "SandboxFailure",
                            "error": err_tail,
                            "stage": "sandbox",
                            "duration_s": round(sb.duration_s, 3),
                        },
                    )
                    self.store.update_claim(
                        claim.id,
                        status="sandbox_failed",
                        payload_json=json.dumps({"error": sb.error}),
                    )
                    touch(factor_id, comparison_index, "proposed", "not_executable", {"error": err_tail[:120]})
                    continue
                touch(factor_id, comparison_index, "executable")
                feat = sb.series.reindex(labels[unit_col].astype(str)).to_numpy(dtype=float)
                explore_idx = explore_mask
                x_e = feat[explore_idx]
                cov = float(np.isfinite(x_e).mean()) if len(x_e) else 0.0
                if cov < coverage_min_explore:
                    touch(
                        factor_id,
                        comparison_index,
                        "executable",
                        "insufficient_coverage",
                        {"coverage": cov},
                    )
                    continue
                touch(factor_id, comparison_index, "coverage_ok")
                code_hash = hashlib.sha256(claim.feature_code.encode("utf-8")).hexdigest()
                if code_hash in seen_hashes:
                    touch(factor_id, comparison_index, "coverage_ok", "duplicate_code")
                    continue
                seen_hashes.add(code_hash)
                touch(factor_id, comparison_index, "deduped")
                lane = entry_lane
                confirm_eligible = entry_confirm_eligible
                rng = np.random.default_rng(seed_from("claim_stats", claim.prereg_hash))
                base_e = baseline_df.reindex(labels.loc[explore_idx, unit_col].astype(str)).fillna(0)
                y_e = y_all[explore_idx]
                g_e = groups_all[explore_idx]
                rho = max_abs_spearman(x_e, base_e)
                x_lr = _impute_feature_matrix(x_e)
                gain, ilo, ihi = incremental_auroc(
                    x_lr, base_e, y_e, g_e, self.cfg.bootstrap_b, self.cfg.alpha, rng,
                )
                marg_eff = signed_effect(x_e, y_e)
                exp_lo, exp_hi = group_bootstrap_ci(
                    x_e, y_e, g_e, self.cfg.bootstrap_b, self.cfg.alpha, rng,
                )
                explore_sign = "+" if marg_eff >= 0 else "-"
                ci_excludes_zero = bool(exp_lo > 0 or exp_hi < 0)
                incr_pass = explore_increment_pass(
                    ilo, gain, explore_incr_rule, min_incr_ci_low
                )
                power_pass = bool(
                    ilo > min_incr_ci_low
                    and abs(marg_eff) >= min_explore_effect
                    and ci_excludes_zero
                )
                detail = _explore_detail(
                    coverage=cov,
                    rho_max_abs=rho,
                    incr_gain=gain,
                    incr_ci_low=ilo,
                    incr_ci_high=ihi,
                    explore_effect=float(marg_eff),
                    explore_ci=(float(exp_lo), float(exp_hi)),
                    explore_sign=explore_sign,
                    power_gate_pass=power_pass,
                    lane=lane,
                    confirm_eligible=confirm_eligible,
                    explore_incr_rule=explore_incr_rule,
                    min_incr_ci_low=min_incr_ci_low,
                )
                if track_label:
                    detail["track_label"] = track_label
                if not incr_pass:
                    touch(
                        factor_id,
                        comparison_index,
                        "deduped",
                        "explore_no_increment",
                        detail,
                    )
                    continue
                touch(factor_id, comparison_index, "explore_incr", detail=detail)
                if lane == "diagnostic" or not confirm_eligible:
                    touch(
                        factor_id,
                        comparison_index,
                        "explore_incr",
                        "diagnostic_only",
                        detail,
                    )
                    continue
                if not power_pass:
                    touch(
                        factor_id,
                        comparison_index,
                        "explore_incr",
                        "explore_below_power_gate",
                        detail,
                    )
                    continue
                touch(factor_id, comparison_index, "power_gate", detail=detail)
                explore_prepared.append(
                    _ExplorePrepared(
                        claim=claim,
                        feat=feat,
                        rho_max_abs=rho,
                        incr_gain=gain,
                        incr_ci_low=ilo,
                        incr_ci_high=ihi,
                        factor_id=factor_id,
                        comparison_index=comparison_index,
                        explore_effect=float(marg_eff),
                        explore_ci_low=float(exp_lo),
                        explore_ci_high=float(exp_hi),
                        coverage=cov,
                    )
                )
            except Exception as exc:
                if self._is_claim_write_error(exc):
                    self.log_event(
                        "claim_write_error",
                        {"error": str(exc)[:200], "claim_id": getattr(claim, "id", "")},
                    )
                    touch(
                        factor_id,
                        comparison_index,
                        "proposed",
                        "claim_write_error",
                        {"error": str(exc)[:120]},
                    )
                    raise
                self._record_llm_error(exc)
                self.log_event("discovery_llm_error", {"error": str(exc)[:200]})
                touch(factor_id, comparison_index, "proposed", "discovery_llm_error", {"error": str(exc)[:120]})
                continue

        explore_prepared.sort(key=lambda p: p.incr_ci_low, reverse=True)
        frozen = explore_prepared[:max_confirm]
        for prep in explore_prepared[max_confirm:]:
            touch(
                prep.factor_id,
                prep.comparison_index,
                "power_gate",
                "not_selected_explore_gate",
                {"incr_ci_low": prep.incr_ci_low},
            )

        for prep in frozen:
            claim = prep.claim
            frozen_dir = claim.direction
            if claim.direction == "auto":
                frozen_dir = "+" if prep.explore_effect >= 0 else "-"
            claim.direction = frozen_dir  # type: ignore[assignment]
            claim.prereg_hash = preregister(claim, self.cfg)
            self.store.update_claim(
                claim.id,
                payload_json=json.dumps(claim.model_dump(mode="json")),
            )
            for pr in self.preregistrations:
                if pr.get("claim_id") == claim.id:
                    pr["hash"] = claim.prereg_hash
                    pr["direction_frozen"] = frozen_dir
            self.log_event(
                "claim_direction_frozen",
                {
                    "claim_id": claim.id,
                    "direction": frozen_dir,
                    "explore_effect": prep.explore_effect,
                    "explore_ci_low": prep.explore_ci_low,
                    "explore_ci_high": prep.explore_ci_high,
                    "prereg_hash": claim.prereg_hash,
                },
            )
            touch(
                prep.factor_id,
                prep.comparison_index,
                "frozen",
                detail={
                    "frozen_direction": frozen_dir,
                    "explore_effect": prep.explore_effect,
                    "prereg_hash": claim.prereg_hash,
                },
            )
            if explore_only:
                continue
            feat = prep.feat
            feature_map[claim.id] = feat
            direction_by_id[claim.id] = claim.direction
            claim_ids.append(claim.id)
            rng = np.random.default_rng(seed_from("claim_stats", claim.prereg_hash))
            confirm_idx = confirm_mask
            x_c = feat[confirm_idx]
            y_c = y_all[confirm_idx]
            g_c = groups_all[confirm_idx]
            self.log_event("claim_stats_started", {"claim_id": claim.id})
            t_stats = time.time()
            res = test_feature(x_c, y_c, g_c, claim.direction, self.cfg, rng)
            e1_val: float | None = None
            e2_val: float | None = None
            all_times = label_times(
                labels,
                unit_col,
                frames.time_col,
                getattr(frames, "env_frame", None),
                frames.history if isinstance(frames.history, pd.DataFrame) else None,
            )
            if all_times is None or all_times.loc[confirm_idx].dropna().empty:
                res.temporal_ok = None
            else:
                times = all_times.loc[confirm_idx].reset_index(drop=True)
                first, second = temporal_halves(times)
                if first.any() and second.any():
                    e1_val = signed_effect(x_c[first], y_c[first])
                    e2_val = signed_effect(x_c[second], y_c[second])
                    sign_ok = claim.direction == "+"
                    res.temporal_ok = bool(
                        (e1_val > 0 and e2_val > 0) if sign_ok else (e1_val < 0 and e2_val < 0)
                    )
                else:
                    res.temporal_ok = None
            res.rho_max_abs = prep.rho_max_abs
            res.incr_gain = prep.incr_gain
            res.incr_ci_low = prep.incr_ci_low
            res.incr_ci_high = prep.incr_ci_high
            self.log_event(
                "claim_stats_finished",
                {"claim_id": claim.id, "duration_s": round(time.time() - t_stats, 3)},
            )
            test_payload = res.model_dump(mode="json")
            test_payload["e1"] = e1_val
            test_payload["e2"] = e2_val
            self.store.create_claim_test(claim.id, self.experiment_id, "confirm", test_payload)
            self.stats.claims_tested += 1
            self.log_event("claim_tested", {"claim_id": claim.id})
            pvals.append(res.p)
            evals.append(res.e)
            tested_claims.append((claim, test_payload))
            touch(prep.factor_id, prep.comparison_index, "confirmed_stats")

        if funnel_records is not None:
            funnel_records.extend(funnel_by_id.values())

        return {
            "tested_claims": tested_claims,
            "pvals": pvals,
            "evals": evals,
            "feature_map": feature_map,
            "direction_by_id": direction_by_id,
            "claim_ids": claim_ids,
        }

    def write_artifacts(self, art_dir: Path) -> None:
        disc = art_dir / "discovery"
        disc.mkdir(parents=True, exist_ok=True)
        with (disc / "phenomena.json").open("w", encoding="utf-8") as f:
            json.dump(self.phenomena, f, indent=2, ensure_ascii=False)
        with (disc / "preregistration.json").open("w", encoding="utf-8") as f:
            json.dump(self.preregistrations, f, indent=2, ensure_ascii=False)
        with (disc / "controls.json").open("w", encoding="utf-8") as f:
            json.dump(self.controls_history, f, indent=2, ensure_ascii=False)
        snap = disc / "discovered_cards.snapshot.jsonl"
        if self.card_path.exists():
            snap.write_text(self.card_path.read_text(encoding="utf-8"), encoding="utf-8")
        else:
            snap.write_text("", encoding="utf-8")
