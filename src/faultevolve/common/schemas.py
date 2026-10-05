"""Pydantic models for FaultEvolve data structures."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class NodeStatus(str, Enum):
    """Status of a node in the evolution tree."""
    PENDING = "pending"
    EVALUATING = "evaluating"
    DONE = "done"
    INVALID = "invalid"
    ABANDONED = "abandoned"


class HypothesisStatus(str, Enum):
    """Status of a hypothesis."""
    OPEN = "open"
    SUPPORTED = "supported"
    REFUTED = "refuted"
    INCONCLUSIVE = "inconclusive"
    CORROBORATED = "corroborated"
    UNDETERMINED = "undetermined"


class OperatorType(str, Enum):
    """Types of evolution operators."""
    INIT = "init"
    REFINE = "refine"
    RECALL_FOCUS = "recall_focus"
    THRESHOLD_CALIBRATE = "threshold_calibrate"
    INJECT = "inject"
    TRANSPLANT = "transplant"
    CROSSOVER = "crossover"
    REPAIR = "repair"
    HPO = "hpo"
    PATCH = "patch"


GENERATIVE_OPERATORS = (
    OperatorType.REFINE,
    OperatorType.RECALL_FOCUS,
    OperatorType.THRESHOLD_CALIBRATE,
    OperatorType.INJECT,
    OperatorType.CROSSOVER,
)


class EvaluationResult(BaseModel):
    """Result from evaluating a candidate."""
    model_config = ConfigDict(extra="forbid")

    validity: float = Field(ge=0, le=1)
    combined_score: float = Field(ge=0)
    cost_time: float = Field(ge=0)
    error_info: str = ""
    metric: dict[str, Any] = Field(default_factory=dict)


class NodeArtifact(BaseModel):
    """Artifact (code) for a node."""
    code: str
    intent: str = ""
    hypothesis: str = ""


class NodeEvidence(BaseModel):
    """Evidence from evaluation for a node."""
    evaluation: EvaluationResult | None = None
    delta_score: float | None = None
    noise_delta: float | None = None


class Insight(BaseModel):
    """An insight extracted from node comparison."""
    id: str
    origin_node: str
    branch_id: str
    polarity: int = Field(ge=-1, le=1)
    change_summary: str
    mechanism: str = ""
    conditions: str = ""
    tags: list[str] = Field(default_factory=list)
    delta: float = 0.0
    z_score: float = 0.0
    alpha: float = 1.0
    beta: float = 1.0
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()


class BranchMemory(BaseModel):
    """Memory for a branch's top insights."""
    summary: str = ""
    top_insight_ids: list[str] = Field(default_factory=list)
    refuted_hypotheses: list[str] = Field(default_factory=list)


class Node(BaseModel):
    """A node in the evolution tree."""
    id: str
    experiment_id: str
    parent_id: str | None = None
    branch_id: str
    depth: int = 0
    operator: OperatorType = OperatorType.INIT
    artifact: NodeArtifact
    evidence: NodeEvidence = Field(default_factory=NodeEvidence)
    status: NodeStatus = NodeStatus.PENDING
    hypothesis_status: HypothesisStatus = HypothesisStatus.OPEN
    visit_count: int = 0
    expand_count: int = 0
    children: list[str] = Field(default_factory=list)
    insight_ids: list[str] = Field(default_factory=list)
    card_ids: list[str] = Field(default_factory=list)
    branch_memory: BranchMemory = Field(default_factory=BranchMemory)
    repair_attempted: bool = False
    hypothesis_fail_count: int = 0
    repair_count: int = 0
    repair_parent_id: str | None = None
    error_class: str = ""
    repair_exhausted: bool = False
    created_at: str = ""

    def is_expandable(self) -> bool:
        """Check if this node can be expanded."""
        if self.status in (NodeStatus.INVALID, NodeStatus.ABANDONED):
            return False
        if self.hypothesis_status == HypothesisStatus.REFUTED:
            return False
        if self.evidence.evaluation is None:
            return False
        if self.evidence.evaluation.validity < 1.0:
            return False
        if self.repair_exhausted:
            return False
        return True

    def is_repair_node(self) -> bool:
        """Check if this is a repair node."""
        return self.operator == OperatorType.REPAIR

    def get_score(self) -> float:
        """Get the combined score of this node."""
        if self.evidence.evaluation is None:
            return 0.0
        return self.evidence.evaluation.combined_score

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()


class LLMCall(BaseModel):
    """Record of an LLM call."""
    id: str
    experiment_id: str
    node_id: str | None = None
    purpose: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0
    cached: bool = False
    created_at: str = ""


class Event(BaseModel):
    """An event in the experiment timeline."""
    id: int | None = None
    experiment_id: str
    type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    ts: str = ""


class ExperimentConfig(BaseModel):
    """Configuration for an evolution experiment."""
    max_iterations: int = 50
    max_tokens: int = 3_000_000
    max_wall_hours: float = 6.0
    target_score: float | None = None
    c_puct: float = 1.2
    kappa_noise: float = 1.0
    widening_c: float = 2.0
    widening_alpha: float = 0.5
    min_noise_delta: float = 0.5
    seed: int = 20260926


class Experiment(BaseModel):
    """An evolution experiment."""
    id: str
    name: str = ""
    status: str = "created"
    config: ExperimentConfig = Field(default_factory=ExperimentConfig)
    problem_md: str = ""
    prompt_md: str = ""
    best_node_id: str | None = None
    best_score: float = 0.0
    iterations_done: int = 0
    total_tokens: int = 0
    created_at: str = ""
    updated_at: str = ""


@dataclass
class CardAdoptionStats:
    """Statistics for a single knowledge card's adoption."""
    card_id: str
    n_adopted: int = 0
    mean_delta: float = 0.0


class RunSummary(BaseModel):
    """Summary of an evolution run."""
    experiment_id: str
    status: str
    iterations_done: int
    best_score: float
    best_node_id: str | None = None
    initial_score: float = 0.0
    improvement: float = 0.0
    valid_rate: float = 0.0
    total_tokens: int = 0
    total_llm_latency_ms: int = 0
    total_eval_time_s: float = 0.0
    wall_time_s: float = 0.0
    rounds_to_target: int | None = None
    time_to_target_s: float | None = None
    tokens_to_target: int | None = None
    stop_reason: str = ""
    repair_attempts: int = 0
    repair_successes: int = 0
    repair_tokens: int = 0
    repair_iterations: int = 0
    knowledge_tokens: int = 0
    card_adoption_rate: float = 0.0
    card_stats: list[dict[str, Any]] = Field(default_factory=list)
    generate_tokens: int = 0
    reflect_tokens: int = 0
    knowledge_token_share: float = 0.0
    cards_offered: int = 0
    cards_adopted: int = 0
    cards_adopted_valid: int = 0
    tokens_per_score_gain: float = 0.0
    precheck_fixes: int = 0
    adapter_errors: int = 0
    perf_rejections: int = 0
    smoke_failures: int = 0
    smoke_fixes: int = 0
    self_fix_tokens: int = 0
    smoke_time_s_total: float = 0.0
    smoke_tests: int = 0
    avg_smoke_time_s: float | None = None
    iteration_events: int = 0
    jev_calls: int = 0
    jev_errors: int = 0
    jev_fail_open: int = 0
    jev_prompt_tokens: int = 0
    jev_completion_tokens: int = 0
    jev_tokens: int = 0
    jev_latency_ms: int = 0
    jev_disabled_reason: str = ""
    candidates_screened: int = 0
    evaluations_saved: int = 0
    eval_time_saved_est_s: float = 0.0
    screen_audited: int = 0
    screen_audit_bad: int = 0
    screen_shadow: int = 0
    screening_precision: float | None = None
    jev_prior_active: bool = False
    analysis_calls: int = 0
    analysis_failures: int = 0
    analysis_time_s: float = 0.0
    analysis_nonempty_rate: float = 0.0
    tokens_per_ros_point: float | None = None
    stage_cap_hits: dict[str, int] = Field(default_factory=dict)
    budget_stop_reason: str = ""
    elite_archive_sizes: dict[str, int] = Field(default_factory=dict)
    expand_skipped_budget: int = 0
    value_mode: str = "scalar"
    operator_counts: dict[str, int] = Field(default_factory=dict)
    operator_valid_rate: dict[str, float] = Field(default_factory=dict)
    operator_mean_delta: dict[str, float] = Field(default_factory=dict)
    operator_posteriors: dict[str, dict[str, float]] = Field(default_factory=dict)
    operator_tokens: dict[str, int] = Field(default_factory=dict)
    generative_valid_rate: float | None = None
    bandit_active: bool = False
    discovery_tokens: int = 0
    discovery_token_share: float = 0.0
    discovery_rounds: int = 0
    discovery_rounds_skipped: int = 0
    claims_proposed: int = 0
    claims_tested: int = 0
    claims_sandbox_failed: int = 0
    claims_confirmed: int = 0
    claims_revised: int = 0
    claims_discovered: int = 0
    claims_refuted: int = 0
    claims_undetermined: int = 0
    discovered_cards_count: int = 0
    discovered_cards_offered: int = 0
    discovered_cards_adopted: int = 0
    discovered_card_adoption_rate: float = 0.0
    discovered_card_mean_delta: float | None = None
    literature_card_mean_delta: float | None = None
    score_delta_after_discovery: float | None = None
    neg_control_false_positives: int = 0
    neg_control_fpr: float | None = None
    planted_recovery_rate: dict[str, float] = Field(default_factory=dict)
    mechanism_tokens: int = 0
    mechanisms_proposed: int = 0
    matches_played: int = 0
    decisive_matches: int = 0
    underpowered_draws: int = 0
    certificates_issued: int = 0
    mechanisms_established: int = 0
    mechanisms_refuted: int = 0
    mechanism_patches: int = 0
    mechanism_cards_count: int = 0
    tournament_rounds: int = 0
    planted_mechanism_recovered: float | None = None
    llm_vs_data_kendall_tau: float | None = None
    shuffled_env_false_pass: float | None = None
    tournament_tokens: int = 0
    min_detectable_effect: float | None = None
    crossover_count: int = 0
    crossover_valid_rate: float | None = None
    crossover_mean_delta: float | None = None
    crossover_best_gain: float | None = None
    crossover_tokens: int = 0


class TreeExport(BaseModel):
    """Export format for the evolution tree."""
    experiment_id: str
    nodes: list[dict[str, Any]]
    edges: list[dict[str, str]]
