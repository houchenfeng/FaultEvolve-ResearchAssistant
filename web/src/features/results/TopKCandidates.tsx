/**
 * Top-K 候选（PRD 13.2）。
 *
 * 排名、分数、`is_best` 全部由后端给（`/api/runs/{id}/leaderboard` →
 * `ScoreboardEntryResponse`，服务端已按分数排序、未评分的排最后）。
 * 前端只截断，不重排、不重新编号、不重算分数。
 *
 * 下载入口只在 `programArtifactId` 非空时出现——那个 id 是从 `/artifacts`
 * 清单里核对过的（存在且 `downloadable === true`），不是拼出来碰运气的。
 */
import { StatusBadge } from '@/components/ui/StatusBadge';
import type { TopKRow } from '@/features/results/results-logic';
import { artifactDownloadUrl } from '@/lib/artifact-url';

export interface TopKCandidatesProps {
  runId: string;
  rows: TopKRow[];
  /** 榜单总条数；null 表示榜单没取到，此时不能说「共 0 条」。 */
  total: number | null;
  k: number;
  onOpenNode?: (nodeId: string) => void;
}

export function TopKCandidates({ runId, rows, total, k, onOpenNode }: TopKCandidatesProps) {
  if (rows.length === 0) {
    return (
      <p className="text-[11px] text-fg-subtle" data-topk-empty>
        榜单为空。这可能是没有任何节点被评过分——按本页一贯的纪律，未评分的节点显示「未评分」
        （同 tree-adapter.ts 的 formatScore），不显示 ROS = 0。
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      <p className="text-[11px] text-fg-subtle" data-topk-note>
        共 {total == null ? '未知' : total} 条，显示前 {Math.min(k, rows.length)} 条。
        排序与名次都来自后端，前端不重排。
      </p>

      <div className="overflow-x-auto rounded-panel border border-border-subtle">
        <table className="w-full border-collapse text-left">
          <thead>
            <tr className="bg-surface-muted text-[11px] text-fg-muted">
              <th className="px-3 py-2 font-medium">名次</th>
              <th className="px-3 py-2 font-medium">节点</th>
              <th className="px-3 py-2 font-medium">分数</th>
              <th className="px-3 py-2 font-medium">算子</th>
              <th className="px-3 py-2 font-medium">深度</th>
              <th className="px-3 py-2 font-medium">候选代码</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr
                key={row.nodeId}
                data-topk-row={row.nodeId}
                className="border-b border-border-subtle last:border-b-0"
              >
                <td className="tabular px-3 py-2 text-xs text-fg-muted">
                  {row.rank.recorded ? row.rank.value : '未记录'}
                </td>
                <td className="px-3 py-2">
                  <div className="flex items-center gap-1.5">
                    <button
                      type="button"
                      data-node-link={row.nodeId}
                      disabled={!onOpenNode}
                      onClick={() => onOpenNode?.(row.nodeId)}
                      className="font-mono text-[11px] text-brand-600 underline-offset-2 hover:underline disabled:text-fg-subtle disabled:no-underline"
                    >
                      {row.nodeId}
                    </button>
                    {row.isBest ? (
                      <StatusBadge tone="success" showDot={false}>
                        最佳
                      </StatusBadge>
                    ) : null}
                  </div>
                </td>
                <td
                  className="tabular px-3 py-2 text-xs"
                  data-score-recorded={row.score.recorded ? 'true' : 'false'}
                >
                  {row.score.value}
                </td>
                <td className="px-3 py-2 font-mono text-[11px] text-fg-muted">
                  {row.operator ?? '未记录'}
                </td>
                <td className="tabular px-3 py-2 text-xs text-fg-muted">{row.depth.value}</td>
                <td className="px-3 py-2" data-downloadable={String(row.downloadable)}>
                  {row.programArtifactId ? (
                    <a
                      data-download={row.programArtifactId}
                      href={artifactDownloadUrl(runId, row.programArtifactId)}
                      download
                      className="text-[11px] text-brand-600 underline-offset-2 hover:underline"
                    >
                      下载
                    </a>
                  ) : row.downloadable === null ? (
                    <span className="text-[11px] text-fg-subtle">未知（制品清单未取到）</span>
                  ) : (
                    <span className="text-[11px] text-fg-subtle">无可下载代码</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
