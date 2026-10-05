"""Autotune hooks used by EvolutionEngine (ledger, patch, quota)."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from faultevolve.common.metering import CallMetrics
from faultevolve.optimization.ledger import CostLedger, CostRecord, Reservation
from faultevolve.optimization.patching import (
    Patch,
    PatchResult,
    apply_patch,
    module_spans,
    parse_patch,
)

if TYPE_CHECKING:
    from faultevolve.cloud.engine import EvolutionEngine
    from faultevolve.common.schemas import Node


def init_ledger(engine: "EvolutionEngine") -> None:
    cfg = engine.config.autotune.ledger
    if cfg.enabled:
        engine._cost_ledger = CostLedger(full_eval_cap=cfg.full_eval_cap)
    else:
        engine._cost_ledger = None
    engine._quota_counts: dict[str, int] = {"hpo": 0, "patch": 0, "draft": 0}
    engine._plateau_evals_since_improve = 0
    engine._restart_count = 0
    engine._ledger_stop = False
    engine._hpo_family_cursor = 0
    engine._hpo_family_trial_index: dict[str, int] = {}
    engine._hpo_used_fits = 0
    engine._hpo_dev_ctx = None


def ledger_record(
    engine: "EvolutionEngine",
    *,
    stage: str,
    fidelity: str,
    node_id: str | None,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    model_fit_count: int = 0,
    evaluator_calls: int = 0,
    wall_s: float = 0.0,
    cache_hit: bool = False,
    status: str = "ok",
    reservation: Reservation | None = None,
) -> None:
    ledger: CostLedger | None = engine._cost_ledger
    if ledger is None:
        return
    rec = CostRecord(
        seq=0,
        stage=stage,
        fidelity=fidelity,
        node_id=node_id,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        model_fit_count=model_fit_count,
        evaluator_calls=evaluator_calls,
        wall_s=wall_s,
        cache_hit=cache_hit,
        status=status,
    )
    if reservation is not None:
        settled = ledger.settle(reservation, rec)
    else:
        settled = ledger.record(rec)
    engine.store.append_cost_record(engine.experiment_id, settled)


def ledger_would_block_full_eval(engine: "EvolutionEngine") -> bool:
    ledger: CostLedger | None = engine._cost_ledger
    if ledger is None or engine.config.autotune.ledger.full_eval_cap is None:
        return False
    return ledger.would_exceed(full_evals=1)


def apply_patch_response(
    engine: "EvolutionEngine",
    parent: "Node",
    response: str,
    metrics: CallMetrics,
) -> tuple[str | None, str, str, PatchResult | None]:
    parsed = parse_patch(response)
    if isinstance(parsed, PatchResult):
        engine._log_event(
            "patch_rejected",
            {
                "parent_id": parent.id,
                "reason": parsed.reason.value if parsed.reason else "parse_error",
                "module": parsed.module,
                "detail": (parsed.detail or "")[:400],
            },
        )
        ledger_record(
            engine,
            stage="generate",
            fidelity="none",
            node_id=parent.id,
            prompt_tokens=metrics.prompt_tokens,
            completion_tokens=metrics.completion_tokens,
            status="rejected",
        )
        return None, "", "", parsed
    patch: Patch = parsed
    engine._log_event(
        "patch_proposed",
        {"parent_id": parent.id, "module": patch.module, "hunks": len(patch.hunks)},
    )
    static_check = lambda code: engine.task_adapter.static_check(code, engine.task_spec)
    result = apply_patch(
        parent.artifact.code,
        patch,
        static_check=static_check,
        max_hunks=engine.config.autotune.patch.max_hunks,
        max_changed_lines=engine.config.autotune.patch.max_changed_lines,
    )
    if not result.ok:
        engine._log_event(
            "patch_rejected",
            {
                "parent_id": parent.id,
                "reason": result.reason.value if result.reason else "parse_error",
                "module": result.module,
                "detail": (result.detail or "")[:400],
            },
        )
        ledger_record(
            engine,
            stage="generate",
            fidelity="none",
            node_id=parent.id,
            prompt_tokens=metrics.prompt_tokens,
            completion_tokens=metrics.completion_tokens,
            status="rejected",
        )
        return None, "", "", result
    engine._log_event(
        "patch_applied",
        {
            "parent_id": parent.id,
            "module": patch.module,
            "changed_lines": result.changed_lines,
        },
    )
    ledger_record(
        engine,
        stage="generate",
        fidelity="none",
        node_id=parent.id,
        prompt_tokens=metrics.prompt_tokens,
        completion_tokens=metrics.completion_tokens,
        status="ok",
    )
    intent = f"patch module={patch.module}"
    hypothesis = f"局部编辑 {patch.module}"
    return result.code, intent, hypothesis, result


def parent_has_patch_blocks(parent: "Node") -> bool:
    return bool(module_spans(parent.artifact.code))


def run_hpo_quota_iteration(engine: "EvolutionEngine", parent: "Node") -> bool:
    """Run one quota HPO slot: dev trials then full eval for promoted specs."""
    from faultevolve.common.schemas import OperatorType
    from faultevolve.cloud.tree import create_child_node
    from faultevolve.optimization.hpo_engine import (
        compile_promoted_code,
        prepare_hpo_dev_context,
        run_family_hpo_trials,
        select_promoted_trials,
    )

    cfg = engine.config.autotune
    if engine.task_dir is None:
        engine._log_event("hpo_skipped", {"parent_id": parent.id, "reason": "no_task_dir"})
        return True
    ledger: CostLedger | None = engine._cost_ledger
    if ledger is None:
        engine._log_event("hpo_skipped", {"parent_id": parent.id, "reason": "ledger_off"})
        return True

    task_dir = engine.task_dir
    hpo_cfg = cfg.hpo
    families = hpo_cfg.families
    if not families:
        engine._log_event("hpo_skipped", {"parent_id": parent.id, "reason": "no_families"})
        return True

    family = families[engine._hpo_family_cursor % len(families)]
    engine._hpo_family_cursor += 1
    start_index = engine._hpo_family_trial_index.get(family, 0)

    try:
        if engine._hpo_dev_ctx is None:
            engine._hpo_dev_ctx = prepare_hpo_dev_context(
                task_dir, engine.config, mock_eval=engine.mock
            )
    except Exception as exc:
        engine._log_event(
            "hpo_skipped",
            {"parent_id": parent.id, "reason": f"split_refused:{exc}"},
        )
        return True

    ledger_before = len(ledger.records())
    trials, engine._hpo_used_fits = run_family_hpo_trials(
        task_dir=task_dir,
        config=engine.config,
        store=engine.store,
        experiment_id=engine.experiment_id,
        ledger=ledger,
        dev_ctx=engine._hpo_dev_ctx,
        family=family,
        start_index=start_index,
        used_fits=engine._hpo_used_fits,
        mock_eval=engine.mock,
        fit_stage="hpo_trial",
    )
    engine._hpo_family_trial_index[family] = start_index + hpo_cfg.trials_per_structure

    for rec in ledger.records()[ledger_before:]:
        engine.store.append_cost_record(engine.experiment_id, rec)

    promoted = select_promoted_trials(trials, hpo_cfg.promote_top_k)
    if not promoted:
        engine._log_event(
            "hpo_no_promotion",
            {"parent_id": parent.id, "family": family, "trials": len(trials)},
        )
        engine._log_iteration_complete("hpo_no_promotion", parent_id=parent.id)
        return True

    last_child_id = None
    for trial in promoted:
        if ledger_would_block_full_eval(engine):
            engine._log_event(
                "hpo_promotion_skipped",
                {"parent_id": parent.id, "trial_id": trial.trial_id, "reason": "ledger_cap"},
            )
            break
        code = compile_promoted_code(trial)
        intent = f"HPO 晋级 trial={trial.trial_id} family={family}"
        hypothesis = f"结构化搜索 dev_proxy={trial.dev_proxy:.4f}" if trial.dev_proxy else intent
        child = create_child_node(
            parent,
            code,
            intent,
            hypothesis,
            OperatorType.HPO,
        )
        engine.tree.add_node(child)
        engine._evaluate_child(parent, child, [], count_iteration=True)
        last_child_id = child.id
        engine._log_event(
            "hpo_promoted",
            {
                "parent_id": parent.id,
                "node_id": child.id,
                "trial_id": trial.trial_id,
                "dev_proxy": trial.dev_proxy,
            },
        )

    if last_child_id is None:
        engine._log_iteration_complete("hpo_promotion_skipped", parent_id=parent.id)
    return True
