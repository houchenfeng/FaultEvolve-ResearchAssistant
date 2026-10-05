/**
 * 13.5 报告导出一节。
 *
 * 本期**只列不生成**，所以这一节最常见的状态就是「清单里没有文件」。
 * 那不是错误，也不是暂不支持——是「这个运行目录下确实没有已导出的报告」。
 * 三种情况必须分开渲染，否则用户会以为点一下就能导出。
 */
import { ApiErrorPanel } from '@/components/states/ApiErrorPanel';
import { ReportManifest } from '@/features/results/ReportManifest';
import { type ReportRow } from '@/features/results/results-logic';
import { toApiError } from '@/lib/api';
import type { SectionState } from '@/lib/section-state';

export interface ReportSectionProps {
  runId: string;
  state: SectionState;
  error: unknown;
  onRetry: () => void;
  rows: ReportRow[];
  /** null = 清单没取到；与 `available === false`（确实没有报告文件）不是一回事。 */
  available: boolean | null;
  warnings: { field: string; reason: string }[];
}

export function ReportSection({
  runId,
  state,
  error,
  onRetry,
  rows,
  available,
  warnings,
}: ReportSectionProps) {
  return (
    <section className="flex flex-col gap-3" data-report data-report-state={state}>
      <header className="flex flex-wrap items-baseline gap-2">
        <h2 className="text-sm font-semibold text-fg">报告与制品下载</h2>
        <span className="text-xs text-fg-subtle">来自 /reports/manifest，本页不生成任何报告</span>
      </header>

      {state === 'pending' ? (
        <div className="px-4 py-6 text-center text-xs text-fg-subtle">正在读取报告清单…</div>
      ) : state === 'error' ? (
        <ApiErrorPanel title="读不到报告清单" error={toApiError(error)} onRetry={onRetry} />
      ) : (
        <ReportManifest runId={runId} rows={rows} available={available} warnings={warnings} />
      )}
    </section>
  );
}
