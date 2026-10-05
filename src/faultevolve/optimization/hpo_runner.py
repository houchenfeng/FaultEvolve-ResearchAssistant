"""Driver for structured HPO without LLM."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from faultevolve.cloud.store import Store
from faultevolve.config import EvolveConfig
from faultevolve.optimization.cache import cache_key, data_version_from_paths, env_fingerprint
from faultevolve.optimization.candidate_spec import (
    CandidateSpec,
    compile_spec,
    config_hash,
    structure_hash,
)
from faultevolve.optimization.ledger import CostLedger, CostRecord
from faultevolve.optimization.parameter_space import validate_values
from faultevolve.optimization.search import RandomSearch
from faultevolve.optimization.trials import Trial
from faultevolve.tasks.hdd_dev import build_dev_task_dir, make_hdd_dev_split, score_dev
from faultevolve.tasks.hdd_space import default_spec, lightgbm_space, logreg_space
from faultevolve.tasks.hdd_templates import TEMPLATE_MAP
from faultevolve.tasks.protocol import EvalResult, TaskAdapter, TaskSpec


@dataclass
class HpoResult:
    experiment_id: str
    best_code: str | None
    stop_reason: str
    trials_path: Path


def _space_for_family(family: str):
    return logreg_space() if family == "logreg" else lightgbm_space()


def run_hpo(
    task_dir: Path,
    config: EvolveConfig,
    *,
    runs_dir: Path,
    artifacts_dir: Path,
    adapter: TaskAdapter | None = None,
    experiment_id: str | None = None,
    mock_eval: bool = False,
) -> HpoResult:
    if not config.autotune.hpo.enabled:
        raise ValueError("autotune.hpo.enabled is false")
    hpo_cfg = config.autotune.hpo
    ledger = CostLedger(full_eval_cap=config.autotune.ledger.full_eval_cap)
    runs_dir.mkdir(parents=True, exist_ok=True)
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    hpo_art = artifacts_dir / "hpo"
    hpo_art.mkdir(parents=True, exist_ok=True)
    db_path = runs_dir / "fe.db"
    store = Store(db_path)
    experiment_id = experiment_id or uuid.uuid4().hex[:8]

    public = task_dir / "data" / "public"
    data_ver = data_version_from_paths(
        [public / "train_labels.csv", public / "train_history.csv.gz"]
    )
    evaluator_hash = "mock" if mock_eval else "task"
    env_fp = env_fingerprint(hpo_cfg.threads)
    searcher = RandomSearch(config.seed)
    used_fits = 0
    trials_out: list[dict[str, Any]] = []
    best_trial: Trial | None = None

    try:
        dev_split = make_hdd_dev_split(
            task_dir,
            late_fraction=hpo_cfg.dev.dev_late_fraction,
            purge_days=hpo_cfg.dev.purge_days,
        )
    except Exception as exc:
        return HpoResult(experiment_id, None, f"split_refused:{exc}", hpo_art / "trials.jsonl")

    history_path = public / "train_history.csv.gz"
    dev_dir = build_dev_task_dir(task_dir, dev_split, history_path)

    for family in hpo_cfg.families:
        base = default_spec(family)
        struct_id = structure_hash(base)
        space = _space_for_family(family)
        proposals = searcher.propose(
            space,
            structure_id=struct_id,
            start_index=0,
            n=hpo_cfg.trials_per_structure,
        )
        for idx, params in enumerate(proposals):
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
                data_version=data_ver,
                evaluator_hash=evaluator_hash,
                fidelity="dev",
                seed=spec.train.seed,
                env_fingerprint=env_fp,
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
            res = ledger.reserve("hpo_fit", est_model_fits=compiled.fits_per_run)
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
                            str(dev_dir),
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
                    dev_metrics = score_dev(pred, dev_split.dev_labels, task_dir / "evaluator.py")
                    dev_proxy = dev_metrics["dev_proxy"]
                    if config.autotune.cache.enabled:
                        store.upsert_eval_cache(ck, "dev", json.dumps(dev_metrics))
                used_fits += compiled.fits_per_run if not cache_hit else 0
                ledger.settle(
                    res,
                    CostRecord(
                        seq=0,
                        stage="hpo_fit",
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
                        stage="hpo_fit",
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
            if best_trial is None or (
                dev_proxy is not None
                and (best_trial.dev_proxy is None or dev_proxy > best_trial.dev_proxy)
            ):
                best_trial = trial
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
            trials_out.append(row)
            store.save_hpo_trial(experiment_id, row)

    best_code = None
    if best_trial is not None:
        best_code = compile_spec(best_trial.spec, TEMPLATE_MAP).code
        (hpo_art / "best.py").write_text(best_code, encoding="utf-8")
    trials_path = hpo_art / "trials.jsonl"
    with trials_path.open("w", encoding="utf-8") as f:
        for row in trials_out:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    summary = {
        "experiment_id": experiment_id,
        "stop_reason": "completed",
        "ledger": ledger.totals().to_dict(),
        "trials": len(trials_out),
        "used_fits": used_fits,
    }
    (hpo_art / "hpo_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return HpoResult(experiment_id, best_code, "completed", trials_path)
