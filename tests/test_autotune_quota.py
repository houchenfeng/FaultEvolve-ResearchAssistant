"""Quota scheduler tests."""

import pytest

from faultevolve.optimization.quota import next_operator
from faultevolve.config import EvolveConfig


def test_q1_share_counts():
    shares = {"hpo": 3, "patch": 5, "draft": 2}
    counts: dict[str, int] = {"hpo": 0, "patch": 0, "draft": 0}
    seq = []
    for _ in range(100):
        slot = next_operator(counts, shares)
        counts[slot] += 1
        seq.append(slot)
    assert seq.count("hpo") == 30
    assert seq.count("patch") == 50
    assert seq.count("draft") == 20


def test_q2_quota_requires_no_bandit():
    with pytest.raises(ValueError):
        EvolveConfig(
            operators={"bandit": True, "enabled": ["refine"], "crossover": {"enabled": False}},
            autotune={"quota": {"enabled": True}, "ledger": {"enabled": True}},
        )
