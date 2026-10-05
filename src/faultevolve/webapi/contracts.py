"""Stable response/request contract between the FaultEvolve engine and the Web UI.

Rules enforced by this module (see docs/plans/FRONTEND_IMPLEMENTATION_TODO.md §4):

1. The front-end never touches internal engine objects. Everything it sees is a
   DTO declared here, converted by the service layer.
2. Every field has an explicit type. The only untyped mapping allowed is an
   event payload, whose shape is genuinely per-event-type.
3. A value the artifact does not contain is ``None``. ``0`` always means zero,
   never "not recorded".
4. Responses carry ``contract_version``.

``NodeStatus`` / ``HypothesisStatus`` / ``OperatorType`` are re-exported rather
than redeclared: they are the engine vocabulary and the Web UI must stay
verbatim in sync with it.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from faultevolve.common.schemas import (
    HypothesisStatus,
    NodeStatus,
    OperatorType,
)

__all__ = [
    "CONTRACT_VERSION",
    "ArtifactState",
    "ControlAction",
    "DeploymentMode",
    "HypothesisStatus",
    "NodeStatus",
    "OperatorType",
    "RunDataState",
    "TreeEdgeKind",
    "ApiErrorResponse",
    "AppendRoundsRequest",
    "ArtifactListResponse",
    "ArtifactResponse",
    "ContractWarning",
    "DeploymentModeAvailability",
    "DiscoveryResponse",
    "EventPageResponse",
    "EventResponse",
    "HealthResponse",
    "InsightResponse",
    "InsightsResponse",
    "KnowledgeCardResponse",
    "KnowledgeCardStatResponse",
    "KnowledgeSourceResponse",
    "MetaResponse",
    "QwenConfigRequest",
    "QwenConfigResponse",
    "NodeArtifactResponse",
    "NodeDetailResponse",
    "NodeEvaluationResponse",
    "PathProbeRequest",
    "PresetFieldSource",
    "PresetListResponse",
    "PresetResponse",
    "RunBudgetResponse",
    "RunControlRequest",
    "RunControlResponse",
    "RunCostResponse",
    "RunCreateRequest",
    "RunCreateResponse",
    "RunDetailResponse",
    "RunJudgeResponse",
    "RunKnowledgeResponse",
    "RunLiveResponse",
    "RunOperatorResponse",
    "RunOutcomeResponse",
    "RunRepairResponse",
    "RunSummaryResponse",
    "ScorePointResponse",
    "ScoreboardEntryResponse",
    "ServerProfileListResponse",
    "ServerProfileRequest",
    "ServerProfileResponse",
    "ServerProbeResponse",
    "PathProbeResponse",
    "ReportFileResponse",
    "ReportManifestResponse",
    "TaskCardMetrics",
    "TaskDatasetCardResponse",
    "TaskDetailResponse",
    "TaskReadinessResponse",
    "TaskSummaryResponse",
    "TreeEdgeDTO",
    "TreeNodeDTO",
    "TreeResponse",
]

#: Bumped per docs/plans/FRONTEND_IMPLEMENTATION_TODO.md §13.4.
#: new optional field -> minor, new required field / rename -> major.
#: 1.1.0: phase 4 added MetaResponse's task/demo/preset fields and the
#: task-card, server-list and preset DTOs -- all additive.
#: 1.6.0: phase 7 added the run lifecycle surface (RunCreateResponse,
#: RunLiveResponse, AppendRoundsRequest) -- additive, no DTO changed shape.
#: 1.7.0: RunLiveResponse gained ``log_tail``/``log_tail_truncated``. Additive,
#: but it is the only channel that can explain a dead process: the log artifact
#: is listed yet not downloadable, so without this the UI has no diagnosis.
#: 1.8.0: RunSummaryResponse.task_id and MetaResponse.qwen_configured. Both
#: optional. task_id is the task directory name, never a path. qwen_configured
#: is a boolean presence check and never carries the key.
#: 1.9.0: MetaResponse.qwen_reachable. Optional. True only after GET /models
#: on the default Qwen base URL returns 200. None when no key is configured,
#: so the UI does not treat "not probed" as a failed call. The key is absent.
#: 1.10.0: KnowledgeCardResponse gains optional title, category, priority and
#: sources. claim / source_kind / source_detail / conditions stay optional and
#: are filled only when the run's registered task has a matching catalog card.
#: 1.11.0: KnowledgeSourceResponse.takeaway. Optional. Copied from
#: sources.yaml when that entry has one; never invented from card stats.
CONTRACT_VERSION = "1.11.0"


# --------------------------------------------------------------------------
# enums
# --------------------------------------------------------------------------


class DeploymentMode(str, Enum):
    """How the engine gets executed. P0 ships cloud-only modes."""

    LOCAL_CLOUD = "local_cloud"
    SSH_CLOUD = "ssh_cloud"
    LOCAL_DESKTOP = "local_desktop"


class RunDataState(str, Enum):
    """Which artifacts back a run directory (TODO §2.4).

    Kept separate from the run's own status: a run can be ``finished`` and still
    be ``live``-only if its ``run_summary.json`` was never written.
    """

    COMPLETE = "complete"
    LIVE = "live"
    UNREADABLE = "unreadable"


class ArtifactState(str, Enum):
    """Availability of one artifact inside a run directory."""

    AVAILABLE = "available"
    MISSING = "missing"
    INVALID = "invalid"


class TreeEdgeKind(str, Enum):
    """Why two tree nodes are connected (TODO §5.1)."""

    PARENT = "parent"
    CROSSOVER_SECOND_PARENT = "crossover_second_parent"
    REPAIR = "repair"


class ControlAction(str, Enum):
    """Lifecycle actions the API accepts.

    ``PAUSE``/``RESUME`` are declared so the API can answer with a stable
    ``not_supported`` error instead of pretending (TODO §7.4). The engine has no
    safe pause point today.
    """

    CANCEL = "cancel"
    PAUSE = "pause"
    RESUME = "resume"


# --------------------------------------------------------------------------
# shared building blocks
# --------------------------------------------------------------------------


class ContractModel(BaseModel):
    """Base for every DTO: strict fields, so drift is a hard failure."""

    model_config = ConfigDict(extra="forbid")


class ContractWarning(ContractModel):
    """A field the current version could not fill.

    The UI renders these as "当前版本未记录" instead of inventing a value.
    """

    field: str
    reason: str


class DeploymentModeAvailability(ContractModel):
    """Whether one deployment mode is usable in this build."""

    mode: DeploymentMode
    available: bool
    supported_transports: list[DeploymentMode]
    detail: str = ""


# --------------------------------------------------------------------------
# meta / health
# --------------------------------------------------------------------------


class HealthResponse(ContractModel):
    """Liveness probe. Must never leak paths, keys or environment details."""

    status: str
    contract_version: str


class QwenConfigRequest(ContractModel):
    """Runtime Qwen endpoint configuration. Secrets remain environment-only."""

    base_url: str


class QwenConfigResponse(ContractModel):
    """Safe Qwen configuration status for the Web UI."""

    base_url: str
    configured: bool
    reachable: bool | None = None


class MetaResponse(ContractModel):
    """Static capability description consumed once at UI start-up."""

    contract_version: str
    engine_version: str
    engine_commit: str | None = None
    deployment_modes: list[DeploymentModeAvailability]
    default_deployment_mode: DeploymentMode
    nav_modules: list[str]
    stream_transport: str
    process_control_enabled: bool
    auth_required: bool

    # --- phase 4 additions (all defaulted: additive, minor bump) -----------
    #: Run ids the deployment considers demo/replay data. The overview page
    #: uses the first one for "open the full replay" and badges them as
    #: demo data (PRD 2.3).
    demo_run_ids: list[str] = Field(default_factory=list)
    #: Whether ``WebSettings.task_roots`` resolves to at least one directory.
    #: ``False`` means the UI must say "no task directory configured" rather
    #: than show an empty list that looks like "no tasks exist".
    task_catalog_available: bool = False
    #: Preset names this build defines. The UI never hard-codes them.
    preset_names: list[str] = Field(default_factory=list)
    #: Whether server profiles can be stored (``server_profile_store`` set).
    server_profiles_enabled: bool = False

    # --- phase 7 additions (additive, minor bump) --------------------------
    #: Whether the run registry has a path. ``process_control_enabled`` alone is
    #: not enough to launch: without a registry a started process could not be
    #: recorded, so the UI checks both before enabling the launch button.
    run_registry_configured: bool = False
    #: True only when ``DASHSCOPE_API_KEY`` is set to a non-empty value.
    #: The value itself is never copied into this response.
    qwen_configured: bool = False
    #: Whether that key was accepted by ``GET {base}/models``.
    #: ``None`` when ``qwen_configured`` is false: no request was made.
    qwen_reachable: bool | None = None


# --------------------------------------------------------------------------
# tasks
# --------------------------------------------------------------------------


class TaskSummaryResponse(ContractModel):
    """One entry of the task listing."""

    task_id: str
    display_name: str
    adapter: str
    problem_summary: str = ""
    has_evaluator: bool
    has_init: bool
    is_stub: bool
    doc_path: str | None = None


class TaskDetailResponse(ContractModel):
    """A task directory worth of facts the intake form needs."""

    task_id: str
    display_name: str
    adapter: str
    problem_md: str
    prompt_md: str
    required_files: list[str]
    missing_files: list[str]
    candidate_files: list[str]
    data_dirs: list[str]
    knowledge_enabled: bool
    config_schema_available: bool


class TaskReadinessResponse(ContractModel):
    """Result of the pre-flight check for one intake card."""

    task_id: str
    ready: bool
    checks: list[ContractWarning]
    adapter: str | None = None
    resolved_path: str | None = None


class TaskCardMetrics(ContractModel):
    """Score contract of one dataset, as shown on its overview card.

    ``score_source`` exists so the UI can never invent a number: a score is
    only rendered when it came from the evaluator or from a finished baseline
    run. PRD 7.3 forbids showing an assumed score for an untested ``init.py``.
    """

    primary_metric: str = ""
    target_direction: str = "higher"
    target_score: float | None = None
    initial_score: float | None = None
    score_source: str = "unavailable"


class TaskDatasetCardResponse(ContractModel):
    """One overview card (PRD 7.1 item 3 / PRD 7.7).

    Aggregates what the overview page needs about a dataset so the front-end
    does not have to join ``/api/tasks`` with ``/api/runs`` itself.
    """

    task_id: str
    display_name: str
    device_type: str = ""
    summary: str = ""
    adapter: str
    is_stub: bool
    doc_path: str | None = None
    metrics: TaskCardMetrics = Field(default_factory=TaskCardMetrics)
    data_ready: bool = False
    data_missing: list[str] = Field(default_factory=list)
    evaluator_ready: bool = False
    init_ready: bool = False
    knowledge_card_count: int | None = None
    last_run_id: str | None = None
    last_best_score: float | None = None
    #: Why this dataset cannot be started yet. ``None`` means nothing blocks it.
    blocked_reason: str | None = None


# --------------------------------------------------------------------------
# servers
# --------------------------------------------------------------------------


class ServerProfileRequest(ContractModel):
    """Create/update a cloud execution target.

    Secrets are never part of the request: the client sends a *reference*
    (``private_key_ref``) and the server resolves it locally.
    """

    display_name: str
    mode: DeploymentMode
    host: str | None = None
    port: int | None = Field(default=None, ge=1, le=65535)
    user: str | None = None
    private_key_ref: str | None = None
    repo_dir: str | None = None
    data_dir: str | None = None
    runs_dir: str | None = None
    artifacts_dir: str | None = None
    logs_dir: str | None = None
    python_executable: str | None = None
    conda_env: str | None = None
    cpu_limit: int | None = Field(default=None, ge=1)
    memory_gb: float | None = Field(default=None, gt=0)
    gpu_count: int | None = Field(default=None, ge=0)
    gpu_model: str | None = None
    gpu_devices: list[str] = Field(default_factory=list)
    max_concurrency: int | None = Field(default=None, ge=1)
    timeout_s: int | None = Field(default=None, gt=0)
    notes: str = ""


class ServerProfileResponse(ContractModel):
    """A stored profile, with every secret replaced by a masked marker."""

    profile_id: str
    display_name: str
    mode: DeploymentMode
    host: str | None = None
    port: int | None = None
    user: str | None = None
    has_private_key: bool
    secret_masked: bool
    repo_dir: str | None = None
    data_dir: str | None = None
    runs_dir: str | None = None
    artifacts_dir: str | None = None
    logs_dir: str | None = None
    cpu_limit: int | None = None
    memory_gb: float | None = None
    gpu_count: int | None = None
    gpu_devices: list[str] = Field(default_factory=list)
    gpu_model: str | None = None
    python_executable: str | None = None
    conda_env: str | None = None
    max_concurrency: int | None = None
    timeout_s: int | None = None
    notes: str = ""


class PathProbeResponse(ContractModel):
    """Result of checking one directory on an execution target."""

    path: str
    exists: bool
    is_directory: bool
    writable: bool | None = None
    detail: str = ""


class ServerProbeResponse(ContractModel):
    """Reachability + environment report for one execution target."""

    profile_id: str
    mode: DeploymentMode
    reachable: bool
    latency_ms: int | None = None
    engine_installed: bool | None = None
    engine_version: str | None = None
    python_version: str | None = None
    gpu_summary: str | None = None
    paths: list[PathProbeResponse] = Field(default_factory=list)
    llm_key_present: bool | None = None
    detail: str = ""


class PathProbeRequest(ContractModel):
    """Body of a directory check on an execution target.

    The path is checked against ``WebSettings``' allow-list before anything is
    stat'ed, so ``..`` traversal is rejected rather than normalised away.
    """

    path: str


class ServerProfileListResponse(ContractModel):
    """Every stored execution target, plus which one the UI should preselect."""

    profiles: list[ServerProfileResponse] = Field(default_factory=list)
    default_profile_id: str | None = None
    #: Whether the SSH transport is usable in this build. Mirrors
    #: ``/api/meta``'s ``ssh_cloud`` availability so the UI can disable the
    #: SSH fields instead of failing on submit.
    ssh_available: bool = False


# --------------------------------------------------------------------------
# evolution presets
# --------------------------------------------------------------------------


class PresetFieldSource(ContractModel):
    """Where one field of a preset came from (TODO 4.6).

    Lets the UI explain "this number is the preset default" versus "this came
    from your patch", without the front-end re-deriving the merge.
    """

    field: str
    value: Any = None
    #: ``preset_default`` | ``task_required`` | ``server_profile`` | ``user_patch``
    source: str


class PresetResponse(ContractModel):
    """A complete, already-validated ``EvolveConfig`` for one preset.

    ``config`` is the full config dump, not a patch: the front-end sends back
    only a patch over this, and the server merges and re-validates.
    """

    name: str
    display_name_zh: str
    summary_zh: str = ""
    config: dict[str, Any] = Field(default_factory=dict)
    sources: list[PresetFieldSource] = Field(default_factory=list)


class PresetListResponse(ContractModel):
    """All presets, in the order the UI should show them."""

    presets: list[PresetResponse] = Field(default_factory=list)


# --------------------------------------------------------------------------
# runs
# --------------------------------------------------------------------------


class RunCreateRequest(ContractModel):
    """Start one evolution run.

    ``config_patch`` is a *patch* on top of a server-built preset; the server
    merges it and re-validates against ``EvolveConfig``.
    """

    task_id: str
    server_profile_id: str
    preset: str
    config_patch: dict[str, Any] = Field(default_factory=dict)
    mock_llm: bool = False
    seed: int | None = None
    resume_run_id: str | None = None


class RunSummaryResponse(ContractModel):
    """One row of the run listing (TODO §2.4)."""

    run_id: str
    data_state: RunDataState
    status: str | None = None
    iterations_done: int | None = None
    best_score: float | None = None
    improvement: float | None = None
    stop_reason: str | None = None
    created_at: str | None = None
    finished_at: str | None = None
    #: Task directory name when this run was started through the Web API and
    #: is still in the run registry. Absent for replay-only fixtures. Never a path.
    task_id: str | None = None
    warnings: list[ContractWarning] = Field(default_factory=list)


class RunBudgetResponse(ContractModel):
    """Token and time accounting (TODO §5.7). All values from RunSummary."""

    total_tokens: int | None = None
    generate_tokens: int | None = None
    reflect_tokens: int | None = None
    knowledge_tokens: int | None = None
    repair_tokens: int | None = None
    discovery_tokens: int | None = None
    tournament_tokens: int | None = None
    crossover_tokens: int | None = None
    self_fix_tokens: int | None = None
    knowledge_token_share: float | None = None
    discovery_token_share: float | None = None
    wall_time_s: float | None = None
    total_eval_time_s: float | None = None
    total_llm_latency_ms: int | None = None
    smoke_time_s_total: float | None = None
    avg_smoke_time_s: float | None = None
    stage_cap_hits: dict[str, int] = Field(default_factory=dict)
    budget_stop_reason: str | None = None
    tokens_per_score_gain: float | None = None
    tokens_per_ros_point: float | None = None
    expand_skipped_budget: int | None = None
    elite_archive_sizes: dict[str, int] = Field(default_factory=dict)


class RunOutcomeResponse(ContractModel):
    """Headline numbers of a run. These come from the evaluator, never the UI."""

    status: str | None = None
    iterations_done: int | None = None
    best_score: float | None = None
    best_node_id: str | None = None
    initial_score: float | None = None
    improvement: float | None = None
    valid_rate: float | None = None
    stop_reason: str | None = None
    rounds_to_target: int | None = None
    time_to_target_s: float | None = None
    tokens_to_target: int | None = None
    iteration_events: int | None = None


class RunRepairResponse(ContractModel):
    """Repair / pre-check / smoke accounting (TODO §5.5)."""

    repair_attempts: int | None = None
    repair_successes: int | None = None
    repair_iterations: int | None = None
    precheck_fixes: int | None = None
    adapter_errors: int | None = None
    perf_rejections: int | None = None
    smoke_tests: int | None = None
    smoke_failures: int | None = None
    smoke_fixes: int | None = None


class KnowledgeCardStatResponse(ContractModel):
    """Per-card adoption statistics, straight from the card_stats table."""

    card_id: str
    n: int | None = None
    sum_delta: float | None = None
    mean_delta: float | None = None
    refuted_count: int | None = None
    invalid_count: int | None = None


class RunKnowledgeResponse(ContractModel):
    """Literature knowledge-package usage."""

    cards_offered: int | None = None
    cards_adopted: int | None = None
    cards_adopted_valid: int | None = None
    card_adoption_rate: float | None = None
    card_stats: list[KnowledgeCardStatResponse] = Field(default_factory=list)


class RunDiscoveryResponse(ContractModel):
    """Knowledge-discovery, mechanism and tournament counters.

    Kept apart from :class:`RunJudgeResponse` and from the evaluator outcome:
    none of these are evolution scores.
    """

    discovery_rounds: int | None = None
    discovery_rounds_skipped: int | None = None
    claims_proposed: int | None = None
    claims_tested: int | None = None
    claims_sandbox_failed: int | None = None
    claims_confirmed: int | None = None
    claims_revised: int | None = None
    claims_discovered: int | None = None
    claims_refuted: int | None = None
    claims_undetermined: int | None = None
    discovered_cards_count: int | None = None
    discovered_cards_offered: int | None = None
    discovered_cards_adopted: int | None = None
    discovered_card_adoption_rate: float | None = None
    discovered_card_mean_delta: float | None = None
    literature_card_mean_delta: float | None = None
    score_delta_after_discovery: float | None = None
    neg_control_false_positives: int | None = None
    neg_control_fpr: float | None = None
    planted_recovery_rate: dict[str, float] = Field(default_factory=dict)
    mechanisms_proposed: int | None = None
    mechanisms_established: int | None = None
    mechanisms_refuted: int | None = None
    mechanism_patches: int | None = None
    mechanism_cards_count: int | None = None
    matches_played: int | None = None
    decisive_matches: int | None = None
    underpowered_draws: int | None = None
    certificates_issued: int | None = None
    tournament_rounds: int | None = None
    planted_mechanism_recovered: float | None = None
    llm_vs_data_kendall_tau: float | None = None
    shuffled_env_false_pass: float | None = None
    min_detectable_effect: float | None = None


class RunJudgeResponse(ContractModel):
    """Qwen / Jev and error-profiling cost.

    Deliberately isolated from :class:`RunOutcomeResponse`: the acceptance
    criteria require judge output to be visually separated from evaluator scores.
    """

    jev_calls: int | None = None
    jev_errors: int | None = None
    jev_fail_open: int | None = None
    jev_tokens: int | None = None
    jev_prompt_tokens: int | None = None
    jev_completion_tokens: int | None = None
    jev_latency_ms: int | None = None
    jev_disabled_reason: str | None = None
    jev_prior_active: bool | None = None
    candidates_screened: int | None = None
    evaluations_saved: int | None = None
    eval_time_saved_est_s: float | None = None
    screen_audited: int | None = None
    screen_audit_bad: int | None = None
    screen_shadow: int | None = None
    screening_precision: float | None = None
    analysis_calls: int | None = None
    analysis_failures: int | None = None
    analysis_time_s: float | None = None
    analysis_nonempty_rate: float | None = None


class RunOperatorResponse(ContractModel):
    """Operator mix, bandit state and crossover counters."""

    operator_counts: dict[str, int] = Field(default_factory=dict)
    operator_valid_rate: dict[str, float] = Field(default_factory=dict)
    operator_mean_delta: dict[str, float] = Field(default_factory=dict)
    operator_tokens: dict[str, int] = Field(default_factory=dict)
    operator_posteriors: dict[str, dict[str, float]] = Field(default_factory=dict)
    value_mode: str | None = None
    bandit_active: bool | None = None
    generative_valid_rate: float | None = None
    crossover_count: int | None = None
    crossover_valid_rate: float | None = None
    crossover_mean_delta: float | None = None
    crossover_best_gain: float | None = None


class RunCostResponse(ContractModel):
    """Grouped cost/outcome view used by the results page."""

    budget: RunBudgetResponse
    judge: RunJudgeResponse


class RunDetailResponse(ContractModel):
    """Everything the run-level pages read out of one run directory.

    Each group is ``None`` when the artifact for it is unavailable, so the UI can
    distinguish "read but zero" from "cannot be read".
    """

    contract_version: str
    run_id: str
    data_state: RunDataState
    outcome: RunOutcomeResponse | None = None
    budget: RunBudgetResponse | None = None
    repair: RunRepairResponse | None = None
    knowledge: RunKnowledgeResponse | None = None
    discovery: RunDiscoveryResponse | None = None
    judge: RunJudgeResponse | None = None
    operators: RunOperatorResponse | None = None
    artifact_states: dict[str, ArtifactState] = Field(default_factory=dict)
    warnings: list[ContractWarning] = Field(default_factory=list)


class RunControlRequest(ContractModel):
    """Pause / resume / cancel request."""

    action: ControlAction


class RunControlResponse(ContractModel):
    """Current lifecycle state after (or instead of) a control action."""

    run_id: str
    status: str | None = None
    action: ControlAction
    applied: bool
    detail: str = ""


class RunCreateResponse(ContractModel):
    """A run the service accepted and started (TODO 7.3 step 9 -> HTTP 202).

    No filesystem path appears here, on purpose: the UI addresses a run by id
    and asks the server for whatever else it needs. ``execution_backend`` is the
    transport that actually ran (``local_cloud`` / ``ssh_cloud``), not an echo
    of the request.
    """

    run_id: str
    status: str
    execution_backend: str
    task_id: str
    created_at: str
    resumed_from: str | None = None
    detail: str = ""


class RunLiveResponse(ContractModel):
    """Live state of a run this service started.

    Deliberately *not* the replay view. ``RunDetailResponse`` describes
    artifacts on disk; this describes a process. A run can be live with no
    artifacts written yet, and a run directory can exist that this service never
    started -- hence ``registered``.
    """

    contract_version: str
    run_id: str
    #: Whether the registry holds a row for this id at all. ``False`` means the
    #: replay view may still work while the lifecycle controls do not apply.
    registered: bool
    status: str | None = None
    execution_backend: str | None = None
    server_profile_id: str | None = None
    pid: int | None = None
    #: Whether the recorded process is alive *right now*. ``None`` when it
    #: cannot be determined -- a remote handle has no local pid to inspect, and
    #: guessing would be worse than admitting the gap.
    process_alive: bool | None = None
    created_at: str | None = None
    finished_at: str | None = None
    exit_code: int | None = None
    resumed_from: str | None = None
    detail: str = ""
    #: Artifact ids (logical names the download route accepts), never host
    #: paths -- PRD 22.2 rule 3.
    log_artifacts: list[str] = Field(default_factory=list)
    #: Sanitized tail of the captured log. The log *is* advertised as an
    #: artifact but is deliberately **not downloadable** (it can carry host
    #: paths), so this is the only channel through which the UI can answer "why
    #: did my run die?". Paths and secrets are already redacted by the server;
    #: clients must not un-redact or re-resolve anything in here.
    log_tail: str | None = None
    #: Whether lines or characters were dropped from ``log_tail``. Stated rather
    #: than implied, so a caller never reads a partial log as a whole one.
    log_tail_truncated: bool = False


class AppendRoundsRequest(ContractModel):
    """Ask a run to evolve further (PRD §16.1).

    ``additional_iterations`` is a *delta*, not a new total. The original
    completion summary is never rewritten, so "this run did N rounds, then M
    more" stays auditable after the fact.
    """

    additional_iterations: int = Field(gt=0, le=500)


# --------------------------------------------------------------------------
# tree / nodes
# --------------------------------------------------------------------------


class TreeNodeDTO(ContractModel):
    """One node of the evolution tree.

    ``score`` is ``None`` when the node was never evaluated. The UI must render
    "未评分", never ``0``. Parent relationships are carried here (joined from the
    edges) because ``tree.json`` only stores them as a separate edge list.
    """

    id: str
    parent_id: str | None = None
    second_parent_ids: list[str] = Field(default_factory=list)
    branch_id: str
    depth: int
    operator: OperatorType
    score: float | None = None
    delta_score: float | None = None
    noise_delta: float | None = None
    #: Server-side classification of the delta against the noise band, computed
    #: by the same function that fills ``ScorePointResponse.within_noise_band``
    #: so a node and its score point cannot disagree. ``None`` when either value
    #: is missing -- the UI must then say "无法判断", not guess.
    within_noise_band: bool | None = None
    status: NodeStatus
    hypothesis_status: HypothesisStatus
    intent: str = ""
    visit_count: int | None = None
    adopted_card_ids: list[str] = Field(default_factory=list)
    #: Knowledge cards this node's *branch* had been offered, from
    #: ``branch_offered_cards`` (deduplicated, ordered by offer iteration).
    #: **Not** a superset of ``adopted_card_ids``: a card injected from the
    #: knowledge library was never "offered" per round, and the committed demo
    #: run adopts ``FE01`` this way. The UI must present the two lists side by
    #: side, never as "N of M". The cross-branch propagation story belongs to
    #: the discovery page.
    offered_card_ids: list[str] = Field(default_factory=list)
    insight_ids: list[str] = Field(default_factory=list)
    repair_parent_id: str | None = None
    repair_count: int | None = None
    repair_attempted: bool | None = None
    repair_exhausted: bool | None = None
    error_class: str | None = None
    is_best: bool = False
    is_on_best_path: bool = False


class TreeEdgeDTO(ContractModel):
    """One connection between tree nodes."""

    source: str
    target: str
    kind: TreeEdgeKind


class TreeResponse(ContractModel):
    """Whole-tree payload for React Flow."""

    contract_version: str
    run_id: str
    data_state: RunDataState
    nodes: list[TreeNodeDTO]
    edges: list[TreeEdgeDTO]
    best_node_id: str | None = None
    best_path: list[str] = Field(default_factory=list)
    warnings: list[ContractWarning] = Field(default_factory=list)


class NodeArtifactResponse(ContractModel):
    """Read-only node program."""

    node_id: str
    code: str | None = None
    intent: str = ""
    hypothesis: str = ""
    state: ArtifactState


class NodeEvaluationResponse(ContractModel):
    """Evaluator output for one node.

    ``metric`` is per-task and therefore a free mapping; the surrounding numbers
    are typed so the UI can render "未记录" correctly.
    """

    node_id: str
    validity: float | None = None
    combined_score: float | None = None
    cost_time: float | None = None
    error_info: str | None = None
    delta_score: float | None = None
    noise_delta: float | None = None
    metric: dict[str, Any] = Field(default_factory=dict)


class NodeDetailResponse(ContractModel):
    """Node detail tabs (TODO §5.3)."""

    contract_version: str
    run_id: str
    node: TreeNodeDTO
    artifact: NodeArtifactResponse | None = None
    evaluation: NodeEvaluationResponse | None = None
    insights: list[str] = Field(default_factory=list)
    adopted_card_ids: list[str] = Field(default_factory=list)
    log_state: ArtifactState = ArtifactState.MISSING
    log_excerpt: str | None = None
    event_ids: list[int] = Field(default_factory=list)
    llm_call_count: int | None = None
    llm_tokens: int | None = None
    #: Unified diff against the primary parent's program. Computed from two
    #: stored programs -- never invented. ``None`` when the node has no parent
    #: or either program is unavailable; a warning says which.
    code_diff: str | None = None
    code_diff_truncated: bool = False
    warnings: list[ContractWarning] = Field(default_factory=list)


# --------------------------------------------------------------------------
# events / scores
# --------------------------------------------------------------------------


class EventResponse(ContractModel):
    """One timeline event.

    ``payload`` stays a free mapping on purpose: every event type has its own
    shape and TODO §13.4 requires unknown types to render generically.
    """

    id: int | None = None
    run_id: str
    type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    ts: str = ""
    is_known_type: bool = True


class EventPageResponse(ContractModel):
    """Incremental event page for polling / SSE catch-up."""

    contract_version: str
    run_id: str
    events: list[EventResponse]
    last_event_id: int | None = None
    has_more: bool = False
    data_state: RunDataState
    #: Carries the parse warnings (lines skipped, jsonl/database mismatch).
    #: Without this a partially written log would look like a shorter run.
    warnings: list[ContractWarning] = Field(default_factory=list)


class ScorePointResponse(ContractModel):
    """One point on the score timeline. Source is always the evaluator record."""

    iteration: int | None = None
    node_id: str
    score: float | None = None
    delta_score: float | None = None
    noise_delta: float | None = None
    within_noise_band: bool | None = None
    operator: OperatorType | None = None
    ts: str | None = None


class ScoreboardEntryResponse(ContractModel):
    """Leaderboard row (TODO §2.5)."""

    rank: int
    node_id: str
    score: float | None = None
    operator: OperatorType | None = None
    depth: int | None = None
    is_best: bool = False


# --------------------------------------------------------------------------
# knowledge / discovery
# --------------------------------------------------------------------------


class KnowledgeSourceResponse(ContractModel):
    """One bibliography entry cited by a knowledge card.

    ``url`` is set only for http(s) links copied from the task's
    ``knowledge/sources.yaml``. Anything else stays ``None`` so the UI cannot
    turn an unknown string into a navigation.
    """

    source_id: str
    title: str | None = None
    url: str | None = None
    #: Evidence summary from ``sources.yaml`` ``takeaway``. Absent stays ``None``.
    takeaway: str | None = None


class KnowledgeCardResponse(ContractModel):
    """One knowledge card plus how the run actually used it.

    ``local_label`` is a UI-only marker and must be displayed together with the
    note that it does not affect the run.

    Prose (``title``, ``category``, ``claim``, ``source_kind``, ``conditions``,
    ``priority``, ``sources``) is copied from the task knowledge catalog when
    the run registry names that task and the card id matches. A run directory
    still does not store the prose. Unmatched cards keep these fields empty
    rather than receiving invented text. ``priority`` is the catalog's 1–5
    rank, not a value derived from ``mean_delta``.
    """

    card_id: str
    title: str | None = None
    category: str | None = None
    source_kind: str | None = None
    source_detail: str | None = None
    claim: str | None = None
    conditions: str | None = None
    priority: int | None = None
    sources: list[KnowledgeSourceResponse] = Field(default_factory=list)
    offered_count: int | None = None
    adopted_count: int | None = None
    refuted_count: int | None = None
    invalid_count: int | None = None
    mean_delta: float | None = None
    adopted_iterations: list[int] = Field(default_factory=list)
    adopted_node_ids: list[str] = Field(default_factory=list)
    local_label: str | None = None
    affects_run: bool = False


class DiscoveryResponse(ContractModel):
    """Artifacts of the knowledge-discovery pipeline (TODO §6.2 / §6.3).

    ``phenomena`` / ``preregistration`` / ``controls`` mirror what
    ``discovery/pipeline.py`` writes: all three are JSON *lists* (one entry per
    claim / preregistration / controls snapshot), not objects.
    """

    contract_version: str
    run_id: str
    enabled: bool | None = None
    phenomena_state: ArtifactState = ArtifactState.MISSING
    preregistration_state: ArtifactState = ArtifactState.MISSING
    controls_state: ArtifactState = ArtifactState.MISSING
    discovered_cards_state: ArtifactState = ArtifactState.MISSING
    mechanisms_state: ArtifactState = ArtifactState.MISSING
    matches_state: ArtifactState = ArtifactState.MISSING
    claims_state: ArtifactState = ArtifactState.MISSING
    phenomena: list[dict[str, Any]] = Field(default_factory=list)
    controls: list[dict[str, Any]] = Field(default_factory=list)
    preregistration: list[dict[str, Any]] = Field(default_factory=list)
    claims: list[dict[str, Any]] = Field(default_factory=list)
    discovered_card_ids: list[str] = Field(default_factory=list)
    matches: list[dict[str, Any]] = Field(default_factory=list)
    certificates: list[dict[str, Any]] = Field(default_factory=list)
    theories: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[ContractWarning] = Field(default_factory=list)


class InsightResponse(ContractModel):
    """One reflection insight recorded by the engine (``insight`` table)."""

    insight_id: str
    origin_node: str | None = None
    branch_id: str | None = None
    polarity: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    delta: float | None = None
    z_score: float | None = None
    created_at: str | None = None


class InsightsResponse(ContractModel):
    """Insights for a run.

    ``available`` distinguishes the two empty cases the UI must not conflate:
    the run never carried an ``insight`` table at all (``available=false``) vs.
    the table exists and simply holds no rows (``available=true`` + ``[]``).
    """

    contract_version: str
    run_id: str
    available: bool
    insights: list[InsightResponse] = Field(default_factory=list)
    warnings: list[ContractWarning] = Field(default_factory=list)


# --------------------------------------------------------------------------
# artifacts
# --------------------------------------------------------------------------


class ArtifactResponse(ContractModel):
    """One downloadable artifact.

    ``artifact_id`` is minted by the server; the raw path is never accepted or
    returned, which is what keeps path traversal and access to protected
    evaluation data impossible.
    """

    artifact_id: str
    run_id: str
    kind: str
    display_name: str
    media_type: str
    size_bytes: int | None = None
    state: ArtifactState
    downloadable: bool


class ArtifactListResponse(ContractModel):
    """Everything downloadable for one run."""

    contract_version: str
    run_id: str
    artifacts: list[ArtifactResponse]


# --------------------------------------------------------------------------
# reports
# --------------------------------------------------------------------------


class ReportFileResponse(ContractModel):
    """One report file that already exists on disk."""

    artifact_id: str
    display_name: str
    media_type: str
    size_bytes: int | None = None
    state: ArtifactState


class ReportManifestResponse(ContractModel):
    """Listing of report files for one run.

    Phase 2 does not *generate* reports (that is a high-risk action, PRD §13.5,
    phase 9). It only surfaces files a prior export already left behind, so
    ``available`` is ``false`` whenever no report file exists.
    """

    contract_version: str
    run_id: str
    available: bool
    files: list[ReportFileResponse] = Field(default_factory=list)
    warnings: list[ContractWarning] = Field(default_factory=list)


# --------------------------------------------------------------------------
# errors
# --------------------------------------------------------------------------


class ApiErrorResponse(ContractModel):
    """Uniform error envelope. The UI shows Chinese text keyed by ``error_code``."""

    error_code: str
    message: str
    detail: str | None = None
    run_id: str | None = None
    field: str | None = None


# --------------------------------------------------------------------------
# model registry
# --------------------------------------------------------------------------


def _collect_contract_models() -> tuple[type[BaseModel], ...]:
    """Every DTO declared above, sorted by name.

    Used by the app factory to publish *all* DTOs into the OpenAPI components,
    not just the ones a route happens to reference today. Without this, a DTO
    that only phase 5 will serve would be absent from the generated TypeScript
    and the front-end would be forced to hand-declare it -- exactly what
    TODO §1.5 forbids.
    """
    found: list[type[BaseModel]] = []
    for name in __all__:
        obj = globals().get(name)
        if (
            isinstance(obj, type)
            and issubclass(obj, BaseModel)
            and obj is not ContractModel
        ):
            found.append(obj)
    return tuple(sorted(found, key=lambda model: model.__name__))


#: All DTOs, exposed so the OpenAPI document and the drift check cover them even
#: before their endpoints exist.
CONTRACT_MODELS: tuple[type[BaseModel], ...] = _collect_contract_models()

