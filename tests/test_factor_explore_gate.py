"""Explore prescreen must not call confirm-set test_feature for all candidates."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from faultevolve.cloud.store import Store
from faultevolve.config import DiscoveryConfig, TournamentConfig
from faultevolve.discovery.factors import factors_to_candidates, load_factor_library
from faultevolve.discovery.pipeline import DiscoveryRound
from faultevolve.discovery.schemas import DiscoveryStats
from faultevolve.worker.runner import FakeAdapter
from faultevolve.cloud.engine import run_local_evolution


def test_explore_prescreen_limits_confirm_test_feature_calls(tmp_path: Path):
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
    (task / "evolve.yaml").write_text(
        "discovery:\n  enabled: true\n  bootstrap_b: 50\n  neg_control_repeats: 1\n",
        encoding="utf-8",
    )
    adapter = FakeAdapter()
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
    store = Store(runs / run_id / "fe.db")
    task_spec = adapter.load_task(task)

    cfg = DiscoveryConfig(
        enabled=True,
        max_claims_per_round=10,
        bootstrap_b=50,
        neg_control_repeats=1,
        planted_strengths=[0.5],
        sandbox_timeout_s=60,
        tournament=TournamentConfig(),
    )
    entries = load_factor_library(
        Path(__file__).resolve().parents[1] / "tests/fixtures/toy_factors.jsonl",
        max_candidates=10,
    )
    candidates = factors_to_candidates(entries)
    stats = DiscoveryStats()
    calls: list[str] = []

    def log_event(_type: str, _payload: dict) -> None:
        return None

    def llm_call(_msgs: list[dict[str, str]]) -> str:
        return ""

    kd = DiscoveryRound(
        cfg,
        store,
        adapter,
        task_spec,
        run_id,
        task / "cards.jsonl",
        None,
        llm_call,
        log_event,
        stats,
    )

    real_test = __import__(
        "faultevolve.discovery.stats", fromlist=["test_feature"]
    ).test_feature

    def spy_test_feature(x_c, y_c, g_c, direction, cfg, rng):
        calls.append("confirm")
        return real_test(x_c, y_c, g_c, direction, cfg, rng)

    with patch("faultevolve.discovery.pipeline.test_feature", side_effect=spy_test_feature):
        kd.run(
            1,
            True,
            candidates,
            explore_gate_max_confirm=2,
            funnel_records=[],
            coverage_min_explore=0.1,
        )

    assert calls, "expected confirm tests for frozen subset only"
    assert len(calls) <= 2
