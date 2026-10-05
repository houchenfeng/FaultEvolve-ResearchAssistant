/**
 * 「评估—反思—纠错」闭环的展示逻辑（TODO 5.5 / PRD §9.5）。
 *
 * 分两层：
 * - **三层反思**：从事件流里还原 design / implementation / mechanism 三段反思。
 *   引擎为三层各发一种事件（`catalog.py` 的 `EVENT_TYPES` 里有全部三种）。
 * - **修复链**：从 `repair_parent_id` 向上追溯，还原"谁失败了 → 谁来修 → 修好了吗"。
 *
 * 重要事实：真实 demo 运行里这三类事件**一次都没触发**（mock 通路不走反思与修复），
 * 所以本模块的测试必须用合成事件，不能拿真实运行"验证通过"。
 */
import type { EventResponse, TreeEdgeKind, TreeNodeDto } from '@/generated/api';

/** 三层反思的固定顺序，来自引擎的设计（设计 → 实现 → 机制）。 */
export const REFLECTION_LAYERS = ['design', 'implementation', 'mechanism'] as const;
export type ReflectionLayer = (typeof REFLECTION_LAYERS)[number];

const LAYER_EVENTS: Record<ReflectionLayer, string> = {
  design: 'reflection_design',
  implementation: 'reflection_implementation',
  mechanism: 'reflection_mechanism',
};

const LAYER_LABELS: Record<ReflectionLayer, string> = {
  design: '设计反思',
  implementation: '实现反思',
  mechanism: '机制反思',
};

export interface ReflectionEntry {
  layer: ReflectionLayer;
  label: string;
  /** 命中的事件；没有就是"这一层没反思过"，不能显示成空字符串冒充有内容。 */
  event: EventResponse | null;
  /** payload 里的文本内容，逐层字段名不统一，取不到就是 null。 */
  text: string | null;
  ts: string;
}

const TEXT_KEYS = ['text', 'summary', 'content', 'message', 'detail', 'reason'] as const;

function extractText(event: EventResponse): string | null {
  const payload = event.payload as Record<string, unknown> | undefined;
  if (!payload) return null;
  for (const key of TEXT_KEYS) {
    const value = payload[key];
    if (typeof value === 'string' && value.trim().length > 0) return value;
  }
  return null;
}

/**
 * 还原三层反思。
 *
 * 同一层出现多次时取**最后一条**：反思是迭代的，最后一次代表当前认知，
 * 最早的那次已经过时。三层都取最新，缺失的层仍然占位（label 显示，内容为 null）。
 */
export function buildReflections(events: EventResponse[]): ReflectionEntry[] {
  const latest = new Map<ReflectionLayer, EventResponse>();
  for (const event of events) {
    for (const layer of REFLECTION_LAYERS) {
      if (event.type === LAYER_EVENTS[layer]) latest.set(layer, event);
    }
  }
  return REFLECTION_LAYERS.map((layer) => {
    const event = latest.get(layer) ?? null;
    return {
      layer,
      label: LAYER_LABELS[layer],
      event,
      text: event ? extractText(event) : null,
      ts: event?.ts ?? '',
    };
  });
}

// --------------------------------------------------------------------------
// 修复链
// --------------------------------------------------------------------------

/** 修复链的一环。 */
export interface RepairLink {
  /** 失败的节点。 */
  failedId: string;
  /** 修它的节点；`null` 表示还没人来修（引擎尚未产出修复节点）。 */
  repairerId: string | null;
  failedScore: number | null;
  repairerScore: number | null;
  /** 修复是否带来了分数变化；两侧都没分数时是 null 而不是 false。 */
  scoreDelta: number | null;
  /** 修复节点的状态，用于判断"修好了没有"。 */
  repairerStatus: TreeNodeDto['status'] | null;
  /**
   * 引擎记录的修复次数（`repair_count`）；没有记录是 null。
   *
   * 取自**失败节点**而不是修复节点：引擎把计数写在被修的那一侧
   * （`engine.py:2009`），而 `repair_parent_id` 指针在修复者身上。
   */
  repairCount: number | null;
  /** 是否已尝试过修复但耗尽。同样取自失败节点（`engine.py:2006` 写链根）。 */
  exhausted: boolean | null;
}

/** 一条修复链的记账数据（次数 / 是否耗尽）。 */
export interface RepairBookkeeping {
  /** 引擎记录的修复次数；没有记录是 `null`，前端要说「未记录」而不是 0。 */
  count: number | null;
  /** 是否已尝试过修复但耗尽；没有记录是 `null`（不是 `false`）。 */
  exhausted: boolean | null;
}

const _isSet = (value: unknown) => value !== null && value !== undefined;

/**
 * 取一条修复链的记账数据。
 *
 * **引擎把这两个字段写在被修的那个失败节点上，不在修复节点上：**
 * `engine.py:2009` `increment_repair_count(failed_node.id)`、
 * `engine.py:2006` `mark_repair_exhausted(root.id)`（链根，也就是最初的失败节点）。
 * 而指针 `repair_parent_id` 是**修复节点**持有的，方向正好相反 ——
 * 于是"谁持有指针就读谁身上的字段"这种写法永远读到 `null`，UI 上的
 * 「重试 N 次」「已耗尽」两处在真实运行里恒不显示。
 *
 * 所以这里以**失败节点**为准；只有失败节点自己也没记时才退回修复节点
 * （万一将来引擎改了落点，UI 不至于静默变空，也不是瞎猜一个 0）。
 */
export function repairBookkeeping(
  failed: TreeNodeDto | null | undefined,
  repairer: TreeNodeDto | null | undefined,
): RepairBookkeeping {
  return {
    count: _isSet(failed?.repair_count)
      ? (failed?.repair_count ?? null)
      : (repairer?.repair_count ?? null),
    exhausted: _isSet(failed?.repair_exhausted)
      ? (failed?.repair_exhausted ?? null)
      : (repairer?.repair_exhausted ?? null),
  };
}

/**
 * 从树里还原修复链。
 *
 * 走 `repair_parent_id` 而不是事件流：事件流是**运行顺序**，修复链是**因果关系**。
 * 用事件流会在重试多次时把同一个失败节点拆成好几条链。
 */
export function buildRepairChain(nodes: TreeNodeDto[]): RepairLink[] {
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const links: RepairLink[] = [];

  for (const node of nodes) {
    if (!node.repair_parent_id) continue;
    const failed = byId.get(node.repair_parent_id);
    if (!failed) continue; // 悬空引用：树已经报过 warning，这里不重复造一条假链

    const failedScore = failed.score ?? null;
    const repairerScore = node.score ?? null;
    const bookkeeping = repairBookkeeping(failed, node);
    links.push({
      failedId: failed.id,
      repairerId: node.id,
      failedScore,
      repairerScore,
      // 两侧都有分数才算得出变化；缺一个就是"算不出"，不是"没变化"。
      scoreDelta:
        failedScore === null || repairerScore === null
          ? null
          : Number((repairerScore - failedScore).toFixed(6)),
      repairerStatus: node.status,
      // 记账在失败节点上，不在修复者身上 —— 见 repairBookkeeping 的说明。
      repairCount: bookkeeping.count,
      exhausted: bookkeeping.exhausted,
    });
  }

  return links.sort((a, b) => a.failedId.localeCompare(b.failedId));
}

/**
 * 一个节点是否是修复者。
 *
 * 判据来自引擎 `cloud/tree.py`：创建修复节点时，新节点**自己**带上
 * `operator=REPAIR` 与 `repair_parent_id=failed_node.id` —— 指针方向是
 * 「修复者 → 它修的那个失败节点」。所以看一个节点有没有 `repair_parent_id`，
 * 而不是看有没有别的节点指向它。
 */
export function isRepairer(node: TreeNodeDto): boolean {
  return typeof node.repair_parent_id === 'string' && node.repair_parent_id.length > 0;
}

// --------------------------------------------------------------------------
// 闭环汇总
// --------------------------------------------------------------------------

export interface LoopSummary {
  /** 评估过的节点数（有分数的）。 */
  evaluatedCount: number;
  /** 有效改进数（Δ 超出噪声带）。 */
  improvedCount: number;
  /** 噪声内的变化数。 */
  noiseCount: number;
  /** 无法判断（缺 Δ 或缺噪声估计）。 */
  unknownCount: number;
  /** 修复链长度。 */
  repairCount: number;
  /** 修复成功的次数（修复节点的分数严格高于失败节点）。 */
  repairSucceeded: number;
  /** 修复失败/耗尽的次数。 */
  repairFailed: number;
  /** 三层反思齐了几层。 */
  reflectionLayersPresent: number;
}

/**
 * 闭环汇总。
 *
 * 计数全部来自树与事件，**不引入任何新的判定** —— 显著性判定在后端
 * （`within_noise_band`），这里只做累加。
 */
export function summarizeLoop(
  nodes: TreeNodeDto[],
  events: EventResponse[],
): LoopSummary {
  let improved = 0;
  let noise = 0;
  let unknown = 0;
  let evaluated = 0;

  for (const node of nodes) {
    if (node.score !== null && node.score !== undefined) evaluated += 1;
    const band = node.within_noise_band;
    if (band === null || band === undefined) {
      // 根节点没有 Δ 是正常的，不该被算成"无法判断"来虚增未知数。
      if (node.delta_score !== null && node.delta_score !== undefined) unknown += 1;
    } else if (band) {
      noise += 1;
    } else {
      improved += 1;
    }
  }

  const chain = buildRepairChain(nodes);
  const succeeded = chain.filter(
    (link) => link.scoreDelta !== null && link.scoreDelta > 0,
  ).length;
  const failed = chain.filter(
    (link) => link.exhausted === true || (link.scoreDelta !== null && link.scoreDelta <= 0),
  ).length;

  return {
    evaluatedCount: evaluated,
    improvedCount: improved,
    noiseCount: noise,
    unknownCount: unknown,
    repairCount: chain.length,
    repairSucceeded: succeeded,
    repairFailed: failed,
    reflectionLayersPresent: buildReflections(events).filter((entry) => entry.event !== null).length,
  };
}

/** 边的 kind → 中文，供修复链图例使用。 */
export const EDGE_KIND_LABELS: Record<TreeEdgeKind, string> = {
  parent: '父子',
  crossover_second_parent: '交叉第二父',
  repair: '修复',
};
