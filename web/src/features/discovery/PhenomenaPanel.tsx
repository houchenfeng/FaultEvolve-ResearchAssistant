/**
 * 现象与 claim 检验面板（TODO 6.2 / PRD 12.2）。
 *
 * 八项要求逐条落到行内的位置：
 *  - condition / feature / outcome / scope / falsifier —— `discovery.claims[]` 的散文
 *  - effect / CI —— `discovery.phenomena[].payload`（`ClaimTestResult`）
 *  - grade / status —— 两处都有，`phenomena[].grade` 优先
 *  - sandbox error —— `claims[]` 里 `status='sandbox_failed'` 那行的 `error`
 *
 * ## 三条必须显式说出来的话
 *
 * 1. **散文可能整段不可得**。引擎在评分时用检验结果覆盖了 payload，所以进过
 *    评分/沙箱失败的 claim 散文在任何制品里都没了。行内显示「未记录」，页面
 *    顶部一条横幅说明**原因**（`proseLossNote`）—— 不是"这一页没做好"。
 * 2. **沙箱失败要被看见**，即使它没有产生任何 phenomena 行（`sandboxNote`）。
 * 3. **现象有、claim 行没有** 是一种真实的数据不完整（`orphanCount`）。
 *
 * 三条都不影响「不编内容」这条底线：拿不到就写「未记录」。
 */
import { EmptyState } from '@/components/states/EmptyState';
import { StatusBadge, type BadgeTone } from '@/components/ui/StatusBadge';
import { buildPhenomenaView, phenomenaEmptyReason, proseLossNote, sandboxNote } from '@/features/discovery/claim-logic';
import type { CardTone, FieldView } from '@/features/discovery/card-logic';
import type { DiscoveryResponse } from '@/features/discovery/types';

function toBadgeTone(tone: CardTone): BadgeTone {
  switch (tone) {
    case 'positive':
      return 'success';
    case 'warning':
      return 'warning';
    case 'brand':
      return 'brand';
    default:
      return 'neutral';
  }
}

/** 页面级横幅：把「为什么不完整」讲清楚，而不是让用户对着空白猜。 */
function Banner({
  tone,
  children,
}: {
  tone: 'info' | 'warning';
  children: React.ReactNode;
}) {
  const toneClass =
    tone === 'warning'
      ? 'border-warning-500/30 bg-warning-50 text-warning-700 dark:border-warning-500/40 dark:bg-warning-500/10 dark:text-warning-500'
      : 'border-info-500/30 bg-info-50 text-info-700 dark:border-info-500/40 dark:bg-info-500/10 dark:text-info-500';
  return (
    <div role="status" className={`rounded-panel border p-2.5 text-[11px] ${toneClass}`}>
      {children}
    </div>
  );
}

function Field({ label, view }: { label: string; view: FieldView }) {
  const placeholder = view.state !== 'recorded';
  return (
    <div className="flex flex-col gap-0.5">
      <dt className="text-[10px] text-fg-subtle">{label}</dt>
      <dd
        className={`text-[11px] ${placeholder ? 'text-fg-subtle italic' : 'text-fg'}`}
        data-field-state={view.state}
      >
        {view.text}
      </dd>
    </div>
  );
}

export interface PhenomenaPanelProps {
  discovery: DiscoveryResponse;
}

export function PhenomenaPanel({ discovery }: PhenomenaPanelProps) {
  const view = buildPhenomenaView(discovery);
  const emptyReason = phenomenaEmptyReason(view);
  const proseNote = proseLossNote(view);
  const sandboxBanner = sandboxNote(view);

  const enabledText =
    view.enabled === null ? '未记录' : view.enabled ? '已启用' : '未启用';
  const enabledTone: BadgeTone =
    view.enabled === null ? 'neutral' : view.enabled ? 'success' : 'neutral';

  return (
    <div className="flex flex-col gap-3" data-testid="phenomena-panel">
      <div className="flex flex-wrap items-center gap-2 fe-card-panel-muted px-3 py-2">
        <span className="text-[11px] font-medium text-fg">假设检验</span>
        <StatusBadge tone={enabledTone}>知识发现 {enabledText}</StatusBadge>
        <span className="text-[11px] text-fg-muted">
          现象 {view.rows.length} 条
          {view.sandboxFailedCount > 0 ? ` · 沙箱失败 ${view.sandboxFailedCount}` : ''}
          {view.orphanCount > 0 ? ` · 缺少主张行 ${view.orphanCount}` : ''}
        </span>
        <span className="flex-1" />
        <span className="text-[10px] text-fg-subtle">
          现象文件 {view.phenomenaState ?? '未记录'}
        </span>
      </div>

      {sandboxBanner ? <Banner tone="warning">{sandboxBanner}</Banner> : null}

      {proseNote ? (
        <Banner tone="info">
          {proseNote}
          <span className="mt-0.5 block text-fg-muted">
            这是引擎侧的覆盖式写入，本页只能如实显示「未记录」，无法还原。
          </span>
        </Banner>
      ) : null}

      {view.orphanCount > 0 ? (
        <Banner tone="warning">
          有 {view.orphanCount} 条现象找不到对应的主张行 ——
          现象文件与主张表不同步，这些行只能显示检验结果，散文一律「未记录」。
        </Banner>
      ) : null}

      {emptyReason ? (
        <EmptyState
          title="没有可展示的现象"
          reason={emptyReason}
          nextStep="换一个启用了知识发现的运行，或查看该运行的事件流确认发现阶段是否跑到"
        />
      ) : (
        <ul className="flex list-none flex-col gap-3 p-0">
          {view.rows.map((row, index) => (
            <li key={`${row.claimId || 'no-claim'}-${index}`}>
              <article
                data-claim-id={row.claimId}
                data-has-claim-row={row.hasClaimRow ? 'true' : 'false'}
                className="fe-card-panel p-3"
              >
                <header className="flex flex-wrap items-center gap-2">
                  <h3 className="tabular font-mono text-xs font-semibold text-fg" title={row.claimId}>
                    {row.claimId ? row.claimId.slice(0, 10) : '（无主张 id）'}
                  </h3>
                  <StatusBadge tone={toBadgeTone(row.grade.tone)}>{row.grade.label}</StatusBadge>
                  <StatusBadge tone={toBadgeTone(row.status.tone)} showDot={false}>
                    {row.status.text}
                  </StatusBadge>
                  <span className="flex-1" />
                  <span className="text-[10px] text-fg-subtle">{row.grade.reason}</span>
                </header>

                <p className="mt-1.5 text-[12px] font-medium text-fg">
                  {row.title.state === 'recorded' ? (
                    row.title.text
                  ) : (
                    <span className="text-fg-subtle italic">{row.title.text}（主张标题）</span>
                  )}
                </p>

                <div className="mt-2 flex flex-wrap items-baseline gap-2">
                  <span
                    className={`tabular text-[12px] ${
                      row.effect.crossesZero === false ? 'text-fg font-medium' : 'text-fg-muted'
                    }`}
                    data-testid="effect-verdict"
                  >
                    {row.effect.text}
                  </span>
                  <span className="text-[10px] text-fg-subtle">{row.effect.reason}</span>
                </div>

                <div className="mt-1.5">
                  <Field label="检验统计（样本 / p / e / 划分）" view={row.statistics} />
                </div>

                <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1.5 border-t border-border-subtle pt-2 sm:grid-cols-3">
                  <Field label="condition" view={row.condition} />
                  <Field label="feature" view={row.feature} />
                  <Field label="outcome" view={row.outcome} />
                  <Field label="scope" view={row.scope} />
                  <Field label="falsifier" view={row.falsifier} />
                  <Field
                    label="状态说明"
                    view={{ state: 'recorded', text: row.status.note, tone: 'muted' }}
                  />
                </dl>

                {row.sandbox ? (
                  <div
                    className="mt-2 rounded-card border border-warning-500/30 bg-warning-50 px-2 py-1.5 text-[11px] dark:border-warning-500/40 dark:bg-warning-500/10"
                    data-testid="sandbox-failure"
                  >
                    <div className="font-medium text-warning-700 dark:text-warning-500">
                      沙箱错误
                    </div>
                    <div className="mt-0.5 text-fg-muted">{row.sandbox.reason}</div>
                    <pre className="mt-1 overflow-x-auto whitespace-pre-wrap break-all font-mono text-[10px] text-fg">
                      {row.sandbox.detail.text}
                    </pre>
                  </div>
                ) : null}

                {!row.hasClaimRow ? (
                  <p className="mt-2 text-[10px] text-warning-500">
                    这条现象在主张表里没有对应行，散文与状态均不可得。
                  </p>
                ) : null}
              </article>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
