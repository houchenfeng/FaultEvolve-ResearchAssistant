/**
 * 三岛概览（TODO D6.4：「增加三岛概览、岛切换/并列树、策略说明、全局最优」）。
 *
 * 判定全部在 `island-view.ts`，这个组件只负责把结果摆出来 —— 和
 * `TreeCanvas` 的分工一样：纯几何/对账要能在没有 DOM 的环境里被测试调用。
 *
 * 三条渲染纪律：
 * 1. 数据只来自 API。岛的数量、名字、分数、成本一律不写死，
 *    `state === 'missing'`（历史单树）时**画一棵树 + 一条说明**，不编三个空岛。
 * 2. 缺失显示「未记录」。0 会被读成"这个岛一个节点都没产出"，
 *    而实际上更可能是引擎那版本没记账。
 * 3. 矛盾要显出来。岛还写着 running 而运行已结束、成本分项加不出总量、
 *    `attempt_total` 与全局评估数不等 —— 都原样陈述，界面不替引擎圆场。
 */
import type { RunIslandsResponse, TreeNodeDto } from '@/generated/api';
import { StatusBadge, type BadgeTone } from '@/components/ui/StatusBadge';
import { MissingArtifactNotice } from '@/components/states/MissingArtifactNotice';
import {
  exchangeFacts,
  formatCount,
  formatScore,
  formatUsd,
  globalBestNote,
  islandRows,
  islandShape,
  reconcileAttempts,
  reconcileCost,
  type IslandRow,
} from '@/features/islands/island-view';
import type { TreeEdgeInput } from '@/features/workbench/tree-adapter';

export interface IslandOverviewProps {
  /** `run.islands`：整个区块缺失时是 null，单树运行是 `state: 'missing'`。 */
  islands: RunIslandsResponse | null | undefined;
  nodes: TreeNodeDto[];
  edges: TreeEdgeInput[];
  /** 运行状态（进程或 `outcome.status`），用来判断"岛还在写 running"是否矛盾。 */
  runStatus?: string | null;
  /** `outcome.iterations_done`，与岛级尝试数对账用。 */
  iterationsDone?: number | null;
  /** 全局最优：与"本岛最优"并列显示，两者不是一回事。 */
  globalBest?: { nodeId: string | null; score: number | null } | null;
  onSelectNode?: (nodeId: string) => void;
}

function tokenText(value: number | null | undefined): string {
  if (value === null || value === undefined) return '未记录';
  return value.toLocaleString();
}

function statusTone(status: string | null | undefined): BadgeTone {
  if (status === 'finished') return 'success';
  if (status === 'running') return 'info';
  if (status === 'paused') return 'warning';
  if (status === 'pending') return 'neutral';
  return 'neutral';
}

export function IslandOverview({
  islands,
  nodes,
  edges,
  runStatus = null,
  iterationsDone = null,
  globalBest = null,
  onSelectNode,
}: IslandOverviewProps) {
  const shape = islandShape(islands);

  if (shape === 'legacy-single') {
    return (
      <div className="flex flex-col gap-2 p-3" data-island-shape="legacy-single">
        <MissingArtifactNotice
          artifact="islands / exchange 记账"
          reason={
            islands?.detail ||
            '该运行早于多岛引擎：只有一棵树，没有任何岛级记账可读。'
          }
          nextStep="进化树、闭环与预算各页照常回放；要看三岛请用多岛配置重新运行。"
        />
      </div>
    );
  }

  if (shape === 'unreadable') {
    return (
      <div className="flex flex-col gap-2 p-3" data-island-shape="unreadable">
        <p className="text-xs font-medium text-fg">岛记账读不出来</p>
        <p className="text-[11px] text-fg-muted">
          {islands?.detail || '制品存在但无法解析为岛视图（state=invalid）。'}
        </p>
      </div>
    );
  }

  const rows = islandRows(islands, nodes, edges, runStatus);
  const facts = exchangeFacts(islands?.exchange);
  const cost = reconcileCost(islands?.cost);
  const attempts = reconcileAttempts(islands, iterationsDone);

  // 全局最优落在哪个岛：各岛的节点集合互不相交（同一棵树不会出现在两个岛里），
  // 所以只要那个节点在树里，它的 `island_id` 就是答案。判定写进 island-view
  // 的 `globalBestNote`，结果页用的是同一个函数 —— 两页不能各写一套说法。
  const globalBestNoteText = globalBestNote(nodes, globalBest?.nodeId ?? null);

  return (
    <div className="flex flex-col gap-3 p-3" data-island-shape="islands" data-testid="island-overview">
      <header className="flex flex-wrap items-center gap-2">
        <h2 className="text-[13px] font-medium text-fg">三岛概览</h2>
        <StatusBadge tone="brand">{rows.length} 个岛</StatusBadge>
        <span className="text-[11px] text-fg-muted">
          记账来源：{islands?.source || '未记录'}
        </span>
        <span className="flex-1" />
        <span className="text-[11px] text-fg-muted">
          全局最优{' '}
          <span className="tabular text-fg" data-global-best>
            {formatScore(globalBest?.score ?? null)}
          </span>
          {globalBest?.nodeId ? (
            <button
              type="button"
              onClick={() => onSelectNode?.(globalBest.nodeId as string)}
              className="tabular ml-1 text-brand-600 underline decoration-dotted dark:text-brand-300"
              title={`完整 ID：${globalBest.nodeId}`}
            >
              {globalBest.nodeId.slice(0, 8)}
            </button>
          ) : null}
          <span className="ml-1 text-fg-subtle">{globalBestNoteText}</span>
        </span>
      </header>

      <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
        {rows.map((row) => (
          <IslandCard key={row.islandId || 'legacy'} row={row} onSelectNode={onSelectNode} />
        ))}
      </div>

      <section className="rounded-panel border border-border-subtle bg-surface p-2">
        <h3 className="text-[12px] font-medium text-fg">摘要交换</h3>
        <p className="mt-0.5 text-[11px] text-fg-subtle">
          发布、投递、采纳/拒绝、采用、其中已评估是四件独立的事，各算各的，界面不合并成一个数。
        </p>
        <dl className="mt-1.5 grid grid-cols-2 gap-x-4 gap-y-1 sm:grid-cols-3">
          {facts.map((fact) => (
            <div key={fact.key} className="flex items-baseline justify-between gap-2 text-[11px]">
              <dt className="text-fg-muted" title={fact.note}>
                {fact.label}
              </dt>
              <dd className="tabular text-fg" data-exchange-fact={fact.key}>
                {fact.value}
              </dd>
            </div>
          ))}
        </dl>
      </section>

      <section className="grid gap-2 sm:grid-cols-2">
        <div className="rounded-panel border border-border-subtle bg-surface p-2 text-[11px]">
          <h3 className="text-[12px] font-medium text-fg">尝试数对账</h3>
          <p className="mt-1 text-fg-muted" data-attempt-reconciliation={attempts.state}>
            {attempts.message}
          </p>
        </div>
        <div className="rounded-panel border border-border-subtle bg-surface p-2 text-[11px]">
          <h3 className="text-[12px] font-medium text-fg">成本对账</h3>
          <p className="mt-1 text-fg-muted" data-cost-reconciliation={cost.state}>
            {cost.message}
          </p>
          <p className="mt-1 text-fg-subtle">
            总量 <span className="tabular">{tokenText(cost.totalTokens)}</span> · 未归属{' '}
            <span className="tabular">{tokenText(cost.sharedTokens)}</span> · 美元{' '}
            <span className="tabular">{formatUsd(islands?.cost)}</span>
          </p>
        </div>
      </section>
    </div>
  );
}

/** 一个岛的卡片：生命周期、策略、本岛最优、嫁接进出、本岛成本份额。 */
function IslandCard({
  row,
  onSelectNode,
}: {
  row: IslandRow;
  onSelectNode?: (nodeId: string) => void;
}) {
  const costStages = Object.entries(row.cost?.by_stage ?? {});
  return (
    <article
      className="rounded-panel border border-border-subtle bg-surface p-2"
      data-island-card={row.islandId || 'legacy'}
    >
      <header className="flex flex-wrap items-center gap-1.5">
        <h3 className="text-[12px] font-medium text-fg">{row.title}</h3>
        <StatusBadge tone={statusTone(row.view?.status)} title={`引擎记录的状态：${row.view?.status ?? '未记录'}`}>
          {row.statusLabel}
        </StatusBadge>
        <StatusBadge tone="neutral" title={row.focusText}>
          {row.profileText}
        </StatusBadge>
      </header>

      <p className="mt-1 text-[11px] leading-relaxed text-fg-muted">{row.focusText}</p>

      <dl className="mt-1.5 grid grid-cols-2 gap-x-3 gap-y-0.5 text-[11px]">
        <Metric label="尝试" value={formatCount(row.view?.attempts)} />
        <Metric label="有效评估" value={formatCount(row.view?.valid_evaluations)} />
        <Metric label="非法评估" value={formatCount(row.view?.invalid_evaluations)} />
        {/*
          树内节点数与尝试数在 fixture 里都等于 7，按文本取数会撞成两个候选，
          所以给这个值挂一个按岛区分的钩子（与 `data-island-best` 同一惯例）。
        */}
        <Metric
          label="树内节点"
          value={String(row.tree.nodeCount)}
          valueAttrs={{ 'data-island-tree-count': row.islandId || 'legacy' }}
        />
      </dl>

      <div className="mt-1.5 border-t border-border-subtle pt-1.5 text-[11px]">
        <span className="text-fg-muted">本岛最优 </span>
        <span className="tabular text-[13px] font-medium text-fg" data-island-best={row.islandId}>
          {formatScore(row.tree.bestScore)}
        </span>
        {row.tree.bestNodeId ? (
          <button
            type="button"
            onClick={() => onSelectNode?.(row.tree.bestNodeId as string)}
            className="tabular ml-1 text-brand-600 underline decoration-dotted dark:text-brand-300"
            title={`完整 ID：${row.tree.bestNodeId}`}
          >
            {row.tree.bestNodeId.slice(0, 8)}
          </button>
        ) : null}
        <span className="ml-1 text-fg-subtle">
          （树内实测；run_summary 记 {formatScore(row.view?.best_score)}
          {row.bestScoreConsistent ? '' : '，与实测不一致'}）
        </span>
      </div>

      <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-fg-muted">
        <span>
          有效改进 <span className="tabular text-fg">{row.tree.improvedCount}</span>
        </span>
        <span title="别的岛的摘要嫁接进本岛的节点数">
          接入 <span className="tabular text-fg">{row.tree.graft.incoming}</span>
        </span>
        <span title="本岛发布的摘要被嫁接进别的岛的次数">
          输出 <span className="tabular text-fg">{row.tree.graft.outgoing}</span>
        </span>
        <span title="本岛账本内的 token 份额">
          token <span className="tabular text-fg">{tokenText(row.cost?.tokens)}</span>
        </span>
        <span title="本岛账本内的调用次数">
          调用 <span className="tabular text-fg">{formatCount(row.cost?.calls)}</span>
        </span>
      </div>

      {costStages.length > 0 ? (
        <div className="mt-1 flex flex-wrap gap-1.5 text-[10px] text-fg-subtle">
          {costStages.map(([stage, tokens]) => (
            <span key={stage} className="rounded-pill bg-surface-muted px-1.5">
              {stage} {tokens.toLocaleString()}
            </span>
          ))}
        </div>
      ) : null}

      <p className="mt-1.5 border-t border-border-subtle pt-1.5 text-[11px] text-fg-muted">
        停止原因：<span className="text-fg">{row.stopLabel}</span>
      </p>

      {row.stalenessNote ? (
        <p
          className="mt-1.5 rounded-card border border-warning-500/30 bg-warning-50 px-1.5 py-1 text-[11px] text-warning-700 dark:bg-warning-500/10 dark:text-warning-500"
          data-island-stale={row.islandId}
        >
          {row.stalenessNote}
        </p>
      ) : null}
    </article>
  );
}

function Metric({
  label,
  value,
  valueAttrs,
}: {
  label: string;
  value: string;
  valueAttrs?: Record<string, string>;
}) {
  return (
    <div className="flex items-baseline justify-between gap-2">
      <dt className="text-fg-muted">{label}</dt>
      <dd className="tabular text-fg" {...valueAttrs}>
        {value}
      </dd>
    </div>
  );
}
