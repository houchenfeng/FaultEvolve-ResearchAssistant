"""Map the flat ``run_summary.json`` onto the contract's response groups.

``run_summary.json`` is one flat object: 116 fields for a single-tree run, 119 once
the engine records an island ring (``islands`` / ``exchange`` / ``cost``). The
contract splits them into ``outcome`` / ``budget`` / ``repair`` / ``knowledge`` /
``discovery`` / ``judge`` / ``operators`` / ``islands`` so the UI can keep judge cost
visually apart from evaluator scores (PRD §2.2).

The mapping is **field-by-field on purpose**: a new engine field is ignored until
someone names it here, rather than silently appearing in the API and in the
front-end's type space. Missing keys stay ``None`` -- never ``0`` -- so the UI
renders "未记录".
"""

from __future__ import annotations

from typing import Any

from faultevolve.webapi.contracts import (
    ArtifactState,
    ExchangeViewResponse,
    IslandCostResponse,
    IslandViewResponse,
    KnowledgeCardStatResponse,
    RunBudgetResponse,
    RunDiscoveryResponse,
    RunIslandCostResponse,
    RunIslandsResponse,
    RunJudgeResponse,
    RunKnowledgeResponse,
    RunOperatorResponse,
    RunOutcomeResponse,
    RunRepairResponse,
)


def _get(summary: dict[str, Any], key: str) -> Any:
    return summary.get(key)


def _dict_of_float(summary: dict[str, Any], key: str) -> dict[str, float]:
    raw = summary.get(key)
    if not isinstance(raw, dict):
        return {}
    out: dict[str, float] = {}
    for name, value in raw.items():
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            out[str(name)] = float(value)
    return out


def _dict_of_int(summary: dict[str, Any], key: str) -> dict[str, int]:
    raw = summary.get(key)
    if not isinstance(raw, dict):
        return {}
    out: dict[str, int] = {}
    for name, value in raw.items():
        if isinstance(value, int) and not isinstance(value, bool):
            out[str(name)] = value
    return out


def outcome(summary: dict[str, Any]) -> RunOutcomeResponse:
    """Headline numbers. Every one of these comes from the evaluator."""
    return RunOutcomeResponse(
        status=_get(summary, "status"),
        iterations_done=_get(summary, "iterations_done"),
        best_score=_get(summary, "best_score"),
        best_node_id=_get(summary, "best_node_id"),
        initial_score=_get(summary, "initial_score"),
        improvement=_get(summary, "improvement"),
        valid_rate=_get(summary, "valid_rate"),
        stop_reason=_get(summary, "stop_reason"),
        rounds_to_target=_get(summary, "rounds_to_target"),
        time_to_target_s=_get(summary, "time_to_target_s"),
        tokens_to_target=_get(summary, "tokens_to_target"),
        iteration_events=_get(summary, "iteration_events"),
    )


def budget(summary: dict[str, Any]) -> RunBudgetResponse:
    """Token and time accounting (TODO §5.7)."""
    return RunBudgetResponse(
        total_tokens=_get(summary, "total_tokens"),
        generate_tokens=_get(summary, "generate_tokens"),
        reflect_tokens=_get(summary, "reflect_tokens"),
        knowledge_tokens=_get(summary, "knowledge_tokens"),
        repair_tokens=_get(summary, "repair_tokens"),
        discovery_tokens=_get(summary, "discovery_tokens"),
        tournament_tokens=_get(summary, "tournament_tokens"),
        crossover_tokens=_get(summary, "crossover_tokens"),
        self_fix_tokens=_get(summary, "self_fix_tokens"),
        knowledge_token_share=_get(summary, "knowledge_token_share"),
        discovery_token_share=_get(summary, "discovery_token_share"),
        wall_time_s=_get(summary, "wall_time_s"),
        total_eval_time_s=_get(summary, "total_eval_time_s"),
        total_llm_latency_ms=_get(summary, "total_llm_latency_ms"),
        smoke_time_s_total=_get(summary, "smoke_time_s_total"),
        avg_smoke_time_s=_get(summary, "avg_smoke_time_s"),
        stage_cap_hits=_dict_of_int(summary, "stage_cap_hits"),
        budget_stop_reason=_get(summary, "budget_stop_reason"),
        tokens_per_score_gain=_get(summary, "tokens_per_score_gain"),
        tokens_per_ros_point=_get(summary, "tokens_per_ros_point"),
        expand_skipped_budget=_get(summary, "expand_skipped_budget"),
        elite_archive_sizes=_dict_of_int(summary, "elite_archive_sizes"),
    )


def repair(summary: dict[str, Any]) -> RunRepairResponse:
    """Repair / pre-check / smoke accounting (TODO §5.5)."""
    return RunRepairResponse(
        repair_attempts=_get(summary, "repair_attempts"),
        repair_successes=_get(summary, "repair_successes"),
        repair_iterations=_get(summary, "repair_iterations"),
        precheck_fixes=_get(summary, "precheck_fixes"),
        adapter_errors=_get(summary, "adapter_errors"),
        perf_rejections=_get(summary, "perf_rejections"),
        smoke_tests=_get(summary, "smoke_tests"),
        smoke_failures=_get(summary, "smoke_failures"),
        smoke_fixes=_get(summary, "smoke_fixes"),
    )


def knowledge(summary: dict[str, Any]) -> RunKnowledgeResponse:
    """Literature knowledge-package usage, including the per-card table."""
    stats: list[KnowledgeCardStatResponse] = []
    raw = summary.get("card_stats")
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict) or not item.get("card_id"):
                continue
            stats.append(
                KnowledgeCardStatResponse(
                    card_id=str(item["card_id"]),
                    n=item.get("n"),
                    sum_delta=item.get("sum_delta"),
                    mean_delta=item.get("mean_delta"),
                    refuted_count=item.get("refuted"),
                    invalid_count=item.get("invalid"),
                )
            )
    return RunKnowledgeResponse(
        cards_offered=_get(summary, "cards_offered"),
        cards_adopted=_get(summary, "cards_adopted"),
        cards_adopted_valid=_get(summary, "cards_adopted_valid"),
        card_adoption_rate=_get(summary, "card_adoption_rate"),
        card_stats=stats,
    )


def discovery_counters(summary: dict[str, Any]) -> RunDiscoveryResponse:
    """Discovery / mechanism / tournament counters.

    None of these is an evolution score; they are kept in their own group so the
    UI cannot accidentally rank a run by mechanism count.
    """
    return RunDiscoveryResponse(
        discovery_rounds=_get(summary, "discovery_rounds"),
        discovery_rounds_skipped=_get(summary, "discovery_rounds_skipped"),
        claims_proposed=_get(summary, "claims_proposed"),
        claims_tested=_get(summary, "claims_tested"),
        claims_sandbox_failed=_get(summary, "claims_sandbox_failed"),
        claims_confirmed=_get(summary, "claims_confirmed"),
        claims_revised=_get(summary, "claims_revised"),
        claims_discovered=_get(summary, "claims_discovered"),
        claims_refuted=_get(summary, "claims_refuted"),
        claims_undetermined=_get(summary, "claims_undetermined"),
        discovered_cards_count=_get(summary, "discovered_cards_count"),
        discovered_cards_offered=_get(summary, "discovered_cards_offered"),
        discovered_cards_adopted=_get(summary, "discovered_cards_adopted"),
        discovered_card_adoption_rate=_get(summary, "discovered_card_adoption_rate"),
        discovered_card_mean_delta=_get(summary, "discovered_card_mean_delta"),
        literature_card_mean_delta=_get(summary, "literature_card_mean_delta"),
        score_delta_after_discovery=_get(summary, "score_delta_after_discovery"),
        neg_control_false_positives=_get(summary, "neg_control_false_positives"),
        neg_control_fpr=_get(summary, "neg_control_fpr"),
        planted_recovery_rate=_dict_of_float(summary, "planted_recovery_rate"),
        mechanisms_proposed=_get(summary, "mechanisms_proposed"),
        mechanisms_established=_get(summary, "mechanisms_established"),
        mechanisms_refuted=_get(summary, "mechanisms_refuted"),
        mechanism_patches=_get(summary, "mechanism_patches"),
        mechanism_cards_count=_get(summary, "mechanism_cards_count"),
        matches_played=_get(summary, "matches_played"),
        decisive_matches=_get(summary, "decisive_matches"),
        underpowered_draws=_get(summary, "underpowered_draws"),
        certificates_issued=_get(summary, "certificates_issued"),
        tournament_rounds=_get(summary, "tournament_rounds"),
        planted_mechanism_recovered=_get(summary, "planted_mechanism_recovered"),
        llm_vs_data_kendall_tau=_get(summary, "llm_vs_data_kendall_tau"),
        shuffled_env_false_pass=_get(summary, "shuffled_env_false_pass"),
        min_detectable_effect=_get(summary, "min_detectable_effect"),
    )


def judge(summary: dict[str, Any]) -> RunJudgeResponse:
    """Jev screening and error-profiling cost (kept apart from scores)."""
    return RunJudgeResponse(
        jev_calls=_get(summary, "jev_calls"),
        jev_errors=_get(summary, "jev_errors"),
        jev_fail_open=_get(summary, "jev_fail_open"),
        jev_tokens=_get(summary, "jev_tokens"),
        jev_prompt_tokens=_get(summary, "jev_prompt_tokens"),
        jev_completion_tokens=_get(summary, "jev_completion_tokens"),
        jev_latency_ms=_get(summary, "jev_latency_ms"),
        jev_disabled_reason=_get(summary, "jev_disabled_reason"),
        jev_prior_active=_get(summary, "jev_prior_active"),
        candidates_screened=_get(summary, "candidates_screened"),
        evaluations_saved=_get(summary, "evaluations_saved"),
        eval_time_saved_est_s=_get(summary, "eval_time_saved_est_s"),
        screen_audited=_get(summary, "screen_audited"),
        screen_audit_bad=_get(summary, "screen_audit_bad"),
        screen_shadow=_get(summary, "screen_shadow"),
        screening_precision=_get(summary, "screening_precision"),
        analysis_calls=_get(summary, "analysis_calls"),
        analysis_failures=_get(summary, "analysis_failures"),
        analysis_time_s=_get(summary, "analysis_time_s"),
        analysis_nonempty_rate=_get(summary, "analysis_nonempty_rate"),
    )


def operators(summary: dict[str, Any]) -> RunOperatorResponse:
    """Operator mix, bandit state and crossover counters."""
    posteriors_raw = summary.get("operator_posteriors")
    posteriors: dict[str, dict[str, float]] = {}
    if isinstance(posteriors_raw, dict):
        for name, value in posteriors_raw.items():
            if isinstance(value, dict):
                posteriors[str(name)] = {
                    str(k): float(v)
                    for k, v in value.items()
                    if isinstance(v, (int, float)) and not isinstance(v, bool)
                }
    return RunOperatorResponse(
        operator_counts=_dict_of_int(summary, "operator_counts"),
        operator_valid_rate=_dict_of_float(summary, "operator_valid_rate"),
        operator_mean_delta=_dict_of_float(summary, "operator_mean_delta"),
        operator_tokens=_dict_of_int(summary, "operator_tokens"),
        operator_posteriors=posteriors,
        value_mode=_get(summary, "value_mode"),
        bandit_active=_get(summary, "bandit_active"),
        generative_valid_rate=_get(summary, "generative_valid_rate"),
        crossover_count=_get(summary, "crossover_count"),
        crossover_valid_rate=_get(summary, "crossover_valid_rate"),
        crossover_mean_delta=_get(summary, "crossover_mean_delta"),
        crossover_best_gain=_get(summary, "crossover_best_gain"),
    )


def _int(value: Any) -> int | None:
    """An integer, or ``None`` for anything that is not one (booleans included)."""
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _num(value: Any) -> float | None:
    return (
        float(value)
        if isinstance(value, (int, float)) and not isinstance(value, bool)
        else None
    )


def _int_map(raw: Any) -> dict[str, int]:
    if not isinstance(raw, dict):
        return {}
    out: dict[str, int] = {}
    for key, value in raw.items():
        if isinstance(value, int) and not isinstance(value, bool):
            out[str(key)] = value
    return out


def _text(value: Any) -> str | None:
    """A string, or ``None`` -- a non-string never reaches the UI as a coerced one."""
    return value if isinstance(value, str) else None


def islands(summary: dict[str, Any]) -> RunIslandsResponse:
    """The island ring, the exchange counters and the per-island spend.

    Read straight out of the three blocks ``island_report()`` projects, so the API
    cannot disagree with the file inside the run directory. Nothing is derived or
    back-filled here: a run that recorded nothing gets ``MISSING`` with an empty
    ring, and a block that is present but not the shape the engine writes gets
    ``INVALID`` rather than a plausible-looking zero.
    """
    raw_islands = summary.get("islands")
    raw_exchange = summary.get("exchange")
    raw_cost = summary.get("cost")

    if raw_islands is None and raw_exchange is None and raw_cost is None:
        return RunIslandsResponse(
            state=ArtifactState.MISSING,
            detail="运行未记录岛状态：单树运行早于多岛引擎，界面应按一棵树展示",
        )

    if raw_islands is None:
        return RunIslandsResponse(
            state=ArtifactState.INVALID,
            detail="run_summary.json 带有 exchange/cost 块却没有 islands，无法确定岛环",
            exchange=_exchange(raw_exchange),
            cost=_cost(raw_cost),
        )

    if not isinstance(raw_islands, dict):
        return RunIslandsResponse(
            state=ArtifactState.INVALID,
            detail="run_summary.json 的 islands 不是对象，无法读取",
            exchange=_exchange(raw_exchange),
            cost=_cost(raw_cost),
        )

    ring: dict[str, IslandViewResponse] = {}
    for island_id, row in raw_islands.items():
        if not isinstance(row, dict):
            return RunIslandsResponse(
                state=ArtifactState.INVALID,
                detail=f"islands.{island_id} 不是对象，无法读取",
                exchange=_exchange(raw_exchange),
                cost=_cost(raw_cost),
            )
        ring[str(island_id)] = IslandViewResponse(
            island_id=str(island_id),
            status=_text(row.get("status")),
            profile=_text(row.get("profile")),
            attempts=_int(row.get("attempts")),
            valid_evaluations=_int(row.get("valid_evaluations")),
            invalid_evaluations=_int(row.get("invalid_evaluations")),
            best_score=_num(row.get("best_score")),
            stop_reason=_text(row.get("stop_reason")),
        )

    if not ring:
        return RunIslandsResponse(
            state=ArtifactState.INVALID,
            detail="islands 是空对象，没有任何岛可展示",
            exchange=_exchange(raw_exchange),
            cost=_cost(raw_cost),
        )

    attempts = [row.attempts for row in ring.values() if row.attempts is not None]
    return RunIslandsResponse(
        state=ArtifactState.AVAILABLE,
        source="run_summary.json",
        islands=ring,
        exchange=_exchange(raw_exchange),
        cost=_cost(raw_cost),
        attempt_total=sum(attempts) if attempts else None,
    )


def _exchange(raw: Any) -> ExchangeViewResponse | None:
    if not isinstance(raw, dict):
        return None
    return ExchangeViewResponse(
        summaries=_int(raw.get("summaries")),
        by_kind=_int_map(raw.get("by_kind")),
        deliveries=_int(raw.get("deliveries")),
        accepted=_int(raw.get("accepted")),
        rejected=_int(raw.get("rejected")),
        applications=_int(raw.get("applications")),
        evaluated_applications=_int(raw.get("evaluated_applications")),
    )


def _cost(raw: Any) -> RunIslandCostResponse | None:
    if not isinstance(raw, dict):
        return None
    rows = raw.get("by_island")
    by_island: dict[str, IslandCostResponse] = {}
    if isinstance(rows, dict):
        for island_id, row in rows.items():
            if isinstance(row, dict):
                by_island[str(island_id)] = IslandCostResponse(
                    tokens=_int(row.get("tokens")),
                    calls=_int(row.get("calls")),
                    unresolved_calls=_int(row.get("unresolved_calls")),
                    cached_calls=_int(row.get("cached_calls")),
                    by_stage=_int_map(row.get("by_stage")),
                )
    return RunIslandCostResponse(
        total_tokens=_int(raw.get("total_tokens")),
        by_island=by_island,
        shared_tokens=_int(raw.get("shared_tokens")),
        unresolved_calls=_int(raw.get("unresolved_calls")),
        cost_usd=_num(raw.get("cost_usd")),
        cost_basis=raw.get("cost_basis"),
    )
