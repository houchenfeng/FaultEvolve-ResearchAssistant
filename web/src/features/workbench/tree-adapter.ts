/**
 * 进化树的适配层：后端 DTO → React Flow 的 nodes/edges，加上布局与过滤（TODO 5.1）。
 *
 * 与 TreeCanvas 组件分文件：react-refresh 要求组件文件只导出组件，而这些纯函数
 * 要被测试直接引用，也要在没有 DOM 的环境里验证（性能测试就是纯调用）。
 *
 * 三条硬约束：
 * 1. **不丢信息**。节点上的每个字段都要能被抽屉显示，转换时不能顺手"整理"掉。
 * 2. **不编造**。`score === null` 仍是 null（契约明确要求渲染「未评分」而不是 0）。
 * 3. **布局是纯函数**。同一份数据算两次坐标必须完全相同，否则每次渲染节点都会跳。
 */
import type { Edge, Node } from '@xyflow/react';
import dagre from 'dagre';
import type {
  NodeStatus,
  OperatorType,
  TreeEdgeKind,
  TreeNodeDto,
} from '@/generated/api';
import { classifySignificance } from '@/features/workbench/significance';

/** 节点卡上显示的派生信息，与 DTO 分开存放避免污染原始数据。 */
export interface TreeNodeData extends Record<string, unknown> {
  node: TreeNodeDto;
  /** 短 ID：UI 上一律显示它，完整 ID 放 title。 */
  shortId: string;
  /** 「未评分」而不是 0 —— 契约禁止把 null 渲染成数字。 */
  scoreLabel: string;
  /** 带符号的 Δ，null 时是「—」。 */
  deltaLabel: string;
  /** 噪声带三态：true 带内、false 带外、null 无法判断。 */
  bandState: 'inside' | 'outside' | 'unknown';
  /** 四档显著性，由 `significanceOf` 判定（与 significance.ts 同源）。 */
  significance: 'best' | 'progress' | 'noise' | 'unknown';
  /** 采纳的知识卡数量。 */
  cardCount: number;
  /** 该分支被投放过的知识卡总数（不等于 cardCount，见下）。 */
  offeredCardCount: number;
  /**
   * 采纳了但**不在**投放列表里的卡。
   *
   * 实测存在这种卡：demo 运行的 `FE01` 走的是知识库预置注入，从未进过
   * `branch_offered_cards`。所以"采纳 N / 投放 M"这种算法会算错 ——
   * 界面必须分开显示两个列表，而不是显示成一个分数。
   */
  injectedCardIds: string[];
  /** 是否有第二父（crossover）—— PRD 10.1 要求节点上标出来。 */
  hasSecondParent: boolean;
  operatorLabel: string;
  statusLabel: string;
  depth: number;

  // ------------------------------------------------------------------------
  // 以下几项由 `TreeCanvas` 在渲染时补上（不属于后端数据）。
  // 全部**可选**：纯函数层不设置它们，只有组件层才知道折叠与最优路径的状态。
  // ------------------------------------------------------------------------
  /** 该节点是否在最优路径上。 */
  isOnBestPath?: boolean;
  /** 折叠时角标要显示的隐藏后代数量。 */
  hiddenCount?: number;
  /** 是否可折叠（有子节点）。 */
  collapsible?: boolean;
  collapsed?: boolean;
  onToggleCollapse?: (nodeId: string) => void;
}

export type TreeFlowNode = Node<TreeNodeData, 'treeNode'>;
export type TreeFlowEdge = Edge<{ kind: TreeEdgeKind }>;

/**
 * 后端 `TreeResponse.edges` 的一项。
 *
 * 单独定义而不是直接用 `TreeFlowEdge`：契约里 `kind` 是必填，而 React Flow 的
 * `Edge` 把它放进了可选的 `data` 里。两边形状不同，混用会让 `kind` 静默变 undefined。
 */
export interface TreeEdgeInput {
  source: string;
  target: string;
  kind: TreeEdgeKind;
}

/**
 * 三种边各自的线型（PRD §9.8：不同关系必须一眼可分）。
 *
 * 颜色全部引用项目真实存在的 CSS 变量（见 `styles/theme.css`）。这里曾写过
 * `--color-line-strong` / `--color-accent` / `--color-warn` —— 三个都不存在，
 * 而 React Flow 拿到的 stroke 是内联样式，解析失败会**静默变成黑色**，
 * 深色主题下三种边就全糊在一起。变量名对不上时不要凭直觉起。
 */
const EDGE_STYLE: Record<TreeEdgeKind, { stroke: string; dash?: string; label: string }> = {
  parent: { stroke: 'var(--color-border-strong)', label: '' },
  crossover_second_parent: { stroke: 'var(--color-brand-500)', dash: '6 4', label: '交叉' },
  repair: { stroke: 'var(--color-warning-500)', dash: '2 3', label: '修复' },
};

/**
 * 算子的中文标签。
 *
 * 取值必须与契约的 `OperatorType` 一致（实测 10 个：init / refine / recall_focus /
 * threshold_calibrate / inject / transplant / crossover / repair / hpo / patch）。
 * 表里没有的算子直接显示原文 —— 引擎加了新算子时前端不该显示空白。
 */
const OPERATOR_LABELS: Record<OperatorType, string> = {
  init: '初始程序',
  refine: '精炼',
  recall_focus: '召回聚焦',
  threshold_calibrate: '阈值校准',
  inject: '注入',
  transplant: '移植',
  crossover: '交叉',
  repair: '修复',
  hpo: '超参搜索',
  patch: '热补丁',
};

/** 节点状态的中文标签，取值同契约 `NodeStatus`。 */
const STATUS_LABELS: Record<NodeStatus, string> = {
  pending: '待评估',
  evaluating: '评估中',
  done: '已完成',
  invalid: '非法',
  abandoned: '已放弃',
};

/** ID 太长在节点上没法看，统一截到 8 位。 */
export function shortId(id: string): string {
  return id.length <= 8 ? id : id.slice(0, 8);
}

function formatScore(score: number | null | undefined): string {
  if (score === null || score === undefined) return '未评分';
  // 固定两位：分数是用于比较的量，不是用来读出有效数字的。
  return score.toFixed(2);
}

function formatDelta(delta: number | null | undefined): string {
  if (delta === null || delta === undefined) return '—';
  return delta > 0 ? `+${delta.toFixed(2)}` : delta.toFixed(2);
}

/** 噪声带是三态，`null` 必须与 `false` 区分开（PRD §9.4）。 */
export function bandStateOf(node: TreeNodeDto): 'inside' | 'outside' | 'unknown' {
  if (node.within_noise_band === null || node.within_noise_band === undefined) {
    return 'unknown';
  }
  return node.within_noise_band ? 'inside' : 'outside';
}

export function toTreeNodeData(node: TreeNodeDto): TreeNodeData {
  const cards = node.adopted_card_ids ?? [];
  const offered = node.offered_card_ids ?? [];
  const offeredSet = new Set(offered);
  return {
    node,
    shortId: shortId(node.id),
    scoreLabel: formatScore(node.score),
    deltaLabel: formatDelta(node.delta_score),
    bandState: bandStateOf(node),
    // 显著性在这里就定下来，`toFlowNodes` 不再重复判定。
    significance: classifySignificance(node),
    cardCount: cards.length,
    offeredCardCount: offered.length,
    injectedCardIds: cards.filter((card) => !offeredSet.has(card)),
    hasSecondParent: (node.second_parent_ids ?? []).length > 0,
    operatorLabel: OPERATOR_LABELS[node.operator] ?? node.operator,
    statusLabel: STATUS_LABELS[node.status] ?? node.status,
    depth: node.depth,
  };
}

export function toFlowNodes(nodes: TreeNodeDto[], bestPath: string[] = []): TreeFlowNode[] {
  const onPath = new Set(bestPath);
  return nodes.map((node) => ({
    id: node.id,
    type: 'treeNode' as const,
    position: { x: 0, y: 0 },
    data: {
      ...toTreeNodeData(node),
      isOnBestPath: onPath.has(node.id),
      // 折叠相关字段的默认值：纯函数层不知道折叠状态，组件层会覆盖。
      hiddenCount: 0,
      collapsible: false,
      collapsed: false,
    },
  }));
}

export function toFlowEdges(edges: TreeEdgeInput[]): TreeFlowEdge[] {
  return edges.map((edge) => {
    // 契约保证 kind 必填，但运行目录可能来自旧版本引擎 —— 未知 kind 退回普通父边，
    // 不能让整张图渲染失败。
    const style = EDGE_STYLE[edge.kind] ?? EDGE_STYLE.parent;
    return {
      id: `${edge.source}->${edge.target}:${edge.kind}`,
      source: edge.source,
      target: edge.target,
      data: { kind: edge.kind },
      label: style.label || undefined,
      style: {
        stroke: style.stroke,
        strokeWidth: 1.5,
        ...(style.dash ? { strokeDasharray: style.dash } : {}),
      },
    };
  });
}

/**
 * 节点卡尺寸（概念图 `docs/images/frontend-concepts/02-evolution-workbench.png` 的密度）。
 *
 * 概念图里的节点是紧凑的竖排小卡：ID / 大分数 / 算子三层，约 112×60。
 * 我们的卡还得多放状态文字、最优/双亲标记和知识卡计数（PRD §10.1 的八项硬要求
 * 一项都不能少），所以取 176×86 —— 保住概念图的竖排层次，同时装得下八项。
 *
 * **必须导出**：`TreeCanvas` 要用它算"把选中节点移到视野中央"的偏移，
 * `rankBands` 要用它算代数分带的包围盒。这里曾经在组件里硬编码过 `+ 110`
 * （= 220/2），一旦改尺寸就会静默错位 —— 尺寸只能有一个来源。
 */
export const TREE_NODE_WIDTH = 176;
export const TREE_NODE_HEIGHT = 86;

const NODE_WIDTH = TREE_NODE_WIDTH;
const NODE_HEIGHT = TREE_NODE_HEIGHT;

/**
 * dagre 自上而下布局。
 *
 * 显式声明 `rankdir: 'TB'` 等参数而不是用默认值：默认值随 dagre 版本变，
 * 而"同一份数据两次算出同一组坐标"是要进测试的契约。
 *
 * `nodeSep` / `rankSep` 取自概念图的密度：卡片小了一圈，间距也要跟着收，
 * 否则节点会稀稀拉拉地浮在大片空白里。但**不能收到贴边** ——
 * 节点卡底部有折叠按钮（`-bottom-2`），左右有双亲连线绕行，留白小于 12px
 * 就会互相压到。
 */
export function layoutTree(
  nodes: TreeFlowNode[],
  edges: TreeFlowEdge[],
  options: { direction?: 'TB' | 'LR'; nodeSep?: number; rankSep?: number } = {},
): TreeFlowNode[] {
  const { direction = 'TB', nodeSep = 26, rankSep = 58 } = options;
  if (nodes.length === 0) return [];

  const graph = new dagre.graphlib.Graph();
  graph.setDefaultEdgeLabel(() => ({}));
  graph.setGraph({ rankdir: direction, nodesep: nodeSep, ranksep: rankSep, marginx: 24, marginy: 24 });

  for (const node of nodes) {
    graph.setNode(node.id, { width: NODE_WIDTH, height: NODE_HEIGHT });
  }
  for (const edge of edges) {
    // dagre 遇到未知节点会抛错，而边的端点来自后端、未必都在节点列表里。
    if (graph.hasNode(edge.source) && graph.hasNode(edge.target)) {
      graph.setEdge(edge.source, edge.target);
    }
  }

  dagre.layout(graph);

  // 保持输入顺序：React Flow 用数组顺序做渲染与键盘导航顺序，
  // 让布局去改顺序会让"第一个节点"随布局漂移。
  return nodes.map((node) => {
    const positioned = graph.node(node.id);
    if (!positioned) return node;
    return {
      ...node,
      // dagre 给的是中心点，React Flow 的 position 是左上角。
      position: {
        x: Math.round(positioned.x - NODE_WIDTH / 2),
        y: Math.round(positioned.y - NODE_HEIGHT / 2),
      },
    };
  });
}

/** 一个「代」在画布上占的竖直条带（概念图里左侧那条带「第 N 代 (n)」的浅色带）。 */
export interface TreeRankBand {
  /** 代数，取自 `TreeNodeDto.depth`。 */
  depth: number;
  /** 「第 3 代」。 */
  label: string;
  /** 这一代有几个节点 —— 概念图把计数写在条带标题里。 */
  count: number;
  /** 条带矩形，与节点同一坐标系（React Flow 的 flow 坐标，不是屏幕坐标）。 */
  x: number;
  y: number;
  width: number;
  height: number;
}

/**
 * 按 `depth` 分组，算出每一代的竖直条带。
 *
 * 为什么放在纯函数层而不是组件里：条带坐标是纯几何，脱离 DOM 就能验证；
 * 而且"同一份数据算两次坐标相同"这条对条带同样成立，写在测试里才守得住。
 *
 * **所有条带共用同一个横向范围**（整棵树的包围盒），而不是各代自己的范围。
 * 两个理由：一是概念图里就是等宽的整列；二是各代自成宽度会让 6 条带子
 * 左右参差（实测 212 / 1106 / 1298 / 1298 / 1298 / 1242），看着像是布局出错。
 * 条带只回答"这是第几代"，横向信息由节点位置本身表达。
 *
 * 上留白比下留白大：条带标题（「第 N 代」）写在顶部那条留白里，
 * 留白不够就会和该代第一个节点的上边框贴在一起。
 *
 * 入参必须是**已布局**的节点（`layoutTree` 之后）。未布局时所有节点的
 * `position` 都是 `{x:0,y:0}`，算出来的条带会全叠在原点上 —— 所以调用方
 * 一定要传布局后的结果。
 */
export function rankBands(
  nodes: TreeFlowNode[],
  options: { paddingX?: number; paddingTop?: number; paddingBottom?: number } = {},
): TreeRankBand[] {
  const { paddingX = 18, paddingTop = 30, paddingBottom = 14 } = options;

  const groups = new Map<number, TreeFlowNode[]>();
  for (const node of nodes) {
    const depth = node.data?.depth;
    // depth 缺失的节点不进条带：随便归一代会把两代混进同一条带里，
    // 看上去像是布局错了，其实是数据缺字段。
    if (typeof depth !== 'number' || !Number.isFinite(depth)) continue;
    const bucket = groups.get(depth);
    if (bucket) bucket.push(node);
    else groups.set(depth, [node]);
  }
  if (groups.size === 0) return [];

  const all = [...groups.values()].flat();
  const treeMinX = Math.min(...all.map((node) => node.position.x));
  const treeMaxX = Math.max(...all.map((node) => node.position.x)) + TREE_NODE_WIDTH;
  const x = treeMinX - paddingX;
  const width = treeMaxX - treeMinX + paddingX * 2;

  return [...groups.entries()]
    .sort(([a], [b]) => a - b)
    .map(([depth, members]) => {
      const ys = members.map((node) => node.position.y);
      const y = Math.min(...ys) - paddingTop;
      const height = Math.max(...ys) + TREE_NODE_HEIGHT + paddingBottom - y;
      return { depth, label: `第 ${depth} 代`, count: members.length, x, y, width, height };
    });
}

/** 一次完成 DTO → 可渲染的图。 */
export function buildFlowGraph(
  nodes: TreeNodeDto[],
  edges: TreeEdgeInput[],
  bestPath: string[] = [],
) {
  const flowNodes = toFlowNodes(nodes, bestPath);
  const flowEdges = toFlowEdges(edges);
  return { nodes: layoutTree(flowNodes, flowEdges), edges: flowEdges };
}

export interface TreeFilter {
  /** 只看这条最优路径上的节点。 */
  bestPathOnly: boolean;
  /** 只看落在噪声带内的节点（改进不显著，容易是噪声）。 */
  withinBandOnly: boolean;
  /** 只看有分数的节点。 */
  scoredOnly: boolean;
  /** 隐藏这些状态的节点。 */
  hiddenStatuses: NodeStatus[];
  /** 只看这些 operator；空数组表示不过滤。 */
  operators: string[];
  /** 关键词，匹配短 ID 或 intent。 */
  keyword: string;
}

export const EMPTY_TREE_FILTER: TreeFilter = {
  bestPathOnly: false,
  withinBandOnly: false,
  scoredOnly: false,
  hiddenStatuses: [],
  operators: [],
  keyword: '',
};

/** 节点是否通过过滤。纯谓词，便于单测。 */
export function passesFilter(node: TreeNodeDto, filter: TreeFilter, bestPath: string[]): boolean {
  if (filter.bestPathOnly && !bestPath.includes(node.id)) return false;
  if (filter.withinBandOnly && bandStateOf(node) !== 'inside') return false;
  if (filter.scoredOnly && (node.score === null || node.score === undefined)) return false;
  if (filter.hiddenStatuses.includes(node.status)) return false;
  if (filter.operators.length > 0 && !filter.operators.includes(node.operator)) return false;
  const keyword = filter.keyword.trim().toLowerCase();
  if (keyword) {
    const haystack = `${shortId(node.id)} ${node.intent ?? ''}`.toLowerCase();
    if (!haystack.includes(keyword)) return false;
  }
  return true;
}

export interface FilteredGraph {
  nodes: TreeFlowNode[];
  edges: TreeFlowEdge[];
  /** 被过滤掉的节点数，用于「已隐藏 N 个节点」提示。 */
  hiddenCount: number;
  /**
 * * 被隐藏节点的后代仍可能被保留节点的边引用吗？会。
   * 过滤后的图必须重新布局，否则保留下来的节点会停在原来的坐标上，
   * 看起来像"树塌了一块"。这里返回重新布局的结果。
   */
}

/** 应用过滤器并**重新布局**，返回可直接交给 React Flow 的图。 */
export function filterTree(
  nodes: TreeNodeDto[],
  edges: TreeEdgeInput[],
  filter: TreeFilter,
  bestPath: string[] = [],
  /**
   * 是否在返回前算坐标。默认算 —— 单看过滤这一步，坐标本来就是对的。
   *
   * 传 `false` 的唯一理由是**调用方还要再布局一次**：`TreeCanvas` 在过滤之后
   * 还要按折叠状态裁掉一批节点，那批节点一走，刚才算出来的坐标就作废了
   * （dagre 是整图排布，不是增量）。500 节点实测两次布局占首帧 1.6 s，
   * 去掉白算的那一次回到 0.4 s —— TODO §12.6 要的正是"不要反复计算布局"。
   */
  layout = true,
): FilteredGraph {
  const kept = nodes.filter((node) => passesFilter(node, filter, bestPath));
  const keptIds = new Set(kept.map((node) => node.id));
  // 边只要有一端被藏起来就不能画，否则会连到空气。
  const keptEdges = edges.filter((edge) => keptIds.has(edge.source) && keptIds.has(edge.target));

  const flowNodes = toFlowNodes(kept, bestPath);
  const flowEdges = toFlowEdges(keptEdges);
  return {
    nodes: layout ? layoutTree(flowNodes, flowEdges) : flowNodes,
    edges: flowEdges,
    hiddenCount: nodes.length - kept.length,
  };
}

/**
 * 合成树，供性能测试使用（TODO 5.7：100 / 500 / 1000 节点）。
 *
 * 真实运行规模差两个数量级（实测 demo 只有 6 节点 5 边），拿真实数据"假装"
 * 通过性能测试是自欺。宽度可配以模拟分叉，深度按对数增长避免栈溢出。
 *
 * ## crossover 密度必须可配，而且默认**很低**
 *
 * 引擎是 bandit 概率选择 crossover，实测 demo 运行里 6 个节点一次 crossover
 * 都没发生。早先这里写成"每 3 层强制一条 crossover 边"，等于把最坏情况当典型 ——
 * 更糟的是它让**路径数变成 2^深度**（每条 crossover 边在每层都让路径翻倍），
 * 100 节点时 `ancestorPaths` 就要返回几千条，测试根本跑不完。
 *
 * 所以默认 5%（接近真实量级），需要压最坏情况时显式传 `crossoverEvery: 1`。
 */
export function buildSyntheticTree(
  nodeCount: number,
  branchWidth = 4,
  crossoverEvery = 20,
): { nodes: TreeNodeDto[]; edges: TreeEdgeInput[] } {
  const nodes: TreeNodeDto[] = [];
  const edges: TreeEdgeInput[] = [];
  const width = Math.max(1, branchWidth);
  const cxEvery = Math.max(0, Math.floor(crossoverEvery));

  for (let i = 0; i < nodeCount; i += 1) {
    const isRoot = i === 0;
    const id = `syn-${String(i).padStart(5, '0')}`;
    // 深度按宽度对数增长：宽度 4 时每 4 个节点下潜一层，深度是 O(log n)。
    const depth = isRoot ? 0 : Math.floor(Math.log2(i + 1) / Math.log2(width + 1)) + 1;
    const isCrossover = !isRoot && cxEvery > 0 && i % cxEvery === 0;
    nodes.push({
      id,
      branch_id: `branch-${depth % 3}`,
      depth,
      operator: isRoot ? 'init' : isCrossover ? 'crossover' : 'refine',
      hypothesis_status: isRoot ? 'undetermined' : 'open',
      status: isRoot ? 'done' : depth % 2 === 0 ? 'done' : 'pending',
      score: isRoot ? 0 : Number((Math.sin(i) * 10).toFixed(4)),
      delta_score: isRoot ? null : Number((Math.cos(i) * 0.5).toFixed(4)),
      noise_delta: isRoot ? null : 0.3,
      within_noise_band: isRoot ? null : Math.abs(Math.cos(i)) > 0.3,
      adopted_card_ids: i % 7 === 0 ? [`card-${i}`] : [],
      second_parent_ids: isCrossover ? [`syn-${String(i - 2).padStart(5, '0')}`] : [],
    });

    if (isRoot) continue;
    // 父节点是"往前数 width 个里的那个"，保证树不会退化成链。
    const parentIndex = Math.max(0, i - width);
    const parentId = `syn-${String(parentIndex).padStart(5, '0')}`;
    edges.push({ source: parentId, target: id, kind: 'parent' });
    if (isCrossover) {
      edges.push({
        source: `syn-${String(i - 2).padStart(5, '0')}`,
        target: id,
        kind: 'crossover_second_parent',
      });
    }
  }

  return { nodes, edges };
}
