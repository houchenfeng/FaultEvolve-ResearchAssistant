"""Local, durable parameter search before an evolved structure is scored."""

from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path
import time
from typing import TYPE_CHECKING

from faultevolve import research_campaign as campaign
from faultevolve.cloud.budget import wall_cap_exceeded
from faultevolve.cloud.engine_autotune import ledger_record, ledger_would_block_full_eval
from faultevolve.tasks.protocol import EvalResult

if TYPE_CHECKING:
    from faultevolve.cloud.engine import EvolutionEngine
    from faultevolve.common.schemas import Node


class StructureTuner:
    def __init__(self, engine: EvolutionEngine, workspace: Path, output: Path):
        self.engine, self.workspace, self.output = engine, workspace, output
        self.root = output / "hyperparameters"
        self.manifest = json.loads((workspace / "manifest.json").read_text())

    def directory(self, node_id: str) -> Path:
        return self.root / "structures" / node_id

    def _evaluate_program(self, candidate: Path, evaluator: Path, result_file: Path) -> dict:
        # Use the same adapter contract as the baseline: task-specific paths,
        # split selection and score normalization belong to the adapter.
        if self.manifest.get("schema") == "faultevolve.workflow-input/v1":
            return campaign.evaluate_val(candidate, evaluator, result_file)
        result = self.engine.task_adapter.evaluate(candidate.read_text(encoding="utf-8"), self.engine.task_spec)
        return asdict(result)

    def can_dispatch(self) -> bool:
        engine = self.engine
        if ledger_would_block_full_eval(engine):
            engine._ledger_stop = True
            return False
        elapsed = (time.time() - engine.metrics.start_time) / 3600
        return not wall_cap_exceeded(elapsed, engine.config.budget.max_wall_hours)

    def evaluate(self, node: Node, context: dict) -> EvalResult | None:
        engine = self.engine
        directory = self.directory(node.id)
        directory.mkdir(parents=True, exist_ok=True)
        proposed = directory / "proposed.py"
        if not proposed.exists():
            proposed.write_text(node.artifact.code, encoding="utf-8")
        campaign.write_json(directory / "context.json", context)
        code = proposed.read_text(encoding="utf-8")
        route = campaign.describe_route(f"structure_{node.id}", code, f"evolution:{node.id}")
        if route is None:
            # No known scalar parameters: evaluate this exact structure once.
            # Never substitute unrelated model templates for an opaque structure.
            route = {"id": f"structure_{node.id}", "default_parameters": {}, "parameter_domains": {},
                     "source": f"evolution:{node.id}", "model_families": [],
                     "source_sha256": hashlib.sha256(code.encode()).hexdigest()}
        route["code_path"] = str(proposed)
        cfg = engine.config.workflow.hierarchical
        manifest = {
            "search_engine_path": str(self.workspace / "search_engine.py"),
            "evaluator_path": str(self.workspace / "task/evaluator.py"),
            "hpo_trials": cfg.max_trials, "hpo_wall_seconds": cfg.max_wall_seconds,
            "structure_node_id": node.id,
            "validation_files": {**self.manifest["validation_files"], **{
                f"public/{name}": value for name, value in self.manifest["data"].get("derived_sha256", {}).items()}},
            "research": engine.config.research.model_dump(mode="json") if engine.config.research else None,
        }
        if self.manifest.get("schema") != "faultevolve.workflow-input/v1":
            manifest.update(evaluation_split=self.manifest["evaluation_split"],
                            adapter_identity=self.manifest["adapter_identity"],
                            cache_evaluations=self.manifest["cache_evaluations"])
            manifest["validation_files"]["task_data_descriptor"] = self.manifest["data_identity"]

        def evaluate(candidate, evaluator, result_file):
            before = time.monotonic()
            result = self._evaluate_program(candidate, evaluator, result_file)
            elapsed = time.monotonic() - before
            ledger_record(engine, stage="full_eval", fidelity="full_val", node_id=node.id,
                          evaluator_calls=1, wall_s=elapsed)
            score = result.get("combined_score")
            engine._log_event("structure_tuning_trial", {
                "node_id": node.id, "candidate_id": candidate.parent.name,
                "valid": result.get("validity") == 1.,
                "score": score if type(score) in (int, float) and math.isfinite(score) else None,
                "duration_s": elapsed,
            })
            return result

        engine._log_event("structure_tuning_started", {"node_id": node.id, "max_trials": cfg.max_trials,
                                                      "tunable_parameters": len(route["parameter_domains"])})
        try:
            ledger = campaign.hierarchical_search(self.output, engine.store.db_path, manifest,
                routes=[route], hpo_dir=directory, evaluate=evaluate, can_dispatch=self.can_dispatch,
                on_trial=self.summarize)
        finally:
            self.summarize()
        best = ledger.get("best_candidate")
        # Research constraints must all hold for the same selected executable.
        if engine.config.research:
            from faultevolve.common.research import assess_goals
            feasible = []
            for trial in ledger["trials"]:
                candidate_id = trial["candidate_id"]
                result = json.loads((directory / "runs" / candidate_id / "evaluation.json").read_text())
                if assess_goals(engine.config.research, result)["achieved"]:
                    feasible.append({"candidate_id": candidate_id, "score": result["combined_score"]})
            if feasible:
                best = max(feasible, key=lambda candidate: candidate["score"])
        if best:
            selected = directory / "runs" / best["candidate_id"]
            evaluation = json.loads((selected / "evaluation.json").read_text())
            tuned_code = (selected / "candidate.py").read_text(encoding="utf-8")
            node.artifact.code = tuned_code
            engine.store.update_node(node.id, artifact_json=node.artifact.model_dump_json())
        elif ledger["trials"]:
            selected = directory / "runs" / ledger["trials"][0]["candidate_id"]
            evaluation = json.loads((selected / "evaluation.json").read_text())
        else:
            # Budget exhaustion is missing evidence, not a failed structure.
            return None
        result = EvalResult(**{key: evaluation.get(key, default) for key, default in (
            ("validity", 0.), ("combined_score", 0.), ("cost_time", 0.), ("error_info", ""), ("metric", {}))})
        if type(result.combined_score) not in (int, float) or not math.isfinite(result.combined_score):
            result.validity, result.combined_score = 0., 0.
        result.cost_time = result.cost_time or 0.
        # Preserve the executable's own runtime; search overhead has a separate counter.
        duration = sum(t["execution"]["duration_seconds"] for t in ledger["trials"])
        engine.metrics.total_eval_time_s += duration
        result.metric = {**result.metric, "structure_tuning": {
            "node_id": node.id, "completed_trials": ledger["completion_count"],
            "best_candidate_id": best["candidate_id"] if best else None,
            "stop_reason": ledger["stop_reason"], "evaluation_seconds": duration,
            "default_score": ledger["route_summaries"][0].get("default_score"),
        }}
        campaign.write_json(directory / "selected.json", {"node_id": node.id, "evaluation": asdict(result),
                            "candidate_id": best["candidate_id"] if best else None})
        engine._log_event("structure_tuning_complete", {
            "node_id": node.id, "score": result.combined_score, "valid": result.is_valid,
            **result.metric["structure_tuning"],
        })
        campaign.write_json(self.output / "status.json", {
            "state": "running", "phase": "evolution", "structure_node_id": node.id,
            "updated_at": time.time(),
        })
        return result

    def summarize(self) -> dict:
        """Project per-structure ledgers for reports and the existing Web view."""
        trials, routes, summaries = [], [], []
        max_trials, elapsed, completed = 0, 0., 0
        contracts = []
        structures = self.root / "structures"
        directories = list(structures.iterdir()) if structures.is_dir() else []
        directories.sort(key=lambda path: (path / "proposed.py").stat().st_mtime_ns)
        for directory in directories:
            ledger_path = directory / "ledger.json"
            if not ledger_path.is_file():
                continue
            ledger = json.loads(ledger_path.read_text())
            spec = json.loads((directory / "experiment_spec.json").read_text())
            contracts.append(ledger["contract_hash"])
            routes.extend(spec["routes"])
            summaries.extend(ledger["route_summaries"])
            max_trials += spec["budgets"]["max_trials"]
            elapsed += ledger["elapsed_seconds"]
            completed += ledger["completion_count"]
            for trial in ledger["trials"]:
                trials.append({**trial, "structure_node_id": directory.name, "trial_number": len(trials) + 1})
        valid = [t for t in trials if t["evaluation"]["succeeded"] and t["evaluation"]["integrity_passed"]]
        best = max(valid, key=lambda t: t["evaluation"]["score"], default=None)
        combined = {"mode": "per_structure", "completion_count": completed, "trials": trials,
                    "route_summaries": summaries, "elapsed_seconds": elapsed, "holdout": None,
                    "contract_hash": hashlib.sha256(json.dumps(contracts).encode()).hexdigest(),
                    "default_barrier_open": bool(summaries), "stop_reason": "per_structure",
                    "best_candidate": {"candidate_id": best["candidate_id"],
                                       "score": best["evaluation"]["score"]} if best else None}
        campaign.write_json(self.root / "ledger.json", combined)
        campaign.write_json(self.root / "experiment_spec.json", {
            "mode": "per_structure", "routes": routes, "budgets": {"max_trials": max_trials}})
        campaign.write_json(self.root / "summary.json", {
            "mode": "per_structure", "completed_structures": len(summaries), "completed_trials": completed,
            "max_trials_per_structure": self.engine.config.workflow.hierarchical.max_trials,
            "best_candidate": combined["best_candidate"], "holdout": None,
        })
        return combined
