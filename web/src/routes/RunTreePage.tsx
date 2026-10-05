/**
 * 进化树页（`/runs/$runId/tree`，TODO 5.1–5.5）。
 *
 * 页面只做数据获取与状态接线，所有判定都在纯函数层。
 * 布局：左侧筛选 + 画布，右侧选中节点的详情抽屉。
 */
import { useQuery } from '@tanstack/react-query';
import { useParams } from '@tanstack/react-router';
import { useMemo, useState } from 'react';

import { ApiErrorPanel } from '@/components/states/ApiErrorPanel';
import { EmptyState } from '@/components/states/EmptyState';
import {
  getEventsApiRunsRunIdEventsGet,
  getNodeApiRunsRunIdNodesNodeIdGet,
  getTreeApiRunsRunIdTreeGet,
} from '@/generated/api';
import { NodeDrawer } from '@/features/workbench/NodeDrawer';
import { TreeCanvas } from '@/features/workbench/TreeCanvas';
import { EMPTY_TREE_FILTER, type TreeFilter } from '@/features/workbench/tree-adapter';
import { toApiError, unwrap } from '@/lib/api';
import { queryKeys } from '@/lib/query-keys';
import { useUiStore } from '@/stores/ui-store';
import { HddEvolutionShowcase } from '@/features/showcase/HddEvolutionShowcase';
import { SHOWCASE_RUN_ID } from '@/features/showcase/hdd-showcase-data';

export function RunTreePage() {
  const { runId } = useParams({ from: '/runs/$runId/tree' });
  const selectedNodeId = useUiStore((state) => state.selectedNodeId);
  const setSelectedNodeId = useUiStore((state) => state.setSelectedNodeId);
  const [filter, setFilter] = useState<TreeFilter>(EMPTY_TREE_FILTER);

  const treeQuery = useQuery({
    queryKey: queryKeys.tree(runId),
    queryFn: () => unwrap(getTreeApiRunsRunIdTreeGet({ path: { run_id: runId } })),
    retry: false,
  });

  // 节点索引交给抽屉用：修复记账（次数 / 是否耗尽）引擎写在**被修的那一侧**，
  // 抽屉只看当前节点读不到，得能顺着 repair_parent_id 反查回去。
  // 依赖取 treeQuery.data?.nodes 本身（react-query 缓存里引用稳定），
  // 不取 `?? []` 的结果 —— 那样每次渲染都是新数组，memo 白算。
  const treeNodes = treeQuery.data?.nodes;
  const nodeById = useMemo(
    () => new Map((treeNodes ?? []).map((item) => [item.id, item])),
    [treeNodes],
  );

  const eventsQuery = useQuery({
    queryKey: queryKeys.events(runId, null, 500),
    queryFn: () =>
      unwrap(getEventsApiRunsRunIdEventsGet({ path: { run_id: runId }, query: { limit: 500 } })),
    retry: false,
  });

  const detailQuery = useQuery({
    queryKey: queryKeys.node(runId, selectedNodeId ?? ''),
    queryFn: () =>
      unwrap(
        getNodeApiRunsRunIdNodesNodeIdGet({
          path: { run_id: runId, node_id: selectedNodeId ?? '' },
        }),
      ),
    enabled: Boolean(selectedNodeId),
    retry: false,
  });

  if (runId === SHOWCASE_RUN_ID) {
    return <HddEvolutionShowcase />;
  }

  if (treeQuery.isPending) {
    return <div className="px-4 py-10 text-center text-xs text-fg-subtle">正在读取进化树…</div>;
  }

  if (treeQuery.isError) {
    return (
      <ApiErrorPanel error={toApiError(treeQuery.error)} onRetry={() => void treeQuery.refetch()} />
    );
  }

  const tree = treeQuery.data;

  if (tree.nodes.length === 0) {
    return (
      <div className="px-4 py-8">
        <EmptyState
          title="这次运行没有进化树"
          reason="产物目录里没有节点记录，可能是运行刚创建还没有产出节点，或 tree.json 缺失。"
          nextStep="到「工作台总览」确认该运行的数据状态（data_state）。"
        />
      </div>
    );
  }

  return (
    <div className="flex min-h-0 flex-1">
      <TreeCanvas
        nodes={tree.nodes}
        edges={tree.edges}
        bestPath={tree.best_path ?? []}
        filter={filter}
        onFilterChange={setFilter}
        selectedNodeId={selectedNodeId}
        onSelect={setSelectedNodeId}
        // 大树默认折叠低价值子树（PRD 10.5）；小树不折，否则用户会以为节点凭空消失。
        autoCollapse={tree.nodes.length > 50}
      />
      {selectedNodeId && detailQuery.data ? (
        <NodeDrawer
          detail={detailQuery.data}
          events={eventsQuery.data?.events ?? []}
          nodeById={nodeById}
          onClose={() => setSelectedNodeId(null)}
          onNavigate={setSelectedNodeId}
        />
      ) : null}
    </div>
  );
}
