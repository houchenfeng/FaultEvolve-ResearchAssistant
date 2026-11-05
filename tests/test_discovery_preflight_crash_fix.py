"""Regression tests for KD1-G preflight exit bugs (claim id collision, funnel JSON)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

from faultevolve.cloud.store import Store
from faultevolve.config import DiscoveryConfig, TournamentConfig
from faultevolve.discovery.factors import factors_to_candidates, load_factor_library
from faultevolve.discovery.funnel import FunnelRecord, json_native
from faultevolve.discovery.pipeline import DiscoveryRound, _explore_detail
from faultevolve.discovery.schemas import Claim, DiscoveryStats
from faultevolve.worker.runner import FakeAdapter
from faultevolve.cloud.engine import run_local_evolution


def _minimal_claim_payload(claim_id: str, experiment_id: str) -> dict:
    return {
        "id": claim_id,
        "experiment_id": experiment_id,
        "origin_node_id": "n0",
        "source": "seed",
        "title": "t",
        "condition": "c",
        "feature_code": "def feature(h): pass",
        "outcome": "failure",
        "direction": "+",
        "scope": "all",
        "falsifier": "f",
        "category": "feature_engineering",
        "tags": [],
        "status": "proposed",
        "prereg_hash": "abc",
    }


def test_max_claim_seq_ignores_unparseable_payload_and_gaps(tmp_path: Path):
    db = tmp_path / "fe.db"
    store = Store(db)
    exp = "gap-exp"
    store.create_claim(exp, _minimal_claim_payload("C-gap-exp-0001", exp), round_idx=0)
    store.create_claim(exp, _minimal_claim_payload("C-gap-exp-0003", exp), round_idx=0)
    with store._conn() as conn:
        conn.execute(
            """
            INSERT INTO claim (
                id, experiment_id, origin_node_id, source, round,
                payload_json, prereg_hash, status, grade, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            """,
            (
                "C-gap-exp-0005",
                exp,
                "",
                "broken",
                0,
                "{not-json",
                "",
                "proposed",
                None,
            ),
        )
    assert len(store.get_claims(exp)) == 2
    assert store.max_claim_seq(exp) == 5


def test_insert_claim_with_retry_avoids_id_gap_collision(tmp_path: Path):
    db = tmp_path / "fe.db"
    store = Store(db)
    exp = "retry-exp"
    store.create_claim(exp, _minimal_claim_payload("C-retry-exp-0001", exp), round_idx=0)
    store.create_claim(exp, _minimal_claim_payload("C-retry-exp-0003", exp), round_idx=0)
    cfg = DiscoveryConfig(
        enabled=True,
        max_claims_per_round=5,
        bootstrap_b=50,
        neg_control_repeats=1,
        planted_strengths=[0.5],
        sandbox_timeout_s=30,
        tournament=TournamentConfig(),
    )
    stats = DiscoveryStats()
    adapter = FakeAdapter()
    task = tmp_path / "task"
    task.mkdir()
    (task / "init.py").write_text("# x", encoding="utf-8")
    task_spec = adapter.load_task(task)

    kd = DiscoveryRound(
        cfg,
        store,
        adapter,
        task_spec,
        exp,
        task / "cards.jsonl",
        None,
        lambda _m: "",
        lambda _t, _p: None,
        stats,
    )
    assert kd._claim_seq == 3
    claim = Claim(
        source="discover_op",
        title="new",
        condition="c",
        feature_code="code",
        outcome="failure",
        direction="+",
        scope="all",
        falsifier="f",
    )
    kd._claim_seq += 1
    claim.id = f"C-{exp}-{kd._claim_seq:04d}"
    claim.experiment_id = exp
    from faultevolve.discovery.claims import preregister

    claim.prereg_hash = preregister(claim, cfg)
    kd._insert_claim_with_retry(claim, round_idx=1)
    assert claim.id == "C-retry-exp-0004"
    with store._conn() as conn:
        rows = conn.execute("SELECT id FROM claim WHERE experiment_id = ?", (exp,)).fetchall()
    ids = {r["id"] for r in rows}
    assert "C-retry-exp-0004" in ids
    assert stats.discovery_llm_errors == 0


def test_funnel_detail_numpy_serializes_to_complete_json(tmp_path: Path):
    detail = _explore_detail(
        coverage=0.9,
        rho_max_abs=0.1,
        incr_gain=0.02,
        incr_ci_low=0.01,
        incr_ci_high=0.03,
        explore_effect=0.06,
        explore_ci=(0.01, 0.02),
        explore_sign="+",
        power_gate_pass=np.bool_(True),
        lane="confirm",
        confirm_eligible=True,
    )
    rec = FunnelRecord(
        factor_id="F006",
        comparison_index=6,
        stage_reached="explore_incr",
        primary_failure="explore_below_power_gate",
        detail=detail,
    )
    payload = rec.to_dict()
    text = json.dumps(payload, default=json_native)
    loaded = json.loads(text)
    assert loaded["detail"]["power_gate_pass"] is True
    assert isinstance(loaded["detail"]["power_gate_pass"], bool)
    path = tmp_path / "funnel.json"
    path.write_text(text, encoding="utf-8")
    assert json.load(path.open(encoding="utf-8"))["detail"]["incr_ci_low"] == 0.01


def test_power_gate_fields_unchanged_after_native_cast():
    ilo = 0.00042
    marg_eff = 0.007236842580610636
    exp_lo = 0.00041983022631656157
    exp_hi = 0.05
    min_explore_effect = 0.05

    ci_numpy = np.bool_(exp_lo > 0 or exp_hi < 0)
    power_numpy = np.bool_(
        ilo > 0 and abs(marg_eff) >= min_explore_effect and ci_numpy
    )
    ci_py = bool(exp_lo > 0 or exp_hi < 0)
    power_py = bool(ilo > 0 and abs(marg_eff) >= min_explore_effect and ci_py)

    assert bool(power_numpy) == power_py
    assert bool(ci_numpy) == ci_py

    detail_numpy = _explore_detail(
        coverage=0.5,
        rho_max_abs=0.0,
        incr_gain=0.0,
        incr_ci_low=ilo,
        incr_ci_high=0.1,
        explore_effect=float(marg_eff),
        explore_ci=(float(exp_lo), float(exp_hi)),
        explore_sign="+",
        power_gate_pass=power_numpy,
        lane="confirm",
        confirm_eligible=True,
    )
    detail_py = _explore_detail(
        coverage=0.5,
        rho_max_abs=0.0,
        incr_gain=0.0,
        incr_ci_low=ilo,
        incr_ci_high=0.1,
        explore_effect=float(marg_eff),
        explore_ci=(float(exp_lo), float(exp_hi)),
        explore_sign="+",
        power_gate_pass=power_py,
        lane="confirm",
        confirm_eligible=True,
    )

    def funnel_view(detail: dict) -> dict:
        if detail["incr_ci_low"] <= 0:
            return {
                "power_gate_pass": detail["power_gate_pass"],
                "stage_reached": "deduped",
                "primary_failure": "explore_no_increment",
            }
        if not detail["power_gate_pass"]:
            return {
                "power_gate_pass": detail["power_gate_pass"],
                "stage_reached": "explore_incr",
                "primary_failure": "explore_below_power_gate",
            }
        return {
            "power_gate_pass": detail["power_gate_pass"],
            "stage_reached": "power_gate",
            "primary_failure": None,
        }

    assert funnel_view(detail_numpy) == funnel_view(detail_py)


def test_atomic_funnel_write_leaves_no_truncated_file_on_serialize_error(tmp_path: Path):
    from faultevolve.discovery import factors as factors_mod

    disc = tmp_path / "discovery"
    disc.mkdir()
    out = disc / "funnel.json"
    out.write_text('{"old": true}', encoding="utf-8")
    bad = [{"detail": {object(): 1}}]

    with pytest.raises(TypeError):
        factors_mod._write_json_atomic(out, bad)
    assert out.read_text(encoding="utf-8") == '{"old": true}'


def test_discover_factors_writes_error_txt_on_failure(tmp_path: Path):
    from typer.testing import CliRunner

    from faultevolve.cli import app

    task = tmp_path / "task"
    task.mkdir()
    (task / "init.py").write_text("# init", encoding="utf-8")
    (task / "problem.md").write_text("# p", encoding="utf-8")
    (task / "prompt.md").write_text("# pr", encoding="utf-8")
    (task / "evaluator.py").write_text(
        "def evaluate(p, **kw):\n"
        "    return {'validity': 1, 'combined_score': 22, 'cost_time': 1, 'error_info': '', 'metric': {}}\n",
        encoding="utf-8",
    )
    (task / "evolve.yaml").write_text("discovery:\n  enabled: true\n", encoding="utf-8")
    adapter = FakeAdapter()
    runs = task / ".fe" / "runs"
    with patch("faultevolve.tasks.create_benchmark_adapter", return_value=adapter):
        evo = run_local_evolution(
            task_dir=task,
            mock=True,
            max_iterations=1,
            runs_dir=runs,
            adapter=adapter,
        )
    run_id = evo["experiment_id"]
    art = tmp_path / "art"
    lib = tmp_path / "one.jsonl"
    # The task adapter owns the column contract, so a library handed to
    # ``discover factors`` for this task must name real columns: the toy fixture
    # (m0..m3) belongs to the toy task, and is rejected here on purpose.
    lib.write_text(
        json.dumps(
            {
                "factor_id": "TEST_F001",
                "family": "smoke",
                "code": (
                    "import pandas as pd\n\n"
                    "def feature(history):\n"
                    "    return history.groupby('serial_number')['smart_197_raw']"
                    ".last().astype(float)\n"
                ),
                "inputs": ["smart_197_raw"],
                "window_days": 14,
                "direction": "+",
                "source": "seed_library",
                "title": "smoke factor",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    runner = CliRunner()
    # The same adapter the run was made with: attaching the run database is a resume,
    # and a resume built on the real HDD adapter describes a different task, which is
    # refused before discovery is reached.
    with (
        patch("faultevolve.tasks.create_benchmark_adapter", return_value=adapter),
        patch(
            "faultevolve.discovery.factors.run_factor_discovery",
            side_effect=RuntimeError("synthetic boom"),
        ),
    ):
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
                "--artifacts-dir",
                str(art),
                "--library",
                str(lib),
                "--max-candidates",
                "3",
            ],
        )
    assert res.exit_code == 1
    err_path = art / run_id / "discovery" / "error.txt"
    assert err_path.is_file()
    body = err_path.read_text(encoding="utf-8")
    assert "synthetic boom" in body
    assert len(body) <= 200
