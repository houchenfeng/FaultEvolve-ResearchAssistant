/**
 * 节点详情抽屉（TODO 5.3 / PRD §10.3）：概览、指标、代码差异、知识与记忆、事件与成本。
 *
 * **代码只读**（PRD §10.3 明确"禁止在页面直接编辑并覆盖节点代码"）——
 * 这里没有 textarea、没有 contentEditable，只有一个复制按钮。
 * diff 由后端算好（`NodeDetailResponse.code_diff`），前端不装 diff 库。
 */
import { useState } from 'react';

import type { EventResponse, NodeDetailResponse, TreeNodeDto } from '@/generated/api';
import { StatusBadge } from '@/components/ui/StatusBadge';
import { explainSignificance } from '@/features/workbench/significance';
import { shortId } from '@/features/workbench/tree-adapter';
import {
  buildReflections,
  repairBookkeeping,
  type ReflectionEntry,
} from '@/features/workbench/reflection';

const TABS = [
  { id: 'overview', label: '概览' },
  { id: 'metrics', label: '指标' },
  { id: 'code', label: '代码差异' },
  { id: 'memory', label: '知识与记忆' },
  { id: 'cost', label: '事件与成本' },
] as const;

type TabId = (typeof TABS)[number]['id'];

export interface NodeDrawerProps {
  detail: NodeDetailResponse;
  /** 该节点相关的事件（由父组件从事件流里筛好）。 */
  events: EventResponse[];
  onClose: () => void;
  /** 点击第二父/父节点时跳转。 */
  onNavigate?: (nodeId: string) => void;
  /**
   * 整棵树的节点索引（id → 节点）。
   *
   * 「修复来源」那一行要显示**失败节点**的 `repair_count` / `repair_exhausted`
   * —— 引擎把这两个字段写在被修的那一侧（`engine.py:2009` / `engine.py:2006`），
   * 而 `repair_parent_id` 指针在修复者身上，只盯着当前节点读一定读到空。
   * 没有这份索引时退回读当前节点自己的字段（老行为），不会崩。
   */
  nodeById?: ReadonlyMap<string, TreeNodeDto>;
}

/** 「未记录」而不是 0 / 0.00 —— PRD §10.3 明确要求。 */
function MetricValue({ value, digits = 4 }: { value: number | null | undefined; digits?: number }) {
  if (value === null || value === undefined) {
    return <span className="text-fg-subtle">未记录</span>;
  }
  return <span className="tabular text-fg">{value.toFixed(digits)}</span>;
}

/**
 * 从开放字典 `metric` 里取数值。
 *
 * `metric` 是 evaluator 的自由映射（契约里就是 `[key: string]: unknown`），
 * 里面的值不保证是数字 —— 直接 `.toFixed()` 会在字符串上报错。
 */
function asNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex gap-2 py-1 text-[12px]">
      <span className="w-24 shrink-0 text-fg-muted">{label}</span>
      <span className="min-w-0 flex-1 break-words">{children}</span>
    </div>
  );
}

export function NodeDrawer({
  detail,
  events,
  onClose,
  onNavigate,
  nodeById,
}: NodeDrawerProps) {
  const [tab, setTab] = useState<TabId>('overview');
  const { node, evaluation, artifact } = detail;
  // 修复记账在被修的那一侧，见 NodeDrawerProps.nodeById 的说明。
  const repairSource = node.repair_parent_id
    ? (nodeById?.get(node.repair_parent_id) ?? null)
    : null;
  const repair = repairBookkeeping(repairSource, node);
  const verdict = explainSignificance(node);
  const delta = evaluation?.delta_score ?? node.delta_score;
  const noise = evaluation?.noise_delta ?? node.noise_delta;
  // 契约里这些数组是可选的（后端可能不填），这里一次性归一，
  // 免得下面每个使用点都写 `?? []` —— 漏一个就是运行时 undefined.length。
  const adopted = detail.adopted_card_ids ?? [];
  const offered = node.offered_card_ids ?? [];
  const injected = adopted.filter((id) => !offered.includes(id));
  const insightList = detail.insights ?? [];
  const relatedEvents = events.filter((event) =>
    (event.payload as Record<string, unknown> | undefined)?.node_id === node.id,
  );
  const reflections = buildReflections(relatedEvents);

  return (
    <aside
      className="flex w-[420px] shrink-0 flex-col border-l border-border-subtle bg-surface"
      data-testid="node-drawer"
    >
      <header className="flex items-start gap-2 border-b border-border-subtle px-3 py-2">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <span className="text-[13px] font-medium text-fg">{shortId(node.id)}</span>
            {node.is_best ? <StatusBadge tone="brand">当前最优</StatusBadge> : null}
            <StatusBadge tone={node.status === 'done' ? 'success' : 'neutral'}>
              {node.status}
            </StatusBadge>
          </div>
          <div className="tabular truncate text-[11px] text-fg-subtle" title={node.id}>
            {node.id}
          </div>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="关闭详情"
          className="rounded-card border border-border-subtle px-1.5 py-0.5 text-[11px] text-fg-muted hover:border-brand-500 hover:text-brand-600"
        >
          关闭
        </button>
      </header>

      <nav className="flex gap-0.5 border-b border-border-subtle px-2 py-1">
        {TABS.map((item) => (
          <button
            key={item.id}
            type="button"
            onClick={() => setTab(item.id)}
            aria-current={tab === item.id}
            className={`rounded-card px-2 py-0.5 text-[11px] ${
              tab === item.id
                ? 'bg-brand-50 text-brand-600 dark:bg-brand-500/10 dark:text-brand-300'
                : 'text-fg-muted hover:text-fg'
            }`}
          >
            {item.label}
          </button>
        ))}
      </nav>

      <div className="min-h-0 flex-1 overflow-y-auto px-3 py-2">
        {tab === 'overview' ? (
          <div>
            <div className="mb-2 rounded-card border border-border-subtle bg-surface-muted px-2 py-1.5">
              <div className="flex items-center gap-1.5 text-[12px]">
                <span className="font-medium">{verdict.label}</span>
                <span className="text-fg-muted">{verdict.reason}</span>
              </div>
            </div>
            <Row label="假设状态">{node.hypothesis_status}</Row>
            <Row label="父节点">
              {node.parent_id ? (
                <NodeLink nodeId={node.parent_id} onNavigate={onNavigate} />
              ) : (
                <span className="text-fg-subtle">无（初始节点）</span>
              )}
            </Row>            <Row label="第二父节点">
              {(node.second_parent_ids ?? []).length > 0 ? (
                <span className="flex flex-wrap gap-1">
                  {(node.second_parent_ids ?? []).map((id) => (
                    <NodeLink key={id} nodeId={id} onNavigate={onNavigate} />
                  ))}
                </span>
              ) : (
                <span className="text-fg-subtle">无（非交叉生成）</span>
              )}
            </Row>
            <Row label="分支">{node.branch_id || '—'}</Row>
            <Row label="深度">{node.depth}</Row>
            <Row label="算子">{node.operator}</Row>
            <Row label="候选意图">{node.intent || <span className="text-fg-subtle">未记录</span>}</Row>
            <Row label="候选假设">
              {artifact?.hypothesis || <span className="text-fg-subtle">未记录</span>}
            </Row>
            <Row label="父节点分数">
              <ParentScore parentId={node.parent_id} />
            </Row>
            <Row label="当前分数">
              <MetricValue value={evaluation?.combined_score ?? node.score} />
            </Row>
            <Row label="Δ / 噪声带">
              <MetricValue value={delta} /> / <MetricValue value={noise} />
            </Row>
            <Row label="超出噪声带">
              {node.within_noise_band === null || node.within_noise_band === undefined ? (
                <span className="text-fg-subtle">无法判断</span>
              ) : node.within_noise_band ? (
                <span>是（噪声内，不能作为证据）</span>
              ) : (
                <span>否（有效改进）</span>
              )}
            </Row>
            {node.repair_parent_id ? (
              <Row label="修复来源">
                <NodeLink nodeId={node.repair_parent_id} onNavigate={onNavigate} />
                {repair.count !== null ? `（重试 ${repair.count} 次）` : ''}
                {repair.exhausted ? '（已耗尽）' : ''}
              </Row>
            ) : null}
            {node.error_class ? <Row label="错误分类">{node.error_class}</Row> : null}
          </div>
        ) : null}

        {tab === 'metrics' ? (
          <div>
            <Row label="validity">
              <MetricValue value={evaluation?.validity} />
            </Row>
            <Row label="combined_score">
              <MetricValue value={evaluation?.combined_score} />
            </Row>
            <Row label="cost_time">
              {evaluation?.cost_time === null || evaluation?.cost_time === undefined ? (
                <span className="text-fg-subtle">未记录</span>
              ) : (
                <span className="tabular">{evaluation.cost_time.toFixed(3)} s</span>
              )}
            </Row>
            <Row label="bootstrap 波动">
              {/* bootstrap 不在契约的固定字段里（各任务 evaluator 自定），
                  所以它要么在 metric 字典中，要么就是没有 —— 两种都显示「未记录」。 */}
              <MetricValue value={asNumber(evaluation?.metric?.bootstrap)} />
            </Row>
            {evaluation?.error_info ? (
              <Row label="评估错误">
                <span className="text-danger-500">{evaluation.error_info}</span>
              </Row>
            ) : null}
            <div className="mt-2 border-t border-border-subtle pt-2">
              <div className="mb-1 text-[11px] text-fg-muted">evaluator 返回的全部指标</div>
              {evaluation?.metric && Object.keys(evaluation.metric).length > 0 ? (
                Object.entries(evaluation.metric).map(([key, value]) => (
                  <Row key={key} label={key}>
                    {typeof value === 'number' ? (
                      <MetricValue value={value} />
                    ) : (
                      <span className="break-all text-[11px]">{String(value)}</span>
                    )}
                  </Row>
                ))
              ) : (
                <div className="text-[11px] text-fg-subtle">该节点没有额外指标</div>
              )}
            </div>
          </div>
        ) : null}

        {tab === 'code' ? (
          <div>
            <div className="mb-1 flex items-center justify-between">
              <span className="text-[11px] text-fg-muted">当前候选代码（只读）</span>
              {artifact?.code ? (
                <button
                  type="button"
                  onClick={() => void navigator.clipboard?.writeText(artifact.code ?? '')}
                  className="rounded-card border border-border-subtle px-1.5 py-0.5 text-[11px] text-fg-muted hover:border-brand-500 hover:text-brand-600"
                >
                  复制
                </button>
              ) : null}
            </div>
            {artifact?.code ? (
              <pre className="max-h-52 overflow-auto rounded-card border border-border-subtle bg-surface-muted p-2 text-[11px] leading-relaxed">
                <code>{artifact.code}</code>
              </pre>
            ) : (
              <div className="text-[11px] text-fg-subtle">该节点没有代码制品（{artifact?.state ?? '未知'}）</div>
            )}

            <div className="mt-3 mb-1 text-[11px] text-fg-muted">
              与主父节点的差异
              {detail.code_diff_truncated ? '（已截断）' : ''}
            </div>
            {detail.code_diff ? (
              <pre className="max-h-64 overflow-auto rounded-card border border-border-subtle bg-surface-muted p-2 text-[11px] leading-relaxed">
                <code>{detail.code_diff}</code>
              </pre>
            ) : (
              <div className="text-[11px] text-fg-subtle">没有可显示的差异（无父节点或缺少代码）</div>
            )}
          </div>
        ) : null}

        {tab === 'memory' ? (
          <div>
            <Row label="采纳的知识卡">
              {adopted.length > 0 ? (
                <span className="flex flex-wrap gap-1">
                  {adopted.map((id) => (
                    <span
                      key={id}
                      className="rounded-pill bg-brand-50 px-1.5 py-px text-[11px] text-brand-600 dark:bg-brand-500/10 dark:text-brand-300"
                    >
                      {id}
                    </span>
                  ))}
                </span>
              ) : (
                <span className="text-fg-subtle">未采纳任何卡</span>
              )}
            </Row>
            <Row label="本分支投放">
              {offered.length > 0 ? (
                <span>
                  {offered.length} 张
                  <span className="ml-1 text-[11px] text-fg-subtle">
                    （{offered.slice(0, 8).join('、')}
                    {offered.length > 8 ? ' …' : ''}）
                  </span>
                </span>
              ) : (
                <span className="text-fg-subtle">本分支没有投放记录</span>
              )}
            </Row>
            {injected.length > 0 ? (
              <div className="mt-1 rounded-card border border-warning-500/30 bg-warning-50 px-2 py-1 text-[11px] text-warning-700 dark:bg-warning-500/10 dark:text-warning-500">
                其中 {injected.join('、')} 来自知识库预置注入，没有按轮次投放记录。
              </div>
            ) : null}
            <Row label="洞察">
              {insightList.length > 0 ? insightList.join('、') : <span className="text-fg-subtle">无</span>}
            </Row>

            <div className="mt-2 border-t border-border-subtle pt-2">
              <div className="mb-1 text-[11px] text-fg-muted">三层反思</div>
              {reflections.every((entry) => entry.event === null) ? (
                <div className="text-[11px] text-fg-subtle">该节点没有反思记录</div>
              ) : (
                reflections.map((entry) => <ReflectionRow key={entry.layer} entry={entry} />)
              )}
            </div>
          </div>
        ) : null}

        {tab === 'cost' ? (
          <div>
            <Row label="LLM 调用次数">
              {detail.llm_call_count === null || detail.llm_call_count === undefined ? (
                <span className="text-fg-subtle">未记录</span>
              ) : (
                <span className="tabular">{detail.llm_call_count}</span>
              )}
            </Row>
            <Row label="LLM tokens">
              {detail.llm_tokens === null || detail.llm_tokens === undefined ? (
                <span className="text-fg-subtle">未记录</span>
              ) : (
                <span className="tabular">{detail.llm_tokens}</span>
              )}
            </Row>
            <Row label="评估时长">
              {evaluation?.cost_time === null || evaluation?.cost_time === undefined ? (
                <span className="text-fg-subtle">未记录</span>
              ) : (
                <span className="tabular">{evaluation.cost_time.toFixed(3)} s</span>
              )}
            </Row>
            {/* 修复者自己身上没有重试计数（引擎记在被修的那一侧），这行会显示
                一个毫无意义的 0，跟上面「修复来源」里的次数自相矛盾。它的记账
                已经在「修复来源」里以被修节点为准显示过了，这里就不重复。 */}
            {node.repair_parent_id ? null : (
              <Row label="修复重试">
                {node.repair_count === null || node.repair_count === undefined ? (
                  <span className="text-fg-subtle">未记录</span>
                ) : (
                  <span className="tabular">
                    {node.repair_count}
                    {node.repair_attempted ? '（已尝试）' : ''}
                    {node.repair_exhausted ? '（已耗尽）' : ''}
                  </span>
                )}
              </Row>
            )}

            <div className="mt-2 border-t border-border-subtle pt-2">
              <div className="mb-1 text-[11px] text-fg-muted">
                相关事件（{relatedEvents.length}）
              </div>
              {relatedEvents.length === 0 ? (
                <div className="text-[11px] text-fg-subtle">没有与该节点直接关联的事件</div>
              ) : (
                <ul className="flex flex-col gap-0.5">
                  {relatedEvents.map((event, index) => (
                    <li
                      key={event.id ?? `${event.type}-${index}`}
                      className="flex gap-1.5 text-[11px]"
                    >
                      {/* 契约里 ts 是可选的（引擎没写时间戳就是空串），不能假设它有值。 */}
                      <span className="shrink-0 text-fg-subtle">
                        {(event.ts ?? '').slice(11, 19) || '--:--:--'}
                      </span>
                      <span className="text-fg">{event.type}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            {detail.log_excerpt ? (
              <div className="mt-2">
                <div className="mb-1 text-[11px] text-fg-muted">日志片段（{detail.log_state}）</div>
                <pre className="max-h-40 overflow-auto rounded-card border border-border-subtle bg-surface-muted p-2 text-[11px]">
                  <code>{detail.log_excerpt}</code>
                </pre>
              </div>
            ) : null}
          </div>
        ) : null}
      </div>
    </aside>
  );
}

function NodeLink({ nodeId, onNavigate }: { nodeId: string; onNavigate?: (id: string) => void }) {
  if (!onNavigate) {
    return <span className="tabular text-fg">{shortId(nodeId)}</span>;
  }
  return (
    <button
      type="button"
      onClick={() => onNavigate(nodeId)}
      className="tabular text-brand-600 underline-offset-2 hover:underline dark:text-brand-300"
    >
      {shortId(nodeId)}
    </button>
  );
}

/**
 * 父节点分数。
 *
 * 它属于**另一个节点**，要再发一次请求才能拿到。当前抽屉只持有一个节点的详情，
 * 所以这里不编造数值，只告诉用户去哪看 —— 这比显示一个假的 0.00 诚实得多。
 */
function ParentScore({ parentId }: { parentId: string | null | undefined }) {
  if (!parentId) return <span className="text-fg-subtle">无父节点</span>;
  return (
    <span className="text-fg-subtle" title="父节点分数需在树中点击父节点查看">
      见父节点 {shortId(parentId)}
    </span>
  );
}

function ReflectionRow({ entry }: { entry: ReflectionEntry }) {
  return (
    <div className="mb-1.5">
      <div className="flex items-center gap-1.5 text-[11px]">
        <span className="text-fg">{entry.label}</span>
        {entry.event ? (
          <span className="text-fg-subtle">{entry.ts.slice(11, 19)}</span>
        ) : (
          <span className="text-fg-subtle">（未发生）</span>
        )}
      </div>
      <div className="text-[11px] leading-relaxed text-fg-muted">
        {entry.text ?? (entry.event ? '该事件没有文本内容' : '')}
      </div>
    </div>
  );
}
