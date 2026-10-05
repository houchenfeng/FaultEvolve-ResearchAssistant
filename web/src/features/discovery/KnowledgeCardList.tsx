/**
 * 知识卡列表（PRD 12.2 / TODO 6.1）。
 *
 * 只吃 props、不发请求（请求在路由页里），这样渲染测试不必 mock SDK。
 *
 * 两条不能破的线：
 * 1. 后端给 null 的格子显示「未记录」，绝不显示 0（PRD §2.3）。
 * 2. 「信任 / 存疑 / 排除」是浏览器本地标记，必须与「不影响真实运行」同时出现
 *    （PRD 12.2 明确要求），不能让它看起来像会影响演化的开关。
 */
import { StatusBadge } from '@/components/ui/StatusBadge';
import {
  CARD_LABELS,
  EMPTY_CARD_FILTER,
  LOCAL_LABEL_DISCLAIMER,
  categoryLabel,
  filterCards,
  type CardFilter,
  type CardLabel,
  type CardRow,
  type Cell,
} from '@/features/discovery/card-logic';

export interface KnowledgeCardListProps {
  rows: CardRow[];
  filter: CardFilter;
  onFilterChange: (filter: CardFilter) => void;
  onLabelChange: (cardId: string, label: CardLabel | null) => void;
  /** 点采纳节点时跳到进化树；由路由页接线到 store + navigate。 */
  onOpenNode?: (nodeId: string) => void;
  /**
   * `fe.db` 的制品状态。`unknown` 表示运行详情请求没成功——那时**不能**宣称
   * 数据库缺失，否则一个接口故障会被说成运行制品有问题。
   */
  databaseState: DatabaseState;
}

/** `ArtifactState` 再加一个「没查到」，三态不能压成布尔。 */
export type DatabaseState = 'available' | 'missing' | 'invalid' | 'unknown';

function StatCell({ cell, name }: { cell: Cell; name: string }) {
  return (
    <td
      data-card-cell={name}
      data-recorded={cell.recorded ? 'true' : 'false'}
      className={`px-3 py-2 tabular text-xs ${cell.recorded ? 'text-fg' : 'text-fg-subtle'}`}
    >
      {cell.value}
    </td>
  );
}

export function KnowledgeCardList({
  rows,
  filter,
  onFilterChange,
  onLabelChange,
  onOpenNode,
  databaseState,
}: KnowledgeCardListProps) {
  const visible = filterCards(rows, filter);
  const categories = [
    ...new Set(rows.map((row) => row.category).filter((category): category is string => Boolean(category))),
  ].sort();
  // 只有**确知**不可读才提示；`unknown` 是运行详情没取到，不能冤枉这份运行。
  const databaseKnownBad = databaseState !== 'unknown' && databaseState !== 'available';

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <input
          type="search"
          value={filter.query}
          onChange={(event) => onFilterChange({ ...filter, query: event.target.value })}
          placeholder="搜索卡片 ID、标题或 claim"
          aria-label="搜索卡片 ID、标题或 claim"
          className="fe-input fe-input-sm py-1 font-mono text-[11px]"
        />
        <select
          value={filter.label}
          aria-label="按本地标记筛选"
          onChange={(event) =>
            onFilterChange({ ...filter, label: event.target.value as CardFilter['label'] })
          }
          className="fe-input fe-input-sm py-1 text-[11px]"
        >
          <option value="any">全部标记</option>
          {CARD_LABELS.map((label) => (
            <option key={label} value={label}>
              {label}
            </option>
          ))}
        </select>
        {categories.length > 0 ? (
          <select
            value={filter.category}
            aria-label="按类别筛选"
            onChange={(event) => onFilterChange({ ...filter, category: event.target.value })}
            className="fe-input fe-input-sm py-1 text-[11px]"
          >
            <option value="any">全部类别</option>
            {categories.map((category) => (
              <option key={category} value={category}>
                {categoryLabel(category)}
              </option>
            ))}
          </select>
        ) : null}
        <span className="text-[11px] text-fg-subtle">
          {visible.length} / {rows.length} 张
        </span>
        <StatusBadge tone="neutral" showDot={false}>
          {LOCAL_LABEL_DISCLAIMER}
        </StatusBadge>
      </div>

      {databaseKnownBad ? (
        <p
          data-database-unavailable="true"
          data-database-state={databaseState}
          className="rounded-card border border-warning-500/30 bg-warning-50 p-2 text-[11px] text-warning-700 dark:border-warning-500/40 dark:bg-warning-500/10 dark:text-warning-500"
        >
          这次运行的 <code className="font-mono">fe.db</code> {databaseState === 'invalid' ? '不可解析' : '缺失'}
          ，下面的计数与平均 Δ 全部显示「未记录」。「未记录」表示读不到，不表示没有采纳过。
        </p>
      ) : null}

      <div className="overflow-x-auto rounded-panel border border-border-subtle">
        <table className="w-full border-collapse text-left">
          <thead>
            <tr className="bg-surface-muted text-[11px] text-fg-muted">
              <th className="px-3 py-2 font-medium">卡片 ID</th>
              <th className="px-3 py-2 font-medium">提供</th>
              <th className="px-3 py-2 font-medium">采纳</th>
              <th className="px-3 py-2 font-medium">否证</th>
              <th className="px-3 py-2 font-medium">无效</th>
              <th className="px-3 py-2 font-medium">平均 Δ</th>
              <th className="px-3 py-2 font-medium">样本数 n</th>
              <th className="px-3 py-2 font-medium">采用代</th>
              <th className="px-3 py-2 font-medium">采纳节点</th>
              <th className="px-3 py-2 font-medium">本地标记</th>
            </tr>
          </thead>
          <tbody>
            {visible.map((row) => (
              <tr
                key={row.cardId}
                data-card-row={row.cardId}
                className="border-b border-border-subtle last:border-b-0"
              >
                <td className="px-3 py-2 text-[11px] text-fg">
                  <div className="font-mono">{row.cardId}</div>
                  {row.title ? (
                    <div data-card-title={row.cardId} className="mt-0.5 max-w-56 font-sans">
                      {row.title}
                    </div>
                  ) : null}
                  {row.category ? (
                    <div className="mt-0.5 text-fg-subtle">{categoryLabel(row.category)}</div>
                  ) : null}
                </td>
                <StatCell cell={row.offered} name="offered" />
                <StatCell cell={row.adopted} name="adopted" />
                <StatCell cell={row.refuted} name="refuted" />
                <StatCell cell={row.invalid} name="invalid" />
                <StatCell cell={row.meanDelta} name="mean_delta" />
                <StatCell cell={row.statN} name="stat_n" />
                <td className="px-3 py-2 text-xs text-fg-muted">
                  {row.adoptedIterations.length > 0 ? row.adoptedIterations.join('、') : '未记录'}
                </td>
                <td className="px-3 py-2">
                  {row.adoptedNodeIds.length === 0 ? (
                    <span className="text-xs text-fg-subtle">无</span>
                  ) : (
                    <ul className="flex flex-wrap gap-1">
                      {row.adoptedNodeIds.map((nodeId) => (
                        <li key={nodeId}>
                          <button
                            type="button"
                            data-node-link={nodeId}
                            disabled={!onOpenNode}
                            onClick={() => onOpenNode?.(nodeId)}
                            className="rounded-card border border-border-subtle bg-surface-muted px-1.5 py-0.5 font-mono text-[10px] text-brand-600 hover:underline disabled:text-fg-subtle disabled:no-underline"
                          >
                            {nodeId}
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                </td>
                <td className="px-3 py-2">
                  <select
                    aria-label={`${row.cardId} 的本地标记`}
                    data-label-select={row.cardId}
                    value={row.label ?? ''}
                    onChange={(event) => {
                      const value = event.target.value;
                      onLabelChange(row.cardId, value === '' ? null : (value as CardLabel));
                    }}
                    className="rounded-card border border-border-subtle bg-surface px-1.5 py-0.5 text-[11px] text-fg"
                  >
                    <option value="">无标记</option>
                    {CARD_LABELS.map((label) => (
                      <option key={label} value={label}>
                        {label}
                      </option>
                    ))}
                  </select>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {rows.length > 0 && visible.length === 0 ? (
        <p className="text-xs text-fg-subtle">
          没有卡片符合当前筛选条件。
          <button
            type="button"
            onClick={() => onFilterChange(EMPTY_CARD_FILTER)}
            className="ml-1 text-brand-600 underline"
          >
            清空筛选
          </button>
        </p>
      ) : null}
    </div>
  );
}
