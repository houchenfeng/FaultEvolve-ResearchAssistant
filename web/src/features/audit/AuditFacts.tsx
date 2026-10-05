/**
 * 制品边界一节（PRD 13.4 的第二项，来源 `/api/runs/{id}/artifacts`）。
 *
 * 这份清单比 PRD 要的更硬：它逐条给出服务器**愿意**谈哪些制品、其中哪些
 * **拒绝下载**，id 由服务器签发、原始路径从不返回（`contracts.py:977-982`）。
 * 所以「数据边界」在这里不是一句承诺，是一张能逐行核对的表。
 *
 * 受保护名称扫描的纪律与任务页一致：查到就大声报缺陷，但**只报数量、不渲染名字**
 * ——名字本身就是不该出现在页面上的内容（`task-detail-logic.ts` 的 §7.8 处置）。
 */
import { ApiErrorPanel } from '@/components/states/ApiErrorPanel';
import { StatusBadge } from '@/components/ui/StatusBadge';
import {
  ARTIFACT_LIST_NOTE,
  type ArtifactStateRow,
  type BoundaryRow,
  type KindRow,
  type LeakScan,
} from '@/features/audit/audit-logic';
import { StatValue } from '@/features/discovery/StatValue';
import { toApiError } from '@/lib/api';
import type { SectionState } from '@/lib/section-state';

export interface AuditFactsProps {
  state: SectionState;
  error: unknown;
  onRetry: () => void;
  /** 来自运行详情（RunLayout 已经取好），与制品清单是两个来源，见下面注释。 */
  artifactStates: ArtifactStateRow[];
  kinds: KindRow[];
  boundary: BoundaryRow[];
  leak: LeakScan;
}

const WARNING_CLASS =
  'rounded-card border border-warning-500/30 bg-warning-50 p-2 text-[11px] text-warning-700 ' +
  'dark:border-warning-500/40 dark:bg-warning-500/10 dark:text-warning-500';

function ArtifactStateList({ rows }: { rows: ArtifactStateRow[] }) {
  if (rows.length === 0) {
    return (
      <p className="text-[11px] text-fg-subtle" data-artifact-states-empty>
        运行详情没有给出 artifact_states，因此无从判断核心制品的可读性。
      </p>
    );
  }
  return (
    <dl className="flex flex-wrap gap-2" data-artifact-states>
      {rows.map((row) => (
        <div
          key={row.name}
          data-artifact-state-row={row.name}
          className="flex items-center gap-1.5 rounded-card border border-border-subtle bg-surface px-2.5 py-1"
        >
          <dt className="font-mono text-[11px] text-fg-muted">{row.name}</dt>
          <dd
            data-artifact-state={row.name}
            className="font-mono text-[10px] text-fg-subtle"
          >
            {row.state}
          </dd>
        </div>
      ))}
    </dl>
  );
}

function KindList({ rows }: { rows: KindRow[] }) {
  if (rows.length === 0) {
    return (
      <p className="text-[11px] text-fg-subtle" data-kind-empty>
        制品清单为空，因此无从按类别汇总。
      </p>
    );
  }
  return (
    <dl className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
      {rows.map((row) => (
        <div
          key={row.kind}
          data-kind-row={row.kind}
          className="fe-card px-3 py-2"
        >
          <dt className="font-mono text-[11px] text-fg-muted">{row.kind}</dt>
          <dd className="mt-0.5 flex flex-wrap items-baseline gap-x-3 text-[11px] text-fg-subtle">
            <span>
              条目 <StatValue cell={row.count} name={`kind-count-${row.kind}`} />
            </span>
            <span data-kind-downloadable={row.kind}>
              可下载 <StatValue cell={row.downloadable} name={`kind-downloadable-${row.kind}`} />
            </span>
          </dd>
        </div>
      ))}
    </dl>
  );
}

function BoundaryTable({ rows }: { rows: BoundaryRow[] }) {
  if (rows.length === 0) {
    return (
      <p className="text-[11px] text-fg-subtle" data-boundary-empty>
        这个运行的制品清单是空的：服务器没有可谈的任何制品。
      </p>
    );
  }
  return (
    <div className="overflow-x-auto rounded-panel border border-border-subtle">
      <table className="w-full border-collapse text-left">
        <thead>
          <tr className="bg-surface-muted text-[11px] text-fg-muted">
            <th className="px-3 py-2 font-medium">制品 id（服务器签发）</th>
            <th className="px-3 py-2 font-medium">类别</th>
            <th className="px-3 py-2 font-medium">显示名</th>
            <th className="px-3 py-2 font-medium">MIME</th>
            <th className="px-3 py-2 font-medium">大小</th>
            <th className="px-3 py-2 font-medium">state</th>
            <th className="px-3 py-2 font-medium">可下载</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr
              key={row.artifactId}
              data-boundary-row={row.artifactId}
              className="border-b border-border-subtle last:border-b-0"
            >
              <td className="px-3 py-2 font-mono text-[11px] text-fg">{row.artifactId}</td>
              <td
                className="px-3 py-2 font-mono text-[10px] text-fg-muted"
                data-boundary-kind={row.artifactId}
              >
                {row.kind}
              </td>
              <td className="px-3 py-2 text-[11px] text-fg-muted">{row.displayName}</td>
              <td className="px-3 py-2 font-mono text-[10px] text-fg-subtle">
                {row.mediaType.value}
              </td>
              <td className="tabular px-3 py-2 text-[11px] text-fg-subtle">
                {row.sizeBytes.value}
              </td>
              <td className="px-3 py-2 font-mono text-[10px] text-fg-subtle">{row.state}</td>
              <td className="px-3 py-2" data-boundary-downloadable={row.artifactId}>
                <StatusBadge tone={row.downloadable ? 'success' : 'danger'} showDot={false}>
                  {row.downloadable ? '是' : '否'}
                </StatusBadge>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function LeakScanResult({ leak }: { leak: LeakScan }) {
  return (
    <div className="flex flex-col gap-2" data-leak-scan>
      <p className="text-[11px] text-fg-subtle">
        浏览器实际收到 <StatValue cell={leak.scanned} name="leak-scanned" /> 个名字（制品 id 与
        显示名各算一次），逐个匹配留出集关键词。
      </p>
      {leak.leaked > 0 ? (
        <p className={WARNING_CLASS} data-leak-defect>
          命中 {leak.leaked} 个受保护名称。这是后端过滤链的缺陷，不是本页的显示问题：命中项的
          名字一律不渲染，因为名字本身就是不该出现在页面上的内容。请检查服务端的
          FORBIDDEN_PATTERNS / PROTECTED_NAME_RE。
        </p>
      ) : (
        <p className="text-[11px] text-fg-muted" data-leak-clean>
          未命中受保护名称。
        </p>
      )}
      <p className="text-[11px] text-fg-subtle" data-leak-scope>
        这次扫描只覆盖本页拿到的制品清单，不是对整个后端输出的审计。「未命中」不等于「后端任何
        响应里都没有受保护内容」——那需要服务端自证，而契约里没有这样的端点（见下方暂不支持）。
      </p>
    </div>
  );
}

export function AuditFacts({
  state,
  error,
  onRetry,
  artifactStates,
  kinds,
  boundary,
  leak,
}: AuditFactsProps) {
  return (
    <section className="flex flex-col gap-3" data-boundary-facts data-artifacts-state={state}>
      <header className="flex flex-wrap items-baseline gap-2">
        <h2 className="text-sm font-semibold text-fg">制品边界</h2>
        <span className="text-xs text-fg-subtle">来自 /api/runs/…/artifacts 与运行详情</span>
      </header>

      {/* 这一块不受下面的三态控制：它出自运行详情（RunLayout 已经取好并拦住了失败），
          制品清单读不到时它仍然是真的，一起藏掉等于丢掉一份已有事实。 */}
      <div className="flex flex-col gap-2">
        <h3 className="text-xs font-medium text-fg-muted">运行核心制品的可读性（run_summary 视角）</h3>
        <ArtifactStateList rows={artifactStates} />
      </div>

      {state === 'pending' ? (
        <div className="px-4 py-6 text-center text-xs text-fg-subtle">正在读取制品清单…</div>
      ) : state === 'error' ? (
        <ApiErrorPanel title="读不到制品清单" error={toApiError(error)} onRetry={onRetry} />
      ) : (
        <>
          <div className="flex flex-col gap-2" data-kinds>
            <h3 className="text-xs font-medium text-fg-muted">按类别汇总</h3>
            <KindList rows={kinds} />
          </div>

          <div className="flex flex-col gap-2" data-boundary>
            <h3 className="text-xs font-medium text-fg-muted">逐条清单</h3>
            <BoundaryTable rows={boundary} />
            <p className="text-[11px] text-fg-subtle" data-artifact-note>
              {ARTIFACT_LIST_NOTE}
            </p>
            <p className="text-[11px] text-fg-subtle" data-artifact-id-note>
              id 由服务器签发，原始路径从不进入响应（
              <code className="font-mono">contracts.py:977-982</code>）。因此本页无法、也不会展示
              「数据在服务器的哪个目录」——那是路径信息，不是边界事实。
            </p>
          </div>

          <div className="flex flex-col gap-2" data-leak>
            <h3 className="text-xs font-medium text-fg-muted">受保护名称扫描（客户端）</h3>
            <LeakScanResult leak={leak} />
          </div>
        </>
      )}
    </section>
  );
}
