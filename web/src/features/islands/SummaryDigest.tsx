/**
 * 知识发现页的「岛间摘要」一节（TODO D6.4：知识页要区分知识卡、运行经验与外岛摘要）。
 *
 * 三样东西在界面上必须能被分开读，因为它们**不是一回事**：
 * - 知识卡：任务知识库里的先验，运行开始前就存在；
 * - 运行经验：这次运行自己沉淀下来的东西（现象层、机制层、本轮沉淀的知识卡）；
 * - 岛间摘要：这次运行里 A 岛发给 B 岛的结论，只在本运行内流转。
 *
 * 需求 §6 的两条硬约束落在这里：
 * 1. 单次观察不得被升级成跨任务规律 —— 所以置信度照 API 原值翻译，
 *    `single_observation` 显示为「单次观察（未复现）」，**永远不出现"已确认"**；
 * 2. 摘要不是知识卡，也不自动进入知识库 —— 这一点写在标题旁边，
 *    而不是让读者从版式里猜。
 *
 * 只读 `/api/runs/{id}/summaries`，失败只降级本节（页面其余小节各有自己的数据源）。
 */
import type { ExchangeSummaryResponse } from '@/generated/api';
import { StatusBadge } from '@/components/ui/StatusBadge';
import {
  confidenceLabel,
  deliveryStatusLabel,
  islandTitle,
  summaryKindLabel,
} from '@/features/islands/island-view';
import { useRunSummaries } from '@/features/islands/use-islands';
import { toApiError } from '@/lib/api';

export interface SummaryDigestProps {
  runId: string;
  onOpenNode?: (nodeId: string) => void;
}

export function SummaryDigest({ runId, onOpenNode }: SummaryDigestProps) {
  const query = useRunSummaries(runId);

  return (
    <section className="flex flex-col gap-2" data-summary-digest>
      <header className="flex flex-wrap items-baseline gap-2">
        <h2 className="text-sm font-semibold text-fg">岛间摘要</h2>
        <span className="text-xs text-fg-subtle">
          来自 /summaries：这是运行内岛与岛之间的结论，不是任务知识库里的知识卡，
          也不会自动登记成知识卡
        </span>
      </header>

      {query.isPending ? (
        <div className="px-4 py-4 text-center text-xs text-fg-subtle" data-summary-state="pending">
          正在读取岛间摘要…
        </div>
      ) : query.isError ? (
        <p
          className="rounded-card border border-warning-500/30 bg-warning-50 p-2 text-[11px] text-warning-700 dark:border-warning-500/40 dark:bg-warning-500/10 dark:text-warning-500"
          data-summary-state="error"
        >
          岛间摘要读不出来（{toApiError(query.error).errorCode}）：{toApiError(query.error).message}
          。这不表示这次运行没有摘要 —— 只表示这一节现在读不到。
        </p>
      ) : query.data.state === 'missing' ? (
        <p className="text-[11px] text-fg-subtle" data-summary-state="missing">
          {query.data.detail || '该运行没有摘要交换层（单树运行早于多岛引擎）。'}
        </p>
      ) : (query.data.summaries ?? []).length === 0 ? (
        <p className="text-[11px] text-fg-subtle" data-summary-state="empty">
          这次运行没有发布过岛间摘要。检查点判定本岛最优超过已发布分数时才会写摘要，
          没有写不等于交换功能被关掉了。
        </p>
      ) : (
        <ul className="flex flex-col gap-2" data-summary-state="available">
          {(query.data.summaries ?? []).map((summary) => (
            <SummaryDigestItem key={summary.summary_id} summary={summary} onOpenNode={onOpenNode} />
          ))}
        </ul>
      )}
    </section>
  );
}

function SummaryDigestItem({
  summary,
  onOpenNode,
}: {
  summary: ExchangeSummaryResponse;
  onOpenNode?: (nodeId: string) => void;
}) {
  const deliveries = summary.deliveries ?? [];
  return (
    <li
      className="rounded-panel border border-border-subtle bg-surface p-2"
      data-digest-summary={summary.summary_id}
    >
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="text-[12px] font-medium text-fg">
          {summaryKindLabel(summary.kind ?? '')}
        </span>
        <StatusBadge tone="neutral">来自 {islandTitle(summary.source_island_id)}</StatusBadge>
        <span
          title={`confidence_status = ${summary.confidence_status ?? ''}`}
          data-confidence={summary.confidence_status ?? 'unknown'}
          className="inline-flex"
        >
          <StatusBadge
            tone={
              summary.confidence_status === 'statistically_confirmed'
                ? 'success'
                : summary.confidence_status === 'replicated'
                  ? 'info'
                  : 'warning'
            }
            title={`confidence_status = ${summary.confidence_status ?? ''}`}
          >
            {confidenceLabel(summary.confidence_status)}
          </StatusBadge>
        </span>
        <span className="flex-1" />
        <span className="text-[10px] text-fg-subtle">
          投递 {deliveries.length} · 采用 {(summary.applications ?? []).length}
        </span>
      </div>

      <p className="mt-1 text-[11px] leading-relaxed text-fg-muted">
        {summary.summary_text || '（该摘要没有文本）'}
      </p>

      {deliveries.length > 0 ? (
        <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-fg-subtle">
          {deliveries.map((delivery) => (
            <span key={delivery.delivery_id}>
              {islandTitle(delivery.source_island_id)} → {islandTitle(delivery.target_island_id)}：
              {deliveryStatusLabel(delivery.status)}
            </span>
          ))}
        </div>
      ) : null}

      {(summary.evidence ?? []).length > 0 ? (
        <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[11px]">
          <span className="text-fg-subtle">证据</span>
          {(summary.evidence ?? []).map((ref) => {
            const nodeId = ref.startsWith('node:') ? ref.slice('node:'.length) : '';
            return nodeId && onOpenNode ? (
              <button
                key={ref}
                type="button"
                onClick={() => onOpenNode(nodeId)}
                className="tabular rounded-pill bg-surface-muted px-1.5 text-brand-600 hover:underline dark:text-brand-300"
                title={`跳转到节点：${nodeId}`}
              >
                {nodeId.slice(0, 8)}
              </button>
            ) : (
              <span key={ref} className="tabular rounded-pill bg-surface-muted px-1.5 text-fg-muted">
                {ref}
              </span>
            );
          })}
        </div>
      ) : null}
    </li>
  );
}
