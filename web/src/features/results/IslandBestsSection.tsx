/**
 * 13.1b 全局最优与各岛最优（TODO D6.4 结果页一行：全局最优与各岛最优，缺失值有状态）。
 *
 * 这一节要挡住两种混淆：
 * 1. **全局最优 ≠ 某一岛的"运气"**：岛之间的树不共享节点，所以全局最优必然落在
 *    某一个岛里。这里把它标在那一行上（`data-holds-global-best`），而不是让读者
 *    自己拿两列数字去比。
 * 2. **同一个候选的指标不被拼接**：本表只报"该岛树内实测的最优"与
 *    `run_summary.json` 为这个岛记的 `best_score` 两个数，并说明二者是否一致；
 *    分项指标仍在「结果总览」那一节，且标明取自哪个节点（同一条纪律）。
 *
 * 历史单树运行没有岛级记账：这里不画一张空表，而是照实说"这次没有岛"。
 */
import { StatusBadge } from '@/components/ui/StatusBadge';
import type { RunIslandsResponse, TreeNodeDto } from '@/generated/api';
import {
  formatScore,
  globalBestNote,
  islandShape,
  type IslandEdge,
} from '@/features/islands/island-view';
import { islandBestRows } from '@/features/results/results-logic';

export interface IslandBestsSectionProps {
  /** `run.islands`：整个区块缺失时是 null，单树运行是 `state: 'missing'`。 */
  islands: RunIslandsResponse | null | undefined;
  nodes: TreeNodeDto[];
  edges: readonly IslandEdge[];
  /**
   * 进化树三态。「本岛最优」是树内实测算出来的，树没读到就不能算 ——
   * 那种情况下本节明说算不了，而不是把「没读到」画成「这个岛 0 个节点」。
   */
  treeState: 'ready' | 'pending' | 'error';
  /** 运行状态，用来标出"岛还写着 running 而运行已结束"。 */
  runStatus: string | null;
  globalBest: { nodeId: string | null; score: number | null };
  onOpenNode: (nodeId: string) => void;
}

export function IslandBestsSection({
  islands,
  nodes,
  edges,
  treeState,
  runStatus,
  globalBest,
  onOpenNode,
}: IslandBestsSectionProps) {
  const shape = islandShape(islands);
  const note = globalBestNote(nodes, globalBest.nodeId);

  if (treeState !== 'ready') {
    return (
      <section className="flex flex-col gap-1" data-island-bests={treeState}>
        <header className="flex flex-wrap items-baseline gap-2">
          <h2 className="text-sm font-semibold text-fg">全局最优与各岛最优</h2>
        </header>
        <p className="text-[11px] text-fg-muted">
          {treeState === 'error'
            ? '进化树读取失败，各岛最优要按树内实测计算，所以本节暂时算不了。这不表示各岛的分数是 0。'
            : '进化树还在读取，各岛最优要按树内实测计算，读到后本节会自动出现。'}
        </p>
        <p className="text-[11px] text-fg-subtle">
          岛级记账（状态、尝试数、成本）不依赖树，在「进化工作台 → 三岛概览」里照常可读。
        </p>
      </section>
    );
  }

  if (shape !== 'islands') {
    return (
      <section className="flex flex-col gap-1" data-island-bests={shape}>
        <header className="flex flex-wrap items-baseline gap-2">
          <h2 className="text-sm font-semibold text-fg">全局最优与各岛最优</h2>
        </header>
        <p className="text-[11px] text-fg-muted">
          全局最优 <span className="tabular text-fg">{formatScore(globalBest.score)}</span>
          {globalBest.nodeId ? <span className="ml-1 font-mono">{globalBest.nodeId}</span> : null}
          {note ? <span className="ml-1">{note}</span> : null}
        </p>
        <p className="text-[11px] text-fg-subtle">
          {shape === 'legacy-single'
            ? `这次运行没有岛级记账（历史单树）${islands?.detail ? `：${islands.detail}` : '。'}各岛最优无从取起，不表示各岛都是 0 分。`
            : `岛记账制品存在但不可解析（state=invalid）${islands?.detail ? `：${islands.detail}` : '。'}各岛最优暂不可用。`}
        </p>
      </section>
    );
  }

  const rows = islandBestRows(islands, nodes, edges, runStatus, globalBest.nodeId);

  return (
    <section className="flex flex-col gap-2" data-island-bests="islands">
      <header className="flex flex-wrap items-baseline gap-2">
        <h2 className="text-sm font-semibold text-fg">全局最优与各岛最优</h2>
        <span className="text-[11px] text-fg-subtle">
          全局最优{' '}
          <span className="tabular text-fg" data-global-best>
            {formatScore(globalBest.score)}
          </span>
          {globalBest.nodeId ? (
            <button
              type="button"
              onClick={() => onOpenNode(globalBest.nodeId as string)}
              className="tabular ml-1 font-mono text-brand-600 underline decoration-dotted dark:text-brand-300"
              title={`完整 ID：${globalBest.nodeId}`}
            >
              {globalBest.nodeId}
            </button>
          ) : null}
          {note ? <span className="ml-1">{note}</span> : null}
        </span>
      </header>

      <p className="text-[11px] text-fg-subtle">
        岛之间不共享节点，所以全局最优必然属于某一个岛 —— 下表用「全局最优」一列标出它在
        哪个岛。本岛最优取本岛树内实测，与 run_summary.json 为这个岛记的分数并列显示。
      </p>

      <table className="w-full text-[11px]">
        <thead className="text-left text-fg-subtle">
          <tr>
            <th className="font-normal">岛</th>
            <th className="font-normal">状态</th>
            <th className="font-normal text-right">本岛最优</th>
            <th className="font-normal text-right">树内节点</th>
            <th className="font-normal text-right">有效改进</th>
            <th className="font-normal">停止原因</th>
            <th className="font-normal">全局最优</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr
              key={row.islandId || 'legacy'}
              data-island-best-row={row.islandId || 'legacy'}
              data-holds-global-best={row.holdsGlobalBest ? 'true' : 'false'}
              className="border-t border-border-subtle align-top"
            >
              <td className="py-1 text-fg">{row.title}</td>
              <td className="py-1">
                <StatusBadge tone="neutral">{row.statusLabel}</StatusBadge>
              </td>
              <td className="tabular py-1 text-right text-fg">
                <span data-island-best={row.islandId}>{formatScore(row.bestScore)}</span>
                {row.bestNodeId ? (
                  <button
                    type="button"
                    onClick={() => onOpenNode(row.bestNodeId as string)}
                    className="ml-1 font-mono text-brand-600 underline decoration-dotted dark:text-brand-300"
                    title={`完整 ID：${row.bestNodeId}`}
                  >
                    {row.bestNodeId.slice(0, 8)}
                  </button>
                ) : null}
                <div className="text-fg-subtle">
                  run_summary 记 {formatScore(row.recordedBestScore)}
                  {row.bestScoreConsistent ? '' : '（与实测不一致）'}
                </div>
              </td>
              <td className="tabular py-1 text-right text-fg-muted">{row.nodeCount}</td>
              <td className="tabular py-1 text-right text-fg-muted">{row.improvedCount}</td>
              <td className="py-1 text-fg-muted">{row.stopLabel}</td>
              <td className="py-1">
                {row.holdsGlobalBest ? (
                  <span className="text-brand-600 dark:text-brand-300">在本岛</span>
                ) : (
                  <span className="text-fg-subtle">—</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {rows.map((row) =>
        row.stalenessNote ? (
          <p
            key={row.islandId || 'legacy'}
            className="rounded-card border border-warning-500/30 bg-warning-50 px-2 py-1 text-[11px] text-warning-700 dark:bg-warning-500/10 dark:text-warning-500"
            data-island-stale={row.islandId || 'legacy'}
          >
            {row.stalenessNote}
          </p>
        ) : null,
      )}
    </section>
  );
}
