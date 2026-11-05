"""Table-driven tests for claim grading."""

from __future__ import annotations

import pytest

from faultevolve.discovery.grading import (
    FDR_MODE_BH_CONFIRM_EBH_DISCOVER,
    GradeInputs,
    grade_claim,
)
from faultevolve.discovery.novelty import Entailment
from faultevolve.discovery.schemas import Grade


def _inp(**kwargs) -> GradeInputs:
    base = dict(
        ci_low=0.05,
        ci_high=0.2,
        direction_ok=True,
        temporal_ok=True,
        bh_pass=True,
        ebh_pass=True,
        functional_novel=True,
        entailment=Entailment(relation="none"),
        controls_ok=True,
    )
    base.update(kwargs)
    return GradeInputs(**base)


def test_refuted_ci_crosses_zero():
    g, c, r = grade_claim(_inp(ci_low=-0.01, ci_high=0.05))
    assert g == Grade.REFUTED
    assert c is None and r is None


def test_refuted_temporal_false():
    g, _, _ = grade_claim(_inp(temporal_ok=False))
    assert g == Grade.REFUTED


def test_undetermined_temporal_none():
    g, _, _ = grade_claim(_inp(temporal_ok=None))
    assert g == Grade.UNDETERMINED


def test_undetermined_ebh_fail():
    g, _, _ = grade_claim(_inp(ebh_pass=False))
    assert g == Grade.UNDETERMINED


def test_relaxed_fdr_ebh_fail_can_still_confirm_same():
    g, confirms, _ = grade_claim(
        _inp(ebh_pass=False, entailment=Entailment(relation="same", card_id="FE01")),
        fdr_mode=FDR_MODE_BH_CONFIRM_EBH_DISCOVER,
    )
    assert g == Grade.CONFIRMED
    assert confirms == "FE01"


def test_confirmed_same():
    g, confirms, revises = grade_claim(
        _inp(entailment=Entailment(relation="same", card_id="FE01"))
    )
    assert g == Grade.CONFIRMED
    assert confirms == "FE01"
    assert revises is None


def test_revised_opposite():
    g, confirms, revises = grade_claim(
        _inp(entailment=Entailment(relation="opposite", card_id="FE02"))
    )
    assert g == Grade.REVISED
    assert revises == "FE02"
    assert confirms is None


def test_undetermined_none_without_controls():
    g, _, _ = grade_claim(
        _inp(entailment=Entailment(relation="none"), controls_ok=False)
    )
    assert g == Grade.UNDETERMINED


def test_undetermined_unknown_relation():
    g, _, _ = grade_claim(_inp(entailment=Entailment(relation="unknown")))
    assert g == Grade.UNDETERMINED


def test_discovered_none_functional_novel():
    g, _, _ = grade_claim(_inp(entailment=Entailment(relation="none")))
    assert g == Grade.DISCOVERED


@pytest.mark.parametrize(
    "relation,expected",
    [
        ("different_magnitude", Grade.REVISED),
        ("refuted_direction", Grade.REFUTED),
    ],
)
def test_grade_extra_cases(relation, expected):
    if relation == "different_magnitude":
        g, _, revises = grade_claim(
            _inp(entailment=Entailment(relation="different_magnitude", card_id="X"))
        )
        assert g == expected
        assert revises == "X"
    else:
        g, _, _ = grade_claim(_inp(direction_ok=False))
        assert g == expected
