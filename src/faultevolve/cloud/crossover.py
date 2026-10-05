"""Crossover partner selection (task-agnostic)."""

from __future__ import annotations

import math
from typing import Any

from faultevolve.common.schemas import Node, OperatorType


def valid_node_count(nodes: dict[str, Node]) -> int:
    return sum(1 for n in nodes.values() if n.is_expandable())


def branch_key(node: Node, nodes: dict[str, Node]) -> str:
    if node.depth == 0:
        return "root"
    current = node
    for _ in range(len(nodes)):
        if current.depth == 1:
            return current.id
        if not current.parent_id:
            break
        parent = nodes.get(current.parent_id)
        if parent is None:
            break
        current = parent
    return node.id


def fn_group_keys(node: Node) -> set[str]:
    evaluation = node.evidence.evaluation
    if evaluation is None:
        return set()
    analysis = evaluation.metric.get("analysis") or {}
    fn_groups = analysis.get("fn_groups") or []
    keys: set[str] = set()
    for item in fn_groups:
        if not isinstance(item, dict):
            continue
        dimension = item.get("dimension")
        value = item.get("value")
        if dimension is None or value is None:
            continue
        keys.add(f"{dimension}={value}")
    return keys


def _numeric_metric_overlap(a: Node, b: Node) -> float:
    ev_a = a.evidence.evaluation
    ev_b = b.evidence.evaluation
    if ev_a is None or ev_b is None:
        return 1.0
    ma = ev_a.metric or {}
    mb = ev_b.metric or {}
    shared: list[float] = []
    for key, va in ma.items():
        if key == "analysis":
            continue
        if key not in mb:
            continue
        vb = mb[key]
        if isinstance(va, bool) or isinstance(vb, bool):
            continue
        if not isinstance(va, (int, float)) or not isinstance(vb, (int, float)):
            continue
        if isinstance(va, float) and math.isnan(va):
            continue
        if isinstance(vb, float) and math.isnan(vb):
            continue
        x, y = float(va), float(vb)
        shared.append(abs(x - y) / (max(abs(x), abs(y)) + 1e-9))
    if not shared:
        return 1.0
    dist = sum(shared) / len(shared)
    return 1.0 - min(1.0, dist)


def complementarity_overlap(a: Node, b: Node) -> float:
    keys_a = fn_group_keys(a)
    keys_b = fn_group_keys(b)
    if keys_a and keys_b:
        inter = len(keys_a & keys_b)
        union = len(keys_a | keys_b)
        return inter / union if union else 1.0
    return _numeric_metric_overlap(a, b)


def estimate_runtime_s(*nodes: Node) -> float:
    total = 0.0
    for node in nodes:
        ev = node.evidence.evaluation
        if ev is None:
            continue
        total += float(ev.cost_time or 0.0)
    return total


def select_crossover_partner(
    node: Node,
    nodes: dict[str, Node],
    *,
    top_quantile: float = 0.3,
) -> Node | None:
    n_valid = valid_node_count(nodes)
    if n_valid == 0:
        return None

    expandable = [n for n in nodes.values() if n.is_expandable()]
    expandable.sort(key=lambda n: (-n.get_score(), n.id))
    k = max(1, math.ceil(top_quantile * n_valid))
    eligible_ids = {n.id for n in expandable[:k]}

    node_branch = branch_key(node, nodes)
    candidates: list[Node] = []
    for cand in nodes.values():
        if not cand.is_expandable():
            continue
        if cand.depth < 1:
            continue
        if cand.operator == OperatorType.INIT:
            continue
        if cand.id == node.id:
            continue
        if branch_key(cand, nodes) == node_branch:
            continue
        if cand.id not in eligible_ids:
            continue
        candidates.append(cand)

    if not candidates:
        return None

    candidates.sort(
        key=lambda c: (
            complementarity_overlap(node, c),
            -c.get_score(),
            c.id,
        )
    )
    return candidates[0]
