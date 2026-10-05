"""Insight extraction and propagation for FaultEvolve.

Handles:
- Extracting insights from parent-child comparisons using reasoning model
- Three-layer reflection (implementation, design, hypothesis)
- Managing branch memory
- Cross-branch knowledge propagation
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Any

from faultevolve.common.metering import CallMetrics
from faultevolve.common.schemas import BranchMemory, Insight, Node
from faultevolve.common.textutil import (
    extract_json_from_response,
    sanitize_error_info,
    truncate_text,
    unified_diff,
)
from faultevolve.cloud.llm import DashScopeLLM, MockLLM, create_llm_call_record
from faultevolve.cloud.store import Store, now_iso
from faultevolve.cloud.tree import Tree


LAYERED_REFLECTION_PROMPT = """分析以下代码变更，判断分数变化的原因所在的层次。

## 父方案
分数：{parent_score:.2f}
分项指标：{parent_metric}

## 子方案
分数：{child_score:.2f}
分项指标：{child_metric}
错误信息：{error_info}

## 代码变更（截断至约6000字符）
```diff
{diff}
```

## 变更意图
{intent}

## 变更假设
{hypothesis}

请判断分数变化的原因，严格按以下 JSON 格式输出：
```json
{{
  "layer": "implementation|design|hypothesis",
  "change_summary": "简明描述做了什么改动（20字内）",
  "mechanism": "解释为什么这个改动会影响分数",
  "conditions": "这个改动有效的前提条件",
  "tags": ["类别标签，如 feature:trend, model:gbdt, threshold:tuning"],
  "affects": {{"recall": "+|-|0", "false_alarm_rate": "+|-|0"}},
  "causes": [
    {{"cause": "原因1", "layer": "implementation|design|hypothesis", "confidence": 0.8, "evidence": "证据"}}
  ]
}}
```

层次定义：
- implementation: 语法错误、运行时错误、超时、格式不合规
- design: 想法正确但实现有问题（如阈值选择不当、特征计算错误）
- hypothesis: 假设本身有问题（如错误的因果假设）

只输出 JSON，不要其他内容。"""

MECHANISM_LAYER_HINT = (
    "\n层次定义补充：\n"
    "- mechanism: 机理/因果假设被数据否证（与实现或设计错误不同）\n"
    "layer 可为 implementation|design|hypothesis|mechanism。"
)


def summarize_error_profile_diff(
    parent_analysis: dict[str, Any] | None,
    child_analysis: dict[str, Any] | None,
) -> dict[str, Any]:
    """Compare parent/child aggregated FN group profiles (task-agnostic)."""
    if not parent_analysis or not child_analysis:
        return {}

    def _fn_key(group: dict[str, Any]) -> tuple[str, str]:
        return (str(group.get("dimension", "")), str(group.get("value", "")))

    parent_fn = parent_analysis.get("fn_groups") or []
    child_fn = child_analysis.get("fn_groups") or []
    parent_top = {_fn_key(g) for g in parent_fn}
    child_top = {_fn_key(g) for g in child_fn}

    child_by_key = {_fn_key(g): g for g in child_fn}
    parent_by_key = {_fn_key(g): g for g in parent_fn}

    new_top_fn_groups = [
        child_by_key[k] for k in sorted(child_top - parent_top) if k in child_by_key
    ]
    no_longer_top_fn_groups = [
        parent_by_key[k] for k in sorted(parent_top - child_top) if k in parent_by_key
    ]

    share_delta: list[dict[str, Any]] = []
    for key in sorted(parent_top & child_top):
        p_share = float(parent_by_key[key].get("share", 0.0))
        c_share = float(child_by_key[key].get("share", 0.0))
        share_delta.append({
            "dimension": key[0],
            "value": key[1],
            "share_delta": c_share - p_share,
        })

    dev_delta: dict[str, float] = {}
    p_dev = parent_analysis.get("dev_metrics") or {}
    c_dev = child_analysis.get("dev_metrics") or {}
    for field in set(p_dev) & set(c_dev):
        try:
            dev_delta[field] = float(c_dev[field]) - float(p_dev[field])
        except (TypeError, ValueError):
            continue

    return {
        "new_top_fn_groups": new_top_fn_groups,
        "no_longer_top_fn_groups": no_longer_top_fn_groups,
        "share_delta": share_delta,
        "dev_metrics_delta": dev_delta,
    }


class LayeredReflector:
    """Perform layered reflection using reasoning model.

    Implementation layer uses rules (no LLM).
    Design and hypothesis layers use the reasoning model for analysis.
    """

    def __init__(
        self,
        llm: DashScopeLLM | MockLLM,
        experiment_id: str,
        mechanism_layer: bool = False,
    ) -> None:
        """Initialize the reflector.

        Args:
            llm: LLM client for reasoning
            experiment_id: Experiment ID for logging
        """
        self.llm = llm
        self.experiment_id = experiment_id
        self.mechanism_layer = mechanism_layer
        self.total_reflect_tokens = 0

    def reflect_implementation(
        self,
        parent: Node,
        child: Node,
        error_info: str,
    ) -> dict[str, Any]:
        """Implementation layer reflection - rule-based, no LLM.

        Args:
            parent: Parent node
            child: Child node
            error_info: Error message

        Returns:
            Reflection result with layer="implementation"
        """
        sanitized_error = sanitize_error_info(error_info, max_chars=500)

        causes = []
        if "syntax" in error_info.lower():
            causes.append({
                "cause": "Syntax error in generated code",
                "layer": "implementation",
                "confidence": 1.0,
                "evidence": sanitized_error[:100],
            })
        elif "timeout" in error_info.lower():
            causes.append({
                "cause": "Execution timeout",
                "layer": "implementation",
                "confidence": 1.0,
                "evidence": "Exceeded time limit",
            })
        elif "static check" in error_info.lower():
            causes.append({
                "cause": "Static check violation",
                "layer": "implementation",
                "confidence": 1.0,
                "evidence": sanitized_error[:100],
            })
        else:
            causes.append({
                "cause": "Runtime or validation error",
                "layer": "implementation",
                "confidence": 0.9,
                "evidence": sanitized_error[:100],
            })

        return {
            "layer": "implementation",
            "change_summary": "Implementation error",
            "mechanism": "Code failed to execute correctly",
            "conditions": "",
            "tags": ["error:implementation"],
            "affects": {"recall": "0", "false_alarm_rate": "0"},
            "causes": causes[:3],
            "repair_hint": sanitized_error,
        }

    def reflect_with_llm(
        self,
        parent: Node,
        child: Node,
        delta: float,
        noise_delta: float,
    ) -> tuple[dict[str, Any], CallMetrics]:
        """Design/hypothesis layer reflection using reasoning model.

        Args:
            parent: Parent node
            child: Child node
            delta: Score change
            noise_delta: Noise threshold

        Returns:
            Tuple of (reflection_result, metrics)
        """
        parent_eval = parent.evidence.evaluation
        child_eval = child.evidence.evaluation

        if parent_eval is None or child_eval is None:
            return self._default_reflection(delta, noise_delta), CallMetrics()

        diff = unified_diff(
            parent.artifact.code,
            child.artifact.code,
            max_chars=6000,
        )

        error_info = sanitize_error_info(
            child_eval.error_info or "", max_chars=300
        )

        parent_analysis = parent_eval.metric.get("analysis") if parent_eval.metric else None
        child_analysis = child_eval.metric.get("analysis") if child_eval.metric else None
        profile_diff = summarize_error_profile_diff(parent_analysis, child_analysis)
        profile_diff_section = ""
        if profile_diff:
            diff_json = json.dumps(profile_diff, ensure_ascii=False, sort_keys=True)
            profile_diff_section = (
                "\n## 聚合错例画像变化\n"
                "不再位于 top 列表仅表示可能修复，不证明因果。\n"
                f"```json\n{truncate_text(diff_json, 2000)}\n```\n"
            )

        prompt = LAYERED_REFLECTION_PROMPT.format(
            parent_score=parent_eval.combined_score,
            parent_metric=json.dumps(parent_eval.metric, ensure_ascii=False),
            child_score=child_eval.combined_score,
            child_metric=json.dumps(child_eval.metric, ensure_ascii=False),
            error_info=error_info or "(none)",
            diff=diff,
            intent=child.artifact.intent or "(none)",
            hypothesis=child.artifact.hypothesis or "(none)",
        ) + profile_diff_section
        if self.mechanism_layer:
            prompt += MECHANISM_LAYER_HINT

        messages = [{"role": "user", "content": prompt}]

        try:
            response, metrics = self.llm.chat_for_reasoning(messages, temperature=0.2)
            self.total_reflect_tokens += metrics.prompt_tokens + metrics.completion_tokens

            result = self._parse_reflection_json(response, delta, noise_delta)
            return result, metrics

        except Exception:
            return self._default_reflection(delta, noise_delta), CallMetrics()

    def _parse_reflection_json(
        self,
        response: str,
        delta: float,
        noise_delta: float,
    ) -> dict[str, Any]:
        """Parse JSON from LLM response with fallback."""
        json_str = extract_json_from_response(response)

        if json_str is None:
            return self._default_reflection(delta, noise_delta)

        try:
            data = json.loads(json_str)

            layer = data.get("layer", "design")
            allowed = ("implementation", "design", "hypothesis", "mechanism")
            if layer not in allowed:
                layer = "design" if delta > -noise_delta * 2 else "hypothesis"
            if layer == "mechanism" and not self.mechanism_layer:
                layer = "design"

            causes = data.get("causes", [])
            if not isinstance(causes, list):
                causes = []
            causes = causes[:3]

            for cause in causes:
                if not isinstance(cause, dict):
                    continue
                if "confidence" in cause:
                    try:
                        cause["confidence"] = float(cause["confidence"])
                    except (ValueError, TypeError):
                        cause["confidence"] = 0.5

            return {
                "layer": layer,
                "change_summary": str(data.get("change_summary", ""))[:100],
                "mechanism": str(data.get("mechanism", ""))[:500],
                "conditions": str(data.get("conditions", ""))[:200],
                "tags": data.get("tags", [])[:5] if isinstance(data.get("tags"), list) else [],
                "affects": data.get("affects", {}),
                "causes": causes,
            }

        except json.JSONDecodeError:
            return self._default_reflection(delta, noise_delta)

    def _default_reflection(self, delta: float, noise_delta: float) -> dict[str, Any]:
        """Generate default reflection when parsing fails."""
        if delta < -noise_delta * 2:
            layer = "hypothesis"
        elif delta < -noise_delta:
            layer = "design"
        else:
            layer = "design"

        return {
            "layer": layer,
            "change_summary": "Score change analysis",
            "mechanism": f"Score changed by {delta:.2f}",
            "conditions": "",
            "tags": [],
            "affects": {},
            "causes": [{
                "cause": "Unable to determine specific cause",
                "layer": layer,
                "confidence": 0.3,
                "evidence": f"Delta={delta:.2f}, threshold={noise_delta:.2f}",
            }],
        }


class InsightExtractor:
    """Extract insights from node comparisons."""

    def __init__(self, llm: DashScopeLLM | MockLLM) -> None:
        """Initialize the extractor.

        Args:
            llm: LLM client for reasoning
        """
        self.llm = llm

    def extract(
        self,
        parent: Node,
        child: Node,
        delta: float,
        noise_delta: float,
    ) -> tuple[Insight | None, CallMetrics]:
        """Extract an insight from a parent-child comparison.

        Args:
            parent: Parent node
            child: Child node
            delta: Score change (child - parent)
            noise_delta: Threshold for significance

        Returns:
            Tuple of (insight, metrics). Insight is None if extraction failed.
        """
        parent_eval = parent.evidence.evaluation
        child_eval = child.evidence.evaluation

        if parent_eval is None or child_eval is None:
            return None, CallMetrics()

        reflector = LayeredReflector(self.llm, parent.experiment_id)
        reflection, metrics = reflector.reflect_with_llm(parent, child, delta, noise_delta)

        z_score = delta / noise_delta if noise_delta > 0 else 0.0

        insight = Insight(
            id=str(uuid.uuid4())[:8],
            origin_node=child.id,
            branch_id=child.branch_id,
            polarity=1 if delta > 0 else -1,
            change_summary=reflection.get("change_summary", ""),
            mechanism=reflection.get("mechanism", ""),
            conditions=reflection.get("conditions", ""),
            tags=reflection.get("tags", []),
            delta=delta,
            z_score=z_score,
            alpha=1.0,
            beta=1.0,
            created_at=now_iso(),
        )

        return insight, metrics


class BranchMemoryManager:
    """Manage branch memory for nodes."""

    def __init__(
        self,
        store: Store,
        tree: Tree,
        top_k: int = 5,
    ) -> None:
        """Initialize the manager.

        Args:
            store: Database store
            tree: Evolution tree
            top_k: Number of top insights to keep per node
        """
        self.store = store
        self.tree = tree
        self.top_k = top_k

    def propagate_insight(
        self,
        insight: Insight,
        child_node: Node,
        experiment_id: str,
    ) -> None:
        """Propagate an insight up the ancestor chain.

        Adds the insight to each ancestor's branch memory,
        keeping only top-k by |z-score|.

        Args:
            insight: The insight to propagate
            child_node: The node where the insight originated
            experiment_id: Experiment ID
        """
        self.store.create_insight(insight, experiment_id)

        ancestors = self.tree.get_ancestors(child_node.id)

        for ancestor in ancestors:
            current_ids = list(ancestor.branch_memory.top_insight_ids)

            if insight.id not in current_ids:
                current_ids.append(insight.id)

            insights = self.store.get_insights_by_experiment(experiment_id)
            insight_map = {i.id: i for i in insights}

            valid_ids = [iid for iid in current_ids if iid in insight_map]

            sorted_ids = sorted(
                valid_ids,
                key=lambda iid: abs(insight_map[iid].z_score),
                reverse=True,
            )

            top_ids = sorted_ids[: self.top_k]

            new_memory = BranchMemory(
                summary=ancestor.branch_memory.summary,
                top_insight_ids=top_ids,
                refuted_hypotheses=ancestor.branch_memory.refuted_hypotheses,
            )
            self.tree.update_branch_memory(ancestor.id, new_memory)

    def get_branch_insights(
        self,
        node: Node,
        experiment_id: str,
    ) -> list[Insight]:
        """Get insights from the branch memory of a node."""
        insight_ids = node.branch_memory.top_insight_ids
        if not insight_ids:
            return []

        all_insights = self.store.get_insights_by_experiment(experiment_id)
        insight_map = {i.id: i for i in all_insights}

        return [insight_map[iid] for iid in insight_ids if iid in insight_map]


def get_foreign_insights(
    node: Node,
    store: Store,
    experiment_id: str,
    top_k_positive: int = 3,
    top_k_negative: int = 3,
    use_reputation: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Get relevant insights from other branches.

    Hook for KGTE cross-branch transfer.
    Currently returns empty lists - will be implemented
    with Jev applicability scoring.

    Args:
        node: Target node
        store: Database store
        experiment_id: Experiment ID
        top_k_positive: Max positive insights to return
        top_k_negative: Max negative insights to return

    Returns:
        Tuple of (positive_insights, negative_insights)
    """
    all_insights = store.get_insights_by_experiment(experiment_id)

    ancestor_ids = set()
    current = node
    while current is not None:
        ancestor_ids.add(current.id)
        if current.parent_id:
            parent = store.get_node(current.parent_id)
            if parent:
                current = parent
            else:
                break
        else:
            break

    foreign = [i for i in all_insights if i.branch_id != node.branch_id]

    used_ids = set()
    for aid in ancestor_ids:
        n = store.get_node(aid)
        if n:
            used_ids.update(n.insight_ids)

    foreign = [i for i in foreign if i.id not in used_ids]

    positive = [i for i in foreign if i.polarity > 0]
    negative = [i for i in foreign if i.polarity < 0]

    def _rank_key(ins: Insight) -> float:
        if use_reputation:
            denom = ins.alpha + ins.beta
            rep = 2 * ins.alpha / denom if denom > 0 else 0.0
            return abs(ins.z_score) * rep
        return abs(ins.z_score)

    positive = sorted(positive, key=_rank_key, reverse=True)[:top_k_positive]
    negative = sorted(negative, key=_rank_key, reverse=True)[:top_k_negative]

    return (
        [i.to_dict() for i in positive],
        [i.to_dict() for i in negative],
    )


def update_insight_reputation(
    insight_id: str,
    success: bool,
    store: Store,
    experiment_id: str,
) -> None:
    """Update an insight's reputation based on usage outcome."""
    insights = store.get_insights_by_experiment(experiment_id)
    if not any(i.id == insight_id for i in insights):
        return
    store.update_insight_beta(
        insight_id,
        experiment_id,
        1.0 if success else 0.0,
        0.0 if success else 1.0,
    )


def record_mechanism_insight(
    store: Store,
    experiment_id: str,
    m: Any,
    claim_origin_node: str,
    e_value: float,
    rival_title: str,
) -> Insight:
    """Record a refuted mechanism as a cross-branch negative insight."""
    import math

    from faultevolve.discovery.schemas import Mechanism

    if not isinstance(m, Mechanism):
        m = Mechanism.model_validate(m)
    insight = Insight(
        id=str(uuid.uuid4())[:8],
        origin_node=claim_origin_node,
        branch_id="__mechanism__",
        polarity=-1,
        change_summary="[MECH] " + m.title[:80],
        mechanism=f"被数据否证：优于它的对手 {rival_title}",
        conditions="",
        tags=["mechanism"],
        delta=0.0,
        z_score=min(math.log(max(e_value, 1.0)), 10.0),
        created_at=now_iso(),
    )
    store.create_insight(insight, experiment_id)
    return insight
