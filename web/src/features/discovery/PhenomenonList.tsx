/**
 * 现象层（PRD 12.3 / TODO 6.2）。
 *
 * 只吃 props、不发请求。PRD 说的是「每张现象卡」，所以这里用卡片而不是宽表：
 * 一个 claim 有 15 个统计量，塞进表格会变成 18 列的横向滚动条，反而读不出
 * 「效应量 + 置信区间 + 判级」这条主线。
 *
 * 两条红线：
 * 1. `recorded=false` 的格子显示「未记录」，绝不显示 0；
 * 2. 「未定」不是「否证」（PRD §2.3）。判级图例里明写，配色也用中性色而非红色。
 */
import type { ReactNode } from 'react';

import { StatusBadge } from '@/components/ui/StatusBadge';
import {
  GRADE_LABEL,
  GRADE_TONE,
  GRADES,
  type PhenomenonRow,
  type SandboxFailure,
} from '@/features/discovery/discovery-logic';
import { StatValue } from '@/features/discovery/StatValue';
import type { Cell } from '@/features/discovery/card-logic';

export interface PhenomenonListProps {
  rows: PhenomenonRow[];
  /** 沙箱失败、因此从未进入检验的 claim。与有结果的 claim 分区显示。 */
  untestedFailures: SandboxFailure[];
  /**
   * 既有检验结果、又记录过沙箱失败的 claim。按 discovery/pipeline.py:174-178 的写法
   * 这不该发生（失败即 continue，永不进入检验），所以出现了就说明制品互相矛盾——
   * 必须说出来，不能悄悄丢掉其中一边。
   */
  matchedFailures: SandboxFailure[];
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5">
      <dt className="text-[10px] text-fg-subtle">{label}</dt>
      <dd className="text-xs">{children}</dd>
    </div>
  );
}

function CiField({
  label,
  low,
  high,
  lowName,
  highName,
}: {
  label: string;
  low: Cell;
  high: Cell;
  /** 测试钩子名，与 payload 里的键名一致。两组 CI 同页出现，必须区分开。 */
  lowName: string;
  highName: string;
}) {
  return (
    <Field label={label}>
      <span className="tabular text-xs">
        [<StatValue cell={low} name={lowName} />, <StatValue cell={high} name={highName} />]
      </span>
    </Field>
  );
}

function FailureList({ failures }: { failures: SandboxFailure[] }) {
  return (
    <ul className="flex flex-col gap-1">
      {failures.map((failure, index) => (
        <li
          key={`${failure.claimId}-${index}`}
          data-sandbox-failure={failure.claimId}
          className="rounded-card border border-danger-500/30 bg-danger-50 p-2 text-[11px] text-danger-700 dark:border-danger-500/40 dark:bg-danger-500/10 dark:text-danger-500"
        >
          <span className="font-mono">{failure.claimId}</span>
          {failure.stage ? <span className="ml-1.5">阶段 {failure.stage}</span> : null}
          {failure.errorType ? <span className="ml-1.5">类型 {failure.errorType}</span> : null}
          {/* 错误文本已由后端 sanitize_value 脱敏（replay_service.py:994）；
              这里当纯文本渲染，不做 Markdown/HTML 解析。 */}
          <p className="mt-1 break-words font-mono text-[10px]">
            {failure.error ?? '未记录错误详情'}
          </p>
        </li>
      ))}
    </ul>
  );
}

export function PhenomenonList({ rows, untestedFailures, matchedFailures }: PhenomenonListProps) {
  return (
    <div className="flex flex-col gap-3">
      <p className="text-[11px] text-fg-subtle" data-grade-legend>
        判级取值：
        {GRADES.map((grade, index) => (
          <span key={grade}>
            {index > 0 ? ' / ' : ''}
            <code className="font-mono">{grade}</code> {GRADE_LABEL[grade]}
          </span>
        ))}
        。其中「未定」表示证据不足，不等于「已否证」。
      </p>

      <div className="flex flex-col gap-3">
        {rows.map((row) => (
          <article
            key={row.claimId}
            data-phenomenon-card={row.claimId}
            className="fe-card-panel p-3"
          >
            <header className="flex flex-wrap items-center gap-2">
              <h3 className="font-mono text-xs font-semibold text-fg">{row.claimId}</h3>
              {row.grade ? (
                // StatusBadge 只接受 tone/children/showDot/title，测试钩子挂在外层。
                <span data-grade={row.grade} className="inline-flex">
                  <StatusBadge tone={GRADE_TONE[row.grade]}>{GRADE_LABEL[row.grade]}</StatusBadge>
                </span>
              ) : (
                // 契约外的判级字符串：原样回显，不猜它对应五个里的哪一个。
                <span data-grade="unknown" className="inline-flex">
                  <StatusBadge tone="warning" showDot={false}>
                    未知判级 {row.rawGrade ?? '未记录'}
                  </StatusBadge>
                </span>
              )}
              {row.preregHash ? (
                <span
                  data-prereg-hash={row.claimId}
                  title={row.preregHash}
                  className="rounded-pill border border-border-subtle bg-surface-muted px-2 py-0.5 font-mono text-[10px] text-fg-muted"
                >
                  预注册 {row.preregHash.slice(0, 8)}
                </span>
              ) : (
                <span className="text-[10px] text-fg-subtle">预注册哈希未记录</span>
              )}
            </header>

            <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-2 sm:grid-cols-4">
              <Field label="效应量">
                <StatValue cell={row.effect} name="effect" className="text-xs" />
              </Field>
              <CiField
                label="效应量 95% CI"
                low={row.ciLow}
                high={row.ciHigh}
                lowName="ci_low"
                highName="ci_high"
              />
              <Field label="p 值">
                <StatValue cell={row.p} name="p" className="text-xs" />
              </Field>
              <Field label="e 值">
                <StatValue cell={row.e} name="e" className="text-xs" />
              </Field>
              <Field label="样本 n">
                <StatValue cell={row.n} name="n" className="text-xs" />
              </Field>
              <Field label="正例 / 负例">
                <span className="text-xs">
                  <StatValue cell={row.nPos} name="n_pos" /> /{' '}
                  <StatValue cell={row.nNeg} name="n_neg" />
                </span>
              </Field>
              <Field label="数据切分">
                <span className="font-mono text-xs">{row.split.value}</span>
              </Field>
              <Field label="方向一致">
                <StatValue cell={row.directionOk} name="direction_ok" className="text-xs" />
              </Field>
              <Field label="时序不变">
                <StatValue cell={row.temporalOk} name="temporal_ok" className="text-xs" />
              </Field>
              <Field label="ρ 最大绝对值">
                <StatValue cell={row.rhoMaxAbs} name="rho_max_abs" className="text-xs" />
              </Field>
              <Field label="增量收益">
                <StatValue cell={row.incrGain} name="incr_gain" className="text-xs" />
              </Field>
              <CiField
                label="增量收益 CI"
                low={row.incrCiLow}
                high={row.incrCiHigh}
                lowName="incr_ci_low"
                highName="incr_ci_high"
              />
            </dl>
          </article>
        ))}
      </div>

      {untestedFailures.length > 0 ? (
        <section className="flex flex-col gap-2" data-sandbox-untested>
          <h3 className="text-xs font-medium text-fg-muted">
            沙箱失败、从未进入检验的 claim（{untestedFailures.length}）
          </h3>
          <p className="text-[11px] text-fg-subtle">
            这些 claim 在沙箱阶段就失败了，没有统计结果，因此没有判级。
            它们既不是「已否证」也不是「未定」——检验根本没跑成。
          </p>
          <FailureList failures={untestedFailures} />
        </section>
      ) : null}

      {matchedFailures.length > 0 ? (
        <section className="flex flex-col gap-2" data-sandbox-inconsistent>
          <h3 className="text-xs font-medium text-fg-muted">
            制品互相矛盾：既有检验结果、又记录过沙箱失败（{matchedFailures.length}）
          </h3>
          <p className="text-[11px] text-fg-subtle">
            按发现流水线的写法，沙箱失败即中止该 claim，不会进入检验，所以这两件事本不该同时
            出现。下面照实列出两边，不替后端判断哪一边才是真的。
          </p>
          <FailureList failures={matchedFailures} />
        </section>
      ) : null}
    </div>
  );
}
