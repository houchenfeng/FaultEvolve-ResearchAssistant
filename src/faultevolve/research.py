"""Reusable research sessions over the existing task adapters and evolution engine."""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import typer

from faultevolve.common.research import ResearchConfig, assess_goals
from faultevolve.config import EvolveConfig
from faultevolve.cloud.llm import MockLLM


app = typer.Typer(help="按多指标目标执行、恢复和审计自动科研实验")


class ReplayLLM(MockLLM):
    """Finite offline candidate replay; scores still come from the real evaluator."""

    def __init__(self, responses: list[str], consumed: int = 0) -> None:
        super().__init__(enable_repair_scenario=False)
        self.set_responses(responses)
        self._call_count = consumed

    def chat(self, *args: Any, **kwargs: Any):
        if self._call_count >= len(self._responses):
            raise RuntimeError("离线候选响应已耗尽；请补齐响应或检查预算")
        return super().chat(*args, **kwargs)


@contextmanager
def _session_lock(output: Path):
    """Serialize controller writes as well as the engine's existing run claim."""
    from faultevolve.common.locking import lock_exclusive, unlock

    with (output / ".research.lock").open("a") as handle:
        try:
            lock_exclusive(handle)
        except BlockingIOError as exc:
            raise ValueError("科研实验仍在运行，请勿并发启动") from exc
        try:
            yield
        finally:
            unlock(handle)


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(_json_safe(value), ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                         encoding="utf-8")
    temporary.replace(path)


def _json_safe(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


def _seconds(start: str, end: str) -> float | None:
    try:
        return max(0., (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds())
    except (TypeError, ValueError):
        return None


def build_report(db: Path, experiment_id: str) -> tuple[dict[str, Any], str | None]:
    """Rebuild from persisted evaluator evidence, including all previous processes."""
    from faultevolve.cloud.store import Store

    store = Store(db, read_only=True)
    experiment = store.get_experiment(experiment_id)
    if experiment is None:
        raise ValueError("实验不存在")
    events = store.get_events(experiment_id)
    contracts = [event.payload["config"] for event in events
                 if event.type == "research_contract" and event.payload.get("config")]
    if not contracts:
        raise ValueError("实验缺少科研目标契约")
    config = ResearchConfig.model_validate(contracts[0])
    nodes = store.get_nodes_by_experiment(experiment_id)
    evaluated = [node for node in nodes if node.evidence.evaluation is not None]
    valid = [node for node in evaluated if node.evidence.evaluation.validity == 1.
             and math.isfinite(node.evidence.evaluation.combined_score)]
    roots = [node for node in valid if node.parent_id is None]
    baseline = roots[0] if roots else None
    feasible = [node for node in valid
                if assess_goals(config, node.evidence.evaluation.model_dump())["achieved"]]
    selected = max(feasible or valid, key=lambda node: node.evidence.evaluation.combined_score,
                   default=None)
    best_score_node = max(valid, key=lambda node: node.evidence.evaluation.combined_score, default=None)
    first_goal = next((event for event in events if event.type == "research_goal_reached"), None)
    first_goal_time = first_goal.ts if first_goal else None
    first_goal_round = first_goal.payload.get("iterations_done") if first_goal else None
    # Derive from full iteration history, never from a resumed process's counters.
    if feasible:
        ids = {node.id for node in feasible}
        if baseline is not None and baseline.id in ids:
            first_goal_time, first_goal_round = first_goal_time or baseline.created_at, 0
        else:
            rounds = 0
            for event in events:
                if event.type == "iteration_complete":
                    rounds += 1
                    if event.payload.get("node_id") in ids:
                        first_goal_time, first_goal_round = event.ts, rounds
                        break
    goal_tokens = None
    if first_goal_time is not None:
        goal_tokens = sum(call.prompt_tokens + call.completion_tokens
                          for call in store.get_llm_calls(experiment_id)
                          if call.created_at <= first_goal_time)
    finish_events = [event for event in events if event.type == "run_finished"]
    stop_reason = None
    summary_path = db.parent / "run_summary.json"
    if summary_path.exists() and experiment.status == "finished":
        stop_reason = json.loads(summary_path.read_text(encoding="utf-8")).get("stop_reason")
    end = (finish_events[-1].ts if experiment.status == "finished" and finish_events
           else datetime.now(timezone.utc).isoformat())
    rollup = store.get_cost_rollup(experiment_id)
    initial = baseline.evidence.evaluation.model_dump() if baseline else None
    final = selected.evidence.evaluation.model_dump() if selected else None
    improvements = {}
    if initial is not None and final is not None:
        for key in sorted(set(initial["metric"]) & set(final["metric"])):
            before, after = initial["metric"][key], final["metric"][key]
            if (type(before) in (int, float) and type(after) in (int, float)
                    and math.isfinite(before) and math.isfinite(after)):
                improvements[key] = {"baseline": before, "selected": after, "delta": after - before}
    report = {
        "schema": "faultevolve.research/v1", "experiment_id": experiment_id,
        "domain": config.domain, "dataset_id": config.dataset_id,
        "evidence_level_declared": config.evidence_level,
        "state": "goal_achieved" if feasible else ("stopped_without_goal" if experiment.status == "finished"
                                                  else experiment.status),
        "stop_reason": stop_reason, "goal": config.model_dump(),
        "goal_achieved": bool(feasible), "selected_node_id": selected.id if selected else None,
        "highest_score_node_id": best_score_node.id if best_score_node else None,
        "baseline": initial, "selected": final,
        "goal_assessment": assess_goals(config, final or {}), "metric_changes": improvements,
        "iterations_done": experiment.iterations_done,
        "convergence": {"first_goal_round": first_goal_round,
                        "time_to_goal_s": _seconds(experiment.created_at, first_goal_time),
                        "known_tokens_to_goal": goal_tokens,
                        "elapsed_wall_s": _seconds(experiment.created_at, end)},
        "cost": rollup,
        "input_identity": json.loads(store.get_run_identity(experiment_id) or "{}"),
        "complexity": {"source_bytes": len(selected.artifact.code.encode()) if selected else None,
                       "parameter_count": final["metric"].get("parameter_count") if final else None,
                       "model_bytes": final["metric"].get("model_bytes") if final else None,
                       "peak_memory_mb": final["metric"].get("peak_memory_mb") if final else None,
                       "note": "模型规模只使用本地评估器实际返回的统计，未知项保持 null"},
        "automation": {"coverage": None, "coverage_basis": "未建立步骤级人工介入分母，不能声明百分比",
                       "resumes": sum(event.type == "run_resumed" for event in events),
                       "recorded_interventions": [event.payload for event in events
                                                  if event.type == "research_intervention"]},
        "generalization": {"independent_test": "not_evaluated", "cross_domain_transfer": "not_proven"},
    }
    manifest_path = db.parent / "research-manifest.json"
    if manifest_path.is_file():
        report["execution"] = json.loads(manifest_path.read_text(encoding="utf-8"))
        report["cost"]["usage_source"] = ("synthetic" if report["execution"]["generation_mode"] != "llm"
                                           else "provider_usage_ledger")
    code = selected.artifact.code if selected else None
    workflow_path = db.parent / "workflow-result.json"
    workflow_state_path = db.parent / "workflow.json"
    if workflow_state_path.is_file():
        report["workflow_state"] = json.loads(workflow_state_path.read_text(encoding="utf-8"))
    if workflow_path.is_file():
        workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
        report["workflow"] = workflow
        # Goal-based research selection considers all completed HPO evaluations,
        # not just the single highest scalar score in the search ledger.
        ledger_path = db.parent / "hyperparameters/ledger.json"
        trials = json.loads(ledger_path.read_text()).get("trials", []) if ledger_path.is_file() else []
        if workflow.get("tuning_mode") == "per_structure":
            # Selected parameter versions already have node evidence and a real
            # evolution round. They must not be reclassified as post-run HPO.
            trials = []
        for trial in trials:
            candidate_id = trial.get("candidate_id", "")
            if not isinstance(candidate_id, str) or not candidate_id.isalnum():
                continue
            directory = db.parent / "hyperparameters/runs" / candidate_id
            evaluation = json.loads((directory / "evaluation.json").read_text())
            assessment = assess_goals(config, evaluation)
            if assessment["achieved"] and (not report["goal_achieved"] or
                    evaluation["combined_score"] > report["selected"]["combined_score"]):
                code = (directory / "candidate.py").read_text(encoding="utf-8")
                if not report["goal_achieved"]:
                    report["convergence"].update(first_goal_round=None, time_to_goal_s=None,
                        known_tokens_to_goal=report["cost"]["total_tokens"], first_goal_phase="hyperparameters")
                report.update(goal_achieved=True, state="goal_achieved", selected=evaluation,
                              selected_node_id=None, selected_candidate_id=candidate_id,
                              goal_assessment=assessment)
                report["complexity"].update(source_bytes=len(code.encode()),
                    **{key: evaluation.get("metric", {}).get(key) for key in (
                        "parameter_count", "model_bytes", "peak_memory_mb")})
                report["metric_changes"] = {}
                for key in sorted(set((initial or {}).get("metric", {})) & set(evaluation.get("metric", {}))):
                    before, after = initial["metric"][key], evaluation["metric"][key]
                    if (type(before) in (int, float) and type(after) in (int, float)
                            and math.isfinite(before) and math.isfinite(after)):
                        report["metric_changes"][key] = {"baseline": before, "selected": after, "delta": after - before}
    return _json_safe(report), code


def publish_report(db: Path, experiment_id: str) -> dict[str, Any]:
    """Publish a candidate, a machine-readable report and task-scoped lessons."""
    from faultevolve.cloud.store import Store

    report, code = build_report(db, experiment_id)
    results = db.parent / "research"
    _write_json(results / "report.json", report)
    if code is not None:
        (results / "best.py").write_text(code, encoding="utf-8")
    selected = report["selected"]
    score = selected["combined_score"] if selected else "未知"
    text = (f"# 自动科研实验报告\n\n实验：{experiment_id}。\n\n"
            f"领域：{report['domain']}；数据集：{report['dataset_id']}。\n\n"
            f"目标达成：{'是' if report['goal_achieved'] else '否'}；停止原因：{report['stop_reason']}。\n\n"
            f"完成轮数：{report['iterations_done']}；所选方案评分：{score}。\n\n"
            f"首次达标：第 {report['convergence']['first_goal_round']} 轮；"
            f"耗时 {report['convergence']['time_to_goal_s']} 秒。\n\n"
            f"已记录 Token：{report['cost']['total_tokens']}；未知用量请求："
            f"{report['cost']['unresolved_calls']}。\n\n"
            "| 指标 | 比较 | 目标 | 实测 | 达标 |\n|---|---|---:|---:|---|\n")
    for check in report["goal_assessment"]["checks"]:
        text += (f"| {check['metric']} | {check['op']} | {check['target']} | "
                 f"{check['observed']} | {'是' if check['passed'] else '否'} |\n")
    text += ("\n本报告只支持当前评估划分的结论；独立测试、跨器件迁移尚未验证。"
             "自动化覆盖率未计量，实际模型参数量等缺失项不作估计。\n")
    if report.get("workflow"):
        text += (f"\n全流程完成分层试验 {report['workflow']['completed_trials']} 次；"
                 f"最高验证评分 {report['workflow']['best_score']}。科研方案按多指标目标单独筛选。\n")
    (results / "报告.md").write_text(text, encoding="utf-8")
    store = Store(db, read_only=True)
    lessons = []
    for node in store.get_nodes_by_experiment(experiment_id):
        evaluation = node.evidence.evaluation
        if evaluation is not None and evaluation.validity == 1. and node.parent_id:
            lessons.append({"node_id": node.id, "parent_id": node.parent_id,
                            "intent": node.artifact.intent, "score": evaluation.combined_score,
                            "delta": node.evidence.delta_score, "scope": "当前任务评估划分"})
    _write_json(results / "lessons.json", lessons)
    source = Path(__file__).resolve().parents[2] / "skill/fe-research-agent"
    if source.is_dir():
        bundle = results / "skill/fe-research-agent"
        shutil.copytree(source, bundle, dirs_exist_ok=True)
        _write_json(bundle / "references/experiment.json", report)
        _write_json(bundle / "references/lessons.json", lessons)
        shutil.make_archive(str(results / "fe-research-agent"), "zip", results / "skill", "fe-research-agent")
    return report


def run_research(task_dir: Path, config_path: Path, runs_dir: Path, run_id: str | None = None,
                 resume: bool = False, mock: bool = False,
                 replay_responses: Path | None = None) -> dict[str, Any]:
    """Reuse the evolution engine with immutable goals and resumable evidence."""
    from faultevolve.cli import check_db_path_network_fs
    from faultevolve.cloud.engine import _validate_experiment_id
    from faultevolve.tasks.registry import create_adapter

    if not config_path.is_file():
        raise ValueError("科研配置文件不存在")
    config = EvolveConfig.from_yaml(config_path)
    if config.research is None:
        raise ValueError("科研配置必须包含 research 数据集身份和多指标目标")
    if config.budget.max_iterations <= 0:
        raise ValueError("科研迭代预算必须为正整数")
    if (mock or replay_responses) and config.research.evidence_level != "synthetic":
        raise ValueError("离线模拟或回放必须声明 evidence_level: synthetic")
    if resume and not run_id:
        raise ValueError("恢复实验必须指定 --run-id")
    experiment_id = _validate_experiment_id(run_id or f"research-{uuid.uuid4().hex[:12]}")
    output = runs_dir.resolve() / experiment_id
    db = output / "fe.db"
    check_db_path_network_fs(db)
    frozen = output / "research-config.json"
    if not resume and output.exists():
        raise ValueError("运行目录已存在；请使用 --resume 或新的运行 ID")
    if resume and not db.is_file():
        raise ValueError("找不到可恢复的实验数据库")
    if not resume:
        create_adapter(config).load_task(task_dir)
        output.mkdir(parents=True)
    with _session_lock(output):
        return _execute_research(task_dir, config, frozen, db, experiment_id, runs_dir,
                                 resume, mock, replay_responses)


def _execute_research(task_dir: Path, config: EvolveConfig, frozen: Path, db: Path,
                      experiment_id: str, runs_dir: Path, resume: bool, mock: bool,
                      replay_responses: Path | None) -> dict[str, Any]:
    from faultevolve.cloud.engine import run_local_evolution
    from faultevolve.cloud.store import Store
    from faultevolve.cloud.resume import claim_is_live
    from faultevolve.common.schemas import Event

    effective = config.model_dump(mode="json")
    manifest_path = db.parent / "research-manifest.json"
    manifest = {"task_dir": str(task_dir.resolve()),
                "generation_mode": "replay" if replay_responses else ("mock" if mock else "llm"),
                "generate_model": config.llm.generate_model,
                "replay_sha256": hashlib.sha256(replay_responses.read_bytes()).hexdigest()
                                  if replay_responses else None}
    llm_client = None
    if resume:
        if not frozen.is_file():
            raise ValueError("缺少冻结配置，不能按科研实验恢复")
        previous = json.loads(frozen.read_text(encoding="utf-8"))
        if {k: v for k, v in previous.items() if k != "budget"} != {
                k: v for k, v in effective.items() if k != "budget"}:
            raise ValueError("任务、模型或目标配置变化；请创建新实验")
        # Check ownership before updating either the evidence or frozen budget.
        store = Store(db, read_only=True)
        claim = store.get_run_claim(experiment_id)
        if claim and claim_is_live(claim):
            raise ValueError("实验仍被其他进程持有")
        if not manifest_path.is_file() or json.loads(manifest_path.read_text(encoding="utf-8")) != manifest:
            raise ValueError("任务路径或生成模式变化；请创建新实验")
        if previous["budget"] != effective["budget"]:
            Store(db).create_event(Event(experiment_id=experiment_id, type="research_intervention",
                                        payload={"action": "budget_changed", "before": previous["budget"],
                                                 "after": effective["budget"]}))
    if replay_responses:
        responses = json.loads(replay_responses.read_text(encoding="utf-8"))
        if not isinstance(responses, list) or not responses or not all(isinstance(x, str) for x in responses):
            raise ValueError("离线响应必须为非空 JSON 字符串列表")
        consumed = sum(call.stage in ("generate", "repair", "self_fix", "crossover")
                       for call in Store(db, read_only=True).get_llm_calls(experiment_id)) if resume else 0
        llm_client = ReplayLLM(responses, consumed)
    _write_json(frozen, effective)
    _write_json(manifest_path, manifest)
    try:
        run_local_evolution(task_dir=task_dir, config_path=frozen, mock=mock or bool(replay_responses),
                            max_iterations=config.budget.max_iterations, seed=config.seed,
                            runs_dir=runs_dir, resume_id=experiment_id if resume else None,
                            experiment_id=None if resume else experiment_id, llm_client=llm_client)
    except BaseException as exc:
        if db.is_file():
            # A direct engine caller can hold a claim independently of this controller.
            store = Store(db)
            claim = store.get_run_claim(experiment_id)
            if claim and claim.get("holder_pid") == os.getpid():
                store.release_run_claim(experiment_id, claim["holder_id"])
                claim = None
            if not claim_is_live(claim) and store.get_experiment(experiment_id).status != "finished":
                store.update_experiment(experiment_id, status="paused" if isinstance(exc, KeyboardInterrupt)
                                        else "failed")
        raise
    finally:
        if db.is_file():
            # Publishing never calls the evaluator or LLM and cannot manufacture scores.
            contracts = [event for event in Store(db, read_only=True).get_events(experiment_id)
                         if event.type == "research_contract" and event.payload.get("config")]
            if contracts and not claim_is_live(Store(db, read_only=True).get_run_claim(experiment_id)):
                publish_report(db, experiment_id)
    return json.loads((db.parent / "research/report.json").read_text(encoding="utf-8"))


def compare_reports(paths: list[Path]) -> dict[str, Any]:
    """Compare per-task outcomes without equating scores from different evaluators."""
    reports = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
    if not reports or any(report.get("schema") != "faultevolve.research/v1" for report in reports):
        raise ValueError("只能比较标准科研报告")
    rows = [{"experiment_id": report["experiment_id"], "domain": report["domain"],
             "dataset_id": report["dataset_id"], "evidence_level": report["evidence_level_declared"],
             "goal_achieved": report["goal_achieved"],
             "score": report["selected"]["combined_score"] if report["selected"] else None}
            for report in reports]
    return {"tasks": rows, "domains": sorted({row["domain"] for row in rows}),
            "datasets": sorted({row["dataset_id"] for row in rows}),
            "goal_achievement_rate": sum(row["goal_achieved"] for row in rows) / len(rows),
            "cross_domain_effectiveness_proven": False,
            "note": "不同评估器分数不直接比较；任务适配或合成验证不等于真实跨场景性能迁移"}


@app.command("run")
def run_command(
    task_dir: Path = typer.Argument(..., help="包含四件套的任务目录"),
    config: Path = typer.Option(..., "--config", help="含科研目标和预算的 YAML 配置"),
    runs_dir: Path = typer.Option(Path(".fe/research"), help="本地运行目录"),
    run_id: str | None = typer.Option(None, help="实验 ID"),
    resume: bool = typer.Option(False, help="恢复相同目标，可显式调整预算"),
    mock: bool = typer.Option(False, help="使用既有硬盘模拟生成器，仅用于硬盘流程调试"),
    replay_responses: Path | None = typer.Option(None, help="有限离线候选响应 JSON，仅用于合成验证"),
) -> None:
    """持续进化，直到全部目标满足或预算、停滞等停止条件触发。"""
    try:
        result = run_research(task_dir, config, runs_dir, run_id, resume, mock, replay_responses)
    except (ValueError, OSError) as exc:
        typer.echo(f"错误：{exc}", err=True)
        raise typer.Exit(2) from exc
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


@app.command("status")
def status_command(run_dir: Path = typer.Argument(..., help="包含 fe.db 的实验目录")) -> None:
    """只读重建当前进度，不产生新的模型调用或评估。"""
    if not (run_dir / "fe.db").is_file():
        typer.echo("错误：运行目录不存在实验数据库", err=True)
        raise typer.Exit(2)
    try:
        report, _ = build_report(run_dir / "fe.db", run_dir.name)
    except ValueError as exc:
        typer.echo(f"错误：{exc}", err=True)
        raise typer.Exit(2) from exc
    typer.echo(json.dumps(report, ensure_ascii=False, indent=2))


@app.command("compare")
def compare_command(reports: list[Path] = typer.Argument(..., help="各任务的 research/report.json")) -> None:
    """输出跨任务证据矩阵，不自动宣称泛化通过。"""
    try:
        result = compare_reports(reports)
    except (ValueError, OSError) as exc:
        typer.echo(f"错误：{exc}", err=True)
        raise typer.Exit(2) from exc
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))
