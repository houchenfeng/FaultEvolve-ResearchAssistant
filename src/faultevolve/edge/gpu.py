"""GPU side of the local evaluator.

``paired_bootstrap`` resamples the full val split tens of thousands of times on the
GPU to put a noise band on before/after metrics and to estimate P(after > before).
It never replaces the evaluator's official score; it is the significance evidence
sent upstream (as scalars) so the cloud search can tell real gains from noise.
"""

from __future__ import annotations

import shutil
import subprocess
import time
from typing import Any

import numpy as np


def gpu_status() -> dict[str, Any]:
    exe = shutil.which("nvidia-smi")
    if exe is None:
        return {"available": False}
    fields = "name,utilization.gpu,memory.used,memory.total,power.draw,temperature.gpu"
    try:
        out = subprocess.run(
            [exe, f"--query-gpu={fields}", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
        ).stdout.strip().splitlines()[0]
    except Exception:
        return {"available": False}
    name, util, used, total, power, temp = [p.strip() for p in out.split(",")]

    def num(v: str) -> float | None:
        try:
            return float(v)
        except ValueError:
            return None

    return {
        "available": True,
        "name": name,
        "util": num(util),
        "mem_used_mb": num(used),
        "mem_total_mb": num(total),
        "power_w": num(power),
        "temp_c": num(temp),
    }


def _torch_device() -> tuple[Any, Any]:
    import torch

    return torch, torch.device("cuda" if torch.cuda.is_available() else "cpu")


def paired_bootstrap(
    y: np.ndarray,
    w: np.ndarray,
    before: tuple[np.ndarray, np.ndarray],
    after: tuple[np.ndarray, np.ndarray],
    n_boot: int = 20_000,
    chunk: int = 500,
    seed: int = 0,
) -> dict[str, Any]:
    """Poisson bootstrap of weighted F1 and AUPRC for two score/alarm pairs on the same disks."""
    torch, device = _torch_device()
    gen = torch.Generator(device=device).manual_seed(seed)
    yt = torch.as_tensor(np.array(y, dtype=np.float32), device=device)
    wt = torch.as_tensor(np.array(w, dtype=np.float32), device=device)

    prepared = []
    for score, alarm in (before, after):
        order = torch.as_tensor(np.argsort(-np.asarray(score), kind="mergesort"), device=device)
        prepared.append((torch.as_tensor(np.array(alarm, dtype=np.float32), device=device), order))

    def metrics(bw: Any, alarm: Any, order: Any) -> tuple[Any, Any]:
        ww = bw * wt
        pos = ww * yt
        neg = ww * (1 - yt)
        tp = (pos * alarm).sum(1)
        fp = (neg * alarm).sum(1)
        fn = (pos * (1 - alarm)).sum(1)
        f1 = 2 * tp / torch.clamp(2 * tp + fp + fn, min=1e-9)
        pos_o = pos[:, order]
        cum_pos = pos_o.cumsum(1)
        cum_all = ww[:, order].cumsum(1)
        precision = cum_pos / torch.clamp(cum_all, min=1e-9)
        auprc = (precision * pos_o).sum(1) / torch.clamp(pos_o.sum(1), min=1e-9)
        return f1, auprc

    if device.type == "cuda":
        torch.cuda.synchronize()
    started = time.perf_counter()
    f1s: list[list[Any]] = [[], []]
    aps: list[list[Any]] = [[], []]
    done = 0
    while done < n_boot:
        b = min(chunk, n_boot - done)
        bw = torch.poisson(torch.ones((b, len(y)), device=device), generator=gen)
        for k, (alarm, order) in enumerate(prepared):
            f1, ap = metrics(bw, alarm, order)
            f1s[k].append(f1)
            aps[k].append(ap)
        done += b
    if device.type == "cuda":
        torch.cuda.synchronize()
    elapsed = time.perf_counter() - started

    def summary(t: Any) -> dict[str, float]:
        arr = t.double().cpu().numpy()
        return {
            "mean": float(arr.mean()),
            "lo": float(np.percentile(arr, 2.5)),
            "hi": float(np.percentile(arr, 97.5)),
            "p10": float(np.percentile(arr, 10)),
        }

    f1_b, f1_a = torch.cat(f1s[0]), torch.cat(f1s[1])
    ap_b, ap_a = torch.cat(aps[0]), torch.cat(aps[1])
    d_f1 = f1_a - f1_b
    d_ap = ap_a - ap_b
    return {
        "device": torch.cuda.get_device_name(0) if device.type == "cuda" else "cpu",
        "n_boot": n_boot,
        "n_disks": int(len(y)),
        "elapsed_s": round(elapsed, 3),
        "resamples_per_s": round(n_boot / max(elapsed, 1e-9)),
        "f1": {"before": summary(f1_b), "after": summary(f1_a), "delta": summary(d_f1)},
        "auprc": {"before": summary(ap_b), "after": summary(ap_a), "delta": summary(d_ap)},
        "p_improve_f1": float((d_f1 > 0).double().mean().item()),
        "p_improve_auprc": float((d_ap > 0).double().mean().item()),
    }
