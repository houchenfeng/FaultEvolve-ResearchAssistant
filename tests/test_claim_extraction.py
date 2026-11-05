"""Tests for claim extraction and preregistration."""

from __future__ import annotations

import json

import pytest

from faultevolve.config import DiscoveryConfig
from faultevolve.discovery.claims import extract_claim_from_response, preregister
from faultevolve.discovery.schemas import Claim


def _valid_claim_dict() -> dict:
    return {
        "title": "t",
        "condition": "c",
        "feature_code": "def feature(history):\n    return history.groupby('unit')['m1'].last()",
        "outcome": "o",
        "direction": "+",
        "scope": "s",
        "falsifier": "f",
        "category": "feature_engineering",
        "tags": [],
    }


def test_extract_valid_claim():
    data = _valid_claim_dict()
    text = f"prefix\n<claim>{json.dumps(data)}</claim>\nsuffix"
    out = extract_claim_from_response(text)
    assert out is not None
    assert out["title"] == "t"


def test_extract_missing_feature_code():
    data = _valid_claim_dict()
    del data["feature_code"]
    text = f"<claim>{json.dumps(data)}</claim>"
    assert extract_claim_from_response(text) is None


def test_extract_non_json():
    assert extract_claim_from_response("<claim>not json</claim>") is None


def test_extract_no_tag():
    assert extract_claim_from_response("no claim here") is None


def test_extract_first_of_multiple():
    d1 = _valid_claim_dict()
    d1["title"] = "first"
    d2 = _valid_claim_dict()
    d2["title"] = "second"
    text = f"<claim>{json.dumps(d1)}</claim><claim>{json.dumps(d2)}</claim>"
    out = extract_claim_from_response(text)
    assert out is not None
    assert out["title"] == "first"


def test_extract_invalid_direction():
    data = _valid_claim_dict()
    data["direction"] = "up"
    text = f"<claim>{json.dumps(data)}</claim>"
    assert extract_claim_from_response(text) is None


def test_preregister_order_insensitive():
    cfg = DiscoveryConfig()
    base = Claim(source="insight", **_valid_claim_dict())
    h1 = preregister(base, cfg)
    reordered = Claim(
        source="insight",
        title=base.title,
        condition=base.condition,
        feature_code=base.feature_code,
        outcome=base.outcome,
        direction=base.direction,
        scope=base.scope,
        falsifier=base.falsifier,
    )
    assert preregister(reordered, cfg) == h1
    changed = base.model_copy(update={"condition": "changed condition"})
    assert preregister(changed, cfg) != h1
