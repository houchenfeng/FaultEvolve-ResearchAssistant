"""One durable local workflow shared by CLI, research sessions and Web launches."""

from __future__ import annotations

from contextlib import contextmanager
from faultevolve.common.locking import lock_exclusive
import json
import os
from pathlib import Path
import shutil
import time
from typing import Any, Callable
import uuid
import sys
from importlib.metadata import version

from faultevolve.config import EvolveConfig
from faultevolve.common.resources import execution_resources
from faultevolve.research import _write_json
from faultevolve.research_campaign import digest, hierarchical_search


@contextmanager
def _execution_environment(environment: dict[str, str] | None, progress: Path, cpu_limit: int = 4):
    environment = environment or {}
    keys = (*environment, "FE_LLM_PROGRESS_DIR", "FE_LLM_PROGRESS_INTERVAL_S")
    previous = {key: os.environ.get(key) for key in keys}
    os.environ.update(environment)
    os.environ.setdefault("FE_LLM_PROGRESS_DIR", str(progress))
    os.environ.setdefault("FE_LLM_PROGRESS_INTERVAL_S", "10")
    try:
        with execution_resources(cpu_limit) as resources:
            yield resources
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _freeze(task: Path, config: EvolveConfig, workspace: Path, adapter=None) -> dict:
    from faultevolve.tasks import create_benchmark_adapter
    from faultevolve.tasks.protocol import WorkflowDataProvider
    from faultevolve.cloud.resume import data_fingerprint
    from faultevolve.research_campaign import copy_tree

    adapter = adapter or create_benchmark_adapter(config)
    task_spec = adapter.load_task(task)
    frozen = workspace / "task"
    frozen.mkdir(exist_ok=True)
    sources = {}
    for name in ("evaluator.py", "init.py", "problem.md", "prompt.md"):
        shutil.copyfile(task / name, frozen / name)
        sources[name] = digest(frozen / name)
    data = {"state": "disabled", "note": "未处理数据；由任务适配器沿用原有评估输入。"}
    environment, extra_files, validation = {}, {}, {}
    if config.workflow.data.enabled:
        if not isinstance(adapter, WorkflowDataProvider):
            raise ValueError("当前任务适配器不支持可选数据处理；请关闭 workflow.data.enabled")
        prepared = adapter.prepare_workflow_data(task_spec, workspace, config.workflow.data)
        data, environment, extra_files, validation = (prepared.report, prepared.environment,
                                                    prepared.files, prepared.validation_files)
        if data["state"] != "passed":
            raise ValueError("数据复检未通过")
        _write_json(frozen / "data/descriptor.json", {
            "train_sha256": data.get("derived_sha256", {}), "validation_sha256": validation,
            "processing_policy": config.workflow.data.model_dump(),
        })
    knowledge = Path(config.knowledge.dir or "knowledge")
    source = task / knowledge
    if (knowledge.is_absolute() or not knowledge.parts or ".." in knowledge.parts
            or not source.resolve().is_relative_to(task)
            or source.resolve().relative_to(task).parts[0] in {"data", ".fe"}
            or source.is_symlink()):
        raise ValueError("知识目录必须是任务内独立目录，不能指向数据或运行目录")
    if source.is_dir():
        copy_tree(source, frozen / knowledge, knowledge_only=True)
    search_source = Path(__file__).resolve().parents[2] / "autoresearch-hierarchical-search-cn/scripts/search_engine.py"
    if config.workflow.hierarchical.enabled:
        shutil.copyfile(search_source, workspace / "search_engine.py")
        extra_files["search_engine.py"] = digest(workspace / "search_engine.py")
    files = {str(path.relative_to(workspace)): digest(path)
             for path in frozen.rglob("*") if path.is_file()}
    files.update(extra_files)
    identity = data_fingerprint(task_spec)
    if any(digest(task / name) != expected for name, expected in sources.items()):
        raise ValueError("准备输入期间任务源码发生变化，请重新运行")
    manifest = {"schema": "faultevolve.workflow-input/v2", "task_dir": str(task.resolve()),
        "execution_task_dir": str(frozen if config.workflow.data.enabled else task),
        "config": config.model_dump(mode="json"), "files": files, "source_files": sources,
        "runtime": {"python": sys.version, "pandas": version("pandas"), "numpy": version("numpy")},
        "adapter_identity": f"{type(adapter).__module__}:{type(adapter).__qualname__}",
        "evaluation_split": getattr(adapter, "EVALUATE_SPLIT", "val"),
        "data_identity": identity, "environment": environment,
        "cache_evaluations": bool(config.workflow.data.enabled or identity),
        "validation_files": validation, "data": data}
    _write_json(workspace / "manifest.json", manifest)
    return manifest


def _verify(workspace: Path, manifest: dict, config: EvolveConfig, task: Path) -> None:
    current = config.model_dump(mode="json")
    # Budget changes are explicit research interventions. A completed tuning
    # stage must never be reused after additional code evolution.
    previous = EvolveConfig.model_validate(manifest["config"]).model_dump(mode="json")
    for value in (current, previous):
        value.pop("budget", None)
        value["workflow"].pop("reports", None)
    if current != previous:
        raise ValueError("工作流配置变化，请创建新运行")
    if manifest["task_dir"] != str(task.resolve()):
        raise ValueError("工作流任务路径变化，请创建新运行")
    for relative, expected in manifest.get("source_files", {}).items():
        if digest(task / relative) != expected:
            raise ValueError("任务源码发生变化：" + relative)
    if "data_identity" in manifest:
        from faultevolve.cloud.resume import data_fingerprint
        from faultevolve.tasks.protocol import TaskSpec
        spec = TaskSpec(task, "", "", "", task / "evaluator.py")
        if data_fingerprint(spec) != manifest["data_identity"]:
            raise ValueError("任务数据描述发生变化")
    for relative, expected in manifest["files"].items():
        if digest(workspace / relative) != expected:
            raise ValueError("冻结输入发生变化：" + relative)


def _publish(output: Path, result: dict, ledger: dict | None, db: Path, task: Path,
             config: EvolveConfig) -> dict:
    summary = json.loads((output / "run_summary.json").read_text())
    best_id = summary["best_node_id"]
    best_score = summary["best_score"] if best_id else None
    selected = ledger.get("best_candidate") if ledger else None
    source = output / "programs" / f"{best_id}.py" if best_id else None
    origin = "code_evolution"
    per_structure = config.workflow.hierarchical.mode == "per_structure"
    if not per_structure and selected and (best_score is None or selected["score"] > best_score):
        source = output / "hyperparameters/runs" / selected["candidate_id"] / "candidate.py"
        best_score, origin = selected["score"], "hierarchical_hpo"
    if source is not None and source.is_file():
        shutil.copyfile(source, output / "workflow-best.py")
    elif source is not None:
        raise ValueError("最终程序制品缺失，不能发布完成结果")
    report = {"schema": "faultevolve.workflow-result/v1", "state": "finished",
              "evolution_best_score": summary["best_score"], "best_score": best_score,
              "best_origin": origin, "best_node_id": best_id if origin == "code_evolution" else None,
              "best_candidate_id": selected["candidate_id"] if origin == "hierarchical_hpo" else None,
              "completed_trials": ledger["completion_count"] if ledger else 0,
              "stop_reason": ledger["stop_reason"] if ledger else "disabled",
              "split": json.loads((db.parent / "workflow/manifest.json").read_text()).get("evaluation_split", "val"),
              "tuning_mode": config.workflow.hierarchical.mode,
              "note": ("每个候选先调优再写回节点，演化评分已包含调优结果。" if per_structure and ledger else "")
                      + "分数来自当前任务的本地评估器；独立泛化尚未验证。"}
    _write_json(output / "workflow-result.json", report)
    return {**result, "workflow": report, "final_best_score": best_score,
            "best_program": str(output / "workflow-best.py") if source else None}


def run_workflow(evolve: Callable[..., dict], config: EvolveConfig, arguments: dict[str, Any]) -> dict:
    from faultevolve.cloud.engine import _validate_experiment_id
    from faultevolve.cli import check_db_path_network_fs

    from faultevolve.tasks import create_benchmark_adapter
    adapter = arguments.get("adapter") or create_benchmark_adapter(config)
    if (config.workflow.hierarchical.enabled and config.workflow.hierarchical.mode == "per_structure"
            and config.autotune.hpo.enabled and config.autotune.quota.enabled):
        raise ValueError("逐结构分层调优与配额 HPO 不能同时启用，请关闭 autotune.hpo 或使用 post_evolution")
    task = arguments["task_dir"].resolve()
    exp_id = _validate_experiment_id(arguments.get("resume_id") or arguments.get("experiment_id")
                                     or f"workflow-{uuid.uuid4().hex[:12]}")
    runs = (arguments.get("runs_dir") or task / ".fe/runs").resolve()
    db_dir = runs / exp_id
    check_db_path_network_fs(db_dir / "fe.db")
    if arguments.get("resume_source") is not None:
        raise ValueError("统一工作流请在原本地运行目录使用 --resume；复制恢复尚不支持冻结搜索路径迁移")
    db_dir.mkdir(parents=True, exist_ok=True)
    output = (arguments["artifacts_dir"] / exp_id).resolve() if arguments.get("artifacts_dir") else db_dir
    output.mkdir(parents=True, exist_ok=True)
    workspace = db_dir / "workflow"
    workspace.mkdir(exist_ok=True)
    state: dict = {"schema": "faultevolve.workflow/v1", "state": "running",
                   "phase": "data_checkup" if config.workflow.data.enabled else "evolution"}

    def phase(name: str, status: str = "running", **extra):
        state.update(phase=name, state=status, updated_at=time.time(), **extra)
        _write_json(output / "workflow.json", state)
        _write_json(output / "status.json", state)

    with (db_dir / ".workflow.lock").open("a") as lock:
        try:
            lock_exclusive(lock)
        except BlockingIOError as exc:
            raise ValueError("统一工作流仍在运行，请勿并发启动") from exc
        manifest_path = workspace / "manifest.json"
        manifest = json.loads(manifest_path.read_text()) if manifest_path.is_file() else None
        if manifest is not None:
            if not arguments.get("resume_id"):
                raise ValueError("工作流已存在，请使用 --resume")
            _verify(workspace, manifest, config, task)
        elif (db_dir / "fe.db").is_file():
            raise ValueError("旧实验缺少工作流合同，请创建新运行以确保数据口径一致")
        try:
            if manifest is None:
                phase("data_checkup" if config.workflow.data.enabled else "evolution")
                manifest = _freeze(task, config, workspace, adapter)
            data = manifest["data"]
            _write_json(output / "data-workflow.json", data)
            for stage in ("before", "after"):
                if not (workspace / stage).is_dir():
                    continue
                destination = output / "data-checkup" / stage
                destination.mkdir(parents=True, exist_ok=True)
                for name in ("data_facts.json", "data_quality.json", "data_report.md", "field_coverage.csv"):
                    shutil.copyfile(workspace / stage / name, destination / name)
            effective = workspace / "effective_config.json"
            if effective.is_file():
                previous_budget = json.loads(effective.read_text()).get("budget")
                if previous_budget != config.budget.model_dump(mode="json"):
                    archive = output / f"workflow-previous-{time.time_ns()}"
                    names = ["workflow-result.json", "workflow-best.py"]
                    if config.workflow.hierarchical.mode == "post_evolution":
                        names.append("hyperparameters")
                    for name in names:
                        if (output / name).exists():
                            archive.mkdir(exist_ok=True)
                            (output / name).rename(archive / name)
            _write_json(effective, config.model_dump(mode="json"))
            execution_task = Path(manifest.get("execution_task_dir", workspace / "task"))
            options = {**arguments, "task_dir": execution_task, "config_path": effective, "adapter": adapter,
                       "runs_dir": runs, "experiment_id": None if arguments.get("resume_id") else exp_id,
                       "workflow_active": True}
            # A failed preflight may have no DB yet even when --resume is used.
            if not (db_dir / "fe.db").is_file():
                options.update(resume_id=None, experiment_id=exp_id)
            environment = manifest.get("environment")
            if environment is None:
                legacy_environment = getattr(adapter, "workflow_environment", lambda _: {})
                environment = legacy_environment(workspace)
            with _execution_environment(environment, output / "llm", config.workflow.cpu_limit) as resources:
                _write_json(output / "runtime-resources.json", resources)
                phase("evolution")
                result = evolve(**options)
                if result["status"] != "finished":
                    phase("evolution", result["status"])
                    return result
                ledger = None
                if (config.workflow.hierarchical.enabled
                        and config.workflow.hierarchical.mode == "per_structure"):
                    ledger_path = output / "hyperparameters/ledger.json"
                    if ledger_path.is_file():
                        ledger = json.loads(ledger_path.read_text())
                elif config.workflow.hierarchical.enabled:
                    # A changed evolution result invalidates the frozen route
                    # contract: archive the old ledger instead of reusing it.
                    basis = digest(output / "tree.json")
                    basis_path = output / "hyperparameters/evolution-basis.json"
                    if basis_path.is_file() and json.loads(basis_path.read_text()) != basis:
                        archive = output / f"hyperparameters-previous-{time.time_ns()}"
                        (output / "hyperparameters").rename(archive)
                    _write_json(basis_path, basis)
                    phase("hyperparameters")
                    from dataclasses import asdict
                    from faultevolve.research_campaign import choose_routes
                    local_spec = adapter.load_task(execution_task)
                    routes = choose_routes(db_dir / "fe.db", output / "hyperparameters", template_fallback=False)
                    def evaluate(candidate, evaluator, result_file):
                        return asdict(adapter.evaluate(candidate.read_text(encoding="utf-8"), local_spec))
                    ledger = hierarchical_search(output, db_dir / "fe.db", {
                        "search_engine_path": str(workspace / "search_engine.py"),
                        "evaluator_path": str(workspace / "task/evaluator.py"),
                        "hpo_trials": config.workflow.hierarchical.max_trials,
                        "hpo_wall_seconds": config.workflow.hierarchical.max_wall_seconds,
                        "cpu_limit": resources["effective_cpu_limit"],
                        "validation_files": {**manifest["validation_files"], **{
                            f"public/{name}": value for name, value in data.get("derived_sha256", {}).items()}},
                        "evaluation_split": manifest.get("evaluation_split", "val"),
                        "adapter_identity": manifest.get("adapter_identity"),
                        "cache_evaluations": manifest.get("cache_evaluations", True),
                        "research": config.research.model_dump(mode="json") if config.research else None,
                    }, routes=routes, evaluate=evaluate)
                result = _publish(output, result, ledger, db_dir / "fe.db", task, config)
                phase("complete", "finished", completed_trials=result["workflow"]["completed_trials"],
                      final_best_score=result["workflow"]["best_score"])
        except BaseException as exc:
            # Publish blocked reports even when the local and artifact roots differ.
            if (workspace / "report.json").is_file():
                _write_json(output / "data-workflow.json", json.loads((workspace / "report.json").read_text()))
                for stage in ("before", "after"):
                    if (workspace / stage).is_dir():
                        shutil.copytree(workspace / stage, output / "data-checkup" / stage, dirs_exist_ok=True)
            phase(state["phase"], "paused" if isinstance(exc, (KeyboardInterrupt, InterruptedError)) else "failed",
                  error_type=type(exc).__name__)
            raise
        if config.workflow.reports.enabled:
            try:
                from faultevolve.reporting import export_workflow_reports
                export_workflow_reports(output, db_dir / "fe.db", workspace / "task")
                result["reports"] = {"state": "finished"}
            except Exception as exc:
                result["reports"] = {"state": "failed", "error_type": type(exc).__name__}
                _write_json(output / "report-status.json", result["reports"])
        return result
