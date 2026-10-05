"""Claim grading (phenomenon layer)."""

from __future__ import annotations

from dataclasses import dataclass

from faultevolve.discovery.novelty import Entailment
from faultevolve.discovery.schemas import Grade

# KD2 hook: mechanism-level adjudication attaches after this module.

FDR_MODE_BH_EBH = "bh_ebh"
FDR_MODE_BH_CONFIRM_EBH_DISCOVER = "bh_for_confirm_ebh_for_discover"
VALID_FDR_MODES = frozenset({FDR_MODE_BH_EBH, FDR_MODE_BH_CONFIRM_EBH_DISCOVER})


@dataclass
class GradeInputs:
    ci_low: float
    ci_high: float
    direction_ok: bool
    temporal_ok: bool | None
    bh_pass: bool
    ebh_pass: bool
    functional_novel: bool
    entailment: Entailment
    controls_ok: bool


def grade_claim(
    inp: GradeInputs,
    fdr_mode: str = FDR_MODE_BH_EBH,
) -> tuple[Grade, str | None, str | None]:
    if fdr_mode not in VALID_FDR_MODES:
        raise ValueError(f"unsupported fdr_mode: {fdr_mode}")
    if inp.ci_low <= 0 <= inp.ci_high or not inp.direction_ok or inp.temporal_ok is False:
        return Grade.REFUTED, None, None
    if inp.temporal_ok is None or inp.entailment.relation == "unknown":
        return Grade.UNDETERMINED, None, None
    if fdr_mode == FDR_MODE_BH_EBH:
        if not (inp.bh_pass and inp.ebh_pass):
            return Grade.UNDETERMINED, None, None
    elif not inp.bh_pass:
        return Grade.UNDETERMINED, None, None
    if inp.entailment.relation == "same":
        return Grade.CONFIRMED, inp.entailment.card_id, None
    if inp.entailment.relation in {"opposite", "different_magnitude"}:
        return Grade.REVISED, None, inp.entailment.card_id
    if inp.entailment.relation == "none":
        if not inp.ebh_pass:
            return Grade.UNDETERMINED, None, None
        if inp.functional_novel and inp.controls_ok:
            return Grade.DISCOVERED, None, None
        return Grade.UNDETERMINED, None, None
    return Grade.UNDETERMINED, None, None
