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
  init_evaluated: '初始程序已评估',
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
