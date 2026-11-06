"""Read-only replay of the real cloud evolution run used in the hybrid demo.

The run itself happened on the evolution server; this module only reads its frozen
``tree.json`` / ``run_summary.json`` and re-expresses every evaluated candidate as
the whitelisted packet the local evaluator would have sent back.
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from faultevolve.edge import boundary, paths


@lru_cache(maxsize=1)
def cloud_replay() -> dict[str, Any]:
    tree = json.loads((paths.CLOUD_RUN_DIR / "tree.json").read_text("utf-8"))
    summary = json.loads((paths.CLOUD_RUN_DIR / "run_summary.json").read_text("utf-8"))
    nodes = tree["nodes"]
    by_id = {n["id"]: n for n in nodes}
    parent = {e["target"]: e["source"] for e in tree.get("edges", [])}

    path: list[str] = []
    cursor: str | None = summary.get("best_node_id")
    while cursor is not None and cursor in by_id:
        path.append(cursor)
        cursor = parent.get(cursor)
    path.reverse()

    best_so_far = 0.0
    timeline = []
    packets = []
    for order, node in enumerate(nodes):
        score = float(node.get("score") or 0.0)
        valid = node.get("status") == "done"
        if valid:
            best_so_far = max(best_so_far, score)
        parent_node = by_id.get(parent.get(node["id"], ""), None)
        delta = score - float(parent_node.get("score") or 0.0) if (valid and parent_node) else None
        timeline.append({
            "order": order,
            "id": node["id"],
            "island": node.get("island_id"),
            "depth": node.get("depth"),
            "operator": node.get("operator"),
            "status": node.get("status"),
            "score": round(score, 4) if valid else None,
            "best_so_far": round(best_so_far, 4),
            "on_best_path": node["id"] in path,
            "intent": (node.get("intent") or "")[:220],
        })
        packets.append(boundary.gate("candidate_eval", {
            "candidate_id": node["id"],
            "validity": 1 if valid else 0,
            "combined_score": round(score, 4) if valid else 0.0,
            "delta_vs_parent": round(delta, 4) if delta is not None else None,
            "predictions": "per-disk scores (30754 rows)",
            "labels": "val_labels.csv",
            "smart_rows": "val_history.csv.gz",
        }))

    islands = {
        k: {key: v.get(key) for key in ("profile", "attempts", "valid_evaluations", "best_score", "stop_reason")}
        for k, v in (summary.get("islands") or {}).items()
    }
    return {
        "run_id": paths.CLOUD_RUN_ID,
        "replay": True,
        "note": "云端进化为服务器上的真实运行记录（回放）；本地评估、GPU 检验与白名单出口为本机实时执行。",
        "initial_score": summary.get("initial_score"),
        "best_score": summary.get("best_score"),
        "best_node_id": summary.get("best_node_id"),
        "total_tokens": summary.get("total_tokens"),
        "wall_time_h": round(float(summary.get("wall_time_s") or 0) / 3600, 1),
        "islands": islands,
        "best_path": [
            {"id": i, "score": round(float(by_id[i].get("score") or 0), 4), "operator": by_id[i].get("operator"),
             "island": by_id[i].get("island_id"), "intent": (by_id[i].get("intent") or "")[:220]}
            for i in path
        ],
        "timeline": timeline,
        "packets": packets,
    }
