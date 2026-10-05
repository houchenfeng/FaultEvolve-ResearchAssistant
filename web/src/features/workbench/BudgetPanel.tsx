/**
 * 预算与算力面板（TODO 5.7 / PRD §9.7）。
 *
 * 核心是 `total_tokens` 的分项占比。**分项之间不强行归一**：后端可能没给全，
 * 少了一项就意味着"这一类没有消耗"或者"数据缺失"，两种情况在界面上必须能区分
 * —— 所以缺失显示「未记录」而不是 0。
 */
import type { RunBudgetResponse } from '@/generated/api';

interface TokenSlice {
  key: keyof RunBudgetResponse;
  label: string;
  color: string;
}

const TOKEN_SLICES: TokenSlice[] = [
  { key: 'generate_tokens', label: '生成', color: 'var(--color-brand-500)' },
  { key: 'reflect_tokens', label: '反思', color: 'var(--color-brand-300)' },
  { key: 'repair_tokens', label: '修复', color: 'var(--color-warning-500)' },
  { key: 'knowledge_tokens', label: '知识卡', color: 'var(--color-success-500)' },
  { key: 'crossover_tokens', label: '交叉', color: 'var(--color-info-500)' },
  { key: 'discovery_tokens', label: '发现', color: 'var(--color-neutral-500)' },
  { key: 'tournament_tokens', label: '赛制', color: 'var(--color-neutral-500)' },
  { key: 'self_fix_tokens', label: '自修复', color: 'var(--color-danger-500)' },
];

function num(value: number | null | undefined): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

/**
 * token 数量的紧凑显示。
 *
 * 参数**不允许** null：调用点在渲染前已经过滤掉了"未记录"的分项，
 * 让这个函数也接受 null 只会逼每个调用点各自处理一遍。
 */
function formatTokens(value: number): string {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(2)}M`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(1)}k`;
  return String(value);
}

export interface BudgetPanelProps {
  budget: RunBudgetResponse;
}

export function BudgetPanel({ budget }: BudgetPanelProps) {
  const total = num(budget.total_tokens);
  const slices = TOKEN_SLICES.map((slice) => ({
    ...slice,
    value: num(budget[slice.key] as number | null | undefined),
  }));
  // 只有有值的分项参与占比计算；缺失的不进分母，否则占比会偏低而看不出"缺数据"。
  // 这里显式建一个「必有值」的数组而不是靠类型守卫收窄 —— 守卫在这个推断链上
  // 收不窄（slice.value 仍是 number | null），反而更难读。
  const known: Array<{ label: string; color: string; value: number }> = [];
  for (const slice of slices) {
    if (slice.value !== null) known.push({ label: slice.label, color: slice.color, value: slice.value });
  }
  let knownSum = 0;
  for (const slice of known) knownSum += slice.value;

  return (
    <div className="flex flex-col gap-3 px-3 py-2" data-testid="budget-panel">
      <div className="flex items-baseline gap-3">
        <div>
          <div className="text-[11px] text-fg-muted">总 token</div>
          <div className="tabular text-[18px] font-medium text-fg">
            {total === null ? '未记录' : total.toLocaleString()}
          </div>
        </div>
        <div className="text-[11px] text-fg-muted">
          {budget.budget_stop_reason ? (
            <>
              停止原因：
              <span className="text-warning-500">{budget.budget_stop_reason}</span>
            </>
          ) : total === null ? (
            '未记录'
          ) : (
            '未触发预算停止'
          )}
        </div>
      </div>

      {total !== null ? (
        <div className="flex h-2 w-full overflow-hidden rounded-pill bg-surface-muted">
          {known.map((slice) => (
            <div
              key={slice.label}
              style={{
                width: `${knownSum === 0 ? 0 : (slice.value / knownSum) * 100}%`,
                background: slice.color,
              }}
              title={`${slice.label} ${slice.value.toLocaleString()} token`}
            />
          ))}
        </div>
      ) : null}

      <table className="text-[11px]">
        <tbody>
          {slices.map((slice) => (
            <tr key={slice.label} className="border-t border-border-subtle">
              <td className="w-20 py-1">
                <span className="inline-flex items-center gap-1.5">
                  <span className="size-1.5 rounded-full" style={{ background: slice.color }} />
                  {slice.label}
                </span>
              </td>
              <td className="tabular py-1 text-right text-fg">
                {slice.value === null ? (
                  <span className="text-fg-subtle">未记录</span>
                ) : (
                  formatTokens(slice.value)
                )}
              </td>
              <td className="tabular w-16 py-1 text-right text-fg-muted">
                {slice.value === null || total === null || total === 0
                  ? '—'
                  : `${((slice.value / total) * 100).toFixed(1)}%`}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {total !== null && knownSum < total ? (
        <div className="rounded-card border border-border-subtle bg-surface-muted px-2 py-1 text-[11px] text-fg-muted">
          已记录的分项合计 {knownSum.toLocaleString()}，占总 token 的{' '}
          {((knownSum / total) * 100).toFixed(1)}%。差额 {((total - knownSum) * 100).toFixed(1)}% 属于
          未单独计量的部分。
        </div>
      ) : null}

      <div className="grid grid-cols-2 gap-x-4 gap-y-0.5 border-t border-border-subtle pt-2 text-[11px]">
        <Derived label="每 ROS 点分摊" value={budget.tokens_per_ros_point} />
        <Derived label="每分提升 token" value={budget.tokens_per_score_gain} />
        <Derived label="LLM 总延迟" value={budget.total_llm_latency_ms} unit="ms" />
        <Derived label="评估总耗时" value={budget.total_eval_time_s} unit="s" />
        <Derived label="墙钟时间" value={budget.wall_time_s} unit="s" />
        <Derived label="冒烟总耗时" value={budget.smoke_time_s_total} unit="s" />
        <Derived label="知识卡 token 占比" value={budget.knowledge_token_share} unit="%" />
        <Derived label="发现 token 占比" value={budget.discovery_token_share} unit="%" />
      </div>

      {budget.stage_cap_hits && Object.keys(budget.stage_cap_hits).length > 0 ? (
        <div className="text-[11px]">
          <div className="mb-0.5 text-fg-muted">阶段上限触发</div>
          {Object.entries(budget.stage_cap_hits).map(([stage, count]) => (
            <span key={stage} className="mr-2 text-warning-500">
              {stage} × {String(count)}
            </span>
          ))}
        </div>
      ) : null}

      {budget.budget_stop_reason ? (
        <div className="rounded-card border border-warning-500/30 bg-warning-50 px-2 py-1 text-[11px] text-warning-700 dark:bg-warning-500/10 dark:text-warning-500">
          本次运行因预算停止：{budget.budget_stop_reason}
        </div>
      ) : null}
    </div>
  );
}

function Derived({
  label,
  value,
  unit,
}: {
  label: string;
  value: number | null | undefined;
  unit?: string;
}) {
  const numeric = num(value);
  return (
    <div className="flex justify-between gap-2">
      <span className="text-fg-muted">{label}</span>
      <span className="tabular text-fg">
        {numeric === null ? '未记录' : `${numeric.toLocaleString()}${unit ? ` ${unit}` : ''}`}
      </span>
    </div>
  );
}
