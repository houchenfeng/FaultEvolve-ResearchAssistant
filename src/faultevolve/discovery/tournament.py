"""Data-adjudicated mechanism tournament."""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np
import pandas as pd

from faultevolve.cloud.store import Store
from faultevolve.config import DiscoveryConfig
from faultevolve.discovery.certificates import issue as issue_certificate
from faultevolve.discovery.icp import icp_check
from faultevolve.discovery.mechanisms import (
    FIXED_RIVALS,
    prediction_hash,
    propose_rivals,
    revise_mechanism,
)
from faultevolve.discovery.schemas import (
    Certificate,
    Claim,
    KD2Handoff,
    MatchResult,
    Mechanism,
    TournamentStats,
)
from faultevolve.discovery.seed_util import seed_from
from faultevolve.discovery.stats import e_from_p, ebh_reject
from faultevolve.discovery.tests_catalog import available_tests, derive_tests, run_test

FIXED_RIVAL_ROLES = set(FIXED_RIVALS)


class SliceReuseError(RuntimeError):
    pass


class DataBudgetLedger:
    def __init__(self, family_id: str) -> None:
        self.family_id = family_id
        self._used: dict[str, str] = {}

    def use(self, slice_id: str, purpose: str) -> None:
        if slice_id in self._used:
            raise SliceReuseError(f"slice {slice_id} reused in {self.family_id}")
        self._used[slice_id] = purpose

    def used(self) -> list[str]:
        return list(self._used.keys())

    def fresh(self, all_ids: list[str]) -> list[str]:
        return [s for s in all_ids if s not in self._used]


def slice_masks(
    unit_ids: np.ndarray,
    confirm_mask: np.ndarray,
    salt: str,
    n_slices: int,
) -> list[np.ndarray]:
    import hashlib

    masks = [np.zeros(len(unit_ids), dtype=bool) for _ in range(n_slices)]
    idx = np.where(confirm_mask)[0]
    for i in idx:
        h = int(hashlib.sha256(f"{salt}|kd2|{unit_ids[i]}".encode()).hexdigest(), 16)
        masks[h % n_slices][i] = True
    return masks


def elo_k(k0: float, e_raw: float, alpha: float) -> float:
    if e_raw <= 1.0:
        return 0.0
    return k0 * min(1.0, abs(math.log(e_raw)) / math.log(1 / alpha))


def elo_update(ra: float, rb: float, score_a: float, k: float) -> tuple[float, float]:
    ea = 1 / (1 + 10 ** ((rb - ra) / 400))
    ra_new = ra + k * (score_a - ea)
    rb_new = rb + k * ((1 - score_a) - (1 - ea))
    return ra_new, rb_new


def trunc_log_bf(log_e_signed: float) -> float:
    return float(np.clip(log_e_signed, math.log(0.1), math.log(10)))


@dataclass
class FamilyResult:
    mechanisms: list[Mechanism]
    matches: list[MatchResult]
    certificates: list[Certificate]
    elo: dict[str, float]
    family_id: str = ""
    prereg_hash: str = ""
    claim_id: str = ""


def swiss_pairs(
    mechs: list[Mechanism],
    elo: dict[str, float],
    played: set[frozenset[str]],
) -> list[tuple[str, str]]:
    claim_mech = next((m for m in mechs if m.role == "claim"), None)
    fixed = [m for m in mechs if m.role in FIXED_RIVAL_ROLES]
    ordered = sorted(mechs, key=lambda m: elo.get(m.id, 1500.0), reverse=True)
    pairs: list[tuple[str, str]] = []
    used: set[str] = set()

    if claim_mech:
        for fr in fixed:
            pair = frozenset((claim_mech.id, fr.id))
            if pair not in played:
                pairs.append((claim_mech.id, fr.id))

    i = 0
    while i < len(ordered):
        a = ordered[i]
        if a.id in used:
            i += 1
            continue
        j = i + 1
        while j < len(ordered):
            b = ordered[j]
            if b.id in used:
                j += 1
                continue
            pair = frozenset((a.id, b.id))
            if pair in played:
                j += 1
                continue
            pairs.append((a.id, b.id))
            used.add(a.id)
            used.add(b.id)
            break
        else:
            i += 1
            continue
        i += 1
    return pairs


class Tournament:
    def __init__(
        self,
        cfg: DiscoveryConfig,
        store: Store,
        experiment_id: str,
        llm_call: Callable[[list[dict[str, str]]], str],
        log_event: Callable[[str, dict], None],
        stats: TournamentStats,
    ) -> None:
        self.cfg = cfg
        self.tcfg = cfg.tournament
        self.store = store
        self.experiment_id = experiment_id
        self.llm_call = llm_call
        self.log_event = log_event
        self.stats = stats
        self._mech_by_id: dict[str, Mechanism] = {}
        self._pair_e: dict[tuple[str, str], float] = {}
        self._direct_e: dict[tuple[str, str], float] = {}

    def run_family(self, handoff: KD2Handoff, family_idx: int) -> FamilyResult:
        tcfg = self.tcfg
        claims = handoff.claims[: self.cfg.max_claims_per_round]
        if family_idx >= len(claims):
            return FamilyResult([], [], [], {})
        claim = claims[family_idx]
        family_id = f"F-{self.experiment_id}-{claim.id}"
        existing_roles = {
            row.get("role")
            for row in self.store.get_mechanisms(self.experiment_id)
            if row.get("family_id") == family_id
        }
        if existing_roles:
            return FamilyResult([], [], [], {})

        env_frame = handoff.env_frame
        ef = env_frame.copy() if env_frame is not None else None
        if ef is not None:
            ef = ef.copy()
            ef["y"] = handoff.y
        avail = available_tests(ef, tcfg.min_env_pos)
        if env_frame is None or not avail:
            self.stats.rounds_skipped += 1
            self.log_event("tournament_skipped", {"reason": "no_env", "family_id": family_id})
            return FamilyResult([], [], [], {})

        mechs = propose_rivals(
            claim,
            handoff.schema_note,
            self.llm_call,
            tcfg.max_rivals,
            self.experiment_id,
        )
        self.stats.mechanisms_proposed += len(mechs)
        for m in mechs:
            self._mech_by_id[m.id] = m
            self.store.create_mechanism(
                self.experiment_id,
                m.model_dump(),
                family_id,
            )

        prereg = prediction_hash(mechs)
        self.log_event("tournament_preregistered", {"family_id": family_id, "hash": prereg})

        slice_ids = [f"S{i}" for i in range(tcfg.n_slices)]
        masks = slice_masks(
            handoff.unit_ids,
            handoff.confirm_mask,
            self.cfg.split_salt,
            tcfg.n_slices,
        )
        ledger = DataBudgetLedger(family_id)
        elo = {m.id: 1500.0 for m in mechs}
        matches: list[MatchResult] = []
        certificates: list[Certificate] = []
        played: set[frozenset[str]] = set()
        mech_map = {m.id: m for m in mechs}

        for _round in range(tcfg.max_rounds):
            pairs = swiss_pairs(mechs, elo, played)
            for id_a, id_b in pairs:
                played.add(frozenset((id_a, id_b)))
                ma, mb = mech_map[id_a], mech_map[id_b]
                tests = derive_tests(ma, mb, avail)
                for test_type in tests:
                    fresh = ledger.fresh(slice_ids)
                    if not fresh:
                        self.log_event("tournament_no_fresh_slice", {"family_id": family_id})
                        break
                    sid = fresh[0]
                    ledger.use(sid, test_type)
                    sidx = int(sid[1:])
                    mask = masks[sidx]
                    x = handoff.feature_map[claim.id][mask]
                    y = handoff.y[mask]
                    g = handoff.groups[mask]
                    ef_slice = ef.loc[mask].reset_index(drop=True) if ef is not None else pd.DataFrame()
                    rng = np.random.default_rng(seed_from(family_id, sid, test_type))
                    stat, ci_lo, ci_hi, p_pos, p_null = run_test(
                        test_type,
                        x,
                        y,
                        g,
                        ef_slice,
                        self.cfg,
                        tcfg,
                        rng,
                        direction=claim.direction,
                    )
                    kappa = self.cfg.e_calibrator_kappa
                    alpha = self.cfg.alpha
                    thresh = 1 / alpha
                    pred_a = ma.predictions.get(test_type, -1)
                    pred_b = mb.predictions.get(test_type, -1)
                    e_pos = max(e_from_p(p_pos, kappa), 1.0)
                    e_null = max(e_from_p(p_null, kappa), 1.0)
                    supports: str = "none"
                    score_a = 0.5
                    decisive = False
                    e_eff = 1.0
                    log_bf = 0.0
                    min_det = None
                    if pred_a == 1 and e_pos >= thresh:
                        supports, score_a, decisive, e_eff, log_bf = "a", 1.0, True, e_pos, math.log(e_pos)
                    elif pred_b == 1 and e_pos >= thresh:
                        supports, score_a, decisive, e_eff, log_bf = "b", 0.0, True, e_pos, -math.log(e_pos)
                    elif pred_a == -1 and e_null >= thresh:
                        supports, score_a, decisive, e_eff, log_bf = "a", 1.0, True, e_null, math.log(e_null)
                    elif pred_b == -1 and e_null >= thresh:
                        supports, score_a, decisive, e_eff, log_bf = "b", 0.0, True, e_null, -math.log(e_null)
                    else:
                        self.stats.underpowered_draws += 1
                        se = float(np.std(
                            np.array([stat] * max(10, self.cfg.bootstrap_b // 50)),
                            ddof=1,
                        ))
                        min_det = 2.0 * se
                        self.stats.min_detectable_effects.append(min_det)

                    self.stats.matches_played += 1
                    if decisive:
                        self.stats.decisive_matches += 1
                    k = elo_k(tcfg.elo_k0, e_eff, alpha)
                    elo[id_a], elo[id_b] = elo_update(elo[id_a], elo[id_b], score_a, k)
                    key = (id_a, id_b) if id_a < id_b else (id_b, id_a)
                    prev = self._pair_e.get(key, 1.0)
                    if supports == "a":
                        self._pair_e[key] = prev * e_eff
                        dkey = (id_a, id_b)
                    elif supports == "b":
                        self._pair_e[key] = prev / max(e_eff, 1e-300)
                        dkey = (id_b, id_a)
                    else:
                        dkey = None
                    if dkey is not None:
                        self._direct_e[dkey] = self._direct_e.get(dkey, 1.0) * e_eff
                    mr = MatchResult(
                        mech_a=id_a,
                        mech_b=id_b,
                        test_type=test_type,
                        test_id=str(uuid.uuid4())[:8],
                        slice_id=sid,
                        stat=stat,
                        ci_low=ci_lo,
                        ci_high=ci_hi,
                        p=p_pos,
                        e_raw=e_eff,
                        log_bf_trunc=trunc_log_bf(log_bf),
                        supports=supports,
                        decisive=decisive,
                        min_detectable=min_det,
                    )
                    matches.append(mr)
                    mid = self.store.create_match(
                        self.experiment_id,
                        family_id,
                        _round,
                        id_a,
                        id_b,
                        sid,
                        mr.model_dump(),
                    )
                    self.store.create_test_result(mid, self.experiment_id, test_type, mr.model_dump())

        claim_m = mech_map[next(m.id for m in mechs if m.role == "claim")]
        x_confirm = handoff.feature_map[claim.id][handoff.confirm_mask]
        y_confirm = handoff.y[handoff.confirm_mask]
        env_confirm = (
            env_frame.loc[handoff.confirm_mask, "env"].to_numpy()
            if env_frame is not None and "env" in env_frame.columns
            else np.zeros(len(y_confirm))
        )
        icp_rng = np.random.default_rng(seed_from(family_id, "icp"))
        icp = icp_check(
            x_confirm,
            y_confirm,
            env_confirm,
            claim.direction,
            self.cfg.alpha,
            self.cfg.bootstrap_b,
            tcfg.icp_gate_p,
            tcfg.min_env_pos,
            icp_rng,
        )

        shuffled_rng = np.random.default_rng(seed_from(family_id, "shuffle"))
        self.stats.shuffled_env_trials += 1
        env_shuf = shuffled_rng.permutation(env_confirm)
        icp_shuf = icp_check(
            x_confirm,
            y_confirm,
            env_shuf,
            claim.direction,
            self.cfg.alpha,
            min(200, self.cfg.bootstrap_b),
            tcfg.icp_gate_p,
            tcfg.min_env_pos,
            shuffled_rng,
        )
        if icp_shuf.passed:
            self.stats.shuffled_env_false_pass += 1

        thresh = 1 / self.cfg.alpha
        rival_targets = [
            m for m in mechs if m.role in FIXED_RIVAL_ROLES or m.role == "llm_rival"
        ]
        e_vals = [
            self._direct_e.get((claim_m.id, r.id), 1.0) for r in rival_targets
        ]
        claim_refuted = any(
            self._direct_e.get((r.id, claim_m.id), 1.0) >= thresh for r in rival_targets
        )
        ebh_ok = all(ebh_reject(e_vals, self.cfg.alpha)) if e_vals else True
        claim_wins = True
        for r in rival_targets:
            if r.role == "other":
                continue
            e_fwd = self._direct_e.get((claim_m.id, r.id), 1.0)
            if e_fwd < thresh:
                claim_wins = False
                break
        claim_established = not claim_refuted and icp.passed and claim_wins and ebh_ok
        if claim_established:
            claim_m.status = "established"
            self.stats.mechanisms_established += 1
        elif claim_refuted:
            claim_m.status = "refuted"
            self.stats.mechanisms_refuted += 1
        else:
            claim_m.status = "undetermined"
        self.store.update_mechanism(claim_m.id, status=claim_m.status)

        for m in mechs:
            if m.role == "claim":
                mech_map[m.id] = claim_m
                continue
            if claim_established and m.role in FIXED_RIVAL_ROLES:
                m.status = "refuted"
                self.stats.mechanisms_refuted += 1
            elif (
                self._direct_e.get((m.id, claim_m.id), 1.0) >= thresh
                and m.role != "other"
            ):
                m.status = "established"
            else:
                m.status = "undetermined"
            self.store.update_mechanism(m.id, status=m.status)
            mech_map[m.id] = m

        for mr in matches:
            if not mr.decisive:
                continue
            if claim_m.id not in (mr.mech_a, mr.mech_b):
                continue
            rival_id = mr.mech_b if mr.mech_a == claim_m.id else mr.mech_a
            cert = issue_certificate(
                claim_m,
                mech_map[rival_id],
                mr,
                str(env_confirm[0]) if len(env_confirm) else "",
                prereg,
                claim.prereg_hash,
            )
            certificates.append(cert)
            self.stats.certificates_issued += 1
            self.store.create_certificate(
                self.experiment_id,
                claim_m.id,
                rival_id,
                cert.model_dump(),
            )

        return FamilyResult(mechs, matches, certificates, elo, family_id, prereg, claim.id)
