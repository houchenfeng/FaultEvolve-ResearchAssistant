"""Factor library schema and loader tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from faultevolve.discovery.factors import FactorEntry, load_factor_library, propose_factors_llm
from faultevolve.tasks.hdd_adapter import HDD_DISCOVERY_INPUT_COLUMNS

REPO = Path(__file__).resolve().parents[1]
HDD_LIB = REPO / "src/faultevolve/discovery/factor_library/hdd_v1.jsonl"
TOY_LIB = REPO / "tests/fixtures/toy_factors.jsonl"


def test_hdd_factor_library_schema():
    # Shipped v1 is validated as on-disk JSONL (30 rows). Full load_factor_library
    # applies duplicate-hash and optional column contracts; CLI supplies columns separately.
    entries: list[FactorEntry] = []
    with HDD_LIB.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            entries.append(FactorEntry.from_dict(json.loads(line)))
    assert 20 <= len(entries) <= 30
    sources = {e.source for e in entries}
    assert "positive_control" in sources
    assert "negative_control" in sources
    for ent in entries:
        assert ent.factor_id
        assert ent.direction in {"+", "-"}
        assert "def feature(" in ent.code
        assert ent.title


def test_factor_jsonl_required_keys():
    required = {
        "factor_id",
        "family",
        "code",
        "direction",
        "title",
    }
    with HDD_LIB.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            data = json.loads(line)
            assert required.issubset(data.keys())


def test_loader_enforces_the_columns_it_is_handed(tmp_path):
    row = {
        "factor_id": "X1",
        "family": "t",
        "code": "def feature(history):\n    return history['not_a_column'].last()\n",
        "inputs": ["not_a_column"],
        "direction": "+",
        "title": "t",
    }
    path = tmp_path / "lib.jsonl"
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="not in the task's discovery columns"):
        load_factor_library(path, max_candidates=5, allowed_columns=HDD_DISCOVERY_INPUT_COLUMNS)
    assert load_factor_library(path, max_candidates=5)[0].factor_id == "X1"


def test_offline_proposal_needs_a_task_supplied_feature():
    with pytest.raises(ValueError, match="mock=True needs"):
        propose_factors_llm(lambda messages: "", "prompt", max_candidates=3, mock=True)
