"""KD2 mechanism feedback, insights, operators."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from faultevolve.cloud.engine import EvolutionEngine
from faultevolve.cloud.insights import (
    MECHANISM_LAYER_HINT,
    LayeredReflector,
    LAYERED_REFLECTION_PROMPT,
    get_foreign_insights,
    record_mechanism_insight,
    update_insight_reputation,
)
from faultevolve.cloud.llm import MockLLM
from faultevolve.cloud.operators import OperatorContext, OperatorType, USER_MESSAGE_TEMPLATE, build_user_message
from faultevolve.cloud.store import Store
from faultevolve.common.schemas import (
    BranchMemory,
    EvaluationResult,
    HypothesisStatus,
    Node,
    NodeArtifact,
    NodeEvidence,
    NodeStatus,
)
from faultevolve.config import EvolveConfig
from faultevolve.discovery.mech_promotion import promote_mechanisms
from faultevolve.discovery.schemas import Claim, Mechanism
from faultevolve.knowledge.loader import load_all_cards
from faultevolve.worker.runner import FakeTaskSpec


def _node(branch: str = "b1") -> Node:
    return Node(
        id="n1",
        experiment_id="e1",
        branch_id=branch,
        artifact=NodeArtifact(code="# x"),
        evidence=NodeEvidence(
            evaluation=EvaluationResult(validity=1.0, combined_score=20.0, cost_time=1.0),
        ),
        status=NodeStatus.DONE,
    )


def test_refuted_mech_in_foreign_negatives(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    m = Mechanism(id="M1", claim_id="C1", role="claim", title="T")
    record_mechanism_insight(store, "e1", m, "origin", 2.0, "rival")
    node = _node("b1")
    pos, neg = get_foreign_insights(node, store, "e1")
    assert any(i["change_summary"].startswith("[MECH]") for i in neg)
    assert not any(i["change_summary"].startswith("[MECH]") for i in pos)
    ctx = OperatorContext(node, FakeTaskSpec())
    ctx.set_foreign_insights(pos, neg)
    msg = build_user_message(ctx)
    assert "[MECH]" in msg


def test_mechanism_layer_parse():
    llm = MockLLM()
    r_false = LayeredReflector(llm, "e", mechanism_layer=False)
    r_true = LayeredReflector(llm, "e", mechanism_layer=True)
    payload = json.dumps({"layer": "mechanism", "change_summary": "x", "mechanism": "m"})
    out_true = r_true._parse_reflection_json(payload, 0.0, 1.0)
    assert out_true["layer"] == "mechanism"
    out_false = r_false._parse_reflection_json(payload, 0.0, 1.0)
    assert out_false["layer"] == "design"
    base = LAYERED_REFLECTION_PROMPT.format(
        parent_score=1.0,
        parent_metric="{}",
        child_score=1.0,
        child_metric="{}",
        error_info="",
        diff="",
        intent="",
        hypothesis="",
    )
    assert MECHANISM_LAYER_HINT not in base


def test_update_insight_reputation_beta(tmp_path):
    import json
    from faultevolve.common.schemas import Insight
    from faultevolve.cloud.store import now_iso

    store = Store(tmp_path / "db.sqlite")
    ins = Insight(
        id="i1",
        origin_node="o",
        branch_id="b2",
        polarity=1,
        change_summary="a",
        alpha=1.0,
        beta=1.0,
        created_at=now_iso(),
    )
    store.create_insight(ins, "e1")
    update_insight_reputation("i1", True, store, "e1")
    row = store.get_insights_by_experiment("e1")[0]
    assert row.alpha == 2 and row.beta == 1
    update_insight_reputation("i1", False, store, "e1")
    row = store.get_insights_by_experiment("e1")[0]
    assert row.alpha == 2 and row.beta == 2
    update_insight_reputation("missing", True, store, "e1")
    node = _node()
    store.create_insight(
        Insight(
            id="hi",
            origin_node="o",
            branch_id="other",
            polarity=1,
            change_summary="hi",
            z_score=5.0,
            alpha=10.0,
            beta=1.0,
            created_at=now_iso(),
        ),
        "e1",
    )
    store.create_insight(
        Insight(
            id="lo",
            origin_node="o",
            branch_id="other",
            polarity=1,
            change_summary="lo",
            z_score=5.0,
            alpha=1.0,
            beta=10.0,
            created_at=now_iso(),
        ),
        "e1",
    )
    pos, _ = get_foreign_insights(node, store, "e1", use_reputation=True)
    assert pos[0]["id"] == "hi"
    pos2, _ = get_foreign_insights(node, store, "e1", use_reputation=False)
    assert pos2[0]["id"] in {"hi", "lo"}


def test_mechanism_context_section_empty_is_identical():
    node = _node()
    ctx = OperatorContext(node, FakeTaskSpec())
    base = build_user_message(ctx)
    ctx.set_mechanism_context([])
    assert build_user_message(ctx) == base
    assert "<mechanism_context>" not in base
    old_tpl = USER_MESSAGE_TEMPLATE.replace("{mechanism_context_section}", "")
    assert "{mechanism_context_section}" in USER_MESSAGE_TEMPLATE
    ctx.set_mechanism_context([{"title": "t", "certificates": 1, "text": "body"}])
    assert "<mechanism_context>" in build_user_message(ctx)


def test_established_mech_card_and_memory(tmp_path):
    claim = Claim(
        id="C1",
        title="t",
        condition="c",
        feature_code="code",
        outcome="o",
        direction="+",
        scope="s",
        falsifier="f",
        source="insight",
        prereg_hash="ph1",
    )
    m = Mechanism(id="M1", claim_id="C1", role="claim", title="mech", status="established")
    cards = tmp_path / "discovered_cards.jsonl"
    out = promote_mechanisms([m], {"C1": claim}, cards, "exp", None)
    assert out[0]["id"] == "D-exp-M001"
    assert out[0]["priority"] == 1
    assert promote_mechanisms([m], {"C1": claim}, cards, "exp", None) == []
    with pytest.raises(ValueError):
        promote_mechanisms([m], {"C1": claim}, tmp_path / "cards.jsonl", "exp", None)
    from faultevolve.knowledge.loader import load_cards

    loaded, _ = load_cards(cards)
    assert loaded[0].id == "D-exp-M001"


def test_hypothesis_status_backward_compat():
    assert HypothesisStatus("corroborated") == HypothesisStatus.CORROBORATED
