"""Evaluator-backed research goals, shared by the engine and evidence reports."""

from __future__ import annotations

import math
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class MetricTarget(BaseModel):
    """One constraint on an evaluator result; all targets apply to one candidate."""

    model_config = ConfigDict(extra="forbid")
    metric: str = Field(pattern=r"^(combined_score|cost_time|metric\.[A-Za-z0-9_.]+)$")
    op: Literal[">=", "<="] = ">="
    value: float = Field(allow_inf_nan=False)

    def check(self, evaluation: dict[str, Any]) -> dict[str, Any]:
        current: Any = evaluation
        for part in self.metric.split("."):
            current = current.get(part) if isinstance(current, dict) else None
        numeric = type(current) in (int, float) and math.isfinite(current)
        passed = numeric and (current >= self.value if self.op == ">=" else current <= self.value)
        return {"metric": self.metric, "op": self.op, "target": self.value,
                "observed": current if numeric else None, "passed": bool(passed)}


class ResearchConfig(BaseModel):
    """Domain metadata and stopping goals; evaluator scores are never rewritten."""

    model_config = ConfigDict(extra="forbid")
    domain: str = Field(default="custom", min_length=1)
    dataset_id: str = Field(min_length=1)
    evidence_level: Literal["unspecified", "synthetic", "real"] = "unspecified"
    evaluation_split: Literal["dev", "val"] | None = None
    targets: list[MetricTarget] = Field(min_length=1)

    @field_validator("targets")
    @classmethod
    def unique_targets(cls, targets: list[MetricTarget]) -> list[MetricTarget]:
        keys = [(target.metric, target.op) for target in targets]
        if len(set(keys)) != len(keys):
            raise ValueError("同一指标和比较方向不能重复配置")
        return targets


def assess_goals(config: ResearchConfig, evaluation: dict[str, Any]) -> dict[str, Any]:
    """Missing, non-finite, invalid or wrong-split evidence cannot satisfy a goal."""
    checks = [target.check(evaluation) for target in config.targets]
    score = evaluation.get("combined_score")
    valid = (evaluation.get("validity") == 1.0 and type(score) in (int, float)
             and math.isfinite(score))
    metrics = evaluation.get("metric")
    split = metrics.get("split") if isinstance(metrics, dict) else None
    split_ok = config.evaluation_split is None or split == config.evaluation_split
    return {"achieved": valid and split_ok and all(check["passed"] for check in checks),
            "valid": valid, "split": split, "split_matches": split_ok, "checks": checks}
