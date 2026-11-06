/**
 * 结果讲解：讲解员 Bot 按章节讲一次运行的结论。页面只读 `RunReport`，
 * 不包含任何任务相关的文案或数字。
 */
import { AnimatePresence, motion } from 'motion/react';
import { useEffect, useState } from 'react';

import { EvoBot } from '../bot/EvoBot';
import type { ReportStep, RunReport } from '../report';
import { CHAPTERS, narrate, operatorLabel } from '../report';
import { AnimatedNumber, Icon, Typewriter } from '../ui';

const MAX_LAYERS = 6;

export function ResultsScreen({ report, onRestart }: { report: RunReport; onRestart: () => void }) {
  const [chapter, setChapter] = useState(0);
  const [auto, setAuto] = useState(true);
  const [spoken, setSpoken] = useState(false);

  useEffect(() => setSpoken(false), [chapter]);
  useEffect(() => {
    if (!auto || !spoken || chapter >= CHAPTERS.length - 1) return;
    const timer = window.setTimeout(() => setChapter((c) => c + 1), 3000);
    return () => window.clearTimeout(timer);
  }, [auto, spoken, chapter]);

  return (
    <div className="grid h-full grid-rows-[auto_minmax(0,1fr)] gap-4 p-6">
      <div className="flex items-center gap-2">
        {CHAPTERS.map((title, i) => (
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

        <div className="evo-card relative min-h-0 overflow-hidden p-6">
          <AnimatePresence mode="wait">
            <motion.div
              key={chapter}
              className="h-full"
              initial={{ opacity: 0, y: 16 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
              transition={{ duration: 0.35, ease: [0.16, 1, 0.3, 1] }}
            >
              {chapter === 0 && <Solution report={report} />}
              {chapter === 1 && <Improvement report={report} />}
              {chapter === 2 && <KeyChanges report={report} />}
              {chapter === 3 && <Knowledge report={report} />}
              {chapter === 4 && <Reproducibility report={report} />}
            </motion.div>
          </AnimatePresence>
        </div>
      </div>
    </div>
  );
}

function Delta({ value, className = '' }: { value: number; className?: string }) {
  return (
    <span className={`evo-mono font-semibold ${value >= 0 ? 'text-[var(--evo-good)]' : 'text-[var(--evo-bad)]'} ${className}`}>
      {value >= 0 ? '+' : ''}
      {value.toFixed(2)}
    </span>
  );
}

/** 最终方案 = 初始解 + 沿谱系逐代保留下来的改动，自下而上叠成一摞。 */
function Solution({ report }: { report: RunReport }) {
  const { root, best, steps } = report;
  const hidden = Math.max(0, steps.length - MAX_LAYERS);
  const shown = steps.slice(hidden);
  const layers = [...shown].reverse();
  return (
    <div className="flex h-full gap-6">
      <div className="flex min-w-0 flex-1 flex-col">
        <div className="text-lg font-semibold">最终方案是怎么叠出来的</div>
        <div className="text-sm text-[var(--evo-muted)]">
          自下而上：初始解 + 每一代保留下来的改动 · 共 {steps.length} 代
        </div>
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
                <span className={`shrink-0 rounded-full px-2 text-[10.5px] ${s.node.id === best.id ? 'bg-white/20' : 'bg-[var(--evo-brand)] text-white'}`}>
                  借鉴 {s.borrowedFrom}
                </span>
              )}
              <span className="evo-mono w-16 shrink-0 text-right text-[13px]">{s.node.score.toFixed(2)}</span>
              <Delta value={s.delta} className={`w-14 shrink-0 text-right text-[12px] ${s.node.id === best.id ? '!text-white' : ''}`} />
            </motion.div>
          ))}
          {hidden > 0 && <div className="py-1 text-center text-xs text-[var(--evo-subtle)]">… 更早的 {hidden} 代改动</div>}
          <motion.div
            className="flex items-center gap-3 rounded-xl border border-dashed border-slate-300 bg-slate-50 px-4 py-2.5"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: 0.1 }}
          >
            <span className="evo-mono w-12 shrink-0 text-[11px] text-[var(--evo-muted)]">{root.id}</span>
            <span className="shrink-0 rounded bg-slate-200 px-1.5 text-[10.5px] text-slate-500">{operatorLabel(root.operator)}</span>
            <span className="flex-1 text-[14px] font-semibold text-[var(--evo-muted)]">{root.title}</span>
            <span className="evo-mono w-16 text-right text-[13px] text-[var(--evo-muted)]">{root.score.toFixed(2)}</span>
            <span className="w-14" />
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

function Improvement({ report }: { report: RunReport }) {
  const { root, best, counts, metricRows } = report;
  return (
    <div className="flex h-full flex-col">
      <div className="text-lg font-semibold">
        {root.id} 初始解 → {best.id} 最优方案
      </div>
      <div className="text-sm text-[var(--evo-muted)]">
        共评估 {counts.total} 个候选 · {counts.failed} 个失败回退 · {counts.pruned} 个被剪枝
        {counts.groups > 1 && ` · ${counts.groups} 个分支并行`}
      </div>
      <div className="mt-8 grid flex-1 gap-4" style={{ gridTemplateColumns: `repeat(${metricRows.length}, minmax(0, 1fr))` }}>
        {metricRows.map((m, i) => (
          <motion.div
            key={m.label}
            className="flex flex-col justify-center rounded-2xl border border-[var(--evo-border)] bg-gradient-to-b from-[#F3F7FF] to-white p-6"
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: i * 0.15 }}
          >
            <div className="text-sm text-[var(--evo-muted)]">{m.label}</div>
            <div className="evo-mono mt-2 text-sm text-[var(--evo-subtle)]">{m.from.toFixed(2)} →</div>
            <CountUp from={m.from} to={m.to} />
            {m.from !== 0 && (
              <div className="evo-mono mt-2 text-sm font-semibold text-[var(--evo-good)]">
                {m.to >= m.from ? '+' : ''}
                {(((m.to - m.from) / Math.abs(m.from)) * 100).toFixed(0)}%
              </div>
            )}
          </motion.div>
        ))}
      </div>
    </div>
  );
}

function CountUp({ from, to }: { from: number; to: number }) {
  const [value, setValue] = useState(from);
  useEffect(() => {
    const timer = window.setTimeout(() => setValue(to), 250);
    return () => window.clearTimeout(timer);
  }, [to]);
  return <AnimatedNumber value={value} className="evo-mono text-[52px] leading-none font-bold text-[var(--evo-brand)]" />;
}

/** 相对初始解，贡献最大的几代改动：做了什么、为什么有效、占总提升多少。 */
function KeyChanges({ report }: { report: RunReport }) {
  const { keyImprovements, gain } = report;
  if (keyImprovements.length === 0) {
    return <Empty text="最优方案就是初始解，没有可讲的改进点。" />;
  }
  return (
    <div className="flex h-full flex-col">
      <div className="text-lg font-semibold">最优方案相对初始解的关键改进</div>
      <div className="text-sm text-[var(--evo-muted)]">按单步带来的 {report.input.metricName} 提升排序，取前 {keyImprovements.length} 项</div>
      <div className="mt-6 grid items-start gap-4" style={{ gridTemplateColumns: `repeat(${keyImprovements.length}, minmax(0, 1fr))` }}>
        {keyImprovements.map((s, i) => (
          <ChangeCard key={s.node.id} step={s} rank={i + 1} share={gain > 0 ? (s.delta / gain) * 100 : 0} />
        ))}
      </div>
    </div>
  );
}

function ChangeCard({ step, rank, share }: { step: ReportStep; rank: number; share: number }) {
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
        <Delta value={step.delta} className="text-[26px]" />
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
      {step.borrowedFrom && (
        <div className="mt-4 w-fit rounded-full bg-[var(--evo-brand-50)] px-2.5 py-1 text-[11px] text-[var(--evo-brand)]">知识来源：{step.borrowedFrom}</div>
      )}
    </motion.div>
  );
}

function Knowledge({ report }: { report: RunReport }) {
  const { confirmed, otherClaims } = report;
  if (confirmed.length === 0) {
    return <Empty text={`本次运行没有产生确认式知识${otherClaims.length ? `（${otherClaims.length} 条候选主张未通过检验）` : ''}。`} />;
  }
  const [main, ...rest] = confirmed;
  const stats = [
    main.n !== undefined && `n = ${main.n.toLocaleString()}`,
    main.effect !== undefined && `效应 ${main.effect.toFixed(4)}`,
    main.ciLow !== undefined && main.ciHigh !== undefined && `95% CI [${main.ciLow.toFixed(3)}, ${main.ciHigh.toFixed(3)}]`,
    main.fdr,
  ].filter(Boolean);
  return (
    <div className="flex h-full flex-col justify-center">
      <motion.div
        className="inline-flex w-fit rounded-full bg-[var(--evo-brand)] px-3 py-1 text-sm font-bold text-white"
        initial={{ scale: 0.5, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        transition={{ type: 'spring', stiffness: 260, damping: 14 }}
      >
        CONFIRMED
      </motion.div>
      <div className="mt-4 text-[26px] leading-snug font-bold">{main.title}</div>
      {stats.length > 0 && <div className="evo-mono mt-3 text-sm text-[var(--evo-muted)]">{stats.join(' · ')}</div>}
      {main.boundary && <div className="mt-4 text-[13px] text-[var(--evo-muted)]">边界：{main.boundary}</div>}
      <div className="mt-8 flex gap-3 text-xs text-[var(--evo-muted)]">
        <span className="rounded-full bg-slate-100 px-2.5 py-1">确认 {confirmed.length} 条</span>
        {otherClaims.length > 0 && <span className="rounded-full bg-slate-100 px-2.5 py-1">未通过 {otherClaims.length} 条</span>}
        {rest.map((c) => (
          <span key={c.id} className="rounded-full bg-[var(--evo-brand-50)] px-2.5 py-1 text-[var(--evo-brand)]">
            {c.title}
          </span>
        ))}
      </div>
    </div>
  );
}

function Reproducibility({ report }: { report: RunReport }) {
  const rows = [
    { label: '运行 ID', path: report.input.runId },
    { label: '最优候选', path: `${report.best.id} · ${report.input.metricName} ${report.best.score.toFixed(2)}` },
    ...(report.input.artifacts ?? []),
  ];
  return (
    <div className="flex h-full flex-col">
      <div className="text-lg font-semibold">复现清单</div>
      <div className="mt-4 space-y-2">
        {rows.map((r, i) => (
          <motion.div
            key={r.label}
            className="flex items-center justify-between rounded-lg border border-[var(--evo-border)] px-4 py-2.5 text-[13px]"
            initial={{ opacity: 0, x: -12 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ delay: i * 0.08 }}
          >
            <span className="text-[var(--evo-muted)]">{r.label}</span>
            <span className="evo-mono">{r.path}</span>
          </motion.div>
        ))}
      </div>
      <div className="flex-1" />
      <div className="flex justify-end gap-2">
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
