/**
 * 13.2 Top-K 候选一节。
 *
 * 榜单失败只降级本节：结果总览来自另一个请求，不该因为 /leaderboard 读不到
 * 就一起消失。`data-topk-state` 是测试的落定信号。
 */
import { ApiErrorPanel } from '@/components/states/ApiErrorPanel';
import { TopKCandidates } from '@/features/results/TopKCandidates';
import type { TopKRow } from '@/features/results/results-logic';
import { toApiError } from '@/lib/api';
import type { SectionState } from '@/lib/section-state';

export interface TopKSectionProps {
  runId: string;
  state: SectionState;
  error: unknown;
  onRetry: () => void;
  rows: TopKRow[];
  total: number | null;
  k: number;
  onOpenNode: (nodeId: string) => void;
}

export function TopKSection({
  runId,
  state,
  error,
  onRetry,
  rows,
  total,
  k,
  onOpenNode,
}: TopKSectionProps) {
  return (
    <section className="flex flex-col gap-3" data-topk data-topk-state={state}>
      <header className="flex flex-wrap items-baseline gap-2">
        <h2 className="text-sm font-semibold text-fg">Top-K 候选</h2>
        <span className="text-xs text-fg-subtle">来自 /leaderboard，排序与名次都是后端给的</span>
      </header>

      {state === 'pending' ? (
        <div className="px-4 py-6 text-center text-xs text-fg-subtle">正在读取排行榜…</div>
      ) : state === 'error' ? (
        <ApiErrorPanel title="读不到排行榜" error={toApiError(error)} onRetry={onRetry} />
      ) : (
        <TopKCandidates
          runId={runId}
          rows={rows}
          total={total}
          k={k}
          onOpenNode={onOpenNode}
        />
      )}
    </section>
  );
}
