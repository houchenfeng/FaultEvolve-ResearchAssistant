/**
 * 事件分类：PRD §16.2 的 12 个**粗类** ↔ 引擎实际发出的**细名**。
 *
 * ## 为什么是"粗类 → 类型集合"，而不是一一映射
 *
 * PRD 列的是"节点创建""迭代完成"这样的粗类，引擎写的是 `node_created`、
 * `iteration_complete` 这样的细名，而**两边的数量本来就不一样**：
 * 「评估开始和完成」在引擎里没有单独事件，「最佳节点改变」是
 * `iteration_complete` 载荷里的两个字段而不是事件类型。所以硬凑一张一一
 * 对应表只会逼出三种坏结果：编造不存在的事件、给真实事件安错类、或者在
 * 前端写一堆 `if (type === ...)` 补丁。
 *
 * 正确姿势是承认粗类只是**视图**：分类表负责把细名归到粗类，用于时间轴的
 * 分组与筛选；具体某个细名在不在表里，由 `tests/event-taxonomy.test.ts` 盯着。
 *
 * ## 未知类型怎么办
 *
 * 表外的类型**照样渲染**，只是没有粗类（`eventCategory` 返回 `null`）——
 * TODO §13.4 要求未知事件可见。这里最危险的不是"渲染出来了"，而是
 * **静默地不认识**：一个新增的事件类型如果没人提，前端不会报错，只会让
 * 时间轴看起来少东西。所以有 `test_every_engine_event_type_has_a_category`
 * 这条漂移测试盯着（它跨到 Python 侧读 `catalog.EVENT_TYPES`）。
 */

/** PRD §16.2 的 12 个粗类。顺序即时间轴分组里显示的顺序。 */
export const EVENT_CATEGORIES = [
  'run_state',
  'init',
  'node_created',
  'node_state',
  'evaluation',
  'iteration',
  'best_node',
  'llm',
  'insight',
  'discovery',
  'budget',
  'run_finished',
] as const;

export type EventCategory = (typeof EVENT_CATEGORIES)[number];

/** 粗类的中文标签。表外的类型不编造粗类，直接显示类型原文。 */
export const CATEGORY_LABELS: Record<EventCategory, string> = {
  run_state: '运行状态改变',
  init: '初始化完成',
  node_created: '节点创建',
  node_state: '节点状态改变',
  evaluation: '评估开始/完成',
  iteration: '迭代完成',
  best_node: '最佳节点改变',
  llm: 'Qwen 调用状态',
  insight: '洞察提取',
  discovery: 'claim/机制/锦标赛更新',
  budget: '预算更新',
  run_finished: '运行完成或失败',
};

/**
 * 粗类 → 引擎细名。
 *
 * 每一项都必须能在 `catalog.EVENT_TYPES` 里找到（反向由漂移测试保证）。
 * 一个细名出现在两个粗类里同样是漂移，测试会抓住。
 */
const CATEGORY_MEMBERS: Record<EventCategory, readonly string[]> = {
  run_state: [
    'objective_brief_failed',
    'objective_spec_failed',
    'value_mode_fallback',
    'budget_stop',
    'budget_stage_cap_hit',
    'selection_failed',
    'run_stalled',
    'expand_redirected_budget',
    'invalid_generation',
  ],
  init: [
    'init_evaluated',
    'smoke_data_built',
    'smoke_data_build_failed',
    'smoke_passed',
    'smoke_failed',
    'smoke_fix_success',
  ],
  node_created: ['node_created'],
  node_state: [
    'analysis_complete',
    'analysis_failed',
    'precheck_fix',
    'precheck_fix_repair',
    'perf_self_fix_success',
    'perf_rejected',
    'operator_selected',
    'operator_fallback',
    'patch_applied',
    'patch_fallback_draft',
    'patch_proposed',
    'patch_rejected',
    'patch_unavailable',
    'quota_slot',
    'crossover_parents',
    'crossover_reflection_skipped',
    'repair_success',
    'repair_failed',
    'repair_perf_rejected',
    'repair_smoke_failed',
  ],
  // 引擎没有独立的"评估开始"事件：评估结果随 iteration_complete / node 状态
  // 一起到。这一类目前只有"完成"侧，如实反映，不补造事件。
  evaluation: [],
  iteration: ['iteration_complete'],
  // 「最佳节点改变」同理：由 iteration_complete 载荷的 best_node_id/best_score
  // 承载，不是独立事件。留空而不是拿 iteration_complete 顶替——那会让
  // "最佳节点改变"在筛选器里和"迭代完成"完全等价，而它们不是一回事。
  best_node: [],
  llm: ['llm_error'],
  insight: [
    'insight_extracted',
    'hypothesis_refuted',
    'mechanism_refuted',
    'reflection_design',
    'reflection_implementation',
    'reflection_mechanism',
  ],
  discovery: [
    'discovery_round_finished',
    'discovery_skipped',
    'hpo_no_promotion',
    'hpo_promoted',
    'hpo_promotion_skipped',
    'hpo_skipped',
    'jev_prescreen',
    'jev_screened',
    'jev_audited',
    'jev_circuit_open',
    'jev_deferred_evaluated',
    'jev_error',
    'tournament_round_finished',
    'tournament_skipped',
  ],
  // 预算类在 run_state 里也有一份（引擎复用同一批类型表达"因为预算而停"）。
  // 一个类型只能属于一个粗类，所以预算以 run_state 为准，这里不重复收。
  budget: [],
  run_finished: ['run_finished'],
};

/** 类型 → 粗类的反查表。构造时发现重复会直接抛，不静默取最后一个。 */
const TYPE_TO_CATEGORY: ReadonlyMap<string, EventCategory> = (() => {
  const map = new Map<string, EventCategory>();
  for (const category of EVENT_CATEGORIES) {
    for (const type of CATEGORY_MEMBERS[category]) {
      const existing = map.get(type);
      if (existing !== undefined) {
        throw new Error(
          `事件类型 ${type} 同时属于 ${existing} 与 ${category}：粗类必须互斥`,
        );
      }
      map.set(type, category);
    }
  }
  return map;
})();

/** 这个细名属于哪个粗类；表外返回 null（仍然渲染，只是不分组）。 */
export function eventCategory(type: string): EventCategory | null {
  return TYPE_TO_CATEGORY.get(type) ?? null;
}

export function categoryLabel(category: EventCategory): string {
  return CATEGORY_LABELS[category];
}

/** 展开成扁平列表，供漂移测试与筛选器共用同一份事实。 */
export function classifiedEventTypes(): string[] {
  return [...TYPE_TO_CATEGORY.keys()].sort();
}
