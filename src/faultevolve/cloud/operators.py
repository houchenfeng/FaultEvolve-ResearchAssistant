"""Evolution operators for FaultEvolve.

Implements refine operator with prompt templates.
Hooks provided for inject and transplant operators.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any

import re

from faultevolve.discovery.claims import extract_claim_from_response
from faultevolve.common.codecheck import (
    extract_adopted_cards_from_response,
    extract_code_from_response,
    extract_hypothesis_from_response,
    extract_intent_from_response,
)
from faultevolve.common.precheck import get_error_fix_hint
from faultevolve.common.metering import CallMetrics
from faultevolve.common.schemas import Node, OperatorType
from faultevolve.common.textutil import format_metric_summary, truncate_text, unified_diff
from faultevolve.cloud.llm import DashScopeLLM, MockLLM
from faultevolve.tasks.protocol import TaskSpec


def classify_error(error_info: str) -> str:
    """Classify an error by exception type and library frame.

    Ignores *Warning lines and uses the final exception line of the traceback.

    Args:
        error_info: Error traceback or message

    Returns:
        Error class string like "TypeError@lightgbm" or "TimeoutError"
    """
    if not error_info:
        return "UnknownError"

    exception_type = "RuntimeError"
    library = ""

    lines = error_info.strip().split("\n")
    filtered_lines = [
        ln for ln in lines
        if not re.search(r"\w+Warning:", ln)
    ]

    final_exception_line = ""
    for line in reversed(filtered_lines):
        line = line.strip()
        if re.match(r"(\w+Error|\w+Exception):", line):
            final_exception_line = line
            break

    search_text = final_exception_line if final_exception_line else error_info

    type_match = re.search(r"(\w+Error|\w+Exception):", search_text)
    if type_match:
        exception_type = type_match.group(1)
    elif "timeout" in error_info.lower():
        exception_type = "TimeoutError"

    lib_patterns = [
        (r"lightgbm", "lightgbm"),
        (r"sklearn", "sklearn"),
        (r"pandas", "pandas"),
        (r"numpy", "numpy"),
        (r"scipy", "scipy"),
    ]
    for pattern, lib_name in lib_patterns:
        if re.search(pattern, error_info, re.IGNORECASE):
            library = lib_name
            break

    if library:
        return f"{exception_type}@{library}"
    return exception_type


def get_error_tail(error_info: str, max_lines: int = 40) -> str:
    """Get the last N lines of an error traceback.

    Args:
        error_info: Full error output
        max_lines: Maximum number of lines to return

    Returns:
        Truncated error tail
    """
    lines = error_info.strip().split("\n")
    if len(lines) <= max_lines:
        return error_info
    return "\n".join(lines[-max_lines:])


OPERATOR_INSTRUCTIONS = {
    OperatorType.REFINE: """针对错例画像中最主要的误告或漏告来源，做最小必要修改以提升 ROS。
重点关注：漏告率较高的厂商或型号、误告中占比最高的特征模式。
如果之前的修改导致了分数下降，避免重复相同的策略。""",
    OperatorType.RECALL_FOCUS: """依据"聚合错例画像"中的漏告（fn_groups）分组，只修改特征工程或模型部分，
以提高这些分组的召回；禁止修改告警阈值、告警数量或告警策略相关代码。""",
    OperatorType.THRESHOLD_CALIBRATE: """只修改告警/阈值决策部分，保持特征和模型不变。
可选做法：(a) 在训练集上用折外(OOF)预测选择使评估目标最优的阈值；
(b) 按待评估数据的无标签得分分布分位数确定告警比例。
禁止读取任何标签文件，禁止改动特征工程或模型结构。""",
    OperatorType.INJECT: """把知识卡片中的方法落地到父方案中，保留父方案中已经有效的部分。
谨慎修改，确保新方法与现有代码兼容。必须采纳下方唯一一张知识卡片并在 adopted_cards 中声明其 ID。""",
    OperatorType.TRANSPLANT: """把待移植经验应用到父方案中，按父方案的技术栈做必要适配。
注意适用条件是否满足，不要强行移植不适合的方法。""",
    OperatorType.CROSSOVER: """将下面两份父方案合成为一个自包含程序（rank-average 或 stacking，优先共享特征计算）。
保持与任务一致的输出格式与硬约束；禁止读取标签文件以外的数据。
合成程序的总运行时间必须小于 {runtime_budget_s:.0f} 秒。""",
    OperatorType.REPAIR: """修复代码中的运行时错误或超时问题，使其能正常执行。
仔细阅读错误信息，针对性地修改代码。保持原有的算法逻辑，只修复导致错误的部分。""",
    OperatorType.PATCH: """只输出一个 <patch> 块，使用 SEARCH/REPLACE 在单个模块内做最小修改。
禁止输出完整程序；禁止修改 FE-BLOCK 标记行。""",
}

USER_MESSAGE_TEMPLATE = """{objective_brief_section}## 父方案（ROS={score:.2f}）
分项指标：{metric_summary}

```python
{parent_code}
```

{error_profile_section}
{branch_memory_section}
{refuted_hypotheses_section}
{repair_hint_section}
{foreign_positive_section}
{foreign_negative_section}{mechanism_context_section}
{knowledge_cards_section}
{transplant_insight_section}
{constraints_section}
## 任务
{operator_instruction}

输出格式（严格遵守）：
<hypothesis>用 1-2 句话说明你的假设：改什么、为什么能提分</hypothesis>
<intent>不超过 3 行的变更意图</intent>
{adopted_cards_instruction}
```python
完整可运行的程序（不要省略任何代码）
```"""


CROSSOVER_USER_TEMPLATE = """{objective_brief_section}## 父方案 A（ROS={score_a:.2f}）
分项指标：{metric_a}

```python
{code_a}
```

## 父方案 B（ROS={score_b:.2f}）
分项指标：{metric_b}

```python
{code_b}
```

## 互补性线索
{complement_section}

## 运行时间
{runtime_section}

{constraints_section}
## 任务
{operator_instruction}

输出格式（严格遵守）：
<hypothesis>用 1-2 句话说明你的假设：如何集成两方案、为什么能提分</hypothesis>
<intent>不超过 3 行的变更意图</intent>
```python
完整可运行的程序（不要省略任何代码）
```"""


REPAIR_PROMPT_TEMPLATE = """## 失败的代码

```python
{failing_code}
```

## 错误信息（最后 {error_lines} 行）

```
{error_tail}
```

{error_fix_hint_section}
## 父方案（可运行，ROS={parent_score:.2f}）

```python
{parent_code}
```

{avoidance_notes_section}
{constraints_section}
## 任务
修复上面失败的代码中的错误，使其能正常运行。
- 仔细分析错误信息，找出导致错误的具体原因
- 只修改必要的部分来修复错误，保持原有的算法逻辑
- 如果是参数名错误，请查阅正确的 API 用法
- 如果是数据类型错误，确保类型转换正确

输出格式（严格遵守）：
<hypothesis>简述错误原因和修复方法</hypothesis>
<intent>不超过 3 行的修复意图</intent>

```python
完整可运行的修复后程序（不要省略任何代码）
```"""


DISCOVER_CLAIM_SUFFIX = """
在 <intent> 之后、代码块之前，额外输出一行：
<claim>{"title":"...","condition":"...","feature_code":"def feature(history): ...","outcome":"...","direction":"+"或"-","scope":"...","falsifier":"...","category":"feature_engineering","tags":[]}</claim>
feature_code 必须包含 def feature(history): 并返回按 unit 索引的 pandas Series。
"""


class OperatorContext:
    """Context for generating prompts."""

    def __init__(
        self,
        node: Node,
        task_spec: TaskSpec,
        operator: OperatorType = OperatorType.REFINE,
    ) -> None:
        """Initialize context.

        Args:
            node: Parent node to improve
            task_spec: Task specification
            operator: Type of operator to apply
        """
        self.node = node
        self.task_spec = task_spec
        self.operator = operator

        self.error_profile: dict[str, Any] = {}
        self.branch_memory_summary: str = ""
        self.refuted_hypotheses: list[str] = []
        self.repair_hint: str = ""
        self.foreign_positive: list[dict[str, Any]] = []
        self.foreign_negative: list[dict[str, Any]] = []
        self.knowledge_card: dict[str, Any] | None = None
        self.knowledge_cards: list[dict[str, Any]] = []
        self.transplant_insight: dict[str, Any] | None = None
        self.constraints: str = ""
        self.objective_brief: str = ""
        self.discover_claim: bool = False
        self.mechanism_context: list[dict[str, Any]] = []
        self.partner: Node | None = None
        self.runtime_budget_s: float = 300.0
        self.crossover_max_chars: int = 6000
        self.target_module: str = ""
        self.feedback_text: str = ""

    def set_target_module(self, name: str) -> "OperatorContext":
        self.target_module = name
        return self

    def set_feedback_text(self, text: str) -> "OperatorContext":
        self.feedback_text = text
        return self

    def set_partner(
        self,
        node: Node,
        runtime_budget_s: float = 300.0,
        max_chars: int = 6000,
    ) -> "OperatorContext":
        self.partner = node
        self.runtime_budget_s = runtime_budget_s
        self.crossover_max_chars = max_chars
        return self

    def set_mechanism_context(self, items: list[dict[str, Any]]) -> "OperatorContext":
        self.mechanism_context = items
        return self

    def set_discover_claim(self, flag: bool) -> "OperatorContext":
        self.discover_claim = flag
        return self

    def set_objective_brief(self, brief: str) -> "OperatorContext":
        """Set evaluator-aware objective brief for generation prompts."""
        self.objective_brief = brief
        return self

    def set_error_profile(self, profile: dict[str, Any]) -> "OperatorContext":
        """Set error profile from evaluation analysis."""
        self.error_profile = profile
        return self

    def set_branch_memory(self, summary: str) -> "OperatorContext":
        """Set branch memory summary."""
        self.branch_memory_summary = summary
        return self

    def set_refuted_hypotheses(self, hypotheses: list[str]) -> "OperatorContext":
        """Set list of refuted hypotheses to avoid."""
        self.refuted_hypotheses = hypotheses
        return self

    def set_repair_hint(self, hint: str) -> "OperatorContext":
        """Set repair hint from previous failure."""
        self.repair_hint = hint
        return self

    def set_foreign_insights(
        self,
        positive: list[dict[str, Any]],
        negative: list[dict[str, Any]],
    ) -> "OperatorContext":
        """Set foreign branch insights.

        Hook for cross-branch knowledge propagation.
        """
        self.foreign_positive = positive
        self.foreign_negative = negative
        return self

    def set_knowledge_card(self, card: dict[str, Any]) -> "OperatorContext":
        """Set knowledge card for inject operator (single card, legacy).

        Hook for ERA-style knowledge injection.
        """
        self.knowledge_card = card
        return self

    def set_knowledge_cards(self, cards: list[dict[str, Any]]) -> "OperatorContext":
        """Set knowledge cards for refine/inject operators (multiple cards).

        ERA-style knowledge injection with multiple cards.
        """
        self.knowledge_cards = cards
        return self

    def set_transplant_insight(self, insight: dict[str, Any]) -> "OperatorContext":
        """Set insight for transplant operator."""
        self.transplant_insight = insight
        return self

    def set_constraints(self, constraints: str) -> "OperatorContext":
        """Set task constraints to be injected into prompts."""
        self.constraints = constraints
        return self


def build_system_message(task_spec: TaskSpec) -> str:
    """Build the system message from task prompt."""
    return task_spec.prompt_md


def _fn_groups_preview(node: Node, limit: int = 3) -> list[str]:
    evaluation = node.evidence.evaluation
    if evaluation is None:
        return []
    analysis = evaluation.metric.get("analysis") or {}
    fn_groups = analysis.get("fn_groups") or []
    lines: list[str] = []
    for item in fn_groups[:limit]:
        if not isinstance(item, dict):
            continue
        dimension = item.get("dimension")
        value = item.get("value")
        recall = item.get("group_recall")
        if dimension is None or value is None:
            continue
        lines.append(f"{dimension}={value}, group_recall={recall}")
    return lines


def build_crossover_message(ctx: OperatorContext) -> str:
    from faultevolve.cloud.crossover import estimate_runtime_s

    parent = ctx.node
    partner = ctx.partner
    if partner is None:
        raise ValueError("crossover requires partner")

    pe = parent.evidence.evaluation
    se = partner.evidence.evaluation
    score_a = pe.combined_score if pe else 0.0
    score_b = se.combined_score if se else 0.0
    metric_a = format_metric_summary(pe.metric if pe else {})
    metric_b = format_metric_summary(se.metric if se else {})

    raw_a = parent.artifact.code
    raw_b = partner.artifact.code
    code_a = truncate_text(raw_a, ctx.crossover_max_chars)
    code_b = truncate_text(raw_b, ctx.crossover_max_chars)
    trunc_note = ""
    if len(raw_a) > ctx.crossover_max_chars or len(raw_b) > ctx.crossover_max_chars:
        trunc_note = "（部分代码已截断，请保留关键函数并补全为可运行程序）\n"

    lines_a = _fn_groups_preview(parent)
    lines_b = _fn_groups_preview(partner)
    if lines_a or lines_b:
        complement_section = (
            f"父 A fn_groups：{'; '.join(lines_a) or '无'}\n"
            f"父 B fn_groups：{'; '.join(lines_b) or '无'}"
        )
    else:
        complement_section = "无画像，按分项指标互补"

    est = estimate_runtime_s(parent, partner)
    budget = ctx.runtime_budget_s
    if est > budget:
        runtime_section = (
            f"两者运行时间之和约 {est:.0f}s，超过 {budget:.0f}s，"
            "必须共享特征计算或只保留一个模型。"
        )
    else:
        runtime_section = f"总运行时间必须小于 {budget:.0f}s。"

    objective_brief_section = ""
    if ctx.objective_brief:
        objective_brief_section = (
            f"## 评估目标与权衡\n{truncate_text(ctx.objective_brief, 2000)}\n\n"
        )

    constraints_section = ""
    if ctx.constraints:
        constraints_section = f"""## 硬约束（必须遵守）
{ctx.constraints}
"""

    base_instr = OPERATOR_INSTRUCTIONS[OperatorType.CROSSOVER]
    operator_instruction = base_instr.format(runtime_budget_s=budget)
    if trunc_note:
        operator_instruction = trunc_note + operator_instruction

    return CROSSOVER_USER_TEMPLATE.format(
        objective_brief_section=objective_brief_section,
        score_a=score_a,
        metric_a=metric_a,
        code_a=code_a,
        score_b=score_b,
        metric_b=metric_b,
        code_b=code_b,
        complement_section=complement_section,
        runtime_section=runtime_section,
        constraints_section=constraints_section,
        operator_instruction=operator_instruction,
    )


def build_user_message(ctx: OperatorContext) -> str:
    """Build the user message for the LLM."""
    if ctx.operator == OperatorType.CROSSOVER and ctx.partner is not None:
        return build_crossover_message(ctx)

    node = ctx.node
    eval_result = node.evidence.evaluation

    score = eval_result.combined_score if eval_result else 0.0
    metric = eval_result.metric if eval_result else {}
    metric_summary = format_metric_summary(metric)

    objective_brief_section = ""
    if ctx.objective_brief:
        objective_brief_section = (
            f"## 评估目标与权衡\n{truncate_text(ctx.objective_brief, 2000)}\n\n"
        )

    error_profile_section = ""
    if ctx.error_profile:
        import json
        profile_str = json.dumps(
            ctx.error_profile, indent=2, ensure_ascii=False, sort_keys=True,
        )
        error_profile_section = (
            "## 聚合错例画像（本地统计）\n"
            "聚合画像只作改进线索，不代表因果关系。\n"
            f"```json\n{truncate_text(profile_str, 3000)}\n```\n"
        )

    branch_memory_section = ""
    if ctx.branch_memory_summary:
        branch_memory_section = f"## 本分支经验\n{ctx.branch_memory_summary}\n"

    refuted_hypotheses_section = ""
    if ctx.refuted_hypotheses:
        refuted_list = "\n".join(f"- {h}" for h in ctx.refuted_hypotheses[:5])
        refuted_hypotheses_section = f"## 已证伪的假设（避免重复）\n{refuted_list}\n"

    repair_hint_section = ""
    if ctx.repair_hint:
        repair_hint_section = f"## 修复提示（上次失败原因）\n{ctx.repair_hint}\n"

    foreign_positive_section = ""
    if ctx.foreign_positive:
        items = []
        for insight in ctx.foreign_positive[:3]:
            items.append(f"- {insight.get('change_summary', '')}: {insight.get('mechanism', '')} (Δ={insight.get('delta', 0):.2f})")
        foreign_positive_section = f"## 其他分支已验证有效的做法\n" + "\n".join(items) + "\n"

    foreign_negative_section = ""
    if ctx.foreign_negative:
        items = []
        for insight in ctx.foreign_negative[:3]:
            items.append(f"- {insight.get('change_summary', '')}: {insight.get('mechanism', '')}")
        foreign_negative_section = f"## 其他分支已证伪的做法（避免重复）\n" + "\n".join(items) + "\n"

    mechanism_context_section = ""
    if ctx.mechanism_context:
        lines = []
        for item in ctx.mechanism_context[:3]:
            title = item.get("title", "")
            n_cert = item.get("certificates", 0)
            text = str(item.get("text", ""))[:200]
            lines.append(f"- {title}（证书 {n_cert} 张）：{text}")
        mechanism_context_section = (
            "## 已成立的机理（数据裁决，可作为设计依据）\n"
            "<mechanism_context>\n"
            + "\n".join(lines)
            + "\n</mechanism_context>\n"
        )

    knowledge_cards_section = ""
    if ctx.knowledge_cards:
        cards_text = []
        for card in ctx.knowledge_cards:
            card_text = f"""- **{card.get('id', '')}**: {card.get('title', '')}
  - 核心思想：{card.get('claim', card.get('idea', ''))}
  - 落地提示：{card.get('impl_hint', '')}
  - 风险：{card.get('risk', '')}"""
            cards_text.append(card_text)
        if ctx.operator == OperatorType.INJECT:
            cards_header = "## 知识卡片（必须采纳）"
        else:
            cards_header = "## 知识卡片（可选采纳）"
        knowledge_cards_section = f"""{cards_header}
以下是与当前方案相关的领域知识，如果采纳了某个卡片的方法，请在输出中声明。

<knowledge_cards>
{chr(10).join(cards_text)}
</knowledge_cards>
"""
    elif ctx.knowledge_card and ctx.operator == OperatorType.INJECT:
        card = ctx.knowledge_card
        knowledge_cards_section = f"""## 知识卡片（仅 inject）
标题：{card.get('title', '')}
来源：{card.get('source', '')}
核心思想：{card.get('idea', '')}
落地提示：{card.get('impl_hint', '')}
风险：{card.get('risk', '')}
"""

    transplant_insight_section = ""
    if ctx.transplant_insight and ctx.operator == OperatorType.TRANSPLANT:
        insight = ctx.transplant_insight
        transplant_insight_section = f"""## 待移植经验（仅 transplant）
变更摘要：{insight.get('change_summary', '')}
机制：{insight.get('mechanism', '')}
适用条件：{insight.get('conditions', '')}
"""

    constraints_section = ""
    if ctx.constraints:
        constraints_section = f"""## 硬约束（必须遵守）
{ctx.constraints}
"""

    adopted_cards_instruction = ""
    if ctx.knowledge_cards:
        if ctx.operator == OperatorType.INJECT:
            adopted_cards_instruction = (
                f"<adopted_cards>{ctx.knowledge_cards[0]['id']}</adopted_cards>"
                "（必须采纳，不可留空）\n"
            )
        else:
            adopted_cards_instruction = (
                "<adopted_cards>采纳的卡片ID，用逗号分隔，如 FE01,M01；未采纳则留空</adopted_cards>\n"
            )

    operator_instruction = OPERATOR_INSTRUCTIONS.get(ctx.operator, OPERATOR_INSTRUCTIONS[OperatorType.REFINE])
    if ctx.discover_claim:
        operator_instruction = operator_instruction + DISCOVER_CLAIM_SUFFIX

    feedback_section = ""
    if ctx.feedback_text:
        feedback_section = f"## 反馈\n{ctx.feedback_text}\n"
    if ctx.target_module:
        operator_instruction = (
            f"目标模块：{ctx.target_module}\n" + operator_instruction
        )

    return USER_MESSAGE_TEMPLATE.format(
        objective_brief_section=objective_brief_section,
        score=score,
        metric_summary=metric_summary,
        parent_code=truncate_text(node.artifact.code, 8000),
        error_profile_section=error_profile_section,
        branch_memory_section=branch_memory_section,
        refuted_hypotheses_section=refuted_hypotheses_section,
        repair_hint_section=repair_hint_section + feedback_section,
        foreign_positive_section=foreign_positive_section,
        foreign_negative_section=foreign_negative_section,
        mechanism_context_section=mechanism_context_section,
        knowledge_cards_section=knowledge_cards_section,
        transplant_insight_section=transplant_insight_section,
        constraints_section=constraints_section,
        operator_instruction=operator_instruction,
        adopted_cards_instruction=adopted_cards_instruction,
    )


@dataclass
class GenerationResult:
    """Result of code generation."""
    code: str | None
    intent: str
    hypothesis: str
    adopted_cards: list[str]
    metrics: CallMetrics
    claim: dict | None = None


class RefineOperator:
    """Operator for refining a solution based on error analysis."""

    def __init__(self, llm: DashScopeLLM | MockLLM) -> None:
        """Initialize the operator.

        Args:
            llm: LLM client for code generation
        """
        self.llm = llm

    def generate(
        self,
        ctx: OperatorContext,
        max_retries: int = 1,
    ) -> tuple[str | None, str, str, CallMetrics]:
        """Generate a refined solution (legacy signature).

        Args:
            ctx: Operator context with parent node and task info
            max_retries: Max retries on parse failure

        Returns:
            Tuple of (code, intent, hypothesis, metrics)
            Code is None if generation/parsing failed.
        """
        result = self.generate_with_adoption(ctx, max_retries)
        return result.code, result.intent, result.hypothesis, result.metrics

    def generate_with_adoption(
        self,
        ctx: OperatorContext,
        max_retries: int = 1,
    ) -> GenerationResult:
        """Generate a refined solution with knowledge card adoption tracking.

        Args:
            ctx: Operator context with parent node and task info
            max_retries: Max retries on parse failure

        Returns:
            GenerationResult with code, intent, hypothesis, adopted_cards, and metrics
        """
        system_msg = build_system_message(ctx.task_spec)
        user_msg = build_user_message(ctx)

        messages = [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg},
        ]

        total_metrics = CallMetrics()

        for attempt in range(max_retries + 1):
            response, metrics = self.llm.chat(messages)

            total_metrics.prompt_tokens += metrics.prompt_tokens
            total_metrics.completion_tokens += metrics.completion_tokens
            total_metrics.latency_ms += metrics.latency_ms

            code = extract_code_from_response(response)
            intent = extract_intent_from_response(response)
            hypothesis = extract_hypothesis_from_response(response)
            adopted_cards = extract_adopted_cards_from_response(response)
            claim_dict = None
            if ctx.discover_claim:
                claim_dict = extract_claim_from_response(response)

            if code is not None:
                return GenerationResult(
                    code=code,
                    intent=intent,
                    hypothesis=hypothesis,
                    adopted_cards=adopted_cards,
                    metrics=total_metrics,
                    claim=claim_dict,
                )

            if attempt < max_retries:
                messages.append({"role": "assistant", "content": response})
                messages.append({
                    "role": "user",
                    "content": "请按照指定格式输出：<hypothesis>...</hypothesis>、<intent>...</intent>、```python...```",
                })

        return GenerationResult(
            code=None,
            intent=intent,
            hypothesis=hypothesis,
            adopted_cards=[],
            metrics=total_metrics,
        )


class PatchOperator:
    """SEARCH/REPLACE patch operator."""

    def __init__(self, llm: DashScopeLLM | MockLLM) -> None:
        self.llm = llm

    def generate_with_adoption(
        self,
        ctx: OperatorContext,
        *,
        static_check,
        patch_cfg,
        on_reject,
        on_applied,
        on_proposed,
        max_retries: int = 0,
    ) -> GenerationResult:
        from faultevolve.optimization.patching import Patch, PatchResult, apply_patch, parse_patch, source_hash

        system_msg = build_system_message(ctx.task_spec)
        user_msg = build_user_message(ctx)
        messages = [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg},
        ]
        total_metrics = CallMetrics()
        response, metrics = self.llm.chat(messages)
        total_metrics.prompt_tokens += metrics.prompt_tokens
        total_metrics.completion_tokens += metrics.completion_tokens
        total_metrics.latency_ms += metrics.latency_ms
        parsed = parse_patch(response)
        if isinstance(parsed, PatchResult):
            on_reject(
                {
                    "parent_id": ctx.node.id,
                    "reason": parsed.reason.value if parsed.reason else "parse_error",
                    "module": parsed.module,
                    "detail": (parsed.detail or "")[:400],
                }
            )
            return GenerationResult(
                code=None,
                intent=parsed.reason.value if parsed.reason else "patch_rejected",
                hypothesis="",
                adopted_cards=[],
                metrics=total_metrics,
            )
        patch: Patch = parsed
        on_proposed(
            {
                "parent_id": ctx.node.id,
                "module": patch.module,
                "hunks": len(patch.hunks),
            }
        )
        result = apply_patch(
            ctx.node.artifact.code,
            patch,
            static_check=static_check,
            max_hunks=patch_cfg.max_hunks,
            max_changed_lines=patch_cfg.max_changed_lines,
        )
        if not result.ok:
            on_reject(
                {
                    "parent_id": ctx.node.id,
                    "reason": result.reason.value if result.reason else "parse_error",
                    "module": result.module,
                    "detail": (result.detail or "")[:400],
                }
            )
            return GenerationResult(
                code=None,
                intent=result.reason.value if result.reason else "patch_rejected",
                hypothesis="",
                adopted_cards=[],
                metrics=total_metrics,
            )
        on_applied(
            {
                "parent_id": ctx.node.id,
                "module": patch.module,
                "changed_lines": result.changed_lines,
            }
        )
        return GenerationResult(
            code=result.code,
            intent=f"patch:{patch.module}",
            hypothesis=f"局部编辑模块 {patch.module}",
            adopted_cards=[],
            metrics=total_metrics,
        )


class CrossoverOperator:
    """Operator that merges two parent programs into one."""

    def __init__(self, llm: DashScopeLLM | MockLLM) -> None:
        self.llm = llm

    def generate(
        self,
        parent_a: Node,
        parent_b: Node,
        ctx: OperatorContext,
        max_retries: int = 1,
    ) -> GenerationResult:
        if ctx.node is not parent_a:
            raise ValueError("ctx.node must be parent_a for crossover")
        ctx.set_partner(parent_b, ctx.runtime_budget_s, ctx.crossover_max_chars)
        ctx.operator = OperatorType.CROSSOVER
        return RefineOperator(self.llm).generate_with_adoption(ctx, max_retries)


class RepairOperator:
    """Operator for repairing a failed candidate.

    Sends the failing code, error tail, and parent code to the LLM
    with a repair-focused prompt.
    """

    def __init__(self, llm: DashScopeLLM | MockLLM) -> None:
        """Initialize the operator.

        Args:
            llm: LLM client for code generation
        """
        self.llm = llm

    def generate(
        self,
        failing_code: str,
        error_info: str,
        parent_node: Node,
        task_spec: TaskSpec,
        avoidance_notes: list[str] | None = None,
        max_retries: int = 1,
        constraints: str = "",
    ) -> tuple[str | None, str, str, CallMetrics]:
        """Generate a repaired solution.

        Args:
            failing_code: Code that failed to run
            error_info: Error traceback/message
            parent_node: The working parent node
            task_spec: Task specification
            avoidance_notes: Notes about known error patterns to avoid
            max_retries: Max retries on parse failure
            constraints: Task-specific constraints to inject into prompt

        Returns:
            Tuple of (code, intent, hypothesis, metrics)
            Code is None if generation/parsing failed.
        """
        error_tail = get_error_tail(error_info, max_lines=40)
        parent_score = parent_node.get_score()

        avoidance_section = ""
        if avoidance_notes:
            notes_text = "\n".join(f"- {note}" for note in avoidance_notes[:5])
            avoidance_section = f"## 已知需要避免的错误模式\n{notes_text}\n\n"

        constraints_section = ""
        if constraints:
            constraints_section = f"## 硬约束（必须遵守）\n{constraints}\n\n"

        error_fix_hint = get_error_fix_hint(error_info)
        error_fix_hint_section = ""
        if error_fix_hint:
            error_fix_hint_section = f"## 已知修复方法\n{error_fix_hint}\n\n"

        user_msg = REPAIR_PROMPT_TEMPLATE.format(
            failing_code=truncate_text(failing_code, 6000),
            error_tail=error_tail,
            error_lines=min(40, len(error_info.split("\n"))),
            parent_code=truncate_text(parent_node.artifact.code, 6000),
            parent_score=parent_score,
            avoidance_notes_section=avoidance_section,
            constraints_section=constraints_section,
            error_fix_hint_section=error_fix_hint_section,
        )

        system_msg = build_system_message(task_spec)
        messages = [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg},
        ]

        total_metrics = CallMetrics()

        for attempt in range(max_retries + 1):
            response, metrics = self.llm.chat(messages)

            total_metrics.prompt_tokens += metrics.prompt_tokens
            total_metrics.completion_tokens += metrics.completion_tokens
            total_metrics.latency_ms += metrics.latency_ms

            code = extract_code_from_response(response)
            intent = extract_intent_from_response(response)
            hypothesis = extract_hypothesis_from_response(response)

            if code is not None:
                return code, intent, hypothesis, total_metrics

            if attempt < max_retries:
                messages.append({"role": "assistant", "content": response})
                messages.append({
                    "role": "user",
                    "content": "请按照指定格式输出：<hypothesis>...</hypothesis>、<intent>...</intent>、```python...```",
                })

        return None, intent, hypothesis, total_metrics


def fn_profile_keywords(analysis: dict, max_groups: int = 3) -> list[str]:
    """Extract lowercase keywords from FN group profile for card retrieval."""
    keywords: list[str] = []
    seen: set[str] = set()

    for group in analysis.get("fn_groups", [])[:max_groups]:
        if not isinstance(group, dict):
            continue
        dimension = group.get("dimension")
        value = group.get("value")
        if dimension is None or value is None:
            continue
        dim = str(dimension).lower()
        val = str(value).lower()
        for token in (dim, val):
            if token and token not in seen:
                seen.add(token)
                keywords.append(token)

    return keywords


def operator_posterior_summary(
    rows: dict[str, dict[str, float]],
) -> dict[str, dict[str, float]]:
    """Summarize operator Beta posteriors for run summary."""
    summary: dict[str, dict[str, float]] = {}
    for op, row in rows.items():
        alpha = float(row.get("alpha", 1.0))
        beta = float(row.get("beta", 1.0))
        denom = alpha + beta
        mean = alpha / denom if denom else 0.0
        summary[op] = {
            "alpha": round(alpha, 4),
            "beta": round(beta, 4),
            "mean": round(mean, 4),
        }
    return summary


def select_operator(
    node: Node | None = None,
    available_operators: list[OperatorType] | None = None,
    *,
    stats: dict[OperatorType, tuple[float, float]] | None = None,
    rng: random.Random | None = None,
    min_explore: float = 0.1,
    bandit: bool = False,
) -> OperatorType:
    """Select an operator for the next generation."""
    del node  # reserved for future context-aware selection
    if available_operators is None:
        available_operators = [OperatorType.REFINE]

    if not bandit or len(available_operators) <= 1:
        return OperatorType.REFINE

    rng = rng or random.Random(0)
    stats = stats or {}
    k = len(available_operators)
    explore_p = min(1.0, min_explore * k)
    if rng.random() < explore_p:
        return rng.choice(available_operators)

    best_op = available_operators[0]
    best_sample = -1.0
    for op in available_operators:
        alpha, beta = stats.get(op, (1.0, 1.0))
        sample = rng.betavariate(alpha, beta)
        if sample > best_sample:
            best_sample = sample
            best_op = op
    return best_op


def get_operator_thompson_sample(
    operator_stats: dict[OperatorType, tuple[float, float]],
) -> dict[OperatorType, float]:
    """Get Thompson sampling weights for operators.

    Hook for operator selection using Beta-Bernoulli bandits.
    Currently returns uniform weights.

    Args:
        operator_stats: Dict mapping operator to (alpha, beta)

    Returns:
        Dict mapping operator to sampling probability
    """
    import numpy as np

    if not operator_stats:
        return {OperatorType.REFINE: 1.0}

    samples = {}
    for op, (alpha, beta) in operator_stats.items():
        samples[op] = np.random.beta(alpha, beta)

    total = sum(samples.values())
    return {op: s / total for op, s in samples.items()}
