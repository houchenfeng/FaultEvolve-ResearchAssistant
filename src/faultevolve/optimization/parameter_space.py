"""Generic parameter space definitions."""

from __future__ import annotations

import math
from typing import Any, Mapping

import numpy as np
from pydantic import BaseModel, Field, model_validator

class ParameterSpaceError(ValueError):
    """Invalid parameter space definition."""


class Condition(BaseModel):
    param: str
    in_: list[Any] = Field(alias="in")

    model_config = {"populate_by_name": True}


class ParamDef(BaseModel):
    name: str
    kind: str
    low: float | None = None
    high: float | None = None
    log: bool = False
    choices: list[Any] | None = None
    when: Condition | None = None

    @model_validator(mode="after")
    def _validate_bounds(self) -> "ParamDef":
        if self.kind in ("float", "int"):
            if self.low is None or self.high is None or self.low >= self.high:
                raise ParameterSpaceError(f"invalid bounds for {self.name}")
            if self.log and self.low <= 0:
                raise ParameterSpaceError(f"log scale requires low>0 for {self.name}")
        if self.kind == "categorical" and (not self.choices or len(self.choices) == 0):
            raise ParameterSpaceError(f"categorical {self.name} needs choices")
        return self


class ParameterSpace(BaseModel):
    version: int
    params: list[ParamDef]
    constraints: list[str] = Field(default_factory=list)


_CONSTRAINT_REGISTRY: dict[str, Any] = {}


def register_constraint(constraint_id: str, fn: Any) -> None:
    _CONSTRAINT_REGISTRY[constraint_id] = fn


def _c1(values: Mapping[str, Any]) -> str | None:
    wp = values.get("weight_policy")
    if wp != "none" and values.get("scale_pos_weight") is not None:
        return "C1: scale_pos_weight conflicts with weight_policy"
    return None


def _c2(values: Mapping[str, Any]) -> str | None:
    md = values.get("max_depth")
    if md is None or int(md) <= 0:
        return None
    nl = values.get("num_leaves")
    if nl is not None and int(nl) > 2 ** int(md):
        return "C2: num_leaves exceeds 2**max_depth"
    return None


def _c3(values: Mapping[str, Any]) -> str | None:
    penalty = values.get("penalty")
    solver = values.get("solver")
    if penalty is None or solver is None:
        return None
    allowed = {
        "l1": {"liblinear", "saga"},
        "l2": {"lbfgs", "liblinear"},
    }
    if penalty in allowed and solver not in allowed[penalty]:
        return "C3: solver incompatible with penalty"
    return None


register_constraint("C1", _c1)
register_constraint("C2", _c2)
register_constraint("C3", _c3)


def _when_satisfied(defn: ParamDef, values: Mapping[str, Any]) -> bool:
    if defn.when is None:
        return True
    cur = values.get(defn.when.param)
    return cur in defn.when.in_


def validate_values(space: ParameterSpace, values: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    names = {p.name for p in space.params}
    for defn in space.params:
        if not _when_satisfied(defn, values):
            continue
        if defn.name not in values:
            errors.append(f"missing param {defn.name}")
            continue
        val = values[defn.name]
        if defn.kind == "float":
            if not isinstance(val, (int, float)):
                errors.append(f"{defn.name} must be float")
            elif defn.low is not None and float(val) < float(defn.low):
                errors.append(f"{defn.name} below low")
            elif defn.high is not None and float(val) > float(defn.high):
                errors.append(f"{defn.name} above high")
        elif defn.kind == "int":
            if not isinstance(val, int):
                errors.append(f"{defn.name} must be int")
            elif defn.low is not None and val < int(defn.low):
                errors.append(f"{defn.name} below low")
            elif defn.high is not None and val > int(defn.high):
                errors.append(f"{defn.name} above high")
        elif defn.kind == "categorical":
            if defn.choices and val not in defn.choices:
                errors.append(f"{defn.name} not in choices")
        elif defn.kind == "bool":
            if not isinstance(val, bool):
                errors.append(f"{defn.name} must be bool")
    for key in values:
        if key not in names:
            errors.append(f"unknown param {key}")
    for cid in space.constraints:
        fn = _CONSTRAINT_REGISTRY.get(cid)
        if fn is None:
            raise ParameterSpaceError(f"unknown constraint id {cid}")
        msg = fn(values)
        if msg:
            errors.append(msg)
    return errors


def sample(space: ParameterSpace, rng: np.random.Generator) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for defn in space.params:
        if defn.when is not None:
            if not _when_satisfied(defn, values):
                continue
        if defn.kind == "float":
            lo, hi = float(defn.low), float(defn.high)
            if defn.log:
                val = math.exp(rng.uniform(math.log(lo), math.log(hi)))
            else:
                val = rng.uniform(lo, hi)
            values[defn.name] = float(val)
        elif defn.kind == "int":
            lo, hi = int(defn.low), int(defn.high)
            if defn.log:
                val = int(round(math.exp(rng.uniform(math.log(lo), math.log(hi)))))
            else:
                val = int(rng.integers(lo, hi + 1))
            values[defn.name] = val
        elif defn.kind == "categorical":
            values[defn.name] = rng.choice(defn.choices)
        elif defn.kind == "bool":
            values[defn.name] = bool(rng.integers(0, 2))
    return values
