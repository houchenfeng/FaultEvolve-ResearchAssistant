"""Bounded projections of workflow evidence; never expose raw data or ledger paths."""

import json
import math
from contextlib import contextmanager

from faultevolve.webapi import paths, replay_service
from faultevolve.webapi.contracts import (
    ArtifactState, ContractWarning, EffectReportResponse, HierarchicalRouteResponse, HierarchicalSearchResponse,
    HierarchicalTrialResponse, WorkflowDataResponse, WorkflowResponse, WorkflowTransformationResponse,
)
from faultevolve.webapi.sanitization import sanitize
from faultevolve.webapi.settings import WebSettings


def _number(value):
    return value if type(value) in (float, int) and math.isfinite(value) else None


def _convergence(value, model):
    if not isinstance(value, dict):
        return None
    point = model.model_fields["evolution_curve"].annotation.__args__[0]
    keep = lambda item: {k: v for k, v in item.items() if k in point.model_fields} if isinstance(item, dict) else item
    result = {k: v for k, v in value.items() if k in model.model_fields}
    for curve in ("evolution_curve", "hpo_curve"):
        result[curve] = [keep(item) for item in value.get(curve, [])[:1000]]
    return result


def workflow(settings: WebSettings, run_id: str) -> WorkflowResponse:
    artifacts = replay_service.artifacts_for(settings, run_id)
    root = artifacts.workflow_dir or artifacts.run_dir
    warnings = []

    def read(*parts):
        path = paths.resolve_run_child(root, *parts)
        if not path.is_file():
            return None, ArtifactState.MISSING
        try:
            if path.stat().st_size > 16 * 1024 * 1024:
                raise ValueError("too large")
            value = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise ValueError("not an object")
            return value, ArtifactState.AVAILABLE
        except (OSError, ValueError):
            warnings.append(ContractWarning(field="/".join(parts), reason="记录无法解析，相关数值保持未知。"))
            return None, ArtifactState.INVALID

    status, _ = read("workflow.json")
    if status is None:
        status, _ = read("status.json")
    data, data_state = read("data-workflow.json")
    ledger, search_state = read("hyperparameters", "ledger.json")
    spec, _ = read("hyperparameters", "experiment_spec.json")
    result, _ = read("workflow-result.json")
    effect, effect_state = read("effect-report.json")
    report_status, _ = read("report-status.json")
    if (report_status or {}).get("state") == "failed":
        warnings.append(ContractWarning(field="reports", reason="搜索状态不受影响；报告导出失败，可单独重建报告。"))
    legacy = False
    if result is None:
        result, _ = read("results", "report.json")
        legacy = result is not None
    response = WorkflowResponse(run_id=run_id, state=(status or {}).get("state"),
        phase=(status or {}).get("phase"), data_state=data_state, search_state=search_state,
        effect_state=effect_state, warnings=warnings)
    @contextmanager
    def project(section):
        try:
            yield
        except (ValueError, TypeError, KeyError, AttributeError):
            setattr(response, section, None)
            setattr(response, section + "_state", ArtifactState.INVALID)
            response.warnings.append(ContractWarning(field=section, reason="记录结构损坏，相关数值保持未知。"))

    if data is not None:
        with project("data"):
            transformations = [WorkflowTransformationResponse(
                rule=str(t.get("rule", "unknown")), column=t.get("column"),
                affected=int(t.get("affected", 0)), reason=sanitize(str(t.get("reason", "")))[0])
                for t in data.get("transformations", []) if isinstance(t, dict)]
            response.data = WorkflowDataResponse(state=data.get("state"),
                before_samples=data.get("before", {}).get("n_samples"), after_samples=data.get("after", {}).get("n_samples"),
                before_rows=data.get("before", {}).get("n_history_rows"), after_rows=data.get("after", {}).get("n_history_rows"),
                transformations=transformations, accepted_issues=data.get("accepted_issues", []),
                unresolved_codes=data.get("unresolved_codes", []),
                source_sha256=data.get("source_sha256", {}), derived_sha256=data.get("derived_sha256", {}))
    if ledger is not None:
        with project("search"):
            route_specs = {r["id"]: r for r in (spec or {}).get("routes", [])}
            routes = [HierarchicalRouteResponse(route_id=r["route_id"],
                source=sanitize(str(route_specs.get(r["route_id"], {}).get("source", "")))[0] or None,
                default_score=_number(r.get("default_score")), visits=r.get("real_visits"),
                best_score=max((v for c in r.get("best_candidates", [])
                                if (v := _number(c.get("score"))) is not None), default=None))
                for r in ledger.get("route_summaries", [])]
            trials = []
            for t in ledger.get("trials", [])[:1000]:
                evaluation, execution, decision = t.get("evaluation", {}), t.get("execution", {}), t.get("decision", {})
                valid = evaluation.get("succeeded") is True and evaluation.get("integrity_passed") is True
                trials.append(HierarchicalTrialResponse(
                    trial_number=t["trial_number"], candidate_id=t["candidate_id"], route_id=t["route_id"],
                    parent_id=t.get("parent_id"), depth=t.get("depth"), changed_parameter=t.get("changed_parameter"),
                    parameters={k: v for k, v in t.get("parameters", {}).items() if _number(v) is not None},
                    status=execution.get("status"), score=_number(evaluation.get("score")) if valid else None,
                    reward=_number(evaluation.get("reward")), decision=decision.get("status"),
                    reason=sanitize(str(decision.get("reason") or evaluation.get("error") or ""))[0] or None,
                    duration_seconds=_number(execution.get("duration_seconds"))))
            best = ledger.get("best_candidate") or {}
            response.search = HierarchicalSearchResponse(
                contract_hash=ledger.get("contract_hash"), completed_trials=ledger.get("completion_count"),
                max_trials=(spec or {}).get("budgets", {}).get("max_trials"),
                default_barrier_open=ledger.get("default_barrier_open"), stop_reason=ledger.get("stop_reason"),
                best_candidate_id=best.get("candidate_id"), best_score=_number(best.get("score")), routes=routes, trials=trials)
    if effect is not None:
        with project("effect"):
            # Keep only declared fields so an extra key in the record cannot leak or
            # invalidate the whole section; type errors in declared fields still do.
            def only(model, value):
                return {k: v for k, v in value.items() if k in model.model_fields} if isinstance(value, dict) else value

            fields = EffectReportResponse.model_fields
            solution_model = fields["solutions"].annotation.__args__[0]
            response.effect = EffectReportResponse.model_validate({
                "solutions": [{
                    **only(solution_model, item),
                    "performance": only(solution_model.model_fields["performance"].annotation, item.get("performance", {})),
                    "complexity": only(solution_model.model_fields["complexity"].annotation, item.get("complexity", {})),
                } for item in effect.get("solutions", []) if isinstance(item, dict)],
                "token_usage": only(fields["token_usage"].annotation, effect.get("token_usage", {})),
                "convergence": _convergence(effect.get("convergence"), fields["convergence"].annotation.__args__[0]),
                "automation": only(fields["automation"].annotation.__args__[0], effect.get("automation")),
                "note": sanitize(str(effect.get("note", "")))[0] or None})
    if result is not None:
        response.evolution_best_score = _number(result.get("evolution_best_val_ros" if legacy else "evolution_best_score"))
        response.final_best_score = _number(result.get("best_val_ros" if legacy else "best_score"))
        response.best_origin = result.get("best_origin")
        if not legacy and paths.resolve_run_child(root, "workflow-best.py").is_file():
            response.best_artifact_id = "workflow-best"
        elif legacy and paths.resolve_run_child(root, "results", "best.py").is_file():
            response.best_artifact_id = "campaign-best"
    return response
