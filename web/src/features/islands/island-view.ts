/**
 * 三岛视图的纯推导层（TODO D6.4）。
 *
 * 与 `tree-adapter.ts` 同一套约束：不做 IO、不依赖 DOM，同一份输入两次输出必须
 * 完全一样，这样每条对账规则都能在没有浏览器的环境里被测试直接调用。
 *
 * 三条硬约束：
 * 1. **`null` 不是 0**。契约里每个计数都是 `int | None`，`None` 表示这次运行
 *    根本没记这笔账（单树运行、旧引擎、或该岛从未被调度）。显示成 0 会讲出
 *    一个假故事 —— 「从没跑过」和「跑了但没产出」看起来一模一样。
 * 2. **不替引擎圆场**。岛状态与运行状态矛盾、`attempt_total` 与
 *    `iterations_done` 不等、成本分项加起来不等于总额 —— 都如实说出来，
 *    不改数、不隐藏，也不"顺手修正"。
 * 3. **发布 / 投递 / 采纳 / 采用是四件事**（契约 `ExchangeViewResponse` 的注释
 *    就是这么写的），这里绝不合并成一个"交换成功数"。
 */
import type {
  ExchangeViewResponse,
  IslandCostResponse,
  IslandViewResponse,
  RunIslandCostResponse,
  RunIslandsResponse,
  TreeEdgeKind,
  TreeNodeDto,
} from '@/generated/api';

/**
 * 一条边。
 *
 * 形状与 `tree-adapter.ts` 的 `TreeEdgeInput` 相同，但这里**不 import 它**：
 * 适配层要用本模块的岛标签（`islandTitle`），本模块再反向依赖适配层就成了
 * 运行时的循环 import —— 类型 import 会被擦除，值 import 不会。
 */
export interface IslandEdge {
  source: string;
  target: string;
  kind: TreeEdgeKind;
}

/** 契约里"没有值"的统一显示。 */
export const NOT_RECORDED = '未记录';
export const NOT_SCORED = '未评分';

/** 历史单树运行的节点 `island_id` 是空串 —— 那是"没有岛"，不是岛名叫空串。 */
export const LEGACY_ISLAND = '';

/** 运行已经是终态时，岛仍写着 running 就要标出来（实测 fixture 就是这样）。 */
const TERMINAL_RUN_STATUSES = new Set([
  'completed',
  'success',
  'finished',
  'failed',
  'error',
  'cancelled',
  'canceled',
  'interrupted',
  'stopped',
]);

export function formatCount(value: number | null | undefined): string {
  if (value === null || value === undefined) return NOT_RECORDED;
  return String(value);
}

export function formatScore(value: number | null | undefined): string {
  if (value === null || value === undefined) return NOT_SCORED;
  return value.toFixed(2);
}

/**
 * 美元成本。只有 `cost_basis === 'recorded'` 才允许出现数字（契约
 * `RunIslandCostResponse` 明确：没报价的模型绝不编一个价）。
 */
export function formatUsd(cost: RunIslandCostResponse | null | undefined): string {
  if (!cost) return NOT_RECORDED;
  if (cost.cost_basis !== 'recorded' || cost.cost_usd === null || cost.cost_usd === undefined) {
    return `未记录（计价依据：${cost.cost_basis ?? NOT_RECORDED}）`;
  }
  return `$${cost.cost_usd.toFixed(4)}`;
}

const STATUS_LABELS: Record<string, string> = {
  pending: '待启动',
  running: '进行中',
  paused: '已暂停',
  finished: '已结束',
};

const PROFILE_LABELS: Record<string, string> = {
  performance: '性能优先',
  miss_alert: '漏报优先',
  efficiency: '效率优先',
  custom: '自定义',
};

/**
 * 各 profile 的策略说明。
 *
 * 权威文本在后端 `src/faultevolve/cloud/islands.py::PROFILE_FOCUS`（那份会进
 * prompt，真正影响算子选择）。这里只是把同一段话显示给人看 —— 所以**必须逐字
 * 一致**，改那边就要改这边。表里没有的 profile 直接显示原文：引擎加了新
 * profile 时，前端不该显示空白让人以为"这岛没有策略"。
 */
const PROFILE_FOCUS: Record<string, string> = {
  performance: '优先提升综合指标，允许在多个维度上权衡。',
  miss_alert: '优先降低漏报与误报：关注假阴性分组与召回-精确率折中。',
  efficiency: '优先提升效率与稳健性：关注推理耗时、内存与跨窗口稳定性。',
};

const STOP_REASON_LABELS: Record<string, string> = {
  max_attempts: '尝试次数用尽',
  stalled: '连续多轮没有有效改进',
  selection_exhausted: '连续失败达到上限',
  infra_failures: '基础设施连续失败',
  init_evaluation_invalid: '初始程序评估非法',
};

/** 未知取值一律回落原文，界面不编造语义。 */
export function islandStatusLabel(value: string | null | undefined): string {
  if (value === null || value === undefined || value === '') return NOT_RECORDED;
  return STATUS_LABELS[value] ?? value;
}

export function stopReasonLabel(value: string | null | undefined): string {
  if (value === null || value === undefined) return NOT_RECORDED;
  if (value === '') return '未停止（仍在配额内）';
  return STOP_REASON_LABELS[value] ?? value;
}

export function profileLabel(value: string | null | undefined): string {
  if (value === null || value === undefined || value === '') return NOT_RECORDED;
  return PROFILE_LABELS[value] ?? value;
}

export function profileFocus(value: string | null | undefined): string {
  if (value === null || value === undefined || value === '') return NOT_RECORDED;
  return PROFILE_FOCUS[value] ?? `未内置说明的策略「${value}」：以运行的配置为准。`;
}

/** 岛 id 的稳定排序：常规岛按字面序，历史单树（空串）排最后。 */
export function compareIslandIds(a: string, b: string): number {
  if (a === b) return 0;
  if (a === LEGACY_ISLAND) return 1;
  if (b === LEGACY_ISLAND) return -1;
  return a < b ? -1 : 1;
}

export function islandTitle(id: string): string {
  return id === LEGACY_ISLAND ? '未分岛（历史单树）' : `岛 ${id}`;
}

/**
 * 「全局最优落在哪里」的一句话（概览页与结果页共用同一句话，避免两页措辞打架）。
 *
 * 各岛的节点集合互不相交，所以运行级最优的节点在树里时，它的 `island_id`
 * 就是答案 —— 这是**读**出来的，不是按顺序猜的。节点不在树里（只记在
 * `run_summary.json`）或没有岛标记时照实说，不拿别的岛顶替。
 */
export function globalBestNote(
  nodes: readonly TreeNodeDto[],
  nodeId: string | null | undefined,
): string {
  if (nodeId === null || nodeId === undefined || nodeId === '') return '';
  const node = nodes.find((item) => item.id === nodeId) ?? null;
  if (node === null) return '（该节点不在树里，只有 run_summary.json 记了它）';
  const islandId = node.island_id ?? LEGACY_ISLAND;
  return islandId === LEGACY_ISLAND ? '（该节点没有岛标记）' : `（落在岛 ${islandId}）`;
}

/** 树里真实出现过的岛 id（不含空串），排序稳定。 */
export function treeIslandIds(nodes: readonly TreeNodeDto[]): string[] {
  const ids = new Set<string>();
  for (const node of nodes) {
    const id = node.island_id ?? LEGACY_ISLAND;
    if (id !== LEGACY_ISLAND) ids.add(id);
  }
  return [...ids].sort(compareIslandIds);
}

/** 节点属于哪个岛。 */
export function islandOfNode(node: TreeNodeDto): string {
  return node.island_id ?? LEGACY_ISLAND;
}

/** 嫁接边（外岛摘要 → 本岛节点）按岛的进出计数。 */
export interface GraftCounts {
  /** 别的岛的摘要 graft 进本岛的节点数。 */
  incoming: number;
  /** 本岛发布的摘要被 graft 到别的岛的次数。 */
  outgoing: number;
}

/**
 * 逐岛统计 `summary_cross` 边。
 *
 * 岛屿归属取自**节点**而不是边：契约的边只有 source/target/kind，"这条边来自
 * 哪个岛"其实是"source 节点属于哪个岛"。
 */
export function graftCountsByIsland(
  nodes: readonly TreeNodeDto[],
  edges: readonly IslandEdge[],
): Map<string, GraftCounts> {
  const islandOf = new Map<string, string>();
  for (const node of nodes) islandOf.set(node.id, islandOfNode(node));
  const counts = new Map<string, GraftCounts>();
  const bump = (id: string, key: keyof GraftCounts) => {
    const current = counts.get(id) ?? { incoming: 0, outgoing: 0 };
    current[key] += 1;
    counts.set(id, current);
  };
  for (const edge of edges) {
    if (edge.kind !== 'summary_cross') continue;
    const source = islandOf.get(edge.source);
    const target = islandOf.get(edge.target);
    if (target !== undefined) bump(target, 'incoming');
    if (source !== undefined) bump(source, 'outgoing');
  }
  return counts;
}

/** 一岛在自己树里的实测统计，全部从 `tree` 端点算，不经 run_summary 转手。 */
export interface IslandTreeStats {
  nodeCount: number;
  /** 本岛自己树里的最优（分数最高且已评分）节点。 */
  bestNodeId: string | null;
  bestScore: number | null;
  /** 本岛树里 Δ>0 且落在噪声带**外**的节点数 —— 只有这种才算有效改进。 */
  improvedCount: number;
  graft: GraftCounts;
}

/**
 * 单岛树统计。
 *
 * 并列树必须各算各的：`best_path` 是全局的，按岛切过滤之后仍可能落在别的岛上，
 * 所以"本岛最优"只能从本岛节点里重算。
 */
export function islandTreeStats(
  islandId: string,
  nodes: readonly TreeNodeDto[],
  edges: readonly IslandEdge[],
): IslandTreeStats {
  let bestNodeId: string | null = null;
  let bestScore: number | null = null;
  let improvedCount = 0;
  let nodeCount = 0;
  for (const node of nodes) {
    if (islandOfNode(node) !== islandId) continue;
    nodeCount += 1;
    const score = node.score ?? null;
    // 同分时取**先出现**的节点，保证两次调用给出同一个 id。
    if (score !== null && (bestScore === null || score > bestScore)) {
      bestScore = score;
      bestNodeId = node.id;
    }
    const delta = node.delta_score ?? null;
    if (delta !== null && delta > 0 && node.within_noise_band === false) improvedCount += 1;
  }
  const graft = graftCountsByIsland(nodes, edges).get(islandId) ?? { incoming: 0, outgoing: 0 };
  return { nodeCount, bestNodeId, bestScore, improvedCount, graft };
}

/** 一岛的完整视图：引擎记的生命周期 + 树里实测的 + 账本里的份额。 */
export interface IslandRow {
  islandId: string;
  title: string;
  /** 引擎在 run_summary 里记的这一岛；`null` 表示只出现在树里、从没被记账。 */
  view: IslandViewResponse | null;
  tree: IslandTreeStats;
  cost: IslandCostResponse | null;
  statusLabel: string;
  stopLabel: string;
  profileText: string;
  focusText: string;
  /**
   * 「运行已结束，但这个岛还写着 running」这类矛盾的说明文字。
   * 只描述，不修改 —— 数据是引擎写的，界面没有资格替它收尾。
   */
  stalenessNote: string | null;
  /** `view.best_score` 与树里实测的本岛最优是否对得上。 */
  bestScoreConsistent: boolean;
}

/**
 * 组装岛列表。
 *
 * 岛 id 取**引擎记账的**与**树里出现的**两个来源的并集，而不是只取前者：
 * 「配置了三岛、树里也有 a/b/c，但 `run_summary.json` 的 islands 块缺失」是
 * 真实会出现的中间态（引擎跑到一半被杀），只信一边就会把有数据的岛整艘丢掉。
 */
export function islandRows(
  islands: RunIslandsResponse | null | undefined,
  nodes: readonly TreeNodeDto[],
  edges: readonly IslandEdge[],
  runStatus: string | null | undefined,
): IslandRow[] {
  const recorded = islands?.islands ?? {};
  const ids = new Set<string>([...Object.keys(recorded), ...treeIslandIds(nodes)]);
  const terminal = runStatus !== null && runStatus !== undefined && TERMINAL_RUN_STATUSES.has(runStatus);
  return [...ids]
    .sort(compareIslandIds)
    .map((islandId) => {
      const view = recorded[islandId] ?? null;
      const tree = islandTreeStats(islandId, nodes, edges);
      const status = view?.status ?? null;
      return {
        islandId,
        title: islandTitle(islandId),
        view,
        tree,
        cost: islands?.cost?.by_island?.[islandId] ?? null,
        statusLabel: islandStatusLabel(status),
        stopLabel: stopReasonLabel(view?.stop_reason),
        profileText: profileLabel(view?.profile),
        focusText: profileFocus(view?.profile),
        stalenessNote:
          terminal && status === 'running'
            ? `运行已是「${runStatus}」，该岛仍记录为 running：引擎写入即为此，界面照原样显示。`
            : null,
        bestScoreConsistent: sameScore(view?.best_score, tree.bestScore),
      };
    });
}

/** 两个来源的最优分数对不对得上（允许 null==null，两边都没记就算一致）。 */
export function sameScore(a: number | null | undefined, b: number | null | undefined): boolean {
  if (a === null || a === undefined) return b === null || b === undefined;
  if (b === null || b === undefined) return false;
  // 两端各自 round/格式化过一次，1e-9 以内视为同一个数。
  return Math.abs(a - b) < 1e-9;
}

/** 交换链路上的一环：发布 → 投递 → 采纳 → 采用 → 其中已评估。 */
export interface ExchangeFact {
  key: string;
  label: string;
  value: string;
  /** 为什么单独算一件事，用于 tooltip。 */
  note: string;
}

/**
 * 把四个事实摊成四行，**永远不合并**。
 *
 * 「采用次数 > 采纳次数」是契约允许的正常现象（一条被采纳的摘要可以生成多个
 * 候选），所以这里既不能把它当异常报警，也不能把两个数平均成一个。
 */
export function exchangeFacts(exchange: ExchangeViewResponse | null | undefined): ExchangeFact[] {
  const value = (key: number | null | undefined) => formatCount(key);
  return [
    {
      key: 'summaries',
      label: '发布摘要',
      value: value(exchange?.summaries),
      note: '各岛写入摘要表的条数（同内容的重复发布会被合并成一条，另记证据）。',
    },
    {
      key: 'deliveries',
      label: '投递',
      value: value(exchange?.deliveries),
      note: '一条摘要可以投给多个岛，所以这条可以大于发布数。',
    },
    {
      key: 'accepted',
      label: '采纳',
      value: value(exchange?.accepted),
      note: '目标岛自己判定可用；判定不可用会落在「拒绝」里并带原因。',
    },
    {
      key: 'rejected',
      label: '拒绝',
      value: value(exchange?.rejected),
      note: '拒绝也是事实，不并入采纳数。',
    },
    {
      key: 'applications',
      label: '采用（生成候选）',
      value: value(exchange?.applications),
      note: '一次采纳可以生成多个候选，所以这条可以大于采纳数。',
    },
    {
      key: 'evaluated_applications',
      label: '其中已被评估',
      value: value(exchange?.evaluated_applications),
      note: '分数来自接收岛的本地评估器，不是摘要自带的。',
    },
  ];
}

/** 摘要类型的中文名；未知类型显示原文。 */
export function summaryKindLabel(kind: string): string {
  const labels: Record<string, string> = {
    best: '本岛最优',
    failure: '失败模式',
    knowledge: '知识结论',
  };
  return labels[kind] ?? kind;
}

/**
 * 置信度的中文名。
 *
 * `single_observation` 是「单次观察」，按需求 §6 **不能**渲染成已确认的规律，
 * 所以这里保留"单次"字样，文案里不出现"规律/结论已确认"。
 */
export function confidenceLabel(value: string | null | undefined): string {
  if (value === null || value === undefined || value === '') return NOT_RECORDED;
  const labels: Record<string, string> = {
    proposal: '提案',
    single_observation: '单次观察（未复现）',
    replicated: '已复现',
    statistically_confirmed: '统计确认',
  };
  return labels[value] ?? value;
}

export function deliveryStatusLabel(value: string | null | undefined): string {
  if (value === null || value === undefined || value === '') return NOT_RECORDED;
  const labels: Record<string, string> = {
    offered: '已投递待判定',
    accepted: '已采纳',
    rejected: '已拒绝',
  };
  return labels[value] ?? value;
}

/** 投递的拒绝原因。引擎写的是机器码，这里翻译成人话，未知原因保留原文。 */
export function deliveryReasonLabel(value: string | null | undefined): string {
  if (value === null || value === undefined || value === '') return '';
  const labels: Record<string, string> = {
    target_island_not_runnable: '目标岛当时不可用',
    task_fingerprint_mismatch: '任务指纹不一致',
    evaluator_fingerprint_mismatch: '评估器指纹不一致',
    superseded_by_newer_best: '已被该源岛更新的摘要取代',
  };
  return labels[value] ?? value;
}

/** 成本对账：各岛份额 + 无法归属的部分，必须等于总量。 */
export interface CostReconciliation {
  /** 各岛 token 之和（`null` 表示一个岛都没记）。 */
  islandTokens: number | null;
  totalTokens: number | null;
  sharedTokens: number | null;
  /** 总额减分项的差额；`balanced` 时为 0。 */
  gap: number | null;
  state: 'balanced' | 'unbalanced' | 'unknown';
  message: string;
}

export function reconcileCost(cost: RunIslandCostResponse | null | undefined): CostReconciliation {
  if (!cost) {
    return {
      islandTokens: null,
      totalTokens: null,
      sharedTokens: null,
      gap: null,
      state: 'unknown',
      message: '该运行没有逐岛成本账本。',
    };
  }
  const values = Object.values(cost.by_island ?? {});
  const islandTokens = values.length > 0
    ? values.reduce((sum, item) => sum + (item.tokens ?? 0), 0)
    : null;
  const total = cost.total_tokens ?? null;
  const shared = cost.shared_tokens ?? null;
  if (total === null || islandTokens === null) {
    return {
      islandTokens,
      totalTokens: total,
      sharedTokens: shared,
      gap: null,
      state: 'unknown',
      message: '成本账本缺少总量或逐岛分项，无法对账。',
    };
  }
  const attributed = islandTokens + (shared ?? 0);
  const gap = total - attributed;
  return {
    islandTokens,
    totalTokens: total,
    sharedTokens: shared,
    gap,
    state: gap === 0 ? 'balanced' : 'unbalanced',
    message:
      gap === 0
        ? `逐岛 ${islandTokens} + 未归属 ${shared ?? 0} = 总量 ${total}，账本自洽。`
        : `逐岛与未归属合计 ${attributed}，与总量 ${total} 相差 ${gap} —— 账本不自洽，此处如实显示差额。`,
  };
}

/** `attempt_total` 与 `outcome.iterations_done` 的对账。 */
export interface AttemptReconciliation {
  attemptTotal: number | null;
  iterationsDone: number | null;
  /** 界面自己按各岛 attempts 求和，用来验 `attempt_total` 这个派生字段。 */
  summedFromIslands: number;
  state: 'match' | 'mismatch' | 'unknown';
  message: string;
}

/**
 * 三者的关系必须显示出来而不是默认成立：
 * 引擎的身份等式是「各岛 attempts 之和 == 全局已执行评估数」，而
 * `attempt_total` 只是它的一个派生字段（契约注释明确要求界面自己比）。
 */
export function reconcileAttempts(
  islands: RunIslandsResponse | null | undefined,
  iterationsDone: number | null | undefined,
): AttemptReconciliation {
  const rows = Object.values(islands?.islands ?? {});
  const summedFromIslands = rows.reduce((sum, item) => sum + (item.attempts ?? 0), 0);
  const attemptTotal = islands?.attempt_total ?? null;
  const done = iterationsDone ?? null;
  if (attemptTotal === null || done === null) {
    return {
      attemptTotal,
      iterationsDone: done,
      summedFromIslands,
      state: 'unknown',
      message: '该运行没有记录岛级尝试数或全局评估数，无法核对。',
    };
  }
  const agrees = attemptTotal === done && summedFromIslands === attemptTotal;
  return {
    attemptTotal,
    iterationsDone: done,
    summedFromIslands,
    state: agrees ? 'match' : 'mismatch',
    message: agrees
      ? `各岛尝试数之和 ${summedFromIslands} = 岛级总量 ${attemptTotal} = 全局已执行评估 ${done}。`
      : `各岛尝试数之和 ${summedFromIslands}、岛级总量 ${attemptTotal}、全局已执行评估 ${done} 三者不完全相等 —— 以 API 返回值为准，此处不做修正。`,
  };
}

/** 单树（历史）运行与三岛运行的区别，界面据此决定画几棵树。 */
export type IslandShape = 'islands' | 'legacy-single' | 'unreadable';

/**
 * `state === 'missing'` 的正确读法。
 *
 * 契约的 detail 已经写好："该运行没有摘要交换层：单树运行早于多岛引擎"。
 * 历史单树运行**不是**数据缺失，界面不能因此画三个空岛，也不能报错。
 */
export function islandShape(islands: RunIslandsResponse | null | undefined): IslandShape {
  if (!islands || islands.state === 'invalid') return 'unreadable';
  const count = Object.keys(islands.islands ?? {}).length;
  if (islands.state === 'available' && count > 0) return 'islands';
  return 'legacy-single';
}

/** 树里是否真的分出了多个岛（与 run_summary 的记账无关）。 */
export function treeIsSplit(nodes: readonly TreeNodeDto[]): boolean {
  return treeIslandIds(nodes).length > 1;
}
