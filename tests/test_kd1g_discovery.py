"""KD1-G discovery: auto direction, explore-only, library validation."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

from faultevolve.discovery.claims import preregister
from faultevolve.discovery.factors import load_factor_library
from faultevolve.discovery.pipeline import _impute_feature_matrix
from faultevolve.discovery.schemas import Claim
from faultevolve.config import DiscoveryConfig
from faultevolve.tasks.hdd_adapter import HDD_DISCOVERY_INPUT_COLUMNS
from typer.testing import CliRunner

from faultevolve.cli import app

REPO = Path(__file__).resolve().parents[1]


def test_hdd_v2_library_schema():
    lib = REPO / "src/faultevolve/discovery/factor_library/hdd_v2.jsonl"
    entries = load_factor_library(
        lib, max_candidates=30, allowed_columns=HDD_DISCOVERY_INPUT_COLUMNS
    )
    assert len(entries) == 27
    assert sum(1 for e in entries if e.lane == "diagnostic") == 4
    assert all(e.direction in {"+", "-", "auto"} for e in entries)


def test_load_factor_library_rejects_duplicate_hash(tmp_path):
    line = {
        "factor_id": "X1",
        "family": "t",
        "code": "def feature(history):\n    return history.groupby('serial_number')['smart_1_raw'].last()\n",
        "inputs": ["smart_1_raw"],
        "window_days": 14,
        "direction": "auto",
        "title": "t",
        "lane": "confirm",
    }
    path = tmp_path / "hdd_dup.jsonl"
    path.write_text(json.dumps(line) + "\n" + json.dumps({**line, "factor_id": "X2"}) + "\n")
    with pytest.raises(ValueError, match="duplicate"):
        load_factor_library(path, max_candidates=30)


def test_impute_feature_matrix_no_nan():
    x = np.array([1.0, np.nan, 3.0])
    m = _impute_feature_matrix(x)
    assert m.shape == (3, 2)
    assert np.isfinite(m).all()


def test_auto_direction_updates_prereg_hash():
    cfg = DiscoveryConfig(confirmation_fraction=0.5, bootstrap_b=50, alpha=0.05)
    claim = Claim(
        source="discover_op",
        title="t",
        condition="c",
        feature_code="code",
        outcome="failure",
        direction="auto",
        scope="all",
        falsifier="f",
    )
    h_auto = preregister(claim, cfg)
    claim.direction = "+"
    h_frozen = preregister(claim, cfg)
    assert h_auto != h_frozen


def test_explore_only_cli_no_confirm_tests(tmp_path):
    from faultevolve.cloud.engine import run_local_evolution
    from faultevolve.worker.runner import FakeAdapter
    from tests.test_cli_discover_factors import _task

    task = _task(tmp_path)
    adapter = FakeAdapter()
    adapter.set_results(
        [{"validity": 1.0, "combined_score": 22.0 + i, "cost_time": 1.0, "metric": {}} for i in range(4)]
    )
    runs = task / ".fe" / "runs"
    with patch("faultevolve.tasks.create_benchmark_adapter", return_value=adapter):
        evo = run_local_evolution(
            task_dir=task,
            mock=True,
            max_iterations=2,
            runs_dir=runs,
            adapter=adapter,
        )
    run_id = evo["experiment_id"]
    lib = REPO / "tests/fixtures/toy_factors.jsonl"
    runner = CliRunner()
    with patch("faultevolve.tasks.create_benchmark_adapter", return_value=adapter):
        res = runner.invoke(
            app,
            [
                "discover",
                "factors",
                str(task),
                "--run-id",
                run_id,
                "--mock",
                "--json",
                "--runs-dir",
                str(runs),
                "--library",
                str(lib),
                "--max-candidates",
                "3",
                "--max-confirm",
                "1",
                "--explore-only",
            ],
        )
    assert res.exit_code == 0
    payload = json.loads(res.stdout)
    assert payload["claims_tested"] == 0
    art = Path(payload["artifacts_dir"])
    audit = json.loads((art / "discovery" / "data_audit.json").read_text(encoding="utf-8"))
    assert audit["explore_only"] is True
