/**
 * 论文组合工作台：每篇可运行的 SOTA 论文复现后成为一座算法岛（树根）。组合节点长在
 * 宿主父算法的岛上（树边），另一个父算法从自己的岛跨岛汇入（飞线）；每个组合按冻结
 * 协议在两个季度各做 5 项检查，全部通过才晋升。
 */
import { AnimatePresence, motion } from 'motion/react';
import { useEffect, useLayoutEffect, useRef, useState } from 'react';

import { EvoBot } from '../bot/EvoBot';
import type { BotMood } from '../bot/EvoBot';
import type { PaperNode } from '../cases/paper';
import { CHECKS, COLUMNS, LANES, PAPERS, PAPER_NODES, PAPER_NODE_BY_ID, QUARTERS, SLOTS, precisionGainPp } from '../cases/paper';
import type { DemoCase } from '../cases/types';
import { operatorLabel } from '../report';
import { AnimatedNumber } from '../ui';
import { useDemoPlayer, useLanding } from '../use-demo-player';
import type { PlayerView } from '../use-demo-player';
import { CloudLocalPanel } from './CloudLocalPanel';
import { EventFeed, LandingOverlay, NextButton, PlayerControls } from './WorkbenchScreen';

type QuarterKey = (typeof QUARTERS)[number]['key'];

const HEADER = 36;
const GUTTER = 138;
const LANE_GAP = 8;
const LANE_WEIGHT = [1, 1, 1, 0.62];
const COMBO_COUNT = PAPER_NODES.filter((n) => n.column > 0).length;
const PAPER_BY_ID = new Map(PAPERS.map((p) => [p.id, p]));

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
          <div className="mb-2 flex items-center gap-3 px-1">
            <div className="shrink-0 text-[16px] font-semibold">多岛论文组合进化</div>
            <div className="min-w-0 truncate text-xs text-[var(--evo-muted)]">每篇 SOTA 论文一座岛 · 组合在宿主岛生长，另一父算法跨岛汇入</div>
            <div className="flex-1" />
            <Legend />
          </div>
          <div className="relative h-[calc(100%-36px)]">
            <IslandCanvas view={view} selectedId={selectedId} onSelect={setSelectedId} />
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

      <LandingOverlay
        show={!landed}
        title="4 篇 SOTA 论文复现为 4 座算法岛，开始跨岛组合进化"
        sub={`${LANES.map((id) => `${PAPER_BY_ID.get(id)?.name} 岛`).join(' · ')}（Mitra-v2 第 2 批加入）`}
      />
    </div>
  );
}

interface Point {
  x: number;
  y: number;
}

function IslandCanvas({ view, selectedId, onSelect }: { view: PlayerView; selectedId: string | null; onSelect: (id: string) => void }) {
  const [ref, { width, height }] = useSize<HTMLDivElement>();
  const unit = (height - HEADER - LANE_GAP * (LANES.length - 1)) / LANE_WEIGHT.reduce((a, b) => a + b, 0);
  const laneTop = LANE_WEIGHT.map((_, i) => HEADER + LANE_WEIGHT.slice(0, i).reduce((a, b) => a + b * unit + LANE_GAP, 0));
  const laneH = (lane: number) => LANE_WEIGHT[lane] * unit;
  const slotStart = GUTTER + 64;
  const slotW = (width - slotStart - 4) / SLOTS.length;
  const slotX = (slot: number) => (slot === 0 ? GUTTER + 26 : slotStart + slotW * (slot - 0.5));
  const trunkY = (lane: number) => laneTop[lane] + laneH(lane) / 2 + 4;

  /** 上排节点整块（Bot + 名称 + 检查点）落在树干之上，下排落在树干之下，树干不压字。 */
  const pos = (n: PaperNode): Point => {
    const y = trunkY(n.lane);
    return { x: slotX(n.slot), y: n.column === 0 ? y : n.upper ? y - 33 : y + 18 };
  };

  const visible = PAPER_NODES.filter((n) => n.lane >= 0 && view.phases.has(n.id));
  const highlight = selectedId ?? view.lastResultId;

  return (
    <div ref={ref} className="relative h-full w-full">
      {[1, 2, 3].map((column) => {
        const first = SLOTS.findIndex((s) => s.column === column) + 1;
        const left = slotStart + slotW * (first - 1);
        return (
          <div key={column} className="absolute top-0 text-center" style={{ left, width: slotW * 2 }}>
            <div className="text-[12px] leading-tight font-semibold">{COLUMNS[column].title}</div>
            <div className="flex">
              {SLOTS.filter((s) => s.column === column).map((s) => (
                <div key={s.title + s.depth} className="flex-1 truncate text-[10px] leading-tight text-[var(--evo-brand)]">
                  {s.title}
                </div>
              ))}
            </div>
          </div>
        );
      })}

      {LANES.map((id, lane) => {
        const paper = PAPER_BY_ID.get(id)!;
        const late = id === 'mitra';
        return (
          <div
            key={id}
            className="absolute right-0 left-0 rounded-xl border border-[var(--evo-border)] bg-gradient-to-r from-[#F3F7FF] to-white/40"
            style={{ top: laneTop[lane], height: laneH(lane) }}
          >
            <div className="absolute top-1/2 left-3 w-[118px] -translate-y-1/2">
              <div className="text-[13px] leading-tight font-semibold">{paper.name} 岛</div>
              <div className="text-[10.5px] leading-tight text-[var(--evo-muted)]">{paper.venue}</div>
              {late ? (
                <span className="mt-0.5 inline-block rounded bg-indigo-50 px-1 text-[9.5px] font-semibold text-indigo-600">第 2 批加入</span>
              ) : (
                <div className="mt-0.5 text-[10.5px] leading-tight text-[var(--evo-subtle)]">{paper.idea}</div>
              )}
            </div>
          </div>
        );
      })}

      {[2, 4].map((s) => (
        <div key={s} className="absolute border-l border-dashed border-slate-200" style={{ left: slotStart + slotW * s, top: 2, bottom: 0 }} />
      ))}

      <svg className="pointer-events-none absolute inset-0" width={width} height={height}>
        {visible
          .filter((n) => n.host)
          .map((node) => {
            const host = PAPER_NODE_BY_ID.get(node.host!)!;
            const a = pos(host);
            const b = pos(node);
            const done = view.phases.get(node.id) === 'done';
            const rejected = done && node.outcome === 'rejected';
            const strong = node.outcome === 'promoted' || node.id === highlight;
            const fromRoot = host.column === 0;
            const bend = b.x - slotW * 0.48;
            const trunk = fromRoot ? `M${a.x + 15} ${a.y} H${bend}` : '';
            const curve = fromRoot
              ? `M${bend} ${a.y} C${b.x - slotW * 0.22} ${a.y}, ${b.x - slotW * 0.32} ${b.y}, ${b.x - 13} ${b.y}`
              : `M${a.x + 16} ${a.y} C${a.x + slotW * 0.5} ${a.y}, ${b.x - slotW * 0.5} ${b.y}, ${b.x - 13} ${b.y}`;
            return (
              <g key={`tree-${node.id}`}>
                {trunk && (
                  <motion.path d={trunk} fill="none" stroke="#93B4F5" strokeWidth={1.6} initial={{ pathLength: 0 }} animate={{ pathLength: 1 }} transition={{ duration: 0.6, ease: [0.16, 1, 0.3, 1] }} />
                )}
                <motion.path
                  d={curve}
                  fill="none"
                  stroke={rejected && !strong ? '#CBD5E1' : '#93B4F5'}
                  strokeWidth={strong ? 2.2 : 1.6}
                  strokeDasharray={rejected ? '4 4' : undefined}
                  initial={{ pathLength: 0 }}
                  animate={{ pathLength: 1 }}
                  transition={{ duration: 0.6, delay: trunk ? 0.4 : 0, ease: [0.16, 1, 0.3, 1] }}
                />
              </g>
            );
          })}
        {visible
          .filter((n) => n.partner)
          .map((node) => {
            const partner = PAPER_NODE_BY_ID.get(node.partner!)!;
            const phase = view.phases.get(node.id);
            const strong = node.outcome === 'promoted' || node.id === highlight;
            const tone = phase !== 'done' ? 'active' : strong ? (node.outcome === 'promoted' ? 'promoted' : 'focus') : 'faded';
            return <MergeArc key={`merge-${node.id}`} from={pos(partner)} to={pos(node)} tone={tone} flying={phase === 'proposed'} />;
          })}
      </svg>

      {visible.map((node) => (
        <IslandNode key={node.id} node={node} at={pos(node)} width={Math.min(slotW - 4, 132)} view={view} selected={selectedId === node.id} onSelect={onSelect} />
      ))}
    </div>
  );
}

const ARC_STYLE = {
  active: { stroke: '#6366F1', width: 1.6, opacity: 0.85, dash: undefined },
  promoted: { stroke: '#2563EB', width: 2.2, opacity: 0.95, dash: undefined },
  focus: { stroke: '#6366F1', width: 1.8, opacity: 0.8, dash: '5 4' },
  faded: { stroke: '#A5B4FC', width: 1.2, opacity: 0.28, dash: '5 4' },
} as const;

/** 另一个父算法跨岛汇入组合节点的飞线；提出阶段有粒子沿线飞过去。 */
function MergeArc({ from, to, tone, flying }: { from: Point; to: Point; tone: keyof typeof ARC_STYLE; flying: boolean }) {
  const pathRef = useRef<SVGPathElement>(null);
  const dotRef = useRef<SVGCircleElement>(null);
  const side = from.y > to.y ? 1 : -1;
  const endY = to.y + side * 13;
  const d = `M${from.x + 14} ${from.y} C${from.x + 90} ${from.y}, ${to.x - 24} ${endY + side * 40}, ${to.x - 2} ${endY}`;
  const style = ARC_STYLE[tone];

  useEffect(() => {
    if (!flying) return;
    const path = pathRef.current;
    const dot = dotRef.current;
    if (!path || !dot) return;
    const len = path.getTotalLength();
    const start = performance.now();
    let raf = 0;
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / 1200);
      const p = path.getPointAtLength(len * (1 - Math.pow(1 - t, 3)));
      dot.setAttribute('cx', String(p.x));
      dot.setAttribute('cy', String(p.y));
      dot.setAttribute('opacity', t >= 1 ? '0' : '1');
      if (t < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [flying, d]);

  return (
    <g>
      <motion.path
        ref={pathRef}
        d={d}
        fill="none"
        stroke={style.stroke}
        strokeWidth={style.width}
        strokeDasharray={style.dash}
        initial={{ pathLength: 0, opacity: 0 }}
        animate={{ pathLength: 1, opacity: style.opacity }}
        transition={{ duration: 1.1, ease: [0.16, 1, 0.3, 1] }}
      />
      <circle ref={dotRef} r={4.5} fill="#6366F1" opacity={0}>
        <animate attributeName="r" values="3.5;5.5;3.5" dur="0.6s" repeatCount="indefinite" />
      </circle>
    </g>
  );
}

function IslandNode({
  node,
  at,
  width,
  view,
  selected,
  onSelect,
}: {
  node: PaperNode;
  at: Point;
  width: number;
  view: PlayerView;
  selected: boolean;
  onSelect: (id: string) => void;
}) {
  const { mood, animated } = moodFor(node, view);
  const done = view.phases.get(node.id) === 'done';
  const promoted = done && node.outcome === 'promoted';
  const size = promoted ? 32 : node.column === 0 ? 28 : 24;
  const gain = precisionGainPp(node);
  const q1 = node.metrics.recent_2026q1;
  return (
    <motion.button
      className="absolute flex flex-col items-center"
      style={{ left: at.x - width / 2, top: at.y - size / 2, width }}
      initial={{ opacity: 0, scale: 0.3 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ type: 'spring', stiffness: 260, damping: 18 }}
      onClick={() => onSelect(node.id)}
    >
      <span className={`relative rounded-full ${selected ? 'ring-2 ring-[var(--evo-brand)] ring-offset-2' : ''}`}>
        <EvoBot size={size} shape={node.shape} mood={mood} animated={animated} />
        {node.code && (
          <span
            className={`evo-mono absolute top-1/2 right-full mr-1 -translate-y-1/2 rounded px-1 text-[9px] leading-[13px] font-semibold ${promoted ? 'bg-[var(--evo-brand)] text-white' : 'bg-slate-100 text-slate-500'}`}
          >
            {node.code}
          </span>
        )}
        {node.checks && done && (
          <span className="absolute top-1/2 left-full ml-1 -translate-y-1/2">
            <CheckDots node={node} />
          </span>
        )}
        {promoted && (
          <motion.span
            className="absolute bottom-full left-1/2 mb-0.5 -translate-x-1/2 rounded-full bg-[var(--evo-brand)] px-1.5 text-[10px] font-semibold whitespace-nowrap text-white shadow-sm"
            initial={{ scale: 0 }}
            animate={{ scale: 1 }}
            transition={{ type: 'spring', stiffness: 300, damping: 14 }}
          >
            晋升 · 新算法
          </motion.span>
        )}
      </span>
      {node.column === 0 ? (
        <span className="evo-mono mt-0.5 text-[10.5px] leading-tight text-[var(--evo-muted)]">
          {!done ? '复现中' : node.outcome === 'silent' ? '无告警' : `P ${pct(q1?.precision, 1)}`}
        </span>
      ) : (
        <span className={`mt-0.5 max-w-full truncate text-[10.5px] leading-tight font-semibold ${done && node.outcome === 'rejected' ? 'text-[var(--evo-muted)]' : ''}`}>{node.label}</span>
      )}
      <AnimatePresence>
        {done && !promoted && view.lastResultId === node.id && gain !== undefined && (
          <motion.span
            className={`evo-mono absolute -top-5 rounded-full px-1.5 text-[10px] font-semibold ${gain > 0 ? 'bg-green-50 text-[var(--evo-good)]' : 'bg-red-50 text-[var(--evo-bad)]'}`}
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: -4 }}
            exit={{ opacity: 0 }}
          >
            P {gain > 0 ? '+' : ''}
            {gain.toFixed(1)}pp
          </motion.span>
        )}
      </AnimatePresence>
    </motion.button>
  );
}

function CheckDots({ node }: { node: PaperNode }) {
  return (
    <span className="flex flex-col gap-[1.5px]">
      {QUARTERS.map((q) => (
        <span key={q.key} className="flex gap-[1.5px]">
          {CHECKS.map((c, i) => {
            const ok = node.checks?.[q.key]?.[c.key];
            return (
              <motion.span
                key={c.key}
                className={`size-[4.5px] rounded-full ${ok ? 'bg-[var(--evo-good)]' : 'bg-[var(--evo-bad)]'}`}
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
                {promoted ? 'CAF' : n.label}
              </text>
            )}
          </motion.g>
        );
      })}
    </svg>
  );
}

function FocusCard({ node }: { node: PaperNode | undefined }) {
  const host = node?.host ? PAPER_NODE_BY_ID.get(node.host) : undefined;
  const partner = node?.partner ? PAPER_NODE_BY_ID.get(node.partner) : undefined;
  return (
    <div className="evo-card min-h-[150px] p-4">
      <AnimatePresence mode="wait">
        {node ? (
          <motion.div key={node.id} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} transition={{ duration: 0.2 }}>
            <div className="flex items-center gap-2">
              <span className="truncate text-[14px] font-semibold">{node.column === 0 ? `${node.label} 岛` : node.label}</span>
              {node.outcome === 'promoted' && <span className="shrink-0 rounded bg-[var(--evo-brand)] px-1.5 text-[10px] font-semibold text-white">晋升</span>}
            </div>
            <div className="mt-0.5 text-[11px] text-[var(--evo-muted)]">
              {node.column === 0 ? (
                `${PAPER_BY_ID.get(node.id)?.venue} · ${PAPER_BY_ID.get(node.id)?.idea}`
              ) : (
                <>
                  <span className="font-semibold text-[var(--evo-brand)]">
                    {operatorLabel(node.operator)} · {node.code}
                  </span>
                  {host && partner && ` · 宿主 ${host.column === 0 ? `${host.label} 岛` : host.label}，${partner.label} 跨岛汇入`}
                </>
              )}
            </div>
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
    <div className="flex shrink-0 items-center gap-3 text-[11px] text-[var(--evo-muted)]">
      <span className="flex items-center gap-1">
        <EvoBot size={16} mood="best" animated={false} /> 晋升
      </span>
      <span className="flex items-center gap-1">
        <EvoBot size={16} mood="pruned" animated={false} /> 未晋升
      </span>
      <span className="flex items-center gap-1">
        <span className="h-0.5 w-4 bg-[#93B4F5]" /> 同岛父代
      </span>
      <span className="flex items-center gap-1">
        <span className="h-0.5 w-4 bg-indigo-500" /> 跨岛汇入
      </span>
    </div>
  );
}
