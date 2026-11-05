"""Backblaze task directory and adapter integration tests."""

from __future__ import annotations

import hashlib
import importlib.util
import shutil
from pathlib import Path

import pytest

from faultevolve.cloud.engine import run_local_evolution
from faultevolve.config import EvolveConfig
from faultevolve.tasks.backblaze_adapter import BackblazeAdapter
from faultevolve.tasks.protocol import (
    DataStatusProvider,
    DiscoveryDataProvider,
    ErrorProfiler,
    EvalResult,
    ObjectiveBriefProvider,
    ObjectiveSpec,
    TaskAdapter,
)
from faultevolve.tasks.hdd_adapter import HDDAdapter
from tests.helpers_backblaze import make_tiny_raw
from tests.test_backblaze_prepare import _run_prepare

_REPO = Path(__file__).resolve().parents[1]
_HDD = _REPO / "benchmark/hdd_mvp"
_BB = _REPO / "benchmark/backblaze_hdd"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_bb_variant_evaluator_identical_to_hdd():
    for name in ("evaluator.py", "init.py", "prompt.md"):
        assert _sha(_BB / name) == _sha(_HDD / name)
    hdd_lines = (_HDD / "problem.md").read_text(encoding="utf-8").splitlines()
    bb_lines = (_BB / "problem.md").read_text(encoding="utf-8").splitlines()
    assert len(hdd_lines) == len(bb_lines)
    skip = {29, 30, 31, 56}
    for i, (a, b) in enumerate(zip(hdd_lines, bb_lines)):
        if i in skip:
            continue
        assert a == b


def test_bb_evolve_yaml_valid():
    cfg = EvolveConfig.from_yaml(_BB / "evolve.yaml")
    assert cfg.task.adapter == "backblaze"
    hdd_cfg = EvolveConfig.from_yaml(_HDD / "evolve.yaml")
    assert cfg.discovery.enabled == hdd_cfg.discovery.enabled
    assert cfg.analysis.enabled == hdd_cfg.analysis.enabled
    assert cfg.operators.bandit == hdd_cfg.operators.bandit
    assert cfg.judge.provider == hdd_cfg.judge.provider


def test_bb_knowledge_is_copy():
    assert (_BB / "knowledge/cards.jsonl").read_bytes() == (_HDD / "knowledge/cards.jsonl").read_bytes()
    assert _BB / "knowledge/cards.jsonl" != _HDD / "knowledge/cards.jsonl"


def test_bb_tiny_end_to_end_evaluator(tmp_path, monkeypatch):
    pytest.importorskip("duckdb")
    raw = tmp_path / "raw"
    out = tmp_path / "out"
    make_tiny_raw(raw, ["2024Q4", "2025Q1", "2025Q2"], n_fail=10, n_stay=20)
    _run_prepare(raw, out)
    monkeypatch.setenv("HDD_BENCH_DATA_ROOT", str(out))
    spec = importlib.util.spec_from_file_location("bb_eval", _BB / "evaluator.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(mod)
    result = mod.evaluate(str(_BB / "init.py"))
    assert result["validity"] == 1
    assert isinstance(result["combined_score"], float)
    assert "f1_p10" in result["metric"]
    st = BackblazeAdapter().data_status(_BB)
    assert st.ok


def test_bb_adapter_protocol():
    adapter = BackblazeAdapter()
    hdd = HDDAdapter(min_noise_delta=0.5, kappa=1.0)
    assert isinstance(adapter, TaskAdapter)
    assert isinstance(adapter, ObjectiveSpec)
    assert isinstance(adapter, ErrorProfiler)
    assert isinstance(adapter, ObjectiveBriefProvider)
    assert isinstance(adapter, DiscoveryDataProvider)
    assert isinstance(adapter, DataStatusProvider)
    ev = EvalResult(1.0, 1.0, 1.0, "", {"f1_boot_std": 0.2})
    assert adapter.get_noise_delta(ev) == hdd.get_noise_delta(ev)


def test_bb_mock_evolution_tiny(tmp_path):
    pytest.importorskip("duckdb")
    task = tmp_path / "task"
    shutil.copytree(_BB, task, ignore=shutil.ignore_patterns(".fe"))
    raw = tmp_path / "raw"
    make_tiny_raw(raw, ["2024Q4", "2025Q1", "2025Q2"], n_fail=8, n_stay=15)
    _run_prepare(raw, task / "data")
    runs = tmp_path / "runs"
    result = run_local_evolution(
        task_dir=task,
        mock=True,
        max_iterations=2,
        runs_dir=runs,
        artifacts_dir=runs / "artifacts",
    )
    assert "status" in result
