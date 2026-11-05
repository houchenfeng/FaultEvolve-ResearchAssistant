"""KD1-I hdd_v4 factor-library offline tests (no labels, no API)."""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

from faultevolve.discovery.factors import code_sha256, load_factor_library
from faultevolve.tasks.hdd_adapter import HDD_DISCOVERY_COLUMNS

REPO = Path(__file__).resolve().parents[1]
LIB_DIR = REPO / "src/faultevolve/discovery/factor_library"
V4 = LIB_DIR / "hdd_v4.jsonl"
CHECK = REPO / "skill/fe-knowledge-discovery/scripts/check_factor_library.py"
ORDER_IDS = {*(f"HDD4_F{i:02d}" for i in range(1, 19)), "HDD4_F21"}


def _entries(path: Path):
    return load_factor_library(path, max_candidates=30)


def _raw_entries(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _load_check_module():
    spec = importlib.util.spec_from_file_location("check_factor_library_v4", CHECK)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_v4_loads_count_ids_and_schema():
    entries = _entries(V4)
    old_ids = {
        row["factor_id"]
        for name in ("hdd_v1.jsonl", "hdd_v2.jsonl", "hdd_v3.jsonl")
        for row in _raw_entries(LIB_DIR / name)
    }
    assert len(entries) == 23
    assert len({e.factor_id for e in entries}) == 23
    assert all(e.factor_id.startswith("HDD4_") and e.factor_id not in old_ids for e in entries)
    for ent in entries:
        assert ent.scope == "train_labeled_units"
        assert ent.lane == ("control" if ent.factor_id.startswith("HDD4_C") else "confirm")
        assert ent.confirm_eligible is True
        assert ent.direction == ("+" if ent.factor_id.startswith("HDD4_C") else "auto")


def test_v4_inputs_and_code_hashes_are_new():
    allowed = set(HDD_DISCOVERY_COLUMNS) - {"serial_number"}
    old_hashes = {
        code_sha256(row["code"])
        for name in ("hdd_v1.jsonl", "hdd_v2.jsonl", "hdd_v3.jsonl")
        for row in _raw_entries(LIB_DIR / name)
    }
    hashes = [code_sha256(e.code) for e in _entries(V4)]
    assert len(hashes) == len(set(hashes))
    assert not old_hashes.intersection(hashes)
    assert all(col in allowed for e in _entries(V4) for col in e.inputs)


def test_default_library_remains_v1():
    text = (REPO / "src/faultevolve/cli.py").read_text(encoding="utf-8")
    assert 'Path("src/faultevolve/discovery/factor_library/hdd_v1.jsonl")' in text


def test_checker_synthetic_pass_fail_and_legacy_keys():
    mod = _load_check_module()
    history = pd.DataFrame(
        {
            "serial_number": ["A", "A", "B", "B"],
            "date": ["2024-01-01", "2024-01-02"] * 2,
            "smart_5_raw": [1.0, 2.0, 3.0, 4.0],
        }
    )
    units = pd.Index(["A", "B"])
    good = "import pandas as pd\n\ndef feature(history):\n return history.groupby('serial_number')['smart_5_raw'].last().astype(float)\n"
    bad = "import pandas as pd\n\ndef feature(history):\n return history.groupby('serial_number')['smart_5_raw'].apply(lambda x: 1.0)\n"
    row = mod.evaluate_row("TOY", "control", good, history, units, "serial_number", 30)
    assert row["ok"] is True
    assert "rhoK0" not in row and "order_sensitive" not in row
    assert mod.evaluate_row("TOY_BAD", "confirm", bad, history, units, "serial_number", 30)["ok"] is False


def test_order_sensitive_family_changes_under_nontrivial_permutation():
    mod = _load_check_module()
    sample_cols = pd.Index(
        [
            "smart_194_raw",
            "smart_193_raw",
            "smart_192_raw",
            "smart_7_raw",
            "smart_3_raw",
            "smart_4_raw",
            "smart_1_normalized",
            "smart_7_normalized",
            "smart_3_normalized",
        ]
    )
    history = mod._synthetic_order_history(sample_cols)
    permuted = mod._permute_values_within_units(history, "serial_number")
    units = pd.Index(["SYN_A", "SYN_B"])
    for ent in _entries(V4):
        if ent.factor_id not in ORDER_IDS:
            continue
        before, err = mod.raw_feature_series(ent.code, history, units, 30)
        after, err2 = mod.raw_feature_series(ent.code, permuted, units, 30)
        assert before is not None, err
        assert after is not None, err2
        assert not np.allclose(before, after, equal_nan=True), ent.factor_id

    std = next(e for e in _entries(LIB_DIR / "hdd_v3.jsonl") if e.factor_id == "HDD3_F12")
    std_history = mod._synthetic_order_history(pd.Index(["smart_193_raw"]))
    std_perm = mod._permute_values_within_units(std_history, "serial_number")
    before, _ = mod.raw_feature_series(std.code, std_history, pd.Index(["SYN_A", "SYN_B"]), 30)
    after, _ = mod.raw_feature_series(std.code, std_perm, pd.Index(["SYN_A", "SYN_B"]), 30)
    assert np.allclose(before, after, equal_nan=True)


def test_negative_control_seed_is_new():
    def seeds(path: Path) -> set[str]:
        return {
            m.group(1)
            for row in _raw_entries(path)
            for m in [re.search(r"default_rng\(([^)]+)\)", row["code"])]
            if m
        }

    current = seeds(V4)
    old = set().union(*(seeds(LIB_DIR / name) for name in ("hdd_v1.jsonl", "hdd_v2.jsonl", "hdd_v3.jsonl")))
    assert len(current) == 1
    assert current.isdisjoint(old)


def test_checker_source_does_not_read_outcomes():
    source = CHECK.read_text(encoding="utf-8")
    assert '["label"]' not in source
    assert "['label']" not in source
    assert '["weight"]' not in source
    assert "['weight']" not in source
