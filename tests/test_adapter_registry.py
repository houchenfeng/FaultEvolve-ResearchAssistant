"""Task adapter registry and TaskConfig tests."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from faultevolve.config import EvolveConfig
from faultevolve.tasks import create_adapter, create_benchmark_adapter, resolve_adapter_class
from faultevolve.tasks.backblaze_adapter import BackblazeAdapter
from faultevolve.tasks.famou_adapter import FamouAdapter
from faultevolve.tasks.hdd_adapter import HDDAdapter
from faultevolve.tasks.smartmem_adapter import SmartMemAdapter
from faultevolve.tasks.ssd_alibaba_adapter import AlibabaSSDAdapter


def test_task_config_default_is_hdd():
    assert EvolveConfig().task.adapter == "hdd"
    assert EvolveConfig.from_dict({"task": {"adapter": "famou"}}).task.adapter == "famou"
    assert EvolveConfig().with_overrides(max_iterations=3).task.adapter == "hdd"


@pytest.mark.parametrize(
    ("alias", "cls"),
    [
        ("hdd", HDDAdapter),
        ("famou", FamouAdapter),
        ("backblaze", BackblazeAdapter),
        ("alibaba_ssd", AlibabaSSDAdapter),
        ("smartmem", SmartMemAdapter),
        ("faultevolve.tasks.famou_adapter:FamouAdapter", FamouAdapter),
    ],
)
def test_adapter_from_config(alias, cls):
    cfg = EvolveConfig.from_dict({"task": {"adapter": alias}})
    assert isinstance(create_adapter(cfg), cls)


def test_create_benchmark_adapter_default_unchanged():
    cfg = EvolveConfig()
    adapter = create_benchmark_adapter(cfg)
    assert isinstance(adapter, HDDAdapter)
    assert adapter.min_noise_delta == 0.5
    assert adapter.kappa == cfg.selection.kappa_noise
    assert adapter.dev_late_fraction == cfg.analysis.dev_late_fraction
    assert adapter.analysis_min_group_count == cfg.analysis.min_group_count

    cfg2 = EvolveConfig.from_dict({"selection": {"kappa_noise": 2.0}})
    adapter2 = create_benchmark_adapter(cfg2)
    assert adapter2.kappa == 2.0


def test_unknown_adapter_errors():
    for spec in ("nope", "a.b:C", "faultevolve.tasks.hdd_adapter:Nope"):
        with pytest.raises(ValueError, match="aliases"):
            resolve_adapter_class(spec)


def test_famou_adapter_receives_only_supported_kwargs():
    cfg = EvolveConfig.from_dict({"task": {"adapter": "famou"}, "selection": {"kappa_noise": 9.0}})
    adapter = create_adapter(cfg)
    assert isinstance(adapter, FamouAdapter)
    assert adapter.min_noise_delta == 0.5


def test_hdd_adapter_data_status_uses_env(tmp_path, monkeypatch):
    root = tmp_path / "data"
    pub = root / "public"
    pub.mkdir(parents=True)
    for name in (
        "train_history.csv.gz",
        "train_labels.csv",
        "val_history.csv.gz",
        "val_index.csv",
    ):
        (pub / name).write_bytes(b"")

    monkeypatch.setenv("HDD_BENCH_DATA_ROOT", str(root))
    adapter = HDDAdapter()
    status = adapter.data_status(Path("benchmark/hdd_mvp"))
    assert status.ok
    (pub / "val_index.csv").unlink()
    status2 = adapter.data_status(Path("benchmark/hdd_mvp"))
    assert not status2.ok
    assert "val_index.csv" in status2.missing
