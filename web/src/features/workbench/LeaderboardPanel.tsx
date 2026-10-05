/**
 * 排行榜（TODO 5.7 / PRD §9.7）。
 *
 * 数据源 `ScoreboardEntryResponse`（rank / node_id / score / operator / depth / is_best）。
 * 点击条目在树里定位节点（PRD §10.2 第 13 条）。
 *
 * 排序由后端给出，这里**不重新排序** —— 分数相同的节点之间次序是引擎的判定，
 * 前端按自己的规则排一遍会让"第 3 名"和引擎的结论不一致。
 */
import type { ScoreboardEntryResponse } from '@/generated/api';
import { shortId } from '@/features/workbench/tree-adapter';

const OPERATOR_LABELS: Record<string, string> = {
  init: '初始程序',
  refine: '精炼',
  crossover: '交叉',
  repair: '修复',
  recall_focus: '召回聚焦',
  threshold_calibrate: '阈值校准',
  inject: '注入',
  transplant: '移植',
};

export interface LeaderboardPanelProps {
  entries: ScoreboardEntryResponse[];
  onLocateNode?: (nodeId: string) => void;
  highlightNodeId?: string | null;
}

export function LeaderboardPanel({ entries, onLocateNode, highlightNodeId }: LeaderboardPanelProps) {
  if (entries.length === 0) {
    return (
      <div className="px-3 py-4 text-[11px] text-fg-subtle" data-testid="leaderboard">
        这次运行还没有可排名的节点
      </div>
    );
  }

  return (
    <table className="w-full text-[11px]" data-testid="leaderboard">
      <thead>
        <tr className="bg-surface-muted text-left text-fg-muted">
          <th className="w-10 px-3 py-1 font-medium">#</th>
          <th className="px-1 py-1 font-medium">节点</th>
          <th className="px-1 py-1 font-medium">算子</th>
          <th className="px-1 py-1 font-medium">深度</th>
          <th className="px-3 py-1 text-right font-medium">分数</th>
        </tr>
      </thead>
      <tbody>
        {entries.map((entry) => {
          const isHighlight = highlightNodeId === entry.node_id;
          return (
            <tr
              key={entry.node_id}
              className={`border-t border-border-subtle ${
                isHighlight ? 'bg-brand-50 dark:bg-brand-500/10' : ''
              }`}
            >
              <td className="tabular px-3 py-1 text-fg-muted">
                {entry.rank}
                {entry.is_best ? <span className="ml-1 text-brand-600">★</span> : null}
              </td>
              <td className="px-1 py-1">
                {onLocateNode ? (
                  <button
                    type="button"
                    onClick={() => onLocateNode(entry.node_id)}
                    className="tabular text-brand-600 underline-offset-2 hover:underline dark:text-brand-300"
                  >
                    {shortId(entry.node_id)}
                  </button>
                ) : (
                  <span className="tabular">{shortId(entry.node_id)}</span>
                )}
              </td>
              <td className="px-1 py-1 text-fg-muted">
                {OPERATOR_LABELS[entry.operator ?? ''] ?? entry.operator ?? '—'}
              </td>
              <td className="tabular px-1 py-1 text-fg-muted">{entry.depth ?? '—'}</td>
              <td className="tabular px-3 py-1 text-right">
                {entry.score === null || entry.score === undefined ? (
                  <span className="text-fg-subtle">未评分</span>
                ) : (
                  entry.score.toFixed(4)
                )}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
