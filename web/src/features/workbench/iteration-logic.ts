/**
 * 事件流的整理：去重、代际切分、分组（TODO 5.6 / PRD §9.6）。
 *
 * 三个真实问题决定了这个模块的形状：
 *
 * 1. **事件会重复到达**。轮询用 `after_id` 增量拉，但重新挂载时 TanStack Query
 *    会重放缓存，页面上会出现同一个事件两次。必须按 `id` 去重。
 * 2. **事件没有"第几代"字段**。`iteration_complete` 只说明"一代结束了"，
 *    要把事件流切成代，得靠这个标记事件的位置。
 * 3. **事件类型不该在前端硬编码**。后端 `catalog.py` 已经把 40+ 个
 *    `EVENT_TYPES` 通过 `meta` 端点暴露出来（`is_known_type` 也是拿它算的）。
 *    前端写一份清单必然会漏。
 */
import type { EventResponse } from '@/generated/api';

/** 一"代"：从上一条 `iteration_complete` 之后到下一条之间的全部事件。 */
export interface Generation {
  /** 从 0 开始。0 是初始化阶段（第一次 `iteration_complete` 之前）。 */
  index: number;
  /** 该代包含的事件，已按 id 升序。 */
  events: EventResponse[];
  /** 便于列表 key 与折叠。 */
  id: string;
}

/** 标记"一代结束"的事件类型。唯一可据以切分代际的标记。 */
export const GENERATION_MARKER = 'iteration_complete';

/** 运行结束的标记事件。 */
export const RUN_FINISHED = 'run_finished';

/**
 * 按 id 去重并按 id 升序。
 *
 * 保留**先出现的**那条：同一 id 的 payload 是同一次写入的产物，
 * 后到的可能是被重放的旧缓存，而先到的是本轮真实响应。
 */
export function dedupeEvents(events: EventResponse[]): EventResponse[] {
  const byId = new Map<number, EventResponse>();
  const withoutId: EventResponse[] = [];

  for (const event of events) {
    if (event.id === null || event.id === undefined) {
      // 没有 id 的事件无法去重（契约允许），只能原样保留。
      withoutId.push(event);
      continue;
    }
    if (!byId.has(event.id)) byId.set(event.id, event);
  }

  const sorted = [...byId.values()].sort((a, b) => (a.id ?? 0) - (b.id ?? 0));
  return [...sorted, ...withoutId];
}

/**
 * 把事件流切成代。
 *
 * `iteration_complete` **归属它结束的那一代**（而不是开启下一代），
 * 这样"这一代做成了什么"和"这一代结束了"在同一组里，读起来才连贯。
 */
export function splitGenerations(events: EventResponse[]): Generation[] {
  const ordered = dedupeEvents(events);
  const generations: Generation[] = [];
  let current: EventResponse[] = [];

  const flush = () => {
    if (current.length === 0) return;
    const index = generations.length;
    generations.push({
      index,
      events: current,
      id: `gen-${index}-${current[0].id ?? 'x'}`,
    });
    current = [];
  };

  for (const event of ordered) {
    current.push(event);
    if (event.type === GENERATION_MARKER) flush();
  }
  // 收尾：最后一代没有结束标记（运行被中断、还在跑、或压根没有该事件）。
  flush();

  return generations;
}

/** 一代的统计，用于时间轴上的刻度。 */
export interface GenerationStats {
  index: number;
  eventCount: number;
  /** 已知类型的事件数，`is_known_type=false` 的是前端不认识的新类型。 */
  knownCount: number;
  unknownCount: number;
  /** 这代里出现过的节点/运行 id（从 payload 里尽力提取）。 */
  firstTs: string;
  lastTs: string;
  /** 该代是否已被 `iteration_complete` 正常收尾。 */
  closed: boolean;
}

function isClosed(generation: Generation): boolean {
  const last = generation.events[generation.events.length - 1];
  return last?.type === GENERATION_MARKER;
}

/** payload 里节点 id 的候选键名。引擎各事件命名不统一，只能多试几个。 */
const NODE_ID_KEYS = ['node_id', 'node', 'child_id', 'best_node_id'] as const;

/** 从 payload 里尽力提取节点 id；取不到返回 null，不猜。 */
export function nodeIdOf(event: EventResponse): string | null {
  const payload = event.payload as Record<string, unknown> | undefined;
  if (!payload) return null;
  for (const key of NODE_ID_KEYS) {
    const value = payload[key];
    if (typeof value === 'string' && value.length > 0) return value;
  }
  return null;
}

export function generationStats(generation: Generation): GenerationStats {
  const unknown = generation.events.filter((event) => event.is_known_type === false);
  const timestamps = generation.events
    .map((event) => event.ts ?? '')
    .filter((ts) => ts.length > 0);
  return {
    index: generation.index,
    eventCount: generation.events.length,
    knownCount: generation.events.length - unknown.length,
    unknownCount: unknown.length,
    firstTs: timestamps[0] ?? '',
    lastTs: timestamps[timestamps.length - 1] ?? '',
    closed: isClosed(generation),
  };
}

export interface EventFilter {
  /** 只看这些类型；空数组表示不过滤。 */
  types: string[];
  /** 关键词，匹配 type 或 payload 的字符串值。 */
  keyword: string;
  /** 隐藏前端不认识的事件类型（引擎加新事件时页面不会突然变乱）。 */
  hideUnknown: boolean;
  /** 只看与这个节点相关的事件。 */
  nodeId: string | null;
}

export const EMPTY_EVENT_FILTER: EventFilter = {
  types: [],
  keyword: '',
  hideUnknown: false,
  nodeId: null,
};

export function passesEventFilter(event: EventResponse, filter: EventFilter): boolean {
  if (filter.hideUnknown && event.is_known_type === false) return false;
  if (filter.types.length > 0 && !filter.types.includes(event.type)) return false;
  if (filter.nodeId && nodeIdOf(event) !== filter.nodeId) return false;

  const keyword = filter.keyword.trim().toLowerCase();
  if (keyword) {
    const payloadText = JSON.stringify(event.payload ?? {}).toLowerCase();
    if (!event.type.toLowerCase().includes(keyword) && !payloadText.includes(keyword)) {
      return false;
    }
  }
  return true;
}

export function filterEvents(events: EventResponse[], filter: EventFilter): EventResponse[] {
  return dedupeEvents(events).filter((event) => passesEventFilter(event, filter));
}

/** 事件类型的中文标签。取不到就是类型原文，不编造译名。 */
const EVENT_LABELS: Record<string, string> = {
  research_contract: '冻结科研目标',
  research_goal_reached: '同一候选达成全部科研目标',
  init_evaluated: '初始程序已评估',
  structure_tuning_started: '开始逐结构分层调优',
  structure_tuning_trial: '完成参数试验',
  structure_tuning_complete: '完成逐结构分层调优',
  node_created: '创建节点',
  iteration_complete: '一代完成',
  run_finished: '运行结束',
  hypothesis_refuted: '假设被推翻',
  mechanism_refuted: '机制被推翻',
  insight_extracted: '提取到洞察',
  reflection_design: '反思 · 设计',
  reflection_implementation: '反思 · 实现',
  reflection_mechanism: '反思 · 机制',
  repair_success: '修复成功',
  repair_failed: '修复失败',
  repair_perf_rejected: '修复被性能门拒绝',
  repair_smoke_failed: '修复未通过冒烟',
  precheck_fix: '预检修复',
  precheck_fix_repair: '预检修复 · 二次修复',
  perf_rejected: '性能门拒绝',
  perf_self_fix_success: '性能自修复成功',
  operator_selected: '选定算子',
  operator_fallback: '算子回退',
  crossover_parents: '交叉双亲',
  crossover_reflection_skipped: '跳过交叉反思',
  budget_stop: '预算耗尽停止',
  budget_stage_cap_hit: '触发阶段上限',
  llm_error: 'LLM 调用失败',
  llm_call_lost: 'LLM 调用丢失（花费未知）',
  jev_error: 'JEV 失败',
  jev_prescreen: 'JEV 预筛',
  jev_screened: 'JEV 已筛',
  jev_audited: 'JEV 已审计',
  jev_circuit_open: 'JEV 熔断',
  jev_deferred_evaluated: 'JEV 延迟评估',
  selection_failed: '选择失败',
  invalid_generation: '生成结果非法',
  smoke_data_built: '冒烟数据已构建',
  smoke_passed: '冒烟通过',
  smoke_failed: '冒烟失败',
  discovery_round_finished: '发现轮次完成',
  discovery_skipped: '跳过发现',
  analysis_complete: '分析完成',
  analysis_failed: '分析失败',
  // 三岛：一次尝试的生命周期、岛自己的停止、调度与配额。
  attempt_started: '尝试开始',
  island_stopped: '岛停止',
  all_islands_stopped: '全部岛停止',
  island_attempt_cap_hit: '岛尝试上限触发',
  infra_failure: '基础设施失败',
  init_evaluation_invalid: '初始评估非法',
  run_aborted_invalid_init: '因初始评估非法中止',
  value_mode_fallback: '价值模式回退（无目标指标）',
  objective_brief_failed: '目标简报生成失败',
  objective_spec_failed: '目标规格生成失败',
  operator_bias_applied: '岛策略算子偏置生效',
  quota_slot: '配额槽位改选算子',
  expand_redirected_budget: '扩展改道到高分节点（预算）',
  run_stalled: '运行停滞',
  run_interrupted: '运行被中断',
  run_resumed: '运行已恢复',
  run_resume_refused: '恢复被拒',
  knowledge_injected: '注入知识卡',
  // 摘要交换：发布、复制证据、投递、拒绝、采用各有各的事件，时间轴上要能分开读。
  exchange_check: '摘要交换检查',
  exchange_summary_published: '发布摘要',
  exchange_summary_replicated: '摘要被复现（追加证据）',
  exchange_summary_failed: '摘要生成失败',
  exchange_delivered: '摘要已投递',
  exchange_delivery_backfilled: '补投递摘要',
  exchange_rejected: '摘要投递被拒',
  exchange_applied: '摘要被采用',
  summary_cross_selected: '选定摘要交叉',
  summary_crossover: '摘要交叉生成',
  // 超参搜索（HPO）：跳过/无晋级/晋级各有事件，payload 里带 reason 与试验号。
  hpo_skipped: '超参搜索跳过',
  hpo_no_promotion: '超参搜索无晋级',
  hpo_promotion_skipped: '超参晋级被跳过',
  hpo_promoted: '超参试验晋级',
  // 机理锦标赛：整轮跳过与一轮完成（payload 带 established/refuted/undetermined）。
  tournament_skipped: '机理锦标赛跳过',
  tournament_round_finished: '机理锦标赛一轮完成',
  // 热补丁与冒烟修复。
  patch_proposed: '热补丁已提议',
  patch_applied: '热补丁已应用',
  patch_rejected: '热补丁被拒',
  patch_unavailable: '热补丁不可用',
  patch_fallback_draft: '热补丁回退为草稿',
  smoke_data_build_failed: '冒烟数据构建失败',
  smoke_fix_success: '冒烟修复成功',
};

export function eventLabel(type: string): string {
  return EVENT_LABELS[type] ?? type;
}

/** 时间轴颜色键：错误类事件必须一眼可辨（PRD §9.6）。 */
export function eventTone(type: string): 'normal' | 'warn' | 'error' | 'success' | 'muted' {
  if (type.endsWith('_failed') || type.endsWith('_error') || type.endsWith('_rejected')) {
    return 'error';
  }
  if (type === 'budget_stop' || type === 'budget_stage_cap_hit' || type === 'jev_circuit_open') {
    return 'warn';
  }
  if (type === GENERATION_MARKER || type === RUN_FINISHED || type.endsWith('_success')) {
    return 'success';
  }
  if (type.startsWith('reflection_') || type === 'insight_extracted') return 'muted';
  return 'normal';
}

/** 出现过的类型计数，按次数降序 —— 给过滤器面板用。 */
export function countEventTypes(events: EventResponse[]): Array<{ type: string; count: number }> {
  const counts = new Map<string, number>();
  for (const event of dedupeEvents(events)) {
    counts.set(event.type, (counts.get(event.type) ?? 0) + 1);
  }
  return [...counts.entries()]
    .map(([type, count]) => ({ type, count }))
    .sort((a, b) => b.count - a.count || a.type.localeCompare(b.type));
}
