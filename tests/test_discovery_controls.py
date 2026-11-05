"""Tests for discovery negative and planted controls."""

from __future__ import annotations

import numpy as np

from faultevolve.config import DiscoveryConfig
from faultevolve.discovery.controls import run_negative_controls, run_planted_controls
from faultevolve.worker.runner import FakeAdapter, FakeTaskSpec


def _synthetic_arrays(seed: int = 20260926):
    adapter = FakeAdapter()
    frames = adapter.discovery_frames(FakeTaskSpec(task_dir=__import__("pathlib").Path("/tmp")))
    labels = frames.labels
    y = labels[frames.label_col].to_numpy(dtype=int)
    groups = labels[frames.unit_col].astype(str).to_numpy()
    rng = np.random.default_rng(seed)
    features = {
        f"f{i}": rng.normal(0, 1, size=len(y)) for i in range(5)
    }
    return y, groups, features


def test_negative_control_fpr():
    cfg = DiscoveryConfig(neg_control_repeats=20, bootstrap_b=200)
    y, groups, features = _synthetic_arrays()
    fp, trials = run_negative_controls(
        features,
        y,
        groups,
        y,
        {k: "+" for k in features},
        cfg,
        seed=123,
    )
    assert trials == 20 * len(features)
    assert fp / trials <= 0.10


def test_planted_strong_recovery():
    cfg = DiscoveryConfig(bootstrap_b=200, neg_control_repeats=20)
    y, groups, _ = _synthetic_arrays()
    planted = run_planted_controls(
        y.astype(float),
        groups,
        cfg,
        seed=99,
        strengths=[1.0],
        repeats=20,
    )
    assert planted["1.0"]["rate"] >= 0.9


def test_zero_strength_not_discovered():
    cfg = DiscoveryConfig(bootstrap_b=200)
    y, groups, _ = _synthetic_arrays()
    planted = run_planted_controls(
        y.astype(float),
        groups,
        cfg,
        seed=77,
        strengths=[0.0],
        repeats=40,
    )
    assert planted["0.0"]["rate"] <= 0.15
