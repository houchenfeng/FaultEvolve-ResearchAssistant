/**
 * 进化工作台总览（`/runs/$runId`，TODO 5.5 / 5.7 / PRD §9.1–9.9 + 阶段 7）。
 *
 * 三块内容：闭环汇总（评估/改进/噪声/修复）、树（内嵌）、预算与算力。
 * 树在这里也显示，因为 PRD §9.2 的"评估—反思—纠错闭环"离开树就没法讲。
 *
 * ## 为什么"制品还没产生"不是 `ApiErrorPanel`
 *
 * 阶段 7 之后，这个页面**刚刚被自己创建出来**的运行是常态：点了「启动运行」
 * → 跳到这里 → 此时运行目录里只有 `evolve.effective.yaml` 和 `logs/`，还没有
 * `fe.db` / `tree.json`。回放层会如实报 `run.unreadable`（"既没有可读的
 * run_summary.json，也没有 fe.db"）——**那不是错误，是还没到时候**。
 *
 * 所以这个页面在制品读不出来时要说三件事，而不是把整页换成错误：
 * 1. 进程还在不在（`/live`，并给出控制条，让用户能取消/恢复/追加）；
 * 2. 进程在跑就按 3 秒重试，制品一落盘自动出现；
 * 3. 进程已经退出就报退出码，并指出"失败原因在控制条展开的运行日志末尾里"。
 *
 * "这个运行根本不是本服务启动的"由上层 `RunLayout` 拦住（它先问注册表），
 * 所以这里不需要再判一次 registered。
 */
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useParams } from '@tanstack/react-router';
import { useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';

import { StatusBadge } from '@/components/ui/StatusBadge';
import { HddCaseOverview } from '@/features/showcase/HddCaseOverview';
import { SHOWCASE_RUN_ID } from '@/features/showcase/hdd-showcase-data';
import {
  getEventsApiRunsRunIdEventsGet,
  getRunApiRunsRunIdGet,
  getTreeApiRunsRunIdTreeGet,
} from '@/generated/api';
import { BudgetPanel } from '@/features/workbench/BudgetPanel';
import { EventStream } from '@/features/workbench/EventStream';
import { RunControls } from '@/features/workbench/RunControls';
import { TreeCanvas } from '@/features/workbench/TreeCanvas';
import { dedupeEvents } from '@/features/workbench/iteration-logic';
import { summarizeLoop } from '@/features/workbench/reflection';
import { EMPTY_TREE_FILTER, type TreeFilter } from '@/features/workbench/tree-adapter';
import { useEventStream } from '@/features/workbench/use-event-stream';
import { useRunLive } from '@/features/workbench/use-run-live';
import { toApiError, unwrap } from '@/lib/api';
import { queryKeys, runScopedKeys } from '@/lib/query-keys';
import { useUiStore } from '@/stores/ui-store';

type Panel = 'tree' | 'loop' | 'budget';

/** 制品每 3 秒重试的间隔。只在进程还活着时用。 */
const ARTIFACT_POLL_MS = 3_000;

export function RunWorkbenchPage() {
  const { runId } = useParams({ from: '/runs/$runId' });
  const queryClient = useQueryClient();
  const selectedNodeId = useUiStore((state) => state.selectedNodeId);
  const setSelectedNodeId = useUiStore((state) => state.setSelectedNodeId);
  const [filter, setFilter] = useState<TreeFilter>(EMPTY_TREE_FILTER);
  const [panel, setPanel] = useState<Panel>('tree');

  // 进程态先取：它决定制品查询要不要轮询，也决定"读不到制品"该说成什么。
  // 轮询由控制条拥有（同一 queryKey 只该有一个 interval），这里只读缓存。
  const liveQuery = useRunLive(runId, { poll: false });
  const live = liveQuery.data;
  const status = live?.status ?? null;
  const running = status === 'running';

  const artifactsPoll = running ? ARTIFACT_POLL_MS : false;

  const runQuery = useQuery({
    queryKey: queryKeys.run(runId),
    queryFn: () => unwrap(getRunApiRunsRunIdGet({ path: { run_id: runId } })),
    retry: false,
    refetchInterval: artifactsPoll,
  });

  const treeQuery = useQuery({
    queryKey: queryKeys.tree(runId),
    queryFn: () => unwrap(getTreeApiRunsRunIdTreeGet({ path: { run_id: runId } })),
    retry: false,
    refetchInterval: artifactsPoll,
  });

  const eventsQuery = useQuery({
    queryKey: queryKeys.events(runId, null, 500),
    queryFn: () =>
      unwrap(getEventsApiRunsRunIdEventsGet({ path: { run_id: runId }, query: { limit: 500 } })),
    retry: false,
    refetchInterval: artifactsPoll,
  });

  /*
   * 阶段 8：实时事件走 SSE，`eventsQuery` 只做首屏快照与降级底座。
   *
   * 两条数据源要合并而不是二选一：SSE 只发**新**事件（游标之后），首屏那
   * 几百条历史事件仍来自 REST。`dedupeEvents` 按 id 去重，所以重叠部分不会
   * 变成两条。运行在跑时优先用流里的，运行结束（`snapshotReady`）后一律用
   * REST 的——那时制品才是权威，而 `snapshot_ready` 已经让缓存全部失效。
   */
  const stream = useEventStream({ runId, enabled: true });
  const events = useMemo(() => {
    // 降级轮询期间 / 快照就绪后，REST 才是权威来源，丢掉流里的增量。
    const liveEvents =
      stream.status === 'polling' || stream.snapshotReady ? [] : stream.events;
    const merged = dedupeEvents([...(eventsQuery.data?.events ?? []), ...liveEvents]);
    // 实时流可能已经跑到 REST 快照前面去了；倒序渲染时按 id 排才不会出现
    // "时间倒流"。
    return merged.sort((a, b) => (b.id ?? 0) - (a.id ?? 0));
  }, [eventsQuery.data?.events, stream.events, stream.snapshotReady, stream.status]);

  // 进程从"进行中"变成终态的那一刻，制品才是可信的：停轮询前补拉一次，
  // 否则最后一次轮询可能正好落在 run_summary.json 落盘之前，页面就停在
  // "还没制品"上不动了。
  const previousStatus = useRef<string | null>(null);
  useEffect(() => {
    const was = previousStatus.current;
    previousStatus.current = status;
    if (was !== 'running' || status === null || status === 'running') return;
    for (const key of runScopedKeys(runId)) {
      void queryClient.invalidateQueries({ queryKey: key });
    }
  }, [status, queryClient, runId]);

  if (runId === SHOWCASE_RUN_ID) return <HddCaseOverview />;

  // 用联合类型自己的判别式（isPending/isError）来判断，别把它们合成一个
  // 布尔量：合成之后 TS 就收窄不出 `data` 已定义了。
  if (runQuery.isPending || treeQuery.isPending || runQuery.isError || treeQuery.isError) {
    const failed = runQuery.error ?? treeQuery.error;
    const error = failed !== null && failed !== undefined ? toApiError(failed) : null;
    return (
      <div className="flex min-h-0 flex-1 flex-col">
        {/*
          没有制品时不给三个面板切换按钮：它们切过去也没有东西可看，
          摆了只会让人以为"是不是我点错了标签"。
        */}
        <WorkbenchHeader
          live={live}
          dataState={null}
          loopLine={null}
          panel={panel}
          onPanelChange={setPanel}
          showPanels={false}
        />
        <div className="shrink-0 px-3 pt-2">
          <RunControls runId={runId} />
        </div>
        <div
          className="min-h-0 flex-1 overflow-y-auto bg-surface px-4 py-6"
          data-artifacts-pending="true"
        >
          <p className="text-xs font-medium text-fg">
            {running || error === null
              ? '引擎正在运行，制品尚未产生。'
              : '这次运行没有产出可回放的制品。'}
          </p>
          <p className="mt-1 text-[11px] text-fg-muted">
            {running || error === null
              ? `运行目录里还没有 fe.db / tree.json；每 ${ARTIFACT_POLL_MS / 1000} 秒自动重试，产生后会自动出现。`
              : `进程已退出（${
                  live?.exit_code !== null && live?.exit_code !== undefined
                    ? `退出码 ${live.exit_code}`
                    : '退出码未知'
                }），既没有 run_summary.json，也没有 fe.db。失败原因通常在运行日志末尾 —— 展开上方控制条里的「运行日志末尾」。`}
          </p>
          {error !== null ? (
            <p className="mt-2 text-[11px] text-fg-subtle">
              回放层的原因：{error.message}（{error.errorCode}）
            </p>
          ) : null}
          <button
            type="button"
            onClick={() => void runQuery.refetch()}
            className="mt-3 fe-btn fe-btn-secondary fe-btn-sm px-2.5 py-1"
          >
            重新读取
          </button>
        </div>
      </div>
    );
  }

  const run = runQuery.data;
  const tree = treeQuery.data;
  const loop = summarizeLoop(tree.nodes, events);

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <WorkbenchHeader
        live={live}
        dataState={run.data_state}
        loopLine={
          <>
            闭环：已评估 {loop.evaluatedCount} · 有效改进 {loop.improvedCount} · 噪声内{' '}
            {loop.noiseCount}
            {loop.unknownCount > 0 ? ` · 无法判断 ${loop.unknownCount}` : ''} · 修复{' '}
            {loop.repairCount}（成功 {loop.repairSucceeded}）· 反思 {loop.reflectionLayersPresent}/3
          </>
        }
        panel={panel}
        onPanelChange={setPanel}
      />

      {/* 控制条常驻：进程态可以随时变化，藏进标签页会让"运行还在跑吗"看不出来。 */}
      <div className="shrink-0 px-3 pt-2">
        <RunControls runId={runId} />
      </div>

      {panel === 'tree' ? (
        <TreeCanvas
          nodes={tree.nodes}
          edges={tree.edges}
          bestPath={tree.best_path ?? []}
          filter={filter}
          onFilterChange={setFilter}
          selectedNodeId={selectedNodeId}
          onSelect={setSelectedNodeId}
          autoCollapse={tree.nodes.length > 50}
        />
      ) : null}

      {panel === 'loop' ? (
        <EventStream events={events} onLocateNode={setSelectedNodeId} highlightNodeId={selectedNodeId} />
      ) : null}

      {panel === 'budget' ? (
        <div className="min-h-0 flex-1 overflow-y-auto bg-surface">
          {run.budget ? (
            <BudgetPanel budget={run.budget} />
          ) : (
            <div className="px-3 py-4 text-[11px] text-fg-subtle">
              该运行没有预算制品（可能是 demo 数据或运行未记账）。
            </div>
          )}
        </div>
      ) : null}
    </div>
  );
}

/** 顶部条：运行名、进程态徽章、数据状态、闭环摘要、三块面板的切换。 */
function WorkbenchHeader({
  live,
  dataState,
  loopLine,
  panel,
  onPanelChange,
  showPanels = true,
}: {
  live: { status?: string | null; detail?: string } | undefined;
  dataState: string | null;
  loopLine: ReactNode;
  panel: Panel;
  onPanelChange: (panel: Panel) => void;
  showPanels?: boolean;
}) {
  const status = live?.status ?? null;
  return (
    <header className="flex flex-wrap items-center gap-2 border-b border-border-subtle bg-surface px-3 py-2">
      <h1 className="text-[13px] font-medium text-fg">进化工作台</h1>
      {status !== null ? (
        <StatusBadge
          tone={
            status === 'running'
              ? 'info'
              : status === 'completed'
                ? 'success'
                : status === 'failed'
                  ? 'danger'
                  : status === 'interrupted'
                    ? 'warning'
                    : 'neutral'
          }
          title={live?.detail}
        >
          {status}
        </StatusBadge>
      ) : null}
      {dataState !== null ? (
        <StatusBadge tone={dataState === 'complete' ? 'success' : 'info'}>{dataState}</StatusBadge>
      ) : null}
      {loopLine !== null ? <span className="text-[11px] text-fg-muted">{loopLine}</span> : null}
      <span className="flex-1" />
      {showPanels
        ? (['tree', 'loop', 'budget'] as const).map((item) => (
            <button
              key={item}
              type="button"
              onClick={() => onPanelChange(item)}
              aria-current={panel === item}
              className={`rounded-card px-2 py-0.5 text-[11px] ${
                panel === item
                  ? 'bg-brand-50 text-brand-600 dark:bg-brand-500/10 dark:text-brand-300'
                  : 'text-fg-muted hover:text-fg'
              }`}
            >
              {item === 'tree' ? '进化树' : item === 'loop' ? '事件流' : '预算与算力'}
            </button>
          ))
        : null}
    </header>
  );
}
