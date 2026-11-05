"""KD2 tournament unit tests (offline synthetic data)."""

from __future__ import annotations

import json
import math
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from faultevolve.cloud.llm import LLMTransientError
from faultevolve.cloud.store import Store
from faultevolve.config import DiscoveryConfig, TournamentConfig
from faultevolve.discovery.mechanisms import (
    FIXED_RIVALS,
    prediction_hash,
    propose_rivals,
    revise_mechanism,
)
from faultevolve.discovery.schemas import Claim, KD2Handoff, Mechanism, TournamentStats
from faultevolve.discovery.tests_catalog import available_tests, derive_tests
from faultevolve.discovery.tournament import (
    DataBudgetLedger,
    SliceReuseError,
    Tournament,
    elo_k,
    elo_update,
    slice_masks,
    swiss_pairs,
    trunc_log_bf,
)
from faultevolve.discovery.icp import icp_check


def _claim() -> Claim:
    return Claim(
        id="C-exp-0001",
        source="insight",
        title="x effect",
        condition="all",
        feature_code="def feature(h): pass",
        outcome="fail",
        direction="+",
        scope="train",
        falsifier="none",
        prereg_hash="h1",
    )


def test_planted_mechanism_wins_confound_loses(tmp_path):
    rng = np.random.default_rng(7)
    n = 6000
    env_ids = np.repeat(np.arange(4), n // 4)
    x = rng.normal(0, 1, n) + env_ids.astype(float) * 0.15
    logits = -1.2 + 1.3 * x
    y = (rng.random(n) < 1 / (1 + np.exp(-logits))).astype(int)
    unit_ids = np.array([f"u{i}" for i in range(n)])
    groups = unit_ids
    env_frame = pd.DataFrame({
        "env": env_ids.astype(str),
        "conf": env_ids.astype(str),
        "time": np.arange(n),
        "y": y,
    })
    claim = _claim()
    handoff = KD2Handoff(
        claims=[claim],
        payloads={claim.id: {}},
        feature_map={claim.id: x},
        y=y,
        groups=groups,
        unit_ids=unit_ids,
        confirm_mask=np.ones(n, dtype=bool),
        env_frame=env_frame.drop(columns=["y"]),
        schema_note="syn",
        round_idx=1,
    )
    cfg = DiscoveryConfig(
        enabled=True,
        alpha=0.2,
        bootstrap_b=250,
        tournament=TournamentConfig(
            enabled=True, n_slices=16, max_rounds=4, min_env_pos=5, icp_gate_p=0.05,
        ),
    )
    store = Store(tmp_path / "db.sqlite")
    events: list[tuple[str, dict]] = []

    def llm_call(msgs):
        return "<rivals>[]</rivals>"

    t = Tournament(cfg, store, "exp", llm_call, lambda t, p: events.append((t, p)), TournamentStats())
    fr = t.run_family(handoff, 0)
    claim_m = next(m for m in fr.mechanisms if m.role == "claim")
    assert claim_m.status == "established"
    conf = next(m for m in fr.mechanisms if m.role == "confound")
    art = next(m for m in fr.mechanisms if m.role == "artifact")
    assert conf.status == "refuted"
    assert art.status == "refuted"
    assert len(fr.certificates) >= 1
    assert t.stats.decisive_matches >= 1

    rng2 = np.random.default_rng(8)
    env_shift = rng2.normal(0, 2, 4)
    x2 = env_shift[env_ids] + rng2.normal(0, 1, n)
    y2 = (env_ids > 0).astype(int)
    handoff2 = KD2Handoff(
        claims=[claim],
        payloads={claim.id: {}},
        feature_map={claim.id: x2},
        y=y2,
        groups=groups,
        unit_ids=unit_ids,
        confirm_mask=np.ones(n, dtype=bool),
        env_frame=env_frame.drop(columns=["y"]),
        schema_note="syn",
        round_idx=1,
    )
    store2 = Store(tmp_path / "db2.sqlite")
    t2 = Tournament(cfg, store2, "exp", llm_call, lambda t, p: None, TournamentStats())
    fr2 = t2.run_family(handoff2, 0)
    claim2 = next(m for m in fr2.mechanisms if m.role == "claim")
    assert claim2.status != "established"


def test_icp_shuffled_env_rejects():
    passed = 0
    shuffled_rejected = 0
    for seed in range(20):
        rng = np.random.default_rng(seed)
        n = 3000
        env = np.repeat(np.arange(4), n // 4)
        x = rng.normal(0, 1, n) + env.astype(float) * 0.35
        logits = -2.0 + 0.8 * x
        y = (rng.random(n) < 1 / (1 + np.exp(-logits))).astype(int)
        real = icp_check(x, y, env.astype(str), "+", 0.05, 80, 0.05, 5, rng)
        if real.passed:
            passed += 1
        env_shuf = rng.permutation(env)
        shuf = icp_check(x, y, env_shuf.astype(str), "+", 0.05, 80, 0.05, 5, rng)
        if not shuf.passed and shuf.reason in {
            "env_uninformative",
            "sign_flip",
            "heterogeneous",
            "too_few_envs",
        }:
            shuffled_rejected += 1
    assert passed >= 18
    assert shuffled_rejected / 20 >= 0.9


def test_elo_k_formula():
    assert elo_k(32, math.e**3, 0.05) == pytest.approx(32 * min(1, 3 / math.log(20)))
    assert elo_k(32, math.exp(1.0), 0.05) == pytest.approx(32 * 1 / math.log(20))
    assert elo_k(32, 1.0, 0.05) == 0.0
    assert elo_update(1500, 1500, 1.0, 32) == (1516.0, 1484.0)
    assert trunc_log_bf(10) == pytest.approx(math.log(10))
    assert trunc_log_bf(-10) == pytest.approx(math.log(0.1))


def test_data_budget_ledger_rejects_reuse():
    led = DataBudgetLedger("F1")
    led.use("S0", "t")
    with pytest.raises(SliceReuseError):
        led.use("S0", "t2")
    DataBudgetLedger("F2").use("S0", "t")
    unit = np.array(["a", "b", "c", "d"])
    confirm = np.array([True, True, True, True])
    masks = slice_masks(unit, confirm, "salt", 2)
    assert not (masks[0] & masks[1]).any()
    assert (masks[0] | masks[1]).sum() == confirm.sum()


def test_fixed_rivals_always_present():
    claim = _claim()
    for resp in ["garbage", "<rivals>[]</rivals>", None]:
        def llm(msgs):
            if resp is None:
                raise LLMTransientError("x")
            return resp

        mechs = propose_rivals(claim, "note", llm, 2, "exp")
        roles = {m.role for m in mechs}
        assert roles >= {"claim", "confound", "artifact", "censor", "other"}
    mechs2 = propose_rivals(
        claim,
        "n",
        lambda m: "<rivals>" + json.dumps([{"title": f"r{i}"} for i in range(3)]) + "</rivals>",
        2,
        "exp",
    )
    assert sum(1 for m in mechs2 if m.role == "llm_rival") == 2
    claim_m = next(m for m in mechs2 if m.role == "claim")
    elo = {m.id: 1500.0 for m in mechs2}
    pairs = swiss_pairs(mechs2, elo, set())
    fixed_ids = {m.id for m in mechs2 if m.role in FIXED_RIVALS}
    for fid in fixed_ids:
        assert any(claim_m.id in p and fid in p for p in pairs)


def test_derive_tests_only_opposite_signs():
    a = Mechanism(
        id="a",
        claim_id="c",
        role="claim",
        title="a",
        predictions={"env_invariance": 1, "heterogeneity": -1, "temporal": 1, "dose_response": 1, "mediation": 1},
    )
    b = Mechanism(
        id="b",
        claim_id="c",
        role="confound",
        title="b",
        predictions={"env_invariance": -1, "heterogeneity": 1, "temporal": 1, "dose_response": 1, "mediation": -1},
    )
    avail = ["env_invariance", "heterogeneity", "dose_response"]
    assert derive_tests(a, b, avail) == ["env_invariance", "heterogeneity"]
    ef = pd.DataFrame({"conf": ["0"]})
    assert "env_invariance" not in available_tests(ef)


def test_prediction_hash_frozen():
    claim = _claim()
    mechs = propose_rivals(claim, "n", lambda m: "<rivals>[]</rivals>", 0, "e")
    h1 = prediction_hash(mechs)
    h2 = prediction_hash(mechs)
    assert h1 == h2
    mechs[0].predictions["temporal"] = -1
    assert prediction_hash(mechs) != h1
    rev = revise_mechanism(mechs[0], [], lambda m: '{"temporal": 1}', 2)
    assert rev is not None and rev.patch_count == 1
    assert revise_mechanism(rev, [], lambda m: "{}", 1) is None
