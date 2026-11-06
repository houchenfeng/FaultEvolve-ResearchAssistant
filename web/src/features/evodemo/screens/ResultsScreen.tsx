/**
 * 结果讲解：讲解员 Bot 按章节讲一次运行的结论。页面只读 `RunReport`，
 * 不包含任何任务相关的文案或数字。
 */
import { AnimatePresence, motion } from 'motion/react';
import { useEffect, useState } from 'react';

import { EvoBot } from '../bot/EvoBot';
import type { MetricDef, MetricRow, ReportClaim, ReportNode, ReportStep, RunReport } from '../report';
import { chapterTitles, formatDelta, formatMetric, narrate, operatorLabel, primaryDef } from '../report';
import { Icon, Typewriter } from '../ui';

const MAX_LAYERS = 6;

export function ResultsScreen({ report, onRestart }: { report: RunReport; onRestart: () => void }) {
  const [chapter, setChapter] = useState(0);
  const [auto, setAuto] = useState(true);
  const [spoken, setSpoken] = useState(false);
  const titles = chapterTitles(report);

  useEffect(() => setSpoken(false), [chapter]);
  useEffect(() => {
    if (!auto || !spoken || chapter >= titles.length - 1) return;
    const timer = window.setTimeout(() => setChapter((c) => c + 1), chapter === 2 ? 6000 : 3000);
    return () => window.clearTimeout(timer);
  }, [auto, spoken, chapter, titles.length]);

  return (
    <div className="grid h-full grid-rows-[auto_minmax(0,1fr)] gap-4 p-6">
      <div className="flex items-center gap-2">
        {titles.map((title, i) => (
          <button key={title} className="flex flex-1 flex-col items-start gap-1.5" onClick={() => setChapter(i)}>
            <div className="h-1 w-full overflow-hidden rounded-full bg-slate-200">
              <motion.div
                className="h-full bg-[var(--evo-brand)]"
                animate={{ width: i < chapter ? '100%' : i === chapter ? (spoken ? '100%' : '45%') : '0%' }}
                transition={{ duration: 0.6 }}
              />
            </div>
            <span className={`text-[13px] ${i === chapter ? 'font-semibold text-[var(--evo-brand)]' : 'text-[var(--evo-muted)]'}`}>
              {i + 1} {title}
            </span>
          </button>
        ))}
        <button className="evo-chip ml-3" data-active={auto} onClick={() => setAuto((a) => !a)}>
          <Icon name={auto ? 'pause' : 'play'} size={12} /> 自动讲解
        </button>
      </div>

      <div className="grid min-h-0 grid-cols-[260px_minmax(0,1fr)] gap-6">
        <div className="flex flex-col items-center pt-4">
          <div className="evo-mono mb-3 text-center text-[11px] text-[var(--evo-muted)]">
            {report.input.taskName} · {report.input.runId}
          </div>
          <div className="evo-card relative mb-5 w-full px-4 py-3 text-[14px] leading-relaxed shadow-lg">
            <Typewriter key={chapter} text={narrate(report, chapter)} speed={30} onDone={() => setSpoken(true)} />
            <span className="absolute -bottom-2 left-1/2 size-4 -translate-x-1/2 rotate-45 border-r border-b border-[var(--evo-border)] bg-white" />
          </div>
          <EvoBot size={150} mood={spoken ? 'happy' : 'talk'} gaze={{ x: 0.7, y: 0.1 }} />
          <div className="mt-3 text-sm font-semibold">讲解员 · Evo</div>
          <button className="evo-btn evo-btn--ghost mt-6" onClick={onRestart}>
            <Icon name="restart" /> 重新演示
          </button>
        </div>

        <div className="evo-card evo-scroll relative min-h-0 overflow-auto p-6">
          <AnimatePresence mode="wait">
            <motion.div
              key={chapter}
              className="h-full"
              initial={{ opacity: 0, y: 16 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
              transition={{ duration: 0.35, ease: [0.16, 1, 0.3, 1] }}
            >
              {chapter === 0 && (report.structure === 'combination' ? <Combination report={report} /> : <Stack report={report} />)}
              {chapter === 1 && <Improvement report={report} />}
              {chapter === 2 && (report.input.insights?.length ? <Insights report={report} /> : <KeyChanges report={report} />)}
              {chapter === 3 && <Knowledge report={report} />}
              {chapter === 4 && <Reproducibility report={report} />}
            </motion.div>
          </AnimatePresence>
        </div>
      </div>
    </div>
  );
}

/** `value` 是按指标方向取正后的改善量；显示时还原成指标的真实变化方向。 */
function Delta({ def, value, className = '' }: { def: Omit<MetricDef, 'key'>; value: number; className?: string }) {
  const raw = def.higherIsBetter === false ? -value : value;
  return (
    <span className={`evo-mono font-semibold ${value >= 0 ? 'text-[var(--evo-good)]' : 'text-[var(--evo-bad)]'} ${className}`}>
      {formatDelta(def, raw)}
    </span>
  );
}

function Heading({ title, sub }: { title: string; sub?: string }) {
  return (
    <>
      <div className="text-lg font-semibold">{title}</div>
      {sub && <div className="text-sm text-[var(--evo-muted)]">{sub}</div>}
    </>
  );
}

/** 组合形态：父算法 → 组合规则 → 决策，从左到右。 */
function Combination({ report }: { report: RunReport }) {
  const { parents, best, input } = report;
  const primary = primaryDef(input);
  return (
    <div className="flex h-full flex-col">
      <Heading title="最终方案由哪些算法、怎样组合而成" sub={`${parents.length} 个父算法 · ${operatorLabel(best.operator)} · 无新增可学习参数`} />
      <div className="mt-8 grid flex-1 grid-cols-[minmax(0,1fr)_48px_minmax(0,1.15fr)_48px_minmax(0,0.9fr)] items-center">
        <div className="space-y-3">
          {parents.map((p, i) => (
            <motion.div
              key={p.id}
              className="rounded-2xl border border-[var(--evo-border)] bg-white p-4"
              initial={{ opacity: 0, x: -24 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: 0.1 + i * 0.15, type: 'spring', stiffness: 220, damping: 22 }}
            >
              <div className="text-[11px] text-[var(--evo-subtle)]">父算法 {String.fromCharCode(65 + i)}</div>
              <div className="text-[17px] font-semibold">{p.title}</div>
              {p.subtitle && <div className="mt-0.5 text-[12px] text-[var(--evo-muted)]">{p.subtitle}</div>}
              <div className="evo-mono mt-2 text-[12px] text-[var(--evo-muted)]">
                {primary.label} {formatMetric(primary, p.score)}
              </div>
            </motion.div>
          ))}
        </div>
        <Arrow delay={0.45} />
        <motion.div
          className="rounded-2xl border-2 border-[var(--evo-brand)] bg-[var(--evo-brand-50)] p-5 text-center"
          initial={{ opacity: 0, scale: 0.85 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ delay: 0.6, type: 'spring', stiffness: 220, damping: 18 }}
        >
          <div className="text-[11px] font-semibold text-[var(--evo-brand)]">{operatorLabel(best.operator)}</div>
          {input.formula && <div className="evo-mono mt-2 text-[19px] leading-snug font-bold">{input.formula.expression}</div>}
          {input.formula?.decision && <div className="mt-3 text-[12.5px] leading-snug text-[var(--evo-muted)]">{input.formula.decision}</div>}
        </motion.div>
        <Arrow delay={0.85} />
        <motion.div
          className="rounded-2xl bg-[var(--evo-brand)] p-5 text-white"
          initial={{ opacity: 0, x: 24 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ delay: 1, type: 'spring', stiffness: 220, damping: 22 }}
        >
          <div className="text-[11px] opacity-80">最终方案</div>
          <div className="text-[17px] leading-snug font-semibold">{best.title}</div>
          <div className="mt-3 space-y-1">
            {report.wins.slice(0, 4).map((r) => (
              <div key={r.def.key} className="flex items-center justify-between text-[12px]">
                <span className="opacity-85">{r.def.label}</span>
                <span className="evo-mono font-semibold">{formatMetric(r.def, r.best)}</span>
              </div>
            ))}
          </div>
        </motion.div>
      </div>
    </div>
  );
}

function Arrow({ delay }: { delay: number }) {
  return (
    <svg viewBox="0 0 48 24" className="w-full">
      <motion.path d="M4 12 H40 M32 5 L41 12 L32 19" fill="none" stroke="#2563EB" strokeWidth={2.2} strokeLinecap="round" strokeLinejoin="round" initial={{ pathLength: 0 }} animate={{ pathLength: 1 }} transition={{ delay, duration: 0.5 }} />
    </svg>
  );
}

/** 谱系形态：初始解 + 沿谱系逐代保留下来的改动，自下而上叠成一摞。 */
function Stack({ report }: { report: RunReport }) {
  const { root, best, steps, input } = report;
  const primary = primaryDef(input);
  const hidden = Math.max(0, steps.length - MAX_LAYERS);
  const layers = [...steps.slice(hidden)].reverse();
  return (
    <div className="flex h-full gap-6">
      <div className="flex min-w-0 flex-1 flex-col">
        <Heading title="最终方案是怎么叠出来的" sub={`自下而上：初始解 + 每一代保留下来的改动 · 共 ${steps.length} 代`} />
        <div className="mt-5 flex flex-col gap-1.5">
          {layers.map((s, i) => (
            <motion.div
              key={s.node.id}
              className={`flex items-center gap-3 rounded-xl border px-4 py-2.5 ${s.node.id === best.id ? 'border-[var(--evo-brand)] bg-[var(--evo-brand)] text-white' : s.borrowedFrom ? 'border-[var(--evo-brand)] bg-[var(--evo-brand-50)]' : 'border-[var(--evo-border)] bg-white'}`}
              initial={{ opacity: 0, y: -24 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.15 + (layers.length - i) * 0.14, type: 'spring', stiffness: 240, damping: 20 }}
            >
              <span className="evo-mono w-12 shrink-0 text-[11px] opacity-70">{s.node.id}</span>
              <span className={`shrink-0 rounded px-1.5 text-[10.5px] ${s.node.id === best.id ? 'bg-white/20' : 'bg-slate-100 text-slate-500'}`}>{s.operatorLabel}</span>
              <span className="min-w-0 flex-1 truncate text-[14px] font-semibold">{s.node.title}</span>
              {s.borrowedFrom && (
                <span className={`shrink-0 rounded-full px-2 text-[10.5px] ${s.node.id === best.id ? 'bg-white/20' : 'bg-[var(--evo-brand)] text-white'}`}>借鉴 {s.borrowedFrom}</span>
              )}
              <span className="evo-mono w-16 shrink-0 text-right text-[13px]">{formatMetric(primary, s.node.score)}</span>
              <Delta def={primary} value={s.delta} className={`w-16 shrink-0 text-right text-[12px] ${s.node.id === best.id ? '!text-white' : ''}`} />
            </motion.div>
          ))}
          {hidden > 0 && <div className="py-1 text-center text-xs text-[var(--evo-subtle)]">… 更早的 {hidden} 代改动</div>}
          <motion.div className="flex items-center gap-3 rounded-xl border border-dashed border-slate-300 bg-slate-50 px-4 py-2.5" initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.1 }}>
            <span className="evo-mono w-12 shrink-0 text-[11px] text-[var(--evo-muted)]">{root.id}</span>
            <span className="shrink-0 rounded bg-slate-200 px-1.5 text-[10.5px] text-slate-500">{operatorLabel(root.operator)}</span>
            <span className="flex-1 text-[14px] font-semibold text-[var(--evo-muted)]">{root.title}</span>
            <span className="evo-mono w-16 text-right text-[13px] text-[var(--evo-muted)]">{formatMetric(primary, root.score)}</span>
            <span className="w-16" />
          </motion.div>
        </div>
      </div>
      {best.reflection && (
        <div className="w-[240px] shrink-0 pt-[60px]">
          <div className="rounded-xl bg-slate-50 p-4 text-[13px] leading-relaxed">
            <div className="mb-1 text-xs font-semibold text-[var(--evo-brand)]">最优方案 {best.id} 的反思</div>
            <span className="text-[var(--evo-muted)]">{best.reflection}</span>
            {best.group && <div className="mt-3 text-xs text-[var(--evo-subtle)]">所属分支：{best.group}</div>}
          </div>
        </div>
      )}
    </div>
  );
}

/** 指标对照表：每列一个对照节点，最后一列是最终方案。 */
function Improvement({ report }: { report: RunReport }) {
  const { baselines, best, counts, metricRows, structure } = report;
  return (
    <div className="flex h-full flex-col">
      <Heading
        title={structure === 'combination' ? '相对每个父算法提升了什么' : `${baselines[0].id} 初始解 → ${best.id} 最优方案`}
        sub={`共评估 ${counts.total} 个候选${counts.failed ? ` · ${counts.failed} 个失败回退` : ''}${counts.pruned ? ` · ${counts.pruned} 个未通过筛选` : ''}${counts.groups > 1 ? ` · ${counts.groups} 个分支 / 批次` : ''}`}
      />
      <div className="mt-6 overflow-hidden rounded-2xl border border-[var(--evo-border)]">
        <table className="w-full text-[13.5px]">
          <thead className="bg-slate-50 text-[12px] text-[var(--evo-muted)]">
            <tr>
              <th className="px-4 py-2.5 text-left font-medium">指标</th>
              {baselines.map((b) => (
                <th key={b.id} className="px-4 py-2.5 text-right font-medium">
                  {b.title}
                </th>
              ))}
              <th className="bg-[var(--evo-brand-50)] px-4 py-2.5 text-right font-semibold text-[var(--evo-brand)]">{best.title}</th>
              <th className="px-4 py-2.5 text-right font-medium">相对最强对照</th>
            </tr>
          </thead>
          <tbody>
            {metricRows.map((row, i) => (
              <MetricLine key={row.def.key} row={row} index={i} />
            ))}
          </tbody>
        </table>
      </div>
      <div className="mt-4 flex flex-wrap gap-2 text-[12px]">
        {report.wins.length > 0 && <span className="rounded-full bg-green-50 px-3 py-1 text-[var(--evo-good)]">同时优于所有对照：{report.wins.map((r) => r.def.label).join('、')}</span>}
        {report.tradeoffs.length > 0 && <span className="rounded-full bg-amber-50 px-3 py-1 text-amber-700">取舍：{report.tradeoffs.map((r) => r.def.label).join('、')}</span>}
      </div>
    </div>
  );
}

function MetricLine({ row, index }: { row: MetricRow; index: number }) {
  return (
    <motion.tr className="border-t border-[var(--evo-border)]" initial={{ opacity: 0, x: -10 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: 0.1 + index * 0.08 }}>
      <td className="px-4 py-2.5">
        {row.def.label}
        {row.def.higherIsBetter === false && <span className="ml-1 text-[11px] text-[var(--evo-subtle)]">越低越好</span>}
      </td>
      {row.baselines.map((v, i) => (
        <td key={i} className="evo-mono px-4 py-2.5 text-right text-[var(--evo-muted)]">
          {formatMetric(row.def, v)}
        </td>
      ))}
      <td className={`evo-mono bg-[var(--evo-brand-50)] px-4 py-2.5 text-right font-bold ${row.beatsAll ? 'text-[var(--evo-brand)]' : ''}`}>{formatMetric(row.def, row.best)}</td>
      <td className="px-4 py-2.5 text-right">
        <Delta def={row.def} value={row.delta} className="text-[12.5px]" />
      </td>
    </motion.tr>
  );
}

/** 本质创新：按知识卡给出的层次逐层讲，最后用同父对照说明收益来自组合方式本身。 */
function Insights({ report }: { report: RunReport }) {
  const insights = report.input.insights ?? [];
  const siblings = report.siblings;
  const primary = primaryDef(report.input);
  return (
    <div className="flex h-full flex-col">
      <Heading title="这个新算法的本质创新" sub="不是又加了一个模型，而是把两种学习方式的“分歧”变成了告警筛选信号" />
      <div className="mt-5 grid gap-3" style={{ gridTemplateColumns: `repeat(${insights.length}, minmax(0, 1fr))` }}>
        {insights.map((s, i) => (
          <motion.div
            key={s.title}
            className="flex flex-col rounded-2xl border border-[var(--evo-border)] p-4"
            initial={{ opacity: 0, y: 24 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.15 + i * 0.6, type: 'spring', stiffness: 200, damping: 20 }}
          >
            <div className="flex items-center gap-2">
              <span className="flex size-6 items-center justify-center rounded-lg bg-[var(--evo-brand)] text-[12px] font-bold text-white">{i + 1}</span>
              <span className="text-[15.5px] font-semibold">{s.title}</span>
            </div>
            {s.formula && <div className="evo-mono mt-3 rounded-lg bg-[var(--evo-brand-50)] px-3 py-2 text-center text-[13.5px] font-semibold text-[var(--evo-brand)]">{s.formula}</div>}
            <div className="mt-3 text-[12.5px] leading-relaxed text-[var(--evo-muted)]">{s.body}</div>
          </motion.div>
        ))}
      </div>
      {siblings.length > 0 && (
        <motion.div className="mt-4 rounded-2xl bg-slate-50 p-4" initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.3 + insights.length * 0.6 }}>
          <div className="text-[12px] font-semibold text-[var(--evo-muted)]">同父对照 · 父算法完全相同，只换组合方式</div>
          <div className="mt-2 grid gap-2" style={{ gridTemplateColumns: `repeat(${siblings.length + 1}, minmax(0, 1fr))` }}>
            <SiblingCard node={report.best} primary={primary} winner />
            {siblings.map((s) => (
              <SiblingCard key={s.id} node={s} primary={primary} />
            ))}
          </div>
        </motion.div>
      )}
    </div>
  );
}

function SiblingCard({ node, primary, winner = false }: { node: ReportNode; primary: Omit<MetricDef, 'key'>; winner?: boolean }) {
  return (
    <div className={`rounded-xl border px-3 py-2 text-[12px] ${winner ? 'border-[var(--evo-brand)] bg-white' : 'border-[var(--evo-border)] bg-white'}`}>
      <div className="flex items-center gap-1.5">
        <span className={`font-semibold ${winner ? 'text-[var(--evo-brand)]' : ''}`}>{operatorLabel(node.operator)}</span>
        <span className={`ml-auto rounded px-1.5 text-[10.5px] ${node.status === 'ok' ? 'bg-green-50 text-[var(--evo-good)]' : 'bg-red-50 text-[var(--evo-bad)]'}`}>{node.status === 'ok' ? '通过' : '未通过'}</span>
      </div>
      <div className="evo-mono mt-0.5 text-[var(--evo-muted)]">
        {primary.label} {formatMetric(primary, node.score)}
      </div>
      {node.note && <div className="mt-0.5 leading-snug text-[var(--evo-muted)]">{node.note}</div>}
    </div>
  );
}

/** 谱系形态的改进点：相对初始解贡献最大的几代改动。 */
function KeyChanges({ report }: { report: RunReport }) {
  const { keyImprovements, gain } = report;
  const primary = primaryDef(report.input);
  if (keyImprovements.length === 0) return <Empty text="最优方案就是初始解，没有可讲的改进点。" />;
  return (
    <div className="flex h-full flex-col">
      <Heading title="最优方案相对初始解的关键改进" sub={`按单步带来的 ${primary.label} 提升排序，取前 ${keyImprovements.length} 项`} />
      <div className="mt-6 grid items-start gap-4" style={{ gridTemplateColumns: `repeat(${keyImprovements.length}, minmax(0, 1fr))` }}>
        {keyImprovements.map((s, i) => (
          <ChangeCard key={s.node.id} step={s} rank={i + 1} share={gain > 0 ? (s.delta / gain) * 100 : 0} primary={primary} />
        ))}
      </div>
    </div>
  );
}

function ChangeCard({ step, rank, share, primary }: { step: ReportStep; rank: number; share: number; primary: Omit<MetricDef, 'key'> }) {
  return (
    <motion.div
      className="flex flex-col rounded-2xl border border-[var(--evo-border)] p-5"
      initial={{ opacity: 0, y: 24 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: (rank - 1) * 0.18, type: 'spring', stiffness: 200, damping: 20 }}
    >
      <div className="flex items-center gap-2">
        <span className="flex size-7 items-center justify-center rounded-lg bg-[var(--evo-brand)] text-[13px] font-bold text-white">{rank}</span>
        <span className="rounded bg-slate-100 px-1.5 text-[11px] text-slate-500">{step.operatorLabel}</span>
        <span className="evo-mono text-[11px] text-[var(--evo-subtle)]">
          {step.parent.id} → {step.node.id}
        </span>
      </div>
      <div className="mt-3 text-[17px] font-semibold">{step.node.title}</div>
      <div className="mt-2 flex items-baseline gap-2">
        <Delta def={primary} value={step.delta} className="text-[26px]" />
        <span className="text-xs text-[var(--evo-muted)]">占总提升 {share.toFixed(0)}%</span>
      </div>
      <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-slate-100">
        <motion.div
          className="h-full rounded-full bg-[var(--evo-brand)]"
          initial={{ width: 0 }}
          animate={{ width: `${Math.min(100, Math.max(0, share))}%` }}
          transition={{ delay: 0.3 + rank * 0.15, duration: 0.8, ease: [0.16, 1, 0.3, 1] }}
        />
      </div>
      {step.node.reflection && <div className="mt-4 text-[13px] leading-relaxed text-[var(--evo-muted)]">{step.node.reflection}</div>}
      {step.borrowedFrom && <div className="mt-4 w-fit rounded-full bg-[var(--evo-brand-50)] px-2.5 py-1 text-[11px] text-[var(--evo-brand)]">知识来源：{step.borrowedFrom}</div>}
    </motion.div>
  );
}

const GRADE_BADGE: Record<ReportClaim['grade'], string> = {
  confirmed: 'CONFIRMED',
  candidate: '新知识 · 候选',
  discovered: '发现',
  refuted: '已证伪',
  undetermined: '未定',
};

function Knowledge({ report }: { report: RunReport }) {
  const { confirmed, candidates, otherClaims } = report;
  const main = confirmed[0] ?? candidates[0];
  if (!main) return <Empty text={`本次运行没有产生新知识${otherClaims.length ? `（${otherClaims.length} 条主张未通过检验）` : ''}。`} />;
  return (
    <div className="flex h-full flex-col justify-center">
      <motion.div
        className="inline-flex w-fit rounded-full bg-[var(--evo-brand)] px-3 py-1 text-sm font-bold text-white"
        initial={{ scale: 0.5, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        transition={{ type: 'spring', stiffness: 260, damping: 14 }}
      >
        {GRADE_BADGE[main.grade]}
      </motion.div>
      <div className="mt-4 text-[24px] leading-snug font-bold">{main.title}</div>
      {main.evidence && main.evidence.length > 0 && (
        <div className="mt-5 grid grid-cols-3 gap-2">
          {main.evidence.map((e, i) => (
            <motion.div
              key={e.label}
              className={`rounded-xl px-3 py-2 ${e.good ? 'bg-[var(--evo-brand-50)]' : 'bg-slate-50'}`}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.2 + i * 0.06 }}
            >
              <div className="text-[11px] text-[var(--evo-muted)]">{e.label}</div>
              <div className={`evo-mono text-[13px] font-semibold ${e.good ? 'text-[var(--evo-brand)]' : ''}`}>{e.value}</div>
            </motion.div>
          ))}
        </div>
      )}
      {main.boundary && <div className="mt-4 text-[13px] leading-relaxed text-[var(--evo-muted)]">{main.boundary}</div>}
      <div className="mt-6 flex flex-wrap gap-2 text-xs text-[var(--evo-muted)]">
        {confirmed.length > 0 && <span className="rounded-full bg-slate-100 px-2.5 py-1">确认 {confirmed.length} 条</span>}
        {candidates.length > 0 && <span className="rounded-full bg-slate-100 px-2.5 py-1">候选 {candidates.length} 条</span>}
        {otherClaims.map((c) => (
          <span key={c.id} className="rounded-full bg-red-50 px-2.5 py-1 text-[var(--evo-bad)]">
            {GRADE_BADGE[c.grade]}：{c.title}
          </span>
        ))}
      </div>
    </div>
  );
}

function Reproducibility({ report }: { report: RunReport }) {
  const primary = primaryDef(report.input);
  const rows = [
    { label: '运行 ID', path: report.input.runId },
    { label: '最终方案', path: `${report.best.id} · ${primary.label} ${formatMetric(primary, report.best.score)}` },
    ...(report.input.artifacts ?? []),
  ];
  return (
    <div className="flex h-full flex-col">
      <div className="text-lg font-semibold">复现清单</div>
      <div className="mt-4 space-y-2">
        {rows.map((r, i) => (
          <motion.div
            key={r.label}
            className="flex items-center justify-between gap-4 rounded-lg border border-[var(--evo-border)] px-4 py-2.5 text-[13px]"
            initial={{ opacity: 0, x: -12 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ delay: i * 0.08 }}
          >
            <span className="shrink-0 text-[var(--evo-muted)]">{r.label}</span>
            <span className="evo-mono truncate">{r.path}</span>
          </motion.div>
        ))}
      </div>
      <div className="flex-1" />
      <div className="mt-4 flex justify-end gap-2">
        <button className="evo-btn evo-btn--ghost">导出报告</button>
        <button className="evo-btn evo-btn--primary">下载最优代码</button>
      </div>
    </div>
  );
}

function Empty({ text }: { text: string }) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-4 text-[var(--evo-muted)]">
      <EvoBot size={64} mood="listen" />
      {text}
    </div>
  );
}
