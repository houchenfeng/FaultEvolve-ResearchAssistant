"""Task-neutral tuning, opt-in preparation and independent report execution."""

import json
import sqlite3
from pathlib import Path

import pytest
from typer.testing import CliRunner

from faultevolve.cli import app
from faultevolve.cloud.engine import run_local_evolution
from faultevolve.cloud.llm import MockLLM
from faultevolve.config import EvolveConfig, IslandsConfig
from faultevolve.reporting import export_workflow_reports
from faultevolve.tasks.famou_adapter import FamouAdapter


@pytest.fixture
def generic_task(tmp_path):
    task = tmp_path / "numeric_task"
    task.mkdir()
    (task / "evaluator.py").write_text('''import ast
def evaluate(path, timeout=900):
    tree = ast.parse(open(path).read())
    value = next(ast.literal_eval(n.value) for n in tree.body
                 if isinstance(n, ast.Assign) and n.targets[0].id == 'C')
    score = 20.0 - 10.0 * (value - 1.0) ** 2
    return {'validity': 1.0, 'combined_score': score, 'cost_time': 0.01,
            'error_info': '', 'metric': {'split': 'dev', 'objective_loss': 20.0 - score}}
''')
    (task / "init.py").write_text('C = 0.5\n')
    (task / "problem.md").write_text("合成数值优化任务")
    (task / "prompt.md").write_text("提出可本地评估的候选程序")
    config = EvolveConfig()
    config.task.adapter = "famou"
    config.workflow.enabled = True
    config.workflow.hierarchical.max_trials = 3
    config.islands = IslandsConfig.legacy_single()
    config.budget.max_iterations = 1
    config.stop.stop_at_target = False
    config.smoke_test.enabled = False
    config.knowledge.enabled = False
    (task / "evolve.yaml").write_text(json.dumps(config.model_dump(mode="json")))
    return task, config


class NumericAdapter(FamouAdapter):
    EVALUATE_SPLIT = "dev"


def _model():
    model = MockLLM(False)
    model.set_responses(['```python\nC = 0.5\n# new structure\n```'])
    return model


def test_generic_core_needs_neither_data_preparation_nor_reporting(generic_task, tmp_path, monkeypatch):
    task, _ = generic_task
    def forbidden(*args, **kwargs):
        pytest.fail("Optional component was invoked by core tuning")
    monkeypatch.setattr("faultevolve.tasks.data_workflow.prepare_train", forbidden)
    monkeypatch.setattr("faultevolve.tasks.hdd_adapter.HDDAdapter.load_task", forbidden)
    monkeypatch.setattr("faultevolve.reporting.export_workflow_reports", forbidden)
    result = run_local_evolution(task, mock=True, adapter=NumericAdapter(), llm_client=_model(),
                                 runs_dir=tmp_path / "runs", experiment_id="generic")
    output = tmp_path / "runs/generic"
    assert result["final_best_score"] == 20.
    assert result["workflow"]["completed_trials"] == 3
    assert result["workflow"]["split"] == "dev"
    assert "C = 1.0" in (output / "workflow-best.py").read_text()
    assert not (task / "data").exists()
    assert not (output / "workflow/data").exists()
    assert not (output / "effect-report.json").exists()
    assert not (output / "reports").exists()
    manifest = json.loads((output / "workflow/manifest.json").read_text())
    assert manifest["data"]["state"] == "disabled" and manifest["environment"] == {}
    spec = next((output / "hyperparameters/structures").glob('*/experiment_spec.json'))
    assert json.loads(spec.read_text())["evaluation"]["adapter_identity"].endswith(":NumericAdapter")


def test_reports_are_rebuilt_without_evaluation_or_score_changes(generic_task, tmp_path, monkeypatch):
    task, _ = generic_task
    adapter, model = NumericAdapter(), _model()
    run_local_evolution(task, mock=True, adapter=adapter, llm_client=model,
                        runs_dir=tmp_path / "runs", experiment_id="report")
    output = tmp_path / "runs/report"
    with sqlite3.connect(output / "fe.db") as conn:
        before = conn.execute("select id,evidence_json from node order by id").fetchall()
    selected, calls = (output / "workflow-best.py").read_bytes(), model._call_count
    def forbidden(*args, **kwargs):
        pytest.fail("Reporting cannot evaluate or generate candidates")
    monkeypatch.setattr(NumericAdapter, "evaluate", forbidden)
    report = export_workflow_reports(output, output / "fe.db")
    assert report["best_score"] == 20. and report["split"] == "dev"
    assert report["stage_metrics"][0]["task_metrics"]["objective_loss"] == 2.5
    assert (output / "effect-report.json").is_file()
    assert model._call_count == calls and (output / "workflow-best.py").read_bytes() == selected
    with sqlite3.connect(output / "fe.db") as conn:
        assert conn.execute("select id,evidence_json from node order by id").fetchall() == before
    response = CliRunner().invoke(app, ['report', str(task), '--run-id', 'report',
        '--runs-dir', str(tmp_path / 'runs'), '--workflow', '--json'])
    assert response.exit_code == 0, response.output
    assert json.loads(response.output)["best_score"] == 20.


def test_report_failure_does_not_turn_finished_search_into_failure(generic_task, tmp_path, monkeypatch):
    task, config = generic_task
    config.workflow.reports.enabled = True
    (task / "evolve.yaml").write_text(json.dumps(config.model_dump(mode="json")))
    def fail(*args, **kwargs):
        raise RuntimeError("synthetic report failure")
    monkeypatch.setattr("faultevolve.reporting.export_workflow_reports", fail)
    result = run_local_evolution(task, mock=True, adapter=NumericAdapter(), llm_client=_model(),
                                 runs_dir=tmp_path / "runs", experiment_id="report_failure")
    output = tmp_path / "runs/report_failure"
    assert result["status"] == result["workflow"]["state"] == "finished"
    assert result["final_best_score"] == 20. and result["reports"]["state"] == "failed"
    assert json.loads((output / "workflow.json").read_text())["state"] == "finished"


def test_data_preparation_requires_an_explicit_adapter_capability(generic_task, tmp_path):
    task, config = generic_task
    config.workflow.data.enabled = True
    (task / "evolve.yaml").write_text(json.dumps(config.model_dump(mode="json")))
    model = _model()
    with pytest.raises(ValueError, match="适配器不支持可选数据处理"):
        run_local_evolution(task, mock=True, adapter=NumericAdapter(), llm_client=model,
                            runs_dir=tmp_path / "runs", experiment_id="unsupported_data")
    assert model._call_count == 0


def test_experiment_configuration_controls_models_and_budgets(generic_task, tmp_path, monkeypatch):
    task, config = generic_task
    config.budget.max_iterations = 2
    config.llm.generate_model = "configured-generator"
    config.llm.reason_model = "configured-reasoner"
    config.llm.max_tokens = 1234
    config.judge.provider = "none"
    external = tmp_path / "experiment.yaml"
    external.write_text(json.dumps(config.model_dump(mode="json")))
    seen = []
    model = _model()
    model.set_responses(['```python\nC = 0.5\n# first\n```', '```python\nC = 0.5\n# second\n```'])
    def gateway(effective):
        seen.append(effective)
        return model
    monkeypatch.setattr("faultevolve.cloud.engine.DashScopeLLM", gateway)
    result = run_local_evolution(task, config_path=external, adapter=NumericAdapter(),
                                 runs_dir=tmp_path / "runs", experiment_id="configured")
    assert result["iterations_done"] == 2
    assert seen[0].llm.generate_model == "configured-generator"
    assert seen[0].llm.reason_model == "configured-reasoner" and seen[0].llm.max_tokens == 1234
    assert seen[0].budget.max_iterations == 2 and seen[0].workflow.hierarchical.max_trials == 3
    # The shared task configuration was not rewritten by this experiment.
    original = json.loads((task / "evolve.yaml").read_text())
    assert original["budget"]["max_iterations"] == 1


def test_reporting_can_be_enabled_after_search_without_retraining(generic_task, tmp_path, monkeypatch):
    task, config = generic_task
    model = _model()
    run_local_evolution(task, mock=True, adapter=NumericAdapter(), llm_client=model,
                        runs_dir=tmp_path / "runs", experiment_id="enable_report")
    generated = model._call_count
    config.workflow.reports.enabled = True
    (task / "evolve.yaml").write_text(json.dumps(config.model_dump(mode="json")))
    def forbidden(*args, **kwargs):
        pytest.fail("Enabling reports on a finished run must not retrain")
    monkeypatch.setattr(NumericAdapter, "evaluate", forbidden)
    result = run_local_evolution(task, mock=True, adapter=NumericAdapter(), llm_client=model,
        runs_dir=tmp_path / "runs", resume_id="enable_report")
    assert result["reports"]["state"] == "finished" and model._call_count == generated
    assert (tmp_path / "runs/enable_report/reports/完整运行报告.md").exists()
