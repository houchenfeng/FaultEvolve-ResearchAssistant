"""Local sandbox evaluation of one cloud-generated candidate program.

Every candidate is scored twice, both times on this machine only:

* **tablet scene** -- the 300-disk data-hall stream the tablet sends (or, before a
  tablet has streamed, the same ``replay.json`` it would send). The scene is staged
  as the ``test`` split so any program honouring the CLI contract can score it;
  outcome = early warnings vs. the real failures of days 15..21.
* **full val split** -- the official ``evaluator.py`` scoring (ROS), plus a GPU
  paired bootstrap against the parent's per-disk predictions.

Only the scalars of :func:`evaluate_candidate`'s ``packet`` may leave the machine,
and they still go through :func:`faultevolve.edge.boundary.gate`.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from faultevolve.edge import gpu, paths

REPLAY_JSON = paths.REPO_ROOT / "edge-tablet" / "public" / "replay.json"
SCENE_DIR = paths.CACHE_DIR / "tablet_scene"
VAL_DIR = paths.CACHE_DIR / "val_stage"
TRAIN_FILES = ("train_history.csv.gz", "train_labels.csv")

_evaluator_mod: Any = None
_pred_cache: dict[str, pd.DataFrame] = {}
_lock = threading.Lock()


def _evaluator() -> Any:
    global _evaluator_mod
    if _evaluator_mod is None:
        spec = importlib.util.spec_from_file_location("hdd_evaluator", paths.EVALUATOR)
        mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        _evaluator_mod = mod
    return _evaluator_mod


def _sha(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()[:16]


# --------------------------------------------------------------- staging
def _stage_train(target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    for name in TRAIN_FILES:
        dst = target / name
        if not dst.exists():
            shutil.copy2(paths.PUBLIC_DIR / name, dst)


def stage_val() -> Path:
    _stage_train(VAL_DIR)
    for name in ("val_history.csv.gz", "val_index.csv"):
        dst = VAL_DIR / name
        if not dst.exists():
            shutil.copy2(paths.PUBLIC_DIR / name, dst)
    return VAL_DIR


def scene_from_replay() -> dict[str, Any]:
    replay = json.loads(REPLAY_JSON.read_text("utf-8"))
    rows = [(d["sn"], i + 1, v) for d in replay["disks"] for i, v in enumerate(d["days"]) if v is not None]
    return {
        "source": "replay.json（平板同款回放）",
        "columns": replay["columns"],
        "start_date": date.fromisoformat(replay["start_date"]),
        "history_days": int(replay["history_days"]),
        "disks": {d["sn"]: {"model": d["model"], "cap": d["cap"]} for d in replay["disks"]},
        "rows": rows,
        "failures": {d["sn"]: int(d["fail_day"]) for d in replay["disks"] if d.get("fail_day")},
    }


def scene_from_hub(hub: Any) -> dict[str, Any] | None:
    """The live tablet stream, once it has covered the window and the horizon."""
    if hub is None or hub.phase != "done" or not hub.rows:
        return None
    with hub._lock:  # noqa: SLF001 - same package
        return {
            "source": f"平板实时数据流（{hub.device['name'] if hub.device else '边缘设备'}）",
            "columns": list(hub.columns),
            "start_date": hub.start_date,
            "history_days": hub.history_days,
            "disks": {sn: {"model": d["model"], "cap": d["cap"]} for sn, d in hub.disks.items()},
            "rows": [r for r in hub.rows if r[1] <= hub.history_days],
            "failures": dict(hub.failures),
        }


def stage_scene(scene: dict[str, Any]) -> Path:
    key = hashlib.sha256(json.dumps([scene["source"], len(scene["rows"]), sorted(scene["failures"].items())],
                                    default=str).encode()).hexdigest()[:10]
    target = SCENE_DIR / key
    _stage_train(target)
    if (target / "test_index.csv").exists():
        return target
    records = []
    for sn, day, values in scene["rows"]:
        disk = scene["disks"].get(sn, {})
        rec: dict[str, Any] = {
            "date": (scene["start_date"] + timedelta(days=day - 1)).isoformat(),
            "serial_number": sn, "model": disk.get("model", ""), "capacity_bytes": disk.get("cap", 0.0),
        }
        rec.update({c: (np.nan if v is None else v) for c, v in zip(scene["columns"], values)})
        records.append(rec)
    pd.DataFrame.from_records(records).to_csv(target / "test_history.csv.gz", index=False)
    cutoff = (scene["start_date"] + timedelta(days=scene["history_days"] - 1)).isoformat()
    pd.DataFrame({
        "serial_number": list(scene["disks"].keys()),
        "model": [d["model"] for d in scene["disks"].values()],
        "cutoff_date": cutoff,
    }).to_csv(target / "test_index.csv", index=False)
    return target


# --------------------------------------------------------------- running
def run_program(program: Path, data_dir: Path, split: str, timeout: int = 900) -> tuple[pd.DataFrame | None, float, str]:
    ev = _evaluator()
    violation = ev.static_check(program.read_text(encoding="utf-8", errors="ignore"))
    if violation:
        return None, 0.0, f"static check failed: {violation}"
    with tempfile.TemporaryDirectory(prefix="fe_edge_run_") as tmp:
        out = Path(tmp) / "pred.csv"
        cmd = [sys.executable, str(program), "--data-dir", str(data_dir), "--split", split, "--out", str(out)]
        t0 = time.time()
        try:
            proc = subprocess.run(cmd, cwd=str(paths.TASK_DIR), capture_output=True, text=True,
                                  timeout=timeout, encoding="utf-8", errors="replace")
        except subprocess.TimeoutExpired:
            return None, time.time() - t0, f"timeout after {timeout}s"
        elapsed = time.time() - t0
        if proc.returncode != 0:
            return None, elapsed, f"exit {proc.returncode}: {(proc.stderr or proc.stdout)[-800:]}"
        index = pd.read_csv(data_dir / f"{split}_index.csv")
        pred, err = ev.validate_output(out, index)
        return pred, elapsed, err


class GpuSampler:
    """Samples nvidia-smi while an evaluation runs, so the GPU share is evidence, not a claim."""

    def __init__(self, interval: float = 0.5) -> None:
        self.interval = interval
        self.samples: list[dict[str, Any]] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        while not self._stop.is_set():
            s = gpu.gpu_status()
            if s.get("available"):
                self.samples.append({"t": time.time(), "util": s.get("util"), "mem": s.get("mem_used_mb")})
            self._stop.wait(self.interval)

    def __enter__(self) -> "GpuSampler":
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._stop.set()
        self._thread.join(timeout=3)

    def summary(self) -> dict[str, Any]:
        utils = [s["util"] for s in self.samples if s["util"] is not None]
        mems = [s["mem"] for s in self.samples if s["mem"] is not None]
        return {
            "samples": len(self.samples),
            "peak_util": max(utils) if utils else None,
            "mean_util": round(float(np.mean(utils)), 1) if utils else None,
            "peak_mem_mb": max(mems) if mems else None,
            "base_mem_mb": min(mems) if mems else None,
        }


def error_kind(err: str, program_name: str) -> str:
    """Exception class and line in the candidate only: the message may quote data values."""
    if not err:
        return "unknown"
    if err.startswith("static check failed"):
        return "static_check: " + err.split(":", 2)[1].strip()[:60]
    if err.startswith("timeout"):
        return "timeout"
    lines = [ln.strip() for ln in err.splitlines() if ln.strip()]
    line_no = None
    for ln in lines:
        m = re.search(r'File ".*' + re.escape(program_name) + r'", line (\d+)', ln)
        if m:
            line_no = m.group(1)
    exc = next((m.group(1) for ln in reversed(lines) if (m := re.match(r"^([A-Za-z_][\w.]*(?:Error|Exception|Warning))\b", ln))), None)
    if exc is None and not err.startswith("exit "):
        return "invalid_output"
    return f"{exc or 'RuntimeError'}" + (f" @ line {line_no}" if line_no else "")


def _baseline_val_pred() -> pd.DataFrame:
    code = paths.BASELINE_PROGRAM.read_text("utf-8")
    key = _sha(code)
    if key not in _pred_cache:
        pred, _, err = run_program(paths.BASELINE_PROGRAM, stage_val(), "val")
        if pred is None:
            raise RuntimeError(f"baseline failed: {err}")
        _pred_cache[key] = pred
    return _pred_cache[key]


def evaluate_candidate(
    program: Path,
    *,
    parent_code: str | None = None,
    scene: dict[str, Any] | None = None,
    n_boot: int = 100_000,
    progress: Any = None,
) -> dict[str, Any]:
    """Score one candidate locally. Returns local details plus the outbound ``packet``."""
    step = progress or (lambda _s: None)
    ev = _evaluator()
    scene = scene or scene_from_replay()
    started = time.time()
    with _lock, GpuSampler() as sampler:
        step("平板场景打分")
        scene_dir = stage_scene(scene)
        scene_pred, scene_t, scene_err = run_program(program, scene_dir, "test")
        outcome: dict[str, Any] = {"source": scene["source"], "disks": len(scene["disks"]),
                                   "failures": len(scene["failures"])}
        if scene_pred is not None:
            alarmed = set(scene_pred.loc[scene_pred["alarm"] == 1, "serial_number"])
            failed = set(scene["failures"])
            outcome.update({"alarms": len(alarmed), "caught": len(alarmed & failed),
                            "false_alarms": len(alarmed - failed), "run_time_s": round(scene_t, 2)})
        else:
            outcome["error"] = scene_err

        step("完整验证集评估（evaluator.py 打分规则）")
        val_pred, val_t, val_err = run_program(program, stage_val(), "val")
        if val_pred is None:
            err = val_err or scene_err
            return {"valid": False, "error": err, "scene": outcome,
                    "gpu": sampler.summary(), "elapsed_s": round(time.time() - started, 1),
                    "packet": {"validity": 0, "combined_score": 0.0,
                               "error_kind": error_kind(err, program.name)}}
        labels = pd.read_csv(paths.LABELS_DIR / "val_labels.csv")
        quality, metric = ev.score_predictions(val_pred, labels)
        time_factor = min(1.0, ev.TIME_BUDGET_S / max(val_t, 1e-6))
        ros = 100.0 * quality * time_factor
        _pred_cache[_sha(program.read_text("utf-8"))] = val_pred

        step("GPU 配对 bootstrap（对比父代）")
        if parent_code is not None and _sha(parent_code) in _pred_cache:
            parent_pred = _pred_cache[_sha(parent_code)]
            parent_label = "父代"
        else:
            parent_pred = _baseline_val_pred()
            parent_label = "init.py"
        frame = labels.merge(parent_pred, on="serial_number").merge(val_pred, on="serial_number", suffixes=("_p", "_c"))
        boot = gpu.paired_bootstrap(
            frame["label"].to_numpy(), frame["weight"].to_numpy(),
            (frame["score_p"].to_numpy(), frame["alarm_p"].to_numpy()),
            (frame["score_c"].to_numpy(), frame["alarm_c"].to_numpy()),
            n_boot=n_boot, chunk=1000,
        )
        parent_ros = None
        if parent_label == "父代":
            q_p, _ = ev.score_predictions(parent_pred, labels)
            parent_ros = 100.0 * q_p
    gpu_used = sampler.summary()
    noise_band = (boot["f1"]["after"]["hi"] - boot["f1"]["after"]["lo"]) / 2 * 100
    packet = {
        "validity": 1,
        "combined_score": round(ros, 4),
        "f1_p10": metric["f1_p10"],
        "auprc": metric["auprc"],
        "recall_at_far": metric["recall_at_far"],
        "precision": metric["precision"],
        "recall": metric["recall"],
        "false_alarm_rate": metric["false_alarm_rate"],
        "run_time_s": round(val_t, 2),
        "noise_band": round(noise_band, 3),
        "p_improve": round(boot["p_improve_f1"], 4),
        "disks_monitored": outcome["disks"],
        "failures_observed": outcome["failures"],
        "caught": outcome.get("caught"),
        "false_alarms": outcome.get("false_alarms"),
    }
    if parent_ros is not None:
        packet["delta_vs_parent"] = round(ros - parent_ros, 4)
    return {
        "valid": True,
        "ros": round(ros, 4),
        "metric": metric,
        "scene": outcome,
        "bootstrap": {k: boot[k] for k in ("device", "n_boot", "n_disks", "elapsed_s", "resamples_per_s",
                                           "p_improve_f1", "p_improve_auprc")} | {"vs": parent_label},
        "gpu": gpu_used,
        "elapsed_s": round(time.time() - started, 1),
        "packet": packet,
        # Stays local: per-disk predictions on the tablet scene, for the audit panel.
        "scene_alarm_serials": sorted(scene_pred.loc[scene_pred["alarm"] == 1, "serial_number"]) if scene_pred is not None else [],
    }
