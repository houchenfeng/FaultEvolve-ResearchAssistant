"""Tests for functional novelty and entailment judging."""

from __future__ import annotations

import json

from faultevolve.config import DiscoveryConfig
from faultevolve.discovery.novelty import Entailment, functional_novel, judge_entailment
from faultevolve.discovery.schemas import Claim
from faultevolve.knowledge.loader import KnowledgeCard


def _claim() -> Claim:
    return Claim(
        source="insight",
        title="T",
        condition="C",
        feature_code="def feature(h):\n    return h['m1']",
        outcome="O",
        direction="+",
        scope="S",
        falsifier="F",
    )


def test_functional_novel_quadrants():
    cfg = DiscoveryConfig(rho_max=0.8)
    assert functional_novel(0.5, 0.1, cfg) is True
    assert functional_novel(0.5, -0.1, cfg) is False
    assert functional_novel(0.9, 0.1, cfg) is False
    assert functional_novel(0.9, -0.1, cfg) is False


def test_judge_entailment_valid_json():
    cards = [
        KnowledgeCard(
            id="FE01",
            title="Card",
            category="feature_engineering",
            claim="Does X",
            source_ids=[],
            tags=[],
        )
    ]

    def llm(_messages):
        return json.dumps({"card_id": "FE01", "relation": "same"})

    ent = judge_entailment(_claim(), cards, llm)
    assert ent.relation == "same"
    assert ent.card_id == "FE01"


def test_judge_entailment_invalid_json():
    def llm(_messages):
        return "not json at all"

    ent = judge_entailment(_claim(), [], llm)
    assert ent.relation == "unknown"


def test_judge_entailment_unknown_card_id():
    cards = [
        KnowledgeCard(
            id="FE01",
            title="Card",
            category="feature_engineering",
            claim="Does X",
            source_ids=[],
            tags=[],
        )
    ]

    def llm(_messages):
        return json.dumps({"card_id": "MISSING", "relation": "same"})

    ent = judge_entailment(_claim(), cards, llm)
    assert ent.relation == "unknown"
