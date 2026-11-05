"""Frozen multi-seed verification on the same validation benchmark.

This measures training-seed stability, NOT independent-set generalization.
Configurations are selected and hashed before any new seed is evaluated.
"""
from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import math
import os
from pathlib import Path
import statistics
import time


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def config_from_source(source):
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "CONFIG" for t in node.targets):
            value = ast.literal_eval(node.value)
            if not isinstance(value, dict) or "seed" not in value:
                raise ValueError("Candidate has no literal seed configuration")
            return value
    raise ValueError("Candidate CONFIG missing")


def aggregate(records, expected):
    groups = {}
    for row in records:
        groups.setdefault(row["candidate"], []).append(row)
    result = {}
    for name, rows in groups.items():
        valid = [r for r in rows if r["result"].get("validity") == 1]
        keys = sorted(set(k for r in valid for k, v in r["result"].get("metric", {}).items()
                          if isinstance(v, (float, int)))) + ["combined_score"]
        metrics = {}
        for key in keys:
            values = [(r["result"].get(key) if key == "combined_score" else r["result"]["metric"].get(key))
                      for r in valid]
            if not values or any(v is None or not math.isfinite(v) for v in values):
                continue
            metrics[key] = {"mean": statistics.mean(values), "min": min(values),
                            "max": max(values), "median": statistics.median(values),
                            "std": statistics.stdev(values) if len(values) > 1 else None}
        complete = (len(rows) == expected and len(valid) == expected
                    and len({r["seed"] for r in rows}) == expected
                    and all(r.get("comparisons") for r in rows))
        result[name] = {
            "evaluated": len(rows), "valid": len(valid), "expected": expected,
            "complete": complete, "metrics": metrics,
            "all_seeds_all_predictive_better": complete and all(
                all(c["all_predictive_strictly_better"] for c in r["comparisons"]) for r in rows),
            "all_seeds_quality_without_runtime_better": complete and all(
                all(all(c.get("metrics", {}).get(k, {}).get("better") is True
                        for k in ("precision", "recall", "f1", "f1_p10", "auprc", "recall_at_far",
                                  "quality", "false_alarm_rate", "missed_detection_rate", "f1_boot_std"))
                    for c in r["comparisons"]) for r in rows),
            "all_seeds_all_metrics_better": complete and all(
                all(c["all_including_resources_strictly_better"] for c in r["comparisons"]) for r in rows),
        }
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--candidate", action="append", required=True)
    parser.add_argument("--baseline", action="append", required=True)
    parser.add_argument("--seeds", default="20261021,20261022,20261023")
    parser.add_argument("--gpu", type=int, default=0)
    args = parser.parse_args()
    seeds = [int(s) for s in args.seeds.split(",")]
    if len(set(seeds)) != len(seeds) or not 2 <= len(seeds) <= 10:
        parser.error("Use 2..10 distinct predeclared seeds")
    repo, output = Path(args.repo), Path(args.output)
    controller = load(repo / "experiments/hdd_dl/controller.py", "verification_controller")
    nas = Path("/home/hcf/nas_hcf_data")
    controller.guard(nas, output)
    import fcntl
    with Path("/home/hcf/faultevolve-dl/state/campaign.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        affinity = sorted(os.sched_getaffinity(0))[:4]
        os.sched_setaffinity(0, affinity)
        os.environ.update(CUDA_VISIBLE_DEVICES=str(args.gpu), OMP_NUM_THREADS="4", OPENBLAS_NUM_THREADS="4",
                          HDD_BENCH_DATA_ROOT=str(nas / "faultevolve/data/hdd_mvp"))
        import tempfile
        scratch = Path("/home/hcf/faultevolve-dl/scratch/evaluator")
        scratch.mkdir(parents=True, exist_ok=True)
        if sum(p.stat().st_size for p in scratch.rglob("*") if p.is_file()) > 5 * 1024**3:
            raise RuntimeError("Scratch exceeds 5 GiB; inspect owned stale files")
        tempfile.tempdir = str(scratch)
        os.environ["TMPDIR"] = str(scratch)
        output.mkdir(parents=True, exist_ok=True)
        evaluator_path = repo / "benchmark/hdd_mvp/evaluator.py"
        evaluator = load(evaluator_path, "verification_evaluator")
        public, error_or_labels = evaluator.locate_split("val")
        if public is None:
            raise RuntimeError(error_or_labels)
        if sum(p.stat().st_size for p in public.values()) > 1024**3:
            raise RuntimeError("Staging exceeds 1 GiB allowance")
        manifest = {
            "seeds": seeds, "cpu_affinity": affinity, "gpu": args.gpu,
            "evaluator_sha256": controller.sha(evaluator_path),
            "verification_sha256": controller.sha(Path(__file__)),
            "controller_sha256": controller.sha(repo / "experiments/hdd_dl/controller.py"),
            "candidates": {str(Path(p).resolve()): controller.sha(Path(p)) for p in args.candidate},
            "baselines": {str(Path(p).resolve()): controller.sha(Path(p)) for p in args.baseline},
            "public_data": {k: controller.sha(v) for k, v in public.items()},
            "validation_labels_sha256": controller.sha(error_or_labels),
            "packages": controller.package_versions(),
            "scope": "training_seed_stability_on_reused_search_validation_set",
            "baseline_randomness": "original_ML_program_fixed;repeated_for_timing",
            "selection_rule": "explicit_predeclared_candidates;no_reselection_after_seed_results",
        }
        path = output / "manifest.json"
        if path.exists() and json.loads(path.read_text(encoding="utf-8")) != manifest:
            raise RuntimeError("Verification contract changed; use a new directory")
        controller.write_json(path, manifest)
        ledger_path = output / "records.json"
        records = json.loads(ledger_path.read_text(encoding="utf-8")) if ledger_path.exists() else []
        started = time.monotonic()
        for seed in seeds:
            controller.guard(nas, output)
            if (output / "STOP").exists() or time.monotonic() - started > 4 * 3600:
                break
            baseline_path = output / f"baseline_repetition_{seed}.json"
            if baseline_path.exists():
                baselines = json.loads(baseline_path.read_text(encoding="utf-8"))
            else:
                baselines = [{"path": p, "result": evaluator.evaluate(p, timeout=900, split="val")}
                             for p in args.baseline]
                controller.write_json(baseline_path, baselines)
            if any(b["result"]["validity"] != 1 for b in baselines):
                raise RuntimeError("Baseline failed; verification cannot pass")
            for number, candidate_path in enumerate(args.candidate):
                if (output / "STOP").exists() or time.monotonic() - started > 4 * 3600:
                    break
                if any(r["candidate"] == candidate_path and r["seed"] == seed for r in records):
                    continue
                controller.guard(nas, output)
                source = Path(candidate_path).read_text(encoding="utf-8")
                config = config_from_source(source)
                config["seed"] = seed
                candidate = output / f"candidate_{number}_seed_{seed}.py"
                candidate.write_text(controller.render(source, config), encoding="utf-8")
                controller.write_json(output / "status.json", {"phase": "evaluating",
                                      "candidate": candidate_path, "seed": seed})
                result = evaluator.evaluate(str(candidate), timeout=900, split="val")
                records.append({"candidate": candidate_path, "seed": seed, "result": result,
                                "comparisons": [{"baseline": b["path"], **controller.comparison(result, b["result"])}
                                                for b in baselines]})
                controller.write_json(ledger_path, records)
                controller.write_json(output / "summary.json",
                                      {"scope": manifest["scope"], "independent_generalization": False,
                                       "candidates": aggregate(records, len(seeds))})
                print(json.dumps({"candidate": number, "seed": seed, "score": result["combined_score"],
                                  "validity": result["validity"]}), flush=True)
        controller.write_json(output / "status.json",
                              {"phase": "complete" if len(records) == len(seeds) * len(args.candidate)
                               else "stopped", "evaluations": len(records)})


if __name__ == "__main__":
    main()
