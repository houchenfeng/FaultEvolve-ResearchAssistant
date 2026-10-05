/**
 * 进化树画布（TODO 5.1 / PRD §10.2）。
 *
 * 这个组件只做四件事：把数据交给纯函数、把纯函数的结果交给 React Flow、
 * 把用户操作回调给上层、把概念图那套"代数分带 + 图例"画出来。
 * 它**不含任何判定逻辑** —— 显著性、噪声带、折叠、路径高亮全部在
 * `tree-adapter.ts` / `tree-interactions.ts` 里，那样才能在没有 DOM 的环境里测试。
 *
 * 视觉方向来自 `docs/images/frontend-concepts/02-evolution-workbench.png`：
 * 每一代有一条浅色竖带（标题「第 N 代 (n)」）、节点是紧凑竖排小卡、
 * 最佳路径是**静态绿色实线**（不是位移动画 —— 概念图里没有动画，
 * 而且动画会让"哪条是最优路径"变成一件要靠等待才能看清的事）。
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Background,
  Controls,
  MiniMap,
  ReactFlow,
  ReactFlowProvider,
  ViewportPortal,
  useReactFlow,
  type Edge,
  type Node,
  type NodeMouseHandler,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';

import type { TreeNodeDto } from '@/generated/api';
import {
  TreeEdgeLegend,
  TreeNodeCard,
  TreeSignificanceLegend,
} from '@/features/workbench/TreeNodeCard';
import { TreeFilters } from '@/features/workbench/TreeFilters';
import {
  EMPTY_TREE_FILTER,
  filterTree,
  layoutTree,
  rankBands,
  TREE_NODE_HEIGHT,
  TREE_NODE_WIDTH,
  type TreeEdgeInput,
  type TreeFilter,
} from '@/features/workbench/tree-adapter';
import {
  collapsibleIds,
  defaultCollapsedIds,
  descendantsOf,
  edgesWithin,
  relatedNodeIds,
  toggleCollapse,
  visibleNodeIds,
  type CollapseSet,
} from '@/features/workbench/tree-interactions';
const nodeTypes = { treeNode: TreeNodeCard };

export interface TreeCanvasProps {
  nodes: TreeNodeDto[];
  edges: TreeEdgeInput[];
  bestPath: string[];
  filter?: TreeFilter;
  selectedNodeId: string | null;
  /** 双亲高亮：非空时高亮这些节点构成的路径。 */
  highlightNodeId?: string | null;
  onSelect: (nodeId: string | null) => void;
  onFilterChange?: (filter: TreeFilter) => void;
  /** 大树时（PRD 10.5）默认折叠低价值子树。 */
  autoCollapse?: boolean;
  onVisibleCountChange?: (visible: number, hiddenByFilter: number, collapsed: number) => void;
}

function TreeCanvasInner({
  nodes,
  edges,
  bestPath,
  filter = EMPTY_TREE_FILTER,
  selectedNodeId,
  highlightNodeId = null,
  onSelect,
  onFilterChange,
  autoCollapse = false,
  onVisibleCountChange,
}: TreeCanvasProps) {
  const { fitView, setCenter } = useReactFlow();
  const [collapsed, setCollapsed] = useState<CollapseSet>(
    () => (autoCollapse ? defaultCollapsedIds(nodes, edges) : new Set<string>()),
  );
  /** 代数分带默认开；节点太密时用户可能想关掉看纯连线。 */
  const [showBands, setShowBands] = useState(true);
  const containerRef = useRef<HTMLDivElement | null>(null);

  // 运行切换时（换 runId）重置折叠状态，否则上一棵树的折叠集会套到新树上。
  const runKey = nodes[0]?.id ?? 'empty';
  const lastRunKey = useRef(runKey);
  useEffect(() => {
    if (lastRunKey.current !== runKey) {
      lastRunKey.current = runKey;
      setCollapsed(autoCollapse ? defaultCollapsedIds(nodes, edges) : new Set<string>());
    }
  }, [runKey, nodes, edges, autoCollapse]);

  // 筛选：先按过滤条件筛，再按折叠隐藏。两者的区别要对用户可见。
  //
  // 末位 `false` = 这一步**不**要坐标：下面还要按折叠裁掉一批节点，裁完
  // `layoutTree` 会重排一次，现在算的坐标必然作废（dagre 是整图排布）。
  // 500 节点实测：算两次 1.6 s，算一次 0.4 s —— 这是首帧最大的一笔开销。
  const filtered = useMemo(() => filterTree(nodes, edges, filter, bestPath, false), [
    nodes,
    edges,
    filter,
    bestPath,
  ]);
  const visibleIds = useMemo(
    () => visibleNodeIds([...filtered.nodes.map((n) => n.id)], edges, collapsed),
    [filtered.nodes, edges, collapsed],
  );
  const collapsible = useMemo(() => collapsibleIds(edges), [edges]);

  const graph = useMemo(() => {
    const keptNodes = filtered.nodes.filter((n) => visibleIds.has(n.id));
    const keptIds = new Set(keptNodes.map((n) => n.id));
    const keptEdges = filtered.edges.filter(
      (edge) => keptIds.has(edge.source) && keptIds.has(edge.target),
    );
    return { nodes: keptNodes, edges: keptEdges };
  }, [filtered, visibleIds]);

  // 折叠计数：某个折叠节点藏了多少后代（角标要显示这个数）。
  const hiddenDescendants = useMemo(() => {
    const counts = new Map<string, number>();
    for (const id of collapsed) {
      counts.set(id, descendantsOf(id, edges).size - 1);
    }
    return counts;
  }, [collapsed, edges]);

  const handleToggleCollapse = useCallback(
    (nodeId: string) => setCollapsed((prev: CollapseSet) => toggleCollapse(prev, nodeId)),
    [],
  );

  // 双亲高亮：把选中节点的所有祖先标出来，相关节点与边加粗。
  const highlight = useMemo(() => {
    if (!highlightNodeId) return null;
    const ids = relatedNodeIds(highlightNodeId, edges);
    const edgeKeys = new Set(edgesWithin(ids, edges).map((e) => `${e.source}->${e.target}`));
    return { ids, edgeKeys };
  }, [highlightNodeId, edges]);

  const flowNodes = useMemo(() => {
    const bestSet = new Set(bestPath);
    return layoutTree(
      graph.nodes.map((n) => ({
        ...n,
        selected: n.id === selectedNodeId,
        data: {
          ...n.data,
          isOnBestPath: bestSet.has(n.id),
          hiddenCount: hiddenDescendants.get(n.id) ?? 0,
          collapsible: collapsible.has(n.id),
          collapsed: collapsed.has(n.id),
          onToggleCollapse: handleToggleCollapse,
        },
      })),
      graph.edges,
    );
  }, [
    graph,
    selectedNodeId,
    bestPath,
    hiddenDescendants,
    collapsible,
    collapsed,
    handleToggleCollapse,
  ]);

  /**
   * 代数分带。必须在 `layoutTree` **之后**算 —— 分带的包围盒来自节点坐标，
   * 未布局时所有节点都在 (0,0)，会算出一条叠在原点的带子。
   */
  const bands = useMemo(() => (showBands ? rankBands(flowNodes) : []), [flowNodes, showBands]);

  const flowEdges = useMemo(() => {
    const bestSet = new Set(bestPath);
    return graph.edges.map((edge) => {
      const isBestPath = bestSet.has(edge.source) && bestSet.has(edge.target);
      const isHighlight = highlight?.edgeKeys.has(`${edge.source}->${edge.target}`) ?? false;
      // 最优路径改成**绿色实线**：概念图是这样，而且"路径"与"边类型"是两个维度 ——
      // 绿色只表示"这条边在最优路径上"，线型（实/虚）仍然表示边的关系种类。
      return {
        ...edge,
        style: {
          ...edge.style,
          ...(isBestPath ? { stroke: 'var(--color-success-500)' } : {}),
          strokeWidth: isHighlight ? 3 : isBestPath ? 2.5 : 1.5,
          opacity: highlight && !isHighlight ? 0.25 : 1,
        },
      };
    });
  }, [graph.edges, bestPath, highlight]);

  useEffect(() => {
    onVisibleCountChange?.(
      graph.nodes.length,
      filtered.hiddenCount,
      nodes.length - visibleIds.size - filtered.hiddenCount,
    );
  }, [graph.nodes.length, filtered.hiddenCount, nodes.length, visibleIds.size, onVisibleCountChange]);

  const handleNodeClick = useCallback<NodeMouseHandler>(
    (_event, node) => {
      onSelect(node.id);
    },
    [onSelect],
  );

  // 从时间轴/排行榜跳过来时把节点移到视野中央。
  useEffect(() => {
    if (!selectedNodeId) return;
    const target = flowNodes.find((n) => n.id === selectedNodeId);
    if (!target) return;
    setCenter(
      target.position.x + TREE_NODE_WIDTH / 2,
      target.position.y + TREE_NODE_HEIGHT / 2,
      { zoom: 1, duration: 240 },
    );
  }, [selectedNodeId, flowNodes, setCenter]);

  const handleFitView = useCallback(() => fitView({ padding: 0.15, duration: 200 }), [fitView]);

  const hiddenByFilter = filtered.hiddenCount;
  const hiddenByCollapse = nodes.length - visibleIds.size - filtered.hiddenCount;

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {onFilterChange ? (
        <TreeFilters
          filter={filter}
          onChange={onFilterChange}
          nodes={nodes}
          collapsedCount={hiddenByCollapse}
        />
      ) : null}

      {/*
         图例条放在画布**上方**（概念图的位置）：线型图例 + 显著性图例在左，
         计数与操作在右。图例紧挨着它解释的东西，比塞在页面底部好读。
      */}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 border-b border-border-subtle bg-surface px-3 py-1.5">
        <TreeEdgeLegend />
        <span className="h-3.5 w-px bg-border-subtle" aria-hidden />
        <TreeSignificanceLegend />
        <span className="flex-1" />
        <span className="text-[11px] text-fg-muted">
          显示 {graph.nodes.length} / {nodes.length} 个节点
          {hiddenByFilter > 0 ? `（筛选隐藏 ${hiddenByFilter}）` : ''}
          {hiddenByCollapse > 0 ? `（折叠隐藏 ${hiddenByCollapse}）` : ''}
        </span>
        <button
          type="button"
          onClick={() => setShowBands((value) => !value)}
          aria-pressed={showBands}
          title="按代数画出竖向分带，便于看清演化到了第几代"
          className={`rounded-card border px-2 py-0.5 text-[11px] ${
            showBands
              ? 'border-brand-500 text-brand-600 dark:text-brand-300'
              : 'border-border-subtle text-fg-muted hover:border-border-strong'
          }`}
        >
          代数分带
        </button>
        <button
          type="button"
          onClick={handleFitView}
          className="rounded-card border border-border-subtle px-2 py-0.5 text-[11px] text-fg-muted hover:border-brand-500 hover:text-brand-600"
        >
          适配视野
        </button>
      </div>

      {/*
         ReactFlow 要求容器有确定的宽高，否则整张图不渲染。
         `flex-1` 只有在**祖先链上有确定高度**时才能分到高度；`RunLayout`
         的根容器是 auto 高度，这条链断掉了，实测容器高度塌成 0、画布全空。
         用 `min-h-[520px]` 兜底：有确定高度时 `flex-1` 照常撑满，
         塌陷时也保证画布可见。改布局层时请连同这条一起复核。
      */}
      <div
        ref={containerRef}
        className="min-h-[520px] flex-1"
        data-testid="tree-canvas"
      >
        <ReactFlow
          nodes={flowNodes as Node[]}
          edges={flowEdges as Edge[]}
          nodeTypes={nodeTypes}
          onNodeClick={handleNodeClick}
          onPaneClick={() => onSelect(null)}
          nodesDraggable={false}
          nodesConnectable={false}
          elementsSelectable
          onlyRenderVisibleElements
          // 打开就把整棵树纳入视野。不设的话默认视口是 (0,0) / zoom 1，
          // 六节点的 demo 刚好塞得下，但稍大一点的树就只能看到左上角一隅 ——
          // 配合 `onlyRenderVisibleElements`（视口外的节点压根不进 DOM），
          // 表现出来就是"树怎么只有几个节点"。这一条和上一行是绑在一起的：
          // 关掉虚拟化就不会暴露，打开虚拟化就必须 fit。
          fitView
          fitViewOptions={{ padding: 0.15 }}
          minZoom={0.1}
          maxZoom={2}
          proOptions={{ hideAttribution: true }}
        >
          {/*
            分带必须画在节点**下面**。`ViewportPortal` 的容器在 viewport 里
            是最后一个子元素（实测：边 → 连线 → 边标签 → 节点 → portal），
            所以 DOM 顺序天然在上 —— 只能用负 z-index 压回去。
            负值会落到同一个 viewport 叠层里（viewport 有 transform，
            自己就是一个层叠上下文），不会跑到画布底色后面去。
          */}
          <ViewportPortal>
            {bands.map((band) => (
              <div
                key={band.depth}
                aria-hidden
                data-testid={`tree-band-${band.depth}`}
                style={{
                  position: 'absolute',
                  transform: `translate(${band.x}px, ${band.y}px)`,
                  width: band.width,
                  height: band.height,
                  zIndex: -1,
                  pointerEvents: 'none',
                }}
                className="rounded-panel bg-surface"
              >
                <span className="absolute left-2.5 top-2 text-[11px] text-fg-subtle">
                  {band.label}（{band.count}）
                </span>
              </div>
            ))}
          </ViewportPortal>
          <Background gap={24} size={1} color="var(--color-border-subtle)" className="!bg-surface-muted" />
          <Controls showInteractive={false} />
          {/*
             MiniMap 是压在画布右下角的一张不透明面板，会实打实盖住那一角的
            节点（实测 200×150、z-index 5）。缩到 140×96 并降不透明度，
            让它"能看但挡不住"。位置保持默认右下，不与左下角的缩放控件打架。
          */}
          <MiniMap
            pannable
            zoomable
            className="!bg-surface/80 !border-border-subtle"
            style={{ width: 140, height: 96 }}
          />
        </ReactFlow>
      </div>
    </div>
  );
}

export function TreeCanvas(props: TreeCanvasProps) {
  return (
    <ReactFlowProvider>
      <TreeCanvasInner {...props} />
    </ReactFlowProvider>
  );
}
