"""Goal stopping and durable research evidence use only local evaluator results."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError
from typer.testing import CliRunner

from faultevolve.cli import app
from faultevolve.cloud.engine import EvolutionEngine
from faultevolve.cloud.llm import MockLLM
from faultevolve.cloud.store import Store
from faultevolve.common.research import ResearchConfig, assess_goals
from faultevolve.config import EvolveConfig, IslandsConfig
from faultevolve.research import build_report, compare_reports, publish_report, run_research
from faultevolve.worker.runner import FakeAdapter, FakeTaskSpec


def goal_config(**changes):
    return ResearchConfig.model_validate({
        "domain": "hdd", "dataset_id": "synthetic-hdd-v1", "evidence_level": "synthetic",
        "evaluation_split": "val", "targets": [
            {"metric": "combined_score", "op": ">=", "value": 30},
            {"metric": "metric.recall", "op": ">=", "value": .6},
            {"metric": "metric.false_alarm_rate", "op": "<=", "value": .002},
        ], **changes,
    })


def result(score=35., recall=.7, far=.001, **changes):
    return {"validity": 1., "combined_score": score, "cost_time": .1, "error_info": "",
            "metric": {"recall": recall, "false_alarm_rate": far, "split": "val"}, **changes}


def config():
    value = EvolveConfig()
    value.islands = IslandsConfig.legacy_single()
    value.knowledge.enabled = False
    value.smoke_test.enabled = False
    value.operators.enabled = ["refine"]
    value.operators.bandit = False
    value.budget.max_iterations = 4
    value.stop.target_score = 1
    value.stop.stop_at_target = True
    value.research = goal_config()
    return value


def engine(tmp_path, evaluations, cfg=None, resume_id=None):
    task = tmp_path / "task"
    task.mkdir(exist_ok=True)
    (task / "evaluator.py").write_text("# local evaluator\n")
    spec = FakeTaskSpec(task_dir=task, evaluator_path=task / "evaluator.py", init_code="pass\n")
    adapter = FakeAdapter()
    adapter.set_results(evaluations)
    model = EvolutionEngine(config=cfg or config(), task_adapter=adapter, task_spec=spec,
                            store=Store(tmp_path / "fe.db"),
                            llm=MockLLM(enable_repair_scenario=False), mock=True)
    model.initialize(resume_id=resume_id)
    return model, adapter


@pytest.mark.parametrize("evaluation", [
    result(recall=.4), result(far=.02), result(validity=0.),
    result(metric={"split": "dev", "recall": .8, "false_alarm_rate": .001}),
    result(metric={"split": "val", "recall": float("nan"), "false_alarm_rate": .001}),
    result(metric={"split": "val", "recall": True, "false_alarm_rate": .001}),
    result(metric={"split": "val"}), result(score=float("inf")),
])
def test_missing_invalid_or_wrong_split_evidence_cannot_pass(evaluation):
    assert not assess_goals(goal_config(), evaluation)["achieved"]


def test_nested_metrics_and_lower_is_better_goals():
    goals = goal_config(targets=[{"metric": "metric.loss.mae", "op": "<=", "value": .2}])
    assert assess_goals(goals, result(metric={"split": "val", "loss": {"mae": .1}}))["achieved"]


def test_config_roundtrip_and_invalid_targets():
    cfg = config()
    assert EvolveConfig.from_dict(cfg.model_dump()).research == cfg.research
    with pytest.raises(ValidationError):
        goal_config(targets=[{"metric": "combined_score", "value": float("nan")}])
    with pytest.raises(ValidationError):
        goal_config(evaluation_split="test")
    with pytest.raises(ValidationError):
        goal_config(targets=[{"metric": "combined_score", "value": 1}] * 2)


def test_baseline_goal_stops_without_llm_spend(tmp_path):
    model, adapter = engine(tmp_path, [result()])
    summary = model.run()
    assert summary.stop_reason == "research_goal_reached"
    assert summary.iterations_done == 0
    assert model.store.get_llm_calls(model.experiment_id) == []
    report, _ = build_report(tmp_path / "fe.db", model.experiment_id)
    assert report["convergence"]["first_goal_round"] == 0


def test_all_constraints_apply_to_same_candidate_even_if_score_is_lower(tmp_path):
    model, adapter = engine(tmp_path, [result(score=20, recall=.3),
                                     result(score=50, recall=.9, far=.03), result(score=35)])
    summary = model.run()
    assert summary.iterations_done == 2
    assert summary.stop_reason == "research_goal_reached"
    report = publish_report(tmp_path / "fe.db", model.experiment_id)
    assert report["goal_achieved"]
    assert report["selected"]["combined_score"] == 35
    assert report["selected_node_id"] != report["highest_score_node_id"]
    assert report["baseline"]["combined_score"] == 20
    assert report["convergence"]["first_goal_round"] == 2
    assert report["automation"]["coverage"] is None
    assert report["complexity"]["parameter_count"] is None


def test_budget_stop_is_distinct_from_achievement(tmp_path):
    cfg = config()
    cfg.budget.max_iterations = 1
    model, _ = engine(tmp_path, [result(score=20), result(score=25)], cfg)
    summary = model.run()
    assert summary.stop_reason == "max_iterations"
    report, _ = build_report(tmp_path / "fe.db", model.experiment_id)
    assert not report["goal_achieved"]
    assert report["state"] == "stopped_without_goal"


def test_research_report_selects_jointly_feasible_hpo_instead_of_highest_scalar_score(tmp_path):
    cfg = config()
    cfg.budget.max_iterations = 1
    model, _ = engine(tmp_path, [result(score=20, recall=.3), result(score=25, recall=.4)], cfg)
    model.run()
    (tmp_path / "workflow-result.json").write_text(json.dumps({"completed_trials": 2, "best_score": 50.}))
    trials = []
    for candidate_id, evaluation in (("abc123", result(score=50, far=.03)), ("def456", result(score=35))):
        directory = tmp_path / "hyperparameters/runs" / candidate_id
        directory.mkdir(parents=True)
        (directory / "evaluation.json").write_text(json.dumps(evaluation))
        (directory / "candidate.py").write_text(f"# {candidate_id}\n")
        trials.append({"candidate_id": candidate_id})
    (tmp_path / "hyperparameters/ledger.json").write_text(json.dumps({"trials": trials}))
    report = publish_report(tmp_path / "fe.db", model.experiment_id)
    assert report["goal_achieved"]
    assert report["selected"]["combined_score"] == 35
    assert report["selected_node_id"] is None
    assert report["selected_candidate_id"] == "def456"
    assert report["convergence"]["first_goal_phase"] == "hyperparameters"
    assert report["workflow"]["best_score"] == 50
    assert (tmp_path / "research/best.py").read_text() == "# def456\n"


def test_resume_preserves_baseline_cost_and_first_goal(tmp_path):
    cfg = config()
    cfg.budget.max_iterations = 1
    model, _ = engine(tmp_path, [result(score=20), result(score=25)], cfg)
    model.run()
    before, _ = build_report(tmp_path / "fe.db", model.experiment_id)
    cfg.budget.max_iterations = 3
    resumed, _ = engine(tmp_path, [result(score=35)], cfg, model.experiment_id)
    resumed.run()
    after, _ = build_report(tmp_path / "fe.db", model.experiment_id)
    assert after["baseline"] == before["baseline"]
    assert after["cost"]["total_tokens"] > before["cost"]["total_tokens"]
    assert after["convergence"]["first_goal_round"] == 2
    cost = after["cost"]["total_tokens"]
    already_done, _ = engine(tmp_path, [], cfg, model.experiment_id)
    already_done.run()
    again, _ = build_report(tmp_path / "fe.db", model.experiment_id)
    assert again["convergence"]["first_goal_round"] == 2
    assert again["cost"]["total_tokens"] == cost


def test_resume_refuses_changed_acceptance_before_spending(tmp_path):
    cfg = config()
    model, _ = engine(tmp_path, [result()], cfg)
    model.run()
    cfg.research = goal_config(dataset_id="different-data")
    with pytest.raises(ValueError, match="契约"):
        engine(tmp_path, [], cfg, model.experiment_id)


@pytest.mark.parametrize("domain", ["hdd", "memory", "optical-amplifier"])
def test_same_engine_accepts_domain_specific_metric_contracts(tmp_path, domain):
    cfg = config()
    cfg.research = goal_config(domain=domain, dataset_id=f"synthetic-{domain}",
                             targets=[{"metric": "metric.loss", "op": "<=", "value": .1}])
    metric = {"split": "val", "loss": .05}
    model, _ = engine(tmp_path, [result(score=20, metric=metric)], cfg)
    model.run()
    report, _ = build_report(tmp_path / "fe.db", model.experiment_id)
    assert report["goal_achieved"]
    assert report["domain"] == domain
    assert report["evidence_level_declared"] == "synthetic"
    assert report["generalization"]["cross_domain_transfer"] == "not_proven"


def test_cross_domain_comparison_keeps_evidence_limits(tmp_path):
    paths = []
    for domain in ["hdd", "memory"]:
        root = tmp_path / domain
        root.mkdir()
        cfg = config()
        cfg.research = goal_config(domain=domain, dataset_id=domain)
        model, _ = engine(root, [result()], cfg)
        model.run()
        publish_report(root / "fe.db", model.experiment_id)
        paths.append(root / "research/report.json")
    compared = compare_reports(paths)
    assert compared["goal_achievement_rate"] == 1
    assert len(compared["domains"]) == 2
    assert not compared["cross_domain_effectiveness_proven"]


def test_cli_research_commands_are_available():
    runner = CliRunner()
    for command in ["run", "status", "compare"]:
        response = runner.invoke(app, ["research", command, "--help"])
        assert response.exit_code == 0, response.output


def test_runner_requires_goal_contract_before_creating_output(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("budget:\n  max_iterations: 2\n")
    with pytest.raises(ValueError, match="research"):
        run_research(tmp_path / "task", path, tmp_path / "runs")
    assert not (tmp_path / "runs").exists()


def test_real_evaluator_replay_runner_resume_and_skill_export(tmp_path):
    task = Path(__file__).resolve().parents[1] / "examples/research/toy"
    cfg = yaml.safe_load((task / "research.yaml").read_text())
    cfg["budget"]["max_iterations"] = 1
    path = tmp_path / "research.yaml"
    path.write_text(yaml.safe_dump(cfg))
    runs = tmp_path / "runs"
    first = run_research(task, path, runs, "replay-demo", replay_responses=task / "responses.json")
    assert first["state"] == "stopped_without_goal"
    assert first["selected"]["metric"]["false_alarm_rate"] > .1
    cfg["budget"]["max_iterations"] = 3
    path.write_text(yaml.safe_dump(cfg))
    second = run_research(task, path, runs, "replay-demo", resume=True,
                          replay_responses=task / "responses.json")
    assert second["state"] == "goal_achieved"
    assert second["convergence"]["first_goal_round"] == 2
    assert second["baseline"]["combined_score"] == 50
    assert second["selected"]["metric"]["false_alarm_rate"] == 0
    assert second["automation"]["recorded_interventions"][0]["action"] == "budget_changed"
    assert second["cost"]["usage_source"] == "synthetic"
    output = runs / "replay-demo/research"
    assert (output / "fe-research-agent.zip").is_file()
    assert json.loads((output / "skill/fe-research-agent/references/experiment.json").read_text())["goal_achieved"]
    before = second["cost"]["total_tokens"]
    third = run_research(task, path, runs, "replay-demo", resume=True,
                         replay_responses=task / "responses.json")
    assert third["cost"]["total_tokens"] == before
    response = CliRunner().invoke(app, ["research", "status", str(runs / "replay-demo")])
    assert response.exit_code == 0, response.output
    assert json.loads(response.output)["goal_achieved"]


def test_resumed_wall_budget_includes_previous_processes(tmp_path):
    cfg = config()
    cfg.budget.max_iterations = 1
    model, _ = engine(tmp_path, [result(score=20), result(score=25)], cfg)
    model.run()
    old = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    with sqlite3.connect(tmp_path / "fe.db") as conn:
        conn.execute("update experiment set created_at=?", (old,))
    cfg.budget.max_iterations = 3
    cfg.budget.max_wall_hours = 1
    resumed, adapter = engine(tmp_path, [result()], cfg, model.experiment_id)
    summary = resumed.run()
    assert summary.stop_reason == "wall_time"
    assert adapter._call_count == 0
    assert summary.initial_score == 20


def test_controller_lock_refuses_parallel_writers(tmp_path):
    from faultevolve.research import _session_lock
    with _session_lock(tmp_path):
        with pytest.raises(ValueError, match="并发"):
            with _session_lock(tmp_path):
                pass
