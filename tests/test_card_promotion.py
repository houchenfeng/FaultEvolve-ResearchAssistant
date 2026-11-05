"""Tests for discovered card promotion."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

from faultevolve.discovery.promotion import promote_claims
from faultevolve.discovery.schemas import Claim, ControlReport, Grade
from faultevolve.knowledge.loader import load_all_cards, load_cards_from_dir, validate_card


def _controls(passed: bool = True) -> ControlReport:
    return ControlReport(
        neg_trials=100,
        neg_false_positives=5,
        neg_fpr=0.05,
        planted={},
        passed=passed,
    )


def _claim(**kwargs) -> Claim:
    base = Claim(
        id="C-exp-0001",
        experiment_id="exp1",
        origin_node_id="n1",
        source="insight",
        title="Title",
        condition="cond",
        feature_code="def feature(history):\n    return history.groupby('unit')['m1'].last()",
        outcome="Better recall",
        direction="+",
        scope="all units",
        falsifier="no lift",
        prereg_hash="abc123",
        grade=Grade.DISCOVERED,
    )
    return base.model_copy(update=kwargs) if kwargs else base


def _payload() -> dict:
    return {
        "effect": 0.12,
        "ci_low": 0.05,
        "ci_high": 0.18,
        "p": 0.001,
        "e": 50.0,
        "n": 200,
    }


def test_promoted_card_validates(tmp_path):
    cards_path = tmp_path / "discovered_cards.jsonl"
    promoted = promote_claims(
        [(_claim(), _payload())],
        _controls(),
        cards_path,
        "exp1",
        25.0,
    )
    assert len(promoted) == 1
    assert re.match(r"^D-exp1-\d{3}$", promoted[0]["id"])
    ok, err = validate_card(promoted[0])
    assert ok, err


def test_priority_and_metadata(tmp_path):
    cards_path = tmp_path / "discovered_cards.jsonl"
    disc = promote_claims([(_claim(grade=Grade.DISCOVERED), _payload())], _controls(), cards_path, "exp1", 0.0)
    rev = promote_claims(
        [(_claim(id="C2", prereg_hash="hash2", grade=Grade.REVISED), _payload())],
        _controls(),
        cards_path,
        "exp1",
        0.0,
    )
    assert disc[0]["priority"] == 2
    assert rev[0]["priority"] == 3
    assert disc[0]["evidence"] == "run"
    assert "数据驱动发现" in disc[0]["risk"]


def test_controls_failed_returns_empty(tmp_path):
    cards_path = tmp_path / "discovered_cards.jsonl"
    out = promote_claims([(_claim(), _payload())], _controls(passed=False), cards_path, "exp1", 0.0)
    assert out == []


def test_prereg_hash_dedup(tmp_path):
    cards_path = tmp_path / "discovered_cards.jsonl"
    item = (_claim(), _payload())
    first = promote_claims([item], _controls(), cards_path, "exp1", 0.0)
    second = promote_claims([item], _controls(), cards_path, "exp1", 0.0)
    assert len(first) == 1
    assert len(second) == 0


def test_id_conflict_increments(tmp_path):
    cards_path = tmp_path / "discovered_cards.jsonl"
    cards_path.write_text(
        json.dumps({"id": "D-exp1-001", "prereg_hash": "other"}) + "\n",
        encoding="utf-8",
    )
    promoted = promote_claims(
        [(_claim(prereg_hash="unique-hash"), _payload())],
        _controls(),
        cards_path,
        "exp1",
        0.0,
    )
    assert promoted[0]["id"] == "D-exp1-002"


def test_rejects_cards_jsonl(tmp_path):
    with pytest.raises(ValueError):
        promote_claims(
            [(_claim(), _payload())],
            _controls(),
            tmp_path / "cards.jsonl",
            "exp1",
            0.0,
        )


def test_benchmark_cards_sha256_unchanged(tmp_path):
    repo_cards = Path(__file__).resolve().parents[1] / "benchmark" / "hdd_mvp" / "knowledge" / "cards.jsonl"
    before = hashlib.sha256(repo_cards.read_bytes()).hexdigest()
    cards_path = tmp_path / "discovered_cards.jsonl"
    promote_claims([(_claim(), _payload())], _controls(), cards_path, "exp1", 0.0)
    after = hashlib.sha256(repo_cards.read_bytes()).hexdigest()
    assert before == after


def test_load_all_cards_with_discovered(tmp_path):
    lit_dir = tmp_path / "knowledge"
    lit_dir.mkdir()
    lit_cards = [
        {"id": "L1", "title": "Lit", "category": "model", "claim": "c", "source_ids": [], "tags": []},
        {"id": "L2", "title": "Lit2", "category": "model", "claim": "c", "source_ids": [], "tags": []},
    ]
    with (lit_dir / "cards.jsonl").open("w", encoding="utf-8") as f:
        for c in lit_cards:
            f.write(json.dumps(c) + "\n")
    discovered = tmp_path / "discovered_cards.jsonl"
    discovered.write_text(
        json.dumps(
            {
                "id": "D-exp-001",
                "title": "D",
                "category": "feature_engineering",
                "claim": "x",
                "source_ids": [],
                "tags": [],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    cards, errors = load_all_cards(lit_dir, [discovered])
    assert not errors
    assert len(cards) == 3

    dup = tmp_path / "dup.jsonl"
    dup.write_text(
        json.dumps(
            {
                "id": "L1",
                "title": "Dup",
                "category": "model",
                "claim": "c",
                "source_ids": [],
                "tags": [],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    _, errors2 = load_all_cards(lit_dir, [dup])
    assert any("Duplicate" in e for e in errors2)

    only_lit, err_lit = load_cards_from_dir(lit_dir)
    assert len(err_lit) == 0
    assert len(only_lit) == 2
