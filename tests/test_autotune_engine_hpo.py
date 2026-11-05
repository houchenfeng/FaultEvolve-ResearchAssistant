"""Engine integration tests for quota HPO slots."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from faultevolve.cloud.engine import EvolutionEngine, run_local_evolution
from faultevolve.cloud.llm import MockLLM
from faultevolve.cloud.store import Store
from faultevolve.common.schemas import OperatorType
from faultevolve.config import EvolveConfig
from faultevolve.worker.runner import FakeAdapter, FakeTaskSpec
from tests.helpers_autotune import make_synthetic_hdd

BENCHMARK = Path("benchmark/hdd_mvp")


def _hpo_task(tmp_path: Path) -> Path:
    task = tmp_path / "task"
    task.mkdir()
    for name in ("evaluator.py", "init.py", "problem.md", "prompt.md"):
        shutil.copy(BENCHMARK / name, task / name)
    make_synthetic_hdd(task, n_serials=48, n_dates=6)
    return task


def _hpo_config() -> EvolveConfig:
    return EvolveConfig.from_dict(
        {
            "operators": {
                "bandit": False,
                "enabled": ["refine"],
                "crossover": {"enabled": False},
            },
            "budget": {"max_iterations": 3, "max_tokens": 200_000, "max_wall_hours": 1},
            "judge": {"provider": "none"},
            "discovery": {"enabled": False, "tournament": {"enabled": False}},
            "analysis": {"enabled": False},
            "autotune": {
                "ledger": {"enabled": True, "full_eval_cap": 30},
                "hpo": {
                    "enabled": True,
                    "families": ["logreg"],
                    "trials_per_structure": 3,
                    "max_fits_total": 24,
                    "promote_top_k": 1,
                },
                "quota": {"enabled": True, "shares": {"hpo": 10, "patch": 0, "draft": 1}},
            },
        }
    )


def _engine(tmp_path: Path, task_dir: Path, cfg: EvolveConfig, adapter: FakeAdapter) -> EvolutionEngine:
    runs = tmp_path / "runs"
    runs.mkdir()
    store = Store(runs / "fe.db")
    task_spec = FakeTaskSpec(
        task_dir=task_dir,
        problem_md=(task_dir / "problem.md").read_text(encoding="utf-8"),
        prompt_md=(task_dir / "prompt.md").read_text(encoding="utf-8"),
        init_code=(task_dir / "init.py").read_text(encoding="utf-8"),
    )
    eng = EvolutionEngine(
        cfg,
        adapter,
        task_spec,
        store,
        MockLLM(enable_repair_scenario=False),
        mock=True,
        task_dir=task_dir,
    )
    eng.artifacts_dir = runs / "art"
    eng.artifacts_dir.mkdir(parents=True, exist_ok=True)
    return eng


def test_hpo_quota_slot_creates_hpo_node(tmp_path):
    task = _hpo_task(tmp_path)
    cfg = _hpo_config()
    adapter = FakeAdapter()
    eng = _engine(tmp_path, task, cfg, adapter)
    eng.initialize()
    eng.run(2)
    hpo_nodes = [n for n in eng.tree.nodes.values() if n.operator == OperatorType.HPO]
    assert hpo_nodes, "expected at least one HPO child node"
    assert all(n.evidence.evaluation is not None for n in hpo_nodes)


def test_default_off_run_summary_keys_unchanged(tmp_path):
    task = tmp_path / "task"
    task.mkdir()
    (task / "init.py").write_text("# init\n", encoding="utf-8")
    (task / "problem.md").write_text("# p\n", encoding="utf-8")
    (task / "prompt.md").write_text("# p\n", encoding="utf-8")
    (task / "evaluator.py").write_text(
        "def evaluate(p, **kw):\n"
        "    return {'validity': 1, 'combined_score': 22, 'cost_time': 1, 'error_info': '', 'metric': {}}\n",
        encoding="utf-8",
    )
    runs = tmp_path / "runs"
    base = run_local_evolution(
        task_dir=task,
        mock=True,
        max_iterations=2,
        runs_dir=runs / "a",
        adapter=FakeAdapter(),
        seed=11,
    )
    hpo_runs = tmp_path / "runs_b"
    hpo_cfg = task / "hpo_off.yaml"
    hpo_cfg.write_text(
        "autotune:\n  quota: {enabled: false}\n  hpo: {enabled: false}\n",
        encoding="utf-8",
    )
    off = run_local_evolution(
        task_dir=task,
        mock=True,
        max_iterations=2,
        runs_dir=hpo_runs,
        adapter=FakeAdapter(),
        seed=11,
        config_path=hpo_cfg,
    )
    base_keys = set(json.loads((Path(base["output_dir"]) / "run_summary.json").read_text()).keys())
    off_keys = set(json.loads((Path(off["output_dir"]) / "run_summary.json").read_text()).keys())
    volatile = {
        "experiment_id",
        "wall_time_s",
        "total_eval_time_s",
        "total_llm_latency_ms",
        "iteration_events",
    }
    assert base_keys - volatile == off_keys - volatile


def test_hpo_dev_proxy_not_in_combined_score(tmp_path):
    task = _hpo_task(tmp_path)
    cfg = _hpo_config()
    fixed_score = 41.25
    adapter = FakeAdapter()
    adapter.set_results(
        [
            {"validity": 1.0, "combined_score": 22.0, "cost_time": 1.0, "metric": {}},
            {"validity": 1.0, "combined_score": fixed_score, "cost_time": 1.0, "metric": {}},
            {"validity": 1.0, "combined_score": fixed_score, "cost_time": 1.0, "metric": {}},
        ]
    )
    eng = _engine(tmp_path, task, cfg, adapter)
    eng.initialize()
    eng.run(2)
    hpo_nodes = [n for n in eng.tree.nodes.values() if n.operator == OperatorType.HPO]
    assert hpo_nodes
    node = hpo_nodes[0]
    assert node.evidence.evaluation is not None
    assert node.evidence.evaluation.combined_score == fixed_score
    promoted = [
        e
        for e in eng.store.get_events(eng.experiment_id)
        if e.type == "hpo_promoted"
    ]
    assert promoted
    for event in promoted:
        assert event.payload["dev_proxy"] != fixed_score
