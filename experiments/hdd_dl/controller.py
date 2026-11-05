"""Bounded, resumable deep-learning architecture/config evolution on frozen HDD scoring.

Run this trusted controller on the lab host. Candidate source never receives
evaluation labels. A campaign lock serializes GPU/evaluator access; trial state
and source live on NAS, with no persistent training checkpoints in this MVP.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import importlib.metadata
import json
import math
import os
from pathlib import Path
import random
import shutil
import subprocess
import sys
import time

HIGHER = ["precision", "recall", "f1", "f1_p10", "auprc", "recall_at_far", "quality"]
LOWER = ["false_alarm_rate", "missed_detection_rate", "f1_boot_std", "run_time_s"]
QUALITY_KEYS = HIGHER + ["false_alarm_rate", "missed_detection_rate", "f1_boot_std"]


def quality_gate(comparison_row):
    """Require every prediction/stability metric; runtime and ROS are descriptive."""
    metrics = comparison_row.get("metrics", {})
    return all(metrics.get(key, {}).get("better") is True for key in QUALITY_KEYS)


SPACE = dict(family=["mlp", "tcn", "gru", "dual"], width=[64, 128, 256], depth=[1, 2, 3],
             dropout=[0.0, 0.1, 0.25, 0.4], lr=[0.0003, 0.001, 0.003],
             weight_decay=[0.00001, 0.001, 0.01], batch_size=[256, 512, 1024],
             epochs=[30, 60, 100], positive_boost=[1.0, 3.0, 10.0, 30.0],
             threshold_scale=[0.8, 0.9, 1.0, 1.05, 1.1, 1.15, 1.2], normalization=["standard", "quantile"],
             folds=[1, 3], feature_set=["basic", "trends"], focal_gamma=[0.0, 1.0, 2.0],
             model_identity=[False, True], smart_subset=["all", "reliability"],
             epoch_objective=["auprc", "operational_proxy"], replicas=[1, 3],
             ranking_weight=[0.0, 0.1, 0.3], device_context=[False, True],
             tree_blend=[0.0, 0.25, 0.5], fold_calibration=["raw", "threshold_ratio"],
             tabm_members=[0, 8], tabm_embedding=["none", "periodic"],
             share_fold_preprocessing=[False, True], share_fold_tree=[False, True])
DEFAULT = dict(family="mlp", width=128, depth=2, dropout=0.1, lr=0.001,
               weight_decay=0.001, batch_size=1024, epochs=60, positive_boost=3.0,
               threshold_scale=1.0, seed=20261020, train_seconds=240,
               normalization="standard", folds=1, feature_set="basic",
               focal_gamma=0.0, model_identity=False, smart_subset="all", epoch_objective="auprc",
               replicas=1, ranking_weight=0.0, device_context=True, tree_blend=0.25,
               fold_calibration="raw", tabm_members=0, tabm_embedding="none",
               share_fold_preprocessing=False, share_fold_tree=False)


def canonical_config(config):
    """Collapse inactive or incompatible choices before evaluation and deduplication."""
    config = {**DEFAULT, **config}
    if config["tabm_members"] == 0:
        config["tabm_embedding"] = "none"
    if (not config["share_fold_preprocessing"] or not config["tree_blend"]
            or config.get("tree_residual", False) or config.get("hybrid_selection", False)):
        config["share_fold_tree"] = False
    return config


def package_versions():
    versions = {p: importlib.metadata.version(p) for p in
                ["torch", "numpy", "pandas", "scikit-learn", "lightgbm"]}
    for name in ("tabm", "rtdl_num_embeddings"):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    return versions


def write_json(path, value):
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")
    temp.replace(path)


def sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def comparison(candidate, baseline):
    if candidate.get("validity") != 1 or baseline.get("validity") != 1:
        return {"all_predictive_strictly_better": False, "all_including_resources_strictly_better": False,
                "all_quality_strictly_better": False, "reason": "invalid_or_missing_evaluation"}
    rows = {}
    for key in HIGHER + LOWER + ["combined_score"]:
        a = candidate.get("metric", {}).get(key) if key != "combined_score" else candidate.get(key)
        b = baseline.get("metric", {}).get(key) if key != "combined_score" else baseline.get(key)
        valid = isinstance(a, (float, int)) and isinstance(b, (float, int))
        valid = valid and math.isfinite(a) and math.isfinite(b)
        rows[key] = {"candidate": a, "baseline": b,
                     "better": bool(valid and (a < b if key in LOWER else a > b))}
    predictive = HIGHER + ["false_alarm_rate", "missed_detection_rate", "combined_score"]
    return {"metrics": rows,
            "all_predictive_strictly_better": all(rows[k]["better"] for k in predictive),
            "all_quality_strictly_better": quality_gate({"metrics": rows}),
            "all_including_resources_strictly_better": all(r["better"] for r in rows.values()),
            "note": "Single validation evaluation; not independent generalization or statistical proof."}


def guard(nas, output, min_local_gb=150):
    fs = subprocess.check_output(["findmnt", "-n", "-T", str(nas), "-o", "FSTYPE"], text=True).strip()
    source = subprocess.check_output(["findmnt", "-n", "-T", str(nas), "-o", "SOURCE"], text=True).strip()
    if fs != "cifs" or source != "//10.62.192.79/public/hcf_data":
        raise RuntimeError("NAS mount identity mismatch; refusing fallback writes")
    output.resolve().relative_to(nas.resolve() / "faultevolve-dl")
    if shutil.disk_usage("/home/hcf").free < min_local_gb * 1024**3:
        raise RuntimeError("Local free-space floor reached")
    if shutil.disk_usage(nas).free < 100 * 1024**3:
        raise RuntimeError("NAS free-space floor reached")
    used = sum(p.stat().st_size for p in output.rglob("*") if p.is_file()) if output.exists() else 0
    if used > 50 * 1024**3:
        raise RuntimeError("Campaign 50 GiB quota reached")


def render(template, config):
    tree = ast.parse(template)
    assignment = next(n for n in tree.body if isinstance(n, ast.Assign)
                      and any(isinstance(t, ast.Name) and t.id == "CONFIG" for t in n.targets))
    lines = template.splitlines()
    lines[assignment.lineno - 1:assignment.end_lineno] = ["CONFIG = " + repr(config)]
    return "\n".join(lines) + "\n"


def weakest_margin(record, include_resources=False):
    """Worst relative predictive gap across all declared ML baselines."""
    gaps = []
    for comparison_row in record.get("comparisons", []):
        metrics = comparison_row.get("metrics", {})
        keys = HIGHER + ["combined_score", "false_alarm_rate", "missed_detection_rate"]
        if include_resources:
            keys += ["f1_boot_std", "run_time_s"]
        for key in keys:
            item = metrics.get(key, {})
            a, b = item.get("candidate"), item.get("baseline")
            if not isinstance(a, (float, int)) or not isinstance(b, (float, int)):
                return -math.inf
            if not math.isfinite(a) or not math.isfinite(b):
                return -math.inf
            gaps.append(((b - a) if key in LOWER else (a - b)) / max(abs(b), 1e-6))
    return min(gaps) if gaps else -math.inf


def quality_margin(record):
    """Worst relative prediction/stability gap; ignore runtime and ROS."""
    if record.get("result", {}).get("validity") != 1 or not record.get("comparisons"):
        return -math.inf
    gaps = []
    for comparison_row in record["comparisons"]:
        for key in QUALITY_KEYS:
            item = comparison_row.get("metrics", {}).get(key, {})
            a, b = item.get("candidate"), item.get("baseline")
            if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in (a, b)):
                return -math.inf
            gaps.append(((b - a) if key in LOWER else (a - b)) / max(abs(b), 1e-6))
    return min(gaps)


def resource_margin(record):
    """Worst gap including stability and runtime, without relaxing predictive gates."""
    return weakest_margin(record, include_resources=True)


def predictive_resource_rank(record):
    """Never trade an unmet predictive constraint for a runtime improvement."""
    if record.get("result", {}).get("validity") != 1:
        return (-1, -math.inf, -math.inf)
    predictive = weakest_margin(record)
    resources = resource_margin(record)
    if not math.isfinite(predictive) or not math.isfinite(resources):
        return (-1, -math.inf, -math.inf)
    if predictive > 0:
        return (1, resources, predictive)
    return (0, predictive, resources)


def seed_configs(records):
    valid = [r for r in records if r.get("result", {}).get("validity") == 1]
    ranked = sorted(valid, key=lambda r: r["result"]["combined_score"], reverse=True)[:3]
    ranked += sorted(valid, key=weakest_margin, reverse=True)[:3]
    configs = []
    for record in ranked:
        config = {**DEFAULT, **record["config"]}
        if any(key not in DEFAULT for key in config):
            raise ValueError("Seed contains an unsupported configuration key")
        if any(config[key] not in values for key, values in SPACE.items()):
            raise ValueError("Seed contains an unsupported configuration value")
        if config["seed"] != DEFAULT["seed"] or config["train_seconds"] != DEFAULT["train_seconds"]:
            raise ValueError("Seed changes the frozen random seed or training budget")
        config = canonical_config(config)
        if config not in configs:
            configs.append(config)
    return configs


def applicable_cards(knowledge, config):
    result = []
    for card in knowledge:
        action = card.get("action", {})
        matches = any(key in config and (config[key] in value if isinstance(value, list)
                                        else config[key] == value) for key, value in action.items())
        if card.get("type") == "task_prior" or matches:
            result.append(card["id"])
    return result


def backend_seeds(configs):
    """Evaluate historical configurations afresh alongside explicit TabM starts."""
    result = [canonical_config(c) for c in configs]
    base = result[0] if result else DEFAULT
    for embedding in ("none", "periodic"):
        config = canonical_config({**base, "tabm_members": 8,
                                   "tabm_embedding": embedding, "replicas": 1, "depth": 2})
        if config not in result:
            result.append(config)
    if base.get("tree_blend", 0):
        for replicas in (3, 1):
            config = canonical_config({**base, "share_fold_preprocessing": True,
                                       "share_fold_tree": True, "replicas": replicas})
            if config not in result:
                result.append(config)
    return result


BACKENDS = ((0, "none"), (8, "none"), (8, "periodic"))


def backend_key(config):
    config = canonical_config(config)
    return config["tabm_members"], config["tabm_embedding"]


def backend_slot(index, initial_configs, enabled):
    start = len(initial_configs or [])
    return BACKENDS[(index - start) % len(BACKENDS)] if enabled and index >= start else None


def constrain_backend(config, backend):
    if backend is not None:
        config = {**config, "tabm_members": backend[0], "tabm_embedding": backend[1]}
    return canonical_config(config)


def propose(index, records, knowledge=None, initial_configs=None, backend=None, resource_selection=False, quality_selection=False):
    rng = random.Random(20261020 + index)
    successful = [r for r in records if r.get("result", {}).get("validity") == 1]
    if backend is not None:
        successful = [r for r in successful if backend_key(r["config"]) == backend]
    ranking = weakest_margin if index % 4 in [2, 3] else lambda r: r["result"]["combined_score"]
    if resource_selection and index % 4 == 1:
        ranking = predictive_resource_rank
    if quality_selection:
        ranking = quality_margin
    parent = max(successful, key=ranking) if successful else None
    config = dict(parent["config"] if parent and index % 4 else DEFAULT)
    seeds = [c for c in (knowledge or []) if c.get("action", {}).get("family") in SPACE["family"]]
    families = [c["action"]["family"] for c in seeds] or ["mlp", "tcn"]
    if initial_configs and index < len(initial_configs):
        config = dict(initial_configs[index])
        parent = None
    elif index < 8:
        config.update(family=families[index % len(families)],
                      positive_boost=[3.0, 3.0, 10.0, 10.0, 3.0, 3.0, 3.0, 3.0][index])
        if index >= 4:
            config.update(normalization="quantile", feature_set="trends",
                          folds=3 if index >= 6 else 1)
    else:
        for key in rng.sample(list(SPACE), 2):
            config[key] = rng.choice(SPACE[key])
    config = constrain_backend(config, backend)
    cards = applicable_cards(knowledge, config) if knowledge else [
                  "HDD-MISSING-01", "DL-SEQ-01" if config["family"] == "tcn" else "DL-TAB-01"]
    return config, (parent["trial"] if parent else None), cards


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def unseen_config(config, records, index, allowed_families, backend=None):
    """Avoid exact repeats without reusing historical scores as new evaluations."""
    seen = {json.dumps(canonical_config(r["config"]), sort_keys=True) for r in records}
    config = constrain_backend(config, backend)
    if json.dumps(config, sort_keys=True) not in seen:
        return config, False
    rng = random.Random(9012026 + index)
    for _ in range(512):
        alternative = dict(config)
        for key in rng.sample(list(SPACE), 2):
            values = allowed_families if key == "family" else SPACE[key]
            alternative[key] = rng.choice(values)
        alternative = constrain_backend(alternative, backend)
        if json.dumps(alternative, sort_keys=True) not in seen:
            return alternative, True
    raise RuntimeError("Unable to propose an unseen configuration within bounded attempts")


def report(output, best, baselines, count, balanced=None):
    lines = ["# HDD 深度学习实验进度", "",
             f"已完成 {count} 个候选。验证集参与搜索；尚未进行独立复验。", ""]
    if best is None:
        lines.append("目前没有有效深度学习候选。")
    else:
        lines += [f"按 ROS 选择的当前最优：候选 {best['trial']}，"
                  f"结构 {best['config']['family']}，树模型融合比例 "
                  f"{best['config'].get('tree_blend', 0.0)}（大于零表示 ML+DL 混合模型）。", "",
                  "| 指标 | 当前 DL | " + " | ".join(f"ML 对照 {i}" for i in range(len(baselines))) + " |",
                  "|---|---|" + "---|" * len(baselines)]
        for key in ["combined_score"] + HIGHER + LOWER + ["alarms_per_1k_disks"]:
            def value(result):
                return result.get(key) if key == "combined_score" else result.get("metric", {}).get(key)
            lines.append(f"| {key} | {value(best['result'])} | " +
                         " | ".join(str(value(b["result"])) for b in baselines) + " |")
        lines += ["", "基线来源："] + [f"- ML 对照 {i}：`{b['path']}`" for i, b in enumerate(baselines)]
        lines += ["", "逐项差距："]
        for i, c in enumerate(best["comparisons"]):
            missing = [key for key, item in c.get("metrics", {}).items() if not item["better"]]
            lines.append(f"- 对照 {i} 尚未严格超过：{', '.join(missing) if missing else '无（仍需独立复验）'}。")
        if balanced and balanced["trial"] != best["trial"]:
            lines += ["", f"按最弱预测指标差距选择的候选：{balanced['trial']}，"
                      f"ROS {balanced['result']['combined_score']:.4f}，"
                      f"最弱相对差距 {weakest_margin(balanced):.4f}（正数才表示所有预测指标严格超过）。"]
            for i, c in enumerate(balanced["comparisons"]):
                missing = [k for k, item in c.get("metrics", {}).items() if not item["better"]]
                lines.append(f"- 该候选对照 {i} 尚未超过：{', '.join(missing)}。")
    path = output / "REPORT.md"
    temp = output / "REPORT.md.tmp"
    temp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    temp.replace(path)


def run(args):
    import fcntl
    # Fail before expensive staging if the expanded search backend is unavailable.
    for dependency in ("tabm", "rtdl_num_embeddings"):
        if importlib.util.find_spec(dependency) is None:
            raise RuntimeError(f"Search requires optional dependency {dependency}; install requirements-tabm.txt")
    nas, output, repo = Path(args.nas), Path(args.output), Path(args.repo)
    guard(nas, output)
    lock_path = Path("/home/hcf/faultevolve-dl/state/campaign.lock")
    with lock_path.open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        affinity = sorted(os.sched_getaffinity(0))[:4]
        os.sched_setaffinity(0, affinity)
        output.mkdir(parents=True, exist_ok=True)
        # The frozen evaluator uses copy2/utime, unsupported by this CIFS mount.
        # Bound its short-lived local copies instead of changing the evaluator.
        scratch = Path("/home/hcf/faultevolve-dl/scratch/evaluator")
        scratch.mkdir(parents=True, exist_ok=True)
        scratch_used = sum(p.stat().st_size for p in scratch.rglob("*") if p.is_file())
        if scratch_used > 5 * 1024**3:
            raise RuntimeError("Evaluation scratch exceeds 5 GiB; inspect stale owned files")
        os.environ.update(TMPDIR=str(scratch), CUDA_VISIBLE_DEVICES=str(args.gpu),
                          HDD_BENCH_DATA_ROOT=args.data,
                          OMP_NUM_THREADS="4", OPENBLAS_NUM_THREADS="4",
                          XDG_CACHE_HOME=str(nas / "faultevolve-dl/cache/xdg"))
        import tempfile
        tempfile.tempdir = str(scratch)
        evaluator_path = repo / "benchmark/hdd_mvp/evaluator.py"
        evaluator = load_module(evaluator_path, "hdd_frozen_evaluator")
        template_path = repo / "experiments/hdd_dl/candidate.py"
        knowledge_path = repo / "experiments/hdd_dl/knowledge.json"
        context_path = repo / "experiments/hdd_dl/research_context.py"
        planner_path = repo / "experiments/hdd_dl/planner.py"
        existing_manifest = output / "manifest.json"
        if existing_manifest.exists():
            frozen = json.loads(existing_manifest.read_text(encoding="utf-8"))
            for key, path in [("controller_sha256", Path(__file__)),
                              ("context_sha256", context_path),
                              ("template_sha256", template_path)]:
                if frozen.get(key) != sha(path):
                    raise RuntimeError("Campaign code changed; use a new output directory")
        # Hash only the documented public training/query inputs, never private test.
        public, error_or_labels = evaluator.locate_split("val")
        if public is None:
            raise RuntimeError(error_or_labels)
        if sum(p.stat().st_size for p in public.values()) > 1024**3:
            raise RuntimeError("Public staging input exceeds the 1 GiB per-evaluation allowance")
        context = load_module(context_path, "hdd_research_context")
        # GPU discovery stays in the trusted controller; only aggregates leave the host.
        import torch
        profile = context.profile_training(public, torch.cuda.is_available())
        write_json(output / "dataset_profile.json", profile)
        retrieval_path = output / "literature.json"
        if retrieval_path.exists():
            retrieval = json.loads(retrieval_path.read_text(encoding="utf-8"))
        else:
            retrieval = context.retrieve(profile)
            write_json(retrieval_path, retrieval)
        initial_configs = seed_configs(json.loads(Path(args.seed_records).read_text(encoding="utf-8"))) if args.seed_records else []
        initial_configs = backend_seeds(initial_configs)
        manifest = dict(evaluator_sha256=sha(evaluator_path), template_sha256=sha(template_path),
                        knowledge_sha256=sha(knowledge_path), seed=20261020,
                        controller_sha256=sha(Path(__file__)), context_sha256=sha(context_path),
                        planner_sha256=sha(planner_path),
                        planner={"enabled": args.planner, "model": args.planner_model,
                                 "max_calls": args.planner_max_calls},
                        retrieval_sha256=sha(retrieval_path),
                        seed_records_sha256=sha(Path(args.seed_records)) if args.seed_records else None,
                        packages=package_versions(), search_space=SPACE,
                        backend_quota=args.backend_quota,
                        resource_selection=args.resource_selection,
                        quality_selection=args.quality_selection, quality_selection_policy="worst-quality-gap-v1",
                        resource_selection_policy="predictive-feasible-first-v2",
                        public_data_sha256={k: sha(v) for k, v in public.items()},
                        baselines={str(Path(p).resolve()): sha(Path(p)) for p in args.baseline},
                        gpu=args.gpu, protocol="unchanged-hdd-val-900s-training-included",
                        cpu_affinity=affinity,
                        staging_policy="local-bounded-1GiB-input-5GiB-scratch",
                        scope="validation_search_not_independent_test")
        manifest_path = output / "manifest.json"
        if manifest_path.exists() and json.loads(manifest_path.read_text(encoding="utf-8")) != manifest:
            raise RuntimeError("Frozen campaign identity changed; create a new output directory")
        write_json(manifest_path, manifest)
        knowledge = json.loads(knowledge_path.read_text(encoding="utf-8"))
        knowledge += retrieval["cards"]
        write_json(output / "knowledge.json", knowledge)
        baseline_path = output / "baselines.json"
        if baseline_path.exists():
            baselines = json.loads(baseline_path.read_text(encoding="utf-8"))
        else:
            baselines = []
            for path in args.baseline:
                guard(nas, output)
                result = evaluator.evaluate(path, timeout=900, split="val")
                baselines.append({"path": path, "sha256": sha(Path(path)), "result": result})
                write_json(output / "status.json", {"phase": "baseline", "completed": len(baselines)})
            write_json(baseline_path, baselines)
        if not baselines or any(b["result"]["validity"] != 1 for b in baselines):
            raise RuntimeError("All declared ML baselines must evaluate successfully")
        if profile["route"] == "ml_only":
            write_json(output / "status.json", {"phase": "ml_only_complete", "profile": profile})
            return
        records_path = output / "trials.json"
        records = json.loads(records_path.read_text(encoding="utf-8")) if records_path.exists() else []
        template = template_path.read_text(encoding="utf-8")
        planner = load_module(planner_path, "hdd_planner") if args.planner else None
        start = time.monotonic()
        for index in range(len(records), args.trials):
            guard(nas, output)
            if (output / "STOP").exists() or time.monotonic() - start > args.hours * 3600:
                break
            backend = backend_slot(index, initial_configs, args.backend_quota)
            config, parent, cards = propose(index, records, knowledge, initial_configs, backend, args.resource_selection, args.quality_selection)
            hypothesis = None
            if planner and index % 8 == 7:
                valid_parents = [r for r in records if r["result"]["validity"] == 1]
                if backend is not None:
                    valid_parents = [r for r in valid_parents if backend_key(r["config"]) == backend]
                selected = max(valid_parents, key=quality_margin if args.quality_selection else weakest_margin) if valid_parents else None
                planning_base = constrain_backend(selected["config"] if selected else config, backend)
                planning_space = dict(SPACE)
                if backend is not None:
                    planning_space.update(tabm_members=[backend[0]], tabm_embedding=[backend[1]])
                hypothesis = planner.propose(
                    trial=index, parent=planning_base, records=records, knowledge=knowledge, space=planning_space,
                    ledger_path=output / "planner.json", write_json=write_json,
                    ranking_key=quality_margin if args.quality_selection else None,
                    model=args.planner_model, env_file=args.env_file, max_calls=args.planner_max_calls)
                if hypothesis:
                    config = {**planning_base, **hypothesis["changes"]}
                    parent = selected["trial"] if selected else None
                    cards = applicable_cards(knowledge, config)
            if config["family"] not in profile["dl_families"]:
                config["family"] = profile["dl_families"][0]
                cards = applicable_cards(knowledge, config)
            config, duplicate_replaced = unseen_config(config, records, index, profile["dl_families"], backend)
            cards = applicable_cards(knowledge, config)
            candidate = output / f"candidate_{index:04d}.py"
            candidate.write_text(render(template, config), encoding="utf-8")
            write_json(output / "status.json", {"phase": "evaluating", "trial": index,
                       "config": config, "knowledge_cards": cards, "updated_at": time.time()})
            result = evaluator.evaluate(str(candidate), timeout=900, split="val")
            record = {"trial": index, "parent": parent, "config": config,
                      "backend_slot": list(backend) if backend is not None else None,
                      "hypothesis": hypothesis,
                      "hypothesis_applied": bool(hypothesis and not duplicate_replaced and all(
                          config[k] == v for k, v in hypothesis["changes"].items())),
                      "duplicate_replaced": duplicate_replaced,
                      "knowledge_cards": cards, "candidate_sha256": sha(candidate),
                      "result": result, "comparisons": [
                          {"baseline": b["path"], **comparison(result, b["result"])} for b in baselines]}
            records.append(record)
            write_json(records_path, records)
            valid = [r for r in records if r["result"]["validity"] == 1]
            best = max(valid, key=lambda r: r["result"]["combined_score"]) if valid else None
            balanced = max(valid, key=weakest_margin) if valid else None
            resource_balanced = max(valid, key=predictive_resource_rank) if valid else None
            if best:
                shutil.copyfile(output / f"candidate_{best['trial']:04d}.py", output / "best.py")
            write_json(output / "summary.json", {"trials": len(records), "best": best, "balanced": balanced,
                       "resource_balanced": resource_balanced,
                       "quality_balanced": max(valid, key=quality_margin) if valid else None,
                       "all_quality_targets_met_single_run": any(quality_margin(r) > 0 for r in valid),
                       "all_targets_met_single_run": any(
                           all(c["all_including_resources_strictly_better"] for c in r["comparisons"])
                           for r in valid), "independent_replication": False})
            report(output, best, baselines, len(records), balanced)
            print(json.dumps({"trial": index, "score": result["combined_score"],
                              "validity": result["validity"], "error": result["error_info"]}), flush=True)
            if len(records) >= 3 and all(r["result"]["validity"] != 1 for r in records[-3:]):
                write_json(output / "status.json", {"phase": "needs_repair",
                           "reason": "three_consecutive_invalid_candidates", "trials": len(records)})
                return
        write_json(output / "status.json", {"phase": "batch_complete", "trials": len(records),
                                          "updated_at": time.time()})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--nas", default="/home/hcf/nas_hcf_data")
    parser.add_argument("--data", default="/home/hcf/nas_hcf_data/faultevolve/data/hdd_mvp")
    parser.add_argument("--output", required=True)
    parser.add_argument("--baseline", action="append", required=True)
    parser.add_argument("--seed-records", help="Explicit prior trial ledger; configurations only, never scores")
    parser.add_argument("--planner", action="store_true", help="Enable bounded Qwen hypothesis proposals")
    parser.add_argument("--backend-quota", action="store_true", help="Rotate backend exploration after initial seeds")
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--quality-selection", action="store_true", help="Select parents by worst prediction/stability gap; ignore runtime and ROS")
    selection.add_argument("--resource-selection", action="store_true", help="Use full-metric worst gap for one parent slot in four")
    parser.add_argument("--planner-model", default="qwen3.8-flash")
    parser.add_argument("--planner-max-calls", type=int, default=12)
    parser.add_argument("--env-file", help="Local key source; values are never logged")
    parser.add_argument("--gpu", type=int, default=0)
    parser.add_argument("--trials", type=int, default=24)
    parser.add_argument("--hours", type=float, default=8)
    args = parser.parse_args()
    if not 1 <= args.trials <= 1000 or not 0 < args.hours <= 24:
        parser.error("Trials must be 1..1000 and batch hours must be 0..24")
    if not 0 <= args.planner_max_calls <= 12:
        parser.error("Planner calls must be 0..12 per frozen campaign")
    run(args)


if __name__ == "__main__":
    main()
