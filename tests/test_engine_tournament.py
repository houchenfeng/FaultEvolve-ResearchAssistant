"""Engine integration tests for KD2 tournament."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from faultevolve.cli import app
from faultevolve.cloud.engine import EvolutionEngine, run_local_evolution
from faultevolve.cloud.store import Store
from faultevolve.config import EvolveConfig
from faultevolve.discovery.report import build_manifest, render_json, render_md, verify_md
from tests.test_engine_discovery import (
    ScriptedDiscoveryLLM,
    _discovery_config,
    _engine,
    _task_dir,
)


def test_tournament_disabled_zero_cost(tmp_path):
    llm = ScriptedDiscoveryLLM()
    cfg_a = _discovery_config()
    cfg_a.discovery.tournament.enabled = False
    cfg_a.seed = 11
    base = tmp_path / "a"
    base.mkdir(parents=True)
    s1 = _engine(base, cfg_a, llm).run(max_iterations=4)
    cfg_b = _discovery_config()
    cfg_b.discovery.tournament.enabled = False
    cfg_b.seed = 11
    (tmp_path / "b").mkdir(parents=True)
    s2 = _engine(tmp_path / "b", cfg_b, llm).run(max_iterations=4)
    assert s1.discovery_tokens == s2.discovery_tokens
    assert s1.best_score == s2.best_score
    assert s1.mechanism_tokens == 0
    assert s1.tournament_tokens == 0
    store = Store(base / "db" / "fe.db")
    assert store.get_mechanisms(s1.experiment_id) == []


def test_tournament_requires_discovery_config():
    cfg = EvolveConfig()
    cfg.discovery.enabled = False
    cfg.discovery.tournament.enabled = True
    with pytest.raises(ValueError, match="tournament requires discovery"):
        EvolveConfig.model_validate(cfg.model_dump())


def test_tournament_enabled_accounting(tmp_path):
    cfg = _discovery_config(tournament={"enabled": True, "max_rounds": 1})
    llm = ScriptedDiscoveryLLM()
    llm.chat_for_reasoning = _mech_llm_patch(llm.chat_for_reasoning)
    eng = _engine(tmp_path, cfg, llm)
    summary = eng.run(max_iterations=6)
    assert summary.mechanism_tokens == summary.tournament_tokens
    assert summary.total_tokens >= summary.mechanism_tokens
    store = Store(tmp_path / "db" / "fe.db")
    with store._conn() as conn:
        rows = conn.execute(
            "SELECT prompt_tokens, completion_tokens FROM llm_call WHERE purpose='mechanism'",
        ).fetchall()
    mech_tok = sum(int(r[0]) + int(r[1]) for r in rows)
    assert mech_tok == summary.mechanism_tokens


def _mech_llm_patch(orig):
    from faultevolve.common.metering import CallMetrics

    def wrapped(messages, temperature=0.2):
        text = messages[-1]["content"] if messages else ""
        if "KD_MECH" in text:
            return "<rivals>[]</rivals>", CallMetrics(10, 5, 1)
        return orig(messages, temperature)

    return wrapped


def test_report_numbers_match_manifest(tmp_path):
    cfg = _discovery_config()
    task = _task_dir(tmp_path)
    runs = tmp_path / "runs"
    off = run_local_evolution(task_dir=task, mock=True, max_iterations=3, runs_dir=runs)
    art = Path(off["output_dir"])
    manifest = build_manifest(art, off["experiment_id"])
    md = render_md(manifest)
    assert verify_md(md, manifest) == []
    md_bad = md.replace(str(int(manifest["numbers"]["total_tokens"])), "99999", 1)
    assert verify_md(md_bad, manifest) != []
    j = json.loads(render_json(manifest))
    rs = json.loads((art / "run_summary.json").read_text())
    for k, v in j["numbers"].items():
        if k in rs and rs[k] is not None:
            assert rs[k] == v or k.startswith("planted_recovery_rate")
    runner = CliRunner()
    r = runner.invoke(
        app,
        ["report", str(task), "--run-id", off["experiment_id"], "--json", "--runs-dir", str(runs)],
    )
    assert r.exit_code == 0
    json.loads(r.stdout)

    default_off = run_local_evolution(task_dir=task, mock=True, max_iterations=2)
    default_run = runner.invoke(
        app,
        ["report", str(task), "--run-id", default_off["experiment_id"], "--json"],
    )
    assert default_run.exit_code == 0
    json.loads(default_run.stdout)


def test_tournament_with_jev_deferred_and_resume(tmp_path):
    cfg = _discovery_config(tournament={"enabled": True, "max_rounds": 1})
    cfg.judge.provider = "mock"
    cfg.judge.prescreen = True
    cfg.judge.low_value_action = "defer"
    cfg.judge.defer_flush_evals = 1
    llm = ScriptedDiscoveryLLM()
    llm.chat_for_reasoning = _mech_llm_patch(llm.chat_for_reasoning)
    eng = _engine(tmp_path, cfg, llm)
    summary = eng.run(max_iterations=5)
    events = eng.store.get_events(summary.experiment_id)
    types = [e.type for e in events]
    assert "tournament_round_finished" in types or summary.mechanisms_proposed == 0
    eng2 = EvolutionEngine(
        cfg, eng.task_adapter, eng.task_spec, eng.store, llm, mock=True, task_dir=eng.task_dir,
    )
    eng2.initialize(resume_id=summary.experiment_id)
    eng2.run(max_iterations=2)
    assert eng2.metrics.iterations_done >= summary.iterations_done


def test_kd2_sources_task_agnostic():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "src" / "faultevolve" / "cloud"
    for name in ("insights.py", "operators.py"):
        text = (root / name).read_text(encoding="utf-8")
        for line in text.splitlines():
            if "MECH" in line or "mechanism" in line.lower():
                low = line.lower()
                assert not any(w in low for w in ("smart", "serial", "hdd", "vendor"))
