"""Structured candidate specification and compilation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Literal, Mapping

from pydantic import BaseModel, Field


class TrainSpec(BaseModel):
    seed: int = 0
    weight_policy: Literal["sample_weight_only", "class_weight_only", "none"] = "sample_weight_only"


class CalibrationSpec(BaseModel):
    rule: Literal["oof_f1_quantile"] = "oof_f1_quantile"
    quantile_grid: int = Field(default=60, ge=10, le=200)


class CandidateSpec(BaseModel):
    spec_version: int = 1
    family_id: Literal["logreg", "lightgbm"]
    template_id: str
    feature_groups: list[str]
    params: dict[str, float | int | str | bool]
    train: TrainSpec = Field(default_factory=TrainSpec)
    calibration: CalibrationSpec = Field(default_factory=CalibrationSpec)
    editable_blocks: list[Literal["feature", "model", "train", "calibration"]] = Field(
        default_factory=lambda: ["feature", "model", "train", "calibration"]
    )
    space_version: int = 1


@dataclass(frozen=True)
class CompiledCandidate:
    code: str
    source_hash: str
    config_hash: str
    fits_per_run: int


def _canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def config_hash(spec: CandidateSpec) -> str:
    payload = {
        "params": spec.params,
        "train": spec.train.model_dump(),
        "calibration": spec.calibration.model_dump(),
        "seed": spec.train.seed,
        "space_version": spec.space_version,
    }
    digest = hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def structure_hash(spec: CandidateSpec) -> str:
    payload = {
        "family_id": spec.family_id,
        "template_id": spec.template_id,
        "feature_groups": spec.feature_groups,
    }
    digest = hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def source_hash(code: str) -> str:
    normalized = code.replace("\r\n", "\n").rstrip() + "\n"
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def compile_spec(spec: CandidateSpec, templates: Mapping[str, str]) -> CompiledCandidate:
    template = templates.get(spec.template_id)
    if template is None:
        raise ValueError(f"unknown template_id: {spec.template_id}")
    params_json = _canonical_json(spec.params)
    train_json = _canonical_json(spec.train.model_dump())
    cal_json = _canonical_json(spec.calibration.model_dump())
    code = (
        template.replace("{{PARAMS_JSON}}", params_json)
        .replace("{{TRAIN_JSON}}", train_json)
        .replace("{{CALIBRATION_JSON}}", cal_json)
        .replace("{{FEATURE_GROUPS_JSON}}", _canonical_json(spec.feature_groups))
        .replace("{{SEED}}", str(spec.train.seed))
    )
    ch = config_hash(spec)
    sh = source_hash(code)
    fits = 1
    if "FITS_PER_RUN =" in code:
        for line in code.splitlines():
            if line.strip().startswith("FITS_PER_RUN ="):
                fits = int(line.split("=", 1)[1].strip())
                break
    return CompiledCandidate(code=code, source_hash=sh, config_hash=ch, fits_per_run=fits)
