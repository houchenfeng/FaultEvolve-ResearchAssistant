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
    // 三岛调度：岛是搜索的运行单位，它的启停与基础设施失败都是运行状态改变，
    // 不是节点或评估事件。`infra_failure` 指评估器/环境抛异常，算法判定无效不算。
    'island_stopped',
    'all_islands_stopped',
    'island_attempt_cap_hit',
    'infra_failure',
    // 断点恢复是运行状态的改变，不是节点事件：`run_resumed` 说明这一次是从哪个
    // 中断点接着跑的（含恢复到的成本行与岛状态），`run_interrupted` 说明上一份
    // 进程死了但留下了认领记录，`run_resume_refused` 说明任务/数据指纹/岛数/代码
    // schema 对不上因而拒绝续跑。三者都只描述"这个运行现在处于什么状态"。
    'run_resumed',
    'run_interrupted',
    'run_resume_refused',
    'research_contract',
    'research_goal_reached',
  ],
  init: [
    'init_evaluated',
    // 初始评估失败时正式实验不允许继续，0 分无效根不能当基线。
    'init_evaluation_invalid',
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
    // 岛画像对本岛算子池的偏好（含带种子的多样探索逃逸），与算子选择同源。
    'operator_bias_applied',
    'patch_applied',
    'patch_fallback_draft',
    'patch_proposed',
    'patch_rejected',
    'patch_unavailable',
    'quota_slot',
    'crossover_parents',
    'crossover_reflection_skipped',
    // 知识卡注入属于"这次生成本岛被给了什么先验"，与算子选择同源。空选择也发事
    // 件：没有这一条，报告分不清"库里没有适用的卡"和"知识功能被关掉了"。
    'knowledge_injected',
    // 跨岛交叉是"本岛父方案 + 兄弟岛结论"的单亲生成：算子被摘要选中、以及据
    // 摘要嫁接出新节点，都属于节点状态改变，与 operator_selected /
    // crossover_parents 同源。它不是双亲交叉，所以没有第二个 parent。
    'summary_cross_selected',
    'summary_crossover',
    'repair_success',
    'repair_failed',
    'repair_perf_rejected',
    'repair_smoke_failed',
  ],
  // 逐结构调优单独记录开始、参数试验与选中版本；外层轮次仍由 iteration_complete 计数。
  evaluation: ['structure_tuning_started', 'structure_tuning_trial', 'structure_tuning_complete'],
  // 三岛调度下"一次尝试"归属某个岛并带配额，是迭代生命周期的开始侧；
  // 结束侧仍是 `iteration_complete`。
  iteration: ['iteration_complete', 'attempt_started'],
  // 「最佳节点改变」同理：由 iteration_complete 载荷的 best_node_id/best_score
  // 承载，不是独立事件。留空而不是拿 iteration_complete 顶替——那会让
  // "最佳节点改变"在筛选器里和"迭代完成"完全等价，而它们不是一回事。
  best_node: [],
  // `llm_call_lost` 与 `llm_error` 同源，但记账含义不同：前者是"请求已发出、
  // 回应没拿到"，花费未知而非零，因此必须能在时间线上被筛出来。
  llm: ['llm_error', 'llm_call_lost'],
  insight: [
    'insight_extracted',
    'hypothesis_refuted',
    'mechanism_refuted',
    'reflection_design',
    'reflection_implementation',
    'reflection_mechanism',
    // 三岛摘要通道：一条结论从发布、送达、采纳到被候选使用，全程都是洞察的
    // 生命周期，而不是节点的评估结果。`exchange_check` 是"本轮无可发送"也要
    // 留痕的记账事件，与它同源。
    'exchange_check',
    'exchange_summary_published',
    'exchange_summary_replicated',
    'exchange_summary_failed',
    'exchange_delivered',
    // 中断修复：摘要已落库但进程在投递前退出，下一轮补齐投递时留痕。
    'exchange_delivery_backfilled',
    'exchange_rejected',
    'exchange_applied',
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
  run_finished: ['run_finished', 'run_aborted_invalid_init'],
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
