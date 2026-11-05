"""Effect report: prediction metrics and model complexity for a finished workflow run.

Every number is read from the local evaluator's output or from the candidate source
itself. Nothing here comes from an LLM. Parameter counts are static upper-bound
estimates (the candidate trains inside the evaluator subprocess), and are labelled so.
"""

from __future__ import annotations

import ast
from datetime import datetime
import json
import math
import sqlite3
from pathlib import Path
from typing import Any

PERFORMANCE_KEYS = (
    "accuracy", "unweighted_accuracy", "true_positives", "false_positives", "false_negatives", "true_negatives",
    "precision", "recall", "f1", "false_alarm_rate", "missed_detection_rate",
    "alarms_per_1k_disks", "auprc", "recall_at_far", "f1_p10", "combined_score",
)
_TREE_DEFAULTS = {"n_estimators": 100, "num_leaves": 31, "num_boost_round": 100}
_LINEAR = {"LogisticRegression", "SGDClassifier", "LinearSVC", "RidgeClassifier"}
_TREES = {"LGBMClassifier", "XGBClassifier", "GradientBoostingClassifier"}
_FOREST = {"RandomForestClassifier", "ExtraTreesClassifier"}


def _number(value: Any) -> float | None:
    return float(value) if type(value) in (int, float) and math.isfinite(value) else None


def _constant(node: ast.AST, names: dict[str, Any] | None = None) -> Any:
    if isinstance(node, ast.Name) and names:
        return names.get(node.id)
    if isinstance(node, ast.Dict):
        values = {}
        for key, value in zip(node.keys, node.values):
            if key is None:
                expanded = _constant(value, names)
                if isinstance(expanded, dict):
                    values.update(expanded)
            else:
                name = _constant(key, names)
                if isinstance(name, str):
                    values[name] = _constant(value, names)
        return values
    if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "dict" and not node.args:
        return _keywords(node, names or {})
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError):
        return None


def _keywords(node: ast.Call, names: dict[str, Any]) -> dict[str, Any]:
    values = {}
    for keyword in node.keywords:
        value = _constant(keyword.value, names)
        if keyword.arg is None:
            if isinstance(value, dict):
                values.update(value)
            else:
                values["_unresolved_expansion"] = True
        else:
            values[keyword.arg] = value
    return values


def _known_names(tree: ast.AST) -> dict[str, Any]:
    """Literal values bound to plain names: module constants and function defaults."""
    names: dict[str, Any] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = node.args.args[len(node.args.args) - len(node.args.defaults):]
            for arg, default in zip(args, node.args.defaults):
                value = _constant(default, names)
                if value is not None:
                    names.setdefault(arg.arg, value)
            for arg, default in zip(node.args.kwonlyargs, node.args.kw_defaults):
                value = _constant(default, names) if default is not None else None
                if value is not None:
                    names.setdefault(arg.arg, value)
        elif isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            value = _constant(node.value, names)
            if value is not None:
                names.setdefault(node.targets[0].id, value)
    return names


def program_complexity(code: str, n_features: int | None = None) -> dict[str, Any]:
    """Static size and capacity estimate of a candidate program."""
    tree = ast.parse(code)
    names = _known_names(tree)
    models: list[dict[str, Any]] = []
    folds = 1
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            kwargs = _keywords(node, names)
            if name == "StratifiedKFold" or name == "KFold":
                splits = kwargs.get("n_splits") or (_constant(node.args[0], names) if node.args else None)
                folds = max(folds, splits if isinstance(splits, int) else 1)
            elif name in _TREES | _FOREST | _LINEAR:
                models.append({"family": name, **kwargs})
    estimate = 0
    for model in models:
        family = model["family"]
        if family in _TREES:
            rounds = model.get("n_estimators", model.get("num_boost_round", _TREE_DEFAULTS["n_estimators"]))
            leaves = model.get("num_leaves", _TREE_DEFAULTS["num_leaves"])
            if (model.get("_unresolved_expansion") or type(rounds) not in (int, float)
                    or type(leaves) not in (int, float)):
                model["tree_parameters"] = None
                continue
            rounds, leaves = int(rounds), int(leaves)
            if family == "GradientBoostingClassifier":
                leaves = 8
            # a binary tree with L leaves has L-1 split nodes (feature, threshold) and L leaf values
            model["tree_parameters"] = rounds * (3 * (leaves - 1) + leaves)
            estimate += model["tree_parameters"]
        elif family in _FOREST:
            model["tree_parameters"] = None  # leaf count depends on the data
        elif n_features is not None:
            model["linear_parameters"] = n_features + 1
            estimate += n_features + 1
    estimate_known = bool(models) and all(
        m.get("tree_parameters") is not None or m.get("linear_parameters") is not None for m in models)
    branches = sum(isinstance(n, (ast.If, ast.For, ast.While, ast.IfExp, ast.Try, ast.BoolOp, ast.comprehension))
                   for n in ast.walk(tree))
    return {
        "source_lines": sum(1 for line in code.splitlines() if line.strip() and not line.strip().startswith("#")),
        "ast_nodes": sum(1 for _ in ast.walk(tree)),
        "branch_points": branches,
        "functions": sum(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) for n in ast.walk(tree)),
        "model_families": sorted({m["family"] for m in models}),
        "ensemble_fits": folds if models else 0,
        "estimated_parameters": estimate * folds if estimate_known else None,
        "parameter_note": "静态估计：树模型按每棵树 4L-3 个数值上界计，交叉验证折数视为集成成员；"
                          "线性模型按 特征数+1；随机森林等依赖数据的模型不估计。",
    }


def _performance(evaluation: dict[str, Any] | None) -> dict[str, Any]:
    if not evaluation:
        return {}
    metric = evaluation.get("metric") or {}
    source = {**metric, "combined_score": evaluation.get("combined_score")}
    return {key: _number(source.get(key)) for key in PERFORMANCE_KEYS}


def _baseline_features(task: Path) -> int | None:
    """Feature count of the frozen init program, when it declares a FEATURES list."""
    try:
        tree = ast.parse((task / "init.py").read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return None
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "FEATURES" for t in node.targets):
            value = _constant(node.value)
            if isinstance(value, list):
                return len(value) + 4  # + vendor one-hot columns declared in init.py
    return None


def _node(db: Path, node_id: str | None, operator: str | None = None) -> tuple[str, dict | None] | None:
    with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as conn:
        if node_id:
            row = conn.execute("SELECT artifact_json, evidence_json FROM node WHERE id=?", (node_id,)).fetchone()
        else:
            row = conn.execute("SELECT artifact_json, evidence_json FROM node WHERE operator=? ORDER BY created_at LIMIT 1",
                               (operator,)).fetchone()
    if row is None:
        return None
    return json.loads(row[0])["code"], (json.loads(row[1] or "{}").get("evaluation"))


def _solution(label: str, code: str, evaluation: dict | None, features: int | None) -> dict[str, Any]:
    cost = _number((evaluation or {}).get("cost_time"))
    return {"label": label, "performance": _performance(evaluation),
            "complexity": {**program_complexity(code, features), "evaluation_seconds": cost}}


def _events(output: Path) -> list[dict[str, Any]]:
    path = output / "events.jsonl"
    rows = []
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict) and isinstance(row.get("type"), str):
                rows.append(row)
    return rows


def _epoch(ts: Any) -> float | None:
    try:
        return datetime.fromisoformat(str(ts)).timestamp()
    except ValueError:
        return None


def convergence_report(output: Path, summary: dict[str, Any], ledger: dict[str, Any] | None,
                       target: float | None, events: list[dict[str, Any]]) -> dict[str, Any]:
    """How fast the run got to its goal: rounds, wall time and tokens, plus the curve."""
    baseline = _number(summary.get("initial_score"))
    starts = [t for e in events if e["type"] in {"init_evaluated", "attempt_started"} and (t := _epoch(e.get("ts"))) is not None]
    origin = min(starts) if starts else None
    curve, best = [], baseline
    for event in events:
        payload = event.get("payload") or {}
        if event["type"] != "iteration_complete" or not payload.get("valid"):
            continue
        score = _number(payload.get("score"))
        if score is None:
            continue
        best = score if best is None else max(best, score)
        at = _epoch(event.get("ts"))
        curve.append({"round": len(curve) + 1, "score": score, "best_so_far": best,
                      "elapsed_s": round(at - origin, 1) if at is not None and origin is not None else None})
    trials = (ledger or {}).get("trials", [])
    hpo_curve, hpo_best, hpo_best_trial = [], None, None
    for trial in trials:
        score = _number(trial.get("evaluation", {}).get("score"))
        if score is not None and (hpo_best is None or score > hpo_best):
            hpo_best, hpo_best_trial = score, trial.get("trial_number")
        hpo_curve.append({"trial": trial.get("trial_number"), "best_so_far": hpo_best})
    reached = summary.get("rounds_to_target") is not None
    return {
        "target_score": target, "target_reached": reached if target is not None else None,
        "rounds_to_target": summary.get("rounds_to_target"), "time_to_target_s": _number(summary.get("time_to_target_s")),
        "tokens_to_target": _number(summary.get("tokens_to_target")),
        "evolution_rounds": summary.get("iterations_done"), "evolution_stop_reason": summary.get("stop_reason"),
        "evolution_curve": curve,
        "hpo_trials": len(trials), "hpo_best_trial": hpo_best_trial,
        "hpo_elapsed_s": _number((ledger or {}).get("elapsed_seconds")), "hpo_curve": hpo_curve,
        "hpo_stop_reason": (ledger or {}).get("stop_reason"),
    }


def automation_report(summary: dict[str, Any], ledger: dict[str, Any] | None,
                      events: list[dict[str, Any]], hierarchical: bool) -> dict[str, Any]:
    """Share of steps that ran with no human action, counted from the run's own event log."""
    count = lambda *kinds: sum(e["type"] in kinds for e in events)
    attempts = count("attempt_started")
    trials = len((ledger or {}).get("trials", []))
    stages = 2 + int(hierarchical)  # data checkup+recheck, code evolution, optional hierarchical tuning
    steps = stages + attempts + trials
    interventions = count("run_resumed", "run_interrupted")
    recovered = int(sum(_number(summary.get(k)) or 0 for k in ("precheck_fixes", "smoke_fixes", "repair_successes")))
    failed_unrecovered = int(_number(summary.get("adapter_errors")) or 0)
    return {
        "stages": stages, "evolution_attempts": attempts, "hpo_trials": trials, "total_steps": steps,
        "manual_interventions": interventions,
        "automatic_coverage": round(max(0.0, 1 - interventions / steps), 4) if steps else None,
        "end_to_end_unattended": interventions == 0,
        "self_recovered_failures": recovered, "unrecovered_adapter_errors": failed_unrecovered,
        "note": "步骤 = 数据处理与复检、代码演化、分层调优各算一步，加上每次演化尝试与每次调优试验；"
                "人工介入 = 事件日志中的中断与恢复次数。启动命令本身不计入；"
                "无法从日志观察到的线下操作（例如手工改配置后新建运行）不在统计内。",
    }


def build_effect_report(output: Path, db: Path, task: Path, summary: dict[str, Any],
                        ledger: dict[str, Any] | None, final_origin: str, final_node_id: str | None,
                        *, target_score: float | None = None, hierarchical: bool = True) -> dict[str, Any]:
    features = _baseline_features(task)
    solutions = []
    baseline = _node(db, None, "init")
    if baseline:
        solutions.append({"key": "baseline", **_solution("初始方案", baseline[0], baseline[1], features)})
    evolution = _node(db, summary.get("best_node_id"))
    per_structure = (ledger or {}).get("mode") == "per_structure"
    if evolution:
        label = "结构演化最优（已逐结构调优）" if per_structure else "代码演化最优"
        solutions.append({"key": "evolution", **_solution(label, evolution[0], evolution[1], None)})
    best = (ledger or {}).get("best_candidate")
    if final_origin == "hierarchical_hpo" and best:
        run = output / "hyperparameters/runs" / best["candidate_id"]
        evaluation = json.loads((run / "evaluation.json").read_text(encoding="utf-8"))
        solutions.append({"key": "final", **_solution("分层调优最终", (run / "candidate.py").read_text(encoding="utf-8"),
                                                       evaluation, None)})
    elif evolution:
        label = "最终方案（逐结构调优后选优）" if per_structure else "最终方案（来自代码演化）"
        solutions.append({"key": "final", **_solution(label, evolution[0], evolution[1], None)})
    keys = ("total_tokens", "generate_tokens", "reflect_tokens", "jev_tokens", "knowledge_tokens",
            "repair_tokens", "tokens_per_score_gain", "wall_time_s", "total_llm_latency_ms", "total_eval_time_s",
            "iterations_done")
    events = _events(output)
    return {"schema": "faultevolve.effect-report/v1", "split": "val", "solutions": solutions,
            "convergence": convergence_report(output, summary, ledger, target_score, events),
            "automation": automation_report(summary, ledger, events, hierarchical),
            "token_usage": {**{k: _number(summary.get(k)) for k in keys},
                            "hierarchical_tokens": 0,
                            "hierarchical_note": "分层调优只调用本地评估器，不消耗 LLM token。"},
            "note": "全部数值来自本地验证评估器与候选源码的静态分析；验证集上反复选择，尚不能证明独立泛化。"}
