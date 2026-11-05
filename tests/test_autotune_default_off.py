"""Default-off compatibility for autotune features."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from faultevolve.config import EvolveConfig


def test_d1_ledger_defaults():
    cfg = EvolveConfig()
    assert cfg.autotune.ledger.enabled is False
    assert cfg.autotune.ledger.full_eval_cap is None


def test_d2_from_dict_roundtrip():
    raw = {"autotune": {"ledger": {"enabled": True, "full_eval_cap": 7}}}
    cfg = EvolveConfig.from_dict(raw)
    assert cfg.with_overrides(seed=1).autotune.ledger.full_eval_cap == 7


def test_d5_hpo_defaults_and_roundtrip():
    cfg = EvolveConfig()
    assert cfg.autotune.hpo.enabled is False
    assert cfg.autotune.cache.enabled is False
    data = {"autotune": {"hpo": {"trials_per_structure": 11}}}
    cfg2 = EvolveConfig.from_dict(data)
    assert cfg2.with_overrides().autotune.hpo.trials_per_structure == 11


def test_d7_hpo_requires_ledger():
    with pytest.raises(ValueError):
        EvolveConfig.from_dict({"autotune": {"hpo": {"enabled": True}}})


def test_d9_quota_roundtrip_and_bad_share_key():
    cfg = EvolveConfig.from_dict(
        {
            "autotune": {
                "patch": {"enabled": True, "max_hunks": 2},
                "quota": {"shares": {"hpo": 1, "patch": 1, "draft": 1}},
                "ablation": {"paired_resamples": 120},
                "ledger": {"enabled": True},
            }
        }
    )
    assert cfg.autotune.patch.max_hunks == 2
    assert cfg.autotune.ablation.paired_resamples == 120
    with pytest.raises(ValueError):
        EvolveConfig.from_dict(
            {"autotune": {"quota": {"shares": {"bad": 1, "patch": 1, "draft": 1}}}}
        )
