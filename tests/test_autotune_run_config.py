"""Regression tests for autotune full-run evolve.yaml."""

from pathlib import Path

from faultevolve.config import EvolveConfig

RUN_CFG = Path("docs/plans/autotune/run_full_hdd.evolve.yaml")


def test_run_full_hdd_config_loads():
    cfg = EvolveConfig.from_yaml(RUN_CFG)
    assert cfg.budget.max_tokens == 150000
    assert cfg.budget.max_iterations == 10
    assert cfg.autotune.ledger.enabled is True
    assert cfg.autotune.ledger.full_eval_cap == 24
    assert cfg.autotune.hpo.enabled is True
    assert cfg.autotune.patch.enabled is True
    assert cfg.autotune.quota.enabled is True
    assert cfg.autotune.quota.shares == {"hpo": 3, "patch": 5, "draft": 2}
    assert cfg.operators.bandit is False
    assert cfg.operators.crossover.enabled is False


def test_autotune_defaults_all_disabled():
    cfg = EvolveConfig()
    assert cfg.autotune.ledger.enabled is False
    assert cfg.autotune.hpo.enabled is False
    assert cfg.autotune.patch.enabled is False
    assert cfg.autotune.quota.enabled is False
    assert cfg.autotune.feedback.enabled is False
