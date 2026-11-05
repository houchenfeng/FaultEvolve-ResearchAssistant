"""Tests for discovery train/confirm splits."""

from __future__ import annotations

import numpy as np
import pandas as pd

from faultevolve.discovery.splits import assign_split, label_times, split_masks, temporal_halves
from faultevolve.discovery.tests_catalog import _temporal_stat


def test_assign_split_deterministic():
    a = assign_split("unit-1", "salt-a", 0.3)
    b = assign_split("unit-1", "salt-a", 0.3)
    assert a == b


def test_assign_split_salt_changes_assignment():
    diffs = 0
    for i in range(200):
        u = f"unit-{i}"
        if assign_split(u, "salt-one", 0.3) != assign_split(u, "salt-two", 0.3):
            diffs += 1
    assert diffs > 0


def test_confirm_fraction_in_range():
    salt = "fe-kd-test"
    n = 2000
    confirm = sum(
        1 for i in range(n) if assign_split(f"id-{i}", salt, 0.3) == "confirm"
    )
    frac = confirm / n
    assert 0.26 <= frac <= 0.34


def test_temporal_halves_partition():
    times = pd.Series([1, 1, 2, 2, 3, 3, 4, 4])
    first, second = temporal_halves(times)
    assert not (first & second).any()
    assert (first | second).all()


def test_temporal_halves_iso_date_strings():
    times = pd.Series(
        [
            "2020-01-01",
            "2020-01-01",
            "2020-06-01",
            "2020-06-01",
            "2020-12-31",
            "2020-12-31",
        ]
    )
    first, second = temporal_halves(times)
    assert set(times[first]) == {"2020-01-01", "2020-06-01"}
    assert set(times[second]) == {"2020-12-31"}


def test_label_times_from_env_when_labels_drop_date():
    labels = pd.DataFrame({"unit": ["a", "b", "c"], "label": [0, 1, 0]})
    env = pd.DataFrame({"time": ["2020-01-15", "2020-06-01", "2020-12-31"]})
    got = label_times(labels, "unit", "date", env_frame=env)
    assert got is not None
    assert list(got) == list(env["time"])


def test_label_times_from_history_when_labels_drop_date():
    labels = pd.DataFrame({"unit": ["a", "b"], "label": [0, 1]})
    history = pd.DataFrame(
        {
            "unit": ["a", "a", "b"],
            "date": ["2020-01-01", "2020-04-01", "2020-02-01"],
        }
    )
    got = label_times(labels, "unit", "date", history=history)
    assert got is not None
    assert list(got) == ["2020-04-01", "2020-02-01"]


def test_label_times_missing_returns_none():
    labels = pd.DataFrame({"unit": ["a"], "label": [0]})
    assert label_times(labels, "unit", "date") is None


def test_temporal_tournament_stat_accepts_iso_strings():
    times = np.array(
        [
            "2020-01-01",
            "2020-01-01",
            "2020-06-01",
            "2020-06-01",
            "2020-12-31",
            "2020-12-31",
        ]
    )
    x = np.linspace(-1, 1, len(times))
    y = np.array([0, 0, 1, 1, 0, 1])
    stat = _temporal_stat(x, y, times, "+")
    assert np.isfinite(stat)
