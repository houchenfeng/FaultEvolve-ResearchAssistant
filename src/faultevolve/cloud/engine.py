"""Evolution engine for FaultEvolve.

Implements the main evolution loop with:
- Node selection (UCT)
- Code generation (refine operator)
- Evaluation
- Three-layer reflection (implementation, design, hypothesis)
- Insight extraction and propagation
- Knowledge card injection and feedback
"""

from __future__ import annotations

import json
import os
import random
import re
import time
import uuid
from datetime import datetime
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from faultevolve.common.codecheck import (
    extract_adopted_cards_from_response,
    full_check,
)
from faultevolve.common.precheck import (
    precheck_and_fix,
    is_api_compat_error,
    get_error_fix_hint,
)
from faultevolve.common.metering import CallMetrics, RunMetrics
from faultevolve.common.research import assess_goals
from faultevolve.common.textutil import sanitize_error_info
from faultevolve.common.schemas import (
    Event,
    IslandStatus,
    Experiment,
    ExperimentConfig,
    EvaluationResult,
    HypothesisStatus,
    Insight,
    Node,
    NodeEvidence,
    NodeStatus,
    OperatorType,
    RunSummary,
    EXCHANGE_KINDS,
    GENERATIVE_OPERATORS,
)
from faultevolve.cloud.insights import (
    BranchMemoryManager,
    InsightExtractor,
    LayeredReflector,
    get_foreign_insights,
    record_mechanism_insight,
    update_insight_reputation,
)
from faultevolve.cloud.judge import JudgeClient, PrescreenResult
from faultevolve.cloud.llm import DashScopeLLM, LLMClient, LLMTransientError, MockLLM, create_llm_call_record
from faultevolve.cloud.crossover import (
    estimate_runtime_s,
    select_crossover_partner,
    valid_node_count,
)
from faultevolve.cloud.operators import (
    CrossoverOperator,
    GenerationResult,
    OperatorContext,
    RefineOperator,
    RepairOperator,
    classify_error,
    fn_profile_keywords,
    operator_posterior_summary,
    select_operator,
)
from faultevolve.cloud.budget import BudgetController, token_cap_exceeded, wall_cap_exceeded
from faultevolve.cloud.engine_autotune import (
    init_ledger,
    ledger_record,
    ledger_would_block_full_eval,
    parent_has_patch_blocks,
    run_hpo_quota_iteration,
)
from faultevolve.optimization.ledger import CostLedger
from faultevolve.optimization.quota import next_operator
from faultevolve.cloud.selection import UCTSelector, get_era_knowledge_cards
from faultevolve.knowledge.loader import ORIGIN_FROZEN
from faultevolve.cloud.store import SCHEMA_VERSION, Store, now_iso
from faultevolve.cloud.tree import Tree, create_child_node, create_init_node, create_repair_node
from faultevolve.cloud.islands import (
    IslandCoordinator,
    IslandRuntime,
    apply_profile_defaults,
    build_runtimes,
    legacy_island_spec,
    profile_focus,
    seeded_island_rng,
)
from faultevolve.cloud.exchange import (
    IslandExchange,
    SummaryContext,
    evaluator_fingerprint,
    task_fingerprint,
)
from faultevolve.cloud.resume import (
    CHECKED_FIELDS,
    RunBusy,
    RunIdentity,
    ResumeRefused,
    capture_identity,
    check_identity,
    claim_is_foreign_death,
    claim_is_live,
    clone_run_directory,
    known_fields,
    new_holder_id,
    rng_from_snapshot,
    run_claim_summary,
    snapshot_rng,
)
from faultevolve.config import EvolveConfig, IslandSpec
from faultevolve.discovery.certificates import write_json as write_certificate_artifacts
from faultevolve.discovery.mech_promotion import promote_mechanisms
from faultevolve.discovery.pipeline import DiscoveryRound
from faultevolve.discovery.schemas import (
    Certificate,
    Claim,
    DiscoveryStats,
    Mechanism,
    TournamentStats,
)
from faultevolve.discovery.tournament import Tournament
from faultevolve.tasks.protocol import (
    ErrorProfiler,
    EvalResult,
    ObjectiveBriefProvider,
    ObjectiveSpec,
    TaskAdapter,
    TaskSpec,
)


MAX_REPAIR_ATTEMPTS = 2

_ENABLED_OPERATOR_MAP = {
    "refine": OperatorType.REFINE,
    "recall_focus": OperatorType.RECALL_FOCUS,
    "threshold_calibrate": OperatorType.THRESHOLD_CALIBRATE,
    "inject": OperatorType.INJECT,
}
DEGENERATE_SCORE_THRESHOLD = 5.0

#: Accounting bucket -> cost stage name, shared by the ledger and the ``llm_call``
#: rows so the two can never start calling the same call by different names.
LLM_STAGE_MAP = {
    "generate": "generate",
    "refine": "generate",
    "repair": "repair",
    "reflect": "reflect",
    "crossover": "crossover",
    "self_fix": "self_fix",
}

#: Cost row purpose -> the :class:`RunMetrics` bucket it was accounted into.
#: ``_meter_llm_call`` can name a row after the work it did (``refine``,
#: ``jev_prescreen``) while bucketing it under the line the budget reads
#: (``generate``, ``jev``), so a resumed run has to translate back before it
#: replays the rows -- otherwise those tokens exist in the ledger and count
#: toward nothing.
_COST_ROW_TO_BUCKET = {
    "refine": "generate",
    "summary_cross": "generate",
    "jev_prescreen": "jev",
}


class DiscoveryLLMError(Exception):
    """Raised when discovery LLM call fails transiently."""


@dataclass
class DeferredCandidate:
    node_id: str
    parent_id: str
    value: float
    offered_card_ids: list[str]


@dataclass
class KnowledgeSelection:
    """What knowledge one generation attempt was handed, and why that is it.

    A finished run has to be able to name the card ids a candidate actually saw.
    "the knowledge switch was on" is not that answer, and an empty selection is a
    normal outcome rather than a failure -- so the reason for the emptiness is
    carried next to the ids instead of being inferred later.
    """

    cards: list[dict[str, Any]] = field(default_factory=list)
    island_id: str = ""
    profile: str = ""
    island_keywords: list[str] = field(default_factory=list)
    reason: str = ""
    error_type: str = ""

    def sources_by_origin(self) -> dict[str, list[str]]:
        """Card ids grouped by the library they were read from.

        ``frozen`` is the task's checked-in library, ``run_new`` a card file this
        run produced; the tag is set where the cards are loaded, not guessed from
        the id here.
        """
        grouped: dict[str, list[str]] = {}
        for card in self.cards:
            origin = str(card.get("origin") or ORIGIN_FROZEN)
            grouped.setdefault(origin, []).append(str(card.get("id", "")))
        return {origin: sorted(ids) for origin, ids in sorted(grouped.items())}

    def event_payload(
        self,
        *,
        parent_id: str,
        operator: str,
        estimated_tokens: int = 0,
    ) -> dict[str, Any]:
        return {
            "island_id": self.island_id,
            "profile": self.profile,
            "parent_id": parent_id,
            "operator": operator,
            "selected": bool(self.cards),
            "card_ids": [str(card.get("id", "")) for card in self.cards],
            "sources": self.sources_by_origin(),
            "island_keywords": list(self.island_keywords),
            "reason": self.reason,
            "error_type": self.error_type,
            # Written down rather than left in the counter: the knowledge stage cap
            # is checked again after a resume, and the only way to know what the
            # interrupted run injected is to have recorded the estimate it used.
            "estimated_tokens": int(estimated_tokens),
        }


class EvolutionEngine:
    """Main evolution engine."""

    def __init__(
        self,
        config: EvolveConfig,
        task_adapter: TaskAdapter,
        task_spec: TaskSpec,
        store: Store,
        llm: DashScopeLLM | MockLLM,
        mock: bool = False,
        task_dir: Path | None = None,
        judge: JudgeClient | None = None,
    ) -> None:
        """Initialize the engine.

        Args:
            config: Evolution configuration
            task_adapter: Task adapter for evaluation
            task_spec: Task specification
            store: Database store
            llm: LLM client
            mock: Whether running in mock mode
            task_dir: Task directory for knowledge loading
        """
        self.config = config
        self.task_adapter = task_adapter
        self.task_spec = task_spec
        self.store = store
        self.llm = llm
        self.mock = mock
        self.task_dir = task_dir

        self.experiment_id = ""
        self.tree: Tree | None = None
        self.selector: UCTSelector | None = None
        self.judge = judge
        self.operator = RefineOperator(llm)
        self.crossover_operator = CrossoverOperator(llm)
        self.repair_operator = RepairOperator(llm)
        self._crossover_partners: dict[str, str] = {}
        self.insight_extractor = InsightExtractor(llm)
        self.metrics = RunMetrics()
        self.error_class_counts: dict[str, int] = {}
        self._constraints_text: str = ""
        self._api_notes: str = ""
        self._invalid_penalty_factor: float = 2.0
        self._branch_invalid_threshold: int = 2
        self._smoke_data_dir: Path | None = None
        self._audit_rng = random.Random(config.seed)
        self._jev_values: dict[str, float] = {}
        self._deferred: list[DeferredCandidate] = []
        self._circuit_event_emitted = False
        self._objective_brief: str = ""
        self.budget = BudgetController(config.budget)
        self._budget_stop_reason = ""
        self._initial_score = 0.0
        self._op_rng = random.Random(config.seed + 1009)
        self._op_tokens: dict[str, int] = {}
        self._discovery: DiscoveryRound | None = None
        self._dstats = DiscoveryStats()
        self._pending_claims: list[tuple[str, dict]] = []
        self._last_discovery_iter = 0
        self.artifacts_dir: Path | None = None
        self._structure_tuner = None
        self._tournament: Tournament | None = None
        self._tstats = TournamentStats()
        self._tournament_rounds = 0
        self._offered_insights: dict[str, list[str]] = {}
        self._tournament_results: dict[str, Any] = {}
        self._mechanism_layer = False
        self._cost_ledger = None
        self._quota_counts: dict[str, int] = {"hpo": 0, "patch": 0, "draft": 0}
        self._plateau_evals_since_improve = 0
        self._restart_count = 0
        self._ledger_stop = False
        self._hpo_family_cursor = 0
        self._hpo_family_trial_index: dict[str, int] = {}
        self._hpo_used_fits = 0
        self._hpo_dev_ctx = None
        self.patch_operator = None
        # Island scaffolding. ``tree``/``selector`` and the other entries of
        # ``ISLAND_ATTRS`` above are per island: the coordinator swaps them in
        # when it activates one, so the search code below stays single-tree.
        self._coordinator: IslandCoordinator | None = None
        #: None until an island is activated; "" is a real island id (legacy).
        self._active_island: str | None = None
        self._island_focus = ""
        self._exchange: IslandExchange | None = None
        self._summary_contexts: list[SummaryContext] = []
        self._summary_applications: dict[str, list[str]] = {}
        self._init_eval_error: str = ""
        self._all_islands_stopped = False
        #: Resume bookkeeping. ``_holder_id`` is this process's name on the run
        #: claim, so a second launch can see that the run is already being written.
        self._holder_id = new_holder_id()
        self._claims_run = False
        self._resumed = False
        self._resume_check: dict[str, Any] = {}
        self._interrupted_claim: dict[str, Any] = {}

    def initialize(
        self,
        resume_id: str | None = None,
        experiment_id: str | None = None,
    ) -> str:
        """Initialize or resume an experiment.

        Args:
            resume_id: ID of experiment to resume, or None for new
            experiment_id: Pre-assigned experiment ID for new experiments

        Returns:
            Experiment ID
        """
        # One island at a time is what this engine actually implements. Accepting
        # concurrency number and then ignoring it would let a run look like it had
        # three evaluations in flight while the ledger said one -- so refuse.
        if self.config.islands.eval_concurrency > 1:
            raise ValueError(
                "islands.eval_concurrency > 1 is not implemented: islands run "
                f"serially, got {self.config.islands.eval_concurrency}"
            )
        if resume_id:
            experiment = self.store.get_experiment(resume_id)
            if experiment is None:
                raise ValueError(f"Experiment {resume_id} not found")
            self.experiment_id = resume_id
        else:
            self.experiment_id = experiment_id or str(uuid.uuid4())[:8]
            experiment = Experiment(
                id=self.experiment_id,
                name=f"fe-local-{self.experiment_id}",
                status="running",
                config=ExperimentConfig(
                    max_iterations=self.config.budget.max_iterations,
                    max_tokens=self.config.budget.max_tokens,
                    target_score=self.config.stop.target_score,
                    c_puct=self.config.selection.c_puct,
                    seed=self.config.seed,
                ),
                problem_md=self.task_spec.problem_md,
                prompt_md=self.task_spec.prompt_md,
                created_at=now_iso(),
            )
            self.store.create_experiment(experiment)

        specs = self._resolve_island_specs(resuming=bool(resume_id))
        # Before anything is written: a resume that would silently continue a
        # different experiment has to stop here, not halfway through its first
        # island, and a run that another live process already holds has to be
        # refused before the two of them write one database.
        self._resumed = bool(resume_id)
        self._verify_run_identity(specs, resuming=self._resumed)
        research_contract = self.config.research.model_dump() if self.config.research else None
        contracts = [event.payload.get("config") for event in self.store.get_events(self.experiment_id)
                     if event.type == "research_contract"]
        if self._resumed and research_contract is not None and not contracts:
            raise ValueError("旧实验没有科研目标契约；请创建新实验，避免变更验收标准")
        if contracts and contracts[-1] != research_contract:
            raise ValueError("科研目标契约发生变化；请创建新实验")
        self._take_run_claim()
        if self.config.research:
            self.store.update_experiment(self.experiment_id, status="running")
        if not self._resumed:
            self._log_event("research_contract", {"config": research_contract})

        if self.judge is None:
            self.judge = JudgeClient(self.config)

        self._shared_context_setup()

        self._coordinator = IslandCoordinator(
            self.experiment_id,
            build_runtimes(self.experiment_id, specs, self.store),
            self.store,
            self._log_event,
        )
        self._coordinator.rng_snapshot = self._rng_snapshot_states
        self._coordinator.restore_cursor()
        # A summary channel only exists when there is more than one tree to
        # exchange between; a single island has no sibling to describe.
        if self._coordinator.multi:
            self._exchange = IslandExchange(
                store=self.store,
                experiment_id=self.experiment_id,
                islands=self.config.islands,
                log_event=self._log_event,
                task_fp=task_fingerprint(self.task_spec),
                evaluator_fp=evaluator_fingerprint(self.task_spec),
            )
        for island_id in self._coordinator.order:
            self._prepare_runtime(self._coordinator.runtime(island_id))
        # After the runtimes exist, because preparing one builds its operator
        # stream from the seed; a resumed run replaces that stream with the one the
        # interrupted process had actually advanced through.
        self._apply_restored_rng()

        self._activate_island(self._coordinator.order[0])
        if (self.config.workflow.enabled and self.config.workflow.hierarchical.enabled
                and self.config.workflow.hierarchical.mode == "per_structure"):
            # The global evaluation cap includes the shared, untuned baseline.
            init_ledger(self)
        self._init_island_roots()
        for island_id in self._coordinator.order:
            self._activate_island(island_id)
            self._prime_selector()
        self._activate_island(self._coordinator.order[0])

        self._sync_selector_priors()
        if self._cost_ledger is None:
            init_ledger(self)
        if self.config.autotune.patch.enabled:
            from faultevolve.cloud.operators import PatchOperator

            self.patch_operator = PatchOperator(self.llm)

        return self.experiment_id

    def _verify_run_identity(self, specs: list[IslandSpec], *, resuming: bool) -> RunIdentity:
        """Record what this run is, and refuse a resume that would not be it.

        A new run writes its identity. A resumed run reads it back and compares:
        task text, evaluator, baseline code, data descriptor, island ring, schema
        and seed. Anything both sides can describe must agree; a field the stored
        run described and this one cannot is treated as a change too, because the
        only way it can disappear is that the thing it described moved.
        """
        incoming = capture_identity(
            self.task_spec,
            [spec.island_id for spec in specs],
            schema_version=SCHEMA_VERSION,
            seed=self.config.seed,
        )
        stored_json = self.store.get_run_identity(self.experiment_id)
        if not resuming:
            self.store.put_run_identity(self.experiment_id, incoming.to_json())
            return incoming
        if stored_json is None:
            # A run started before this record existed cannot be compared field by
            # field. The experiment row still carries the task text it was created
            # with, so a resume that changed the question is still refused; the rest
            # is reported as unverified and filled in on the way through.
            experiment = self.store.get_experiment(self.experiment_id)
            was = task_fingerprint(experiment) if experiment is not None else ""
            if was and incoming.task_fp and was != incoming.task_fp:
                self._log_event("run_resume_refused", {
                    "mismatches": {"task_fp": {"stored": was, "now": incoming.task_fp}},
                    "lost": [],
                    "reason": "no identity record; the experiment row reads differently",
                })
                raise ResumeRefused(self.experiment_id, {"task_fp": (was, incoming.task_fp)})
            self._resume_check = {
                "verified": ["task_fp"] if was else [],
                "unverified": ["no identity record"],
            }
            self.store.put_run_identity(self.experiment_id, incoming.to_json())
            return incoming
        stored = RunIdentity.from_json(stored_json)
        mismatches, lost = check_identity(stored, incoming)
        if mismatches or lost:
            self._log_event("run_resume_refused", {
                "mismatches": {k: {"stored": w, "now": n} for k, (w, n) in mismatches.items()},
                "lost": lost,
            })
            raise ResumeRefused(self.experiment_id, mismatches, lost)
        verified = known_fields(stored)
        self._resume_check = {
            "verified": verified,
            "unverified": [name for name in CHECKED_FIELDS if name not in verified],
        }
        # Fill in what the old run never described, so the next resume can check it.
        if self._resume_check["unverified"]:
            self.store.put_run_identity(self.experiment_id, incoming.to_json())
        return incoming

    def _take_run_claim(self) -> None:
        """Hold the run so a second process cannot start against the same database.

        A claim whose process is gone is not a lock: that attempt stopped without
        finishing, and the honest record of it is a ``run_interrupted`` event naming
        the dead holder, written before the new holder takes over so the gap between
        the two attempts stays visible. A claim left by *this* process is not another
        execution -- an engine rebuilt in the same process just takes it over.
        """
        my_pid = os.getpid()
        existing = self.store.get_run_claim(self.experiment_id)
        if claim_is_live(existing, current_pid=my_pid):
            raise RunBusy(
                self.experiment_id,
                str(existing.get("holder_id", "")),
                existing.get("holder_pid"),
            )
        if claim_is_foreign_death(existing, current_pid=my_pid):
            self._interrupted_claim = run_claim_summary(existing)
            experiment = self.store.get_experiment(self.experiment_id)
            self._log_event("run_interrupted", {
                "previous_holder": self._interrupted_claim,
                "iterations_done": experiment.iterations_done if experiment else 0,
            })
        self.store.take_run_claim(self.experiment_id, self._holder_id, my_pid)
        self._claims_run = True

    def _release_run_claim(self) -> None:
        if self._claims_run:
            self.store.release_run_claim(self.experiment_id, self._holder_id)
            self._claims_run = False

    def _rng_snapshot_states(self) -> dict[str, str]:
        """Every island's operator stream, keyed by island id."""
        if self._coordinator is None:
            return {}
        states: dict[str, str] = {}
        for island_id in self._coordinator.order:
            rng = self._coordinator.runtime(island_id).attrs.get("_op_rng")
            if isinstance(rng, random.Random):
                states[island_id] = snapshot_rng(rng)
        return states

    def _apply_restored_rng(self) -> None:
        """Continue each island's stream instead of re-deriving it from the seed.

        Without this, a resume reproduces the interrupted run's *first* choices
        again: the stream is seeded from the persisted operator counts, so the same
        explores repeat and the island wastes attempts it already spent.
        """
        if self._coordinator is None:
            return
        for island_id, payload in self._coordinator.rng_states.items():
            rt = self._coordinator.runtimes.get(island_id)
            if rt is None:
                continue
            rng = rng_from_snapshot(payload)
            if rng is not None:
                rt.attrs["_op_rng"] = rng

    def _restore_run_cost(self) -> dict[str, Any]:
        """Replay the stored cost rows into the fresh run's counters.

        ``run()`` has to start from an empty :class:`RunMetrics` because the counters
        are per-process objects, but a resume that starts at zero token spend can
        blow the budget twice over: the budget check reads what the counter says, not
        what the run has cost. Replaying the rows through ``add_llm_call`` uses the
        same accumulator the live calls used, so the restored total cannot drift
        from the ledger by construction.
        """
        rows = self.store.get_llm_calls(self.experiment_id)
        replayed = 0
        for row in rows:
            self.metrics.add_llm_call(
                CallMetrics(
                    prompt_tokens=row.prompt_tokens,
                    completion_tokens=row.completion_tokens,
                    latency_ms=row.latency_ms,
                    request_id=row.request_id,
                    attempts=row.transport_attempts,
                ),
                _COST_ROW_TO_BUCKET.get(row.purpose, row.purpose),
            )
            replayed += 1
        knowledge = 0
        for event in self.store.get_events(self.experiment_id):
            if event.type == "knowledge_injected":
                knowledge += int(event.payload.get("estimated_tokens", 0) or 0)
        if knowledge:
            self.metrics.add_knowledge_tokens(knowledge)
        return {
            "cost_rows": replayed,
            "total_tokens": self.metrics.total_tokens,
            "knowledge_tokens": self.metrics.knowledge_tokens,
            "iterations_done": self.metrics.iterations_done,
            "island_states": {
                rt.island_id or "legacy": {
                    "attempts": rt.state.attempts,
                    "status": str(rt.state.status),
                    "best_score": rt.state.best_score,
                }
                for rt in self._island_nodes()
            },
        }

    def _resolve_island_specs(self, resuming: bool) -> list[IslandSpec]:
        """Which islands this run owns.

        A resumed run is driven by what is already persisted: a pre-island
        experiment keeps its single implicit island (empty id) and never gains
        two islands because the current default config happens to have three.
        """
        cfg = self.config.islands
        if resuming:
            persisted = self.store.get_island_states(self.experiment_id)
            if not persisted:
                nodes = self.store.get_nodes_by_experiment(self.experiment_id)
                islands = {n.island_id for n in nodes} or {""}
                if islands == {""}:
                    return [legacy_island_spec()]
                by_id = {s.island_id: s for s in cfg.islands}
                return [
                    by_id.get(iid) or IslandSpec(
                        island_id=iid,
                        profile="performance",
                        focus=profile_focus("performance"),
                    )
                    for iid in sorted(islands)
                ]
            by_id = {s.island_id: s for s in cfg.islands}
            out: list[IslandSpec] = []
            for state in persisted:
                spec = by_id.get(state.island_id)
                if spec is None:
                    spec = IslandSpec(
                        island_id=state.island_id,
                        profile=state.profile,
                        focus=profile_focus(state.profile),
                    )
                out.append(apply_profile_defaults(spec))
            return out
        if not cfg.enabled:
            return [legacy_island_spec()]
        return [apply_profile_defaults(spec) for spec in cfg.islands]

    def _shared_context_setup(self) -> None:
        """Task-level prompt context, identical for every island."""
        self._constraints_text = self.task_adapter.constraints(self.task_spec)
        if self.config.research:
            goals = "; ".join(f"{target.metric} {target.op} {target.value}"
                              for target in self.config.research.targets)
            self._constraints_text += (
                "\nResearch acceptance: one candidate must satisfy ALL constraints: " + goals
                + ". Optimize the evaluator's combined_score without changing its definition."
            )
        if hasattr(self.task_adapter, "api_notes"):
            self._api_notes = self.task_adapter.api_notes()
        if self._api_notes:
            self._constraints_text = f"{self._constraints_text}\n\n{self._api_notes}".strip()

        if hasattr(self.task_adapter, "data_schema"):
            data_schema = self.task_adapter.data_schema()
            if data_schema:
                self._constraints_text = f"{self._constraints_text}\n\n{data_schema}".strip()

        if hasattr(self.task_adapter, "edit_guidance"):
            edit_guidance = self.task_adapter.edit_guidance()
            if edit_guidance:
                self._constraints_text = f"{self._constraints_text}\n\n{edit_guidance}".strip()

        self._objective_brief = ""
        if isinstance(self.task_adapter, ObjectiveBriefProvider):
            try:
                self._objective_brief = self.task_adapter.objective_brief(self.task_spec)
            except Exception as e:
                self._log_event("objective_brief_failed", {
                    "error_type": type(e).__name__,
                })

    def _fresh_island_attrs(self, island_id: str) -> dict[str, Any]:
        """A clean set of the per-island mutable objects.

        The empty-string island keeps the historical integer seed formula so a
        resumed legacy run reproduces its old operator stream; named islands get
        a seed that also mixes in the island id, which is what makes their
        exploration sequences independent.
        """
        rows = self.store.get_operator_stats(self.experiment_id, island_id=island_id)
        total_n = sum(int(r["n"]) for r in rows.values())
        if island_id == "":
            rng = random.Random(self.config.seed + 1009 + total_n)
        else:
            rng = seeded_island_rng(self.config.seed, island_id, total_n)
        return {
            "tree": None,
            "selector": None,
            "_jev_values": {},
            "_deferred": [],
            "_op_tokens": {},
            "_op_rng": rng,
            "_crossover_partners": {},
            "_offered_insights": {},
            "_summary_contexts": [],
            "_summary_applications": {},
            "error_class_counts": {},
            "_quota_counts": {"hpo": 0, "patch": 0, "draft": 0},
            "_plateau_evals_since_improve": 0,
            "_hpo_family_cursor": 0,
            "_hpo_family_trial_index": {},
            "_hpo_used_fits": 0,
            "_hpo_dev_ctx": None,
            "_island_focus": "",
        }

    def _prepare_runtime(self, rt: IslandRuntime) -> None:
        """Give one island its own tree view, selector and mutable state."""
        rt.attrs = self._fresh_island_attrs(rt.island_id)
        rt.attrs["_island_focus"] = rt.spec.focus
        tree = Tree(self.experiment_id, self.store, island_id=rt.island_id)
        # `node_created` hangs off the tree's single add funnel, so no creation
        # site can forget it. Installed *after* load_from_store, which fills
        # `tree.nodes` directly and therefore must not re-announce the nodes a
        # resumed run already has.
        tree.on_node_added = self._log_node_created
        tree.load_from_store()
        rt.attrs["tree"] = tree
        rt.attrs["selector"] = UCTSelector(self.config)
        rt.attrs["_summary_applications"] = self._pending_summary_applications(tree)
        if tree.get_root() is not None:
            best_id, best_score = tree.get_island_best()
            rt.state.root_id = tree.root_id
            if rt.state.best_node_id is None:
                rt.state.best_node_id = best_id
                rt.state.best_score = best_score
            if rt.state.status in (IslandStatus.PENDING, IslandStatus.RUNNING):
                rt.state.status = IslandStatus.RUNNING
        if rt.exhausted and rt.state.status in (IslandStatus.PENDING, IslandStatus.RUNNING):
            rt.state.status = IslandStatus.FINISHED
            rt.state.stop_reason = rt.state.stop_reason or "max_attempts"
        self._coordinator.save_states()

    def _pending_summary_applications(self, tree: Tree) -> dict[str, list[str]]:
        """Applications this island recorded but never got a result for.

        The map is in-memory and the row is not, so a restart without this loses
        the link: the candidate that was built from a sibling's summary would be
        evaluated and scored without the summary ever learning it helped. Only
        unfinished rows (no ``evaluation_id``) for nodes that really live in this
        island's tree are re-attached, so a row whose candidate was abandoned
        stays a record of an application that never paid off.
        """
        if self._exchange is None:
            return {}
        pending: dict[str, list[str]] = {}
        for row in self.store.get_applications_by_experiment(self.experiment_id):
            if row.evaluation_id:
                continue
            node = tree.nodes.get(row.candidate_node_id)
            if node is None:
                continue
            pending.setdefault(row.candidate_node_id, []).append(row.application_id)
        return pending

    def _activate_island(self, island_id: str) -> None:
        """Point the engine's island-scoped attributes at one island."""
        if self._coordinator is None:
            return
        if island_id == self._active_island:
            return
        previous = self._active_island
        if previous is not None and previous in self._coordinator.runtimes:
            self._coordinator.runtime(previous).store_from(self)
        rt = self._coordinator.runtime(island_id)
        self._active_island = island_id
        rt.load_into(self)

    def _island_nodes(self) -> list[IslandRuntime]:
        if self._coordinator is None:
            return []
        return [self._coordinator.runtime(iid) for iid in self._coordinator.order]

    def _sync_island_states(self) -> None:
        """Refresh the persisted counters of every island from live objects."""
        for rt in self._island_nodes():
            tree = rt.attrs.get("tree")
            if tree is not None and tree.root_id:
                rt.state.root_id = tree.root_id
                best_id, best_score = tree.get_island_best()
                rt.state.best_node_id = best_id
                rt.state.best_score = best_score
        self._coordinator.save_states()

    def _prime_selector(self) -> None:
        """Install task objectives and replay this island's nodes into its selector."""
        if self.selector is None or self.tree is None:
            return
        if isinstance(self.task_adapter, ObjectiveSpec):
            try:
                self.selector.set_objective_spec(
                    self.task_adapter.objectives(),
                    self.task_adapter.threshold_objectives(),
                    self.task_adapter.noise_metric(),
                )
            except Exception as e:
                self._log_event("objective_spec_failed", {
                    "error_type": type(e).__name__,
                })
        root = self.tree.get_root()
        if root is not None:
            self.selector.set_reference(root)
        for node in self.tree.nodes.values():
            self._observe_node(node)
        if (
            self.config.selection.value.mode == "multi"
            and not self.selector.multi_active
        ):
            self._log_event("value_mode_fallback", {
                "reason": "no_objective_metrics",
                "island_id": self._active_island,
            })

    def _init_island_roots(self) -> None:
        """Create (or restore) one root per island from a single real evaluation.

        The islands share the same initial code, so evaluating it three times
        would buy nothing and charge the run three times. One evaluator call
        fills every root, ``shared_initial_evaluation_id`` records which root
        the numbers came from, and the ledger sees exactly one full
        evaluation.
        """
        runtimes = self._island_nodes()
        trees = [rt.attrs["tree"] for rt in runtimes]
        if all(tree.get_root() is not None for tree in trees):
            for rt in runtimes:
                self._activate_island(rt.island_id)
                self._restore_jev_state()
            self._activate_island(runtimes[0].island_id)
            self._sync_island_states()
            return
        if any(tree.get_root() is not None for tree in trees):
            raise ValueError(
                "partial island initialization: some islands have a root and others "
                "do not; a run must be resumed or started, never half-created"
            )

        shared: tuple[Any, NodeEvidence] | None = None
        shared_id: str | None = None
        for rt in runtimes:
            self._activate_island(rt.island_id)
            node, result, evidence = self._create_root_for_island(rt, shared, shared_id)
            if node is None:
                # No evaluation happened (the cost ledger refused it), so there
                # are no numbers to hand the remaining islands.
                break
            if shared is None:
                shared = (result, evidence)
                shared_id = node.id
        if shared is not None and self._init_eval_error:
            # An invalid baseline is not a baseline: every island is closed with
            # the reason, so the scheduler ends the run instead of searching from
            # a zero-score root.
            for rt in runtimes:
                rt.state.status = IslandStatus.FINISHED
                rt.state.stop_reason = "init_evaluation_invalid"
            self._log_event("run_aborted_invalid_init", {"reason": self._init_eval_error})
        self._initial_score = self._best_across_islands()[1]
        if shared is not None and not self._init_eval_error:
            best_id, best_score = self._best_across_islands()
            self.store.update_experiment(
                self.experiment_id,
                best_node_id=best_id,
                best_score=best_score,
            )
        self._activate_island(runtimes[0].island_id)
        self._sync_island_states()

    def _create_root_for_island(
        self,
        rt: IslandRuntime,
        shared: tuple[Any, NodeEvidence] | None,
        shared_id: str | None,
    ) -> tuple[Node | None, Any, NodeEvidence]:
        """Root one island, reusing the already evaluated shared init."""
        init_node = create_init_node(
            experiment_id=self.experiment_id,
            branch_id="main",
            code=self.task_spec.init_code,
            intent="Initial solution",
            island_id=rt.island_id,
        )
        self.tree.add_node(init_node)

        if shared is not None:
            eval_result, evidence = shared
            self.tree.update_node_evidence(init_node.id, evidence)
            self.selector.set_initial_score(eval_result.combined_score)
            self.selector.set_noise_delta(evidence.noise_delta or 0.5)
            rt.state.root_id = init_node.id
            rt.state.best_node_id = init_node.id
            rt.state.best_score = eval_result.combined_score
            rt.state.shared_initial_evaluation_id = shared_id
            # The evaluation was paid for once, but this island's root really is
            # evaluated: its stall counter starts at the same place as the island
            # that ran the evaluator.
            rt.state.valid_evaluations = 1 if eval_result.is_valid else 0
            rt.state.status = (
                IslandStatus.RUNNING if eval_result.is_valid else IslandStatus.FINISHED
            )
            self._log_event("init_evaluated", {
                "node_id": init_node.id,
                "island_id": rt.island_id,
                "score": eval_result.combined_score,
                "shared_initial_evaluation_id": shared_id,
                "metric": eval_result.metric,
            })
            return init_node, eval_result, evidence

        if ledger_would_block_full_eval(self):
            self._ledger_stop = True
            return None, None, NodeEvidence()
        t0 = time.time()
        try:
            eval_result = self.task_adapter.evaluate(
                init_node.artifact.code,
                self.task_spec,
            )
        except Exception as e:
            self._init_eval_error = f"evaluate_exception:{type(e).__name__}"
            self._note_infra_failure("init_evaluate_exception", {
                "node_id": init_node.id,
                "island_id": rt.island_id,
                "error_type": type(e).__name__,
            })
            raise
        ledger_record(
            self,
            stage="full_eval",
            fidelity="full_val",
            node_id=init_node.id,
            evaluator_calls=1,
            wall_s=time.time() - t0,
        )

        evidence = NodeEvidence(
            evaluation=EvaluationResult(
                validity=eval_result.validity,
                combined_score=eval_result.combined_score,
                cost_time=eval_result.cost_time,
                error_info=eval_result.error_info,
                metric=eval_result.metric,
            ),
            noise_delta=self.task_adapter.get_noise_delta(eval_result),
        )
        self.tree.update_node_evidence(init_node.id, evidence)

        self.selector.set_initial_score(eval_result.combined_score)
        self.selector.set_noise_delta(evidence.noise_delta or 0.5)
        rt.state.root_id = init_node.id
        rt.state.valid_evaluations = 1 if eval_result.is_valid else 0
        rt.state.shared_initial_evaluation_id = init_node.id
        if not eval_result.is_valid:
            # An invalid baseline is not a baseline: the formal protocol stops
            # here instead of optimizing against a zero score.
            self._init_eval_error = eval_result.error_info or "init_invalid"
            rt.state.stop_reason = "init_evaluation_invalid"
            self._log_event("init_evaluation_invalid", {
                "node_id": init_node.id,
                "island_id": rt.island_id,
                "error_info": sanitize_error_info(eval_result.error_info or "")[:400],
            })
        else:
            rt.state.status = IslandStatus.RUNNING
        rt.state.best_node_id = init_node.id
        rt.state.best_score = eval_result.combined_score
        self._log_event("init_evaluated", {
            "node_id": init_node.id,
            "island_id": rt.island_id,
            "score": eval_result.combined_score,
            "metric": eval_result.metric,
        })
        return init_node, eval_result, evidence

    def _best_across_islands(self) -> tuple[str | None, float]:
        """Global best over every island's own best, for reporting only.

        Single-island runs get the same answer the old ``get_global_best`` gave,
        so nothing downstream needs to know how many islands exist.
        """
        runtimes = self._island_nodes()
        if not runtimes:
            return None, 0.0
        best_id, best_score = None, float("-inf")
        for rt in runtimes:
            tree = rt.attrs.get("tree")
            if tree is None:
                continue
            node_id, score = tree.get_island_best()
            if node_id is not None and score > best_score:
                best_id, best_score = node_id, score
        if best_id is None:
            return None, 0.0
        return best_id, best_score


    def _active_runtime(self) -> IslandRuntime | None:
        if self._coordinator is None or self._active_island is None:
            return None
        return self._coordinator.runtime(self._active_island)

    def _count_attempt(self, parent: Node, operator: OperatorType) -> None:
        """Charge one attempt to the active island when generation starts.

        The counter tracks candidate attempts, not operator kinds: an HPO or
        repair candidate spends the same unit of the island budget as a refine,
        so the 50-attempt protocol limit means the same thing everywhere.
        """
        rt = self._active_runtime()
        if rt is None:
            return
        rt.state.attempts += 1
        self._coordinator.save_states()
        self._log_event("attempt_started", {
            "island_id": rt.island_id,
            "profile": rt.profile,
            "attempt": rt.state.attempts,
            "max_attempts": rt.spec.max_attempts,
            "parent_id": parent.id,
            "operator": operator.value,
        })

    def _record_evaluation_outcome(
        self,
        *,
        node_id: str,
        valid: bool,
        score: float,
        previous_best: float,
    ) -> None:
        """Fold one completed real evaluation into the active island counters.

        Only evaluations that actually ran count: a ledger-blocked or
        infrastructure-failed candidate is handled by :meth:`_note_infra_failure`
        instead, so an outage cannot look like a stalled island.

        The island's own champion is updated here rather than only at the end of
        the iteration: the score is known the moment the evaluator returns, and a
        run that dies mid-iteration should not resume having forgotten which node
        it was proud of.
        """
        rt = self._active_runtime()
        if rt is None:
            return
        state = rt.state
        state.infra_fail_streak = 0
        if not valid:
            state.invalid_evaluations += 1
        else:
            state.valid_evaluations += 1
            # combined_score is direction-normalized by the task adapter (higher is
            # better for both ROS-style and accuracy-style tasks), so "no
            # improvement" is always "not above the island best so far".
            if score > previous_best:
                state.stall_valid_evals = 0
                state.consecutive_failures = 0
            else:
                state.stall_valid_evals += 1
            if score > state.best_score:
                state.best_node_id = node_id
                state.best_score = score
        self._coordinator.save_state(rt.island_id)

    def _note_infra_failure(self, reason: str, payload: dict[str, Any]) -> None:
        """Record an infrastructure failure (evaluator itself, not the candidate).

        The streak is persisted immediately: an outage that crashes the process
        must still count toward the paused-island rule after a resume, instead of
        every restart beginning at zero.
        """
        rt = self._active_runtime()
        if rt is None:
            return
        rt.state.infra_fail_streak += 1
        self._coordinator.save_state(rt.island_id)
        self._log_event("infra_failure", {
            "island_id": rt.island_id,
            "reason": reason,
            "streak": rt.state.infra_fail_streak,
            **payload,
        })

    def _update_island_after_attempt(self, rt: IslandRuntime, success: bool) -> None:
        """Apply this island's own stop rules after one iteration."""
        cfg = self.config.islands
        state = rt.state
        if not success:
            state.consecutive_failures += 1
        else:
            state.consecutive_failures = 0
        if state.status != IslandStatus.RUNNING:
            self._coordinator.save_states()
            return
        if rt.exhausted:
            state.status = IslandStatus.FINISHED
            state.stop_reason = "max_attempts"
        elif (
            state.valid_evaluations >= cfg.min_valid_evals_before_stall
            and state.stall_valid_evals >= cfg.stall_valid_evals
        ):
            state.status = IslandStatus.FINISHED
            state.stop_reason = "stalled"
        elif state.consecutive_failures >= self.config.budget.stall_iterations:
            state.status = IslandStatus.FINISHED
            state.stop_reason = "selection_exhausted"
        elif state.infra_fail_streak >= cfg.infra_fail_pause:
            state.status = IslandStatus.PAUSED
            state.stop_reason = "infra_failures"
        if state.status != IslandStatus.RUNNING:
            self._log_event("island_stopped", {
                "island_id": rt.island_id,
                "status": state.status,
                "stop_reason": state.stop_reason,
                "attempts": state.attempts,
                "valid_evaluations": state.valid_evaluations,
                "invalid_evaluations": state.invalid_evaluations,
                "best_score": state.best_score,
            })
        self._coordinator.save_states()

    def _activate_island_of_best(self) -> None:
        """Leave the engine on the island that owns the champion.

        Post-run reporting keeps reading ``engine.tree`` (exports, artifacts);
        pointing it at the winning island makes that read mean something instead
        of whatever the rotation cursor last happened to touch.
        """
        best_id, _ = self._best_across_islands()
        if best_id is None:
            return
        for rt in self._island_nodes():
            tree = rt.attrs.get("tree")
            if tree is not None and best_id in tree.nodes:
                self._activate_island(rt.island_id)
                return

    def _accepted_summaries(self) -> list[SummaryContext]:
        """Read this island's inbox and decide what it will actually use.

        Called at generation time rather than delivery time: being *offered*
        only makes a summary visible, and the island's own current best is what
        decides relevance. The decision (accepted / rejected, with a reason) is
        written once, so a later restart replays the same inbox state instead
        of re-deciding.
        """
        if self._exchange is None:
            self._summary_contexts = []
            return []
        rt = self._active_runtime()
        if rt is None:
            self._summary_contexts = []
            return []
        self._summary_contexts = self._exchange.accept_for(
            rt.island_id,
            runnable=rt.runnable,
            best_score=rt.state.best_score,
        )
        return self._summary_contexts

    def _local_best_score(self) -> float:
        """This island's own best, which decides whether a sibling leads."""
        rt = self._active_runtime()
        if rt is None:
            return self.tree.get_island_best()[1]
        return rt.state.best_score

    def _exchange_targets(self, rt: IslandRuntime) -> list[str]:
        """Siblings that can still act on a message.

        An island that stopped for its own reasons gets nothing: a reader that
        will never generate again cannot apply a summary.
        """
        return [
            other.island_id
            for other in self._island_nodes()
            if other.island_id != rt.island_id
            and other.state.status in (IslandStatus.PENDING, IslandStatus.RUNNING)
        ]

    def _unpublished_failures(self, rt: IslandRuntime) -> list[Node]:
        """This island's invalid candidates that no summary has covered yet.

        What has already been published is read back from the store, so a resumed
        run does not re-broadcast a lesson it taught before the interruption.
        """
        tree = rt.attrs.get("tree")
        if tree is None or self._exchange is None:
            return []
        already = self._exchange.summarized_nodes(rt.island_id, "failure")
        fresh = [
            node
            for node in tree.nodes.values()
            if node.id not in already
            and node.status == NodeStatus.INVALID
            and not node.is_repair_node()
        ]
        fresh.sort(key=lambda node: node.created_at, reverse=True)
        return fresh

    def _maybe_exchange(self, rt: IslandRuntime) -> None:
        """Publish this island's new results to its siblings, then move cursor.

        The cursor advances even when nothing was sent, otherwise an island
        with nothing new would re-check every single attempt and the run would
        pay for an empty inbox scan forever.
        """
        if self._exchange is None:
            return
        if self.config.islands.early_error_share:
            # A fresh bug is sent as soon as it appears: waiting for the cursor
            # would let a sibling spend an attempt rediscovering it.
            fresh = self._unpublished_failures(rt)
            if fresh:
                self._exchange.share_error(rt.state, fresh[0], self._exchange_targets(rt))
        if not self._exchange.due(rt.state):
            return
        tree = rt.attrs.get("tree")
        best_node: Node | None = None
        if tree is not None:
            best_id, _ = tree.get_island_best()
            if best_id:
                best_node = tree.nodes.get(best_id)
        self._exchange.checkpoint(
            rt.state,
            best_node=best_node,
            failed_nodes=self._unpublished_failures(rt),
            target_islands=self._exchange_targets(rt),
        )
        rt.state.last_exchange_attempt = rt.state.attempts
        self._coordinator.save_state(rt.island_id)

    def _finish_summary_applications(
        self, child: Node, eval_result: EvalResult
    ) -> None:
        """Attach the candidate's own real result to the summaries it used.

        A summary never transfers its score: the application row records what
        the evaluator said about the *new* program, and nothing at all when the
        candidate turned out invalid.
        """
        application_ids = self._summary_applications.pop(child.id, [])
        if not application_ids or self._exchange is None:
            return
        self._exchange.complete_applications(
            application_ids,
            evaluation_id=child.id,
            score=eval_result.combined_score if eval_result.is_valid else None,
        )

    def _island_stop_summary(self) -> dict[str, Any]:
        return {
            "islands": {
                rt.island_id: {
                    "status": rt.state.status,
                    "stop_reason": rt.state.stop_reason,
                    "attempts": rt.state.attempts,
                    "valid_evaluations": rt.state.valid_evaluations,
                    "invalid_evaluations": rt.state.invalid_evaluations,
                }
                for rt in self._island_nodes()
            },
            "iterations_done": self.metrics.iterations_done,
        }

    def _flush_deferred_all_islands(self, limit: int) -> None:
        """Drain every island's own deferred queue before the run closes."""
        for island_id in self._coordinator.order:
            self._activate_island(island_id)
            self._flush_deferred(limit)

    def _create_and_evaluate_init(self) -> None:
        """Create and evaluate the initial node of the active island."""
        rt = self._coordinator.runtime(self._active_island)
        self._create_root_for_island(rt, None, None)

    def _build_smoke_data_dir(self) -> Path | None:
        """Build and cache the smoke data directory for this run."""
        if self._smoke_data_dir is not None:
            return self._smoke_data_dir

        smoke_test_enabled = getattr(self.config, "smoke_test", None)
        if smoke_test_enabled is None:
            smoke_test_enabled = True
        else:
            smoke_test_enabled = getattr(smoke_test_enabled, "enabled", True)

        if not smoke_test_enabled:
            return None

        if not hasattr(self.task_adapter, "build_smoke_data_dir"):
            return None

        sample_fraction = 0.02
        if hasattr(self.config, "smoke_test") and self.config.smoke_test:
            sample_fraction = getattr(self.config.smoke_test, "sample_fraction", 0.02)

        try:
            self._smoke_data_dir = self.task_adapter.build_smoke_data_dir(
                self.task_spec,
                sample_fraction=sample_fraction,
            )
            if self._smoke_data_dir is not None:
                self._log_event("smoke_data_built", {
                    "path": str(self._smoke_data_dir),
                    "sample_fraction": sample_fraction,
                })
            return self._smoke_data_dir
        except Exception as e:
            self._log_event("smoke_data_build_failed", {"error": str(e)})
            return None

    def _cleanup_smoke_data_dir(self) -> None:
        """Clean up the smoke data directory."""
        if self._smoke_data_dir is not None:
            if hasattr(self.task_adapter, "cleanup_smoke_data"):
                self.task_adapter.cleanup_smoke_data(self._smoke_data_dir)
            self._smoke_data_dir = None

    def run(self, max_iterations: int | None = None) -> RunSummary:
        """Run the evolution loop.

        Args:
            max_iterations: Override max iterations

        Returns:
            Run summary
        """
        if self.tree is None or self._coordinator is None:
            raise RuntimeError("Engine not initialized")

        max_iter = max_iterations or self.config.budget.max_iterations
        target_score = self.config.stop.target_score
        start_time = time.time()
        self.metrics = RunMetrics(start_time=start_time)
        self.metrics.jev_disabled_reason = self.judge.disabled_reason if self.judge else ""
        self.metrics.jev_prior_active = bool(
            self.judge
            and self.judge.enabled
            and self.config.judge.prior
            and self.config.selection.policy == "jev_puct"
        )
        self._sync_selector_priors()

        experiment = self.store.get_experiment(self.experiment_id)
        if experiment:
            self.metrics.iterations_done = experiment.iterations_done
            self._last_discovery_iter = self.metrics.iterations_done
            if self.config.research and experiment.created_at:
                # Research wall budgets include earlier processes and paused time.
                start_time = datetime.fromisoformat(experiment.created_at).timestamp()
                self.metrics.start_time = start_time

        if self._resumed:
            # Cost is what a run has spent, not what this process has seen, so the
            # counters are rebuilt from the ledger rows before anything else in this
            # attempt can spend -- and before the first budget check of the attempt.
            self._log_event("run_resumed", {
                **self._restore_run_cost(),
                "identity": self._resume_check,
                "previous_holder": self._interrupted_claim,
            })

        self._build_smoke_data_dir()
        self._ensure_root_analysis()

        self._tstats = TournamentStats()
        self._tournament_rounds = 0
        self._mechanism_layer = (
            self.config.discovery.enabled and self.config.discovery.tournament.enabled
        )
        if self.config.discovery.enabled and self.config.discovery.tournament.enabled:
            self._tournament = Tournament(
                self.config.discovery,
                self.store,
                self.experiment_id,
                self._mechanism_llm_call,
                self._log_event,
                self._tstats,
            )
        else:
            self._tournament = None

        if self.config.discovery.enabled:
            card_path = self._discovery_card_path()
            knowledge_dir = self._get_knowledge_dir()
            self._discovery = DiscoveryRound(
                self.config.discovery,
                self.store,
                self.task_adapter,
                self.task_spec,
                self.experiment_id,
                card_path,
                knowledge_dir,
                self._discovery_llm_call,
                self._log_event,
                self._dstats,
            )

        _, initial_score = self._best_across_islands()
        if self.config.research:
            roots = [node for node in self.store.get_nodes_by_experiment(self.experiment_id)
                     if node.parent_id is None and node.evidence.evaluation is not None
                     and node.evidence.evaluation.validity == 1.]
            if roots:
                initial_score = roots[0].evidence.evaluation.combined_score
        self._initial_score = initial_score
        self.metrics.target_reached = False

        try:
            self._stalled = False
            no_progress = 0
            if self._structure_tuner is not None and self._resumed:
                self._resume_structure_tuning()
            while self.metrics.iterations_done < max_iter:
                if self._should_stop(start_time):
                    break

                rt = self._coordinator.next_runnable()
                if rt is None:
                    self._all_islands_stopped = True
                    self._log_event("all_islands_stopped", self._island_stop_summary())
                    break
                self._activate_island(rt.island_id)

                success = self._run_one_iteration()

                self._update_island_after_attempt(rt, success)
                self._maybe_exchange(rt)
                if success:
                    no_progress = 0
                    best_id, best_score = self._best_across_islands()
                    self.store.update_experiment(
                        self.experiment_id,
                        iterations_done=self.metrics.iterations_done,
                        best_node_id=best_id,
                        best_score=best_score,
                        total_tokens=self.metrics.total_tokens,
                    )

                    if self.config.research and self._check_research_goals():
                        break
                    if not self.config.research and target_score and best_score >= target_score:
                        if not self.metrics.target_reached:
                            self.metrics.mark_target_reached()
                        stop_at_target = getattr(self.config.stop, "stop_at_target", True)
                        if stop_at_target:
                            break
                    self._maybe_run_discovery(final=False)
                else:
                    no_progress += 1
                    limit = self.config.budget.stall_iterations
                    if no_progress >= limit:
                        self._stalled = True
                        self._log_event("run_stalled", {
                            "consecutive": no_progress,
                            "limit": limit,
                            "iterations_done": self.metrics.iterations_done,
                            "max_iterations": max_iter,
                        })
                        break
                self._coordinator.persist_cursor()
                self._sync_island_states()
            if not (self.config.research and getattr(self, "_research_goal_node_id", None)):
                self._flush_deferred_all_islands(self.config.judge.defer_flush_evals)
                self._maybe_run_discovery(final=True)
            self._activate_island_of_best()
        finally:
            self._cleanup_smoke_data_dir()
            # The claim is released even when the run raises: a process that dies
            # without it would leave the next launch guessing.
            self._release_run_claim()
            if hasattr(self.task_adapter, "cleanup_analysis_data"):
                self.task_adapter.cleanup_analysis_data()
            if hasattr(self.task_adapter, "cleanup_discovery_data"):
                self.task_adapter.cleanup_discovery_data()

        self.metrics.finalize()

        best_id, best_score = self._best_across_islands()

        self.store.update_experiment(
            self.experiment_id,
            status="finished",
            iterations_done=self.metrics.iterations_done,
            best_node_id=best_id,
            best_score=best_score,
            total_tokens=self.metrics.total_tokens,
        )

        self._log_event("run_finished", {
            **self.metrics.to_dict(),
            **(self._discovery_summary() if self.config.discovery.enabled else {}),
            **(self._crossover_summary()),
            # Every island's own end reason travels with the parent's, so one
            # event answers "why did each tree stop", not just "why did the run".
            **(self._island_stop_summary() if self._coordinator.multi else {}),
            # Read back out of the stored call rows rather than out of the
            # in-memory counters: the rollup is the version of the cost that
            # survives a restart, and it is where an unresolved request shows up.
            "cost": self.store.get_cost_rollup(self.experiment_id),
        })

        card_stats = self._get_card_stats_summary()

        tokens_per_gain = self.metrics.compute_tokens_per_score_gain(best_score, initial_score)

        return RunSummary(
            experiment_id=self.experiment_id,
            status="finished",
            iterations_done=self.metrics.iterations_done,
            best_score=best_score,
            best_node_id=best_id,
            initial_score=initial_score,
            improvement=best_score - initial_score,
            valid_rate=self.metrics.valid_rate,
            total_tokens=self.metrics.total_tokens,
            total_llm_latency_ms=self.metrics.total_llm_latency_ms,
            total_eval_time_s=self.metrics.total_eval_time_s,
            wall_time_s=self.metrics.total_wall_time_s,
            rounds_to_target=self.metrics.rounds_to_target,
            time_to_target_s=self.metrics.time_to_target_s,
            tokens_to_target=self.metrics.tokens_to_target,
            stop_reason=self._get_stop_reason(),
            repair_attempts=self.metrics.repair_attempts,
            repair_successes=self.metrics.repair_successes,
            repair_tokens=self.metrics.repair_tokens,
            repair_iterations=self.metrics.repair_iterations,
            knowledge_tokens=self.metrics.knowledge_tokens,
            card_adoption_rate=self.metrics.card_adoption_rate,
            card_stats=card_stats,
            generate_tokens=self.metrics.generate_tokens,
            reflect_tokens=self.metrics.reflect_tokens,
            knowledge_token_share=self.metrics.knowledge_token_share,
            cards_offered=self.metrics.cards_offered_count,
            cards_adopted=self.metrics.cards_adopted_count,
            cards_adopted_valid=self.metrics.cards_adopted_valid_count,
            tokens_per_score_gain=round(tokens_per_gain, 2),
            precheck_fixes=self.metrics.precheck_fixes,
            adapter_errors=self.metrics.adapter_errors,
            perf_rejections=self.metrics.perf_rejections,
            smoke_failures=self.metrics.smoke_failures,
            smoke_fixes=self.metrics.smoke_fixes,
            self_fix_tokens=self.metrics.self_fix_tokens,
            smoke_time_s_total=round(self.metrics.smoke_time_s_total, 3),
            smoke_tests=self.metrics.smoke_tests,
            avg_smoke_time_s=(
                round(self.metrics.avg_smoke_time_s, 3)
                if self.metrics.avg_smoke_time_s is not None
                else None
            ),
            iteration_events=self.metrics.iteration_events,
            jev_calls=self.metrics.jev_calls,
            jev_errors=self.metrics.jev_errors,
            jev_fail_open=self.metrics.jev_fail_open,
            jev_prompt_tokens=self.metrics.jev_prompt_tokens,
            jev_completion_tokens=self.metrics.jev_completion_tokens,
            jev_tokens=self.metrics.jev_tokens,
            jev_latency_ms=self.metrics.jev_latency_ms,
            jev_disabled_reason=self.metrics.jev_disabled_reason,
            candidates_screened=self.metrics.candidates_screened,
            evaluations_saved=self.metrics.evaluations_saved,
            eval_time_saved_est_s=self.metrics.eval_time_saved_est_s,
            screen_audited=self.metrics.screen_audited,
            screen_audit_bad=self.metrics.screen_audit_bad,
            screen_shadow=self.metrics.screen_shadow,
            screening_precision=self.metrics.screening_precision,
            jev_prior_active=self.metrics.jev_prior_active,
            analysis_calls=self.metrics.analysis_calls,
            analysis_failures=self.metrics.analysis_failures,
            analysis_time_s=round(self.metrics.analysis_time_s, 3),
            analysis_nonempty_rate=round(self.metrics.analysis_nonempty_rate, 3),
            tokens_per_ros_point=(
                round(self.metrics.total_tokens / (best_score - initial_score), 2)
                if best_score - initial_score > 0
                else None
            ),
            stage_cap_hits=dict(self.metrics.stage_cap_hits),
            budget_stop_reason=self._budget_stop_reason,
            elite_archive_sizes=self.selector.elite_sizes() if self.selector else {},
            expand_skipped_budget=self.metrics.expand_skipped_budget,
            value_mode="multi" if self.selector and self.selector.multi_active else "scalar",
            **self._discovery_summary(),
            **self._operator_summary(),
            **self._crossover_summary(),
        )

    def _analysis_enabled(self) -> bool:
        return bool(
            self.config.analysis.enabled
            and isinstance(self.task_adapter, ErrorProfiler)
        )

    def _node_has_analysis(self, node: Node) -> bool:
        evaluation = node.evidence.evaluation
        if evaluation is None:
            return False
        analysis = evaluation.metric.get("analysis") or {}
        return bool(analysis)

    def _should_analyze_node(
        self,
        node: Node,
        previous_best_score: float,
    ) -> tuple[bool, str]:
        if not self._analysis_enabled():
            return False, ""
        evaluation = node.evidence.evaluation
        if evaluation is None or evaluation.validity < 1.0:
            return False, ""
        if self._node_has_analysis(node):
            return False, ""

        score = evaluation.combined_score
        new_best = score > previous_best_score
        in_top_k = False
        top_k = self.config.analysis.top_k
        if top_k > 0 and self.tree is not None:
            valid_nodes = [
                n for n in self.tree.nodes.values()
                if n.evidence.evaluation and n.evidence.evaluation.validity >= 1.0
            ]
            valid_nodes.sort(
                key=lambda n: (
                    -n.evidence.evaluation.combined_score,
                    n.id,
                ),
            )
            in_top_k = node.id in {n.id for n in valid_nodes[:top_k]}

        if self.config.analysis.on_new_best and new_best:
            return True, "new_best"
        if in_top_k:
            return True, "top_k"
        return False, ""

    def _maybe_analyze_node(self, node: Node, previous_best_score: float) -> None:
        should, trigger = self._should_analyze_node(node, previous_best_score)
        if not should:
            return

        self.metrics.analysis_calls += 1
        start = time.time()
        try:
            profile = self.task_adapter.analyze(
                node.artifact.code,
                self.task_spec,
                self.config.analysis.timeout_s,
            )
            duration_s = time.time() - start
            self.metrics.analysis_time_s += duration_s
            nonempty = bool(profile)
            if nonempty:
                self.metrics.analysis_nonempty_count += 1

            evaluation = node.evidence.evaluation
            if evaluation is not None:
                metric = dict(evaluation.metric)
                metric["analysis"] = profile
                self.tree.update_node_evidence(node.id, NodeEvidence(
                    evaluation=EvaluationResult(
                        validity=evaluation.validity,
                        combined_score=evaluation.combined_score,
                        cost_time=evaluation.cost_time,
                        error_info=evaluation.error_info,
                        metric=metric,
                    ),
                    delta_score=node.evidence.delta_score,
                    noise_delta=node.evidence.noise_delta,
                ))

            self._log_event("analysis_complete", {
                "node_id": node.id,
                "trigger": trigger,
                "duration_s": round(duration_s, 3),
                "nonempty": nonempty,
            })
        except Exception as e:
            duration_s = time.time() - start
            self.metrics.analysis_time_s += duration_s
            self.metrics.analysis_failures += 1
            self._log_event("analysis_failed", {
                "node_id": node.id,
                "error_type": type(e).__name__,
                "duration_s": round(duration_s, 3),
            })

    def _ensure_root_analysis(self) -> None:
        if not self._analysis_enabled() or self.tree is None:
            return
        root = self.tree.get_root()
        if root is None or self._node_has_analysis(root):
            return
        if root.evidence.evaluation and root.evidence.evaluation.validity >= 1.0:
            self._maybe_analyze_node(root, 0.0)

    def _get_card_stats_summary(self) -> list[dict[str, Any]]:
        """Get summary of card statistics for run_summary.json."""
        stats = self.store.get_all_card_stats(self.experiment_id)
        result = []
        for card_id, stat in stats.items():
            result.append({
                "card_id": card_id,
                "n": stat.n,
                "mean_delta": round(stat.mean_delta, 4) if stat.n > 0 else 0.0,
                "refuted": stat.refuted_count,
            })
        return result

    def _check_research_goals(self) -> bool:
        """Any single evaluated candidate must meet every configured constraint."""
        if self.config.research is None:
            return False
        for node in self.store.get_nodes_by_experiment(self.experiment_id):
            evaluation = node.evidence.evaluation
            if evaluation is None:
                continue
            assessment = assess_goals(self.config.research, evaluation.model_dump())
            if assessment["achieved"]:
                if not getattr(self, "_research_goal_node_id", None):
                    self._research_goal_node_id = node.id
                    self.metrics.mark_target_reached()
                    self._log_event("research_goal_reached", {
                        "node_id": node.id, "iterations_done": self.metrics.iterations_done,
                        "assessment": assessment,
                    })
                return True
        return False

    def _should_stop(self, start_time: float) -> bool:
        """Check if evolution should stop."""
        if self._check_research_goals():
            return True
        if self._ledger_stop:
            return True
        if self._structure_tuner is not None and ledger_would_block_full_eval(self):
            self._ledger_stop = True
            return True
        wall_hours = (time.time() - start_time) / 3600
        if wall_cap_exceeded(wall_hours, self.config.budget.max_wall_hours):
            return True

        if token_cap_exceeded(self.metrics.total_tokens, self.config.budget.max_tokens):
            return True

        if self.selector:
            reason = self.budget.check_stop(
                iterations_done=self.metrics.iterations_done,
                total_tokens=self.metrics.total_tokens,
                best_score=self._best_across_islands()[1],
                initial_score=self._initial_score,
                noise_delta=self.selector.noise_delta,
            )
            if reason:
                self._budget_stop_reason = reason
                self._log_event("budget_stop", {"reason": reason})
                return True

        return False

    def _get_stop_reason(self) -> str:
        """Get the reason for stopping."""
        if self.config.research and getattr(self, "_research_goal_node_id", None):
            return "research_goal_reached"
        stop_at_target = getattr(self.config.stop, "stop_at_target", True)
        if self.metrics.target_reached and stop_at_target:
            return "target_score_reached"
        if self._init_eval_error:
            return "init_evaluation_invalid"
        if getattr(self, "_stalled", False):
            return "selection_stalled"
        if self._ledger_stop:
            return "ledger_full_eval_cap"
        if self._budget_stop_reason:
            return self._budget_stop_reason
        # Checked after the budget reasons: an island that runs out of attempts
        # while the global budget still has room is the run's own stopping
        # cause, but a run cut off by cost stops for the cost, not the islands.
        if self._all_islands_stopped:
            return "all_islands_stopped"
        if self.metrics.iterations_done >= self.config.budget.max_iterations:
            return "max_iterations"
        if token_cap_exceeded(self.metrics.total_tokens, self.config.budget.max_tokens):
            return "token_budget"
        if wall_cap_exceeded(self.metrics.total_wall_time_s / 3600, self.config.budget.max_wall_hours):
            return "wall_time"
        return "unknown"

    def _observe_node(self, node: Node) -> None:
        if self.selector is None:
            return
        evaluation = node.evidence.evaluation
        if evaluation is None or evaluation.validity < 1.0:
            return
        if node.status in (NodeStatus.INVALID, NodeStatus.ABANDONED):
            return
        self.selector.observe_node(node)

    def _stage_used_tokens(self, stage: str) -> int:
        if stage == "reflect":
            return self.metrics.reflect_tokens
        if stage == "repair":
            return self.metrics.repair_tokens
        if stage == "knowledge":
            return self.metrics.knowledge_tokens
        if stage == "jev":
            return self.metrics.jev_tokens
        if stage == "mechanism":
            return self.metrics.mechanism_tokens
        if stage == "crossover":
            return self.metrics.crossover_tokens
        return 0

    def _stage_capped(self, stage: str) -> bool:
        used = self._stage_used_tokens(stage)
        if not self.budget.stage_exceeded(stage, used):
            return False
        self.metrics.stage_cap_hits[stage] = (
            self.metrics.stage_cap_hits.get(stage, 0) + 1
        )
        if self.budget.note_cap_hit(stage):
            cap = self.budget.stage_cap_tokens(stage)
            self._log_event("budget_stage_cap_hit", {
                "stage": stage,
                "used": used,
                "cap": cap,
            })
        return True

    def _available_operators(self, parent: Node) -> list[OperatorType]:
        available: list[OperatorType] = []
        for name in self.config.operators.enabled:
            op = _ENABLED_OPERATOR_MAP.get(name)
            if op is None:
                continue
            if op == OperatorType.REFINE or op == OperatorType.THRESHOLD_CALIBRATE:
                available.append(op)
                continue
            if op == OperatorType.RECALL_FOCUS:
                analysis: dict[str, Any] = {}
                if parent.evidence.evaluation:
                    analysis = parent.evidence.evaluation.metric.get("analysis") or {}
                if analysis.get("fn_groups"):
                    available.append(op)
                continue
            if op == OperatorType.INJECT:
                if not self._is_knowledge_enabled():
                    continue
                knowledge_dir = self._get_knowledge_dir()
                if knowledge_dir is None or not knowledge_dir.exists():
                    continue
                if self.budget.stage_exceeded(
                    "knowledge",
                    self.metrics.knowledge_tokens,
                ):
                    continue
                available.append(op)
        cx = self.config.operators.crossover
        if cx.enabled:
            if valid_node_count(self.tree.nodes) >= cx.min_valid_nodes:
                if not self.budget.stage_exceeded(
                    "crossover",
                    self.metrics.crossover_tokens,
                ):
                    if select_crossover_partner(
                        parent,
                        self.tree.nodes,
                        top_quantile=cx.top_quantile,
                    ) is not None:
                        available.append(OperatorType.CROSSOVER)
        if self._summary_cross_candidates():
            available.append(OperatorType.SUMMARY_CROSS)
        return available

    def _summary_cross_candidates(self) -> list[SummaryContext]:
        """Accepted sibling conclusions this island could graft.

        Availability comes from the inbox, not from this tree: a summary carries
        method text only, so there is no second parent to find here.
        """
        if self._exchange is None:
            return []
        return [c for c in self._summary_contexts if c.kind == "best"]

    def _apply_island_bias(self, avail: list[OperatorType]) -> list[OperatorType]:
        """Keep an island mostly on its profile operators, with seeded escape.

        ``exploration_ratio`` of the choices see the full set, so an island can
        still learn that an off-profile operator pays off. The draw comes from
        that island's own RNG, which makes the sequence reproducible per seed
        and independent between islands -- a fixed every-fifth-round schedule
        would look random and not be.
        """
        rt = self._active_runtime()
        if rt is None or self._coordinator is None or not self._coordinator.multi:
            return avail
        bias = set(rt.spec.operator_bias)
        if not bias or len(avail) <= 1:
            return avail
        preferred = [op for op in avail if op.value in bias]
        off_bias = [op for op in avail if op.value not in bias]
        if not preferred or not off_bias:
            return avail
        explore = self._op_rng.random() < rt.spec.exploration_ratio
        narrow = preferred
        if OperatorType.SUMMARY_CROSS in avail and OperatorType.SUMMARY_CROSS not in narrow:
            # A sibling publishing something is not this island expressing a
            # strategy preference: dropping it here would silently discard the
            # exchange on exactly the rounds the bias filter runs.
            narrow = [*preferred, OperatorType.SUMMARY_CROSS]
        self._log_event("operator_bias_applied", {
            "island_id": rt.island_id,
            "profile": rt.profile,
            "preferred": [op.value for op in preferred],
            "off_bias": [op.value for op in off_bias],
            "exchange_kept": OperatorType.SUMMARY_CROSS in narrow,
            "exploration_ratio": rt.spec.exploration_ratio,
            "exploration_draw": explore,
        })
        return avail if explore else narrow

    def _choose_operator(self, parent: Node) -> OperatorType:
        if self.config.autotune.quota.enabled:
            slot = next_operator(self._quota_counts, self.config.autotune.quota.shares)
            self._quota_counts[slot] = self._quota_counts.get(slot, 0) + 1
            if slot == "patch" and self.config.autotune.patch.enabled:
                if parent_has_patch_blocks(parent):
                    return OperatorType.PATCH
                self._log_event("patch_unavailable", {"parent_id": parent.id})
                if self.config.autotune.patch.fallback == "draft":
                    self._log_event("patch_fallback_draft", {"parent_id": parent.id})
                return OperatorType.REFINE
            if slot == "hpo":
                self._log_event("quota_slot", {"slot": "hpo", "parent_id": parent.id})
                if self.config.autotune.hpo.enabled:
                    return OperatorType.HPO
            else:
                self._log_event("quota_slot", {"slot": slot, "parent_id": parent.id})
            return OperatorType.REFINE
        if not self.config.operators.bandit:
            # Without a bandit an offered conclusion would be read and then
            # ignored, so take the graft while a sibling is genuinely ahead of
            # this island. A paying graft raises the local best and the lead --
            # and with it this shortcut -- disappears on its own.
            ahead = [
                c
                for c in self._summary_cross_candidates()
                if isinstance(c.metrics.get("combined_score"), (int, float))
                and float(c.metrics["combined_score"]) > self._local_best_score()
            ]
            if ahead:
                self._log_event("summary_cross_selected", {
                    "island_id": self._active_island or "",
                    "parent_id": parent.id,
                    "summary_id": ahead[0].summary_id,
                    "source_island_id": ahead[0].source_island_id,
                    "reason": "sibling_ahead",
                })
                return OperatorType.SUMMARY_CROSS
            return OperatorType.REFINE

        avail = self._available_operators(parent)
        pool = self._apply_island_bias(avail)
        cfg = self.config.operators
        rows = self.store.get_operator_stats(
            self.experiment_id, island_id=self._active_island or ""
        )
        stats: dict[OperatorType, tuple[float, float]] = {}
        for op in pool:
            row = rows.get(op.value, {})
            stats[op] = (
                float(row.get("alpha", cfg.prior_alpha)),
                float(row.get("beta", cfg.prior_beta)),
            )
        chosen = select_operator(
            parent,
            pool,
            stats=stats,
            rng=self._op_rng,
            min_explore=cfg.min_explore,
            bandit=True,
        )
        self._log_event(
            "operator_selected",
            {
                "island_id": self._active_island or "",
                "parent_id": parent.id,
                "operator": chosen.value,
                "available": [op.value for op in avail],
                "profile_pool": [op.value for op in pool],
            },
        )
        return chosen

    def _record_operator_outcome(
        self,
        operator: OperatorType,
        *,
        valid: bool,
        delta: float,
        noise_delta: float,
    ) -> None:
        if operator not in GENERATIVE_OPERATORS:
            return
        cfg = self.config.operators
        success = delta > noise_delta if valid else False
        self.store.record_operator_outcome(
            self.experiment_id,
            operator.value,
            self._active_island or "",
            valid=valid,
            success=success,
            delta=delta,
            prior_alpha=cfg.prior_alpha,
            prior_beta=cfg.prior_beta,
        )

    def _operator_summary(self) -> dict[str, Any]:
        rows = self.store.get_operator_stats(self.experiment_id)
        operator_counts: dict[str, int] = {}
        operator_valid_rate: dict[str, float] = {}
        operator_mean_delta: dict[str, float] = {}
        total_n = 0
        total_valid = 0
        for op, row in rows.items():
            n = int(row.get("n", 0))
            n_valid = int(row.get("n_valid", 0))
            operator_counts[op] = n
            operator_valid_rate[op] = (n_valid / n) if n else 0.0
            operator_mean_delta[op] = (
                float(row.get("sum_delta", 0.0)) / n_valid if n_valid else 0.0
            )
            total_n += n
            total_valid += n_valid
        generative_valid_rate = (total_valid / total_n) if total_n else None
        return {
            "operator_counts": operator_counts,
            "operator_valid_rate": operator_valid_rate,
            "operator_mean_delta": operator_mean_delta,
            "operator_posteriors": operator_posterior_summary(rows),
            "generative_valid_rate": generative_valid_rate,
            "operator_tokens": dict(self._op_tokens),
            "bandit_active": self.config.operators.bandit,
        }

    def _crossover_summary(self) -> dict[str, Any]:
        tokens = self.metrics.crossover_tokens
        if not self.config.operators.crossover.enabled:
            return {
                "crossover_count": 0,
                "crossover_valid_rate": None,
                "crossover_mean_delta": None,
                "crossover_best_gain": None,
                "crossover_tokens": tokens,
            }
        nodes = self.store.get_nodes_by_experiment(self.experiment_id)
        crossover_nodes = [n for n in nodes if n.operator == OperatorType.CROSSOVER]
        count = len(crossover_nodes)
        if count == 0:
            return {
                "crossover_count": 0,
                "crossover_valid_rate": None,
                "crossover_mean_delta": None,
                "crossover_best_gain": None,
                "crossover_tokens": tokens,
            }
        valid_gains: list[float] = []
        valid_n = 0
        for node in crossover_nodes:
            ev = node.evidence.evaluation
            is_valid = node.is_expandable() or bool(ev and ev.validity >= 1.0)
            if is_valid:
                valid_n += 1
            parents = self.store.get_node_parents(node.id)
            if not parents:
                continue
            parent_scores: list[float] = []
            for pid, _role in parents:
                pnode = self.tree.get_node(pid) if self.tree else None
                if pnode is None:
                    for candidate in nodes:
                        if candidate.id == pid:
                            pnode = candidate
                            break
                if pnode is not None:
                    parent_scores.append(pnode.get_score())
            if not parent_scores or ev is None:
                continue
            gain = ev.combined_score - max(parent_scores)
            if is_valid:
                valid_gains.append(gain)
        return {
            "crossover_count": count,
            "crossover_valid_rate": (valid_n / count) if count else None,
            "crossover_mean_delta": (
                sum(valid_gains) / len(valid_gains) if valid_gains else None
            ),
            "crossover_best_gain": max(valid_gains) if valid_gains else None,
            "crossover_tokens": tokens,
        }

    def _top_nodes(self, k: int) -> list[Node]:
        if self.tree is None:
            return []
        valid = [
            n for n in self.tree.nodes.values()
            if n.is_expandable()
        ]
        valid.sort(key=lambda n: (-n.get_score(), n.id))
        return valid[:k]

    def _traceback_snippet(self, error_info: str, max_chars: int = 800) -> str:
        """Sanitize and keep the tail of traceback-like error text."""
        if not error_info:
            return error_info
        return sanitize_error_info(error_info, max_chars=max_chars, keep_tail=True)

    def _log_iteration_complete(self, outcome: str, parent_id: str, **payload: Any) -> None:
        """Emit iteration_complete once per iteration counted in iterations_done."""
        self._log_event(
            "iteration_complete",
            {
                "outcome": outcome,
                "parent_id": parent_id,
                # Which tree this iteration belonged to; "" is the real island id
                # of a legacy single-tree run.
                "island_id": self._active_island or "",
                **payload,
            },
        )
        self.metrics.iteration_events += 1

    def _log_node_created(self, node: Node) -> None:
        """Emit ``node_created`` for a node that has just entered the tree.

        PRD §16.2 asks for a node-creation event of its own. Until now the only
        thing that announced a new node was ``iteration_complete`` -- which is
        one event per *iteration*, not per node, and does not fire at all for the
        initial node or for a repair node produced outside the iteration loop.
        A front end that draws the tree from the event stream therefore could not
        show a node until the iteration that made it ended, and could not show the
        root or a repair node at all. Rather than have the UI "assume one
        iteration yields one node" (an assumption that is false in three of those
        cases), the engine says it outright.

        Emitted from ``Tree.add_node`` so the count is exact: one event per node,
        ever -- not one per call site that happens to remember.

        The payload is what a drawer needs to render the node before it has any
        evidence: identity, placement, and how it was born. Score is
        deliberately ``null`` rather than ``0.0``: at birth the node has not been
        evaluated, and a zero would read as "scored zero" in the timeline.
        """
        self._log_event(
            "node_created",
            {
                "node_id": node.id,
                "island_id": node.island_id,
                "parent_id": node.parent_id,
                "depth": node.depth,
                "branch_id": node.branch_id,
                "operator": node.operator.value,
                "status": node.status.value,
                "is_root": node.parent_id is None,
                "is_repair": node.is_repair_node(),
                "card_ids": list(node.card_ids),
                "score": None,
            },
        )

    def _get_knowledge_dir(self) -> Path | None:
        """Get knowledge directory from config or adapter."""
        if self.task_dir is None:
            return None

        knowledge_config = getattr(self.config, "knowledge", None)
        if knowledge_config and hasattr(knowledge_config, "dir"):
            knowledge_dir_name = knowledge_config.dir
            if knowledge_dir_name:
                return self.task_dir / knowledge_dir_name

        return None

    def _estimate_knowledge_tokens(self, cards: list[dict[str, Any]]) -> int:
        """Estimate tokens used by knowledge cards from actual card text.

        Uses a simple chars/4 heuristic as a rough token estimate.

        Args:
            cards: List of card dictionaries

        Returns:
            Estimated token count for the knowledge block
        """
        if not cards:
            return 0

        block_text = "<knowledge_cards>\n"
        for card in cards:
            card_text = f"- **{card.get('id', '')}**: {card.get('title', '')}\n"
            card_text += f"  - 核心思想：{card.get('claim', card.get('idea', ''))}\n"
            card_text += f"  - 落地提示：{card.get('impl_hint', '')}\n"
            card_text += f"  - 风险：{card.get('risk', '')}\n"
            block_text += card_text
        block_text += "</knowledge_cards>\n"

        return len(block_text) // 4

    def _is_knowledge_enabled(self) -> bool:
        """Check if knowledge injection is enabled."""
        knowledge_config = getattr(self.config, "knowledge", None)
        if knowledge_config is None:
            return True
        return getattr(knowledge_config, "enabled", True)

    def _active_island_spec(self) -> IslandSpec | None:
        """The spec of the island currently taking the attempt, if any."""
        if self._coordinator is None or self._active_island is None:
            return None
        return self._coordinator.runtime(self._active_island).spec

    def _retrieve_knowledge_cards(
        self,
        parent: Node,
        *,
        profile_keywords: list[str] | None = None,
    ) -> KnowledgeSelection:
        """Retrieve knowledge cards for the current context.

        The island asking gets its profile into the search: three trees reading
        one library for one keyword list would all be handed the same four cards,
        which is the opposite of why the islands exist.

        Args:
            parent: Parent node to refine

        Returns:
            :class:`KnowledgeSelection` -- the cards to inject plus why the answer
            is empty when it is
        """
        spec = self._active_island_spec()
        selection = KnowledgeSelection(
            island_id=spec.island_id if spec else (self._active_island or ""),
            profile=spec.profile if spec else "",
            island_keywords=list(spec.knowledge_keywords) if spec else [],
        )

        if not self._is_knowledge_enabled():
            selection.reason = "knowledge_disabled"
            return selection

        if self._stage_capped("knowledge"):
            selection.reason = "stage_capped"
            return selection

        knowledge_dir = self._get_knowledge_dir()
        if knowledge_dir is None or not knowledge_dir.exists():
            selection.reason = "no_knowledge_source"
            return selection

        knowledge_config = getattr(self.config, "knowledge", None)
        k = 4
        max_per_category = 2
        if knowledge_config:
            k = getattr(knowledge_config, "k", 4)
            max_per_category = getattr(knowledge_config, "max_per_category", 2)

        context_keywords = self.task_adapter.context_keywords(parent.artifact.code)

        last_reflection = ""
        if parent.branch_memory.summary:
            last_reflection = parent.branch_memory.summary

        error_class = ""
        if parent.evidence.evaluation and parent.evidence.evaluation.error_info:
            error_class = classify_error(parent.evidence.evaluation.error_info)

        context = {
            "knowledge_dir": knowledge_dir,
            "store": self.store,
            "experiment_id": self.experiment_id,
            "node": parent,
            "keywords": context_keywords,
            "last_reflection": last_reflection,
            "error_class": error_class,
            "k": k,
            "max_per_category": max_per_category,
        }
        if profile_keywords:
            context["profile_keywords"] = profile_keywords
        if selection.island_keywords:
            context["island_keywords"] = selection.island_keywords
        context["extra_card_paths"] = self._extra_card_paths()

        try:
            cards = get_era_knowledge_cards(parent, context)
        except Exception as exc:
            # A knowledge service that is down is recorded as down. It must never
            # turn into a confirmed finding, and it must not stop the run either:
            # the generation goes ahead with no cards, which the caller logs.
            selection.reason = "retrieval_failed"
            selection.error_type = type(exc).__name__
            return selection

        selection.cards = cards
        if not cards:
            # The retriever cannot tell an empty library from a library whose
            # every card is already refuted or adopted on this branch; both mean
            # "nothing applicable for this node" here, and that is what is saved.
            selection.reason = "no_applicable_card"
        return selection

    def _attempt_perf_self_fix(
        self,
        code: str,
        issues: list[str],
        parent: Node,
    ) -> tuple[str | None, bool]:
        """Attempt to fix performance issues via LLM.

        Args:
            code: Code with performance issues
            issues: List of performance issue descriptions
            parent: Parent node for context

        Returns:
            Tuple of (fixed_code or None, was_fixed)
        """
        issues_text = "\n".join(f"- {issue}" for issue in issues)
        fix_prompt = f"""以下代码存在性能问题，会导致超时：

{issues_text}

请修复这些性能问题，使用向量化操作代替循环。

```python
{code[:6000]}
```

输出格式：
<intent>修复性能问题的方法</intent>
```python
完整修复后的代码
```"""

        messages = [
            {"role": "system", "content": self.task_spec.prompt_md},
            {"role": "user", "content": fix_prompt},
        ]

        try:
            response, metrics = self.llm.chat(messages)
            self._meter_llm_call(metrics, "self_fix", node_id=parent.id)

            from faultevolve.common.codecheck import extract_code_from_response
            fixed_code = extract_code_from_response(response)

            if fixed_code:
                return fixed_code, True
        except LLMTransientError as exc:
            self._record_lost_llm_call(exc, "self_fix", node_id=parent.id)

        return None, False

    def _attempt_smoke_self_fix(
        self,
        code: str,
        error_info: str,
        parent: Node,
    ) -> tuple[str | None, bool]:
        """Attempt to fix smoke test failure via LLM.

        Args:
            code: Code that failed smoke test
            error_info: Error traceback
            parent: Parent node for context

        Returns:
            Tuple of (fixed_code or None, was_fixed)
        """
        error_tail = error_info[-1500:] if len(error_info) > 1500 else error_info
        error_hint = get_error_fix_hint(error_info)

        fix_prompt = f"""代码在烟雾测试中失败，错误信息：

```
{error_tail}
```

{f'已知修复方法：{error_hint}' if error_hint else ''}

请修复错误，只做最小必要的修改。

```python
{code[:6000]}
```

输出格式：
<intent>修复错误的方法</intent>
```python
完整修复后的代码
```"""

        messages = [
            {"role": "system", "content": self.task_spec.prompt_md},
            {"role": "user", "content": fix_prompt},
        ]

        try:
            response, metrics = self.llm.chat(messages)
            self._meter_llm_call(metrics, "self_fix", node_id=parent.id)

            from faultevolve.common.codecheck import extract_code_from_response
            fixed_code = extract_code_from_response(response)

            if fixed_code:
                return fixed_code, True
        except LLMTransientError as exc:
            self._record_lost_llm_call(exc, "self_fix", node_id=parent.id)

        return None, False

    def _run_smoke_test(self, code: str, parent: Node) -> tuple[EvalResult | None, float]:
        """Run smoke test if enabled.

        Args:
            code: Candidate code to test
            parent: Parent node for context

        Returns:
            Tuple of (EvalResult if smoke test ran else None, duration in seconds)
        """
        smoke_test_enabled = getattr(self.config, "smoke_test", None)
        if smoke_test_enabled is None:
            smoke_test_enabled = True
        else:
            smoke_test_enabled = getattr(smoke_test_enabled, "enabled", True)

        if not smoke_test_enabled:
            return None, 0.0

        if not hasattr(self.task_adapter, "smoke_test"):
            return None, 0.0

        smoke_timeout = 60
        sample_fraction = 0.02
        if hasattr(self.config, "smoke_test") and self.config.smoke_test:
            smoke_timeout = getattr(self.config.smoke_test, "timeout_s", 60)
            sample_fraction = getattr(self.config.smoke_test, "sample_fraction", 0.02)

        start = time.time()
        result = self.task_adapter.smoke_test(
            code,
            self.task_spec,
            timeout=smoke_timeout,
            sample_fraction=sample_fraction,
            smoke_data_dir=self._smoke_data_dir,
        )
        duration_s = time.time() - start
        self.metrics.add_smoke_duration(duration_s)
        ledger_record(
            self,
            stage="smoke",
            fidelity="smoke",
            node_id=parent.id,
            wall_s=duration_s,
            status="ok" if result is None or result.is_valid else "failed",
        )
        return result, duration_s

    def _run_one_iteration(self) -> bool:
        t0 = self.metrics.total_tokens
        e0 = self.metrics.total_eval_time_s
        ok = self._run_one_iteration_inner()
        self.budget.record_iteration(
            self.metrics.total_tokens - t0,
            self.metrics.total_eval_time_s - e0,
        )
        if self.tree:
            self.budget.record_best(self._best_across_islands()[1])
        return ok

    def _run_one_iteration_inner(self) -> bool:
        """Run one iteration of evolution.

        Handles transient LLM errors by logging an event and skipping the
        iteration instead of crashing the entire run.

        Returns:
            True if iteration completed successfully
        """
        result = self.selector.select(self.tree)

        if not result.should_expand:
            self._log_event("selection_failed", {"node_id": result.node.id})
            return False

        parent = result.node
        top = self._top_nodes(3)
        top_ids = {n.id for n in top}
        if (
            top
            and not self.budget.should_expand(
                self.metrics.total_tokens,
                parent.id in top_ids,
            )
        ):
            parent = top[0]
            self.metrics.expand_skipped_budget += 1
            self._log_event("expand_redirected_budget", {"to": parent.id})

        self.tree.increment_expand_count(parent.id)

        # The inbox is read before operator selection: summary crossover is only
        # a candidate strategy while a sibling conclusion is actually usable.
        self._accepted_summaries()
        operator = self._choose_operator(parent)
        self._count_attempt(parent, operator)
        if operator == OperatorType.HPO:
            return run_hpo_quota_iteration(self, parent)
        partner: Node | None = None
        cx_cfg = self.config.operators.crossover
        if operator == OperatorType.CROSSOVER:
            partner = select_crossover_partner(
                parent,
                self.tree.nodes,
                top_quantile=cx_cfg.top_quantile,
            )
            if partner is None:
                operator = OperatorType.REFINE
                self._log_event(
                    "operator_fallback",
                    {
                        "parent_id": parent.id,
                        "requested": "crossover",
                        "used": "refine",
                        "reason": "no_partner",
                    },
                )

        ctx = OperatorContext(parent, self.task_spec, operator)
        is_crossover = operator == OperatorType.CROSSOVER and partner is not None
        if is_crossover:
            ctx.set_partner(
                partner,
                cx_cfg.runtime_budget_s,
                cx_cfg.max_code_chars,
            )

        # Delivery only made a summary visible; here it enters a prompt, and as
        # method text only -- the DTO has no code field to copy. A graft is
        # chosen from the sibling's positive conclusion, but the avoidance
        # lessons belong in the same prompt: grafting a method while repeating a
        # bug the sibling already hit would waste the exchange.
        is_summary_cross = operator == OperatorType.SUMMARY_CROSS
        if is_summary_cross and not self._summary_cross_candidates():
            operator = OperatorType.REFINE
            ctx.operator = OperatorType.REFINE
            is_summary_cross = False
            self._log_event("operator_fallback", {
                "parent_id": parent.id,
                "requested": "summary_cross",
                "used": "refine",
                "reason": "no_applicable_summary",
            })
        rendered = self._summary_contexts
        if rendered:
            ctx.set_exchange_summaries([c.as_dict() for c in rendered])

        discover_every = self.config.discovery.discover_op_every
        discover_flag = (
            self.config.discovery.enabled
            and discover_every > 0
            and operator == OperatorType.REFINE
            and (self.metrics.iterations_done + 1) % discover_every == 0
        )
        ctx.set_discover_claim(discover_flag)
        ctx.set_objective_brief(self._objective_brief)
        if self._coordinator is not None and self._coordinator.multi:
            ctx.set_island_focus(self._island_focus)

        analysis_for_profile: dict[str, Any] = {}
        if parent.evidence.evaluation:
            analysis_for_profile = parent.evidence.evaluation.metric.get("analysis") or {}
            ctx.set_error_profile(analysis_for_profile)

        ctx.set_branch_memory(parent.branch_memory.summary)
        ctx.set_refuted_hypotheses(parent.branch_memory.refuted_hypotheses)

        positive: list[dict[str, Any]] = []
        negative: list[dict[str, Any]] = []
        knowledge_cards: list[dict[str, Any]] = []
        knowledge_selection: KnowledgeSelection | None = None
        if is_crossover:
            ctx.set_foreign_insights([], [])
        else:
            positive, negative = get_foreign_insights(
                parent, self.store, self.experiment_id,
                self.config.insights.top_k_foreign,
                self.config.insights.top_k_negative,
                use_reputation=self.config.insights.reputation_enabled,
            )
            ctx.set_foreign_insights(positive, negative)
            if self.config.discovery.tournament.enabled:
                ctx.set_mechanism_context(self._mechanism_context_items())

            profile_keywords = None
            if self.config.operators.fn_keywords:
                profile_keywords = fn_profile_keywords(
                    analysis_for_profile,
                    self.config.operators.fn_keyword_groups,
                )

            knowledge_selection = self._retrieve_knowledge_cards(
                parent,
                profile_keywords=profile_keywords,
            )
            knowledge_cards = knowledge_selection.cards
        if operator == OperatorType.INJECT:
            knowledge_cards = knowledge_cards[:1]
            if knowledge_selection is not None:
                # The record has to name what was injected, not what was offered.
                knowledge_selection.cards = knowledge_cards
            if not knowledge_cards:
                operator = OperatorType.REFINE
                ctx.operator = OperatorType.REFINE
                self._log_event(
                    "operator_fallback",
                    {
                        "parent_id": parent.id,
                        "requested": "inject",
                        "used": "refine",
                        "reason": "no_card",
                    },
                )

        knowledge_estimate = self._estimate_knowledge_tokens(knowledge_cards)
        if knowledge_selection is not None:
            # Recorded even when empty: a report has to be able to tell "this
            # island's keywords matched nothing" from "knowledge was switched off"
            # from "the knowledge service raised", and only the reason says which.
            self._log_event(
                "knowledge_injected",
                knowledge_selection.event_payload(
                    parent_id=parent.id,
                    operator=operator.value,
                    estimated_tokens=knowledge_estimate,
                ),
            )

        offered_card_ids = [c.get("id", "") for c in knowledge_cards] if knowledge_cards else []
        self.metrics.discovered_cards_offered += sum(
            1 for cid in offered_card_ids if cid.startswith("D-")
        )

        if knowledge_cards:
            ctx.set_knowledge_cards(knowledge_cards)
            self.metrics.add_card_adoption(len(knowledge_cards), 0)

        if self._constraints_text:
            ctx.set_constraints(self._constraints_text)

        if self.config.autotune.feedback.enabled:
            from faultevolve.optimization.feedback import build_feedback, render_feedback

            bundle = build_feedback(
                parent,
                parent,
                dev_preds=None,
                config=self.config.autotune.feedback,
            )
            ctx.set_feedback_text(
                render_feedback(bundle, max_chars=self.config.autotune.feedback.max_chars)
            )

        # Named before the try so a request that dies partway through can still be
        # written down with the stage it belonged to.
        llm_purpose = "generate"
        record_purpose = "summary_cross" if is_summary_cross else "refine"
        try:
            if operator == OperatorType.PATCH and self.patch_operator is not None:
                gen_result = self.patch_operator.generate_with_adoption(
                    ctx,
                    static_check=lambda c: self.task_adapter.static_check(c, self.task_spec),
                    patch_cfg=self.config.autotune.patch,
                    on_reject=lambda payload: self._log_event("patch_rejected", payload),
                    on_applied=lambda payload: self._log_event("patch_applied", payload),
                    on_proposed=lambda payload: self._log_event("patch_proposed", payload),
                )
                llm_purpose = "generate"
                record_purpose = "patch"
                if gen_result.code is None:
                    invalid_child = self._handle_invalid_generation(
                        parent,
                        gen_result.intent or "patch_rejected",
                        gen_result.intent,
                        operator=OperatorType.PATCH,
                    )
                    self.metrics.add_eval(0, False)
                    self._log_iteration_complete(
                        "patch_rejected",
                        parent_id=parent.id,
                        node_id=invalid_child.id,
                    )
                    return True
            elif is_crossover:
                gen_result = self.crossover_operator.generate(parent, partner, ctx)
                llm_purpose = "crossover"
                record_purpose = "crossover"
            else:
                gen_result = self.operator.generate_with_adoption(ctx)
                llm_purpose = "generate"
                record_purpose = "summary_cross" if is_summary_cross else "refine"
        except LLMTransientError as e:
            self._log_event("llm_error", {
                "parent_id": parent.id,
                "error": str(e),
                "iteration": self.metrics.iterations_done,
            })
            self._record_lost_llm_call(e, llm_purpose, node_id=parent.id)
            return True

        code = gen_result.code
        intent = gen_result.intent
        hypothesis = gen_result.hypothesis
        adopted_cards = gen_result.adopted_cards
        gen_metrics = gen_result.metrics

        self._meter_llm_call(
            gen_metrics, llm_purpose, node_id=parent.id, db_purpose=record_purpose,
        )
        self._op_tokens[operator.value] = (
            self._op_tokens.get(operator.value, 0)
            + gen_metrics.prompt_tokens
            + gen_metrics.completion_tokens
        )

        if knowledge_cards and not is_crossover:
            self.metrics.add_knowledge_tokens(knowledge_estimate)

        if code is None:
            invalid_child = self._handle_invalid_generation(
                parent, "generation_failed", intent, operator=operator,
            )
            self.metrics.add_eval(0, False)
            self._log_iteration_complete(
                "invalid", parent_id=parent.id, node_id=invalid_child.id,
            )
            return True

        precheck_result = precheck_and_fix(code)
        if precheck_result.was_fixed:
            code = precheck_result.fixed_code
            self.metrics.precheck_fixes += len(precheck_result.fixes_applied)
            self._log_event("precheck_fix", {
                "parent_id": parent.id,
                "fixes": precheck_result.fixes_applied,
            })

        if precheck_result.has_unfixable:
            fixed_code, was_fixed = self._attempt_perf_self_fix(
                code, precheck_result.unfixable_issues, parent
            )
            if was_fixed and fixed_code:
                recheck = precheck_and_fix(fixed_code)
                if not recheck.has_unfixable:
                    code = recheck.fixed_code if recheck.was_fixed else fixed_code
                    self._log_event("perf_self_fix_success", {
                        "parent_id": parent.id,
                        "issues_fixed": precheck_result.unfixable_issues,
                    })
                else:
                    invalid_child = self._handle_invalid_generation(
                        parent, f"perf_rejected: {precheck_result.unfixable_issues[0][:100]}",
                        intent, code, hypothesis, operator=operator,
                    )
                    self.metrics.add_eval(0, False)
                    self.metrics.perf_rejections += 1
                    self._log_event("perf_rejected", {
                        "parent_id": parent.id,
                        "issues": precheck_result.unfixable_issues,
                    })
                    self._log_iteration_complete(
                        "perf_rejected", parent_id=parent.id, node_id=invalid_child.id,
                    )
                    return True
            else:
                invalid_child = self._handle_invalid_generation(
                    parent, f"perf_rejected: {precheck_result.unfixable_issues[0][:100]}",
                    intent, code, hypothesis, operator=operator,
                )
                self.metrics.add_eval(0, False)
                self.metrics.perf_rejections += 1
                self._log_event("perf_rejected", {
                    "parent_id": parent.id,
                    "issues": precheck_result.unfixable_issues,
                })
                self._log_iteration_complete(
                    "perf_rejected", parent_id=parent.id, node_id=invalid_child.id,
                )
                return True

        static_error = self.task_adapter.static_check(code, self.task_spec)
        if static_error:
            invalid_child = self._handle_invalid_generation(
                parent, static_error, intent, code, hypothesis, operator=operator,
            )
            self.metrics.add_eval(0, False)
            self._log_iteration_complete(
                "invalid", parent_id=parent.id, node_id=invalid_child.id,
            )
            return True

        smoke_result, smoke_duration_s = self._run_smoke_test(code, parent)
        if smoke_result is not None:
            if smoke_result.is_valid:
                self._log_event("smoke_passed", {
                    "parent_id": parent.id,
                    "duration_s": round(smoke_duration_s, 3),
                })
            elif not smoke_result.is_valid:
                is_timeout = "timeout" in smoke_result.error_info.lower()
                err_snippet = self._traceback_snippet(smoke_result.error_info)
                if is_timeout:
                    self.metrics.perf_rejections += 1
                    invalid_child = self._handle_invalid_generation(
                        parent, f"perf_rejected: smoke timeout",
                        intent, code, hypothesis, operator=operator,
                    )
                    self.metrics.add_eval(0, False)
                    self._log_event("perf_rejected", {
                        "parent_id": parent.id,
                        "issues": ["smoke_timeout"],
                    })
                    self._log_iteration_complete(
                        "perf_rejected", parent_id=parent.id, node_id=invalid_child.id,
                    )
                    return True

                self.metrics.smoke_failures += 1
                fixed_code, was_fixed = self._attempt_smoke_self_fix(
                    code, smoke_result.error_info, parent
                )
                if was_fixed and fixed_code:
                    smoke_retry, retry_duration_s = self._run_smoke_test(fixed_code, parent)
                    if smoke_retry and smoke_retry.is_valid:
                        code = fixed_code
                        self.metrics.smoke_fixes += 1
                        self._log_event("smoke_passed", {
                            "parent_id": parent.id,
                            "duration_s": round(retry_duration_s, 3),
                        })
                        self._log_event("smoke_fix_success", {
                            "parent_id": parent.id,
                            "original_error": err_snippet[:200],
                        })
                    else:
                        retry_is_timeout = (
                            smoke_retry and "timeout" in smoke_retry.error_info.lower()
                        )
                        if retry_is_timeout:
                            self.metrics.perf_rejections += 1
                            invalid_child = self._handle_invalid_generation(
                                parent, f"perf_rejected: smoke timeout after fix",
                                intent, code, hypothesis, operator=operator,
                            )
                            outcome = "perf_rejected"
                        else:
                            invalid_child = self._handle_invalid_generation(
                                parent, f"smoke_failed: {err_snippet[:100]}",
                                intent, code, hypothesis, operator=operator,
                            )
                            outcome = "smoke_rejected"
                        self.metrics.add_eval(0, False)
                        self._log_event("smoke_failed", {
                            "parent_id": parent.id,
                            "error": err_snippet,
                            "duration_s": round(retry_duration_s, 3),
                        })
                        self._log_iteration_complete(
                            outcome, parent_id=parent.id, node_id=invalid_child.id,
                        )
                        return True
                else:
                    invalid_child = self._handle_invalid_generation(
                        parent, f"smoke_failed: {err_snippet[:100]}",
                        intent, code, hypothesis, operator=operator,
                    )
                    self.metrics.add_eval(0, False)
                    self._log_event("smoke_failed", {
                        "parent_id": parent.id,
                        "error": err_snippet,
                        "duration_s": round(smoke_duration_s, 3),
                    })
                    self._log_iteration_complete(
                        "smoke_rejected", parent_id=parent.id, node_id=invalid_child.id,
                    )
                    return True

        if operator == OperatorType.INJECT and knowledge_cards and not adopted_cards:
            adopted_cards = [knowledge_cards[0]["id"]]

        child = create_child_node(
            parent, code, intent, hypothesis, operator,
        )
        if adopted_cards:
            child.card_ids = adopted_cards
            self.metrics.cards_adopted_count += len(adopted_cards)
            self.metrics.discovered_cards_adopted += sum(
                1 for cid in adopted_cards if cid.startswith("D-")
            )
        if gen_result.claim:
            self._pending_claims.append((child.id, gen_result.claim))
        self.tree.add_node(child)
        if is_crossover and partner is not None:
            self.store.add_node_parent(
                self.experiment_id, child.id, parent.id, "primary",
            )
            self.store.add_node_parent(
                self.experiment_id, child.id, partner.id, "secondary",
            )
            self._crossover_partners[child.id] = partner.id
            self._log_event(
                "crossover_parents",
                {
                    "node_id": child.id,
                    "parent_id": parent.id,
                    "partner_id": partner.id,
                    "est_runtime_s": estimate_runtime_s(parent, partner),
                },
            )
        if self.config.insights.reputation_enabled and not is_crossover:
            self._offered_insights[child.id] = [
                str(i.get("id"))
                for i in (*positive, *negative)
                if i.get("id")
            ]
        if rendered and self._exchange is not None:
            # Provenance lives on the application row, never on parent_id: the
            # tree parent stays in this island, and the sibling link is the
            # summary that was read.
            self._summary_applications[child.id] = self._exchange.record_applications(
                rendered, child.id
            )
            if is_summary_cross:
                self._log_event("summary_crossover", {
                    "island_id": self._active_island or "",
                    "node_id": child.id,
                    "parent_id": parent.id,
                    "sources": [
                        {
                            "summary_id": c.summary_id,
                            "delivery_id": c.delivery_id,
                            "source_island_id": c.source_island_id,
                            "source_node_id": c.source_node_id,
                        }
                        for c in self._summary_cross_candidates()
                    ],
                })
        prescreen = self._apply_prescreen(parent, child, offered_card_ids)
        screened = prescreen.decision != "evaluate"
        shadow = prescreen.would_screen and prescreen.decision == "evaluate"
        audited = screened and self._audit_rng.random() < self.config.judge.audit_rate
        if screened and not audited:
            self.tree.update_node_status(child.id, NodeStatus.ABANDONED)
            self.metrics.iterations_done += 1
            self.metrics.candidates_screened += 1
            self.metrics.evaluations_saved += 1
            deferred = prescreen.decision == "defer"
            if deferred:
                self._deferred.append(DeferredCandidate(
                    child.id, parent.id, prescreen.value, offered_card_ids,
                ))
            self._log_event("jev_screened", {
                "island_id": self._active_island or "",
                "node_id": child.id,
                "parent_id": parent.id,
                "decision": prescreen.decision,
                "value": prescreen.value,
                "audited": False,
                "deferred": deferred,
            })
            self._log_iteration_complete(
                "jev_screened", parent_id=parent.id, node_id=child.id,
            )
            return True

        baseline_score = None
        if is_crossover and partner is not None:
            baseline_score = max(parent.get_score(), partner.get_score())
        self._evaluate_child(
            parent,
            child,
            offered_card_ids,
            count_iteration=True,
            screen_sample="shadow" if shadow else ("audit" if audited else None),
            baseline_score=baseline_score,
        )

        return True

    def _prescreen_context(self, parent: Node, hypothesis: str) -> dict[str, Any]:
        return {
            "problem_md": self.task_spec.problem_md,
            "constraints": self._constraints_text,
            "candidate_hypothesis": hypothesis,
        }

    def _apply_prescreen(
        self,
        parent: Node,
        child: Node,
        offered_card_ids: list[str],
    ) -> PrescreenResult:
        if self._structure_tuner is not None:
            # A structure is ranked only after its local parameter search.
            return PrescreenResult()
        if child.operator == OperatorType.CROSSOVER:
            return PrescreenResult()
        if not self.judge or not self.judge.enabled or not self.config.judge.prescreen:
            return PrescreenResult()
        if self._stage_capped("jev"):
            return PrescreenResult()
        was_circuit_open = self.judge.circuit_open
        result = self.judge.prescreen(
            parent,
            child.artifact.code,
            child.artifact.intent,
            self._prescreen_context(parent, child.artifact.hypothesis),
        )
        if result.attempted:
            self.metrics.jev_calls += 1
        if result.ok:
            self._meter_llm_call(
                CallMetrics(
                    result.prompt_tokens,
                    result.completion_tokens,
                    result.latency_ms,
                ),
                "jev",
                node_id=child.id,
                model=self.judge.model,
                db_purpose="jev_prescreen",
            )
            self._jev_values[child.id] = result.value
            self.judge.value_cache[child.id] = result.value
            self._log_event("jev_prescreen", {
                "island_id": self._active_island or "",
                "node_id": child.id,
                "parent_id": parent.id,
                "ok": True,
                "decision": result.decision,
                "would_screen": result.would_screen,
                "p_invalid": result.p_invalid,
                "p_improve": result.p_improve,
                "value": result.value,
                "latency_ms": result.latency_ms,
            })
            self._sync_selector_priors()
        elif result.attempted:
            self.metrics.jev_errors += 1
            self.metrics.jev_fail_open += 1
            self._log_event("jev_error", {
                "node_id": child.id,
                "error_type": result.error,
                "consecutive_errors": self.judge.consecutive_errors,
                "fail_open": True,
            })
        if (
            not was_circuit_open
            and self.judge.circuit_open
            and not self._circuit_event_emitted
        ):
            self._circuit_event_emitted = True
            self.metrics.jev_disabled_reason = "circuit_open"
            self._log_event("jev_circuit_open", {
                "threshold": self.config.judge.max_consecutive_errors,
            })
        if self.judge.disabled_reason:
            self.metrics.jev_disabled_reason = self.judge.disabled_reason
        return result

    def _resume_structure_tuning(self) -> None:
        # Finish a persisted proposal before selecting or generating another one.
        for rt in self._island_nodes():
            self._activate_island(rt.island_id)
            for node in list(self.tree.nodes.values()):
                context_path = self._structure_tuner.directory(node.id) / "context.json"
                if node.evidence.evaluation is not None or not context_path.is_file():
                    continue
                context = json.loads(context_path.read_text())
                parent = self.tree.nodes[node.parent_id]
                self._evaluate_child(parent, node, context.pop("offered_card_ids", []), **context)
                self._update_island_after_attempt(rt, True)
                best_id, best_score = self._best_across_islands()
                self.store.update_experiment(self.experiment_id, iterations_done=self.metrics.iterations_done,
                                             best_node_id=best_id, best_score=best_score)

    def _evaluate_child(
        self,
        parent: Node,
        child: Node,
        offered_card_ids: list[str],
        *,
        count_iteration: bool,
        screen_sample: str | None = None,
        baseline_score: float | None = None,
        is_repair: bool = False,
    ) -> tuple[EvalResult, float]:
        _, previous_best_score = self.tree.get_island_best()
        if self._structure_tuner is None and ledger_would_block_full_eval(self):
            self._ledger_stop = True
            return EvalResult(0, 0, 0, "ledger_full_eval_cap", {}), 0.0
        t0 = time.time()
        try:
            if self._structure_tuner is not None:
                eval_result = self._structure_tuner.evaluate(child, {
                    "count_iteration": count_iteration, "screen_sample": screen_sample,
                    "baseline_score": baseline_score, "offered_card_ids": offered_card_ids,
                    "is_repair": is_repair,
                })
                if eval_result is None:
                    return EvalResult(0, 0, 0, "structure_tuning_budget_exhausted", {}), 0.0
            else:
                eval_result = self.task_adapter.evaluate(child.artifact.code, self.task_spec)
        except Exception as e:
            self._note_infra_failure("evaluate_exception", {
                "node_id": child.id,
                "error_type": type(e).__name__,
            })
            raise
        self._record_evaluation_outcome(
            node_id=child.id,
            valid=eval_result.is_valid,
            score=eval_result.combined_score,
            previous_best=previous_best_score,
        )
        self._finish_summary_applications(child, eval_result)
        if self._structure_tuner is None:
            ledger_record(
                self, stage="full_eval", fidelity="full_val", node_id=child.id,
                evaluator_calls=1, wall_s=time.time() - t0,
            )
        self.metrics.add_eval(
            0.0 if self._structure_tuner is not None else eval_result.cost_time,
            eval_result.is_valid,
            count_iteration=count_iteration,
            is_repair=is_repair,
        )
        noise_delta = self.task_adapter.get_noise_delta(eval_result)
        base = baseline_score if baseline_score is not None else parent.get_score()
        delta = eval_result.combined_score - base
        self._record_operator_outcome(
            child.operator,
            valid=eval_result.is_valid,
            delta=delta,
            noise_delta=noise_delta,
        )
        stored_error = (
            self._traceback_snippet(eval_result.error_info)
            if eval_result.error_info else ""
        )
        self.tree.update_node_evidence(child.id, NodeEvidence(
            evaluation=EvaluationResult(
                validity=eval_result.validity,
                combined_score=eval_result.combined_score,
                cost_time=eval_result.cost_time,
                error_info=stored_error,
                metric=eval_result.metric,
            ),
            delta_score=delta,
            noise_delta=noise_delta,
        ))
        adopted_cards = child.card_ids
        if adopted_cards:
            self.store.add_node_adopted_cards(
                self.experiment_id, child.id, adopted_cards,
            )
            is_degenerate = (
                eval_result.is_valid
                and eval_result.combined_score < DEGENERATE_SCORE_THRESHOLD
            )
            if eval_result.is_valid and not is_degenerate:
                for card_id in adopted_cards:
                    self.store.update_card_stats(self.experiment_id, card_id, delta)
                self.metrics.cards_adopted_valid_count += len(adopted_cards)
            elif is_api_compat_error(eval_result.error_info):
                self.metrics.adapter_errors += 1
            elif not is_degenerate:
                for card_id in adopted_cards:
                    self.store.update_card_stats_invalid(
                        self.experiment_id, card_id,
                        -self._invalid_penalty_factor * noise_delta,
                    )
        self._maybe_analyze_node(child, previous_best_score)
        if offered_card_ids:
            self.store.record_offered_cards(
                self.experiment_id,
                child.branch_id,
                offered_card_ids,
                self.metrics.iterations_done,
                was_invalid=not eval_result.is_valid,
            )
        if eval_result.is_valid:
            if self.config.insights.reputation_enabled:
                for iid in self._offered_insights.pop(child.id, []):
                    update_insight_reputation(
                        iid,
                        delta > noise_delta,
                        self.store,
                        self.experiment_id,
                    )
            self.selector.update_best_score(eval_result.combined_score)
            self._observe_node(child)
            self._apply_reflection(
                parent, child, delta, noise_delta, eval_result, adopted_cards,
            )
        else:
            error_class = classify_error(eval_result.error_info)
            self.tree.set_error_class(child.id, error_class)
            self._update_error_class_memory(parent, error_class)
            if self.tree.get_repair_chain_length(child.id) < MAX_REPAIR_ATTEMPTS:
                self._attempt_repair(
                    child, parent, eval_result.error_info, error_class,
                )
        if screen_sample:
            bad = not eval_result.is_valid or delta <= noise_delta
            self.metrics.screen_audited += 1
            self.metrics.screen_audit_bad += int(bad)
            self.metrics.screen_shadow += int(screen_sample == "shadow")
            self._log_event("jev_audited", {
                "node_id": child.id,
                "shadow": screen_sample == "shadow",
                "bad": bad,
                "delta": delta,
                "valid": eval_result.is_valid,
            })
            if self.judge:
                self.judge.record_outcome(
                    "prescreen",
                    {"bad": 1.0 if bad else 0.0},
                    "bad" if bad else "good",
                    {"shadow": screen_sample == "shadow"},
                )
        if count_iteration:
            self._log_iteration_complete(
                "evaluated" if eval_result.is_valid else "invalid",
                node_id=child.id,
                parent_id=parent.id,
                score=eval_result.combined_score,
                delta=delta,
                valid=eval_result.is_valid,
                error_class=child.error_class if not eval_result.is_valid else "",
                adopted_cards=adopted_cards,
            )
        return eval_result, delta

    def _flush_deferred(self, limit: int) -> None:
        if limit <= 0 or not self.tree:
            return
        island_id = self._active_island or ""
        flushed: list[str] = []
        for item in sorted(self._deferred, key=lambda x: x.value, reverse=True)[:limit]:
            if token_cap_exceeded(self.metrics.total_tokens, self.config.budget.max_tokens):
                break
            child = self.tree.get_node(item.node_id)
            parent = self.tree.get_node(item.parent_id)
            if child is None or parent is None:
                continue
            stored = child.evidence.evaluation
            if stored is not None:
                # This candidate has already been paid for: the process died after
                # the evaluator answered but before the flush event was written.
                # Re-announcing the result is right, running the evaluator again
                # would spend twice and credit the same gain twice.
                self.tree.update_node_status(child.id, NodeStatus.DONE)
                self._log_event("jev_deferred_evaluated", {
                    "island_id": island_id,
                    "node_id": child.id,
                    "value": item.value,
                    "valid": stored.validity >= 1.0,
                    "delta": child.get_score() - parent.get_score(),
                    "rebuilt_from_node": True,
                })
                flushed.append(item.node_id)
                continue
            self.tree.update_node_status(child.id, NodeStatus.PENDING)
            result, delta = self._evaluate_child(
                parent, child, item.offered_card_ids, count_iteration=False,
            )
            self.metrics.evaluations_saved = max(0, self.metrics.evaluations_saved - 1)
            # The island tag is what lets a resume tell "screened, still waiting"
            # from "screened, already flushed"; without it the candidate comes back
            # on the next start and gets evaluated a second time.
            self._log_event("jev_deferred_evaluated", {
                "island_id": island_id,
                "node_id": child.id,
                "value": item.value,
                "valid": result.is_valid,
                "delta": delta,
            })
            flushed.append(item.node_id)
        self._deferred = [item for item in self._deferred if item.node_id not in flushed]

    def _restore_jev_state(self) -> None:
        screened: dict[str, DeferredCandidate] = {}
        flushed: set[str] = set()
        for event in self.store.get_events(self.experiment_id):
            payload = event.payload
            # Events predating islands carry no island tag at all; they belong
            # to the implicit single island, which is the active one here.
            if str(payload.get("island_id", "")) != (self._active_island or ""):
                continue
            if event.type == "jev_prescreen" and payload.get("ok"):
                self._jev_values[str(payload["node_id"])] = float(payload.get("value", 0.5))
            elif event.type == "jev_screened" and payload.get("deferred"):
                node_id = str(payload["node_id"])
                screened[node_id] = DeferredCandidate(
                    node_id,
                    str(payload["parent_id"]),
                    float(payload.get("value", 0.5)),
                    [],
                )
            elif event.type == "jev_deferred_evaluated":
                flushed.add(str(payload["node_id"]))
        self._deferred = [
            item for node_id, item in screened.items() if node_id not in flushed
        ]
        if self.judge:
            self.judge.value_cache.update(self._jev_values)

    def _sync_selector_priors(self) -> None:
        if not self.selector or not self.judge:
            return
        enabled = bool(
            self.config.selection.policy == "jev_puct"
            and self.judge.enabled
            and self.config.judge.prior
        )
        self.selector.set_node_priors(
            self._jev_values,
            self.judge.get_trust(),
            enabled,
        )

    def _attempt_repair(
        self,
        failed_node: Node,
        parent: Node,
        error_info: str,
        error_class: str,
    ) -> None:
        """Attempt to repair a failed node.

        Creates a repair child node with the same parent as failed_node.
        Up to MAX_REPAIR_ATTEMPTS repair evaluations are allowed per
        original failed node (tracked via repair_parent_id chain).

        Args:
            failed_node: The node that failed with runtime error
            parent: The original parent (working) node
            error_info: Error traceback/message
            error_class: Classified error type
        """
        if self._structure_tuner is not None and not self._structure_tuner.can_dispatch():
            return
        if self._stage_capped("repair"):
            return

        # A repair candidate is still a candidate: the protocol counts one island
        # attempt per candidate produced, so a chain cannot buy extra evaluations
        # past the island's own cap. Refuse before spending LLM tokens on it.
        runtime = self._active_runtime()
        if runtime is not None and runtime.state.attempts >= runtime.spec.max_attempts:
            self._log_event("island_attempt_cap_hit", {
                "island_id": runtime.island_id,
                "attempts": runtime.state.attempts,
                "max_attempts": runtime.spec.max_attempts,
                "refused": "repair",
                "failed_node_id": failed_node.id,
            })
            return

        chain_length = self.tree.get_repair_chain_length(failed_node.id)
        current_attempt = chain_length + 1

        if current_attempt > MAX_REPAIR_ATTEMPTS:
            root = self.tree.get_repair_chain_root(failed_node.id)
            if root:
                self.tree.mark_repair_exhausted(root.id)
            return

        self.tree.increment_repair_count(failed_node.id)

        avoidance_notes = self._get_avoidance_notes(parent, error_class)

        try:
            repair_code, repair_intent, repair_hypothesis, repair_metrics = \
                self.repair_operator.generate(
                    failing_code=failed_node.artifact.code,
                    error_info=error_info,
                    parent_node=parent,
                    task_spec=self.task_spec,
                    avoidance_notes=avoidance_notes,
                    constraints=self._constraints_text,
                )
        except LLMTransientError as e:
            self._log_event("llm_error", {
                "context": "repair",
                "failed_node_id": failed_node.id,
                "error": str(e),
            })
            self._record_lost_llm_call(e, "repair", node_id=failed_node.id)
            return

        self._meter_llm_call(repair_metrics, "repair", node_id=failed_node.id)
        self.metrics.add_repair_attempt(success=False)

        if repair_code is None:
            self._log_event("repair_failed", {
                "failed_node_id": failed_node.id,
                "repair_attempt": current_attempt,
                "reason": "generation_failed",
            })
            return

        precheck_result = precheck_and_fix(repair_code)
        if precheck_result.was_fixed:
            repair_code = precheck_result.fixed_code
            self.metrics.precheck_fixes += len(precheck_result.fixes_applied)
            self._log_event("precheck_fix_repair", {
                "failed_node_id": failed_node.id,
                "repair_attempt": current_attempt,
                "fixes": precheck_result.fixes_applied,
            })

        if precheck_result.has_unfixable:
            fixed_code, was_fixed = self._attempt_perf_self_fix(
                repair_code, precheck_result.unfixable_issues, parent
            )
            if was_fixed and fixed_code:
                recheck = precheck_and_fix(fixed_code)
                if not recheck.has_unfixable:
                    repair_code = recheck.fixed_code if recheck.was_fixed else fixed_code
                else:
                    self.metrics.perf_rejections += 1
                    self._log_event("repair_perf_rejected", {
                        "failed_node_id": failed_node.id,
                        "repair_attempt": current_attempt,
                        "issues": precheck_result.unfixable_issues,
                    })
                    return
            else:
                self.metrics.perf_rejections += 1
                self._log_event("repair_perf_rejected", {
                    "failed_node_id": failed_node.id,
                    "repair_attempt": current_attempt,
                    "issues": precheck_result.unfixable_issues,
                })
                return

        static_error = self.task_adapter.static_check(repair_code, self.task_spec)
        if static_error:
            self._log_event("repair_failed", {
                "failed_node_id": failed_node.id,
                "repair_attempt": current_attempt,
                "reason": f"static_check: {static_error[:100]}",
            })
            return

        smoke_result, smoke_duration_s = self._run_smoke_test(repair_code, parent)
        if smoke_result is not None and not smoke_result.is_valid:
            is_timeout = "timeout" in smoke_result.error_info.lower()
            if is_timeout:
                self.metrics.perf_rejections += 1
            else:
                self.metrics.smoke_failures += 1
            self._log_event("repair_smoke_failed", {
                "failed_node_id": failed_node.id,
                "repair_attempt": current_attempt,
                "error": self._traceback_snippet(smoke_result.error_info),
                "is_timeout": is_timeout,
                "duration_s": round(smoke_duration_s, 3),
            })
            return

        repair_node = create_repair_node(
            failed_node, repair_code, repair_intent, repair_hypothesis, error_class,
        )
        self.tree.add_node(repair_node)
        # Charged here, not when the chain started: a chain that never produced an
        # evaluable candidate (refused, unfixable, static-check failure) spent no
        # candidate and must not spend one.
        self._count_attempt(failed_node, OperatorType.REPAIR)

        _, previous_best_score = self.tree.get_island_best()
        try:
            if self._structure_tuner is not None:
                eval_result = self._structure_tuner.evaluate(repair_node, {
                    "count_iteration": False, "offered_card_ids": [], "is_repair": True,
                })
                if eval_result is None:
                    return
            else:
                eval_result = self.task_adapter.evaluate(repair_code, self.task_spec)
        except Exception as e:
            self._note_infra_failure("repair_evaluate_exception", {
                "node_id": repair_node.id,
                "error_type": type(e).__name__,
            })
            raise
        self._record_evaluation_outcome(
            node_id=repair_node.id,
            valid=eval_result.is_valid,
            score=eval_result.combined_score,
            previous_best=previous_best_score,
        )
        self.metrics.add_eval(0.0 if self._structure_tuner is not None else eval_result.cost_time,
                              eval_result.is_valid, is_repair=True)

        noise_delta = self.task_adapter.get_noise_delta(eval_result)
        parent_score = parent.get_score()
        delta = eval_result.combined_score - parent_score

        stored_error = (
            self._traceback_snippet(eval_result.error_info)
            if eval_result.error_info
            else eval_result.error_info
        )
        evidence = NodeEvidence(
            evaluation=EvaluationResult(
                validity=eval_result.validity,
                combined_score=eval_result.combined_score,
                cost_time=eval_result.cost_time,
                error_info=stored_error,
                metric=eval_result.metric,
            ),
            delta_score=delta,
            noise_delta=noise_delta,
        )
        self.tree.update_node_evidence(repair_node.id, evidence)
        self._maybe_analyze_node(repair_node, previous_best_score)

        if eval_result.is_valid:
            self.metrics.repair_successes += 1
            self.selector.update_best_score(eval_result.combined_score)
            self._observe_node(repair_node)
            self._apply_reflection(parent, repair_node, delta, noise_delta, eval_result, [])

            self._log_event("repair_success", {
                "failed_node_id": failed_node.id,
                "repair_node_id": repair_node.id,
                "repair_attempt": current_attempt,
                "score": eval_result.combined_score,
                "error_class": error_class,
            })
        else:
            new_error_class = classify_error(eval_result.error_info)
            self.tree.set_error_class(repair_node.id, new_error_class)
            self._update_error_class_memory(parent, new_error_class)

            self._log_event("repair_failed", {
                "failed_node_id": failed_node.id,
                "repair_node_id": repair_node.id,
                "repair_attempt": current_attempt,
                "reason": "runtime_error",
                "error_class": new_error_class,
            })

            new_chain_length = self.tree.get_repair_chain_length(repair_node.id)
            if new_chain_length < MAX_REPAIR_ATTEMPTS:
                self._attempt_repair(repair_node, parent, eval_result.error_info, new_error_class)
            else:
                root = self.tree.get_repair_chain_root(repair_node.id)
                if root:
                    self.tree.mark_repair_exhausted(root.id)

    def _get_avoidance_notes(self, parent: Node, error_class: str) -> list[str]:
        """Get avoidance notes for a given error class from branch memory.

        Notes are derived only from error classes observed in branch memory,
        not from hardcoded library-specific hints.
        """
        notes = []

        if error_class in self.error_class_counts and self.error_class_counts[error_class] >= 2:
            notes.append(f"Error class '{error_class}' has occurred {self.error_class_counts[error_class]} times. Avoid approaches that lead to this error.")

        memory = parent.branch_memory.summary or ""
        if "Avoid:" in memory:
            for line in memory.split("\n"):
                if line.strip().startswith("Avoid:"):
                    notes.append(line.strip())

        return notes

    def _update_error_class_memory(self, parent: Node, error_class: str) -> None:
        """Update error class counts and add avoidance notes to branch memory."""
        self.error_class_counts[error_class] = self.error_class_counts.get(error_class, 0) + 1

        if self.error_class_counts[error_class] >= 2:
            memory = parent.branch_memory
            avoidance_note = f"Avoid: {error_class} error has occurred {self.error_class_counts[error_class]} times"
            if avoidance_note not in memory.summary:
                memory.summary = f"{memory.summary}\n{avoidance_note}".strip()
                self.tree.update_branch_memory(parent.id, memory)

    def _handle_invalid_generation(
        self,
        parent: Node,
        error: str,
        intent: str,
        code: str | None = None,
        hypothesis: str = "",
        operator: OperatorType = OperatorType.REFINE,
    ) -> Node:
        """Handle invalid generation (parse failure or static check failure)."""
        child = create_child_node(
            parent,
            code or "",
            intent,
            hypothesis,
            operator,
        )
        child.status = NodeStatus.INVALID
        self.tree.add_node(child)

        sanitized = self._traceback_snippet(error)
        evidence = NodeEvidence(
            evaluation=EvaluationResult(
                validity=0.0,
                combined_score=0.0,
                cost_time=0.0,
                error_info=sanitized,
                metric={},
            ),
        )
        self.tree.update_node_evidence(child.id, evidence)

        self._record_operator_outcome(
            operator, valid=False, delta=0.0, noise_delta=0.0,
        )

        self._log_event("invalid_generation", {
            "node_id": child.id,
            "parent_id": parent.id,
            "error": sanitized,
        })
        return child

    def _apply_reflection(
        self,
        parent: Node,
        child: Node,
        delta: float,
        noise_delta: float,
        eval_result: EvalResult,
        adopted_cards: list[str],
    ) -> None:
        """Apply three-layer reflection.

        Layers:
        1. Implementation: syntax/static errors -> repair route (once), rule-based
        2. Design: valid but score drop > delta -> LLM analysis, revise
        3. Hypothesis: drop > 2*delta or same hypothesis failing twice -> LLM analysis, refute

        For hypothesis-layer refutation, any adopted cards are marked as refuted
        on this branch to prevent re-selection.
        """
        if child.operator == OperatorType.CROSSOVER:
            self._log_event(
                "crossover_reflection_skipped",
                {"node_id": child.id},
            )
            return
        reflector = LayeredReflector(
            self.llm, self.experiment_id, mechanism_layer=self._mechanism_layer,
        )

        if not eval_result.is_valid:
            reflection = reflector.reflect_implementation(parent, child, eval_result.error_info)
            self._handle_implementation_reflection(parent, child, reflection)
            return

        design_threshold = noise_delta * self.config.reflection.design_delta_factor
        hypothesis_threshold = noise_delta * self.config.reflection.hypothesis_delta_factor

        if abs(delta) > design_threshold:
            if self._stage_capped("reflect"):
                if delta > design_threshold:
                    self.tree.update_hypothesis_status(
                        child.id, HypothesisStatus.SUPPORTED,
                    )
                elif delta < -hypothesis_threshold:
                    self._reflect_hypothesis_refuted(
                        parent, child, None, adopted_cards,
                    )
                elif delta < -design_threshold:
                    self._reflect_design_issue(parent, child, delta, None)
                return
            try:
                reflection, reflect_metrics = reflector.reflect_with_llm(
                    parent, child, delta, noise_delta
                )
            except LLMTransientError as e:
                self._record_lost_llm_call(e, "reflect", node_id=child.id)
                self._log_event("llm_error", {
                    "context": "reflect",
                    "child_id": child.id,
                    "error": str(e),
                })
                return

            self._meter_llm_call(
                reflect_metrics,
                "reflect",
                node_id=child.id,
                model=self.config.llm.reason_model,
                persist=reflect_metrics.prompt_tokens > 0,
            )

            layer = reflection.get("layer", "design")

            if delta > design_threshold:
                self._reflect_positive(parent, child, delta, noise_delta, reflection)
            elif delta < -hypothesis_threshold or layer == "hypothesis":
                self._reflect_hypothesis_refuted(parent, child, reflection, adopted_cards)
            elif delta < -design_threshold or layer == "design":
                self._reflect_design_issue(parent, child, delta, reflection)
            elif layer == "mechanism" and self._mechanism_layer:
                self._reflect_mechanism_issue(parent, child, delta, reflection)

    def _reflect_mechanism_issue(
        self,
        parent: Node,
        child: Node,
        delta: float,
        reflection: dict[str, Any] | None,
    ) -> None:
        self.tree.update_node_status(child.id, NodeStatus.DONE)
        self.tree.update_hypothesis_status(child.id, HypothesisStatus.UNDETERMINED)
        self._log_event("reflection_mechanism", {
            "node_id": child.id,
            "parent_id": parent.id,
            "delta": delta,
            "summary": (reflection or {}).get("change_summary", "")[:200],
        })

    def _handle_implementation_reflection(
        self,
        parent: Node,
        child: Node,
        reflection: dict[str, Any],
    ) -> None:
        """Handle implementation-layer reflection.

        If repair not yet attempted, mark for repair route on parent
        and store the repair hint.
        """
        repair_hint = reflection.get("repair_hint", "")

        if not parent.repair_attempted:
            self.tree.mark_repair_attempted(parent.id)

            if repair_hint:
                memory = parent.branch_memory
                memory.summary = f"Repair hint: {repair_hint[:200]}"
                self.tree.update_branch_memory(parent.id, memory)

            self._log_event("reflection_implementation", {
                "node_id": child.id,
                "parent_id": parent.id,
                "error": repair_hint[:200],
                "causes": reflection.get("causes", []),
            })

    def _reflect_design_issue(
        self,
        parent: Node,
        child: Node,
        delta: float,
        reflection: dict[str, Any] | None = None,
    ) -> None:
        """Handle design-layer reflection.

        Valid but score dropped significantly - idea might be right but
        implementation is wrong. Uses LLM analysis to understand cause.
        """
        self.tree.update_node_status(child.id, NodeStatus.DONE)

        self._log_event("reflection_design", {
            "node_id": child.id,
            "parent_id": parent.id,
            "delta": delta,
            "layer": reflection.get("layer") if reflection else "design",
            "mechanism": reflection.get("mechanism", "")[:200] if reflection else "",
            "causes": reflection.get("causes", []) if reflection else [],
        })

    def _reflect_hypothesis_refuted(
        self,
        parent: Node,
        child: Node,
        reflection: dict[str, Any] | None = None,
        adopted_cards: list[str] | None = None,
    ) -> None:
        """Handle hypothesis-layer reflection.

        Large score drop or repeated failures -> refute hypothesis.
        Uses LLM analysis to understand why the hypothesis failed.

        When a hypothesis is refuted, any adopted knowledge cards are marked
        as refuted on this branch to prevent re-selection in future iterations.
        """
        self.tree.increment_hypothesis_fail_count(parent.id)

        hypothesis = child.artifact.hypothesis
        if hypothesis:
            same_hypothesis_fails = parent.hypothesis_fail_count >= 1
            if same_hypothesis_fails:
                self.tree.update_hypothesis_status(child.id, HypothesisStatus.REFUTED)
                self.tree.add_refuted_hypothesis(parent.id, hypothesis)

                if adopted_cards:
                    for card_id in adopted_cards:
                        self.store.add_branch_refuted_card(
                            self.experiment_id, child.branch_id, card_id
                        )
                        self.store.increment_card_refuted_count(
                            self.experiment_id, card_id
                        )

                self._log_event("hypothesis_refuted", {
                    "node_id": child.id,
                    "hypothesis": hypothesis,
                    "mechanism": reflection.get("mechanism", "")[:200] if reflection else "",
                    "causes": reflection.get("causes", []) if reflection else [],
                    "refuted_cards": adopted_cards or [],
                })

    def _reflect_positive(
        self,
        parent: Node,
        child: Node,
        delta: float,
        noise_delta: float,
        reflection: dict[str, Any] | None = None,
    ) -> None:
        """Handle positive reflection - significant improvement.

        Extract and propagate insight using the reflection analysis.
        """
        self.tree.update_hypothesis_status(child.id, HypothesisStatus.SUPPORTED)

        z_score = delta / noise_delta if noise_delta > 0 else 0.0

        insight = Insight(
            id=str(uuid.uuid4())[:8],
            origin_node=child.id,
            branch_id=child.branch_id,
            island_id=self._active_island or "",
            polarity=1,
            change_summary=reflection.get("change_summary", "") if reflection else "",
            mechanism=reflection.get("mechanism", "") if reflection else "",
            conditions=reflection.get("conditions", "") if reflection else "",
            tags=reflection.get("tags", []) if reflection else [],
            delta=delta,
            z_score=z_score,
            alpha=1.0,
            beta=1.0,
            created_at=now_iso(),
        )

        memory_manager = BranchMemoryManager(
            self.store, self.tree, self.config.insights.top_k_branch_memory,
        )
        memory_manager.propagate_insight(insight, child, self.experiment_id)

        self._log_event("insight_extracted", {
            "insight_id": insight.id,
            "node_id": child.id,
            "delta": delta,
            "z_score": insight.z_score,
            "mechanism": reflection.get("mechanism", "")[:200] if reflection else "",
        })

    def _meter_llm_call(
        self,
        metrics: CallMetrics,
        purpose: str,
        node_id: str | None = None,
        model: str | None = None,
        db_purpose: str | None = None,
        persist: bool = True,
    ) -> None:
        """Single bookkeeping entry point for one LLM call.

        Accounts ``metrics`` into this run's :class:`RunMetrics` under
        ``purpose`` and, in the same statement, writes the matching row to the
        ``llm_call`` table.  The two writes must never diverge:
        ``SUM(llm_call tokens)`` has to equal ``run_summary.total_tokens``.
        Bug B-13 was exactly such a divergence (the two ``self_fix`` sites were
        accounted but never persisted), so funnelling every call through this
        single place makes that class of bug structurally unreintroducible.

        Args:
            metrics: Token/latency counters returned by the LLM client.
            purpose: Accounting bucket in :class:`RunMetrics`.
            node_id: Node the call belongs to (empty/None for run-level calls).
            model: Model name stored on the row; defaults to the generate model.
            db_purpose: Row purpose when it differs from the bucket, e.g. bucket
                ``generate`` paired with row purpose ``refine``.
            persist: When false, only the accounting side is updated (used for
                reflect calls that produced no tokens).
        """
        self.metrics.add_llm_call(metrics, purpose)
        # Which island asked for this call. The loop runs one island at a time, so
        # the active island is exactly the one whose code path is executing; "" is
        # the real island id of a legacy single-tree run, not a missing value.
        island_id = self._active_island or ""
        stage = LLM_STAGE_MAP.get(purpose, "other")
        ledger_record(
            self,
            stage=stage,
            fidelity="none",
            node_id=node_id,
            prompt_tokens=metrics.prompt_tokens,
            completion_tokens=metrics.completion_tokens,
        )
        if not persist:
            return
        self.store.create_llm_call(
            create_llm_call_record(
                self.experiment_id,
                db_purpose or purpose,
                model or self.config.llm.generate_model,
                metrics,
                node_id=node_id,
                island_id=island_id,
                stage=stage,
                island_attempt=self._island_attempt_index(island_id),
            )
        )

    def _island_attempt_index(self, island_id: str) -> int | None:
        """Which attempt of this island the call belongs to, counting from one.

        ``IslandState.attempts`` counts finished attempts, so the one in flight is
        the next number. A call made while no island is active is run-level work
        and gets null, not a zeroth attempt.
        """
        if self._coordinator is None or not island_id:
            return None
        return self._coordinator.runtime(island_id).state.attempts + 1

    def _record_lost_llm_call(
        self,
        exc: LLMTransientError,
        purpose: str,
        node_id: str | None = None,
        model: str | None = None,
    ) -> None:
        """Write down a request that went out and never came back.

        A failed send is not a free send: the provider may have billed tokens the
        client never saw. The row therefore carries the request identity and the
        number of transport tries, with no token counts (the client cannot know
        them) and ``outcome='unknown_outcome'``, which the cost rollup reports as
        unresolved rather than silently dropping. RunMetrics is left alone -- its
        totals only ever add up tokens a client actually reported.
        """
        island_id = self._active_island or ""
        stage = LLM_STAGE_MAP.get(purpose, "other")
        record = create_llm_call_record(
            self.experiment_id,
            purpose,
            model or self.config.llm.generate_model,
            CallMetrics(
                request_id=getattr(exc, "request_id", ""),
                attempts=getattr(exc, "attempts", 1),
            ),
            node_id=node_id,
            island_id=island_id,
            stage=stage,
            island_attempt=self._island_attempt_index(island_id),
            outcome="unknown_outcome",
        )
        self.store.create_llm_call(record)
        ledger_record(
            self,
            stage=stage,
            fidelity="none",
            node_id=node_id,
            status="failed",
        )
        self._log_event(
            "llm_call_lost",
            {
                "island_id": island_id,
                "request_id": record.request_id,
                "transport_attempts": record.transport_attempts,
                "purpose": purpose,
                "node_id": node_id or "",
                "error": str(exc)[:200],
            },
        )

    def _log_event(self, event_type: str, payload: dict[str, Any]) -> None:
        """Log an event to the store."""
        event = Event(
            experiment_id=self.experiment_id,
            type=event_type,
            payload=payload,
            ts=now_iso(),
        )
        self.store.create_event(event)

    def _discovery_card_path(self) -> Path:
        if self.config.discovery.cards_path:
            return Path(self.config.discovery.cards_path)
        base = self.store.db_path.parent.parent / "knowledge" / "discovered_cards.jsonl"
        return base

    def _extra_card_paths(self) -> list[str]:
        if not self.config.discovery.enabled or not self.config.discovery.inject_same_run:
            return []
        paths = [str(self._discovery_card_path())]
        paths.extend(self.config.discovery.extra_card_paths)
        return paths

    def _discovery_llm_call(self, messages: list[dict[str, str]]) -> str:
        try:
            text, metrics = self.llm.chat_for_reasoning(messages)
        except LLMTransientError as exc:
            self._record_lost_llm_call(
                exc, "discover", node_id="", model=self.config.llm.reason_model,
            )
            raise DiscoveryLLMError(str(exc)) from exc
        self._meter_llm_call(
            metrics, "discover", node_id="", model=self.config.llm.reason_model,
        )
        return text

    def _maybe_run_discovery(self, final: bool) -> None:
        if not self.config.discovery.enabled or self._discovery is None:
            return
        cfg = self.config.discovery
        if final and not cfg.run_at_end:
            return
        if not final:
            n = self.metrics.iterations_done
            if n <= 0 or n % cfg.every_n_iterations != 0 or n == self._last_discovery_iter:
                return
        share = self.metrics.discovery_tokens / max(self.metrics.total_tokens, 1)
        if self.metrics.discovery_tokens > 0 and share >= cfg.max_token_share:
            self._dstats.rounds_skipped += 1
            self._log_event("discovery_skipped", {"reason": "token_share"})
            return
        if token_cap_exceeded(self.metrics.total_tokens, self.config.budget.max_tokens):
            self._dstats.rounds_skipped += 1
            self._log_event("discovery_skipped", {"reason": "token_budget"})
            return
        self._last_discovery_iter = self.metrics.iterations_done
        candidates = self._harvest_discovery_candidates()
        result = self._discovery.run(self._dstats.rounds + 1, final, candidates)
        self._maybe_run_tournament(result, final)
        self._dstats.rounds += 1
        if result.promoted_ids and self._dstats.best_at_first_promotion is None and self.tree:
            _, best = self._best_across_islands()
            self._dstats.best_at_first_promotion = best
        self._log_event(
            "discovery_round_finished",
            {"promoted": result.promoted_ids, "skipped": result.skipped_reason},
        )

    def _harvest_discovery_candidates(self) -> list:
        cfg = self.config.discovery
        seen_nodes: set[str] = set()
        out: list = []
        existing_origins = {
            c.get("origin_node_id")
            for c in self.store.get_claims(self.experiment_id)
            if c.get("origin_node_id")
        }
        with self.store._conn() as conn:
            rows = conn.execute(
                "SELECT DISTINCT origin_node_id FROM claim WHERE experiment_id = ? AND origin_node_id != ''",
                (self.experiment_id,),
            ).fetchall()
        existing_origins.update(row["origin_node_id"] for row in rows)

        for node_id, raw in list(self._pending_claims):
            if self.tree is None:
                continue
            node = self.tree.nodes.get(node_id)
            if node is None or not node.evidence.evaluation or node.evidence.evaluation.validity < 1:
                continue
            parent = self.tree.nodes.get(node.parent_id or "")
            if parent is None:
                continue
            delta = node.evidence.evaluation.combined_score - (
                parent.evidence.evaluation.combined_score if parent.evidence.evaluation else 0
            )
            if delta <= 0:
                continue
            out.append((node_id, parent.artifact.code, node.artifact.code, None, "discover_op", raw))
            seen_nodes.add(node_id)
        self._pending_claims = [
            p for p in self._pending_claims if p[0] not in seen_nodes
        ]

        insights = self.store.get_insights_by_experiment(
            self.experiment_id, island_id=self._active_island or ""
        )
        insights.sort(key=lambda i: i.z_score, reverse=True)
        for ins in insights:
            if ins.polarity != 1 or ins.z_score < cfg.min_insight_z:
                continue
            if ins.origin_node in existing_origins or ins.origin_node in seen_nodes:
                continue
            if self.tree is None:
                continue
            node = self.tree.nodes.get(ins.origin_node)
            if node is None or not node.parent_id:
                continue
            if node.operator == OperatorType.CROSSOVER:
                continue
            parent = self.tree.nodes.get(node.parent_id)
            if parent is None:
                continue
            payload = ins.model_dump()
            out.append(
                (
                    ins.origin_node,
                    parent.artifact.code,
                    node.artifact.code,
                    payload,
                    "insight",
                    None,
                )
            )
            seen_nodes.add(ins.origin_node)

        for node in self._top_nodes(cfg.top_k_programs):
            if node.parent_id is None or node.id in existing_origins or node.id in seen_nodes:
                continue
            if node.operator == OperatorType.CROSSOVER:
                continue
            parent = self.tree.nodes.get(node.parent_id) if self.tree else None
            if parent is None:
                continue
            out.append(
                (
                    node.id,
                    parent.artifact.code,
                    node.artifact.code,
                    None,
                    "top_node",
                    None,
                )
            )
            seen_nodes.add(node.id)

        return out[: cfg.max_claims_per_round]

    def _discovery_summary(self) -> dict[str, Any]:
        d = self._dstats
        stats = self.store.get_all_card_stats(self.experiment_id)

        def weighted_mean(use_discovered: bool) -> float | None:
            num = 0.0
            den = 0.0
            for cid, row in stats.items():
                is_d = cid.startswith("D-")
                if is_d != use_discovered:
                    continue
                n = int(getattr(row, "n", 0))
                if n <= 0:
                    continue
                mean_d = float(getattr(row, "sum_delta", 0)) / n
                num += n * mean_d
                den += n
            return num / den if den > 0 else None

        neg_fpr = (
            d.neg_control_false_positives / d.neg_control_trials
            if d.neg_control_trials > 0
            else None
        )
        planted_rate = {
            k: (d.planted_recovered.get(k, 0) / max(d.planted_trials.get(k, 1), 1))
            for k in d.planted_trials
        }
        score_delta = None
        if self.tree and d.best_at_first_promotion is not None and d.cards_promoted > 0:
            _, best = self._best_across_islands()
            score_delta = best - d.best_at_first_promotion
        return {
            "discovery_tokens": self.metrics.discovery_tokens,
            "discovery_token_share": round(self.metrics.discovery_token_share, 3),
            "discovery_rounds": d.rounds,
            "discovery_rounds_skipped": d.rounds_skipped,
            "claims_proposed": d.claims_proposed,
            "claims_tested": d.claims_tested,
            "claims_sandbox_failed": d.claims_sandbox_failed,
            "claims_confirmed": d.confirmed,
            "claims_revised": d.revised,
            "claims_discovered": d.discovered,
            "claims_refuted": d.refuted,
            "claims_undetermined": d.undetermined,
            "discovered_cards_count": d.cards_promoted,
            "discovered_cards_offered": self.metrics.discovered_cards_offered,
            "discovered_cards_adopted": self.metrics.discovered_cards_adopted,
            "discovered_card_adoption_rate": round(self.metrics.discovered_card_adoption_rate, 3),
            "discovered_card_mean_delta": weighted_mean(True),
            "literature_card_mean_delta": weighted_mean(False),
            "score_delta_after_discovery": score_delta,
            "neg_control_false_positives": d.neg_control_false_positives,
            "neg_control_fpr": neg_fpr,
            "planted_recovery_rate": planted_rate,
            **self._tournament_summary(),
        }

    def _mechanism_llm_call(self, messages: list[dict[str, str]]) -> str:
        try:
            text, metrics = self.llm.chat_for_reasoning(messages)
        except LLMTransientError as exc:
            self._record_lost_llm_call(
                exc, "mechanism", node_id="", model=self.config.llm.reason_model,
            )
            raise DiscoveryLLMError(str(exc)) from exc
        self._meter_llm_call(
            metrics, "mechanism", node_id="", model=self.config.llm.reason_model,
        )
        return text

    def _maybe_run_tournament(self, result: Any, final: bool) -> None:
        tcfg = self.config.discovery.tournament
        if not tcfg.enabled or self._tournament is None:
            return
        handoff = result.extras.get("kd2") if result.extras else None
        if handoff is None:
            return
        if self._tournament_rounds >= tcfg.max_rounds:
            self._tstats.rounds_skipped += 1
            self._log_event("tournament_skipped", {"reason": "max_rounds"})
            return
        total = self.metrics.total_tokens
        if self.metrics.mechanism_tokens > 0 and self.metrics.mechanism_tokens / max(total, 1) >= tcfg.max_token_share:
            self._log_event("tournament_skipped", {"reason": "token_share"})
            return
        if self._stage_capped("mechanism"):
            self._log_event("tournament_skipped", {"reason": "stage_cap"})
            return
        if token_cap_exceeded(total, self.config.budget.max_tokens):
            self._log_event("tournament_skipped", {"reason": "token_budget"})
            return
        established_n = refuted_n = undetermined_n = 0
        for idx in range(len(handoff.claims)):
            fr = self._tournament.run_family(handoff, idx)
            self._feed_back_mechanisms(fr, handoff)
            for m in fr.mechanisms:
                if m.status == "established":
                    established_n += 1
                elif m.status == "refuted":
                    refuted_n += 1
                else:
                    undetermined_n += 1
        self._tournament_rounds += 1
        self._tstats.tournament_rounds = self._tournament_rounds
        self._log_event(
            "tournament_round_finished",
            {
                "round": self._tournament_rounds,
                "established": established_n,
                "refuted": refuted_n,
                "undetermined": undetermined_n,
            },
        )

    def _feed_back_mechanisms(self, fr: Any, handoff: Any) -> None:
        claims_map = {c.id: c for c in handoff.claims}
        card_path = self._discovery_card_path()
        for m in fr.mechanisms:
            claim = claims_map.get(m.claim_id)
            if m.status == "refuted" and m.role == "claim" and claim:
                record_mechanism_insight(
                    self.store,
                    self.experiment_id,
                    m,
                    claim.origin_node_id,
                    2.0,
                    "rival",
                )
                self._log_event("mechanism_refuted", {"mechanism_id": m.id})
            if m.status == "established" and m.role == "claim" and claim:
                cards = promote_mechanisms(
                    [m],
                    claims_map,
                    card_path,
                    self.experiment_id,
                    self._log_event,
                )
                self._tstats.mechanism_cards_promoted += len(cards)
                for card in cards:
                    cid = card["id"]
                    self.store.record_discovered_card(
                        cid, claim.id, self.experiment_id, "mechanism",
                    )
                summary = f"[MECH] {m.title}: {claim.title}"[:200]
                node = self.tree.nodes.get(claim.origin_node_id) if self.tree else None
                if node:
                    for anc in self.tree.get_ancestors(node.id) + [node]:
                        mem = anc.branch_memory
                        if mem.summary.startswith("Repair hint:"):
                            continue
                        mem.summary = summary
                        self.tree.update_branch_memory(anc.id, mem)
                cur = (
                    node.hypothesis_status
                    if node
                    else HypothesisStatus.OPEN
                )
                if cur not in (
                    HypothesisStatus.REFUTED,
                    HypothesisStatus.SUPPORTED,
                    HypothesisStatus.CORROBORATED,
                ):
                    self.tree.update_hypothesis_status(
                        claim.origin_node_id, HypothesisStatus.CORROBORATED,
                    )
            if m.status == "undetermined" and m.role == "claim" and claim:
                node = self.tree.nodes.get(claim.origin_node_id) if self.tree else None
                if node and node.hypothesis_status not in (
                    HypothesisStatus.REFUTED,
                    HypothesisStatus.SUPPORTED,
                    HypothesisStatus.CORROBORATED,
                ):
                    self.tree.update_hypothesis_status(
                        claim.origin_node_id, HypothesisStatus.UNDETERMINED,
                    )

    def _mechanism_context_items(self) -> list[dict[str, Any]]:
        rows = self.store.get_mechanisms(self.experiment_id, status="established")
        rows.sort(key=lambda r: float(r.get("e_value", 0) or 0), reverse=True)
        items: list[dict[str, Any]] = []
        for row in rows[:3]:
            items.append({
                "title": row.get("title", ""),
                "certificates": int(row.get("certificates", 0)),
                "text": row.get("title", ""),
            })
        return items

    def _tournament_summary(self) -> dict[str, Any]:
        ts = self._tstats
        planted_rate = (
            ts.planted_mechanism_recovered / ts.planted_mechanism_trials
            if ts.planted_mechanism_trials > 0
            else None
        )
        shuffled_rate = (
            ts.shuffled_env_false_pass / ts.shuffled_env_trials
            if ts.shuffled_env_trials > 0
            else None
        )
        min_det = min(ts.min_detectable_effects) if ts.min_detectable_effects else None
        return {
            "mechanism_tokens": self.metrics.mechanism_tokens,
            "tournament_tokens": self.metrics.mechanism_tokens,
            "mechanisms_proposed": ts.mechanisms_proposed,
            "matches_played": ts.matches_played,
            "decisive_matches": ts.decisive_matches,
            "underpowered_draws": ts.underpowered_draws,
            "certificates_issued": ts.certificates_issued,
            "mechanisms_established": ts.mechanisms_established,
            "mechanisms_refuted": ts.mechanisms_refuted,
            "mechanism_patches": ts.mechanism_patches,
            "mechanism_cards_count": ts.mechanism_cards_promoted,
            "tournament_rounds": ts.tournament_rounds,
            "planted_mechanism_recovered": planted_rate,
            "llm_vs_data_kendall_tau": ts.llm_vs_data_kendall_tau,
            "shuffled_env_false_pass": shuffled_rate,
            "min_detectable_effect": min_det,
        }

    def write_tournament_artifacts(self, art_dir: Path) -> None:
        if not self.config.discovery.tournament.enabled:
            return
        certs = [Certificate(**c) for c in self.store.get_certificates(self.experiment_id)]
        mechs = self.store.get_mechanisms(self.experiment_id)
        write_certificate_artifacts(
            art_dir,
            certs,
            mechs,
            self._tournament_results,
        )

    def write_discovery_artifacts(self, art_dir: Path) -> None:
        if self._discovery is None:
            return
        try:
            self._discovery.write_artifacts(art_dir)
        except Exception:
            pass


#: Shape an externally supplied experiment id must have. ``exp_id`` is joined
#: onto a directory path, so a caller-supplied value is a traversal risk unless
#: it is refused here -- the engine must not assume its caller validated it.
_EXPERIMENT_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")


def _validate_experiment_id(value: str) -> str:
    """Return ``value`` if it is a safe experiment id, else raise.

    Refused rather than sanitised: silently rewriting an id would make the
    caller's record point at a different run than the one that got created.
    """
    if not isinstance(value, str) or not _EXPERIMENT_ID_PATTERN.fullmatch(value):
        raise ValueError(
            "experiment_id must match [A-Za-z0-9][A-Za-z0-9._-]{0,63}"
        )
    return value


def run_local_evolution(
    task_dir: Path,
    mock: bool = False,
    max_iterations: int | None = None,
    resume_id: str | None = None,
    target_score: float | None = None,
    seed: int = 20260926,
    runs_dir: Path | None = None,
    artifacts_dir: Path | None = None,
    adapter: TaskAdapter | None = None,
    experiment_id: str | None = None,
    config_path: Path | None = None,
    resume_source: Path | None = None,
    llm_client: LLMClient | None = None,
    workflow: bool | None = None,
) -> dict[str, Any]:
    """Shared entry for local CLI, research and Web execution."""
    options = dict(task_dir=task_dir, mock=mock, max_iterations=max_iterations, resume_id=resume_id,
                   target_score=target_score, seed=seed, runs_dir=runs_dir, artifacts_dir=artifacts_dir,
                   adapter=adapter, experiment_id=experiment_id, config_path=config_path,
                   resume_source=resume_source, llm_client=llm_client)
    config = EvolveConfig.from_yaml(config_path or task_dir / "evolve.yaml").with_overrides(
        max_iterations=max_iterations, target_score=target_score, seed=seed)
    enabled = config.workflow.enabled if workflow is None else workflow
    if enabled:
        from faultevolve.workflow import run_workflow
        config.workflow.enabled = True
        return run_workflow(_run_local_evolution, config, options)
    if resume_id and ((runs_dir or task_dir / ".fe/runs") / resume_id / "workflow/manifest.json").is_file():
        raise ValueError("该运行属于统一工作流，请启用 workflow 后恢复")
    return _run_local_evolution(**options)


def _run_local_evolution(
    task_dir: Path,
    mock: bool = False,
    max_iterations: int | None = None,
    resume_id: str | None = None,
    target_score: float | None = None,
    seed: int = 20260926,
    runs_dir: Path | None = None,
    artifacts_dir: Path | None = None,
    adapter: TaskAdapter | None = None,
    experiment_id: str | None = None,
    config_path: Path | None = None,
    resume_source: Path | None = None,
    llm_client: LLMClient | None = None,
    workflow_active: bool = False,
) -> dict[str, Any]:
    """Run local evolution on a task directory.

    Args:
        task_dir: Path to task directory
        mock: Use mock LLM
        max_iterations: Override the configured iteration budget when provided
        resume_id: ID to resume, or None for new
        experiment_id: Pre-assigned id for a *new* experiment. Letting the
            caller choose it keeps the Web layer's run registry and the
            engine's run directory on one id, instead of two id spaces plus a
            lookup between them. Ignored when ``resume_id`` is given.
        target_score: Target score to reach
        seed: Random seed
        runs_dir: Directory for SQLite DB (default: task_dir/.fe/runs)
        artifacts_dir: Directory for large artifacts (default: same as runs_dir)
        adapter: Task adapter (uses default benchmark adapter if not provided)
        config_path: YAML file to read the configuration from, instead of
            ``<task_dir>/evolve.yaml``. The Web layer writes the preset it
            merged with the user's patch here, so a run executes exactly the
            configuration the UI showed. A separate file also leaves the task
            directory untouched.
        resume_source: Run directory to copy *before* resuming it, used with
            ``resume_id``. The source is read through SQLite's backup interface
            (so its WAL sidecar is part of the copy, not a discrepancy) and never
            opened for writing: continuing an old run in place would leave nothing
            to go back to if the resume turns out to be wrong.

    Returns:
        Dictionary with run results
    """
    from faultevolve.tasks import create_benchmark_adapter

    output_dir = runs_dir or (task_dir / ".fe" / "runs")
    output_dir.mkdir(parents=True, exist_ok=True)

    evolve_yaml = config_path if config_path is not None else (task_dir / "evolve.yaml")
    config = EvolveConfig.from_yaml(evolve_yaml) if evolve_yaml.exists() else EvolveConfig()
    config = config.with_overrides(
        max_iterations=max_iterations,
        target_score=target_score,
        seed=seed,
    )
    # The public wrapper may explicitly disable a workflow enabled in YAML.
    config.workflow.enabled = workflow_active

    if adapter is None:
        adapter = create_benchmark_adapter(config)
    task_spec = adapter.load_task(task_dir)

    if resume_id:
        exp_id = resume_id
    elif experiment_id is not None:
        # Validated here as well as in the caller: this value becomes a path
        # segment a few lines down.
        exp_id = _validate_experiment_id(experiment_id)
    else:
        exp_id = str(uuid.uuid4())[:8]

    db_dir = output_dir / exp_id
    if resume_id and resume_source is not None:
        # Copy first, then continue the copy. Refuses a destination that already
        # holds a database, so a resume can never overwrite a run by accident.
        # What travels is the run directory it was given: the database through
        # SQLite's backup interface and every artifact beside it. A run that keeps
        # its artifacts in a separate home gets a fresh one here -- the state a
        # resume needs is in the database, and the artifacts are what a run writes.
        source = Path(resume_source)
        if source.resolve() == db_dir.resolve():
            raise ValueError(
                f"--resume-from {source} is the directory this run would write into; "
                "point --runs-dir at a new home so the original stays untouched"
            )
        clone_run_directory(source, db_dir)
    db_dir.mkdir(parents=True, exist_ok=True)
    db_path = db_dir / "fe.db"

    art_dir = (artifacts_dir / exp_id) if artifacts_dir else db_dir
    art_dir.mkdir(parents=True, exist_ok=True)

    store = Store(db_path)

    if llm_client is not None:
        llm = llm_client
    elif mock:
        llm = MockLLM()
    else:
        llm = DashScopeLLM(config)

    engine = EvolutionEngine(
        config=config,
        task_adapter=adapter,
        task_spec=task_spec,
        store=store,
        llm=llm,
        mock=mock,
        task_dir=task_dir,
    )

    experiment_id = engine.initialize(resume_id=resume_id, experiment_id=exp_id)
    assert experiment_id == exp_id, f"ID mismatch: {experiment_id} != {exp_id}"
    engine.artifacts_dir = art_dir
    if (config.workflow.enabled and config.workflow.hierarchical.enabled
            and config.workflow.hierarchical.mode == "per_structure"):
        from faultevolve.structure_tuning import StructureTuner
        engine._structure_tuner = StructureTuner(engine, db_dir / "workflow", art_dir)
        engine._constraints_text += (
            "\n本轮提出新的模型、特征或算法结构。系统会在本地对该候选单独进行参数树搜索，"
            "再用调优后的实测成绩选择下一轮父节点。父节点源码和指标均已包含其调优结果。"
            "请把可调模型参数写成显式数值关键字、参数字典或大写常量，便于自动识别。"
        )

    summary = None
    run_error = None
    try:
        summary = engine.run(max_iterations)
    except Exception as e:
        run_error = e
    finally:
        _write_artifacts(engine, store, experiment_id, art_dir, summary)

    if run_error is not None:
        raise run_error

    programs_dir = art_dir / "programs"
    logs_dir = art_dir / "logs"

    return {
        "experiment_id": experiment_id,
        "status": summary.status if summary else "crashed",
        "iterations_done": summary.iterations_done if summary else engine.metrics.iterations_done,
        "best_score": summary.best_score if summary else 0.0,
        "output_dir": str(art_dir),
        "db_dir": str(db_dir),
        "programs_dir": str(programs_dir),
        "logs_dir": str(logs_dir),
    }


def island_report(store: Store, experiment_id: str) -> dict[str, Any]:
    """Per-island results and exchange counts, projected from the stored rows.

    ``run_summary.json`` is the first file a reader opens, so it has to answer
    "did each island really search on its own, did they exchange anything, and
    what did each one spend" without the reader knowing SQL. Both writers use
    this one projection -- the live run and ``rebuild_run_report`` -- because
    reading it from the database
    instead of in-process counters is what makes a report rebuilt after a crash
    comparable with one written by the process that ran.
    """
    summaries = store.get_summaries_by_experiment(experiment_id)
    deliveries = store.get_deliveries(experiment_id)
    applications = store.get_applications_by_experiment(experiment_id)
    rollup = store.get_cost_rollup(experiment_id)
    return {
        "islands": {
            (state.island_id or "legacy"): {
                "status": state.status.value,
                "profile": state.profile,
                "attempts": state.attempts,
                "valid_evaluations": state.valid_evaluations,
                "invalid_evaluations": state.invalid_evaluations,
                "best_score": state.best_score,
                "stop_reason": state.stop_reason,
            }
            for state in store.get_island_states(experiment_id)
        },
        "exchange": {
            "summaries": len(summaries),
            "by_kind": {
                kind: sum(1 for row in summaries if row.kind == kind)
                for kind in EXCHANGE_KINDS
            },
            "deliveries": len(deliveries),
            "accepted": sum(1 for row in deliveries if row.status == "accepted"),
            "rejected": sum(1 for row in deliveries if row.status == "rejected"),
            "applications": len(applications),
            "evaluated_applications": sum(1 for row in applications if row.evaluation_id),
        },
        "cost": {
            "total_tokens": rollup["total_tokens"],
            "by_island": {
                bucket["island_id"]: {
                    "tokens": bucket["tokens"],
                    "calls": bucket["calls"],
                    "unresolved_calls": bucket["unresolved_calls"],
                    "cached_calls": bucket["cached_calls"],
                    "by_stage": bucket["by_stage"],
                }
                for bucket in rollup["by_island"]
            },
            "shared_tokens": rollup["shared"]["tokens"],
            "unresolved_calls": rollup["unresolved_calls"],
            "cost_usd": rollup["cost_usd"],
            "cost_basis": rollup["cost_basis"],
        },
    }


def export_forest(
    store: Store, experiment_id: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Node]]:
    """Every island's tree, as one node list, one edge list and the nodes themselves.

    A live run used to export only ``engine.tree`` -- one island's handle -- so a
    three-island run wrote a third of its own forest into ``tree.json`` and into
    ``programs/``. Reading the store per island is what the rebuild path already
    did; now both paths project the same forest from the same source.
    """
    island_ids = [
        state.island_id for state in store.get_island_states(experiment_id)
    ] or [""]
    nodes: dict[str, Node] = {}
    export_nodes: list[dict[str, Any]] = []
    export_edges: list[dict[str, Any]] = []
    for island_id in island_ids:
        tree = Tree(experiment_id, store, island_id=island_id)
        tree.load_from_store()
        nodes.update(tree.nodes)
        body = tree.to_export()
        export_nodes.extend(body["nodes"])
        export_edges.extend(body["edges"])
    return export_nodes, export_edges, nodes


def rebuild_run_report(
    store: Store,
    experiment_id: str,
    art_dir: Path,
) -> dict[str, Any]:
    """Write a run's report out of the database alone.

    A process can die after its last evaluation and before its artifacts were
    written. The evaluations are in the database, so the report is a projection of
    them: this path opens nothing that costs money -- no evaluator subprocess, no
    LLM, no new node -- and it re-scores nothing, because a node that already has an
    evaluation keeps that number and no other source is consulted.

    Returns:
        The summary dictionary that was written
    """
    experiment = store.get_experiment(experiment_id)
    if experiment is None:
        raise ValueError(f"experiment {experiment_id} not found")

    export_nodes, export_edges, nodes = export_forest(store, experiment_id)

    scored = [
        node
        for node in nodes.values()
        if node.evidence.evaluation is not None and node.evidence.evaluation.validity >= 1.0
    ]
    best = max(scored, key=lambda node: node.get_score(), default=None)
    rollup = store.get_cost_rollup(experiment_id)

    summary = {
        "experiment_id": experiment_id,
        "status": experiment.status,
        "iterations_done": experiment.iterations_done,
        "best_score": best.get_score() if best else 0.0,
        "best_node_id": best.id if best else None,
        "valid_count": len(scored),
        "node_count": len(nodes),
        "total_tokens": rollup["total_tokens"],
        "cost": rollup,
        **island_report(store, experiment_id),
        # Says out loud that these numbers were read back rather than measured by
        # the process that wrote them, so a rebuilt report is never mistaken for a
        # live run's own accounting.
        "rebuilt_from_store": True,
    }
    # The live write includes the ledger view when the autotune ledger is on; the
    # rebuild takes it from the same rows, so both transcripts describe the whole
    # run instead of disagreeing about which process was running.
    ledger_rows = store.list_cost_records(experiment_id)
    if ledger_rows:
        ledger_view = CostLedger()
        ledger_view.restore_rows(ledger_rows)
        summary["cost_ledger_totals"] = ledger_view.totals().to_dict()

    art_dir.mkdir(parents=True, exist_ok=True)
    (art_dir / "run_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (art_dir / "tree.json").write_text(
        json.dumps(
            {"experiment_id": experiment_id, "nodes": export_nodes, "edges": export_edges},
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    events = store.get_events(experiment_id)
    with (art_dir / "events.jsonl").open("w", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event.model_dump(), ensure_ascii=False) + "\n")

    programs_dir = art_dir / "programs"
    programs_dir.mkdir(parents=True, exist_ok=True)
    logs_dir = art_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    for node_id, node in nodes.items():
        (programs_dir / f"{node_id}.py").write_text(node.artifact.code, encoding="utf-8")
        evaluation = node.evidence.evaluation
        if evaluation is not None and evaluation.error_info:
            (logs_dir / f"{node_id}.log").write_text(evaluation.error_info, encoding="utf-8")
    return summary


def _write_artifacts(
    engine: EvolutionEngine,
    store: Store,
    experiment_id: str,
    art_dir: Path,
    summary: RunSummary | None,
) -> None:
    """Write all artifacts to disk.

    Always called in finally block to ensure artifacts are never left empty,
    even if the run crashes.

    Args:
        engine: Evolution engine with tree data
        store: Database store
        experiment_id: Experiment ID
        art_dir: Artifacts directory
        summary: Run summary (may be None if run crashed)
    """
    if summary is not None:
        summary_path = art_dir / "run_summary.json"
        summary_dict = summary.model_dump()
        summary_dict.update(island_report(store, experiment_id))
        if engine._cost_ledger is not None and engine.config.autotune.ledger.enabled:
            summary_dict["cost_ledger_totals"] = engine._cost_ledger.totals().to_dict()
        with summary_path.open("w", encoding="utf-8") as f:
            json.dump(summary_dict, f, indent=2, ensure_ascii=False)
    else:
        best_id, best_score = engine._best_across_islands() if engine.tree else (None, 0.0)
        initial_score = engine._initial_score
        crash_summary = {
            "experiment_id": experiment_id,
            "status": "crashed",
            "iterations_done": engine.metrics.iterations_done,
            "best_score": best_score,
            "best_node_id": best_id,
            "initial_score": initial_score,
            "valid_rate": engine.metrics.valid_rate,
            "total_tokens": engine.metrics.total_tokens,
            "stop_reason": "crash",
            **island_report(store, experiment_id),
        }
        summary_path = art_dir / "run_summary.json"
        with summary_path.open("w", encoding="utf-8") as f:
            json.dump(crash_summary, f, indent=2, ensure_ascii=False)

    forest_nodes: dict[str, Node] = {}
    if engine.tree is not None:
        export_nodes, export_edges, forest_nodes = export_forest(store, experiment_id)
        tree_path = art_dir / "tree.json"
        with tree_path.open("w", encoding="utf-8") as f:
            json.dump(
                {
                    "experiment_id": experiment_id,
                    "nodes": export_nodes,
                    "edges": export_edges,
                },
                f,
                indent=2,
                ensure_ascii=False,
            )

    events = store.get_events(experiment_id)
    events_path = art_dir / "events.jsonl"
    with events_path.open("w", encoding="utf-8") as f:
        for event in events:
            f.write(json.dumps(event.model_dump(), ensure_ascii=False) + "\n")

    programs_dir = art_dir / "programs"
    programs_dir.mkdir(parents=True, exist_ok=True)
    logs_dir = art_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    if engine._discovery is not None:
        try:
            engine.write_discovery_artifacts(art_dir)
        except Exception:
            pass
    try:
        engine.write_tournament_artifacts(art_dir)
    except Exception:
        pass

    if engine.tree is not None:
        for node_id, node in forest_nodes.items():
            program_path = programs_dir / f"{node_id}.py"
            program_path.write_text(node.artifact.code, encoding="utf-8")

            if node.evidence.evaluation and node.evidence.evaluation.error_info:
                log_path = logs_dir / f"{node_id}.log"
                log_path.write_text(node.evidence.evaluation.error_info, encoding="utf-8")
