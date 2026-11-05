"""Tests for configuration loading."""

import os
import tempfile
from pathlib import Path

import pytest
import yaml

from faultevolve.config import EvolveConfig, get_api_key, has_api_key


def test_default_config():
    """Test that default config has sensible values."""
    config = EvolveConfig()
    assert config.budget.max_iterations == 50
    assert config.budget.max_tokens == 3_000_000
    assert config.selection.c_puct == 1.2
    assert config.llm.temperature == 0.7
    assert config.seed == 20260926


def test_from_yaml():
    """Test loading config from YAML file."""
    yaml_content = """
budget:
  max_iterations: 100
  max_tokens: 5000000
selection:
  c_puct: 1.5
seed: 12345
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(yaml_content)
        yaml_path = Path(f.name)

    try:
        config = EvolveConfig.from_yaml(yaml_path)
        assert config.budget.max_iterations == 100
        assert config.budget.max_tokens == 5_000_000
        assert config.selection.c_puct == 1.5
        assert config.seed == 12345
        assert config.llm.temperature == 0.7
    finally:
        yaml_path.unlink()


def test_from_yaml_missing_file():
    """Test that missing YAML file returns default config."""
    config = EvolveConfig.from_yaml(Path("/nonexistent/path.yaml"))
    assert config.budget.max_iterations == 50


def test_with_overrides():
    """Test applying overrides to config."""
    config = EvolveConfig()
    new_config = config.with_overrides(
        max_iterations=200,
        target_score=35.0,
        seed=99999,
    )
    assert new_config.budget.max_iterations == 200
    assert new_config.stop.target_score == 35.0
    assert new_config.seed == 99999
    assert config.budget.max_iterations == 50


def test_api_key_not_present(monkeypatch):
    """Test API key detection when not set."""
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    assert not has_api_key("DASHSCOPE_API_KEY")
    assert get_api_key("DASHSCOPE_API_KEY") is None


def test_analysis_config_defaults_off():
    config = EvolveConfig.from_yaml(Path("/nonexistent/evolve.yaml"))
    assert config.analysis.enabled is False
    assert config.analysis.top_k == 3


def test_discovery_config_defaults_off():
    config = EvolveConfig()
    assert config.discovery.enabled is False
    assert config.discovery.every_n_iterations == 5
    assert config.discovery.run_at_end is True
    assert config.discovery.max_claims_per_round == 3
    assert config.discovery.split_salt == "fe-kd-2026"
    assert config.discovery.inject_same_run is True


def test_operators_config_defaults():
    config = EvolveConfig()
    assert config.operators.bandit is False
    assert config.operators.min_explore == 0.1


def test_analysis_config_round_trip():
    yaml_content = """
analysis:
  enabled: true
  top_k: 5
  on_new_best: false
  dev_late_fraction: 0.35
  timeout_s: 120
  min_group_count: 15
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(yaml_content)
        yaml_path = Path(f.name)
    try:
        config = EvolveConfig.from_yaml(yaml_path)
        assert config.analysis.enabled is True
        assert config.analysis.top_k == 5
        assert config.analysis.on_new_best is False
        assert config.analysis.dev_late_fraction == 0.35
        assert config.analysis.timeout_s == 120
        assert config.analysis.min_group_count == 15
        round_trip = config.with_overrides(max_iterations=7)
        assert round_trip.analysis.top_k == 5
        assert round_trip.analysis.dev_late_fraction == 0.35
    finally:
        yaml_path.unlink()

    with pytest.raises(Exception):
        EvolveConfig.from_dict({"analysis": {"timeout_s": 901}})
    with pytest.raises(Exception):
        EvolveConfig.from_dict({"analysis": {"dev_late_fraction": 1.0}})
    with pytest.raises(Exception):
        EvolveConfig.from_dict({"analysis": {"min_group_count": 9}})


def test_api_key_present(monkeypatch):
    """Test API key detection when set."""
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key-value")
    assert has_api_key("DASHSCOPE_API_KEY")
    assert get_api_key("DASHSCOPE_API_KEY") == "test-key-value"


def test_api_key_empty(monkeypatch):
    """Test API key detection when set to empty string."""
    monkeypatch.setenv("DASHSCOPE_API_KEY", "")
    assert not has_api_key("DASHSCOPE_API_KEY")
