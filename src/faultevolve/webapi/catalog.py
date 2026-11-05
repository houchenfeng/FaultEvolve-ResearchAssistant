"""Engine-derived catalogues exported to the front-end contract.

Everything the Web UI would otherwise hard-code lives here and is generated from
the live Python source, so that adding an operator, an adapter or a config field
on ``main`` surfaces as a contract drift instead of a silent front-end gap.

Two kinds of content live in this module:

* **Derived** -- enums, adapters, field lists, config groups. Read straight off
  the engine models at import time.
* **Declared** -- the event-type list and the Chinese UI labels. Declared
  because they cannot be derived, and pinned by tests that compare them against
  the source (``tests/webapi/test_engine_catalog.py``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterator

from pydantic_core import to_jsonable_python

from faultevolve.common.schemas import (
    GENERATIVE_OPERATORS,
    HypothesisStatus,
    NodeStatus,
    OperatorType,
    RunSummary,
    TreeExport,
)
from faultevolve.config import EvolveConfig
from faultevolve.tasks.registry import ADAPTER_ALIASES, STUB_ADAPTER_DOCS

from faultevolve.webapi.contracts import CONTRACT_VERSION, DeploymentMode

# --------------------------------------------------------------------------
# event types
# --------------------------------------------------------------------------

#: Every ``Event.type`` the engine writes today, extracted from the
#: ``self._log_event("...")`` call sites.
#:
#: Pinned by tests/webapi/test_engine_catalog.py::test_all_event_types_are_catalogued.
#: Unknown types must still render in the UI (TODO §13.4), so this list exists to
#: label known events, not to filter unknown ones.
EVENT_TYPES: frozenset[str] = frozenset(
    {
        "analysis_complete",
        "analysis_failed",
        "all_islands_stopped",
        "attempt_started",
        "budget_stage_cap_hit",
        "budget_stop",
        "crossover_parents",
        "crossover_reflection_skipped",
        "discovery_round_finished",
        "discovery_skipped",
        "exchange_applied",
        "exchange_check",
        "exchange_delivered",
        "exchange_delivery_backfilled",
        "exchange_rejected",
        "exchange_summary_failed",
        "exchange_summary_published",
        "exchange_summary_replicated",
        "expand_redirected_budget",
        "hpo_no_promotion",
        "hpo_promoted",
        "hpo_promotion_skipped",
        "hpo_skipped",
        "hypothesis_refuted",
        "init_evaluated",
        "init_evaluation_invalid",
        "insight_extracted",
        "invalid_generation",
        "infra_failure",
        "island_attempt_cap_hit",
        "island_stopped",
        "iteration_complete",
        "structure_tuning_started",
        "structure_tuning_trial",
        "structure_tuning_complete",
        "jev_audited",
        "jev_circuit_open",
        "jev_deferred_evaluated",
        "jev_error",
        "jev_prescreen",
        "jev_screened",
        "knowledge_injected",
        "llm_call_lost",
        "llm_error",
        "mechanism_refuted",
        "node_created",
        "objective_brief_failed",
        "objective_spec_failed",
        "operator_bias_applied",
        "operator_fallback",
        "operator_selected",
        "patch_applied",
        "patch_fallback_draft",
        "patch_proposed",
        "patch_rejected",
        "patch_unavailable",
        "perf_rejected",
        "perf_self_fix_success",
        "precheck_fix",
        "precheck_fix_repair",
        "quota_slot",
        "research_contract",
        "research_goal_reached",
        "reflection_design",
        "reflection_implementation",
        "reflection_mechanism",
        "repair_failed",
        "repair_perf_rejected",
        "repair_smoke_failed",
        "repair_success",
        "run_aborted_invalid_init",
        "run_finished",
        "run_interrupted",
        "run_resumed",
        "run_resume_refused",
        "run_stalled",
        "selection_failed",
        "smoke_data_build_failed",
        "smoke_data_built",
        "smoke_failed",
        "smoke_fix_success",
        "smoke_passed",
        "summary_crossover",
        "summary_cross_selected",
        "tournament_round_finished",
        "tournament_skipped",
        "value_mode_fallback",
    }
)

#: Run-level status values actually produced by the engine.
#:
#: PRD §9.2 lists nine lifecycle states; the engine emits these five today
#: (``Experiment.status`` defaults to ``created``, the engine writes
#: ``running`` / ``finished``, ``crashed`` in the crash-summary path, and
#: ``failed`` on terminal evaluation errors). ``pausing`` / ``paused`` /
#: ``finishing`` / ``cancelled`` do not exist yet and must be reported as
#: ``not_supported`` rather than faked.
ENGINE_RUN_STATUSES: frozenset[str] = frozenset(
    {"created", "running", "finished", "crashed", "failed"}
)

#: Lifecycle states named by PRD §9.2 that the engine cannot produce today.
UNIMPLEMENTED_RUN_STATUSES: frozenset[str] = frozenset(
    {"initializing", "pausing", "paused", "finishing", "completed", "cancelled"}
)

# --------------------------------------------------------------------------
# deployment modes and navigation
# --------------------------------------------------------------------------

#: Left-hand navigation, in order. The P0 shell renders exactly these four.
NAV_MODULES: tuple[str, ...] = ("overview", "workbench", "knowledge", "results")

DEPLOYMENT_MODES: tuple[DeploymentMode, ...] = (
    DeploymentMode.LOCAL_CLOUD,
    DeploymentMode.SSH_CLOUD,
)

#: P1+ only -- declared so /api/meta can report it as unavailable instead of
#: the UI pretending the mode exists.
UNAVAILABLE_DEPLOYMENT_MODES: tuple[DeploymentMode, ...] = (
    DeploymentMode.LOCAL_DESKTOP,
)

STREAM_TRANSPORT = "sse"


# --------------------------------------------------------------------------
# UI metadata for config fields
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class UiFieldMeta:
    """Chinese presentation metadata for one config field."""

    label_zh: str
    group_zh: str = ""
    help_zh: str = ""
    advanced: bool = False
    preset_editable: bool = True


#: Explicitly annotated fields. Anything absent is exported with
#: ``advanced=True`` and its dotted name as the label, so no field can be
#: silently promoted into the basic form.
UI_FIELD_METADATA: dict[str, UiFieldMeta] = {
    "workflow.enabled": UiFieldMeta("逐结构调优流程", "工作流", "通过任务适配器执行结构搜索与分层调优；数据处理与报告导出分别配置"),
    "workflow.cpu_limit": UiFieldMeta("评估 CPU 核数", "工作流", "冒烟、完整验证与分层调参共用的 CPU 和数值库线程上限，默认 4 核", advanced=True),
    "workflow.data.drop_exact_duplicates": UiFieldMeta("删除完全重复历史行", "工作流", "仅对运行目录中的训练副本去重", advanced=True),
    "workflow.data.nonfinite_to_missing": UiFieldMeta("无穷特征值转缺失", "工作流", "保留记录，由候选算法处理缺失", advanced=True),
    "workflow.data.accepted_issues": UiFieldMeta("允许保留的数据问题", "工作流", "缺失与常量可按声明保留，其余需决策问题阻断", advanced=True),
    "workflow.data.enabled": UiFieldMeta("可选数据处理", "工作流", "默认关闭；开启时由任务适配器检查、处理并复检训练输入，不影响其他任务的核心调优"),
    "workflow.reports.enabled": UiFieldMeta("完成后导出报告", "工作流", "默认关闭；报告只读取已存结果，可独立重建，导出失败不改变搜索完成状态"),
    "workflow.hierarchical.enabled": UiFieldMeta("分层参数搜索", "工作流", "默认在每个新候选评分前调优，以调优后的代码与实测成绩驱动下一轮演化"),
    "workflow.hierarchical.mode": UiFieldMeta("调优时机", "工作流", "per_structure：逐结构调优；post_evolution：兼容旧版演化结束后统一调优"),
    "workflow.hierarchical.max_trials": UiFieldMeta("分层试验上限", "工作流", "逐结构模式下为每个候选的试验预算，包含默认参数评估"),
    "workflow.hierarchical.max_wall_seconds": UiFieldMeta("分层搜索时限（秒）", "工作流", "达到时限后不再派发新试验，已派发试验按评估器超时结束", advanced=True),
    # task
    "task.adapter": UiFieldMeta("任务适配器", "任务", "决定加载哪个数据集适配器与评估器"),
    # budget
    "budget.max_iterations": UiFieldMeta("最大轮次", "预算", "进化循环的上限轮数"),
    "budget.max_tokens": UiFieldMeta("Token 上限", "预算", "整轮运行的 LLM token 预算"),
    "budget.max_wall_hours": UiFieldMeta("墙钟上限（小时）", "预算", "超时即停止"),
    "budget.min_iterations_before_stop": UiFieldMeta("最短轮次", "预算", "早停前至少跑满的轮数"),
    "budget.stage_caps": UiFieldMeta("分阶段额度", "预算", "按阶段限制 token 占比", advanced=True),
    "budget.stage_caps_absolute": UiFieldMeta(
        "分阶段绝对额度", "预算", "未设总 token 上限时唯一生效的阶段额度", advanced=True
    ),
    # islands
    "islands.enabled": UiFieldMeta("启用三岛演化", "三岛", "关闭则回到单树行为"),
    "islands.islands": UiFieldMeta("岛列表", "三岛", "每个岛一条独立搜索树的策略配置"),
    "islands.exchange_interval": UiFieldMeta("交换间隔", "三岛", "每完成多少次尝试检查一次摘要交换"),
    "islands.max_positive_per_exchange": UiFieldMeta("单次正面摘要上限", "三岛", advanced=True),
    "islands.max_negative_per_exchange": UiFieldMeta("单次负面摘要上限", "三岛", advanced=True),
    "islands.max_summaries_in_context": UiFieldMeta("上下文摘要条数", "三岛", advanced=True),
    "islands.eval_concurrency": UiFieldMeta("评估并发", "三岛", "同时运行的真实评估数量"),
    "islands.min_valid_evals_before_stall": UiFieldMeta("停滞判定门槛", "三岛", advanced=True),
    "islands.stall_valid_evals": UiFieldMeta("停滞窗口", "三岛", "连续多少次有效评估无提升即停该岛", advanced=True),
    "islands.infra_fail_pause": UiFieldMeta("基础设施错误熔断", "三岛", "连续多少次基础设施失败暂停该岛", advanced=True),
    "islands.stagnation_request_evals": UiFieldMeta(
        "停滞求助间隔（引擎未读取）", "三岛", "该字段当前没有引擎调用点；接入前配置它不会有任何效果", advanced=True
    ),
    "islands.early_error_share": UiFieldMeta("提前错误共享", "三岛", "重要执行错误立即跨岛通报", advanced=True),
    # selection
    "selection.policy": UiFieldMeta("选择策略", "搜索"),
    "selection.c_puct": UiFieldMeta("探索系数", "搜索", "UCT 探索项权重", advanced=True),
    "selection.kappa_noise": UiFieldMeta("噪声系数", "搜索", advanced=True),
    "selection.lambda_dup": UiFieldMeta("重复惩罚", "搜索", advanced=True),
    # operators
    "operators.bandit": UiFieldMeta("算子 Bandit", "算子", "按历史收益自适应分配算子"),
    "operators.enabled": UiFieldMeta("启用算子", "算子", "允许使用的算子白名单"),
    "operators.crossover.enabled": UiFieldMeta("启用交叉", "算子", "允许 crossover 算子"),
    "operators.crossover.min_valid_nodes": UiFieldMeta("交叉最少有效节点", "算子", advanced=True),
    # reflection / repair
    "reflection.max_repair_attempts": UiFieldMeta("最大修复次数", "反思与纠错"),
    "reflection.design_delta_factor": UiFieldMeta("设计反思阈值", "反思与纠错", advanced=True),
    "reflection.hypothesis_delta_factor": UiFieldMeta("假设检验阈值", "反思与纠错", advanced=True),
    # stop
    "stop.target_score": UiFieldMeta("目标分数", "停止条件", "达到后停止"),
    "stop.window": UiFieldMeta("早停窗口", "停止条件", advanced=True),
    # llm
    "llm.generate_model": UiFieldMeta("生成模型", "模型", "写代码用的模型"),
    "llm.reason_model": UiFieldMeta("推理模型", "模型", "反思与规划用的模型"),
    "llm.max_concurrency": UiFieldMeta("最大并发", "模型", advanced=True),
    "llm.temperature": UiFieldMeta("温度", "模型", advanced=True),
    # judge
    "judge.provider": UiFieldMeta("评审提供方", "评审", "none / jev / mock"),
    "judge.model": UiFieldMeta("评审模型", "评审", advanced=True),
    "judge.prescreen": UiFieldMeta("启用预筛", "评审", "用 Jev 预筛候选，省评估开销"),
    "judge.max_calls": UiFieldMeta("评审调用上限", "评审", advanced=True),
    # knowledge
    "knowledge.enabled": UiFieldMeta("启用知识注入", "知识注入"),
    "knowledge.dir": UiFieldMeta("知识包目录", "知识注入"),
    "knowledge.k": UiFieldMeta("召回数量", "知识注入", advanced=True),
    "knowledge.max_per_category": UiFieldMeta("每类上限", "知识注入", advanced=True),
    # smoke test
    "smoke_test.enabled": UiFieldMeta("启用冒烟测试", "冒烟测试"),
    "smoke_test.sample_fraction": UiFieldMeta("抽样比例", "冒烟测试", advanced=True),
    "smoke_test.timeout_s": UiFieldMeta("超时（秒）", "冒烟测试", advanced=True),
    # analysis
    "analysis.enabled": UiFieldMeta(
        "启用误差画像",
        "误差画像",
        "开启后 refine 会拿到开发集错误画像；注意 recall_focus 算子也依赖它",
    ),
    "analysis.top_k": UiFieldMeta("画像 Top-K", "误差画像", advanced=True),
    "analysis.on_new_best": UiFieldMeta("仅在新最优时分析", "误差画像", advanced=True),
    # discovery
    "discovery.enabled": UiFieldMeta("启用知识发现", "知识发现"),
    "discovery.every_n_iterations": UiFieldMeta("发现间隔（轮）", "知识发现"),
    "discovery.run_at_end": UiFieldMeta("结束时再跑一轮", "知识发现", advanced=True),
    "discovery.max_claims_per_round": UiFieldMeta("每轮最大主张数", "知识发现", advanced=True),
    "discovery.inject_same_run": UiFieldMeta("本轮即可注入", "知识发现", advanced=True),
    "discovery.tournament.enabled": UiFieldMeta("启用机制辩论赛", "知识发现", "需要先启用知识发现"),
    "discovery.tournament.max_rounds": UiFieldMeta("辩论轮数", "知识发现", advanced=True),
    # top level
    "seed": UiFieldMeta("随机种子", "运行", "影响可复现性"),
}

#: Chinese labels for the four navigation entries.
NAV_MODULE_LABELS_ZH: dict[str, str] = {
    "overview": "总览",
    "workbench": "进化工作台",
    "knowledge": "知识发现",
    "results": "结果与报告",
}


# --------------------------------------------------------------------------
# config walking
# --------------------------------------------------------------------------


def _iter_leaf_fields(
    model: type, prefix: str = ""
) -> Iterator[tuple[str, str, Any]]:
    """Yield ``(dotted_path, type_name, default)`` for every leaf config field."""
    for name, info in model.model_fields.items():
        path = f"{prefix}{name}"
        annotation = info.annotation
        nested = getattr(annotation, "model_fields", None)
        if nested is not None:
            yield from _iter_leaf_fields(annotation, prefix=f"{path}.")
            continue
        type_name = getattr(annotation, "__name__", None) or str(annotation)
        if info.default_factory is not None:
            default: Any = _safe_default_factory(info.default_factory)
        else:
            default = info.default
        yield path, type_name, default


def _safe_default_factory(factory: Any) -> Any:
    try:
        value = factory()
    except Exception:  # pragma: no cover - defensive
        return None
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, dict)):
        # Defaults may hold nested models (e.g. the island specs); the contract
        # files are plain JSON, so normalize before handing them to the UI.
        try:
            return to_jsonable_python(value)
        except Exception:  # pragma: no cover - defensive
            return None
    return None


def config_field_metadata() -> list[dict[str, Any]]:
    """UI metadata for every leaf of ``EvolveConfig`` (TODO §1.2)."""
    entries: list[dict[str, Any]] = []
    for path, type_name, default in _iter_leaf_fields(EvolveConfig):
        meta = UI_FIELD_METADATA.get(path)
        group = path.split(".", 1)[0]
        entries.append(
            {
                "path": path,
                "group": group,
                "group_zh": meta.group_zh if meta else "",
                "label_zh": meta.label_zh if meta else path,
                "help_zh": meta.help_zh if meta else "",
                "type": type_name,
                "default": default,
                "advanced": meta.advanced if meta else True,
                "preset_editable": meta.preset_editable if meta else True,
                "annotated": meta is not None,
            }
        )
    entries.sort(key=lambda e: e["path"])
    return entries


# --------------------------------------------------------------------------
# engine catalog
# --------------------------------------------------------------------------


def build_engine_catalog() -> dict[str, Any]:
    """The ``engine-catalog.json`` payload (TODO §1.3)."""
    return {
        "contract_version": CONTRACT_VERSION,
        "node_status": [m.value for m in NodeStatus],
        "hypothesis_status": [m.value for m in HypothesisStatus],
        "operator_type": [m.value for m in OperatorType],
        "generative_operators": [m.value for m in GENERATIVE_OPERATORS],
        "run_status_engine": sorted(ENGINE_RUN_STATUSES),
        "run_status_unimplemented": sorted(UNIMPLEMENTED_RUN_STATUSES),
        "adapter_aliases": [
            {"alias": alias, "target": target}
            for alias, target in sorted(ADAPTER_ALIASES.items())
        ],
        "stub_adapters": [
            {"alias": alias, "doc_path": doc}
            for alias, doc in sorted(STUB_ADAPTER_DOCS.items())
        ],
        "event_types": sorted(EVENT_TYPES),
        "nav_modules": list(NAV_MODULES),
        "nav_module_labels_zh": dict(NAV_MODULE_LABELS_ZH),
        "deployment_modes": [m.value for m in DEPLOYMENT_MODES],
        "unavailable_deployment_modes": [m.value for m in UNAVAILABLE_DEPLOYMENT_MODES],
        "stream_transport": STREAM_TRANSPORT,
        "run_summary_fields": sorted(RunSummary.model_fields),
        "tree_export_fields": sorted(TreeExport.model_fields),
        "config_groups": sorted(EvolveConfig.model_fields),
    }


def build_ui_metadata() -> dict[str, Any]:
    """The ``ui-metadata.json`` payload.

    Defaults and constraints stay in the Pydantic schema; only presentation
    lives here (TODO §1.2).
    """
    return {
        "contract_version": CONTRACT_VERSION,
        "nav_module_labels_zh": dict(NAV_MODULE_LABELS_ZH),
        "fields": config_field_metadata(),
    }


@dataclass(frozen=True)
class PresetDefinition:
    """One of the three intake presets (TODO §4.6)."""

    preset_id: str
    label_zh: str
    description_zh: str
    overrides: dict[str, Any] = field(default_factory=dict)


#: Built server-side so the front-end never assembles a config by hand.
#: ``quick`` keeps the engine defaults; ``standard`` turns on the profiling and
#: screening helpers; ``deep`` adds knowledge discovery and the tournament.
PRESETS: tuple[PresetDefinition, ...] = (
    PresetDefinition(
        preset_id="quick",
        label_zh="快速验证",
        description_zh="最短路径跑通流程，用默认配置，不启用知识发现",
        overrides={"budget": {"max_iterations": 5}},
    ),
    PresetDefinition(
        preset_id="standard",
        label_zh="标准进化",
        description_zh="开启误差画像与候选预筛，适合常规调参",
        overrides={
            "budget": {"max_iterations": 20},
            "analysis": {"enabled": True},
            "judge": {"prescreen": True},
        },
    ),
    PresetDefinition(
        preset_id="deep",
        label_zh="深度探索",
        description_zh="额外开启知识发现与机制辩论赛，耗时与开销最高",
        overrides={
            "budget": {"max_iterations": 50},
            "analysis": {"enabled": True},
            "judge": {"prescreen": True},
            "discovery": {"enabled": True, "tournament": {"enabled": True}},
        },
    ),
)


def build_preset_catalog() -> list[dict[str, Any]]:
    """Preset definitions with the resulting full config attached."""
    from faultevolve.config import EvolveConfig as _Cfg

    out: list[dict[str, Any]] = []
    for preset in PRESETS:
        merged = _Cfg.from_dict(preset.overrides)
        out.append(
            {
                "preset_id": preset.preset_id,
                "label_zh": preset.label_zh,
                "description_zh": preset.description_zh,
                "config": merged.model_dump(),
            }
        )
    return out
