/**
 * 机制层与辩论赛（PRD 12.4 / TODO 6.3）。
 *
 * 这一节能如实展示的只有**计数**与**证书**。逐场对阵（MatchResult）、机制结构
 * （Mechanism）、Qwen 正反方论点、Elo、证书状态在契约里都不存在，由调用方渲染成
 * 「暂不支持」，本组件不负责编造替代品。
 *
 * 因此这里有一条必须写进界面的红线：`decisive_matches` 是「有多少场判出了胜负」的
 * 数量，不是「谁赢了」。PRD 12.4 要求胜负只能由预注册检验与 evaluator/统计证据决定，
 * 而逐场证据没有暴露出来——所以本页不给出任何胜者、排名或推荐机制。
 */
import { StatusBadge } from '@/components/ui/StatusBadge';
import { StatValue } from '@/features/discovery/StatValue';
import type {
  CertificateRow,
  ControlRow,
  CounterRow,
} from '@/features/discovery/discovery-logic';

export interface MechanismTournamentProps {
  mechanismCounters: CounterRow[];
  tournamentCounters: CounterRow[];
  validityCounters: CounterRow[];
  controls: ControlRow[];
  certificates: CertificateRow[];
}

function CounterGroup({
  title,
  rows,
  note,
}: {
  title: string;
  rows: CounterRow[];
  note?: string;
}) {
  return (
    <section className="flex flex-col gap-2">
      <h3 className="text-xs font-medium text-fg-muted">{title}</h3>
      <dl className="grid grid-cols-2 gap-2 sm:grid-cols-3">
        {rows.map((row) => (
          <div
            key={row.label}
            className="fe-card px-2.5 py-1.5"
          >
            <dt className="text-[10px] text-fg-subtle">{row.label}</dt>
            <dd>
              <StatValue cell={row.cell} name={row.label} className="text-sm font-semibold" />
            </dd>
          </div>
        ))}
      </dl>
      {note ? <p className="text-[11px] text-fg-subtle">{note}</p> : null}
    </section>
  );
}

export function MechanismTournament({
  mechanismCounters,
  tournamentCounters,
  validityCounters,
  controls,
  certificates,
}: MechanismTournamentProps) {
  return (
    <div className="flex flex-col gap-4">
      <p
        data-no-verdict
        className="fe-card-panel-muted p-2.5 text-[11px] text-fg-muted"
      >
        本页只给出计数与证书，不给出胜者、排名或推荐机制。按 PRD 12.4，胜负只能由预注册检验与
        evaluator/统计证据决定；逐场判别检验没有暴露在契约里，「判出胜负的对阵」是一个数量，
        不能读成「哪一方赢了」。
      </p>

      <CounterGroup title="机制" rows={mechanismCounters} />
      <CounterGroup
        title="辩论赛调度"
        rows={tournamentCounters}
        note="这些是配对与调度层面的计数。Elo 不在其中：它被计算过但从未落盘，且按 PRD 12.4 本来也只能作为调度信息，不能替代证据判级。"
      />
      <CounterGroup
        title="方法学校验"
        rows={validityCounters}
        note="这三组不是演化成绩，而是发现流程本身是否可信的检查：植入的机制能否被回收、LLM 的排序与数据排序是否一致、把环境打乱后是否还会误通过。"
      />

      <section className="flex flex-col gap-2" data-controls>
        <h3 className="text-xs font-medium text-fg-muted">对照检验（每轮一条）</h3>
        {controls.length === 0 ? (
          <p className="text-[11px] text-fg-subtle">
            没有对照记录。对照为空时，上面「方法学校验」里的负对照 FPR 无法交叉核对。
          </p>
        ) : (
          <div className="overflow-x-auto rounded-panel border border-border-subtle">
            <table className="w-full border-collapse text-left">
              <thead>
                <tr className="bg-surface-muted text-[11px] text-fg-muted">
                  <th className="px-3 py-2 font-medium">轮次</th>
                  <th className="px-3 py-2 font-medium">负对照试验数</th>
                  <th className="px-3 py-2 font-medium">负对照假阳性</th>
                  <th className="px-3 py-2 font-medium">负对照 FPR</th>
                  <th className="px-3 py-2 font-medium">植入信号回收</th>
                  <th className="px-3 py-2 font-medium">是否通过</th>
                </tr>
              </thead>
              <tbody>
                {controls.map((row, index) => (
                  <tr
                    key={index}
                    data-control-row={index}
                    className="border-b border-border-subtle last:border-b-0"
                  >
                    <td className="tabular px-3 py-2 text-xs text-fg-muted">{index + 1}</td>
                    <td className="px-3 py-2 text-xs">
                      <StatValue cell={row.negTrials} name="neg_trials" />
                    </td>
                    <td className="px-3 py-2 text-xs">
                      <StatValue cell={row.negFalsePositives} name="neg_false_positives" />
                    </td>
                    <td className="px-3 py-2 text-xs">
                      <StatValue cell={row.negFpr} name="neg_fpr" />
                    </td>
                    <td className="px-3 py-2 text-xs text-fg-muted">
                      {row.planted.length === 0 ? (
                        <span className="text-fg-subtle">未记录</span>
                      ) : (
                        <ul className="flex flex-col gap-0.5">
                          {row.planted.map((entry) => (
                            <li key={entry.name} className="tabular">
                              <span className="font-mono text-[10px]">{entry.name}</span>{' '}
                              {entry.recovered ?? '未记录'} / {entry.trials ?? '未记录'}
                            </li>
                          ))}
                        </ul>
                      )}
                    </td>
                    <td className="px-3 py-2">
                      <StatusBadge
                        tone={
                          row.passed.recorded
                            ? row.passed.value === '是'
                              ? 'success'
                              : 'danger'
                            : 'neutral'
                        }
                        showDot={false}
                      >
                        {row.passed.value}
                      </StatusBadge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="flex flex-col gap-2" data-certificates>
        <h3 className="text-xs font-medium text-fg-muted">证书（{certificates.length}）</h3>
        {certificates.length === 0 ? (
          <p className="text-[11px] text-fg-subtle">
            没有签发任何证书。证书只在判别检验判出胜负后由 discovery/certificates.py 写出。
          </p>
        ) : (
          <div className="overflow-x-auto rounded-panel border border-border-subtle">
            <table className="w-full border-collapse text-left">
              <thead>
                <tr className="bg-surface-muted text-[11px] text-fg-muted">
                  <th className="px-3 py-2 font-medium">机制</th>
                  <th className="px-3 py-2 font-medium">对手</th>
                  <th className="px-3 py-2 font-medium">判别检验</th>
                  <th className="px-3 py-2 font-medium">环境</th>
                  <th className="px-3 py-2 font-medium">统计量</th>
                  <th className="px-3 py-2 font-medium">CI</th>
                  <th className="px-3 py-2 font-medium">e 值</th>
                  <th className="px-3 py-2 font-medium">预注册哈希</th>
                  <th className="px-3 py-2 font-medium">签发时间</th>
                </tr>
              </thead>
              <tbody>
                {certificates.map((row, index) => (
                  <tr
                    key={`${row.mechanismId}-${row.testId}-${index}`}
                    data-certificate-row={row.mechanismId}
                    className="border-b border-border-subtle last:border-b-0"
                  >
                    <td className="px-3 py-2 font-mono text-[11px] text-fg">{row.mechanismId}</td>
                    <td className="px-3 py-2 font-mono text-[11px] text-fg-muted">{row.rivalId}</td>
                    <td className="px-3 py-2 text-xs">
                      <span className="font-mono text-[10px]">{row.testId}</span>
                      <span className="ml-1 text-fg-subtle">{row.testType.value}</span>
                    </td>
                    <td className="px-3 py-2 text-xs">
                      <StatValue cell={row.env} name="env" />
                    </td>
                    <td className="px-3 py-2 text-xs">
                      <StatValue cell={row.stat} name="stat" />
                    </td>
                    <td className="tabular px-3 py-2 text-xs">
                      [<StatValue cell={row.ciLow} name="ci_low" />,{' '}
                      <StatValue cell={row.ciHigh} name="ci_high" />]
                    </td>
                    <td className="px-3 py-2 text-xs">
                      <StatValue cell={row.eValue} name="e_value" />
                    </td>
                    <td className="px-3 py-2">
                      {row.preregHash ? (
                        <span title={row.preregHash} className="font-mono text-[10px] text-fg-muted">
                          {row.preregHash.slice(0, 8)}
                        </span>
                      ) : (
                        <span className="text-xs text-fg-subtle">未记录</span>
                      )}
                    </td>
                    <td className="px-3 py-2 text-xs">
                      <StatValue cell={row.date} name="date" />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
