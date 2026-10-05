"""HDD task parameter spaces and feature groups."""

from __future__ import annotations

from faultevolve.optimization.candidate_spec import CandidateSpec, TrainSpec
from faultevolve.optimization.parameter_space import Condition, ParamDef, ParameterSpace

FEATURE_GROUPS = {
    "snapshot_core": [
        "smart_5_raw",
        "smart_187_raw",
        "smart_188_raw",
        "smart_197_raw",
        "smart_198_raw",
        "smart_199_raw",
        "smart_9_raw",
        "smart_194_raw",
        "smart_1_normalized",
        "smart_7_normalized",
    ],
    "vendor_onehot": ["vendor_ST", "vendor_TOSHIBA", "vendor_HGST", "vendor_WDC"],
    "delta_7d": ["delta_smart_5_raw"],
}


def logreg_space() -> ParameterSpace:
    return ParameterSpace(
        version=1,
        params=[
            ParamDef(name="C", kind="float", low=1e-3, high=1e2, log=True),
            ParamDef(name="penalty", kind="categorical", choices=["l1", "l2"]),
            ParamDef(
                name="solver",
                kind="categorical",
                choices=["liblinear", "saga"],
                when=Condition(param="penalty", in_=["l1"]),
            ),
            ParamDef(
                name="solver",
                kind="categorical",
                choices=["lbfgs", "liblinear"],
                when=Condition(param="penalty", in_=["l2"]),
            ),
            ParamDef(name="max_iter", kind="int", low=200, high=2000),
            ParamDef(
                name="weight_policy",
                kind="categorical",
                choices=["sample_weight_only", "class_weight_only", "none"],
            ),
        ],
        constraints=["C1", "C3"],
    )


def lightgbm_space() -> ParameterSpace:
    return ParameterSpace(
        version=1,
        params=[
            ParamDef(name="num_leaves", kind="int", low=8, high=128, log=True),
            ParamDef(name="learning_rate", kind="float", low=0.02, high=0.3, log=True),
            ParamDef(name="n_estimators", kind="int", low=100, high=600),
            ParamDef(name="min_child_samples", kind="int", low=10, high=200),
            ParamDef(name="subsample", kind="float", low=0.5, high=1.0),
            ParamDef(name="colsample_bytree", kind="float", low=0.5, high=1.0),
            ParamDef(name="reg_lambda", kind="float", low=1e-3, high=10.0, log=True),
            ParamDef(name="max_depth", kind="int", low=-1, high=12),
            ParamDef(
                name="weight_policy",
                kind="categorical",
                choices=["sample_weight_only", "class_weight_only", "none"],
            ),
            ParamDef(
                name="scale_pos_weight",
                kind="float",
                low=1.0,
                high=50.0,
                log=True,
                when=Condition(param="weight_policy", in_=["none"]),
            ),
            ParamDef(name="n_jobs", kind="int", low=1, high=8),
        ],
        constraints=["C1", "C2"],
    )


def default_spec(family: str) -> CandidateSpec:
    if family == "logreg":
        return CandidateSpec(
            family_id="logreg",
            template_id="hdd.logreg.v1",
            feature_groups=["snapshot_core", "vendor_onehot"],
            params={"C": 0.5, "penalty": "l2", "solver": "lbfgs", "max_iter": 2000, "weight_policy": "sample_weight_only"},
            train=TrainSpec(seed=0, weight_policy="sample_weight_only"),
            space_version=1,
        )
    return CandidateSpec(
        family_id="lightgbm",
        template_id="hdd.lightgbm.v1",
        feature_groups=["snapshot_core", "vendor_onehot", "delta_7d"],
        params={
            "num_leaves": 31,
            "learning_rate": 0.05,
            "n_estimators": 200,
            "min_child_samples": 20,
            "subsample": 0.8,
            "colsample_bytree": 0.8,
            "reg_lambda": 1.0,
            "max_depth": -1,
            "weight_policy": "none",
            "scale_pos_weight": 1.0,
            "n_jobs": 1,
        },
        train=TrainSpec(seed=0, weight_policy="none"),
        space_version=1,
    )
