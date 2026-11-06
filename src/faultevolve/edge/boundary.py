"""Data-boundary gate: the only path from the local domain to the cloud.

Anything not on the whitelist is dropped and reported by name, so the UI can show
exactly what was withheld. Values must be scalars; arrays and nested objects are
blocked even under a whitelisted key.
"""

from __future__ import annotations

import time
from typing import Any

WHITELIST: dict[str, str] = {
    "candidate_id": "候选编号",
    "validity": "是否有效",
    "combined_score": "ROS 总分",
    "f1_p10": "F1 第 10 百分位",
    "auprc": "AUPRC",
    "recall_at_far": "低误报召回",
    "precision": "精确率",
    "recall": "召回率",
    "false_alarm_rate": "误报率",
    "run_time_s": "推理耗时",
    "noise_band": "噪声带（GPU bootstrap）",
    "delta_vs_parent": "相对父节点增量",
    "p_improve": "提升概率",
    "disks_monitored": "监测盘数",
    "failures_observed": "观测到的故障数",
    "caught": "提前预警命中数",
    "false_alarms": "误报数",
    "error_kind": "失败类型（异常类名 + 行号，不含消息）",
}


def _is_scalar(value: Any) -> bool:
    return value is None or isinstance(value, (bool, int, float, str))


def gate(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    allowed: dict[str, Any] = {}
    blocked: list[dict[str, str]] = []
    for key, value in payload.items():
        if key in WHITELIST and _is_scalar(value):
            allowed[key] = round(value, 5) if isinstance(value, float) else value
        else:
            size = f"{len(value)} 项" if hasattr(value, "__len__") and not isinstance(value, str) else "标量"
            blocked.append({"field": key, "reason": "不在白名单" if key not in WHITELIST else "非标量", "size": size})
    return {
        "kind": kind,
        "at": time.time(),
        "allowed": allowed,
        "allowed_labels": {k: WHITELIST[k] for k in allowed},
        "blocked": blocked,
        "bytes_allowed": len(repr(allowed).encode()),
    }
