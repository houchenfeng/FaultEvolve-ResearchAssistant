/**
 * 结果与报告页的数据装配（PRD 13.1–13.5 / TODO 6.4）。
 *
 * 从路由组件里拆出来有两个原因：
 * 1. 六个查询的降级关系是这一页最容易写错的地方，集中在一处才好看清；
 * 2. 路由组件因此只剩渲染，测试既可以打整页，也可以直接对这个 hook 断言。
 *
 * 贯穿全文件的一条纪律：**请求失败 ≠ 数据为零**。凡是拿不到就传 `undefined`
 * 给下游，由 results-logic 转成「未记录」，不在这里用 `?? []` 兜底——
 * 兜底会把一次网络故障画成「这个运行没有候选 / 没有制品」。
 */
import { useQuery } from '@tanstack/react-query';
import { useParams } from '@tanstack/react-router';

import type { MetricsState } from '@/features/results/results-logic';
import { DEFAULT_TOP_K, bestNodeIdOf, topKRows } from '@/features/results/results-logic';
import {
  getLeaderboardApiRunsRunIdLeaderboardGet,
  getNodeApiRunsRunIdNodesNodeIdGet,
  getReportManifestApiRunsRunIdReportsManifestGet,
  getRunApiRunsRunIdGet,
  getTreeApiRunsRunIdTreeGet,
  listArtifactsApiRunsRunIdArtifactsGet,
} from '@/generated/api';
import { unwrap } from '@/lib/api';
import { queryKeys } from '@/lib/query-keys';

export function useResultsData() {
  const { runId } = useParams({ from: '/runs/$runId/results' });

  // RunLayout 已经用同一个 key 取过运行详情并拦住了失败，这里只是复用缓存。
  const detailQuery = useQuery({
    queryKey: queryKeys.run(runId),
    queryFn: () => unwrap(getRunApiRunsRunIdGet({ path: { run_id: runId } })),
    retry: false,
  });

  const leaderboardQuery = useQuery({
    queryKey: queryKeys.leaderboard(runId),
    queryFn: () => unwrap(getLeaderboardApiRunsRunIdLeaderboardGet({ path: { run_id: runId } })),
    retry: false,
  });

  const treeQuery = useQuery({
    queryKey: queryKeys.tree(runId),
    queryFn: () => unwrap(getTreeApiRunsRunIdTreeGet({ path: { run_id: runId } })),
    retry: false,
  });

  const artifactsQuery = useQuery({
    queryKey: queryKeys.artifacts(runId),
    queryFn: () => unwrap(listArtifactsApiRunsRunIdArtifactsGet({ path: { run_id: runId } })),
    retry: false,
  });

  const reportQuery = useQuery({
    queryKey: queryKeys.reportManifest(runId),
    queryFn: () =>
      unwrap(getReportManifestApiRunsRunIdReportsManifestGet({ path: { run_id: runId } })),
    retry: false,
  });

  const bestNodeId = bestNodeIdOf(detailQuery.data, treeQuery.data);

  // 没有最佳节点就不发这个请求：拿 '' 去问后端只会得到一个 404，
  // 那会被画成「节点详情读取失败」，而真相是「根本没有节点可问」。
  const nodeQuery = useQuery({
    queryKey: queryKeys.node(runId, bestNodeId ?? ''),
    queryFn: () =>
      unwrap(
        getNodeApiRunsRunIdNodesNodeIdGet({
          path: { run_id: runId, node_id: bestNodeId as string },
        }),
      ),
    enabled: bestNodeId != null,
    retry: false,
  });

  const metricsState: MetricsState =
    bestNodeId == null
      ? 'skipped'
      : nodeQuery.isPending
        ? 'pending'
        : nodeQuery.isError
          ? 'error'
          : 'ready';

  const metricsSkipReason = treeQuery.isError
    ? '运行摘要没有给出最佳节点，而进化树又读取失败，所以无从确认这次运行是否真的没有最佳节点。'
    : '这次运行没有最佳节点：run_summary.json 与 tree.json 都没有给出 best_node_id。';

  /**
   * 判定用的节点优先取进化树里的那一个——全树计数也出自同一份制品，
   * 两处必须指同一个对象。树读不到时退回节点详情（`NodeDetailResponse.node`
   * 同样是 `TreeNodeDto`）；两边都没有就是 null，`noiseVerdict` 会说「无法判断」。
   */
  const bestNode =
    treeQuery.data?.nodes.find((node) => node.id === bestNodeId) ??
    nodeQuery.data?.node ??
    null;

  return {
    runId,
    detailQuery,
    leaderboardQuery,
    treeQuery,
    artifactsQuery,
    reportQuery,
    nodeQuery,
    bestNodeId,
    bestNode,
    treeWarnings: treeQuery.data?.warnings ?? [],
    metricsState,
    metricsSkipReason,
    topK: topKRows(leaderboardQuery.data, artifactsQuery.data?.artifacts, DEFAULT_TOP_K),
    leaderboardTotal: leaderboardQuery.data?.length ?? null,
    artifacts: artifactsQuery.data?.artifacts,
    report: reportQuery.data ?? null,
    metric: nodeQuery.data?.evaluation?.metric,
  };
}
