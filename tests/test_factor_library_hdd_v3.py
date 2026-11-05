"""KD1-H hdd_v3 factor library offline tests (no labels, no API)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from faultevolve.discovery.factors import code_sha256, load_factor_library
from faultevolve.tasks.hdd_adapter import HDD_DISCOVERY_INPUT_COLUMNS

REPO = Path(__file__).resolve().parents[1]
V3 = REPO / "src/faultevolve/discovery/factor_library/hdd_v3.jsonl"
V1 = REPO / "src/faultevolve/discovery/factor_library/hdd_v1.jsonl"
V2 = REPO / "src/faultevolve/discovery/factor_library/hdd_v2.jsonl"
CENSUS = REPO / "skill/fe-knowledge-discovery/scripts/hdd_coverage_census.py"
CHECK = REPO / "skill/fe-knowledge-discovery/scripts/check_factor_library.py"

FORBIDDEN_OLD = {
    "HDD2_F001",
    "HDD2_F002",
    "HDD2_F007",
    "HDD2_F008",
    "HDD2_F009",
    "HDD2_F010",
    "HDD2_F012",
    "HDD2_F014",
    "HDD2_F020",
}

EXPECTED_LANES = {
    **{f"HDD3_F{i:02d}": ("confirm", True) for i in range(1, 17)},
    "HDD3_S01": ("confirm", True),
    "HDD3_S02": ("confirm", True),
    "HDD3_S03": ("confirm", True),
    "HDD3_D01": ("diagnostic", False),
    "HDD3_D02": ("diagnostic", False),
    "HDD3_D03": ("diagnostic", False),
    "HDD3_C01": ("control", True),
    "HDD3_C02": ("control", True),
}


def _prior_hashes() -> set[str]:
    out: set[str] = set()
    for path in (V1, V2):
        with path.open(encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    out.add(code_sha256(json.loads(line)["code"]))
    return out


def test_hdd_v3_loads_and_schema():
    entries = load_factor_library(
        V3, max_candidates=30, allowed_columns=HDD_DISCOVERY_INPUT_COLUMNS
    )
    assert len(entries) == 24
    for ent in entries:
        assert ent.factor_id.startswith("HDD3_")
        assert ent.factor_id not in FORBIDDEN_OLD
        assert "def feature(" in ent.code
        lane, confirm_eligible = EXPECTED_LANES[ent.factor_id]
        assert ent.lane == lane
        assert ent.confirm_eligible is confirm_eligible
        if ent.factor_id.startswith("HDD3_C"):
            assert ent.direction in {"+", "-"}
        else:
            assert ent.direction == "auto"


def test_hdd_v3_inputs_and_unique_code():
    allowed = set(HDD_DISCOVERY_INPUT_COLUMNS)
    prior = _prior_hashes()
    seen: set[str] = set()
    for ent in load_factor_library(V3, max_candidates=30, allowed_columns=HDD_DISCOVERY_INPUT_COLUMNS):
        for col in ent.inputs:
            assert col in allowed
        ch = code_sha256(ent.code)
        assert ch not in prior
        assert ch not in seen
        seen.add(ch)


def test_hdd_v3_subgroup_scope_text():
    scopes = {
        e.factor_id: e.scope
        for e in load_factor_library(V3, max_candidates=30, allowed_columns=HDD_DISCOVERY_INPUT_COLUMNS)
    }
    for fid in ("HDD3_S01", "HDD3_S02", "HDD3_S03"):
        text = scopes[fid].lower()
        assert "subgroup" in text
        assert "non-null" in text or "non null" in text.replace("-", " ")


def test_census_script_does_not_read_labels():
    src = CENSUS.read_text(encoding="utf-8")
    assert "read_csv(labels_path, usecols=usecols)" in src
    assert '("serial_number", "model", "cutoff_date")' in src
    assert "train_labels.csv" in src
    assert "FORBIDDEN_LABEL_COLS" in src


def test_check_script_synthetic_pass_and_fail(tmp_path: Path):
    import importlib.util

    spec = importlib.util.spec_from_file_location("check_factor_library", CHECK)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)

    history = __import__("pandas").DataFrame(
        {
            "serial_number": ["A", "A", "B", "B"],
            "date": ["2024-01-01", "2024-01-02", "2024-01-01", "2024-01-02"],
            "smart_5_raw": [1.0, 2.0, 3.0, 4.0],
        }
    )
    units = history["serial_number"].astype(str).unique()
    good_code = """
import pandas as pd

def feature(history):
    return history.groupby('serial_number')['smart_5_raw'].last().astype(float)
"""
    bad_code = """
import pandas as pd

def feature(history):
    return history.groupby('serial_number')['smart_5_raw'].apply(lambda _: 1.0)
"""
    ok_row = mod.evaluate_row("TOY_OK", "control", good_code, history, units, "serial_number", 30)
    bad_row = mod.evaluate_row("TOY_BAD", "confirm", bad_code, history, units, "serial_number", 30)
    assert ok_row["ok"] is True
    assert bad_row["ok"] is False


def test_default_factor_library_unchanged():
    text = (REPO / "src/faultevolve/cli.py").read_text(encoding="utf-8")
    assert "hdd_v1.jsonl" in text
    assert 'Path("src/faultevolve/discovery/factor_library/hdd_v1.jsonl")' in text
