"""Configuration management for FaultEvolve.

Loads configuration from evolve.yaml and environment variables.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

_BUDGET_STAGE_KEYS = frozenset({"reflect", "repair", "knowledge", "jev", "mechanism", "crossover"})


class SelectionValueConfig(BaseModel):
    """Multi-objective node value settings (selection only)."""
    mode: str = Field(default="scalar", pattern="^(scalar|multi)$")
    lambda_rank: float = Field(default=0.3, ge=0)
    lambda_noise: float = Field(default=1.0, ge=0)
    backup: str = Field(default="max", pattern="^(max|softmax)$")
    elite_m: int = Field(default=3, ge=0)
    elite_prob: float = Field(default=0.2, ge=0, le=1)
    rank_keys: list[str] = Field(default_factory=list)
    threshold_keys: list[str] = Field(default_factory=list)
    noise_key: str = ""


class BudgetConfig(BaseModel):
    """Budget constraints for evolution."""
    max_iterations: int = 50
    max_tokens: int = 3_000_000
    max_wall_hours: float = 6.0
    stage_caps: dict[str, float] = Field(default_factory=dict)
    stagnation_window: int = Field(default=0, ge=0)
    tokens_per_point_cap: float | None = Field(default=None, gt=0)
    min_iterations_before_stop: int = Field(default=5, ge=0)
    safety_factor: float = Field(default=1.5, ge=1)
    expand_gating: bool = False
    cost_window: int = Field(default=5, ge=1)
    # Consecutive iterations that make no progress before the run stops.
    stall_iterations: int = Field(default=5, ge=1)

    @field_validator("stage_caps")
    @classmethod
    def _validate_stage_caps(cls, value: dict[str, float]) -> dict[str, float]:
        for key, frac in value.items():
            if key not in _BUDGET_STAGE_KEYS:
                raise ValueError(f"invalid stage_caps key: {key}")
            if not (0 < frac <= 1):
                raise ValueError(f"stage_caps value for {key} must be in (0, 1]")
        return value


class SelectionConfig(BaseModel):
    """Configuration for node selection."""
    policy: str = "uct"
    c_puct: float = 1.2
    kappa_noise: float = 1.0
    lambda_dup: float = 0.1
    value: SelectionValueConfig = Field(default_factory=SelectionValueConfig)


class WideningConfig(BaseModel):
    """Configuration for progressive widening."""
    C: float = 2.0
    alpha: float = 0.5


class CrossoverConfig(BaseModel):
    """Configuration for crossover / ensemble operator."""
    enabled: bool = False
    min_valid_nodes: int = Field(default=4, ge=2)
    runtime_budget_s: float = Field(default=300.0, gt=0)
    top_quantile: float = Field(default=0.3, gt=0, le=1)
    max_code_chars: int = Field(default=6000, ge=500)


class OperatorsConfig(BaseModel):
    """Configuration for operators."""
    bandit: bool = False
    enabled: list[str] = Field(
        default_factory=lambda: [
            "refine",
            "recall_focus",
            "threshold_calibrate",
            "inject",
        ]
    )
    min_explore: float = Field(default=0.1, ge=0, le=1)
    prior_alpha: float = Field(default=1.0, gt=0)
    prior_beta: float = Field(default=1.0, gt=0)
    fn_keywords: bool = False
    fn_keyword_groups: int = Field(default=3, ge=1, le=5)
    crossover: CrossoverConfig = Field(default_factory=CrossoverConfig)

    @model_validator(mode="after")
    def _crossover_requires_bandit(self) -> "OperatorsConfig":
        if self.crossover.enabled and not self.bandit:
            raise ValueError("crossover requires operators.bandit")
        return self

    @field_validator("enabled")
    @classmethod
    def _validate_enabled(cls, value: list[str]) -> list[str]:
        allowed = {"refine", "recall_focus", "threshold_calibrate", "inject"}
        seen: set[str] = set()
        ordered: list[str] = []
        for item in value:
            if item not in allowed:
                raise ValueError(f"invalid operator in enabled: {item}")
            if item not in seen:
                seen.add(item)
                ordered.append(item)
        if "refine" not in ordered:
            raise ValueError("enabled must include refine")
        return ordered


class InsightsConfig(BaseModel):
    """Configuration for insight propagation."""
    top_k_foreign: int = 3
    top_k_negative: int = 3
    summarize_every: int = 5
    top_k_branch_memory: int = 5
    reputation_enabled: bool = False


class StopConfig(BaseModel):
    """Configuration for stopping conditions."""
    target_score: float | None = None
    stop_at_target: bool = True
    window: int = 15
    improve_rate_q90: float = 0.05
    continue_prob: float = 0.2


class JudgeConfig(BaseModel):
    """Configuration for the fast structured judge."""
    provider: str = Field(default="none", pattern="^(none|jev|mock)$")
    base_url: str = "https://miyang.cn/api/v1/decisions"
    api_key_env: str = "MIYANG_API_KEY"
    model: str = "miyang/jev-1.13"
    timeout_s: float = Field(default=5.0, gt=0)
    prescreen: bool = False
    invalid_threshold: float = Field(default=0.85, ge=0, le=1)
    low_value_threshold: float = Field(default=0.15, ge=0, le=1)
    low_value_action: str = Field(default="skip", pattern="^(skip|defer)$")
    defer_flush_evals: int = Field(default=0, ge=0)
    warmup: int = Field(default=10, ge=0)
    audit_rate: float = Field(default=0.1, ge=0, le=1)
    prior: bool = True
    prior_tau: float = Field(default=0.5, ge=0, le=1)
    max_calls: int = Field(default=500, ge=0)
    max_consecutive_errors: int = Field(default=3, ge=1)
    max_state_chars: int = Field(default=6000, ge=1)
    retries: int = Field(default=0, ge=0)
    calibration_window: int = Field(default=30, ge=0)
    initial_trust: float = Field(default=0.5, ge=0, le=1)


class LLMConfig(BaseModel):
    """Configuration for LLM calls."""
    base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    generate_model: str = "qwen3-coder-plus"
    reason_model: str = "qwen3-max"
    max_concurrency: int = 4
    temperature: float = 0.7
    max_tokens: int = 8000


class ReflectionConfig(BaseModel):
    """Configuration for reflection layers."""
    design_delta_factor: float = 1.0
    hypothesis_delta_factor: float = 2.0
    max_repair_attempts: int = 1


class KnowledgeConfig(BaseModel):
    """Configuration for knowledge injection."""
    dir: str = ""
    k: int = 4
    max_per_category: int = 2
    enabled: bool = True


class SmokeTestConfig(BaseModel):
    """Configuration for smoke test before full evaluation."""
    enabled: bool = True
    sample_fraction: float = 0.02
    timeout_s: int = 60


class AnalysisConfig(BaseModel):
    """Configuration for dev-set error profiling."""
    enabled: bool = False
    top_k: int = Field(default=3, ge=0)
    on_new_best: bool = True
    dev_late_fraction: float = Field(default=0.4, gt=0, lt=1)
    timeout_s: int = Field(default=600, gt=0, le=900)
    min_group_count: int = Field(default=10, ge=10)


class TournamentConfig(BaseModel):
    """Configuration for mechanism tournament (KD2)."""
    enabled: bool = False
    elo_k0: float = Field(default=32.0, gt=0)
    max_rounds: int = Field(default=3, ge=1)
    max_rivals: int = Field(default=2, ge=0, le=2)
    n_slices: int = Field(default=4, ge=2, le=16)
    min_env_pos: int = Field(default=5, ge=1)
    equiv_margin: float = Field(default=0.02, gt=0)
    icp_gate_p: float = Field(default=0.01, gt=0, lt=1)
    max_token_share: float = Field(default=0.10, gt=0, le=1)
    max_patches: int = Field(default=1, ge=0)


class DiscoveryConfig(BaseModel):
    """Configuration for phenomenon-level knowledge discovery."""
    enabled: bool = False
    tournament: TournamentConfig = Field(default_factory=TournamentConfig)
    every_n_iterations: int = Field(default=5, ge=1)
    run_at_end: bool = True
    max_claims_per_round: int = Field(default=3, ge=1)
    min_insight_z: float = 2.0
    top_k_programs: int = Field(default=3, ge=0)
    discover_op_every: int = Field(default=0, ge=0)
    alpha: float = Field(default=0.05, gt=0, lt=1)
    bootstrap_b: int = Field(default=500, ge=50)
    e_calibrator_kappa: float = Field(default=0.5, gt=0, lt=1)
    rho_max: float = 0.8
    planted_strengths: list[float] = Field(default_factory=lambda: [0.2, 0.5, 1.0])
    neg_control_repeats: int = Field(default=5, ge=1)
    max_neg_control_fpr: float = 0.10
    confirmation_fraction: float = Field(default=0.3, gt=0, lt=1)
    split_salt: str = "fe-kd-2026"
    sandbox_timeout_s: int = Field(default=120, gt=0)
    max_token_share: float = Field(default=0.2, gt=0, le=1)
    inject_same_run: bool = True
    cards_path: str | None = None
    extra_card_paths: list[str] = Field(default_factory=list)
    use_jev_entailment: bool = False


class TaskConfig(BaseModel):
    """Task adapter selection (default keeps legacy HDD MVP behavior)."""

    adapter: str = "hdd"


class LedgerConfig(BaseModel):
    enabled: bool = False
    full_eval_cap: int | None = Field(default=None, ge=1)


class HpoDevConfig(BaseModel):
    dev_late_fraction: float = Field(default=0.4, gt=0, lt=1)
    purge_days: int = Field(default=7, ge=0)
    min_dev_pos: int = Field(default=20, ge=1)
    min_train_pos: int = Field(default=20, ge=1)


class HpoConfig(BaseModel):
    enabled: bool = False
    families: list[str] = Field(default_factory=lambda: ["logreg"])
    search: str = "random"
    trials_per_structure: int = Field(default=8, ge=1, le=64)
    max_fits_total: int = Field(default=80, ge=1)
    promote_top_k: int = Field(default=1, ge=1, le=3)
    threads: int = Field(default=1, ge=1, le=8)
    trial_timeout_s: int = Field(default=300, ge=10, le=900)
    dev: HpoDevConfig = Field(default_factory=HpoDevConfig)

    @field_validator("families")
    @classmethod
    def _families(cls, value: list[str]) -> list[str]:
        allowed = {"logreg", "lightgbm"}
        for f in value:
            if f not in allowed:
                raise ValueError(f"invalid hpo family: {f}")
        return value

    @model_validator(mode="after")
    def _search_algo(self) -> "HpoConfig":
        if self.search == "tpe":
            raise ValueError("search=tpe is not available in E1")
        if self.search != "random":
            raise ValueError(f"unsupported search: {self.search}")
        return self


class CacheConfig(BaseModel):
    enabled: bool = False
    full_eval: bool = False


class PatchConfig(BaseModel):
    enabled: bool = False
    fallback: str = Field(default="reject", pattern="^(reject|draft)$")
    max_hunks: int = Field(default=3, ge=1, le=8)
    max_changed_lines: int = Field(default=60, ge=1)


class AblationConfig(BaseModel):
    enabled: bool = False
    max_units: int = Field(default=6, ge=1, le=12)
    paired_resamples: int = Field(default=200, ge=50)


class FeedbackConfig(BaseModel):
    enabled: bool = False
    max_chars: int = Field(default=2500, ge=500)


class QuotaConfig(BaseModel):
    enabled: bool = False
    shares: dict[str, int] = Field(default_factory=lambda: {"hpo": 3, "patch": 5, "draft": 2})
    plateau_evals: int = Field(default=8, ge=2)
    max_restarts: int = Field(default=2, ge=0)
    archive_cap: int = Field(default=20, ge=0)

    @field_validator("shares")
    @classmethod
    def _shares(cls, value: dict[str, int]) -> dict[str, int]:
        allowed = {"hpo", "patch", "draft"}
        if set(value.keys()) - allowed:
            raise ValueError("quota.shares keys must be hpo, patch, draft")
        if sum(value.values()) <= 0:
            raise ValueError("quota.shares must sum to > 0")
        return value


class AutotuneConfig(BaseModel):
    ledger: LedgerConfig = Field(default_factory=LedgerConfig)
    hpo: HpoConfig = Field(default_factory=HpoConfig)
    cache: CacheConfig = Field(default_factory=CacheConfig)
    patch: PatchConfig = Field(default_factory=PatchConfig)
    ablation: AblationConfig = Field(default_factory=AblationConfig)
    feedback: FeedbackConfig = Field(default_factory=FeedbackConfig)
    quota: QuotaConfig = Field(default_factory=QuotaConfig)

    @model_validator(mode="after")
    def _cross_validate(self) -> "AutotuneConfig":
        if self.hpo.enabled and not self.ledger.enabled:
            raise ValueError("hpo.enabled requires autotune.ledger.enabled")
        if self.patch.enabled and not self.ledger.enabled:
            raise ValueError("patch.enabled requires autotune.ledger.enabled")
        if self.quota.enabled and not self.ledger.enabled:
            raise ValueError("quota.enabled requires autotune.ledger.enabled")
        if self.ablation.enabled and not self.hpo.enabled:
            raise ValueError("ablation.enabled requires autotune.hpo.enabled")
        return self


class EvolveConfig(BaseModel):
    """Complete evolution configuration."""
    task: TaskConfig = Field(default_factory=TaskConfig)
    budget: BudgetConfig = Field(default_factory=BudgetConfig)
    selection: SelectionConfig = Field(default_factory=SelectionConfig)
    widening: WideningConfig = Field(default_factory=WideningConfig)
    operators: OperatorsConfig = Field(default_factory=OperatorsConfig)
    insights: InsightsConfig = Field(default_factory=InsightsConfig)
    stop: StopConfig = Field(default_factory=StopConfig)
    judge: JudgeConfig = Field(default_factory=JudgeConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    reflection: ReflectionConfig = Field(default_factory=ReflectionConfig)
    knowledge: KnowledgeConfig = Field(default_factory=KnowledgeConfig)
    smoke_test: SmokeTestConfig = Field(default_factory=SmokeTestConfig)
    analysis: AnalysisConfig = Field(default_factory=AnalysisConfig)
    discovery: DiscoveryConfig = Field(default_factory=DiscoveryConfig)
    autotune: AutotuneConfig = Field(default_factory=AutotuneConfig)
    seed: int = 20260926

    @model_validator(mode="after")
    def _tournament_requires_discovery(self) -> "EvolveConfig":
        if self.discovery.tournament.enabled and not self.discovery.enabled:
            raise ValueError("tournament requires discovery.enabled")
        if self.autotune.quota.enabled and self.operators.bandit:
            raise ValueError("quota.enabled requires operators.bandit=false")
        return self

    @classmethod
    def from_yaml(cls, yaml_path: Path) -> "EvolveConfig":
        """Load configuration from a YAML file."""
        if not yaml_path.exists():
            return cls()

        with yaml_path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EvolveConfig":
        """Create configuration from a dictionary."""
        config = cls()

        if "budget" in data:
            config.budget = BudgetConfig(**data["budget"])
        if "selection" in data:
            config.selection = SelectionConfig(**data["selection"])
        if "widening" in data:
            config.widening = WideningConfig(**data["widening"])
        elif "selection" in data and "widening" in data["selection"]:
            config.widening = WideningConfig(**data["selection"]["widening"])
        if "operators" in data:
            config.operators = OperatorsConfig(**data["operators"])
        if "insights" in data:
            config.insights = InsightsConfig(**data["insights"])
        if "stop" in data:
            config.stop = StopConfig(**data["stop"])
        if "judge" in data:
            config.judge = JudgeConfig(**data["judge"])
        if "llm" in data:
            config.llm = LLMConfig(**data["llm"])
        if "reflection" in data:
            config.reflection = ReflectionConfig(**data["reflection"])
        if "knowledge" in data:
            config.knowledge = KnowledgeConfig(**data["knowledge"])
        if "smoke_test" in data:
            config.smoke_test = SmokeTestConfig(**data["smoke_test"])
        if "analysis" in data:
            config.analysis = AnalysisConfig(**data["analysis"])
        if "discovery" in data:
            config.discovery = DiscoveryConfig(**data["discovery"])
        if "seed" in data:
            config.seed = data["seed"]
        if "task" in data:
            config.task = TaskConfig(**data["task"])
        if "autotune" in data:
            config.autotune = AutotuneConfig(**data["autotune"])

        return config

    def with_overrides(
        self,
        max_iterations: int | None = None,
        target_score: float | None = None,
        seed: int | None = None,
    ) -> "EvolveConfig":
        """Create a new config with specified overrides."""
        data = self.model_dump()

        if max_iterations is not None:
            data["budget"]["max_iterations"] = max_iterations
        if target_score is not None:
            data["stop"]["target_score"] = target_score
        if seed is not None:
            data["seed"] = seed

        return EvolveConfig.from_dict(data)


def get_api_key(env_var: str = "DASHSCOPE_API_KEY") -> str | None:
    """Get API key from environment variable.

    Never logs or stores the key value.
    """
    return os.environ.get(env_var)


def has_api_key(env_var: str = "DASHSCOPE_API_KEY") -> bool:
    """Check if API key is set in environment."""
    key = get_api_key(env_var)
    return key is not None and len(key) > 0
