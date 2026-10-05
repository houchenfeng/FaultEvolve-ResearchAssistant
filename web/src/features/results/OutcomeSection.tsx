/**
 * 13.1 结果总览一节（含分项指标与本页的暂不支持清单）。
 *
 * 单独成节的原因：这一节的数据来自两个请求（运行摘要 + 最佳节点详情），
 * 而**运行摘要失败会被 RunLayout 拦在整棵子树之外**，所以这里只需要处理
 * 节点详情那一路的失败，且失败只影响「分项指标」一小块，不影响上面十一行。
 */
import { ApiErrorPanel } from '@/components/states/ApiErrorPanel';
import { ResultsOverview } from '@/features/results/ResultsOverview';
import {
  type MetricRow,
  type MetricsState,
  type SourceRow,
} from '@/features/results/results-logic';
import { toApiError } from '@/lib/api';

export interface OutcomeSectionProps {
  rows: SourceRow[];
  metrics: MetricRow[];
  metricsNodeId: string | null;
  metricsState: MetricsState;
  metricsSkipReason: string | null;
  /** `metricsState === 'error'` 时的原始错误；其余状态传 null。 */
  metricsError: unknown;
  onRetryMetrics: () => void;
}

export function OutcomeSection({
  rows,
  metrics,
  metricsNodeId,
  metricsState,
  metricsSkipReason,
  metricsError,
  onRetryMetrics,
}: OutcomeSectionProps) {
  return (
    <section className="flex flex-col gap-3" data-outcome>
      <header className="flex flex-wrap items-baseline gap-2">
        <h2 className="text-sm font-semibold text-fg">结果总览</h2>
        <span className="text-xs text-fg-subtle">
          来自 run_summary.json，每一格下面标了它出自哪一段
        </span>
      </header>

      <ResultsOverview
        rows={rows}
        metrics={metrics}
        metricsNodeId={metricsNodeId}
        metricsState={metricsState}
        metricsSkipReason={metricsSkipReason}
      />

      {metricsState === 'error' ? (
        <ApiErrorPanel
          title="读不到最佳节点的评测详情"
          error={toApiError(metricsError)}
          onRetry={onRetryMetrics}
          className="self-start"
        />
      ) : null}
    </section>
  );
}
