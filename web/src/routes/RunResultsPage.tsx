/**
 * 结果与报告页（PRD 13.1–13.5 / TODO 6.4，`/runs/$runId/results`）。
 *
 * 数据装配全部在 `use-results-data.ts`，本文件只剩渲染。六个请求彼此独立，
 * 任何一个失败只降级它自己那一节：整页早退会让「报告清单读不到」连带抹掉
 * 已经拿到的结果总览（同知识卡页把整页降级改成按节内联的教训）。
 */
import { Link, useNavigate } from '@tanstack/react-router';

import { ComparisonSection } from '@/features/results/ComparisonSection';
import { OutcomeSection } from '@/features/results/OutcomeSection';
import { ReportSection } from '@/features/results/ReportSection';
import { TopKSection } from '@/features/results/TopKSection';
import {
  DEFAULT_TOP_K,
  metricRows,
  noiseSummary,
  noiseVerdict,
  outcomeRows,
  reportRows,
} from '@/features/results/results-logic';
import { useResultsData } from '@/features/results/use-results-data';
import { toApiError } from '@/lib/api';
import { sectionState } from '@/lib/section-state';
import { useUiStore } from '@/stores/ui-store';
import { HddResultsCase } from '@/features/showcase/HddResultsCase';
import { SHOWCASE_RUN_ID } from '@/features/showcase/hdd-showcase-data';

export function RunResultsPage() {
  const view = useResultsData();
  const navigate = useNavigate();
  const setSelectedNodeId = useUiStore((state) => state.setSelectedNodeId);
  const { runId } = view;

  if (runId === SHOWCASE_RUN_ID) {
    return <HddResultsCase />;
  }

  const openNode = (nodeId: string) => {
    setSelectedNodeId(nodeId);
    void navigate({ to: '/runs/$runId/tree', params: { runId } });
  };

  return (
    <div className="flex flex-col gap-5" data-results-page={runId}>
      {/*
        页面级标题。合入 webui-ci 的阶段 6 页面后这一层没了，只剩各节的 <h2>：
        后果是这一屏在可访问性树里没有 h1（屏幕阅读器读不出"这是哪一页"），
        §12.5 的视觉回归与 E2E-01 第 9 步也因此失去落点。标题不重复侧栏：
        侧栏是导航，这里是"你现在在哪"。
      */}
      <h1 className="text-base font-semibold text-fg">结果与报告</h1>
      {view.artifactsQuery.isError ? (
        <p
          data-artifacts-unavailable
          className="rounded-card border border-warning-500/30 bg-warning-50 p-2 text-[11px] text-warning-700 dark:border-warning-500/40 dark:bg-warning-500/10 dark:text-warning-500"
        >
          制品清单读取失败（{toApiError(view.artifactsQuery.error).errorCode}）。下面的下载入口
          一律显示「未知」而不是「不可下载」：清单没取到时前端并不知道后端允许下载什么，
          替它下结论就是把一次请求故障讲成后端的决定。
        </p>
      ) : null}

      <OutcomeSection
        rows={outcomeRows(view.detailQuery.data)}
        metrics={metricRows(view.metric)}
        metricsNodeId={view.bestNodeId}
        metricsState={view.metricsState}
        metricsSkipReason={view.metricsSkipReason}
        metricsError={view.nodeQuery.error}
        onRetryMetrics={() => void view.nodeQuery.refetch()}
      />

      <TopKSection
        runId={runId}
        state={sectionState(view.leaderboardQuery.isPending, view.leaderboardQuery.isError)}
        error={view.leaderboardQuery.error}
        onRetry={() => void view.leaderboardQuery.refetch()}
        rows={view.topK}
        total={view.leaderboardTotal}
        k={DEFAULT_TOP_K}
        onOpenNode={openNode}
      />

      <ComparisonSection
        state={sectionState(view.treeQuery.isPending, view.treeQuery.isError)}
        error={view.treeQuery.error}
        onRetry={() => void view.treeQuery.refetch()}
        bestNodeId={view.bestNodeId}
        verdict={noiseVerdict(view.bestNode)}
        summary={noiseSummary(view.treeQuery.data?.nodes)}
        warnings={view.treeWarnings}
      />

      {/* PRD 13.4 把「数据边界与审计」归在结果与报告模块下，但它是独立路由，
          且侧栏只有四项，所以入口只能从这里给。 */}
      <Link
        to="/runs/$runId/audit"
        params={{ runId }}
        data-audit-link
        className="self-start fe-btn fe-btn-secondary fe-btn-sm text-brand-600 hover:border-brand-500"
      >
        数据边界与审计 →
      </Link>

      <ReportSection
        runId={runId}
        state={sectionState(view.reportQuery.isPending, view.reportQuery.isError)}
        error={view.reportQuery.error}
        onRetry={() => void view.reportQuery.refetch()}
        rows={reportRows(view.report, view.artifacts)}
        available={view.report?.available ?? null}
        warnings={view.report?.warnings ?? []}
      />
    </div>
  );
}
