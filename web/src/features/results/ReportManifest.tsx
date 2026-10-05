/**
 * 报告导出（PRD 13.5）。
 *
 * 本期**只列不生成**。`ReportManifestResponse` 的 docstring 写得很硬：
 * 「Phase 2 does not *generate* reports (that is a high-risk action, PRD §13.5,
 * phase 9). It only surfaces files a prior export already left behind」。
 *
 * 因此 `available === false` 的正确读法是「这个运行目录下没有已导出的报告文件」，
 * **不是**「导出失败了」，更不是「本期不支持导出所以永远为空」。这句话直接渲染出来，
 * 因为三种读法导向完全不同的下一步。
 */
import { StatusBadge } from '@/components/ui/StatusBadge';
import type { ReportRow } from '@/features/results/results-logic';
import { artifactDownloadUrl } from '@/lib/artifact-url';

export interface ReportManifestProps {
  runId: string;
  rows: ReportRow[];
  available: boolean | null;
  warnings: { field: string; reason: string }[];
}

/** PRD 13.5 要求报告里每个数字都能追溯到具体制品。清单本身不产生数字，
 *  但把这条要求写在页面上，能防止日后有人在这里塞一个前端算出来的汇总。 */
const TRACEABILITY =
  '报告里的每个数字应能追溯到 run_summary.json / tree.json / events.jsonl / fe.db / discovery 制品。' +
  '本页只列出已经存在的报告文件，不生成、不改写其中任何一个数字。';

export function ReportManifest({ runId, rows, available, warnings }: ReportManifestProps) {
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <span data-report-available={available === null ? 'unknown' : String(available)}>
          <StatusBadge
            tone={available === true ? 'success' : available === false ? 'neutral' : 'warning'}
            showDot={false}
          >
            {available === true
              ? '有已导出的报告文件'
              : available === false
                ? '没有已导出的报告文件'
                : '清单未取到'}
          </StatusBadge>
        </span>
        <span className="text-[11px] text-fg-subtle">
          available 的含义是「运行目录下有没有报告文件」，不是「导出成功与否」——本期不生成报告。
        </span>
      </div>

      {warnings.map((warning) => (
        <p
          key={`${warning.field}-${warning.reason}`}
          data-report-warning={warning.field}
          className="rounded-card border border-warning-500/30 bg-warning-50 p-2 text-[11px] text-warning-700 dark:border-warning-500/40 dark:bg-warning-500/10 dark:text-warning-500"
        >
          {warning.reason}
        </p>
      ))}

      {rows.length === 0 ? (
        <p className="text-[11px] text-fg-subtle" data-report-empty>
          没有可列出的报告文件。要得到报告，需要先用仓库既有的导出工具跑一次；
          本页面不会代为生成。
        </p>
      ) : (
        <div className="overflow-x-auto rounded-panel border border-border-subtle">
          <table className="w-full border-collapse text-left">
            <thead>
              <tr className="bg-surface-muted text-[11px] text-fg-muted">
                <th className="px-3 py-2 font-medium">文件</th>
                <th className="px-3 py-2 font-medium">MIME</th>
                <th className="px-3 py-2 font-medium">大小</th>
                <th className="px-3 py-2 font-medium">状态</th>
                <th className="px-3 py-2 font-medium">下载</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr
                  key={row.artifactId}
                  data-report-row={row.artifactId}
                  className="border-b border-border-subtle last:border-b-0"
                >
                  <td className="px-3 py-2 font-mono text-[11px] text-fg">{row.displayName}</td>
                  <td className="px-3 py-2 font-mono text-[10px] text-fg-muted">
                    {row.mediaType.value}
                  </td>
                  <td className="tabular px-3 py-2 text-xs text-fg-muted">{row.sizeBytes.value}</td>
                  <td className="px-3 py-2 font-mono text-[10px] text-fg-muted">{row.state}</td>
                  <td className="px-3 py-2" data-downloadable={String(row.downloadable)}>
                    {row.downloadable === true ? (
                      <a
                        data-download={row.artifactId}
                        href={artifactDownloadUrl(runId, row.artifactId)}
                        download={row.displayName}
                        className="text-[11px] text-brand-600 underline-offset-2 hover:underline"
                      >
                        下载
                      </a>
                    ) : row.downloadable === null ? (
                      <span className="text-[11px] text-fg-subtle">未知（制品清单未取到）</span>
                    ) : (
                      <span className="text-[11px] text-fg-subtle">不可下载</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <p className="text-[11px] text-fg-subtle" data-download-note>
        「可否下载」不在报告清单里：<code className="font-mono">ReportFileResponse</code> 没有
        downloadable 字段，这一列是与 <code className="font-mono">/artifacts</code> 关联出来的。
        关联不上（含制品清单没取到）时显示「未知」，不显示「不可下载」——后者是后端的一个
        明确决定，前端无权替它下。
      </p>

      <p className="text-[11px] text-fg-subtle" data-traceability>
        {TRACEABILITY}
      </p>
    </div>
  );
}
