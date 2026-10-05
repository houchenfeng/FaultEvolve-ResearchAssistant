/**
 * 机制辩论赛（TODO 6.3 / PRD 12.3）。
 *
 * ## 最要紧的一条：论点与裁决必须分区
 *
 * TODO 6.3 末尾那句「必须把 Qwen 论点与数据裁决分区显示」不是排版偏好，
 * 而是**归因正确性**的要求：机制标题、`llm_rival` 这些是模型生成的**假设**，
 * 而 `matches[].supports`、`mechanisms[].status`、`certificates[]` 是**数据
 * 给出的结论**。两者混在一列里，读者会以为"标题写了"就等于"数据支持了"。
 *
 * 所以本组件把页面切成两个显式命名的分区：
 *
 * | 分区 | `data-zone` | 内容 |
 * |---|---|---|
 * | 模型论点（Qwen 生成，未经数据裁决） | `arguments` | `theories[]` 按 `role` 分区 |
 * | 数据裁决（预注册检验 + 统计证据） | `verdicts` | `matches[]` / `status` / `certificates[]` |
 *
 * ## 六个阶段与数据的对应
 *
 * 1. 主张 —— `role='claim'`
 * 2. 对手机制 —— `role='llm_rival'`
 * 3. 正反论点 —— `matches[].supports`（`'a'`/`'b'`/`'none'`）配 `decisive`
 * 4. 预注册检验 —— `matches[].test_type` + `certificates[].test_type`
 * 5. 数据裁决 —— `mechanisms[].status`
 * 6. 证书 / 否证记忆 —— `certificates[]`
 *
 * ## 为什么机制卡上不显示 status
 *
 * `status` 是**裁决**结果。若把它印在论点区的卡片上，就等于把"数据结论"
 * 混进了"模型假设"。所以机制卡只讲它是谁、提了什么，裁决一律去裁决区看。
 */
import type { ReactNode } from 'react';

import { EmptyState } from '@/components/states/EmptyState';
import { StatusBadge, type BadgeTone } from '@/components/ui/StatusBadge';
import type { CardTone, FieldView } from '@/features/discovery/card-logic';
import {
  buildTournamentView,
  matchVerdict,
  mechanismLabel,
  mechanismStatusVerdict,
  tournamentEmptyReason,
  type MechanismGroup,
} from '@/features/discovery/tournament-logic';
import type {
  DiscoveryResponse,
  MatchPayload,
  MechanismPayload,
} from '@/features/discovery/types';

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

const shortId = (id: string) => (id.length > 10 ? id.slice(0, 10) : id || '未记录');

/** 六个阶段的固定标题，顺序即 TODO 6.3 的顺序。 */
const STAGE_TITLES: Record<number, string> = {
  1: '1. 主张',
  2: '2. 对手机制',
  3: '3. 正反论点',
  4: '4. 预注册检验',
  5: '5. 数据裁决',
  6: '6. 证书 / 否证记忆',
};

function Stage({
  n,
  zone,
  children,
  hint,
}: {
  n: number;
  zone: 'arguments' | 'verdicts';
  children: ReactNode;
  hint?: string;
}) {
  return (
    <section data-stage={n} data-zone={zone} className="flex flex-col gap-2">
      <div className="flex flex-wrap items-baseline gap-2">
        <h3 className="text-[12px] font-semibold text-fg">{STAGE_TITLES[n]}</h3>
        {hint ? <span className="text-[10px] text-fg-subtle">{hint}</span> : null}
      </div>
      {children}
    </section>
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

/** 一条机制 —— 只讲"它是什么"，不讲"数据怎么判它"。 */
function MechanismCard({ mechanism }: { mechanism: MechanismPayload }) {
  const label = mechanismLabel(mechanism);
  const predictions = Object.entries(mechanism.predictions ?? {});
  const edges = mechanism.edges ?? [];
  const nodes = mechanism.nodes ?? [];

  return (
    <article
      data-mechanism-id={mechanism.id ?? ''}
      data-mechanism-role={mechanism.role ?? 'none'}
      className="rounded-card border border-border-subtle bg-surface-muted p-2.5"
    >
      <header className="flex flex-wrap items-center gap-2">
        <span className="text-[11px] font-medium text-fg">{label.text}</span>
        <span className="tabular font-mono text-[10px] text-fg-subtle" title={mechanism.id ?? ''}>
          {shortId(mechanism.id ?? '')}
        </span>
        {mechanism.parent_id ? (
          <span className="text-[10px] text-fg-subtle">派生自 {shortId(mechanism.parent_id)}</span>
        ) : null}
      </header>

      <dl className="mt-1.5 grid grid-cols-2 gap-x-4 gap-y-1 sm:grid-cols-4">
        <div className="flex flex-col gap-0.5">
          <dt className="text-[10px] text-fg-subtle">主张</dt>
          <dd className="tabular font-mono text-[11px] text-fg">
            {mechanism.claim_id ? shortId(mechanism.claim_id) : '未关联'}
          </dd>
        </div>
        <div className="flex flex-col gap-0.5">
          <dt className="text-[10px] text-fg-subtle">涉及节点</dt>
          <dd className="text-[11px] text-fg">{nodes.length > 0 ? nodes.length : '（无）'}</dd>
        </div>
        <div className="flex flex-col gap-0.5">
          <dt className="text-[10px] text-fg-subtle">因果边</dt>
          <dd className="text-[11px] text-fg">{edges.length > 0 ? edges.length : '（无）'}</dd>
        </div>
        <div className="flex flex-col gap-0.5">
          <dt className="text-[10px] text-fg-subtle">补丁数</dt>
          <dd className="tabular text-[11px] text-fg">
            {typeof mechanism.patch_count === 'number' ? mechanism.patch_count : '未记录'}
          </dd>
        </div>
      </dl>

      {predictions.length > 0 ? (
        <div className="mt-1.5 flex flex-wrap items-center gap-2 text-[10px] text-fg-muted">
          <span>预测：</span>
          {predictions.map(([feature, sign]) => (
            <span key={feature} className="tabular font-mono">
              {feature} {sign === 1 ? '↑' : '↓'}
            </span>
          ))}
        </div>
      ) : (
        <p className="mt-1.5 text-[10px] text-fg-subtle italic">未记录预测</p>
      )}
    </article>
  );
}

/** 一条机制在裁决区的状态行。 */
function VerdictRow({ mechanism }: { mechanism: MechanismPayload }) {
  const status = mechanismStatusVerdict(mechanism.status);
  return (
    <div
      className="flex flex-wrap items-center gap-2 border-t border-border-subtle py-1.5 first:border-t-0"
      data-verdict-mechanism={mechanism.id ?? ''}
    >
      {/*
        裁决区**只认 id，不印标题**：标题是模型生成的散文（论点），
        印在这里会让人以为"标题写了"就是"数据支持了"。想知道它说了什么，
        去上面的论点区看。
      */}
      <span
        className="tabular min-w-0 flex-1 truncate font-mono text-[11px] text-fg"
        title={mechanism.id ?? ''}
      >
        {shortId(mechanism.id ?? '')}
      </span>
      <StatusBadge tone={toBadgeTone(status.tone)}>{status.label}</StatusBadge>
      <span className="w-full text-[10px] text-fg-subtle sm:w-auto">{status.reason}</span>
    </div>
  );
}

/** 一场辩论（`matches[]` 的一行）—— 这是"正反论点"。 */
function MatchRow({ match }: { match: MatchPayload }) {
  const verdict = matchVerdict(match);
  return (
    <div
      className="rounded-card border border-border-subtle bg-surface-muted p-2"
      data-match-test={match.test_type ?? ''}
      data-match-decisive={verdict.decisive ? 'true' : 'false'}
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="tabular font-mono text-[11px] text-fg" title={`${match.mech_a} vs ${match.mech_b}`}>
          {shortId(match.mech_a ?? '')} vs {shortId(match.mech_b ?? '')}
        </span>
        <StatusBadge tone={toBadgeTone(verdict.tone)}>{verdict.label}</StatusBadge>
        {match.test_type ? (
          <span className="text-[10px] text-fg-subtle">检验={match.test_type}</span>
        ) : null}
        {match.slice_id ? (
          <span className="text-[10px] text-fg-subtle">切片={match.slice_id}</span>
        ) : null}
        <span className="flex-1" />
        <span className="text-[10px] text-fg-subtle">{verdict.reason}</span>
      </div>
      <dl className="mt-1.5 grid grid-cols-2 gap-x-4 gap-y-1">
        <Field label="统计量 / CI / p / e" view={verdict.statistics} />
        <div className="flex flex-col gap-0.5">
          <dt className="text-[10px] text-fg-subtle">胜方机制</dt>
          <dd className="tabular font-mono text-[11px] text-fg">
            {verdict.winner ? shortId(verdict.winner) : '未分胜负'}
          </dd>
        </div>
      </dl>
    </div>
  );
}

/** 转发一次 `matchVerdict`，避免在本文件里重复实现同一套判定。 */
export interface TournamentBracketProps {
  discovery: DiscoveryResponse;
}

export function TournamentBracket({ discovery }: TournamentBracketProps) {
  const view = buildTournamentView(discovery);
  const emptyReason = tournamentEmptyReason(view);

  const groups: MechanismGroup[] = view.partition.groups;

  // 预注册检验：把出现过的检验类型收成一行，不重复每场比赛都念一遍。
  const testTypes = [
    ...new Set(
      [
        ...(discovery.matches ?? []).map((match) => match.test_type),
        ...(discovery.certificates ?? []).map((certificate) => certificate.test_type),
      ].filter((value): value is string => typeof value === 'string' && value !== ''),
    ),
  ];

  return (
    <div className="flex flex-col gap-4" data-testid="tournament-bracket">
      <div className="flex flex-wrap items-center gap-2 fe-card-panel-muted px-3 py-2">
        <span className="text-[11px] font-medium text-fg">机制辩论赛</span>
        <StatusBadge tone={view.enabled === false ? 'neutral' : 'success'}>
          {view.enabled === null ? '启用状态未记录' : view.enabled ? '已启用' : '未启用'}
        </StatusBadge>
        <span className="text-[11px] text-fg-muted">
          机制 {groups.reduce((sum, group) => sum + group.items.length, 0)} 条（主张{' '}
          {view.partition.claim.length} / 对手 {view.partition.rivals.length}） · 比赛{' '}
          {view.totalMatches} 场（决定性 {view.decisiveMatches}） · 证书 {view.certificates.length} 张
        </span>
        <span className="flex-1" />
        <span className="text-[10px] text-fg-subtle">
          数据支持 {view.partition.establishedCount} · 数据否证 {view.partition.refutedCount}
        </span>
      </div>

      {emptyReason ? (
        <EmptyState
          title="没有可展示的机制辩论"
          reason={emptyReason}
          nextStep="确认该运行启用了 discovery 与 tournament，或查看事件流中的机制相关事件"
        />
      ) : (
        <>
          {/* ---------------- 分区一：模型论点 ---------------- */}
          <div
            data-zone="arguments"
            className="rounded-panel border border-info-500/30 bg-info-50/40 p-3 dark:border-info-500/40 dark:bg-info-500/5"
          >
            <div className="flex flex-wrap items-baseline gap-2">
              <h2 className="text-[12px] font-semibold text-fg">模型论点（Qwen 生成）</h2>
              <span className="text-[10px] text-fg-muted">
                以下是模型提出的机制假设，<strong className="text-fg">未经数据裁决</strong>
                {' '}—— 裁决结果在下一个分区
              </span>
            </div>

            <div className="mt-2 flex flex-col gap-3">
              <Stage n={1} zone="arguments">
                {groups.filter((group) => group.key === 'claim').length === 0 ? (
                  <p className="text-[11px] text-fg-subtle italic">本次运行没有提出主张机制</p>
                ) : null}
                {groups
                  .filter((group) => group.key === 'claim')
                  .map((group) => (
                    <div key={group.key} className="flex flex-col gap-1.5">
                      {group.items.map((item) => (
                        <MechanismCard key={item.id ?? labelKey(item)} mechanism={item} />
                      ))}
                    </div>
                  ))}
              </Stage>

              <Stage n={2} zone="arguments" hint="由模型给出的竞争性解释">
                {groups.filter((group) => group.key === 'llm_rival').length === 0 ? (
                  <p className="text-[11px] text-fg-subtle italic">
                    本次运行没有生成对手机制
                  </p>
                ) : null}
                {groups
                  .filter((group) => group.key === 'llm_rival')
                  .map((group) => (
                    <div key={group.key} className="flex flex-col gap-1.5">
                      {group.items.map((item) => (
                        <MechanismCard key={item.id ?? labelKey(item)} mechanism={item} />
                      ))}
                    </div>
                  ))}
              </Stage>

              <Stage n={3} zone="arguments" hint="混淆因素 / 数据处理产物 / 随机性 —— 都是待排除的解释">
                {groups.filter(
                  (group) => !['claim', 'llm_rival'].includes(group.key),
                ).length === 0 ? (
                  <p className="text-[11px] text-fg-subtle italic">没有其它竞争性解释</p>
                ) : null}
                {groups
                  .filter((group) => !['claim', 'llm_rival'].includes(group.key))
                  .map((group) => (
                    <div key={group.key} className="flex flex-col gap-1.5">
                      <div className="flex items-center gap-2">
                        <StatusBadge tone={toBadgeTone(group.tone)} showDot={false}>
                          {group.label}
                        </StatusBadge>
                        <span className="text-[10px] text-fg-subtle">{group.stage}</span>
                      </div>
                      {group.items.map((item) => (
                        <MechanismCard key={item.id ?? labelKey(item)} mechanism={item} />
                      ))}
                    </div>
                  ))}
              </Stage>
            </div>
          </div>

          {/* ---------------- 分区二：数据裁决 ---------------- */}
          <div
            data-zone="verdicts"
            className="rounded-panel border border-border-strong bg-surface p-3"
          >
            <div className="flex flex-wrap items-baseline gap-2">
              <h2 className="text-[12px] font-semibold text-fg">数据裁决（统计证据）</h2>
              <span className="text-[10px] text-fg-muted">
                下面是<strong className="text-fg">预注册检验与数据</strong>
                {' '}给出的结论 —— 与上面的模型假设分开读
              </span>
            </div>

            <div className="mt-2 flex flex-col gap-3">
              <Stage n={4} zone="verdicts" hint="检验在预注册时就定好了类型与切片">
                <div className="flex flex-wrap items-center gap-2">
                  {testTypes.length === 0 ? (
                    <span className="text-[11px] text-fg-subtle italic">未记录检验类型</span>
                  ) : (
                    testTypes.map((type) => (
                      <span
                        key={type}
                        className="rounded-pill border border-border-subtle bg-surface-muted px-2 py-0.5 text-[10px] text-fg-muted"
                      >
                        {type}
                      </span>
                    ))
                  )}
                </div>
              </Stage>

              <Stage n={5} zone="verdicts" hint="每场比赛的胜负；未达决定性阈值的不能当证据">
                {view.families.length === 0 ? (
                  <p className="text-[11px] text-fg-subtle italic">本次运行没有进行任何比赛</p>
                ) : (
                  <div className="flex flex-col gap-3">
                    {view.families.map((family) => (
                      <div key={family.familyId || 'no-family'} className="flex flex-col gap-1.5">
                        <div className="flex flex-wrap items-center gap-2 text-[10px] text-fg-muted">
                          <span className="font-mono">
                            家族 {family.familyId ? shortId(family.familyId) : '未记录'}
                          </span>
                          <span>
                            {family.matches.length} 场 · 决定性 {family.decisiveCount}
                          </span>
                          <span>
                            领先者{' '}
                            <span className="font-mono">
                              {family.champion
                                ? shortId(family.champion)
                                : family.matches.length > 0
                                  ? '并列 / 无'
                                  : '未记录'}
                            </span>
                          </span>
                        </div>
                        {family.matches.map((match, index) => (
                          <MatchRow key={`${match.test_id ?? match.test_type ?? 'm'}-${index}`} match={match} />
                        ))}
                      </div>
                    ))}
                  </div>
                )}
              </Stage>

              <Stage n={6} zone="verdicts" hint="机制自身的裁决状态；证书是胜出的凭证">
                {groups.length === 0 ? (
                  <p className="text-[11px] text-fg-subtle italic">没有可裁决的机制</p>
                ) : (
                  <div className="rounded-card border border-border-subtle bg-surface-muted p-2">
                    {groups
                      .flatMap((group) => group.items)
                      .map((item) => (
                        <VerdictRow key={item.id ?? labelKey(item)} mechanism={item} />
                      ))}
                  </div>
                )}

                {view.certificates.length === 0 ? (
                  <p className="text-[11px] text-fg-subtle italic">本次运行没有发放证书</p>
                ) : (
                  <div className="flex flex-col gap-1.5">
                    {view.certificates.map((certificate, index) => (
                      <div
                        key={`${certificate.mechanismId}-${certificate.rivalId}-${index}`}
                        className="rounded-card border border-success-500/30 bg-success-50 p-2 dark:border-success-500/40 dark:bg-success-500/10"
                        data-certificate
                      >
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="tabular font-mono text-[11px] text-fg">
                            {certificate.headline}
                          </span>
                          <StatusBadge
                            tone={
                              certificate.evidence.state === 'recorded' &&
                              certificate.evidence.tone === 'positive'
                                ? 'success'
                                : 'neutral'
                            }
                          >
                            {certificate.evidence.text}
                          </StatusBadge>
                          <span className="flex-1" />
                          <span
                            className="tabular font-mono text-[10px] text-fg-subtle"
                            title={certificate.preregHash || '未记录预注册哈希'}
                          >
                            预注册 {certificate.preregShort}
                          </span>
                        </div>
                        <div className="mt-1 text-[10px] text-fg-muted">{certificate.context.text}</div>
                      </div>
                    ))}
                  </div>
                )}
              </Stage>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

/** 机制没有 id 时的稳定 React key（用 role+title 拼）。 */
function labelKey(item: MechanismPayload): string {
  return `${item.role ?? 'none'}:${item.title ?? ''}`;
}
