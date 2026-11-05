"""Train gates, real evaluator wiring, frozen resumes and the public workflow entry."""

import json
import os
from pathlib import Path
import shutil

import numpy as np
import pandas as pd
import pytest
from typer.testing import CliRunner

from faultevolve.cli import app
from faultevolve.cloud.engine import run_local_evolution
from faultevolve.cloud.llm import MockLLM
from faultevolve.config import DataWorkflowConfig, EvolveConfig, IslandsConfig
from faultevolve.tasks.data_workflow import prepare_train


ROOT = Path(__file__).resolve().parents[1]
PROGRAM = '''import argparse
import os
import pandas as pd
C = 0.5
p = argparse.ArgumentParser()
p.add_argument('--data-dir')
p.add_argument('--split')
p.add_argument('--out')
a = p.parse_args()
train = pd.read_csv(os.path.join(a.data_dir, 'train_history.csv.gz'))
assert not train['smart_5_raw'].isin([float('inf'), -float('inf')]).any()
idx = pd.read_csv(os.path.join(a.data_dir, a.split + '_index.csv'))
h = pd.read_csv(os.path.join(a.data_dir, a.split + '_history.csv.gz'))
scores = h.groupby('serial_number')['smart_5_raw'].max()
idx['score'] = idx.serial_number.map(scores).fillna(0.)
idx['alarm'] = (idx.score > C).astype(int)
idx[['serial_number', 'score', 'alarm']].to_csv(a.out, index=False)
'''


@pytest.fixture
def workflow_task(tmp_path, monkeypatch):
    monkeypatch.delenv("HDD_BENCH_DATA_ROOT", raising=False)
    task = tmp_path / "task"
    task.mkdir()
    public = task / "data/public"
    public.mkdir(parents=True)
    labels = pd.DataFrame({"serial_number": ["PRIVATE_A", "PRIVATE_B", "PRIVATE_C", "PRIVATE_D"],
        "label": [0, 1, 0, 1], "weight": [1., 1., 1., 1.], "model": ["ST"] * 4,
        "cutoff_date": ["2024-07-14"] * 4})
    history = pd.DataFrame({"serial_number": labels.serial_number, "date": ["2024-07-14"] * 4,
        "smart_5_raw": [0., 1., np.inf, 1.]})
    history = pd.concat([history, history.iloc[[0]]], ignore_index=True)
    labels.to_csv(public / "train_labels.csv", index=False)
    history.to_csv(public / "train_history.csv.gz", index=False)
    history.iloc[:4].assign(smart_5_raw=[0., 1., 0., 1.]).to_csv(public / "val_history.csv.gz", index=False)
    labels.drop(columns=["label", "weight"]).to_csv(public / "val_index.csv", index=False)
    (task / "data/eval_only").mkdir()
    labels.to_csv(task / "data/eval_only/val_labels.csv", index=False)
    # A sentinel outside the explicit allowlist must never enter the snapshot.
    (task / "data/holdout").mkdir()
    (task / "data/holdout/NEVER_READ").write_text("synthetic private sentinel")
    shutil.copyfile(ROOT / "benchmark/hdd_mvp/evaluator.py", task / "evaluator.py")
    (task / "init.py").write_text(PROGRAM)
    (task / "problem.md").write_text("合成流程测试")
    (task / "prompt.md").write_text("保持数据合同")
    config = EvolveConfig()
    config.workflow.enabled = True
    config.workflow.data.enabled = True
    config.workflow.hierarchical.max_trials = 5
    config.islands = IslandsConfig.legacy_single()
    config.knowledge.enabled = False
    config.smoke_test.enabled = False
    config.analysis.enabled = False
    config.budget.max_iterations = 1
    config.stop.stop_at_target = False
    (task / "evolve.yaml").write_text(json.dumps(config.model_dump(mode="json")))
    return task, config


def test_train_processing_rechecks_full_files_and_retains_ground_truth(workflow_task, tmp_path):
    task, _ = workflow_task
    source = task / "data/public"
    before = (source / "train_history.csv.gz").read_bytes()
    report = prepare_train(source, tmp_path / "prepared", DataWorkflowConfig())
    assert report["state"] == "passed"
    assert report["before"]["n_history_rows"] == 5
    assert report["after"]["n_history_rows"] == 4
    assert {t["rule"] for t in report["transformations"]} == {
        "drop_exact_history_duplicates", "nonfinite_to_missing"}
    assert (source / "train_history.csv.gz").read_bytes() == before
    assert (source / "train_labels.csv").read_bytes() == (
        tmp_path / "prepared/data/public/train_labels.csv").read_bytes()
    assert "PRIVATE_A" not in json.dumps(report)


@pytest.mark.parametrize("problem", ["conflicting_label", "future", "conflicting_history", "bad_weight", "bad_time"])
def test_unresolved_data_blocks_before_any_model_call(workflow_task, tmp_path, monkeypatch, problem):
    task, _ = workflow_task
    public = task / "data/public"
    labels = pd.read_csv(public / "train_labels.csv")
    history = pd.read_csv(public / "train_history.csv.gz")
    if problem == "conflicting_label":
        labels = pd.concat([labels, labels.iloc[[0]].assign(label=1)])
    elif problem == "future":
        history.loc[0, "date"] = "2024-07-15"
    elif problem == "conflicting_history":
        history = pd.concat([history, history.iloc[[0]].assign(smart_5_raw=99)])
    elif problem == "bad_weight":
        labels.loc[0, "weight"] = -1
    else:
        history.loc[0, "date"] = "unknown"
    labels.to_csv(public / "train_labels.csv", index=False)
    history.to_csv(public / "train_history.csv.gz", index=False)
    def forbidden(*args, **kwargs):
        pytest.fail("LLM construction happened before the data gate")
    monkeypatch.setattr("faultevolve.cloud.engine.DashScopeLLM", forbidden)
    with pytest.raises(ValueError, match="复检未通过"):
        run_local_evolution(task, runs_dir=tmp_path / "runs", experiment_id="blocked")
    output = tmp_path / "runs/blocked"
    assert not (output / "fe.db").exists()
    assert json.loads((output / "data-workflow.json").read_text())["state"] == "blocked"


def test_real_evaluator_uses_derived_train_and_resumes_without_retraining(workflow_task, tmp_path):
    task, _ = workflow_task
    model = MockLLM(enable_repair_scenario=False)
    model.set_responses([f"```python\n{PROGRAM}\n```"])
    result = run_local_evolution(task, mock=True, runs_dir=tmp_path / "runs", experiment_id="unified",
                                 llm_client=model)
    output = tmp_path / "runs/unified"
    assert result["status"] == "finished"
    assert json.loads((output / "workflow.json").read_text())["phase"] == "complete"
    assert json.loads((output / "status.json").read_text())["state"] == "finished"
    summary = json.loads((output / "run_summary.json").read_text())
    assert summary["best_score"] > 0  # init.py asserts that the training inf was removed.
    assert result["workflow"]["completed_trials"] >= 2
    ledger_path = output / "hyperparameters/ledger.json"
    original = json.loads(ledger_path.read_text())
    assert original["holdout"] is None
    assert original["mode"] == "per_structure"
    assert len(original["route_summaries"]) == 1
    assert original["trials"][0]["depth"] == 0
    assert any(t["depth"] > 0 for t in original["trials"])
    from faultevolve.delivery_report import write_delivery_report
    delivery = write_delivery_report(output, output / "fe.db", output / "workflow/task")
    assert [row["phase"] for row in delivery["stage_metrics"]] == ["baseline", "structure_default", "structure_selected"]
    assert delivery["stage_metrics"][0]["accuracy"] == 1.
    assert all(row["total_tokens"] == 0 for row in delivery["parameter_trials"])
    assert len(delivery["parameter_trials"]) == original["completion_count"]
    assert (output / "reports/stage-metrics.csv").is_file()
    assert "真实内存" in (output / "reports/完整运行报告.md").read_text()
    assert not (output / "workflow/data/holdout").exists()
    assert not (output / "workflow/task/data/holdout").exists()
    assert "HDD_BENCH_DATA_ROOT" not in os.environ
    resumed = run_local_evolution(task, mock=True, runs_dir=tmp_path / "runs", resume_id="unified", llm_client=model)
    assert resumed["final_best_score"] == result["final_best_score"]
    assert json.loads(ledger_path.read_text())["trials"] == original["trials"]
    (output / "workflow/data/public/train_labels.csv").write_text("tampered")
    with pytest.raises(ValueError, match="冻结输入发生变化"):
        run_local_evolution(task, mock=True, runs_dir=tmp_path / "runs", resume_id="unified")


def test_cli_entry_and_config_share_the_same_workflow(workflow_task, tmp_path, monkeypatch):
    task, config = workflow_task
    calls = []
    def execute(**kwargs):
        calls.append(kwargs)
        return {"status": "finished"}
    monkeypatch.setattr("faultevolve.cloud.engine.run_local_evolution", execute)
    response = CliRunner().invoke(app, ["run", str(task), "--mock", "--json"])
    assert response.exit_code == 0, response.output
    assert calls[0]["workflow"] is True
    assert EvolveConfig.from_dict(config.model_dump()).workflow == config.workflow


def test_cpu_limit_reaches_native_pools_children_and_restores_after_failure(tmp_path, monkeypatch):
    import subprocess
    import sys
    from concurrent.futures import ThreadPoolExecutor
    from threadpoolctl import threadpool_info
    from faultevolve.common.resources import THREAD_ENV
    from faultevolve.workflow import _execution_environment

    monkeypatch.setenv("OMP_NUM_THREADS", "7")
    previous = {key: os.environ.get(key) for key in (*THREAD_ENV, "FE_RESEARCH_CPU_LIMIT")}
    affinity = os.sched_getaffinity(0)
    pools = [(pool["filepath"], pool["num_threads"]) for pool in threadpool_info()]
    with pytest.raises(RuntimeError, match="synthetic"):
        with _execution_environment({"HDD_BENCH_DATA_ROOT": str(tmp_path)}, tmp_path / "llm", 2) as resources:
            effective = min(2, len(affinity))
            assert resources["effective_cpu_limit"] == effective
            assert all(pool["num_threads"] <= effective for pool in resources["native_pools"])
            with ThreadPoolExecutor(max_workers=1) as executor:
                assert executor.submit(lambda: len(os.sched_getaffinity(0))).result() == effective
            child = subprocess.run([sys.executable, "-c",
                "import json,os,lightgbm; print(json.dumps({'affinity': len(os.sched_getaffinity(0)), "
                "'n_jobs': lightgbm.LGBMClassifier(n_jobs=-1)._process_n_jobs(-1)}))"],
                capture_output=True, text=True, check=True)
            assert json.loads(child.stdout) == {"affinity": effective, "n_jobs": effective}
            raise RuntimeError("synthetic")
    assert os.sched_getaffinity(0) == affinity
    assert {key: os.environ.get(key) for key in previous} == previous
    assert [(pool["filepath"], pool["num_threads"]) for pool in threadpool_info()] == pools


def test_resource_policy_is_applied_to_actual_smoke_and_full_evaluation(workflow_task, tmp_path):
    import sqlite3
    task, config = workflow_task
    config.smoke_test.enabled = True
    config.workflow.cpu_limit = 2
    config.workflow.hierarchical.enabled = False
    config.operators.enabled = ["refine"]
    config.operators.bandit = False
    program = PROGRAM.replace("C = 0.5", """C = 0.5
import lightgbm as lgb
assert lgb.LGBMClassifier(n_jobs=-1)._process_n_jobs(-1) <= 2
assert int(os.environ['OMP_NUM_THREADS']) <= 2
""")
    (task / "init.py").write_text(program)
    # The production sampler reads serial_number from the second CSV column.
    for name in ("train_history.csv.gz", "val_history.csv.gz"):
        path = task / "data/public" / name
        frame = pd.read_csv(path)
        frame[["date", "serial_number", "smart_5_raw"]].to_csv(path, index=False)
    (task / "evolve.yaml").write_text(json.dumps(config.model_dump(mode="json")))
    model = MockLLM(enable_repair_scenario=False)
    model.set_responses([program])
    run_local_evolution(task, mock=True, runs_dir=tmp_path / "runs", experiment_id="limited", llm_client=model)
    output = tmp_path / "runs/limited"
    with sqlite3.connect(output / "fe.db") as conn:
        assert conn.execute("select count(*) from event where type='smoke_passed'").fetchone()[0] == 1
    summary = json.loads((output / "run_summary.json").read_text())
    assert summary["best_score"] > 0
    assert json.loads((output / "runtime-resources.json").read_text())["effective_cpu_limit"] <= 2


def test_interrupted_tuning_is_not_a_completed_workflow(workflow_task, tmp_path, monkeypatch):
    from types import SimpleNamespace
    from faultevolve.structure_tuning import StructureTuner
    from faultevolve.webapi.run_control import _completed

    task, _ = workflow_task
    original = StructureTuner._evaluate_program
    calls = []
    def interrupt_once(self, candidate, *args):
        calls.append(candidate.parent.name)
        if len(calls) == 3:
            raise InterruptedError("synthetic interruption")
        return original(self, candidate, *args)
    monkeypatch.setattr(StructureTuner, "_evaluate_program", interrupt_once)
    model = MockLLM(enable_repair_scenario=False)
    model.set_responses([f"```python\n{PROGRAM}\n```"])
    with pytest.raises(InterruptedError):
        run_local_evolution(task, mock=True, runs_dir=tmp_path / "runs", experiment_id="interrupted", llm_client=model)
    output = tmp_path / "runs/interrupted"
    generated = model._call_count
    proposed = list((output / "hyperparameters/structures").iterdir())
    record = SimpleNamespace(artifacts_dir=str(output.parent), run_id="interrupted")
    assert (output / "run_summary.json").exists()
    assert not _completed(record)
    assert json.loads((output / "workflow.json").read_text())["state"] == "paused"
    run_local_evolution(task, mock=True, runs_dir=tmp_path / "runs", resume_id="interrupted", llm_client=model)
    assert _completed(record)
    assert len(calls) == len(set(calls))
    assert model._call_count == generated
    assert list((output / "hyperparameters/structures").iterdir()) == proposed
    assert json.loads((output / "run_summary.json").read_text())["iterations_done"] == 1


def test_tuned_executable_and_score_drive_the_next_structure(workflow_task, tmp_path, monkeypatch):
    import ast
    import sqlite3
    from faultevolve.common.metering import CallMetrics
    from faultevolve.tasks.protocol import EvalResult

    task, config = workflow_task
    config.budget.max_iterations = 2
    config.workflow.hierarchical.max_trials = 3
    config.operators.enabled = ["refine"]
    config.operators.bandit = False
    config.widening.C = .1
    config.autotune.ledger.enabled = True
    config.autotune.ledger.full_eval_cap = 7  # baseline plus 2 * 3 local trials
    (task / "evolve.yaml").write_text(json.dumps(config.model_dump(mode="json")))
    monkeypatch.setattr("faultevolve.tasks.famou_adapter.FamouAdapter.evaluate",
        lambda *a, **k: EvalResult(1., 10., .1, "", {"split": "val"}))
    order = []

    def evaluate(path, *_):
        code = path.read_text()
        c = next(n.value.value for n in ast.walk(ast.parse(code))
                 if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "C")
        second = "structure_two" in code
        # The second structure has the better default but the first tunes better.
        score = ({.25: 32., .5: 30., 1.: 35.} if second else {.25: 25., .5: 20., 1.: 40.})[c]
        order.append(("eval", second, c, score))
        return {"validity": 1., "combined_score": score, "cost_time": .1,
                "metric": {"split": "val", "recall": score / 100}}

    monkeypatch.setattr("faultevolve.structure_tuning.StructureTuner._evaluate_program", staticmethod(evaluate))

    class Proposals(MockLLM):
        def chat(self, messages, **kwargs):
            order.append(("generate",))
            if self._call_count == 1:
                prompt = messages[-1]["content"]
                assert "C = 1.0" in prompt
                assert "40.00" in prompt
                assert len([item for item in order if item[0] == "eval"]) == 3
            tag = "structure_one" if self._call_count == 0 else "structure_two"
            self._call_count += 1
            program = PROGRAM if tag == "structure_one" else PROGRAM.replace("idx.score > C", "idx.score >= C")
            return f'```python\n"""{tag}"""\n{program}\n```', CallMetrics(prompt_tokens=10, completion_tokens=10)

    result = run_local_evolution(task, mock=True, runs_dir=tmp_path / "runs",
                                 experiment_id="feedback", llm_client=Proposals(False))
    output = tmp_path / "runs/feedback"
    assert result["best_score"] == result["final_best_score"] == 40.
    assert result["workflow"]["completed_trials"] == 6
    assert [item[0] for item in order] == ["generate", "eval", "eval", "eval"] * 2
    with sqlite3.connect(output / "fe.db") as conn:
        nodes = [tuple(map(json.loads, row)) for row in conn.execute(
            "select artifact_json,evidence_json from node where operator != 'init' order by created_at")]
    assert [e["evaluation"]["combined_score"] for _, e in nodes] == [40., 35.]
    assert all("C = 1.0" in a["code"] for a, _ in nodes)
    assert [e["evaluation"]["metric"]["recall"] for _, e in nodes] == [.4, .35]
    assert "structure_one" in (output / "workflow-best.py").read_text()
    summary = json.loads((output / "run_summary.json").read_text())
    assert summary["iterations_done"] == 2
    assert summary["cost_ledger_totals"]["evaluator_calls"] == 7


@pytest.mark.parametrize("opaque,cap,expected", [(False, 2, 1), (True, 5, 1), (False, 3, 2)])
def test_structure_budget_and_unrecognized_parameters_stay_local(workflow_task, tmp_path, monkeypatch,
                                                                opaque, cap, expected):
    from faultevolve.tasks.protocol import EvalResult
    task, config = workflow_task
    config.autotune.ledger.enabled = True
    config.autotune.ledger.full_eval_cap = cap
    (task / "evolve.yaml").write_text(json.dumps(config.model_dump(mode="json")))
    monkeypatch.setattr("faultevolve.tasks.famou_adapter.FamouAdapter.evaluate",
        lambda *a, **k: EvalResult(1., 10., .1, "", {"split": "val"}))
    calls = []
    def evaluate(path, *_):
        calls.append(path.read_text())
        return {"validity": 1., "combined_score": 30., "metric": {"split": "val"}}
    monkeypatch.setattr("faultevolve.structure_tuning.StructureTuner._evaluate_program", staticmethod(evaluate))
    model = MockLLM(False)
    code = PROGRAM.replace("C = 0.5", "threshold = 0.5").replace("idx.score > C", "idx.score > threshold") if opaque else PROGRAM
    model.set_responses([f"```python\n{code}\n```"])
    result = run_local_evolution(task, mock=True, runs_dir=tmp_path / "runs",
                                 experiment_id="budget", llm_client=model)
    assert len(calls) == expected
    assert result["workflow"]["completed_trials"] == expected
    assert all("smart_5_raw" in code for code in calls)
    assert len(list((tmp_path / "runs/budget/hyperparameters/structures").iterdir())) == 1


def test_legacy_post_evolution_search_remains_explicit(workflow_task, tmp_path):
    task, config = workflow_task
    config.workflow.hierarchical.mode = "post_evolution"
    (task / "evolve.yaml").write_text(json.dumps(config.model_dump(mode="json")))
    model = MockLLM(False)
    model.set_responses([f"```python\n{PROGRAM}\n```"])
    result = run_local_evolution(task, mock=True, runs_dir=tmp_path / "runs",
                                 experiment_id="legacy", llm_client=model)
    output = tmp_path / "runs/legacy"
    assert result["workflow"]["tuning_mode"] == "post_evolution"
    assert (output / "hyperparameters/evolution-basis.json").is_file()
    assert not (output / "hyperparameters/structures").exists()


def test_research_goal_uses_one_feasible_tuned_version_in_its_evolution_round(workflow_task, tmp_path, monkeypatch):
    import ast
    from faultevolve.common.research import ResearchConfig
    from faultevolve.research import publish_report
    from faultevolve.tasks.protocol import EvalResult

    task, config = workflow_task
    config.research = ResearchConfig(dataset_id="synthetic-workflow", evidence_level="synthetic",
        evaluation_split="val", targets=[
            {"metric": "combined_score", "value": 30},
            {"metric": "metric.false_alarm_rate", "op": "<=", "value": .002}])
    (task / "evolve.yaml").write_text(json.dumps(config.model_dump(mode="json")))
    monkeypatch.setattr("faultevolve.tasks.famou_adapter.FamouAdapter.evaluate",
        lambda *a, **k: EvalResult(1., 10., .1, "", {"split": "val"}))
    def evaluate(path, *_):
        c = next(n.value.value for n in ast.walk(ast.parse(path.read_text()))
                 if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "C")
        return {"validity": 1., "combined_score": 50. if c == .5 else 35.,
                "metric": {"split": "val", "false_alarm_rate": .03 if c == .5 else .001}}
    monkeypatch.setattr("faultevolve.structure_tuning.StructureTuner._evaluate_program", staticmethod(evaluate))
    model = MockLLM(False)
    model.set_responses([f"```python\n{PROGRAM}\n```"])
    result = run_local_evolution(task, mock=True, runs_dir=tmp_path / "runs",
                                 experiment_id="goals", llm_client=model)
    output = tmp_path / "runs/goals"
    report = publish_report(output / "fe.db", "goals")
    assert report["goal_achieved"]
    assert report["selected"]["combined_score"] == 35.
    assert report["selected"]["metric"]["false_alarm_rate"] == .001
    assert report["selected_node_id"] is not None
    assert report["convergence"]["first_goal_round"] == 1
    assert result["final_best_score"] == 35.
    assert result["workflow"]["completed_trials"] == 2


def test_failed_parameter_trials_do_not_overwrite_a_valid_structure_score(workflow_task, tmp_path, monkeypatch):
    import ast
    from faultevolve.tasks.protocol import EvalResult
    task, config = workflow_task
    (task / "evolve.yaml").write_text(json.dumps(config.model_dump(mode="json")))
    monkeypatch.setattr("faultevolve.tasks.famou_adapter.FamouAdapter.evaluate",
        lambda *a, **k: EvalResult(1., 10., .1, "", {"split": "val"}))
    def evaluate(path, *_):
        c = next(n.value.value for n in ast.walk(ast.parse(path.read_text()))
                 if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "C")
        return {"validity": 1. if c == .5 else 0., "combined_score": 30. if c == .5 else float("nan"),
                "error_info": "" if c == .5 else "timeout", "metric": {"split": "val"}}
    monkeypatch.setattr("faultevolve.structure_tuning.StructureTuner._evaluate_program", staticmethod(evaluate))
    model = MockLLM(False)
    model.set_responses([f"```python\n{PROGRAM}\n```"])
    result = run_local_evolution(task, mock=True, runs_dir=tmp_path / "runs",
                                 experiment_id="failures", llm_client=model)
    assert result["final_best_score"] == 30.
    assert result["workflow"]["completed_trials"] == 3
    assert "C = 0.5" in (tmp_path / "runs/failures/workflow-best.py").read_text()


def test_explicit_no_workflow_disables_nested_search_even_when_yaml_enables_it(workflow_task, tmp_path, monkeypatch):
    from faultevolve.tasks.protocol import EvalResult
    task, _ = workflow_task
    monkeypatch.setattr("faultevolve.tasks.famou_adapter.FamouAdapter.evaluate",
        lambda *a, **k: EvalResult(1., 10., .1, "", {"split": "val"}))
    model = MockLLM(False)
    model.set_responses([f"```python\n{PROGRAM}\n```"])
    result = run_local_evolution(task, mock=True, workflow=False, runs_dir=tmp_path / "runs",
                                 experiment_id="plain", llm_client=model)
    assert result["iterations_done"] == 1
    assert not (tmp_path / "runs/plain/workflow").exists()
    assert not (tmp_path / "runs/plain/hyperparameters").exists()


def test_new_runs_start_from_task_init_even_when_previous_results_are_better(workflow_task, tmp_path, monkeypatch):
    from faultevolve.tasks.protocol import EvalResult
    task, config = workflow_task
    config.workflow.hierarchical.max_trials = 1
    (task / "evolve.yaml").write_text(json.dumps(config.model_dump(mode="json")))
    initial_evaluations = []

    def evaluate(self, code, *_):
        initial_evaluations.append(code)
        return EvalResult(1., 10., .1, "", {"split": "val"})

    monkeypatch.setattr("faultevolve.tasks.famou_adapter.FamouAdapter.evaluate", evaluate)
    monkeypatch.setattr("faultevolve.structure_tuning.StructureTuner._evaluate_program", staticmethod(lambda path, *_: {
        "validity": 1., "combined_score": 30. if "prior_run_only" in path.read_text() else 20.,
        "cost_time": .1, "metric": {"split": "val"}}))
    old = MockLLM(False)
    old.set_responses([f'```python\n"""prior_run_only"""\n{PROGRAM}\n```'])
    first = run_local_evolution(task, mock=True, runs_dir=tmp_path / "runs", experiment_id="first", llm_client=old)
    assert first["final_best_score"] == 30.

    class FreshRunLLM(MockLLM):
        def chat(self, messages, **kwargs):
            assert "prior_run_only" not in messages[-1]["content"]
            return super().chat(messages, **kwargs)

    fresh = FreshRunLLM(False)
    fresh.set_responses([f'```python\n"""new_run_only"""\n{PROGRAM}\n```'])
    second = run_local_evolution(task, mock=True, runs_dir=tmp_path / "runs", experiment_id="second", llm_client=fresh)
    assert initial_evaluations == [PROGRAM, PROGRAM]
    assert second["final_best_score"] == 20.
    assert "new_run_only" in (tmp_path / "runs/second/workflow-best.py").read_text()
    assert "inheritance" not in json.loads((tmp_path / "runs/second/workflow/manifest.json").read_text())


def test_legacy_workflow_resume_keeps_its_frozen_inputs(workflow_task, tmp_path, monkeypatch):
    task, config = workflow_task
    model = MockLLM(False)
    model.set_responses([f"```python\n{PROGRAM}\n```"])
    first = run_local_evolution(task, mock=True, runs_dir=tmp_path / "runs", experiment_id="legacy_inputs",
                                llm_client=model)
    output = tmp_path / "runs/legacy_inputs"
    path = output / "workflow/manifest.json"
    manifest = json.loads(path.read_text())
    manifest["schema"] = "faultevolve.workflow-input/v1"
    for key in ("source_files", "execution_task_dir", "environment", "adapter_identity", "evaluation_split",
                "data_identity", "cache_evaluations"):
        manifest.pop(key, None)
    manifest["config"]["workflow"]["data"].pop("enabled")
    manifest["config"]["workflow"].pop("reports")
    path.write_text(json.dumps(manifest))
    config.workflow.data.enabled = False  # the new default was absent in v1
    (task / "evolve.yaml").write_text(json.dumps(config.model_dump(mode="json")))
    def forbidden(*args, **kwargs):
        pytest.fail("A completed legacy run must reuse its frozen evidence")
    monkeypatch.setattr("faultevolve.tasks.famou_adapter.FamouAdapter.evaluate", forbidden)
    resumed = run_local_evolution(task, mock=True, runs_dir=tmp_path / "runs", resume_id="legacy_inputs",
                                  llm_client=model)
    assert resumed["final_best_score"] == first["final_best_score"]
    assert json.loads((output / "data-workflow.json").read_text())["state"] == "passed"
