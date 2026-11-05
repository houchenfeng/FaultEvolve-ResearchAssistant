"""Durable code-evolution and hierarchical-parameter research campaigns."""

from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import shutil
import signal
import sqlite3
import subprocess
import sys
import time
from typing import Any, Callable

from faultevolve.common.resources import limit_resources

_active_evaluation: subprocess.Popen | None = None


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def copy_tree(source: Path, destination: Path, *, knowledge_only: bool = False) -> None:
    """Copy content without directory metadata operations unsupported by SMB."""
    destination.mkdir(parents=True, exist_ok=True)
    for entry in source.iterdir():
        if knowledge_only and (entry.name in {"data", "eval_only", ".fe"} or entry.name.startswith("holdout")):
            continue
        if (entry.name in {"__pycache__", ".venv", ".git", "output"}
                or entry.name.startswith(".env") or entry.name.endswith((".pyc", ".egg-info"))):
            continue
        if entry.is_symlink():
            raise ValueError(f"快照不跟随符号链接：{entry.name}")
        target = destination / entry.name
        if entry.is_dir():
            copy_tree(entry, target, knowledge_only=knowledge_only)
        elif entry.is_file():
            if knowledge_only and entry.suffix.lower() not in {".md", ".yaml", ".yml", ".json", ".jsonl", ".txt"}:
                continue
            shutil.copyfile(entry, target)


def load_search(path: Path) -> Any:
    name = "fe_campaign_hierarchical_search"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ValueError("搜索引擎文件无法加载")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


TUNABLE = {
    "C", "learning_rate", "n_estimators", "num_leaves", "max_depth",
    "min_child_samples", "min_samples_leaf", "min_samples_split",
    "reg_alpha", "reg_lambda", "l2_regularization", "max_leaf_nodes",
    "num_boost_round", "max_iter", "subsample", "colsample_bytree",
}


def parameter_sites(tree: ast.AST) -> list[tuple[str, ast.AST, str, int | float]]:
    """Recognize explicit scalar model parameters without importing candidate code."""
    found = []
    for node in ast.walk(tree):
        entries: list[tuple[str, ast.AST, str]] = []
        if isinstance(node, ast.keyword) and node.arg in TUNABLE:
            entries.append((node.arg, node, "value"))
        elif isinstance(node, ast.Dict):
            for index, (key, value) in enumerate(zip(node.keys, node.values)):
                if isinstance(key, ast.Constant) and key.value in TUNABLE:
                    entries.append((str(key.value), node, f"values:{index}"))
        elif isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name) and target.id.isupper():
                name = next((k for k in TUNABLE if k.upper() == target.id), None)
                if name:
                    entries.append((name, node, "value"))
        for name, owner, field in entries:
            value = owner.values[int(field.split(":")[1])] if field.startswith("values:") else getattr(owner, field)
            try:
                number = ast.literal_eval(value)
            except (ValueError, TypeError):
                continue
            if type(number) in (int, float) and math.isfinite(number):
                found.append((name, owner, field, number))
    return found


def domain(name: str, value: int | float) -> list[int | float]:
    if value <= 0:
        return [value]
    factors = (0.5, 1.0, 2.0)
    values = [value]
    for factor in factors:
        v = value * factor
        if isinstance(value, int):
            v = max(2 if name in {"num_leaves", "min_samples_split", "max_leaf_nodes"} else 1, round(v))
        else:
            v = round(v, 9)
        if name in {"subsample", "colsample_bytree"}:
            v = min(1.0, v)
        values.append(v)
    return sorted(set(values))


def describe_route(route_id: str, code: str, source: str) -> dict[str, Any] | None:
    sites = parameter_sites(ast.parse(code))
    defaults, domains = {}, {}
    for index, (name, _, _, value) in enumerate(sites):
        values = domain(name, value)
        if len(values) > 1:
            key = f"p{index:03d}_{name}"
            defaults[key], domains[key] = value, values
    if not domains:
        return None
    families = set()
    for node in ast.walk(ast.parse(code)):
        if isinstance(node, ast.Call):
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            family = {"LogisticRegression": "logreg", "LGBMClassifier": "lightgbm"}.get(name)
            if family:
                families.add(family)
    return {"id": route_id, "default_parameters": defaults, "parameter_domains": domains,
            "source": source, "source_sha256": hashlib.sha256(code.encode()).hexdigest(),
            "model_families": sorted(families)}


def render_candidate(code: str, route: dict[str, Any], parameters: dict[str, Any]) -> str:
    if set(parameters) != set(route["default_parameters"]):
        raise ValueError("候选参数键与冻结契约不一致")
    if hashlib.sha256(code.encode()).hexdigest() != route["source_sha256"]:
        raise ValueError("冻结路线代码发生变化")
    for key, value in parameters.items():
        if type(value) not in (int, float) or value not in route["parameter_domains"][key]:
            raise ValueError("候选参数超出离散域")
    if parameters == route["default_parameters"]:
        return code
    tree = ast.parse(code)
    for index, (name, owner, field, _) in enumerate(parameter_sites(tree)):
        key = f"p{index:03d}_{name}"
        if key not in parameters:
            continue
        replacement = ast.Constant(value=parameters[key])
        if field.startswith("values:"):
            owner.values[int(field.split(":")[1])] = replacement
        else:
            setattr(owner, field, replacement)
    ast.fix_missing_locations(tree)
    return ast.unparse(tree) + "\n"


def snapshot_database(source: Path, local_snapshot: Path, destination: Path) -> None:
    """Use SQLite locally, then publish plain bytes to network storage."""
    local_snapshot.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(f"file:{source}?mode=ro", uri=True) as src, sqlite3.connect(local_snapshot) as dst:
        src.backup(dst)
        dst.execute("PRAGMA journal_mode=DELETE")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".db.tmp")
    shutil.copyfile(local_snapshot, temporary)
    temporary.replace(destination)


def evaluate_val(code_path: Path, evaluator_path: Path, result_path: Path) -> dict[str, Any]:
    """Put the evaluator and its candidate in a cancellable process group."""
    global _active_evaluation
    command = [sys.executable, "-m", "faultevolve.research_campaign", "evaluate",
               "--candidate", str(code_path), "--evaluator", str(evaluator_path),
               "--result", str(result_path), "--cpu-limit", os.environ.get("FE_RESEARCH_CPU_LIMIT", "8")]
    with result_path.with_suffix(".log").open("w") as log:
        _active_evaluation = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            code = _active_evaluation.wait(timeout=960)
        except BaseException:
            if _active_evaluation.poll() is None:
                os.killpg(_active_evaluation.pid, signal.SIGTERM)
                try:
                    _active_evaluation.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(_active_evaluation.pid, signal.SIGKILL)
                    _active_evaluation.wait()
            raise
        finally:
            _active_evaluation = None
    if code != 0 or not result_path.is_file():
        return {"validity": 0, "combined_score": 0, "error_info": "评估子进程失败，查看 evaluation.log"}
    return json.loads(result_path.read_text())


def prepare(args: argparse.Namespace) -> None:
    from faultevolve.cli import detect_network_fs, load_env_file
    from faultevolve.config import EvolveConfig

    repo, output = args.repo.resolve(), args.output.resolve()
    if output.exists():
        raise ValueError("输出目录已存在；运行已有任务请使用 run")
    local = args.local_runs.resolve()
    if detect_network_fs(local)[0]:
        raise ValueError("SQLite 运行目录必须在本地磁盘")
    load_env_file(args.env.resolve())
    config = args.config.resolve()
    cfg = EvolveConfig.from_yaml(config)
    if cfg.workflow.enabled:
        cfg.workflow.hierarchical.max_trials = args.hpo_trials
    if not cfg.llm.stream:
        raise ValueError("本次正式运行需要流式 LLM")
    task = args.task.resolve()
    output.mkdir(parents=True)
    snapshot = output / "snapshot"
    snapshot.mkdir()
    copy_tree(repo / "src", snapshot / "src")
    copy_tree(repo / "autoresearch-hierarchical-search-cn", snapshot / "hierarchical-search")
    copy_tree(repo / "skill/fe-research-agent", output / "skill/fe-research-agent")
    frozen_task = snapshot / "task"
    frozen_task.mkdir()
    for name in ("evaluator.py", "init.py", "problem.md", "prompt.md"):
        shutil.copyfile(task / name, frozen_task / name)
    if cfg.knowledge.dir:
        knowledge = Path(cfg.knowledge.dir)
        source = task / knowledge
        if (knowledge.is_absolute() or not knowledge.parts or ".." in knowledge.parts
                or not source.resolve().is_relative_to(task)
                or source.resolve().relative_to(task).parts[0] in {"data", ".fe"}
                or source.is_symlink()):
            raise ValueError("知识目录不能指向任务数据或运行目录")
        if source.is_dir():
            copy_tree(source, frozen_task / knowledge, knowledge_only=True)
    if cfg.workflow.enabled:
        write_json(frozen_task / "evolve.yaml", cfg.model_dump(mode="json"))
        write_json(output / "effective_config.yaml", cfg.model_dump(mode="json"))
    else:
        shutil.copyfile(config, frozen_task / "evolve.yaml")
        shutil.copyfile(config, output / "effective_config.yaml")
    dependencies = subprocess.run([sys.executable, "-m", "pip", "freeze"], capture_output=True, text=True)
    if dependencies.returncode == 0:
        (snapshot / "requirements-frozen.txt").write_text(dependencies.stdout)
    else:
        from importlib.metadata import distributions
        (snapshot / "requirements-frozen.txt").write_text("\n".join(sorted(
            f"{d.metadata['Name']}=={d.version}" for d in distributions())) + "\n")
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True)
    manifest = {"campaign_id": output.name, "created_at": time.time(), "repo": str(repo),
                "git_commit": commit.stdout.strip(), "local_runs": str(local),
                "env_file": str(args.env.resolve()),
                "data_root": str(Path(os.environ.get("HDD_BENCH_DATA_ROOT", str(task / "data"))).resolve()),
                "model": cfg.llm.generate_model, "stream": cfg.llm.stream,
                "effective_config_sha256": digest(output / "effective_config.yaml"),
                "base_url": os.environ.get("DASHSCOPE_BASE_URL", "").strip() or cfg.llm.base_url,
                "iterations": cfg.budget.max_iterations, "hpo_trials": args.hpo_trials,
                "cpu_limit": args.cpu_limit,
                "llm_progress_interval_s": 10,
                "hpo_wall_seconds": 12 * 3600, "holdout": "未运行；私有集不参与本流程",
                "files": {str(p.relative_to(snapshot)): digest(p) for p in sorted(snapshot.rglob("*"))
                          if p.is_file()}}
    write_json(output / "manifest.json", manifest)
    write_json(output / "status.json", {"state": "prepared", "phase": "prepare", "updated_at": time.time()})
    print(json.dumps({"output": str(output), "iterations": manifest["iterations"],
                      "model": manifest["model"], "hpo_trials": args.hpo_trials}, ensure_ascii=False))


def choose_routes(db: Path, output: Path, *, template_fallback: bool = True) -> list[dict[str, Any]]:
    routes = []
    selected = set()
    sources = set()
    with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as conn:
        rows = conn.execute("SELECT id,island_id,artifact_json,evidence_json FROM node").fetchall()
    scored = []
    for node_id, island, artifact, evidence in rows:
        evaluation = json.loads(evidence or "{}").get("evaluation") or {}
        score = evaluation.get("combined_score", 0)
        if evaluation.get("validity") == 1.0 and math.isfinite(score):
            scored.append((score, node_id, island, json.loads(artifact)["code"]))
    scored.sort(key=lambda row: (-row[0], row[1]))
    for _, node_id, island, code in scored:
        if island in selected:
            continue
        route = describe_route(f"island_{island}_{node_id}", code, f"evolution:{node_id}")
        if route is None and not template_fallback:
            route = {"id": f"island_{island}_{node_id}", "source": f"evolution:{node_id}",
                "source_sha256": hashlib.sha256(code.encode()).hexdigest(),
                "default_parameters": {}, "parameter_domains": {}, "model_families": []}
        if route is not None and route["source_sha256"] not in sources:
            route_dir = output / "routes"
            route_dir.mkdir(parents=True, exist_ok=True)
            path = route_dir / (route["id"] + ".py")
            path.write_text(code)
            route["code_path"] = str(path)
            routes.append(route)
            selected.add(island)
            sources.add(route["source_sha256"])
    if len(routes) < 2 and template_fallback:
        from faultevolve.optimization.candidate_spec import compile_spec
        from faultevolve.tasks.hdd_space import default_spec
        from faultevolve.tasks.hdd_templates import TEMPLATE_MAP
        represented = {family for route in routes for family in route["model_families"]}
        for family in ("logreg", "lightgbm"):
            if family in represented:
                continue
            code = compile_spec(default_spec(family), TEMPLATE_MAP).code
            route = describe_route(f"structured_{family}", code, f"template:{family}")
            if route and route["source_sha256"] not in sources:
                path = output / "routes" / (route["id"] + ".py")
                path.parent.mkdir(exist_ok=True)
                path.write_text(code)
                route["code_path"] = str(path)
                routes.append(route)
                sources.add(route["source_sha256"])
            if len(routes) >= 2:
                break
    return routes


def hierarchical_search(output: Path, db: Path, manifest: dict[str, Any], *,
                        routes: list[dict[str, Any]] | None = None,
                        hpo_dir: Path | None = None,
                        evaluate: Callable | None = None,
                        can_dispatch: Callable[[], bool] | None = None,
                        on_trial: Callable[[], Any] | None = None) -> dict[str, Any]:
    hpo = hpo_dir or output / "hyperparameters"
    hpo.mkdir(parents=True, exist_ok=True)
    cpu_limit = int(os.environ.get("FE_RESEARCH_CPU_LIMIT", "8"))
    search = load_search(Path(manifest.get("search_engine_path", output / "snapshot/hierarchical-search/scripts/search_engine.py")))
    evaluator = Path(manifest.get("evaluator_path", output / "snapshot/task/evaluator.py"))
    spec_path = hpo / "experiment_spec.json"
    if spec_path.exists():
        spec = json.loads(spec_path.read_text())
    else:
        fixed_routes = routes is not None
        routes = routes if fixed_routes else choose_routes(db, hpo)
        spec = {"version": "faultevolve.hierarchical/v1", "routes": routes,
                "metric": {"key": "combined_score", "direction": "maximize", "min_delta": 0.01},
                "budgets": {"max_trials": manifest["hpo_trials"],
                            "max_wall_seconds": manifest["hpo_wall_seconds"], "max_parallel_trials": 1},
                "search": {"beam_width": 3, "exploration_slots": 1, "route_exploration_c": 0.35,
                           "node_exploration_c": 0.35, "virtual_visit_penalty": 0.05,
                           "duration_weight": 0, "failure_penalty": 1, "metric_scale_floor": 1},
                "evaluation": {"split": manifest.get("evaluation_split", "val"), "evaluator_sha256": digest(evaluator),
                               "repetitions": 1, "aggregation": "mean", "timeout_seconds": 900,
                               "cpu_limit": cpu_limit,
                               "data_fingerprint": manifest.get("validation_files", {}),
                               "concurrency_mode": "serial/v1"},
                "holdout": {"enabled": False, "reason": "私有测试集禁止读取"}}
        if "adapter_identity" in manifest:
            spec["evaluation"]["adapter_identity"] = manifest["adapter_identity"]
            spec["evaluation"]["cache_evaluations"] = manifest.get("cache_evaluations", False)
        if manifest.get("research"):
            spec["research"] = manifest["research"]
        if fixed_routes:
            spec["search"]["allow_single_route"] = True
        write_json(spec_path, spec)
    if spec.get("research") != manifest.get("research"):
        raise ValueError("科研目标与冻结搜索契约不一致")
    if routes is not None and spec["routes"] != routes:
        raise ValueError("候选结构与冻结调优契约不一致")
    if digest(evaluator) != spec["evaluation"]["evaluator_sha256"]:
        raise ValueError("冻结评估器发生变化")
    if spec["evaluation"]["split"] != manifest.get("evaluation_split", "val"):
        raise ValueError("任务评估划分与冻结搜索契约不一致")
    if spec["evaluation"].get("adapter_identity") != manifest.get("adapter_identity"):
        raise ValueError("任务适配器与冻结搜索契约不一致")
    if spec["evaluation"]["data_fingerprint"] != manifest.get("validation_files", {}):
        raise ValueError("数据指纹与冻结搜索契约不一致")
    if spec["evaluation"].get("cpu_limit", cpu_limit) != cpu_limit:
        raise ValueError("CPU 配额与冻结搜索契约不一致")
    engine = search.SearchEngine(spec)
    ledger_path = hpo / "ledger.json"
    prior_elapsed = 0.0
    if ledger_path.exists():
        old = json.loads(ledger_path.read_text())
        if old["contract_hash"] != engine.contract_hash:
            raise ValueError("搜索契约哈希发生变化")
        prior_elapsed = old["elapsed_seconds"]
        for trial in old["trials"]:
            candidate = engine.reserve_next(0)
            if candidate is None or candidate.candidate_id != trial["candidate_id"]:
                raise ValueError("账本不能确定性重放")
            result = trial["evaluation"]
            engine.record_result(candidate.candidate_id, search.EvaluationResult(
                result["succeeded"], result["score"], result["samples"],
                trial["execution"]["duration_seconds"], result["integrity_passed"],
                result["evidence"], result["error"]))
        if old.get("stop_reason") == "research_goal_reached":
            engine.stop_reason = "research_goal_reached"
    started = time.monotonic()
    while True:
        if can_dispatch is not None and not can_dispatch():
            engine.stop_reason = "external_budget_exhausted"
            break
        candidate = engine.reserve_next(prior_elapsed + time.monotonic() - started)
        if candidate is None:
            break
        route = engine.routes[candidate.route_id]
        trial_dir = hpo / "runs" / candidate.candidate_id
        trial_dir.mkdir(parents=True, exist_ok=True)
        result_file = trial_dir / "evaluation.json"
        reservation_file = trial_dir / "reservation.json"
        interrupted = reservation_file.exists() and not result_file.exists()
        code = render_candidate(Path(route["code_path"]).read_text(), route, candidate.parameters)
        (trial_dir / "candidate.py").write_text(code)
        write_json(reservation_file, {"candidate_id": candidate.candidate_id, "parameters": candidate.parameters,
                                      "execution_id": candidate.execution_id, "contract_hash": engine.contract_hash})
        before = time.monotonic()
        source_sha256 = digest(trial_dir / "candidate.py")
        cache_key = hashlib.sha256(json.dumps({
            "version": "faultevolve.evaluation-cache/v1", "source_sha256": source_sha256,
            "evaluation": spec["evaluation"], "cpu_limit": cpu_limit,
        }, sort_keys=True, allow_nan=False).encode()).hexdigest()
        cache_file = hpo / "evaluation-cache" / (cache_key + ".json")
        cache_enabled = spec["evaluation"].get("cache_evaluations", True)
        cached = json.loads(cache_file.read_text()) if cache_enabled and cache_file.is_file() else None
        if cached and (cached.get("key") != cache_key or cached.get("source_sha256") != source_sha256):
            raise ValueError("评估缓存指纹不匹配")
        reused = False
        if result_file.exists():
            evaluation = json.loads(result_file.read_text())
        elif cached:
            evaluation = cached["evaluation"]
            reused = True
        elif interrupted:
            evaluation = {"validity": 0, "combined_score": 0, "error_info": "上次执行中断，未重复评估"}
        else:
            evaluation = (evaluate or evaluate_val)(trial_dir / "candidate.py", evaluator, result_file)
        # Persist only finite JSON, including a failed evaluator's metrics.
        from faultevolve.research import _json_safe
        write_json(result_file, _json_safe(evaluation))
        score = evaluation.get("combined_score")
        valid = (evaluation.get("validity") == 1.0 and type(score) in (int, float) and math.isfinite(score))
        duration = cached["duration_seconds"] if reused else time.monotonic() - before
        evidence = {"result_file": str(result_file), "source_sha256": source_sha256,
                    "cache_key": cache_key, "cache_hit": reused}
        if reused:
            evidence["cached_from_candidate_id"] = cached["candidate_id"]
        elif valid and cache_enabled:
            # Cache only successful local evaluations, scoped to frozen inputs,
            # evaluator protocol and CPU policy. Never cache infrastructure errors.
            write_json(cache_file, {"key": cache_key, "source_sha256": source_sha256,
                                   "candidate_id": candidate.candidate_id,
                                   "duration_seconds": duration, "evaluation": _json_safe(evaluation)})
        result = search.EvaluationResult(valid, score if valid else None,
                    [score] if valid else [], duration, valid, [evidence],
                    evaluation.get("error_info") or None)
        engine.record_result(candidate.candidate_id, result)
        if manifest.get("research"):
            from faultevolve.common.research import ResearchConfig, assess_goals
            if assess_goals(ResearchConfig.model_validate(manifest["research"]), evaluation)["achieved"]:
                engine.stop_reason = "research_goal_reached"
        write_json(ledger_path, engine.ledger(prior_elapsed + time.monotonic() - started))
        if on_trial is not None:
            on_trial()
        write_json(output / "status.json", {"state": "running", "phase": "hyperparameters",
                   "completed_trials": engine.completion_count, "updated_at": time.time(),
                   **({"structure_node_id": manifest["structure_node_id"]} if manifest.get("structure_node_id") else {})})
    engine.mark_exhausted_if_idle()
    ledger = engine.ledger(prior_elapsed + time.monotonic() - started)
    write_json(ledger_path, ledger)
    write_json(hpo / "summary.json", {"stop_reason": ledger["stop_reason"],
                                     "best_candidate": ledger["best_candidate"], "holdout": None})
    return ledger


def finalize(output: Path, db: Path, manifest: dict[str, Any], ledger: dict[str, Any]) -> None:
    summary = json.loads((output / "evolution" / manifest["campaign_id"] / "run_summary.json").read_text())
    best = ledger.get("best_candidate")
    evolved_score = summary["best_score"]
    results = output / "results"
    results.mkdir(exist_ok=True)
    if best and best["score"] > evolved_score:
        source = output / "hyperparameters/runs" / best["candidate_id"] / "candidate.py"
        best_score, origin = best["score"], "hierarchical_hpo"
    else:
        source = output / "evolution" / manifest["campaign_id"] / "programs" / (summary["best_node_id"] + ".py")
        best_score, origin = evolved_score, "code_evolution"
    shutil.copyfile(source, results / "best.py")
    report = {"state": "finished", "model": manifest["model"], "evolution_iterations": summary["iterations_done"],
              "evolution_best_val_ros": evolved_score, "evolution_stop_reason": summary.get("stop_reason"),
              "total_llm_tokens": summary.get("total_tokens"), "cost": summary.get("cost"),
              "hpo_trials": ledger["completion_count"],
              "hpo_stop_reason": ledger["stop_reason"], "best_val_ros": best_score, "best_origin": origin,
              "best_source_sha256": digest(results / "best.py"), "holdout": "未运行；未读取私有测试集",
              "limitations": ["验证集反复选择可能过拟合，尚未证明泛化", "有限离散域 UCT-style，不保证全局最优",
                              "单进程串行协调；未验证分布式恢复与跨任务先验"]}
    write_json(results / "report.json", report)
    text = (f"# 正式科研自动化运行结果\n\n模型：{manifest['model']}。\n\n"
            f"代码进化完成 {summary['iterations_done']} 次，最佳 val ROS={evolved_score:.6f}。\n\n"
            f"分层参数搜索完成 {ledger['completion_count']} 次，停止原因：{ledger['stop_reason']}。\n\n"
            f"最终最佳 val ROS={best_score:.6f}，来源：{origin}。\n\n"
            "私有测试集未运行，不声明泛化性能。分数均来自冻结的本地评估器。\n")
    (results / "报告.md").write_text(text)
    references = output / "skill/fe-research-agent/references"
    references.mkdir(exist_ok=True)
    shutil.copyfile(results / "report.json", references / "latest-result.json")
    shutil.copyfile(results / "报告.md", references / "latest-result.md")
    snapshot_database(db, Path(manifest["local_runs"]) / manifest["campaign_id"] / "snapshot.sqlite",
                      output / "database/fe.db")
    shutil.make_archive(str(output / "fe-research-agent"), "zip", output / "skill", "fe-research-agent")
    write_json(output / "status.json", {"state": "finished", "phase": "complete", "updated_at": time.time(), **report})


def run(output: Path) -> None:
    from faultevolve.cli import load_env_file
    from faultevolve.worker.runner import load_evaluator, run_candidate

    output = output.resolve()
    manifest = json.loads((output / "manifest.json").read_text())
    limit_resources(manifest.get("cpu_limit", 8))
    status = json.loads((output / "status.json").read_text())
    if status["state"] == "finished":
        print("任务已经完成；请读取 results/report.json")
        return
    for relative, expected in manifest["files"].items():
        if digest(output / "snapshot" / relative) != expected:
            raise ValueError(f"快照哈希不一致：{relative}")
    if digest(output / "effective_config.yaml") != manifest["effective_config_sha256"]:
        raise ValueError("执行配置与冻结配置哈希不一致")
    load_env_file(Path(manifest["env_file"]))
    os.environ["HDD_BENCH_DATA_ROOT"] = manifest["data_root"]
    os.environ["DASHSCOPE_BASE_URL"] = manifest["base_url"]
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    os.environ["FE_LLM_PROGRESS_DIR"] = str(output / "llm")
    os.environ["FE_LLM_PROGRESS_INTERVAL_S"] = str(manifest.get("llm_progress_interval_s", 10))
    task = output / "snapshot/task"
    local = Path(manifest["local_runs"])
    db = local / manifest["campaign_id"] / "fe.db"
    child: subprocess.Popen | None = None

    def interrupted(signum: int, frame: Any) -> None:
        if child is not None and child.poll() is None:
            os.killpg(child.pid, signal.SIGTERM)
        raise InterruptedError("运行被中断")

    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    try:
        from faultevolve.config import EvolveConfig
        cfg = EvolveConfig.from_yaml(output / "effective_config.yaml")
        if cfg.workflow.enabled:
            # New campaigns use exactly the same orchestrator as fe run/Web.
            # The remaining branch keeps historical frozen campaigns resumable.
            from faultevolve.cloud.engine import run_local_evolution
            result = run_local_evolution(task_dir=task, config_path=output / "effective_config.yaml",
                runs_dir=local, artifacts_dir=output.parent,
                resume_id=manifest["campaign_id"] if db.is_file() else None,
                experiment_id=None if db.is_file() else manifest["campaign_id"])
            if result.get("workflow"):
                results = output / "results"
                results.mkdir(exist_ok=True)
                shutil.copyfile(output / "workflow-best.py", results / "best.py")
                write_json(results / "report.json", result["workflow"])
            write_json(output / "status.json", {"state": result["status"], "phase": "complete",
                       "updated_at": time.time()})
            return
        if not (output / "baseline.json").exists():
            evaluator = load_evaluator(task / "evaluator.py")
            located, labels = evaluator.locate_split("val")
            if located is None:
                raise ValueError("验证数据不可用")
            manifest["validation_files"] = {p.name: digest(p) for p in [*located.values(), labels]}
            write_json(output / "manifest.json", manifest)
            baseline = evaluate_val(task / "init.py", task / "evaluator.py", output / "baseline.json")
            write_json(output / "baseline.json", baseline)
            if baseline.get("validity") != 1.0:
                raise ValueError("基线评估失败")
        write_json(output / "status.json", {"state": "running", "phase": "evolution", "updated_at": time.time()})
        done = False
        if db.exists():
            with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as conn:
                row = conn.execute("SELECT status,iterations_done FROM experiment WHERE id=?", (manifest["campaign_id"],)).fetchone()
                done = bool(row and row[0] == "finished")
        if not done:
            command = [sys.executable, "-m", "faultevolve.cli", "evolve", "local", str(task),
                       "--config-file", str(output / "effective_config.yaml"), "-n", str(manifest["iterations"]),
                       "--runs-dir", str(local), "--artifacts-dir", str(output / "evolution")]
            command += ["--resume" if db.exists() else "--run-id", manifest["campaign_id"]]
            env = os.environ.copy()
            env["PYTHONPATH"] = str(output / "snapshot/src")
            with (output / "evolution.log").open("a") as log:
                child = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, env=env, start_new_session=True)
                last_snapshot = 0.0
                while child.poll() is None:
                    try:
                        if db.exists():
                            with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as conn:
                                row = conn.execute("SELECT status,iterations_done,best_score FROM experiment WHERE id=?",
                                                   (manifest["campaign_id"],)).fetchone()
                            if row:
                                live_path = output / "llm/live.json"
                                live = json.loads(live_path.read_text()) if live_path.exists() else {}
                                write_json(output / "status.json", {"state": "running", "phase": "evolution",
                                           "evolution_state": row[0], "iterations_done": row[1],
                                           "best_val_ros": row[2], "updated_at": time.time(),
                                           "llm_progress": {"updated_at": live.get("updated_at"),
                                               "active_requests": live.get("active_requests", []),
                                               "total_reported_tokens": live.get("total_reported_tokens"),
                                               "requests_without_reported_usage": live.get("requests_without_reported_usage", 0)}})
                                if time.monotonic() - last_snapshot >= 300:
                                    snapshot_database(db, local / manifest["campaign_id"] / "snapshot.sqlite",
                                                      output / "database/fe.db")
                                    last_snapshot = time.monotonic()
                        child.wait(timeout=30)
                    except subprocess.TimeoutExpired:
                        pass
                code = child.returncode
            if code != 0:
                raise RuntimeError(f"代码进化退出码 {code}；详情见 evolution.log")
        with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as conn:
            finished = conn.execute("SELECT status FROM experiment WHERE id=?", (manifest["campaign_id"],)).fetchone()
        if not finished or finished[0] != "finished":
            raise RuntimeError("进化尚未结束，不启动参数搜索；检查状态后恢复")
        snapshot_database(db, local / manifest["campaign_id"] / "snapshot.sqlite", output / "database/fe.db")
        write_json(output / "status.json", {"state": "running", "phase": "hyperparameters", "updated_at": time.time()})
        ledger = hierarchical_search(output, db, manifest)
        finalize(output, db, manifest, ledger)
    except BaseException as exc:
        write_json(output / "status.json", {"state": "interrupted" if isinstance(exc, (InterruptedError, KeyboardInterrupt)) else "failed",
                   "phase": json.loads((output / "status.json").read_text()).get("phase"),
                   "error_type": type(exc).__name__, "updated_at": time.time(), "details": "查看 campaign.log 与 evolution.log"})
        if db.exists():
            snapshot_database(db, local / manifest["campaign_id"] / "snapshot.sqlite", output / "database/fe.db")
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description="代码进化 → 分层超参数搜索 → 科研 Agent Skill")
    sub = parser.add_subparsers(dest="action", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--repo", type=Path, default=Path.cwd())
    prep.add_argument("--task", type=Path, default=Path("benchmark/hdd_mvp"))
    prep.add_argument("--config", type=Path, default=Path("benchmark/hdd_mvp/evolve.yaml"))
    prep.add_argument("--env", type=Path, default=Path(".env"))
    prep.add_argument("--output", type=Path, required=True)
    prep.add_argument("--local-runs", type=Path, required=True)
    prep.add_argument("--hpo-trials", type=int, default=24)
    prep.add_argument("--cpu-limit", type=int, default=8)
    execute = sub.add_parser("run")
    execute.add_argument("--output", type=Path, required=True)
    evaluate = sub.add_parser("evaluate")
    evaluate.add_argument("--candidate", type=Path, required=True)
    evaluate.add_argument("--evaluator", type=Path, required=True)
    evaluate.add_argument("--result", type=Path, required=True)
    evaluate.add_argument("--cpu-limit", type=int, default=8)
    args = parser.parse_args()
    if args.action == "prepare":
        if args.hpo_trials < 5:
            parser.error("至少预留 5 次参数评估，覆盖默认路线与参数扩展")
        if args.cpu_limit < 1:
            parser.error("CPU 配额必须大于 0")
        prepare(args)
    elif args.action == "run":
        run(args.output)
    else:
        if args.cpu_limit < 1:
            parser.error("CPU 配额必须大于 0")
        limit_resources(args.cpu_limit)
        from faultevolve.worker.runner import run_candidate
        write_json(args.result, run_candidate(args.candidate.read_text(), args.evaluator, split="val", timeout=900))


if __name__ == "__main__":
    main()
