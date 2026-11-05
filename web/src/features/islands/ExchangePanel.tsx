/**
 * 摘要交换与采用详情（TODO D6.4：「摘要交换边和采用详情」）。
 *
 * 数据只来自 `GET /api/runs/{run_id}/summaries`：引擎把「发布 / 投递 / 采纳或拒绝 /
 * 采用」记成三张独立的表，接口也照三张表返回，这个面板就按三层显示 ——
 * 任何"交换成功 N 次"式的一句话都会把四件事压成一件，而那正是本项目的
 * 核心可审计性（需求 §6）。
 *
 * 两条不能妥协的显示纪律：
 * 1. 候选的分数是**它自己的评估结果**，不是这条摘要带来的收益（一个候选可能
 *    同时引用多条摘要，而评估器只答一次）。所以表格标题写的是"采用产生的候选"，
 *    列名写的是"该候选的分数"。
 * 2. `evaluated === false` 是"还没评"，不是 0 分。崩溃在写入采用记录之后、
 *    评估返回之前的时候就会出现这一行。
 */
import type { ExchangeSummaryResponse } from '@/generated/api';
import { ApiErrorPanel } from '@/components/states/ApiErrorPanel';
import { EmptyState } from '@/components/states/EmptyState';
import { MissingArtifactNotice } from '@/components/states/MissingArtifactNotice';
import { StatusBadge } from '@/components/ui/StatusBadge';
import {
  confidenceLabel,
  deliveryReasonLabel,
  deliveryStatusLabel,
  formatScore,
  islandTitle,
  summaryKindLabel,
} from '@/features/islands/island-view';
import { useRunSummaries } from '@/features/islands/use-islands';
import { toApiError } from '@/lib/api';

export interface ExchangePanelProps {
  runId: string;
  /** 运行进行中时跟着制品一起刷新。 */
  poll?: boolean;
  onSelectNode?: (nodeId: string) => void;
}

export function ExchangePanel({ runId, poll = false, onSelectNode }: ExchangePanelProps) {
  const query = useRunSummaries(runId, { poll });

  if (query.isPending) {
    return (
      <div className="p-3 text-[11px] text-fg-muted" data-exchange-state="loading">
        正在读取摘要交换层…
      </div>
    );
  }
  if (query.isError) {
    return (
      <div className="p-3">
        <ApiErrorPanel
          error={toApiError(query.error)}
          title="摘要交换层读不出来"
          onRetry={() => void query.refetch()}
        />
      </div>
    );
  }

  const body = query.data;
  if (body.state === 'missing') {
    return (
      <div className="p-3" data-exchange-state="missing">
        <MissingArtifactNotice
          artifact="exchange_summary / exchange_delivery / summary_application"
          reason={body.detail || '该运行没有摘要交换层（单树运行早于多岛引擎）。'}
          nextStep="单树运行的进化树、闭环与预算照常回放；岛间交换需要多岛配置。"
        />
      </div>
    );
  }

  const summaries = body.summaries ?? [];
  return (
    <div className="flex flex-col gap-3 p-3" data-exchange-state="available" data-testid="exchange-panel">
      <header className="flex flex-wrap items-center gap-2">
        <h2 className="text-[13px] font-medium text-fg">摘要交换</h2>
        {/* 四个计数并排，各自带一句解释 —— 谁也不是谁的分子。 */}
        <StatusBadge tone="brand" title="各岛写入 exchange_summary 的条数">
          发布 {body.summary_count}
        </StatusBadge>
        <StatusBadge tone="info" title="投递给其他岛的次数（一条摘要可投给多个岛）">
          投递 {body.delivery_count}
        </StatusBadge>
        <StatusBadge tone="neutral" title="接收岛用该摘要生成候选的次数">
          采用 {body.application_count}
        </StatusBadge>
        <StatusBadge
          tone="success"
          title="其中已由接收岛本地评估器打分的候选数；未评估不等于 0 分"
        >
          已评估 {body.evaluated_application_count}
        </StatusBadge>
      </header>

      {summaries.length === 0 ? (
        <EmptyState
          title="这次运行还没有发布摘要"
          reason="交换层是可用的（三张表都在），只是还没有岛把结论发布出去。多岛引擎在检查点判定本岛最优超过已发布分数时才写摘要。"
          nextStep="想看交换过程可以把 islands.exchange_interval 调小，或多跑几轮。"
        />
      ) : null}

      {summaries.map((summary) => (
        <SummaryCard key={summary.summary_id} summary={summary} onSelectNode={onSelectNode} />
      ))}
    </div>
  );
}

/** 一条摘要：结论本体 + 证据 + 投递判定 + 采用产生的候选。 */
function SummaryCard({
  summary,
  onSelectNode,
}: {
  summary: ExchangeSummaryResponse;
  onSelectNode?: (nodeId: string) => void;
}) {
  const deliveries = summary.deliveries ?? [];
  const applications = summary.applications ?? [];
  const metrics = Object.entries(summary.metrics ?? {});

  return (
    <article
      className="rounded-panel border border-border-subtle bg-surface p-2.5"
      data-summary={summary.summary_id}
    >
      <header className="flex flex-wrap items-center gap-1.5">
        <h3 className="text-[12px] font-medium text-fg">
          {summaryKindLabel(summary.kind ?? '')}
        </h3>
        <StatusBadge tone="neutral" title="发布这条摘要的岛">
          来自 {islandTitle(summary.source_island_id)}
        </StatusBadge>
        {/*
          置信度按 API 原值翻译显示。`single_observation` 是"单次观察"，
          需求 §6 明令不得渲染成已确认的规律，所以标签里保留"未复现"。
        */}
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
        <span className="flex-1" />
        <span className="tabular text-[10px] text-fg-subtle" title={summary.summary_id}>
          {summary.summary_id.slice(0, 12)}
        </span>
      </header>

      <p className="mt-1.5 text-[12px] leading-relaxed text-fg">{summary.summary_text || '（该摘要没有文本）'}</p>

      {summary.conditions ? (
        <p className="mt-1 text-[11px] text-fg-muted">
          适用条件：<span className="text-fg">{summary.conditions}</span>
        </p>
      ) : null}

      <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-[11px]">
        <span className="text-fg-muted">证据</span>
        {(summary.evidence ?? []).map((ref) => (
          <EvidenceChip key={ref} ref_={ref} onSelectNode={onSelectNode} />
        ))}
        {(summary.evidence ?? []).length === 0 ? <span className="text-fg-subtle">未记录</span> : null}
      </div>

      {metrics.length > 0 ? (
        <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-fg-muted">
          {metrics.map(([key, value]) => (
            <span key={key}>
              {key} <span className="tabular text-fg">{formatMetric(value)}</span>
            </span>
          ))}
        </div>
      ) : null}

      <section className="mt-2 border-t border-border-subtle pt-2">
        <h4 className="text-[11px] font-medium text-fg-muted">投递与判定</h4>
        {deliveries.length === 0 ? (
          <p className="mt-1 text-[11px] text-fg-subtle">这条摘要还没有投递给任何岛。</p>
        ) : (
          <ul className="mt-1 flex flex-col gap-1 text-[11px]">
            {deliveries.map((delivery) => (
              <li
                key={delivery.delivery_id}
                data-delivery={delivery.delivery_id}
                className="flex flex-wrap items-center gap-1.5"
              >
                <span className="tabular text-fg-subtle" title={delivery.delivery_id}>
                  {delivery.delivery_id.slice(0, 10)}
                </span>
                <span className="text-fg-muted">
                  {islandTitle(delivery.source_island_id)} →{' '}
                  <span className="text-fg">{islandTitle(delivery.target_island_id)}</span>
                </span>
                <StatusBadge
                  tone={
                    delivery.status === 'accepted'
                      ? 'success'
                      : delivery.status === 'rejected'
                        ? 'danger'
                        : 'neutral'
                  }
                >
                  {deliveryStatusLabel(delivery.status)}
                </StatusBadge>
                {delivery.reason ? (
                  <span className="text-fg-subtle" title={`原因原值：${delivery.reason}`}>
                    {deliveryReasonLabel(delivery.reason) || delivery.reason}
                  </span>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="mt-2 border-t border-border-subtle pt-2">
        <h4 className="text-[11px] font-medium text-fg-muted">采用产生的候选</h4>
        <p className="mt-0.5 text-[10px] text-fg-subtle">
          下表分数是**该候选自己**的评估结果。一个候选可能同时引用多条摘要而评估器只答一次，
          所以这里不表示"这条摘要带来了多少提升"。
        </p>
        {applications.length === 0 ? (
          <p className="mt-1 text-[11px] text-fg-subtle">还没有候选引用这条摘要。</p>
        ) : (
          <table className="mt-1 w-full text-[11px]">
            <thead className="text-left text-fg-subtle">
              <tr>
                <th className="font-normal">候选节点</th>
                <th className="font-normal">接收岛</th>
                <th className="font-normal text-right">该候选的分数</th>
                <th className="font-normal text-right">评估</th>
              </tr>
            </thead>
            <tbody>
              {applications.map((application) => (
                <tr key={application.application_id} className="border-t border-border-subtle">
                  <td className="py-1">
                    <button
                      type="button"
                      onClick={() => onSelectNode?.(application.candidate_node_id)}
                      className="tabular text-brand-600 underline decoration-dotted dark:text-brand-300"
                      title={`完整 ID：${application.candidate_node_id}`}
                    >
                      {application.candidate_node_id.slice(0, 8)}
                    </button>
                  </td>
                  <td className="py-1 text-fg-muted">
                    {islandTitle(application.target_island_id ?? '')}
                  </td>
                  <td className="tabular py-1 text-right" data-application-score={application.application_id}>
                    {application.evaluated ? formatScore(application.score) : '未评估'}
                  </td>
                  <td className="py-1 text-right text-fg-subtle">
                    {application.evaluated ? '已评估' : '尚未'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </article>
  );
}

/**
 * 证据引用。
 *
 * 引擎写的形式是 `node:<id>`（见 `cloud/exchange.py`）。能跳就做成按钮，
 * 不能跳的引用（例如未来的其它前缀）原样显示 —— 接口不提供源文件路径读取，
 * 所以这里也绝不出现"打开文件"之类的动作。
 */
function EvidenceChip({
  ref_,
  onSelectNode,
}: {
  ref_: string;
  onSelectNode?: (nodeId: string) => void;
}) {
  const nodeId = ref_.startsWith('node:') ? ref_.slice('node:'.length) : '';
  if (nodeId) {
    return (
      <button
        type="button"
        onClick={() => onSelectNode?.(nodeId)}
        className="tabular rounded-pill bg-surface-muted px-1.5 text-brand-600 hover:underline dark:text-brand-300"
        title={`跳转到节点：${nodeId}`}
      >
        {nodeId.slice(0, 8)}
      </button>
    );
  }
  return (
    <span className="tabular rounded-pill bg-surface-muted px-1.5 text-fg-muted" title={ref_}>
      {ref_}
    </span>
  );
}

/** 指标值：分数保留两位，其它原样，非有限值显示「未记录」。 */
function formatMetric(value: number): string {
  if (!Number.isFinite(value)) return '未记录';
  return Math.abs(value) >= 100 || Number.isInteger(value)
    ? value.toLocaleString()
    : value.toFixed(4);
}
