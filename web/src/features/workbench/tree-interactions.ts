/**
 * 树的交互逻辑：折叠、双亲路径追溯、对比选择（PRD §10.2 剩余四条）。
 *
 * 与 `tree-adapter.ts` 分开：那一份是"把后端数据变成图"，这一份是"用户在图上
 * 操作后，图该怎么变"。两者都必须是纯函数 —— React 组件只负责把状态接到它们。
 *
 * 一个贯穿全文件的约定：**任何操作都只影响"显示"，绝不修改底层树**（PRD §10.5
 * 明确要求）。所以这里没有一处会 mutate 输入的数组。
 */
import type { TreeNodeDto } from '@/generated/api';

// --------------------------------------------------------------------------
// 折叠
// --------------------------------------------------------------------------

/** 一个折叠状态：哪些节点被折起来了。 */
export type CollapseSet = ReadonlySet<string>;

export const NOTHING_COLLAPSED: CollapseSet = new Set<string>();

/**
 * 哪些节点有子节点可折叠。
 *
 * 必须从**边**算而不是从 `parent_id`：crossover 节点有两个父节点，
 * 用 `parent_id` 会漏掉第二父那边的子树（PRD §10.2 要求高亮双亲路径，
 * 说明第二父是真实存在的祖先关系）。
 *
 * 根也算进来 —— 根有子节点就能折叠，判据是"出现在 source 位置"，
 * 而不是"有没有入边"。
 */
export function collapsibleIds(edges: ReadonlyArray<{ source: string; target: string }>): Set<string> {
  return new Set(edges.map((edge) => edge.source));
}

/** 某个节点的全部后代（含自己），用于计算折叠时该隐藏谁。 */
export function descendantsOf(
  nodeId: string,
  edges: ReadonlyArray<{ source: string; target: string }>,
): Set<string> {
  const childrenOf = new Map<string, string[]>();
  for (const edge of edges) {
    const list = childrenOf.get(edge.source);
    if (list) list.push(edge.target);
    else childrenOf.set(edge.source, [edge.target]);
  }

  const seen = new Set<string>([nodeId]);
  const queue = [nodeId];
  while (queue.length > 0) {
    const current = queue.shift()!;
    for (const child of childrenOf.get(current) ?? []) {
      if (seen.has(child)) continue;
      seen.add(child);
      queue.push(child);
    }
  }
  return seen;
}

/**
 * 折叠后真正要渲染的节点集合。
 *
 * 一个节点被隐藏，当且仅当它的某个祖先被折叠 —— 它自己被折叠时**仍然显示**
 * （只是不显示子树），否则用户连"展开"这个按钮都没地方点。
 */
export function visibleNodeIds(
  allNodeIds: readonly string[],
  edges: ReadonlyArray<{ source: string; target: string }>,
  collapsed: CollapseSet,
): Set<string> {
  if (collapsed.size === 0) return new Set(allNodeIds);

  // 子 → 父
  const parentsOf = new Map<string, string[]>();
  for (const edge of edges) {
    const list = parentsOf.get(edge.target);
    if (list) list.push(edge.source);
    else parentsOf.set(edge.target, [edge.source]);
  }

  // `blocked[id]` = 从 id 上溯，**每一条**父链都会撞上某个被折叠的祖先。
  // 语义与"所有父链都被折叠祖先挡住"完全等价，但只算一次而不是每个节点
  // 枚举 2^深度 条路径 —— 之前的写法在 1000 节点的 crossover 树上要跑几分钟。
  const blocked = new Set<string>();
  for (const nodeId of allNodeIds) {
    if (blocked.has(nodeId)) continue; // 已判定为 blocked，子节点可以直接继承
    // 一条父链上只要还没撞到折叠祖先，就存在"可见路径"。
    let allChainsBlocked = true;
    const seen = new Set<string>([nodeId]);
    const queue = [nodeId];
    while (queue.length > 0) {
      const current = queue.shift()!;
      const parents = parentsOf.get(current);
      if (!parents || parents.length === 0) {
        allChainsBlocked = false; // 走到根：这是一条完好的路径
        break;
      }
      for (const parent of parents) {
        if (seen.has(parent)) continue; // 环：这条链到此为止，算被挡住
        if (collapsed.has(parent)) continue; // 撞上折叠祖先：这条分支被挡住
        seen.add(parent);
        queue.push(parent);
      }
    }
    if (allChainsBlocked) blocked.add(nodeId);
  }

  const hidden = new Set<string>();
  for (const nodeId of allNodeIds) {
    // 自己被折叠的节点仍然可见（否则没有展开按钮可点）。
    if (collapsed.has(nodeId)) continue;
    if (blocked.has(nodeId)) hidden.add(nodeId);
  }

  return new Set(allNodeIds.filter((id) => !hidden.has(id)));
}

/** 切换一个节点的折叠状态，返回新的集合（不 mutate 入参）。 */
export function toggleCollapse(collapsed: CollapseSet, nodeId: string): CollapseSet {
  const next = new Set(collapsed);
  if (next.has(nodeId)) next.delete(nodeId);
  else next.add(nodeId);
  return next;
}

/** 展开全部。 */
export function expandAll(): CollapseSet {
  return new Set<string>();
}

/** 只剩一个节点时，全折叠会让用户看到空图 —— 直接拒绝并说明原因。 */
export function collapseAllResult(
  collapsible: ReadonlySet<string>,
  nodeCount: number,
): { collapsed: CollapseSet; warning: string | null } {
  if (nodeCount <= 1) {
    return { collapsed: new Set(), warning: '只有一个节点，没有可折叠的子树' };
  }
  if (collapsible.size === 0) {
    return { collapsed: new Set(), warning: '这棵树没有子节点，全部都是根' };
  }
  return { collapsed: new Set(collapsible), warning: null };
}

// --------------------------------------------------------------------------
// 「低价值」子树：PRD 10.5「节点过多时默认折叠低价值子树」
// --------------------------------------------------------------------------

/**
 * 默认折叠哪些子树。
 *
 * "低价值"没有后端字段，用的是 4A 已经在后端算好的显著性判定
 * （`within_noise_band`）—— 落在噪声带内的改进**不能作为证据**，
 * 正是大树里最该先藏起来的东西。这不是前端发明标准，是复用后端结论。
 *
 * 只折叠**没有有效改进后代**的子树：如果某个 noise 节点的后代里有 progress，
 * 藏掉它就等于藏掉了改进路径。
 */
export function defaultCollapsedIds(
  nodes: readonly TreeNodeDto[],
  edges: ReadonlyArray<{ source: string; target: string }>,
): CollapseSet {
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const childrenOf = new Map<string, string[]>();
  for (const edge of edges) {
    const list = childrenOf.get(edge.source);
    if (list) list.push(edge.target);
    else childrenOf.set(edge.source, [edge.target]);
  }

  // 后代里有 progress / best 的节点集合
  const worthKeeping = new Set<string>();
  const hasWorth = (nodeId: string, seen: Set<string>): boolean => {
    if (seen.has(nodeId)) return false;
    seen.add(nodeId);
    const node = byId.get(nodeId);
    if (!node) return false;
    if (node.is_best) return true;
    if (node.within_noise_band === false) return true; // progress
    return (childrenOf.get(nodeId) ?? []).some((child) => hasWorth(child, seen));
  };
  for (const node of nodes) {
    if (hasWorth(node.id, new Set())) worthKeeping.add(node.id);
  }

  const collapsible = collapsibleIds(edges);
  const result = new Set<string>();
  for (const id of collapsible) {
    const node = byId.get(id);
    // 根节点不自动折叠：藏掉根会让用户以为树空了。
    if (!node || node.parent_id === null || node.parent_id === undefined) continue;
    if (node.within_noise_band !== true) continue; // 只折 noise 节点
    const descendants = descendantsOf(id, edges);
    const hasWorthDescendant = [...descendants].some((d) => worthKeeping.has(d));
    if (!hasWorthDescendant) result.add(id);
  }
  return result;
}

// --------------------------------------------------------------------------
// 双亲路径追溯：PRD §10.2「高亮 crossover 的双亲路径」
// --------------------------------------------------------------------------

/**
 * 从某节点上溯到根，返回路径上的全部节点 id（含起点与根）。
 *
 * 走**任一**父链。crossover 节点有两个父，这不是 bug 而是事实，所以返回的是
 * 一组路径而不是一条。调用方可以高亮全部，也可以只高亮主父。
 *
 * ## 为什么必须有路径数上限
 *
 * 每条 crossover 边在每一层都会让路径数翻倍，所以路径总数是 **2^深度**。
 * demo 运行里 crossover 出现过 0 次，问题不会暴露；但只要演化真的跑出
 * 一条 20 层的 crossover 链，这里就会返回 100 万条路径把浏览器卡死。
 * 所以 `maxPaths` 是**硬上限**，超了就把 `truncated` 置位而不是继续枚举 ——
 * 高亮用到的前几十条已经够看，界面卡住才是真事故。
 */
export const MAX_ANCESTOR_PATHS = 64;

export interface AncestorPathsResult {
  paths: string[][];
  /** 命中上限时为 true —— 调用方应当告诉用户"路径太多，只显示前 N 条"。 */
  truncated: boolean;
}

export function ancestorPaths(
  nodeId: string,
  edges: ReadonlyArray<{ source: string; target: string; kind?: string }>,
  maxPaths: number = MAX_ANCESTOR_PATHS,
): string[][] {
  return collectAncestorPaths(nodeId, edges, maxPaths).paths;
}

/** 需要知道"是否被截断"时用这个；只要路径本身用 `ancestorPaths` 就够。 */
export function collectAncestorPaths(
  nodeId: string,
  edges: ReadonlyArray<{ source: string; target: string; kind?: string }>,
  maxPaths: number = MAX_ANCESTOR_PATHS,
): AncestorPathsResult {
  const parentsOf = new Map<string, string[]>();
  for (const edge of edges) {
    const list = parentsOf.get(edge.target);
    if (list) list.push(edge.source);
    else parentsOf.set(edge.target, [edge.source]);
  }

  const paths: string[][] = [];
  let truncated = false;

  // 迭代式 DFS，显式栈。递归在 1000 深度下会爆调用栈，而 `concat` 每层复制
  // 一次数组会让分配量变成 O(depth²)。
  //
  // 栈里存的是**已走过的完整前缀**（含起点与当前节点），所以弹出时不需要再
  // 拼接 —— 早先一版把 `path` 与 `node` 分开存，两边不同步导致路径断成两截。
  type Frame = { path: string[]; seen: Set<string> };
  const stack: Frame[] = [{ path: [nodeId], seen: new Set([nodeId]) }];

  while (stack.length > 0) {
    const frame = stack.pop()!;
    const current = frame.path[frame.path.length - 1]!;
    const parents = parentsOf.get(current) ?? [];
    if (parents.length === 0) {
      if (paths.length >= maxPaths) {
        truncated = true;
        break;
      }
      paths.push(frame.path);
      continue;
    }
    // 父按声明顺序压栈（从后往前），弹出时才是从前到后 —— 与旧递归版一致，
    // "主父优先"这个顺序不能变：高亮默认走第一条路径。
    for (let i = parents.length - 1; i >= 0; i -= 1) {
      const parent = parents[i]!;
      if (frame.seen.has(parent)) {
        // 环：这条链到此为止，已经走过的部分本身仍是一条有效路径。
        if (paths.length < maxPaths) paths.push(frame.path);
        else truncated = true;
        continue;
      }
      const nextSeen = new Set(frame.seen);
      nextSeen.add(parent);
      stack.push({ path: [...frame.path, parent], seen: nextSeen });
    }
  }

  return { paths, truncated };
}

/**
 * 与某节点相关的全部节点 id（它自己 + 所有祖先）。
 *
 * 用于高亮：选中一个 crossover 节点时，两条父链都要亮。
 *
 * 这里**不用 `ancestorPaths`**：要的只是并集，而路径枚举是 2^深度。
 * 直接按父指针 BFS 上溯，代价是 O(祖先数) 且与 crossover 密度无关。
 */
export function relatedNodeIds(
  nodeId: string,
  edges: ReadonlyArray<{ source: string; target: string; kind?: string }>,
): Set<string> {
  const parentsOf = new Map<string, string[]>();
  for (const edge of edges) {
    const list = parentsOf.get(edge.target);
    if (list) list.push(edge.source);
    else parentsOf.set(edge.target, [edge.source]);
  }

  const all = new Set<string>([nodeId]);
  const queue = [nodeId];
  while (queue.length > 0) {
    const current = queue.shift()!;
    for (const parent of parentsOf.get(current) ?? []) {
      if (all.has(parent)) continue; // 已访问：兼作环检测
      all.add(parent);
      queue.push(parent);
    }
  }
  return all;
}

/** 双亲高亮用：返回需要加粗的边（源与目标都在高亮集合里的边）。 */
export function edgesWithin(
  ids: ReadonlySet<string>,
  edges: ReadonlyArray<{ source: string; target: string }>,
): Array<{ source: string; target: string }> {
  return edges.filter((edge) => ids.has(edge.source) && ids.has(edge.target));
}

// --------------------------------------------------------------------------
// 对比选择：PRD §10.4 与 §10.2「Shift/勾选两个节点进入对比」
// --------------------------------------------------------------------------

/** 对比最多两个节点 —— 三个以上没法两两并排。 */
export const COMPARE_LIMIT = 2;

export type CompareSelection = readonly string[];

/**
 * 切换一个节点是否参与对比。
 *
 * 已经选满两个时，**替换最旧的那个**（FIFO）而不是拒绝：用户的连续 Shift 点击
 * 应该是"把这两个挪到对比窗口"，卡住不动会让人以为页面死了。
 */
export function toggleCompare(current: CompareSelection, nodeId: string): CompareSelection {
  if (current.includes(nodeId)) return current.filter((id) => id !== nodeId);
  if (current.length < COMPARE_LIMIT) return [...current, nodeId];
  return [...current.slice(1), nodeId];
}

export function clearCompare(): CompareSelection {
  return [];
}

/** 两个节点是否可以进入对比：必须存在，且是不同节点。 */
export function canCompare(selection: CompareSelection): boolean {
  return selection.length === COMPARE_LIMIT && selection[0] !== selection[1];
}

// --------------------------------------------------------------------------
// 跨页定位：PRD §10.2「点击时间轴事件/排行榜条目时在树中定位节点」
// --------------------------------------------------------------------------

export interface LocateOutcome {
  /** 目标节点是否存在于当前（可能已过滤的）可见集合中。 */
  visible: boolean;
  /**
   * 是否需要先取消筛选才能看到它。
   *
   * 这是真实会遇到的情况：用户点了时间轴上一个已被筛掉的节点的事件，
   * 树里找不到它。诚实的做法是告诉用户"它在被隐藏的 N 个节点里"并给出恢复
   * 动作，而不是静悄悄地什么都不发生。
   */
  hiddenByFilter: boolean;
  /** 需要清除的过滤条件（`bestPathOnly` / `withinBandOnly` / `scoredOnly`）。 */
  blockingFilters: string[];
}

/**
 * 判断能否定位到某个节点。
 *
 * 传入可见集合而不是节点全量，是为了让调用方直接用它来决定要不要展开/取消筛选。
 */
export function locateNode(
  nodeId: string,
  visibleIds: ReadonlySet<string>,
  filter: {
    bestPathOnly: boolean;
    withinBandOnly: boolean;
    scoredOnly: boolean;
  },
): LocateOutcome {
  if (visibleIds.has(nodeId)) {
    return { visible: true, hiddenByFilter: false, blockingFilters: [] };
  }
  const blocking: string[] = [];
  if (filter.bestPathOnly) blocking.push('bestPathOnly');
  if (filter.withinBandOnly) blocking.push('withinBandOnly');
  if (filter.scoredOnly) blocking.push('scoredOnly');
  return { visible: false, hiddenByFilter: blocking.length > 0, blockingFilters: blocking };
}
