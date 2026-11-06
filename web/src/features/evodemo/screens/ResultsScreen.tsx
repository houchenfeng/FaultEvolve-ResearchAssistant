import { AnimatePresence, motion } from 'motion/react';
import { useEffect, useState } from 'react';

import { EvoBot } from '../bot/EvoBot';
import { DEMO_NODES, DEMO_TRANSFERS, EVIDENCE_CHAIN, NODE_BY_ID } from '../demo-script';
import type { DemoNode } from '../demo-script';
import { AnimatedNumber, Icon, Typewriter } from '../ui';

function lineage(id: string): DemoNode[] {
  const chain: DemoNode[] = [];
  let node = NODE_BY_ID.get(id);
  while (node) {
    chain.unshift(node);
    node = node.parentId ? NODE_BY_ID.get(node.parentId) : undefined;
  }
  return chain;
}

const BEST = NODE_BY_ID.get('T6')!;
const ROOT = NODE_BY_ID.get('T0')!;
const PATH = lineage('T6');
const okTransfers = DEMO_TRANSFERS.filter((t) => t.success).length;

const CHAPTERS = [
  {
    title: '最终框架',
    line: `最优方案 ${BEST.id}「${BEST.title}」是沿这条谱系一步步进化出来的：每一步都由云端提出、本地打分，只保留越过噪声门的改动。`,
  },
  {
    title: '提升了什么',
    line: `同一岛内从基线 ${ROOT.id} 到 ${BEST.id}，ROS 从 ${ROOT.score.toFixed(2)} 提到 ${BEST.score.toFixed(2)}，提升 ${(((BEST.score - ROOT.score) / ROOT.score) * 100).toFixed(1)}%，稳定性指标 Q 与 Jev 同步上升。`,
  },
  {
    title: '创新点',
    line: '三个创新：知识引导的三岛协同进化、云端生成与本地评估分离、以及可审计的新知识发现流程。',
  },
  {
    title: '新知识',
    line: '进化过程中还发现了一条规律：窗口末端归一化 SMART 194 与短期故障风险正相关，已通过确认检验。',
  },
  {
    title: '可复现性',
    line: '每个候选的代码、分数、事件和决策都落盘，评委可以按 manifest 一键复跑。',
  },
] as const;

export function ResultsScreen({ onRestart }: { onRestart: () => void }) {
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
        {CHAPTERS.map((c, i) => (
          <button key={c.title} className="flex flex-1 flex-col items-start gap-1.5" onClick={() => setChapter(i)}>
            <div className="h-1 w-full overflow-hidden rounded-full bg-slate-200">
              <motion.div className="h-full bg-[var(--evo-brand)]" animate={{ width: i < chapter ? '100%' : i === chapter ? (spoken ? '100%' : '45%') : '0%' }} transition={{ duration: 0.6 }} />
            </div>
            <span className={`text-[13px] ${i === chapter ? 'font-semibold text-[var(--evo-brand)]' : 'text-[var(--evo-muted)]'}`}>
              {i + 1} {c.title}
            </span>
          </button>
        ))}
        <button className="evo-chip ml-3" data-active={auto} onClick={() => setAuto((a) => !a)}>
          <Icon name={auto ? 'pause' : 'play'} size={12} /> 自动讲解
        </button>
      </div>

      <div className="grid min-h-0 grid-cols-[260px_minmax(0,1fr)] gap-6">
        <div className="flex flex-col items-center pt-6">
          <div className="evo-card relative mb-5 w-full px-4 py-3 text-[14px] leading-relaxed shadow-lg">
            <Typewriter key={chapter} text={CHAPTERS[chapter].line} speed={30} onDone={() => setSpoken(true)} />
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
              {chapter === 0 && <Framework />}
              {chapter === 1 && <Improvement />}
              {chapter === 2 && <Innovations />}
              {chapter === 3 && <Knowledge />}
              {chapter === 4 && <Reproducibility />}
            </motion.div>
          </AnimatePresence>
        </div>
      </div>
    </div>
  );
}

function Framework() {
  return (
    <div className="flex h-full flex-col">
      <div className="text-lg font-semibold">最优方案的进化谱系</div>
      <div className="text-sm text-[var(--evo-muted)]">时序特征岛 · {PATH.length} 代 · 其中 {PATH.filter((n) => n.operator === 'INJECT').length} 次吸收了其他岛的知识</div>
      <div className="mt-8 flex flex-1 items-center gap-2">
        {PATH.map((node, i) => (
          <div key={node.id} className="flex flex-1 items-center gap-2">
            <motion.div
              className={`flex flex-1 flex-col items-center rounded-xl border px-2 py-6 text-center ${node.id === BEST.id ? 'border-[var(--evo-brand)] bg-[var(--evo-brand)] text-white' : node.operator === 'INJECT' ? 'border-[var(--evo-brand)] bg-[var(--evo-brand-50)]' : 'border-[var(--evo-border)] bg-white'}`}
              initial={{ opacity: 0, y: 20, scale: 0.9 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              transition={{ delay: 0.15 + i * 0.18, type: 'spring', stiffness: 220, damping: 18 }}
            >
              <span className="evo-mono text-[11px] opacity-70">{node.id}</span>
              <span className="mt-1.5 text-[15px] leading-tight font-semibold">{node.title}</span>
              <span className="evo-mono mt-1.5 text-[18px] font-semibold">{node.score.toFixed(2)}</span>
              {node.operator === 'INJECT' && (
                <span className={`mt-1.5 rounded-full px-1.5 text-[10px] ${node.id === BEST.id ? 'bg-white/20' : 'bg-[var(--evo-brand)] text-white'}`}>知识注入</span>
              )}
            </motion.div>
            {i < PATH.length - 1 && (
              <motion.span className="text-[var(--evo-subtle)]" initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.25 + i * 0.18 }}>
                →
              </motion.span>
            )}
          </div>
        ))}
      </div>
      <div className="mt-6 rounded-xl bg-slate-50 px-4 py-3 text-[13px] leading-relaxed text-[var(--evo-muted)]">
        <span className="font-semibold text-[var(--evo-fg)]">{BEST.id} 反思：</span>
        {BEST.reflection}
      </div>
    </div>
  );
}

function Improvement() {
  const stats = [
    { label: 'ROS', from: ROOT.score, to: BEST.score, digits: 2 },
    { label: 'Q 稳定性', from: ROOT.q, to: BEST.q, digits: 2 },
    { label: 'Jev 评审', from: ROOT.jev, to: BEST.jev, digits: 2 },
  ];
  return (
    <div className="flex h-full flex-col">
      <div className="text-lg font-semibold">
        {ROOT.id} 基线 → {BEST.id} 最优
      </div>
      <div className="text-sm text-[var(--evo-muted)]">
        共评估 {DEMO_NODES.length} 个候选 · {DEMO_NODES.filter((n) => n.outcome === 'failed').length} 个失败回退 · {DEMO_NODES.filter((n) => n.outcome === 'pruned').length} 个被剪枝
      </div>
      <div className="mt-8 grid flex-1 grid-cols-3 gap-4">
        {stats.map((s, i) => (
          <motion.div
            key={s.label}
            className="flex flex-col justify-center rounded-2xl border border-[var(--evo-border)] bg-gradient-to-b from-[#F3F7FF] to-white p-6"
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: i * 0.15 }}
          >
            <div className="text-sm text-[var(--evo-muted)]">{s.label}</div>
            <div className="evo-mono mt-2 text-sm text-[var(--evo-subtle)]">{s.from.toFixed(s.digits)} →</div>
            <CountUp from={s.from} to={s.to} digits={s.digits} />
            <div className="evo-mono mt-2 text-sm font-semibold text-[var(--evo-good)]">+{(((s.to - s.from) / s.from) * 100).toFixed(0)}%</div>
          </motion.div>
        ))}
      </div>
    </div>
  );
}

function CountUp({ from, to, digits }: { from: number; to: number; digits: number }) {
  const [value, setValue] = useState(from);
  useEffect(() => {
    const timer = window.setTimeout(() => setValue(to), 250);
    return () => window.clearTimeout(timer);
  }, [to]);
  return <AnimatedNumber value={value} digits={digits} className="evo-mono text-[52px] leading-none font-bold text-[var(--evo-brand)]" />;
}

function Innovations() {
  const items = [
    { icon: 'seed' as const, title: '知识引导的三岛协同进化', body: `时序 / 集成 / 运维三岛并行搜索，${DEMO_TRANSFERS.length} 次跨岛知识注入中 ${okTransfers} 次成功，失败注入自动回退。` },
    { icon: 'cloud' as const, title: '云端生成 · 本地评估分离', body: '大模型在云端（SSH 服务器）提出候选与反思，评估器与原始数据只在本地沙箱运行，云端只收到分数。' },
    { icon: 'shield' as const, title: '可审计的新知识发现', body: '现象 → 预注册 → 确认检验 → 多重比较控制 → 机制辩论 → 跨切片外推，每一步留证据。' },
  ];
  return (
    <div className="grid h-full grid-cols-3 gap-4">
      {items.map((it, i) => (
        <motion.div
          key={it.title}
          className="flex flex-col rounded-2xl border border-[var(--evo-border)] p-6"
          initial={{ opacity: 0, y: 24 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: i * 0.2, type: 'spring', stiffness: 200, damping: 20 }}
        >
          <span className="flex size-11 items-center justify-center rounded-xl bg-[var(--evo-brand-50)] text-[var(--evo-brand)]">
            <Icon name={it.icon} size={22} />
          </span>
          <div className="mt-4 text-[17px] font-semibold">{it.title}</div>
          <div className="mt-2 text-[13.5px] leading-relaxed text-[var(--evo-muted)]">{it.body}</div>
          <div className="flex-1" />
          <EvoBot size={36} shape={(['circle', 'squircle', 'hex'] as const)[i]} mood="idle" />
        </motion.div>
      ))}
    </div>
  );
}

function Knowledge() {
  return (
    <div className="flex h-full flex-col justify-center">
      <motion.div className="inline-flex w-fit rounded-full bg-[var(--evo-brand)] px-3 py-1 text-sm font-bold text-white" initial={{ scale: 0.5, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} transition={{ type: 'spring', stiffness: 260, damping: 14 }}>
        CONFIRMED
      </motion.div>
      <div className="mt-4 text-[26px] leading-snug font-bold">
        窗口末端归一化 <span className="evo-mono text-[var(--evo-brand)]">SMART 194</span>
        <br />与短期 HDD 故障风险正相关
      </div>
      <div className="evo-mono mt-3 text-sm text-[var(--evo-muted)]">n = 9,262 · 效应 0.3124 · 95% CI [0.278, 0.346] · BH 通过</div>
      <div className="mt-8 flex gap-2">
        {EVIDENCE_CHAIN.map((e, i) => (
          <motion.div key={e} className="flex-1 rounded-lg bg-[var(--evo-brand-50)] px-2 py-2 text-center text-xs font-medium text-[var(--evo-brand)]" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.3 + i * 0.12 }}>
            {i + 1}. {e}
          </motion.div>
        ))}
      </div>
      <div className="mt-4 text-xs text-[var(--evo-muted)]">边界：机制对局 16 场平局，结论表述为可复现的关联指示，不写成因果定律。</div>
    </div>
  );
}

function Reproducibility() {
  const rows = [
    ['运行 ID', 'hdd_mvp_showcase_c89e2a01'],
    ['候选程序', `programs/*.py · ${DEMO_NODES.length} 个`],
    ['进化树', 'tree.json'],
    ['事件流', 'events.jsonl'],
    ['知识发现', 'discovery/certificates.json · preregistration.json'],
    ['最终算法说明', 'reports/final_algorithm_README.md'],
  ];
  return (
    <div className="flex h-full flex-col">
      <div className="text-lg font-semibold">复现清单</div>
      <div className="mt-4 space-y-2">
        {rows.map(([k, v], i) => (
          <motion.div key={k} className="flex items-center justify-between rounded-lg border border-[var(--evo-border)] px-4 py-2.5 text-[13px]" initial={{ opacity: 0, x: -12 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * 0.08 }}>
            <span className="text-[var(--evo-muted)]">{k}</span>
            <span className="evo-mono">{v}</span>
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
