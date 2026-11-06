"""Edge hub: ingests the tablet's telemetry stream and runs the local evaluator.

Protocol (JSON text frames over one WebSocket, tablet -> laptop):

* ``hello``      ``{device, columns, history_days, horizon_days, start_date, disks: [{sn, model, cap, rack, slot}]}``
* ``telemetry``  ``{day, rows: [[sn, [v0, v1, ...]], ...]}`` one frame per simulated day
* ``failure``    ``{day, sn}`` a disk failed in the data hall
* ``end``        the replay finished

laptop -> tablet: ``welcome``, ``ack`` (per frame), ``alarms`` (after the last
history day both programs score every disk), ``summary``.
"""

from __future__ import annotations

import asyncio
import json
import socket
import threading
import time
import warnings
from collections import deque
from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd

from faultevolve.edge import boundary, gpu, paths
from faultevolve.edge.models import ModelService

warnings.filterwarnings("ignore", message="X does not have valid feature names")


def lan_addresses() -> list[str]:
    found: list[str] = []
    try:
        infos = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
    except OSError:
        infos = []
    for info in infos:
        ip = str(info[4][0])
        if ip.startswith(("127.", "169.254.", "198.18.", "198.19.")) or ip in found:
            continue
        found.append(ip)
    return found


class EdgeHub:
    def __init__(self) -> None:
        self.models = ModelService()
        self._lock = threading.Lock()
        self.events: deque[dict[str, Any]] = deque(maxlen=150)
        self.uploads: deque[dict[str, Any]] = deque(maxlen=80)
        self.evaluation: dict[str, Any] = {"status": "idle"}
        self._eval_thread: threading.Thread | None = None
        self._sim_task: asyncio.Task[None] | None = None
        self.device: dict[str, Any] | None = None
        self._frame_times: deque[tuple[float, int]] = deque(maxlen=200)
        self._reset_stream()

    # ------------------------------------------------------------------ state
    def _reset_stream(self) -> None:
        self.columns: list[str] = []
        self.disks: dict[str, dict[str, Any]] = {}
        self.rows: list[tuple[str, int, list[float | None]]] = []
        self.day = 0
        self.history_days = 14
        self.horizon_days = 7
        self.start_date = date(2026, 11, 1)
        self.phase = "idle"
        self.alarms: dict[str, Any] | None = None
        self.failures: dict[str, int] = {}
        self.frames = 0
        self.bytes = 0
        self.summary_sent = False

    def log(self, kind: str, text: str) -> None:
        self.events.appendleft({"at": time.time(), "kind": kind, "text": text})

    # --------------------------------------------------------------- protocol
    async def process(self, msg: dict[str, Any], raw_len: int) -> list[dict[str, Any]]:
        kind = msg.get("type")
        if self.device is not None:
            self.device["last_seen"] = time.time()
            self.device["frames"] += 1
            self.device["bytes"] += raw_len
        self._frame_times.append((time.time(), raw_len))

        if kind == "hello":
            return [self._on_hello(msg)]
        if kind == "telemetry":
            return await self._on_telemetry(msg, raw_len)
        if kind == "failure":
            return self._on_failure(msg)
        if kind == "end":
            return self._on_end()
        return []

    def _on_hello(self, msg: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self._reset_stream()
            self.columns = list(msg.get("columns") or [])
            self.history_days = int(msg.get("history_days") or 14)
            self.horizon_days = int(msg.get("horizon_days") or 7)
            try:
                self.start_date = date.fromisoformat(str(msg.get("start_date")))
            except ValueError:
                pass
            for d in msg.get("disks") or []:
                self.disks[str(d["sn"])] = {
                    "model": d.get("model") or "", "cap": float(d.get("cap") or 0),
                    "rack": int(d.get("rack", 0)), "slot": int(d.get("slot", 0)),
                }
            self.phase = "ingesting"
        self.models.ensure_started()
        self.log("link", f"边缘设备握手：{len(self.disks)} 块盘、{len(self.columns)} 个 SMART 字段")
        return {"type": "welcome", "models": self.models.status, "disks": len(self.disks)}

    async def _on_telemetry(self, msg: dict[str, Any], raw_len: int) -> list[dict[str, Any]]:
        day = int(msg.get("day") or 0)
        rows = msg.get("rows") or []
        if not self.disks:
            return [{"type": "need_hello", "day": day}]
        with self._lock:
            for sn, values in rows:
                if values is not None:
                    self.rows.append((str(sn), day, values))
            self.day = max(self.day, day)
            self.frames += 1
            self.bytes += raw_len
        out: list[dict[str, Any]] = [{"type": "ack", "day": day, "rows": len(rows), "bytes": raw_len}]
        if day == self.history_days and self.alarms is None:
            self.phase = "scoring"
            self.log("eval", f"第 {day} 天窗口完整：本地评估器开始为 {len(self.disks)} 块盘打分")
            try:
                out.append(await asyncio.to_thread(self._score_window))
            except Exception as exc:
                self.phase = "ingesting"
                self.log("error", f"本地打分失败：{type(exc).__name__}: {exc}")
                out.append({"type": "error", "text": f"本地打分失败：{exc}"})
        return out

    def _on_failure(self, msg: dict[str, Any]) -> list[dict[str, Any]]:
        sn = str(msg.get("sn"))
        day = int(msg.get("day") or self.day)
        with self._lock:
            self.failures[sn] = day
            self.day = max(self.day, day)
        caught = []
        if self.alarms is not None:
            for key in ("before", "after"):
                if sn in self.alarms[key]:
                    caught.append("进化后" if key == "after" else "进化前")
        tail = f"，{'/'.join(caught)}已提前 {day - self.history_days} 天预警" if caught else "，两个算法均未预警"
        self.log("failure", f"第 {day} 天 {sn} 故障{tail}")
        return [{"type": "ack", "day": day, "failure": sn}]

    def _on_end(self) -> list[dict[str, Any]]:
        self.phase = "done"
        outcome = self.outcome()
        if not self.summary_sent:
            self.summary_sent = True
            for key in ("before", "after"):
                o = outcome[key]
                self.uploads.appendleft(boundary.gate(f"stream_summary_{key}", {
                    "candidate_id": "init" if key == "before" else paths.EVOLVED_NODE_ID,
                    "disks_monitored": len(self.disks),
                    "failures_observed": o["failures"],
                    "caught": o["caught"],
                    "false_alarms": o["false_alarms"],
                    "serial_numbers": [sn for sn in self.disks],
                    "smart_rows": self.rows,
                    "per_disk_scores": self.alarms["scores"][key] if self.alarms else [],
                }))
            self.log("upload", "回放结束：仅聚合统计经白名单回传云端，序列号/SMART 行/逐盘分数被拦截")
        return [{"type": "summary", "outcome": outcome}]

    # ---------------------------------------------------------------- scoring
    def _frames(self) -> tuple[pd.DataFrame, pd.DataFrame]:
        with self._lock:
            rows = list(self.rows)
            disks = dict(self.disks)
            columns = list(self.columns)
        records = []
        for sn, day, values in rows:
            rec: dict[str, Any] = {
                "serial_number": sn,
                "date": pd.Timestamp(self.start_date + timedelta(days=day - 1)),
                "model": disks.get(sn, {}).get("model", ""),
                "capacity_bytes": disks.get(sn, {}).get("cap", 0.0),
            }
            for col, v in zip(columns, values):
                rec[col] = np.nan if v is None else v
            records.append(rec)
        hist = pd.DataFrame.from_records(records)
        for col in columns + ["capacity_bytes"]:
            if col in hist.columns:
                hist[col] = hist[col].astype("float32")
        cutoff = pd.Timestamp(self.start_date + timedelta(days=self.history_days - 1))
        cutoffs = pd.DataFrame({
            "serial_number": list(disks.keys()),
            "model": [d["model"] for d in disks.values()],
            "cutoff_date": cutoff,
        })
        return hist, cutoffs

    def _score_window(self) -> dict[str, Any]:
        started = time.perf_counter()
        bundle = self.models.get()
        hist, cutoffs = self._frames()
        pred_before = bundle.before.predict(hist.copy(), cutoffs)
        pred_after = bundle.after.predict(hist.copy(), cutoffs)
        elapsed = time.perf_counter() - started
        alarms = {
            "before": [s for s, a in zip(pred_before.serials, pred_before.alarms) if a],
            "after": [s for s, a in zip(pred_after.serials, pred_after.alarms) if a],
            "scores": {
                "before": {s: round(float(p), 5) for s, p in zip(pred_before.serials, pred_before.scores)},
                "after": {s: round(float(p), 5) for s, p in zip(pred_after.serials, pred_after.scores)},
            },
            "day": self.history_days,
            "elapsed_s": round(elapsed, 2),
        }
        with self._lock:
            self.alarms = alarms
            self.phase = "observing"
        self.log("eval", f"打分完成（{elapsed:.1f}s）：进化前预警 {len(alarms['before'])} 块，进化后预警 {len(alarms['after'])} 块；预警已回推平板")
        return {"type": "alarms", "day": self.history_days, "before": alarms["before"], "after": alarms["after"],
                "elapsed_s": alarms["elapsed_s"]}

    # ---------------------------------------------------------------- outcome
    def outcome(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        finished = self.phase == "done"
        for key in ("before", "after"):
            alarmed = set(self.alarms[key]) if self.alarms else set()
            failed = set(self.failures)
            result[key] = {
                "alarms": len(alarmed),
                "failures": len(failed),
                "caught": len(alarmed & failed),
                "missed": len(failed - alarmed),
                "false_alarms": len(alarmed - failed) if finished else None,
                "pending": len(alarmed - failed) if not finished else 0,
            }
        return result

    def snapshot(self) -> dict[str, Any]:
        now = time.time()
        recent = [(t, n) for t, n in self._frame_times if now - t <= 5.0]
        with self._lock:
            alarms = self.alarms
            grid = []
            for sn, d in self.disks.items():
                grid.append({
                    "sn": sn, "rack": d["rack"], "slot": d["slot"], "model": d["model"],
                    "before": bool(alarms and sn in alarms["before"]),
                    "after": bool(alarms and sn in alarms["after"]),
                    "failed_day": self.failures.get(sn),
                })
            failures = [
                {"sn": sn, "day": day, **{k: self.disks.get(sn, {}).get(k) for k in ("rack", "slot", "model")},
                 "caught_before": bool(alarms and sn in alarms["before"]),
                 "caught_after": bool(alarms and sn in alarms["after"]),
                 "lead_days": day - self.history_days}
                for sn, day in sorted(self.failures.items(), key=lambda kv: kv[1])
            ]
            stream = {
                "phase": self.phase, "day": self.day, "history_days": self.history_days,
                "horizon_days": self.horizon_days, "start_date": self.start_date.isoformat(),
                "frames": self.frames, "bytes": self.bytes, "rows": len(self.rows), "disks": len(self.disks),
                "rate_bps": round(sum(n for _, n in recent) / 5.0),
                "scored_in_s": alarms["elapsed_s"] if alarms else None,
            }
        device = dict(self.device) if self.device else None
        if device is not None:
            device["online"] = device.get("connected", False) and now - device.get("last_seen", 0) < 15
        return {
            "device": device,
            "stream": stream,
            "grid": grid,
            "failures": failures,
            "outcome": self.outcome(),
            "models": self.models.describe(),
            "events": list(self.events)[:60],
            "uploads": list(self.uploads)[:30],
            "evaluation_status": self.evaluation.get("status"),
            "lan_ips": lan_addresses(),
            "data_boundary": {
                "kept_local": ["原始 SMART 遥测行", "训练集与验证集标签", "逐盘预测分数与告警名单", "模型权重与评估代码"],
                "whitelist": list(boundary.WHITELIST.values()),
            },
        }

    # --------------------------------------------------------------- devices
    def attach(self, name: str, addr: str) -> None:
        self.device = {"name": name, "addr": addr, "connected": True, "connected_at": time.time(),
                       "last_seen": time.time(), "frames": 0, "bytes": 0}
        self.log("link", f"{name}（{addr}）已接入本地评估域")

    def detach(self) -> None:
        if self.device is not None:
            self.device["connected"] = False
            self.log("link", f"{self.device['name']} 断开")

    # ------------------------------------------------------------- simulator
    def start_simulation(self, day_seconds: float = 1.0) -> bool:
        if self._sim_task is not None and not self._sim_task.done():
            return False
        self._sim_task = asyncio.get_running_loop().create_task(self._simulate(day_seconds))
        return True

    async def _simulate(self, day_seconds: float) -> None:
        replay_path = paths.REPO_ROOT / "edge-tablet" / "public" / "replay.json"
        replay = json.loads(replay_path.read_text("utf-8"))
        self.attach("本机模拟器", "127.0.0.1")

        async def send(msg: dict[str, Any]) -> None:
            raw = json.dumps(msg, ensure_ascii=False, separators=(",", ":"))
            await self.process(msg, len(raw.encode()))

        try:
            await send({
                "type": "hello", "device": "本机模拟器", "columns": replay["columns"],
                "history_days": replay["history_days"], "horizon_days": replay["horizon_days"],
                "start_date": replay["start_date"],
                "disks": [{k: d[k] for k in ("sn", "model", "cap", "rack", "slot")} for d in replay["disks"]],
            })
            for day in range(1, replay["history_days"] + 1):
                rows = [[d["sn"], d["days"][day - 1]] for d in replay["disks"] if d["days"][day - 1] is not None]
                await send({"type": "telemetry", "day": day, "rows": rows})
                await asyncio.sleep(day_seconds)
            for day in range(replay["history_days"] + 1, replay["history_days"] + replay["horizon_days"] + 1):
                for d in replay["disks"]:
                    if d.get("fail_day") == day:
                        await send({"type": "failure", "day": day, "sn": d["sn"]})
                with self._lock:
                    self.day = day
                await asyncio.sleep(day_seconds)
            await send({"type": "end"})
        finally:
            self.detach()

    # ----------------------------------------------------------- evaluation
    def start_evaluation(self) -> bool:
        if self._eval_thread is not None and self._eval_thread.is_alive():
            return False
        self.evaluation = {"status": "running", "started_at": time.time(), "step": "准备模型"}
        self._eval_thread = threading.Thread(target=self._evaluate, name="fe-edge-eval", daemon=True)
        self._eval_thread.start()
        return True

    def _evaluate(self) -> None:
        from faultevolve.worker.runner import load_evaluator

        try:
            bundle = self.models.get()
            evaluator = load_evaluator(paths.EVALUATOR)
            official: dict[str, Any] = {}
            for key, program in (("before", paths.BASELINE_PROGRAM), ("after", paths.EVOLVED_PROGRAM)):
                self.evaluation["step"] = f"沙箱评估 {program.name}（evaluator.py，完整 val 切分）"
                official[key] = dict(evaluator.evaluate(str(program), split="val"))

            self.evaluation["step"] = "GPU 配对 bootstrap 显著性检验"
            labels = pd.read_csv(paths.LABELS_DIR / "val_labels.csv")
            frame = labels.merge(bundle.val_before.frame(), on="serial_number").merge(
                bundle.val_after.frame(), on="serial_number", suffixes=("_b", "_a"))
            boot = gpu.paired_bootstrap(
                frame["label"].to_numpy(), frame["weight"].to_numpy(),
                (frame["score_b"].to_numpy(), frame["alarm_b"].to_numpy()),
                (frame["score_a"].to_numpy(), frame["alarm_a"].to_numpy()),
            )

            after_metric = official["after"].get("metric", {})
            noise_band = (boot["f1"]["after"]["hi"] - boot["f1"]["after"]["lo"]) / 2 * 100
            packet = boundary.gate("candidate_eval", {
                "candidate_id": paths.EVOLVED_NODE_ID,
                "validity": official["after"].get("validity"),
                "combined_score": official["after"].get("combined_score"),
                "f1_p10": after_metric.get("f1_p10"),
                "auprc": after_metric.get("auprc"),
                "recall_at_far": after_metric.get("recall_at_far"),
                "run_time_s": after_metric.get("run_time_s"),
                "noise_band": round(noise_band, 3),
                "delta_vs_parent": round(float(official["after"]["combined_score"]) - float(official["before"]["combined_score"]), 4),
                "p_improve": boot["p_improve_f1"],
                "per_disk_predictions": frame[["serial_number", "score_a", "alarm_a"]].to_dict("records"),
                "val_labels": "eval_only/val_labels.csv",
                "model_weights": f"{len(bundle.after.models)} LightGBM boosters",
                "evaluator_source": "evaluator.py",
            })
            self.uploads.appendleft(packet)
            self.log("upload", f"评估回传：ROS {official['after']['combined_score']:.2f}、噪声带 ±{noise_band:.2f}；逐盘预测/标签/权重被拦截")
            self.evaluation = {
                "status": "done", "finished_at": time.time(),
                "official": {k: {"combined_score": v.get("combined_score"), "validity": v.get("validity"),
                                 "metric": v.get("metric", {}), "error": v.get("error_info")}
                             for k, v in official.items()},
                "bootstrap": boot,
                "packet": packet,
            }
        except Exception as exc:
            self.evaluation = {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
            self.log("error", f"本地评估失败：{exc}")


HUB = EdgeHub()
