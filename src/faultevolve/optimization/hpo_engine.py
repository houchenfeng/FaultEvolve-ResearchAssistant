"""HPO trial execution for in-engine quota slots (reuses hpo_runner data paths)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from faultevolve.cloud.store import Store
from faultevolve.config import EvolveConfig
from faultevolve.optimization.cache import cache_key, data_version_from_paths, env_fingerprint
from faultevolve.optimization.candidate_spec import compile_spec, config_hash, structure_hash
from faultevolve.optimization.ledger import CostLedger, CostRecord, Stage
from faultevolve.optimization.parameter_space import validate_values
from faultevolve.optimization.search import RandomSearch
from faultevolve.optimization.trials import Trial
from faultevolve.optimization.dev_split import DevSplit
from faultevolve.tasks.hdd_dev import build_dev_task_dir, make_hdd_dev_split, score_dev
from faultevolve.tasks.hdd_space import default_spec, lightgbm_space, logreg_space
from faultevolve.tasks.hdd_templates import TEMPLATE_MAP


def _space_for_family(family: str):
    return logreg_space() if family == "logreg" else lightgbm_space()


@dataclass
class HpoDevContext:
    dev_split: DevSplit
    dev_dir: Path
    data_version: str
    evaluator_hash: str
    env_fp: dict[str, Any]


def prepare_hpo_dev_context(
    task_dir: Path,
    config: EvolveConfig,
    *,
    mock_eval: bool,
) -> HpoDevContext:
    hpo_cfg = config.autotune.hpo
    public = task_dir / "data" / "public"
    dev_split = make_hdd_dev_split(
        task_dir,
        late_fraction=hpo_cfg.dev.dev_late_fraction,
        purge_days=hpo_cfg.dev.purge_days,
    )
    history_path = public / "train_history.csv.gz"
    dev_dir = build_dev_task_dir(task_dir, dev_split, history_path)
    data_ver = data_version_from_paths(
        [public / "train_labels.csv", public / "train_history.csv.gz"]
    )
    return HpoDevContext(
        dev_split=dev_split,
        dev_dir=dev_dir,
        data_version=data_ver,
        evaluator_hash="mock" if mock_eval else "task",
        env_fp=env_fingerprint(hpo_cfg.threads),
    )


def run_family_hpo_trials(
    *,
    task_dir: Path,
    config: EvolveConfig,
    store: Store,
    experiment_id: str,
    ledger: CostLedger,
    dev_ctx: HpoDevContext,
    family: str,
    start_index: int,
    used_fits: int,
    mock_eval: bool,
    fit_stage: Stage = "hpo_trial",
) -> tuple[list[Trial], int]:
    """Run up to trials_per_structure trials for one model family."""
    hpo_cfg = config.autotune.hpo
    base = default_spec(family)
    struct_id = structure_hash(base)
    space = _space_for_family(family)
    searcher = RandomSearch(config.seed)
    proposals = searcher.propose(
        space,
        structure_id=struct_id,
        start_index=start_index,
        n=hpo_cfg.trials_per_structure,
    )
    trials: list[Trial] = []
    for offset, params in enumerate(proposals):
        idx = start_index + offset
        spec = base.model_copy(deep=True)
        spec.params.update(params)
        spec.train.seed = config.seed + idx
        errs = validate_values(space, spec.params)
        if errs:
            continue
        compiled = compile_spec(spec, TEMPLATE_MAP)
        if used_fits + compiled.fits_per_run > hpo_cfg.max_fits_total:
            break
        ch = config_hash(spec)
        ck = cache_key(
            source_hash=compiled.source_hash,
            config_hash=ch,
            data_version=dev_ctx.data_version,
            evaluator_hash=dev_ctx.evaluator_hash,
            fidelity="dev",
            seed=spec.train.seed,
            env_fingerprint=dev_ctx.env_fp,
        )
        cache_hit = False
        dev_metrics = None
        dev_proxy = None
        if config.autotune.cache.enabled:
            cached = store.get_eval_cache(ck)
            if cached:
                cache_hit = True
                dev_proxy = cached["result"].get("dev_proxy")
                dev_metrics = cached["result"]
        res = ledger.reserve(fit_stage, est_model_fits=compiled.fits_per_run)
        status = "ok"
        try:
            if not cache_hit:
                pred_path = Path(tempfile.mkstemp(suffix=".csv")[1])
                script_path = Path(tempfile.mkstemp(suffix=".py")[1])
                script_path.write_text(compiled.code, encoding="utf-8")
                env = os.environ.copy()
                for k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
                    env[k] = str(hpo_cfg.threads)
                subprocess.run(
                    [
                        sys.executable,
                        str(script_path),
                        "--data-dir",
                        str(dev_ctx.dev_dir),
                        "--split",
                        "val",
                        "--out",
                        str(pred_path),
                    ],
                    check=True,
                    timeout=hpo_cfg.trial_timeout_s,
                    env=env,
                    capture_output=True,
                )
                pred = __import__("pandas").read_csv(pred_path)
                dev_metrics = score_dev(
                    pred, dev_ctx.dev_split.dev_labels, task_dir / "evaluator.py"
                )
                dev_proxy = dev_metrics["dev_proxy"]
                if config.autotune.cache.enabled:
                    store.upsert_eval_cache(ck, "dev", json.dumps(dev_metrics))
            used_fits += compiled.fits_per_run if not cache_hit else 0
            ledger.settle(
                res,
                CostRecord(
                    seq=0,
                    stage=fit_stage,
                    fidelity="dev",
                    node_id=None,
                    model_fit_count=0 if cache_hit else compiled.fits_per_run,
                    cache_hit=cache_hit,
                    status=status,
                ),
            )
        except Exception as exc:
            status = "failed"
            used_fits += compiled.fits_per_run
            ledger.settle(
                res,
                CostRecord(
                    seq=0,
                    stage=fit_stage,
                    fidelity="dev",
                    node_id=None,
                    model_fit_count=compiled.fits_per_run,
                    status="failed",
                    meta={"error": str(exc)[:200]},
                ),
            )
        trial = Trial(
            trial_id=f"{struct_id[7:15]}-{idx:04d}-{ch[7:15]}",
            structure_id=struct_id,
            index=idx,
            spec=spec,
            seed=spec.train.seed,
            fidelity="dev",
            status=status,
            fit_count=compiled.fits_per_run,
            dev_proxy=dev_proxy,
            dev_metrics=dev_metrics,
            cache_hit=cache_hit,
        )
        row = {
            "trial_id": trial.trial_id,
            "structure_id": struct_id,
            "trial_index": idx,
            "config_hash": ch,
            "params_json": json.dumps(spec.params),
            "seed": spec.train.seed,
            "fidelity": "dev",
            "status": status,
            "fit_count": trial.fit_count,
            "dev_proxy": dev_proxy,
            "dev_metrics": dev_metrics,
            "cache_hit": cache_hit,
        }
        trials.append(trial)
        store.save_hpo_trial(experiment_id, row)
    return trials, used_fits


def select_promoted_trials(trials: list[Trial], promote_top_k: int) -> list[Trial]:
    ok = [t for t in trials if t.status == "ok" and t.dev_proxy is not None]
    ok.sort(key=lambda t: t.dev_proxy or 0.0, reverse=True)
    return ok[:promote_top_k]


def compile_promoted_code(trial: Trial) -> str:
    return compile_spec(trial.spec, TEMPLATE_MAP).code
