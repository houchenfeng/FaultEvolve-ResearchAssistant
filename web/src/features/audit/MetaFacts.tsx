/**
 * 部署事实与部署模式（PRD 13.4 的第一项，来源 `/api/meta`）。
 *
 * 这一节能如实说的只有「这个构建里哪些模式可用、后端怎么描述它们、
 * 浏览器要不要鉴权、能不能控制进程」。**不能**从 `mode === 'local_cloud'`
 * 推出任何关于数据物理位置的话——契约里没有位置信息。
 */
import { ApiErrorPanel } from '@/components/states/ApiErrorPanel';
import { StatusBadge } from '@/components/ui/StatusBadge';
import type { DeploymentRow, MetaFactRow } from '@/features/audit/audit-logic';
import { toApiError } from '@/lib/api';
import type { SectionState } from '@/lib/section-state';

export interface MetaFactsProps {
  state: SectionState;
  error: unknown;
  onRetry: () => void;
  facts: MetaFactRow[];
  deployments: DeploymentRow[];
}

function DeploymentTable({ rows }: { rows: DeploymentRow[] }) {
  if (rows.length === 0) {
    return (
      <p className="text-[11px] text-fg-subtle" data-deployment-empty>
        /api/meta 没有给出任何部署模式条目。这不表示「所有模式都不可用」。
      </p>
    );
  }
  return (
    <div className="overflow-x-auto rounded-panel border border-border-subtle">
      <table className="w-full border-collapse text-left">
        <thead>
          <tr className="bg-surface-muted text-[11px] text-fg-muted">
            <th className="px-3 py-2 font-medium">模式</th>
            <th className="px-3 py-2 font-medium">可用性</th>
            <th className="px-3 py-2 font-medium">后端给的说明</th>
            <th className="px-3 py-2 font-medium">supported_transports</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr
              key={row.mode}
              data-deployment-row={row.mode}
              className="border-b border-border-subtle last:border-b-0"
            >
              <td className="px-3 py-2">
                <div className="flex items-center gap-1.5">
                  <code className="font-mono text-[11px] text-fg">{row.mode}</code>
                  {row.isDefault ? (
                    <StatusBadge tone="brand" showDot={false}>
                      默认
                    </StatusBadge>
                  ) : null}
                </div>
              </td>
              <td className="px-3 py-2">
                <span data-deployment-available={row.mode}>
                  <StatusBadge tone={row.available.value === '可用' ? 'success' : 'neutral'}>
                    {row.available.value}
                  </StatusBadge>
                </span>
              </td>
              <td className="px-3 py-2 text-[11px] text-fg-muted">{row.detail.value}</td>
              <td
                className="px-3 py-2 font-mono text-[10px] text-fg-subtle"
                data-deployment-transports={row.mode}
              >
                {row.supportedTransports}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function MetaFacts({ state, error, onRetry, facts, deployments }: MetaFactsProps) {
  return (
    <section className="flex flex-col gap-3" data-meta-facts data-meta-state={state}>
      <header className="flex flex-wrap items-baseline gap-2">
        <h2 className="text-sm font-semibold text-fg">当前部署</h2>
        <span className="text-xs text-fg-subtle">来自 /api/meta</span>
      </header>

      {state === 'pending' ? (
        <div className="px-4 py-6 text-center text-xs text-fg-subtle">正在读取部署信息…</div>
      ) : state === 'error' ? (
        <ApiErrorPanel title="读不到部署信息" error={toApiError(error)} onRetry={onRetry} />
      ) : (
        <>
          <dl className="grid grid-cols-2 gap-2 sm:grid-cols-4" data-meta-grid>
            {facts.map((row) => (
              <div
                key={row.label}
                data-meta-cell={row.label}
                data-recorded={row.cell.recorded ? 'true' : 'false'}
                className="fe-card px-3 py-2"
              >
                <dt className="text-[11px] text-fg-subtle">{row.label}</dt>
                <dd
                  className={`text-sm font-semibold break-all ${
                    row.cell.recorded ? 'text-fg' : 'text-fg-subtle'
                  }`}
                >
                  {row.cell.value}
                </dd>
              </div>
            ))}
          </dl>

          <DeploymentTable rows={deployments} />

          {/* 这一列照字面名渲染，因为后端往 supported_transports 里填的是模式名本身
              （app.py:221,230,243），改叫「传输方式」就是把命名缺陷讲成事实。 */}
          <p className="text-[11px] text-fg-subtle" data-transports-caveat>
            <code className="font-mono">supported_transports</code> 一列按字段原名渲染：后端往里填的
            是模式名本身，不是传输方式。本页也不用
            <code className="mx-1 font-mono">stream_transport</code> 去推断数据在哪里——
            那是传输方式，与数据位置无关。
          </p>
        </>
      )}
    </section>
  );
}
