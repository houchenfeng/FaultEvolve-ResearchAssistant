/**
 * 论文组合工作台：最新论文复现为父算法，逐批两两组合；每个组合节点按冻结协议在
 * 两个季度各做 5 项检查，全部通过才晋升。
 */
import { AnimatePresence, motion } from 'motion/react';
import { useLayoutEffect, useRef, useState } from 'react';

import { EvoBot } from '../bot/EvoBot';
import type { BotMood } from '../bot/EvoBot';
import type { PaperNode } from '../cases/paper';
import { CHECKS, COLUMNS, PAPERS, PAPER_NODES, PAPER_NODE_BY_ID, QUARTERS, rowsInColumn } from '../cases/paper';
import type { DemoCase } from '../cases/types';
import { operatorLabel } from '../report';
import { AnimatedNumber } from '../ui';
import { useDemoPlayer, useLanding } from '../use-demo-player';
import type { PlayerView } from '../use-demo-player';
import { CloudLocalPanel } from './CloudLocalPanel';
import { EventFeed, LandingOverlay, NextButton, PlayerControls } from './WorkbenchScreen';

type QuarterKey = (typeof QUARTERS)[number]['key'];

const HEADER = 44;
const COMBO_COUNT = PAPER_NODES.filter((n) => n.column > 0).length;

function pct(v: number | undefined, digits = 2) {
  return v === undefined ? '—' : `${(v * 100).toFixed(digits)}%`;
}

function useSize<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [size, setSize] = useState({ width: 900, height: 520 });
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) => setSize({ width: entry.contentRect.width, height: entry.contentRect.height }));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, size] as const;
}

function moodFor(node: PaperNode, view: PlayerView): { mood: BotMood; animated: boolean } {
  const phase = view.phases.get(node.id);
  if (phase === 'proposed') return { mood: 'think', animated: true };
  if (phase === 'evaluating') return { mood: 'eval', animated: true };
  const fresh = view.lastResultId === node.id;
  switch (node.outcome) {
    case 'promoted':
      return { mood: 'best', animated: true };
    case 'rejected':
    case 'silent':
      return { mood: 'pruned', animated: fresh };
    default:
      return { mood: fresh ? 'happy' : 'idle', animated: fresh };
  }
}

export function PaperWorkbenchScreen({ demo, onNext, skipIntro }: { demo: DemoCase; onNext: () => void; skipIntro: boolean }) {
  const landed = useLanding(skipIntro);
  const player = useDemoPlayer(demo, landed);
  const { view } = player;
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [quarter, setQuarter] = useState<QuarterKey>('recent_2026q1');
  const focusId = selectedId ?? view.lastResultId;
  const focus = focusId ? PAPER_NODE_BY_ID.get(focusId) : undefined;
  const evaluated = PAPER_NODES.filter((n) => n.column > 0 && view.phases.get(n.id) === 'done').length;

  return (
    <div className="relative grid h-full grid-cols-[minmax(0,1fr)_340px] gap-4 p-4">
      <div className="flex min-h-0 flex-col gap-4">
        <div className="evo-card relative min-h-0 flex-1 p-3">
          <div className="mb-1 flex items-center gap-3 px-1">
            <div className="text-[16px] font-semibold">论文组合进化</div>
            <div className="text-xs text-[var(--evo-muted)]">每个 Bot 是一个算法 · 父算法来自最新论文 · 组合按冻结协议两域 × 5 项检查</div>
            <div className="flex-1" />
            <Legend />
          </div>
          <div className="relative h-[calc(100%-30px)]">
            <PaperCanvas view={view} selectedId={selectedId} onSelect={setSelectedId} />
          </div>
        </div>
        <div className="h-[200px] shrink-0">
          <CloudLocalPanel view={view} pipeline={demo.pipeline} />
        </div>
      </div>

      <div className="flex min-h-0 flex-col gap-3">
        <div className="evo-card p-4">
          <div className="text-xs text-[var(--evo-muted)]">晋升为新算法候选</div>
          <div className="mt-1 flex items-end gap-2">
            <AnimatedNumber value={view.best ?? 0} digits={0} className="evo-mono text-[40px] leading-none font-bold text-[var(--evo-brand)]" />
            <span className="mb-1 text-[13px] text-[var(--evo-muted)]">
              / {evaluated} 个组合已评估（共 {COMBO_COUNT}）
            </span>
          </div>
          <div className="mt-1.5 text-[11.5px] leading-snug text-[var(--evo-muted)]">两个季度、每季度 5 项检查全部通过才晋升：精确率高于双父、误告不高于双父且 ≤ 0.2%、召回保护、告警 ≥ 10 次。</div>
        </div>

        <div className="evo-card p-3">
          <div className="mb-1 flex items-center gap-2 px-1">
            <span className="text-xs font-semibold text-[var(--evo-muted)]">精确率 × 误告率</span>
            <span className="flex-1" />
            {QUARTERS.map((q) => (
              <button key={q.key} className="evo-chip !px-2 !py-0.5 !text-[11px]" data-active={quarter === q.key} onClick={() => setQuarter(q.key)}>
                {q.label}
              </button>
            ))}
          </div>
          <Scatter view={view} quarter={quarter} focusId={focusId} />
        </div>

        <FocusCard node={focus} />
        <EventFeed view={view} />
        <PlayerControls player={player} total={demo.steps.length} />
        <NextButton show={view.finished} onClick={onNext}>
          进入新知识发现 · 算法辩论赛
        </NextButton>
      </div>

      <LandingOverlay show={!landed} title="把最新论文复现为父算法，开始组合进化" sub={PAPERS.map((p) => p.name).join(' · ')} />
    </div>
  );
}

function PaperCanvas({ view, selectedId, onSelect }: { view: PlayerView; selectedId: string | null; onSelect: (id: string) => void }) {
  const [ref, { width, height }] = useSize<HTMLDivElement>();
  const colW = width / COLUMNS.length;
  const pos = (n: PaperNode) => {
    const rows = rowsInColumn(n.column);
    const h = (height - HEADER) / rows;
    return { x: colW * (n.column + 0.5), y: HEADER + h * (n.row + 0.4) };
  };
  const started = view.index >= 0;
  const visible = PAPER_NODES.filter((n) => view.phases.has(n.id) || (started && n.id === 'tabpfn35'));
  const highlight = selectedId ?? view.lastResultId;

  return (
    <div ref={ref} className="relative h-full w-full">
      {COLUMNS.map((c, i) => (
        <div
          key={c.title}
          className={`absolute top-0 bottom-0 rounded-xl border border-[var(--evo-border)] ${i === 0 ? 'bg-gradient-to-b from-[#EEF4FF] to-white/40' : 'bg-white/40'}`}
          style={{ left: colW * i + 4, width: colW - 8 }}
        >
          <div className="px-3 pt-2 text-center">
            <div className="text-[12.5px] font-semibold">{c.title}</div>
            <div className="text-[10.5px] text-[var(--evo-muted)]">{c.sub}</div>
          </div>
        </div>
      ))}

      <svg className="pointer-events-none absolute inset-0" width={width} height={height}>
        {visible.flatMap((node) =>
          node.parents.map((pid) => {
            const parent = PAPER_NODE_BY_ID.get(pid);
            if (!parent) return null;
            const a = pos(parent);
            const b = pos(node);
            const phase = view.phases.get(node.id);
            const active = phase !== 'done';
            const strong = node.outcome === 'promoted' || node.id === highlight;
            const d = `M${a.x + 18} ${a.y} C${a.x + colW * 0.45} ${a.y}, ${b.x - colW * 0.45} ${b.y}, ${b.x - 18} ${b.y}`;
            return (
              <motion.path
                key={`${pid}-${node.id}`}
                d={d}
                fill="none"
                stroke={active || strong ? '#2563EB' : '#CBD5E1'}
                strokeWidth={strong ? 2.2 : 1.4}
                initial={{ pathLength: 0, opacity: 0 }}
                animate={{ pathLength: 1, opacity: active ? 0.75 : strong ? 0.9 : 0.18 }}
                transition={{ duration: 0.7, ease: [0.16, 1, 0.3, 1] }}
              />
            );
          }),
        )}
      </svg>

      {visible.map((node) => {
        const p = pos(node);
        const { mood, animated } = moodFor(node, view);
        const done = view.phases.get(node.id) === 'done';
        const paper = PAPERS.find((x) => x.id === node.id);
        const blocked = paper?.ready === false;
        const promoted = done && node.outcome === 'promoted';
        return (
          <motion.button
            key={node.id}
            className="absolute flex flex-col items-center"
            style={{ left: p.x - colW / 2 + 6, top: p.y - 16, width: colW - 12 }}
            initial={{ opacity: 0, scale: 0.3 }}
            animate={{ opacity: blocked ? 0.45 : 1, scale: 1 }}
            transition={{ type: 'spring', stiffness: 260, damping: 18 }}
            onClick={() => !blocked && onSelect(node.id)}
          >
            <span className={`rounded-full ${selectedId === node.id ? 'ring-2 ring-[var(--evo-brand)] ring-offset-2' : ''}`}>
              <EvoBot
                size={promoted ? 40 : node.column === 0 ? 32 : 28}
                shape={node.shape}
                mood={blocked ? 'pruned' : mood}
                animated={!blocked && animated}
                color={blocked ? '#94A3B8' : undefined}
              />
            </span>
            <span className="mt-0.5 flex max-w-full items-center gap-1 text-[11px] leading-tight">
              <span className={`truncate font-semibold ${done && node.outcome === 'rejected' ? 'text-[var(--evo-muted)]' : ''}`}>{node.label}</span>
              {node.glyph && <span className="evo-mono shrink-0 rounded bg-slate-100 px-1 text-[9.5px] text-slate-500">{node.glyph}</span>}
            </span>
            {node.column === 0 && paper && <span className="text-[9.5px] text-[var(--evo-subtle)]">{blocked ? '许可受限 · 未运行' : paper.venue}</span>}
            {node.checks && done && <CheckDots node={node} />}
            {promoted && (
              <motion.span
                className="mt-0.5 rounded-full bg-[var(--evo-brand)] px-1.5 text-[10px] font-semibold text-white"
                initial={{ scale: 0 }}
                animate={{ scale: 1 }}
                transition={{ type: 'spring', stiffness: 300, damping: 14 }}
              >
                晋升 · 新算法候选
              </motion.span>
            )}
          </motion.button>
        );
      })}
    </div>
  );
}

function CheckDots({ node }: { node: PaperNode }) {
  return (
    <span className="mt-0.5 flex flex-col gap-[2px]">
      {QUARTERS.map((q) => (
        <span key={q.key} className="flex gap-[2px]">
          {CHECKS.map((c, i) => {
            const ok = node.checks?.[q.key]?.[c.key];
            return (
              <motion.span
                key={c.key}
                className={`size-[5px] rounded-full ${ok ? 'bg-[var(--evo-good)]' : 'bg-[var(--evo-bad)]'}`}
                initial={{ scale: 0 }}
                animate={{ scale: 1 }}
                transition={{ delay: i * 0.05 }}
              />
            );
          })}
        </span>
      ))}
    </span>
  );
}

function Scatter({ view, quarter, focusId }: { view: PlayerView; quarter: QuarterKey; focusId: string | null }) {
  const w = 310;
  const h = 150;
  const pad = { l: 30, r: 8, t: 8, b: 20 };
  const maxFar = 0.2;
  const maxP = 70;
  const x = (far: number) => pad.l + (far / maxFar) * (w - pad.l - pad.r);
  const y = (p: number) => h - pad.b - (p / maxP) * (h - pad.t - pad.b);
  const points = PAPER_NODES.filter((n) => view.phases.get(n.id) === 'done' && (n.metrics[quarter]?.alarm_count ?? 0) > 0);
  return (
    <svg width="100%" viewBox={`0 0 ${w} ${h}`} height={h}>
      <rect x={pad.l} y={pad.t} width={(w - pad.l - pad.r) * 0.4} height={(h - pad.t - pad.b) * 0.45} rx={6} fill="rgb(37 99 235 / 0.06)" />
      <text x={pad.l + 6} y={pad.t + 13} fontSize={9.5} fill="#2563EB">更准、更少误告</text>
      <line x1={pad.l} y1={h - pad.b} x2={w - pad.r} y2={h - pad.b} stroke="#CBD5E1" />
      <line x1={pad.l} y1={pad.t} x2={pad.l} y2={h - pad.b} stroke="#CBD5E1" />
      {[0, 0.1, 0.2].map((t) => (
        <text key={t} x={x(t)} y={h - 6} fontSize={9} fill="#94A3B8" textAnchor="middle">
          {t.toFixed(1)}%
        </text>
      ))}
      {[0, 35, 70].map((t) => (
        <text key={t} x={pad.l - 4} y={y(t) + 3} fontSize={9} fill="#94A3B8" textAnchor="end">
          {t}%
        </text>
      ))}
      <text x={w - pad.r} y={h - pad.b - 4} fontSize={9} fill="#94A3B8" textAnchor="end">
        误告率 →
      </text>
      {points.map((n) => {
        const m = n.metrics[quarter]!;
        const cx = x(m.far * 100);
        const cy = y(m.precision * 100);
        const promoted = n.outcome === 'promoted';
        const focused = n.id === focusId;
        return (
          <motion.g key={n.id} initial={{ opacity: 0, scale: 0 }} animate={{ opacity: 1, scale: 1 }} style={{ originX: `${cx}px`, originY: `${cy}px` }}>
            {n.column === 0 ? (
              <rect x={cx - 4} y={cy - 4} width={8} height={8} rx={1.5} fill="#fff" stroke="#1E3A8A" strokeWidth={1.6} />
            ) : (
              <circle cx={cx} cy={cy} r={promoted ? 5.5 : 3.5} fill={promoted ? '#2563EB' : '#CBD5E1'} stroke={focused ? '#0F172A' : 'none'} strokeWidth={1.5} />
            )}
            {(n.column === 0 || promoted) && (
              <text x={promoted ? cx : cx + 7} y={promoted ? cy + 15 : cy + 3} textAnchor={promoted ? 'middle' : 'start'} fontSize={9.5} fontWeight={promoted ? 700 : 500} fill={promoted ? '#2563EB' : '#334155'}>
                {promoted ? '新组合' : n.label}
              </text>
            )}
          </motion.g>
        );
      })}
    </svg>
  );
}

function FocusCard({ node }: { node: PaperNode | undefined }) {
  return (
    <div className="evo-card min-h-[150px] p-4">
      <AnimatePresence mode="wait">
        {node ? (
          <motion.div key={node.id} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} transition={{ duration: 0.2 }}>
            <div className="flex items-center gap-2">
              <span className="truncate text-[14px] font-semibold">{node.label}</span>
              <span className="shrink-0 rounded bg-slate-100 px-1.5 text-[10px] text-slate-500">{operatorLabel(node.operator)}</span>
              {node.outcome === 'promoted' && <span className="shrink-0 rounded bg-[var(--evo-brand)] px-1.5 text-[10px] font-semibold text-white">晋升</span>}
            </div>
            {node.column === 0 && <div className="mt-0.5 text-[11px] text-[var(--evo-muted)]">{PAPERS.find((p) => p.id === node.id)?.idea}</div>}
            <table className="evo-mono mt-2 w-full text-center text-[11px]">
              <thead className="text-[10px] text-[var(--evo-subtle)]">
                <tr>
                  <th className="text-left font-normal" />
                  <th className="font-normal">精确率</th>
                  <th className="font-normal">误告率</th>
                  <th className="font-normal">召回</th>
                </tr>
              </thead>
              <tbody>
                {QUARTERS.map((q) => {
                  const m = node.metrics[q.key];
                  return (
                    <tr key={q.key}>
                      <td className="text-left text-[var(--evo-muted)]">{q.label}</td>
                      <td className="font-semibold">{m && m.alarm_count > 0 ? pct(m.precision, 1) : '无告警'}</td>
                      <td>{pct(m?.far, 3)}</td>
                      <td>{pct(m?.recall, 1)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            {node.reason && <div className="mt-2 text-[11.5px] leading-snug text-[var(--evo-bad)]">未晋升：{node.reason}</div>}
            {node.outcome === 'promoted' && <div className="mt-2 text-[11.5px] leading-snug text-[var(--evo-good)]">两个季度 10 项检查全部通过</div>}
          </motion.div>
        ) : (
          <div className="flex h-full items-center gap-3 text-xs text-[var(--evo-muted)]">
            <EvoBot size={30} mood="think" /> 正在检索并复现论文…
          </div>
        )}
      </AnimatePresence>
    </div>
  );
}

function Legend() {
  return (
    <div className="flex items-center gap-3 text-[11px] text-[var(--evo-muted)]">
      <span className="flex items-center gap-1">
        <EvoBot size={16} mood="eval" animated={false} /> 运行中
      </span>
      <span className="flex items-center gap-1">
        <EvoBot size={16} mood="best" animated={false} /> 晋升
      </span>
      <span className="flex items-center gap-1">
        <EvoBot size={16} mood="pruned" animated={false} /> 未晋升
      </span>
      <span className="flex items-center gap-1">
        <span className="size-[6px] rounded-full bg-[var(--evo-good)]" />
        <span className="size-[6px] rounded-full bg-[var(--evo-bad)]" /> 检查项
      </span>
    </div>
  );
}
