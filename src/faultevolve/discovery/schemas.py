"""Pydantic schemas for knowledge discovery."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field


class Grade(str, Enum):
    CONFIRMED = "confirmed"
    REVISED = "revised"
    DISCOVERED = "discovered"
    REFUTED = "refuted"
    UNDETERMINED = "undetermined"


class Claim(BaseModel):
    id: str = ""
    experiment_id: str = ""
    origin_node_id: str = ""
    source: Literal["insight", "top_node", "discover_op"]
    title: str
    condition: str
    feature_code: str
    outcome: str
    direction: Literal["+", "-", "auto"]
    scope: str
    falsifier: str
    category: str = "feature_engineering"
    tags: list[str] = Field(default_factory=list)
    prereg_hash: str = ""
    status: str = "proposed"
    grade: Grade | None = None
    confirms: str | None = None
    revises: str | None = None


class ClaimTestResult(BaseModel):
    split: str
    n: int
    n_pos: int
    n_neg: int
    effect: float
    ci_low: float
    ci_high: float
    p: float
    e: float
    direction_ok: bool
    temporal_ok: bool | None = None
    rho_max_abs: float | None = None
    incr_gain: float | None = None
    incr_ci_low: float | None = None
    incr_ci_high: float | None = None


class ControlReport(BaseModel):
    neg_trials: int
    neg_false_positives: int
    neg_fpr: float
    planted: dict[str, dict[str, float]]
    passed: bool


@dataclass
class DiscoveryStats:
    rounds: int = 0
    rounds_skipped: int = 0
    claims_proposed: int = 0
    claims_tested: int = 0
    claims_sandbox_failed: int = 0
    confirmed: int = 0
    revised: int = 0
    discovered: int = 0
    refuted: int = 0
    undetermined: int = 0
    cards_promoted: int = 0
    neg_control_false_positives: int = 0
    neg_control_trials: int = 0
    planted_trials: dict[str, int] = field(default_factory=dict)
    planted_recovered: dict[str, int] = field(default_factory=dict)
    best_at_first_promotion: float | None = None
    discovery_llm_errors: int = 0
    discovery_llm_error_first: str | None = None


MechanismRole = Literal["claim", "llm_rival", "confound", "artifact", "censor", "other"]


class Mechanism(BaseModel):
    id: str
    claim_id: str
    role: MechanismRole
    title: str
    nodes: list[str] = Field(default_factory=list)
    edges: list[tuple[str, str, Literal["+", "-"]]] = Field(default_factory=list)
    predictions: dict[str, Literal[1, -1]] = Field(default_factory=dict)
    patch_count: int = 0
    status: Literal["proposed", "established", "refuted", "undetermined"] = "proposed"
    parent_id: str | None = None


class MatchResult(BaseModel):
    mech_a: str
    mech_b: str
    test_type: str
    test_id: str
    slice_id: str
    stat: float
    ci_low: float
    ci_high: float
    p: float
    e_raw: float
    log_bf_trunc: float
    supports: Literal["a", "b", "none"]
    decisive: bool
    min_detectable: float | None = None


class Certificate(BaseModel):
    mechanism_id: str
    rival_id: str
    test_id: str
    test_type: str
    env: str
    stat: float
    ci: tuple[float, float]
    e_value: float
    prereg_hash: str
    date: str


@dataclass
class KD2Handoff:
    claims: list[Claim]
    payloads: dict[str, dict]
    feature_map: dict[str, np.ndarray]
    y: np.ndarray
    groups: np.ndarray
    unit_ids: np.ndarray
    confirm_mask: np.ndarray
    env_frame: pd.DataFrame | None
    schema_note: str
    round_idx: int


@dataclass
class TournamentStats:
    mechanisms_proposed: int = 0
    matches_played: int = 0
    decisive_matches: int = 0
    underpowered_draws: int = 0
    certificates_issued: int = 0
    mechanisms_established: int = 0
    mechanisms_refuted: int = 0
    mechanism_patches: int = 0
    mechanism_cards_promoted: int = 0
    tournament_rounds: int = 0
    rounds_skipped: int = 0
    planted_mechanism_trials: int = 0
    planted_mechanism_recovered: int = 0
    shuffled_env_trials: int = 0
    shuffled_env_false_pass: int = 0
    llm_vs_data_kendall_tau: float | None = None
    min_detectable_effects: list[float] = field(default_factory=list)
