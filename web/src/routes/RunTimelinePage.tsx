/**
 * 代际时间轴页（`/runs/$runId/timeline`，TODO 5.6 / PRD §11.1–11.2）。
 *
 * 三块：分数曲线、代际事件流、排行榜。点事件或排行条目都能定位到树节点
 * （定位动作写进 UI store，树页会跟着高亮）。
 */
import { useQuery } from '@tanstack/react-query';
import { useNavigate, useParams } from '@tanstack/react-router';
import { useState } from 'react';

import { ApiErrorPanel } from '@/components/states/ApiErrorPanel';
import {
  getEventsApiRunsRunIdEventsGet,
  getLeaderboardApiRunsRunIdLeaderboardGet,
  getRunApiRunsRunIdGet,
  getScoresApiRunsRunIdScoresGet,
} from '@/generated/api';
import { timelineGaps } from '@/features/workbench/timeline-gap';
import { EventStream } from '@/features/workbench/EventStream';
import { LeaderboardPanel } from '@/features/workbench/LeaderboardPanel';
import { ScoreTimeline } from '@/features/workbench/ScoreTimeline';
import { toApiError, unwrap } from '@/lib/api';
import { queryKeys } from '@/lib/query-keys';
import { useUiStore } from '@/stores/ui-store';

const TABS = [
  { id: 'timeline', label: '时间轴与事件' },
  { id: 'leaderboard', label: '排行榜' },
] as const;

type TabId = (typeof TABS)[number]['id'];

export function RunTimelinePage() {
  const { runId } = useParams({ from: '/runs/$runId/timeline' });
  const navigate = useNavigate();
  const setSelectedNodeId = useUiStore((state) => state.setSelectedNodeId);
  const selectedNodeId = useUiStore((state) => state.selectedNodeId);
  // 标签页状态放在 URL 之外：刷新回到默认标签，PRD 没要求深链接到标签。
  const [tab, setTab] = useState<TabId>('timeline');

  const runQuery = useQuery({
    queryKey: queryKeys.run(runId),
    queryFn: () => unwrap(getRunApiRunsRunIdGet({ path: { run_id: runId } })),
    retry: false,
  });

  const eventsQuery = useQuery({
    queryKey: queryKeys.events(runId, null, 1000),
    queryFn: () =>
      unwrap(getEventsApiRunsRunIdEventsGet({ path: { run_id: runId }, query: { limit: 1000 } })),
    retry: false,
  });

  const scoresQuery = useQuery({
    queryKey: queryKeys.scores(runId),
    queryFn: () => unwrap(getScoresApiRunsRunIdScoresGet({ path: { run_id: runId } })),
    retry: false,
  });

  const leaderboardQuery = useQuery({
    queryKey: queryKeys.leaderboard(runId),
    queryFn: () => unwrap(getLeaderboardApiRunsRunIdLeaderboardGet({ path: { run_id: runId } })),
    retry: false,
  });

  // 定位 = 记住选中节点 + 跳到树页。树页会把它移到视野中央。
  const outcome = runQuery.data?.outcome;
  const gaps = timelineGaps({
    iterationsDone: outcome?.iterations_done,
    iterationEvents: outcome?.iteration_events,
    warnings: eventsQuery.data?.warnings,
  });

  const locate = (nodeId: string) => {
    setSelectedNodeId(nodeId);
    void navigate({ to: '/runs/$runId/tree', params: { runId } });
  };

  if (eventsQuery.isError) {
    return (
      <ApiErrorPanel
        error={toApiError(eventsQuery.error)}
        onRetry={() => void eventsQuery.refetch()}
      />
    );
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <nav className="flex gap-0.5 border-b border-border-subtle bg-surface px-3 py-1.5">
        {TABS.map((item) => (
          <button
            key={item.id}
            type="button"
            onClick={() => setTab(item.id)}
            aria-current={tab === item.id}
            className={`rounded-card px-2 py-0.5 text-[12px] ${
              tab === item.id
                ? 'bg-brand-50 text-brand-600 dark:bg-brand-500/10 dark:text-brand-300'
                : 'text-fg-muted hover:text-fg'
            }`}
          >
            {item.label}
          </button>
        ))}
        <span className="flex-1" />
        {selectedNodeId ? (
          <span className="self-center text-[11px] text-fg-subtle">
            已选中节点 {selectedNodeId.slice(0, 8)}
          </span>
        ) : null}
      </nav>

      {tab === 'timeline' ? (
        <div className="flex min-h-0 flex-1 flex-col">
          {runQuery.isError ? (
            <p className="border-b border-border-subtle bg-surface px-3 py-2 text-[11px] text-warning-700 dark:text-warning-500">
              读不到运行摘要，不能核对完成轮次和事件条数。
            </p>
          ) : null}
          {gaps.length > 0 ? (
            <ul className="border-b border-border-subtle bg-surface px-3 py-2" data-timeline-gaps="true">
              {gaps.map((gap) => (
                <li key={gap.id} className="text-[11px] text-warning-700 dark:text-warning-500">
                  {gap.text}
                </li>
              ))}
            </ul>
          ) : null}
          <div className="border-b border-border-subtle bg-surface">
            <ScoreTimeline
              points={scoresQuery.data ?? []}
              bestPath={[]}
              onLocateNode={locate}
              highlightNodeId={selectedNodeId}
            />
          </div>
          {eventsQuery.isPending ? (
            <div className="px-4 py-8 text-center text-xs text-fg-subtle">正在读取事件…</div>
          ) : (
            <EventStream
              events={eventsQuery.data?.events ?? []}
              onLocateNode={locate}
              highlightNodeId={selectedNodeId}
            />
          )}
        </div>
      ) : (
        <div className="min-h-0 flex-1 overflow-y-auto bg-surface">
          {leaderboardQuery.isPending ? (
            <div className="px-4 py-8 text-center text-xs text-fg-subtle">正在读取排行榜…</div>
          ) : leaderboardQuery.isError ? (
            <ApiErrorPanel error={toApiError(leaderboardQuery.error)} />
          ) : (
            <LeaderboardPanel
              entries={leaderboardQuery.data ?? []}
              onLocateNode={locate}
              highlightNodeId={selectedNodeId}
            />
          )}
        </div>
      )}
    </div>
  );
}
