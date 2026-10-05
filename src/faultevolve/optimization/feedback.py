"""Feedback bundle construction for evolution prompts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Mapping

from faultevolve.cloud.operators import get_error_tail
from faultevolve.common.schemas import Node
from faultevolve.config import FeedbackConfig


@dataclass
class FeedbackBundle:
    components: dict[str, float | None]
    parent_delta_components: dict[str, float | None]
    fn_fp_groups: list[dict] | None
    analysis_status: Literal["computed", "not_computed"]
    error_tail: str | None
    timing: dict[str, float | int | None]
    change_scope: dict
    intent: str
    hypothesis: str
    paired: dict | None
    missing: list[str] = field(default_factory=list)


def _metric_components(node: Node) -> dict[str, float | None]:
    ev = node.evidence.evaluation
    if ev is None:
        return {}
    m = ev.metric or {}
    keys = ("auprc", "recall_at_far", "f1_p10", "time_factor")
    return {k: m.get(k) for k in keys}


def build_feedback(
    parent: Node,
    child: Node,
    *,
    dev_preds: Mapping[str, Any] | None,
    config: FeedbackConfig,
) -> FeedbackBundle:
    child_m = _metric_components(child)
    parent_m = _metric_components(parent)
    delta = {k: None for k in child_m}
    for k, v in child_m.items():
        pv = parent_m.get(k)
        if v is not None and pv is not None:
            delta[k] = float(v) - float(pv)
    analysis = (child.evidence.evaluation.metric.get("analysis") if child.evidence.evaluation else None) or None
    analysis_status: Literal["computed", "not_computed"] = (
        "computed" if analysis else "not_computed"
    )
    missing: list[str] = []
    if analysis_status == "not_computed":
        missing.append("analysis")
    paired = None
    if dev_preds and "parent" in dev_preds and "child" in dev_preds:
        paired = dev_preds.get("paired")
    else:
        missing.append("paired_unavailable")
    err = None
    if child.evidence.evaluation and child.evidence.evaluation.error_info:
        err = get_error_tail(child.evidence.evaluation.error_info)
    timing = {
        "eval_cost_time": child.evidence.evaluation.cost_time if child.evidence.evaluation else None,
        "fit_count": child.evidence.evaluation.metric.get("fit_count") if child.evidence.evaluation else None,
    }
    scope = {
        "operator": child.operator.value,
        "module": child.evidence.evaluation.metric.get("patch_module") if child.evidence.evaluation else None,
    }
    return FeedbackBundle(
        components=child_m,
        parent_delta_components=delta,
        fn_fp_groups=analysis.get("fn_groups") if isinstance(analysis, dict) else None,
        analysis_status=analysis_status,
        error_tail=err,
        timing=timing,
        change_scope=scope,
        intent=child.artifact.intent,
        hypothesis=child.artifact.hypothesis,
        paired=paired,
        missing=missing,
    )


_TRUNC_MARK = "\n…（反馈已截断）"


def render_feedback(bundle: FeedbackBundle, *, max_chars: int) -> str:
    lines: list[str] = []
    lines.append("## 结构化反馈")
    if bundle.analysis_status == "not_computed":
        lines.append("错例画像未计算；请勿要求根据 FN/FP 画像群体做定向修改。")
    lines.append(f"假设：{bundle.hypothesis}")
    lines.append(f"意图：{bundle.intent}")
    if bundle.components:
        lines.append("子节点分项：" + ", ".join(f"{k}={v}" for k, v in bundle.components.items()))
    if bundle.parent_delta_components:
        lines.append(
            "分项变化："
            + ", ".join(f"{k}={v}" for k, v in bundle.parent_delta_components.items() if v is not None)
        )
    if bundle.paired:
        lines.append(
            f"成对 dev 证据：n_common={bundle.paired.get('n_common')} "
            f"delta={bundle.paired.get('delta_dev_proxy')} "
            f"ci=({bundle.paired.get('ci_low')}, {bundle.paired.get('ci_high')}) "
            f"method={bundle.paired.get('method')}"
        )
    elif "paired_unavailable" in bundle.missing:
        lines.append("未提供成对 dev 证据，勿用单边分数差下结论。")
    if bundle.error_tail:
        lines.append("错误尾部：\n" + bundle.error_tail)
    text = "\n".join(lines)
    if len(text) > max_chars:
        text = text[: max_chars - len(_TRUNC_MARK)] + _TRUNC_MARK
    return text
