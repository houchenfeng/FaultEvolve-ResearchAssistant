import { AnimatePresence, motion } from 'motion/react';
import { useEffect, useLayoutEffect, useRef, useState } from 'react';

import { EvoBot } from '../bot/EvoBot';
import type { BotMood } from '../bot/EvoBot';
import { ISLAND_SHAPE } from '../bot/shapes';
import type { DemoNode, Transfer } from '../demo-script';
import { DEMO_NODES, ISLAND_META, ISLAND_ORDER, MAX_DEPTH, NODE_BY_ID } from '../demo-script';
import type { PlayerView } from '../use-demo-player';

const GUTTER = 150;
const LANE_GAP = 10;
const NODE = 30;

interface Point {
  x: number;
  y: number;
}

function useSize<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [size, setSize] = useState({ width: 900, height: 520 });
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) => {
      setSize({ width: entry.contentRect.width, height: entry.contentRect.height });
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, size] as const;
}

function moodFor(node: DemoNode, view: PlayerView): { mood: BotMood; animated: boolean } {
  const phase = view.phases.get(node.id);
  if (phase === 'proposed') return { mood: 'think', animated: true };
  if (phase === 'evaluating') return { mood: 'eval', animated: true };
  const fresh = view.lastResultId === node.id && view.step?.kind === 'result';
  switch (node.outcome) {
    case 'failed':
      return { mood: 'fail', animated: fresh };
    case 'pruned':
      return { mood: 'pruned', animated: fresh };
    case 'best':
      return { mood: 'best', animated: true };
    case 'improved':
      return fresh ? { mood: 'happy', animated: true } : { mood: 'idle', animated: false };
    case 'baseline':
      return { mood: 'idle', animated: fresh };
  }
}

export function EvolutionCanvas({
  view,
  selectedId,
  onSelect,
}: {
  view: PlayerView;
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  const [ref, { width, height }] = useSize<HTMLDivElement>();
  const laneH = (height - LANE_GAP * 2) / 3;
  const colW = (width - GUTTER - 70) / MAX_DEPTH;

  const pos = (node: DemoNode): Point => {
    const lane = ISLAND_ORDER.indexOf(node.island);
    const top = lane * (laneH + LANE_GAP);
    return {
      x: GUTTER + 30 + node.depth * colW,
      y: top + 26 + (node.y / 200) * (laneH - 66),
    };
  };

  const visible = DEMO_NODES.filter((n) => view.phases.has(n.id));

  return (
    <div ref={ref} className="relative h-full w-full">
      {ISLAND_ORDER.map((key, lane) => (
        <div
          key={key}
          className="absolute right-0 left-0 rounded-xl border border-[var(--evo-border)] bg-gradient-to-r from-[#F3F7FF] to-white/40"
          style={{ top: lane * (laneH + LANE_GAP), height: laneH }}
        >
          <div className="absolute top-1/2 left-4 flex -translate-y-1/2 items-center gap-2.5">
            <EvoBot size={26} shape={ISLAND_SHAPE[key]} animated={false} color="#93B4F5" />
            <div>
              <div className="text-[13px] font-semibold">{ISLAND_META[key].name}</div>
              <div className="max-w-[92px] text-[11px] leading-tight text-[var(--evo-muted)]">{ISLAND_META[key].focus}</div>
            </div>
          </div>
        </div>
      ))}

      <svg className="pointer-events-none absolute inset-0" width={width} height={height}>
        {visible.map((node) => {
          const parent = node.parentId ? NODE_BY_ID.get(node.parentId) : undefined;
          if (!parent) return null;
          const a = pos(parent);
          const b = pos(node);
          const dashed = node.outcome === 'failed' || node.outcome === 'pruned';
          const done = view.phases.get(node.id) === 'done';
          const d = `M${a.x + NODE / 2} ${a.y} C${a.x + colW / 2} ${a.y}, ${b.x - colW / 2} ${b.y}, ${b.x - NODE / 2} ${b.y}`;
          return (
            <motion.path
              key={node.id}
              d={d}
              fill="none"
              stroke={done && dashed ? '#CBD5E1' : '#93B4F5'}
              strokeWidth={1.6}
              strokeDasharray={done && dashed ? '4 4' : undefined}
              initial={{ pathLength: 0 }}
              animate={{ pathLength: 1 }}
              transition={{ duration: 0.6, ease: [0.16, 1, 0.3, 1] }}
            />
          );
        })}
        {view.shownTransfers.map((t) => (
          <TransferPath key={`${t.from}-${t.to}`} transfer={t} from={pos(NODE_BY_ID.get(t.from)!)} to={pos(NODE_BY_ID.get(t.to)!)} flying={view.flyingTransfers.includes(t)} />
        ))}
      </svg>

      {visible.map((node) => {
        const p = pos(node);
        const { mood, animated } = moodFor(node, view);
        const done = view.phases.get(node.id) === 'done';
        const shape = ISLAND_SHAPE[node.island];
        return (
          <motion.button
            key={node.id}
            className="absolute flex flex-col items-center"
            style={{ left: p.x - 40, top: p.y - NODE / 2, width: 80 }}
            initial={{ opacity: 0, scale: 0.3 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ type: 'spring', stiffness: 260, damping: 18 }}
            onClick={() => onSelect(node.id)}
          >
            <span className={`rounded-full ${selectedId === node.id ? 'ring-2 ring-[var(--evo-brand)] ring-offset-2' : ''}`}>
              <EvoBot size={node.outcome === 'best' && done ? 38 : NODE} shape={shape} mood={mood} animated={animated} />
            </span>
            <span className="evo-mono mt-1 text-[10.5px] leading-tight text-[var(--evo-muted)]">
              {node.id}
              {done && <span className="ml-1 font-semibold text-[var(--evo-fg)]">{node.score.toFixed(2)}</span>}
            </span>
            <AnimatePresence>
              {done && view.lastResultId === node.id && node.depth > 0 && (
                <motion.span
                  className={`evo-mono absolute -top-5 rounded-full px-1.5 text-[10px] font-semibold ${node.delta > 0 ? 'bg-green-50 text-[var(--evo-good)]' : 'bg-red-50 text-[var(--evo-bad)]'}`}
                  initial={{ opacity: 0, y: 6 }}
                  animate={{ opacity: 1, y: -4 }}
                  exit={{ opacity: 0 }}
                >
                  {node.delta > 0 ? '+' : ''}
                  {node.delta.toFixed(2)}
                </motion.span>
              )}
            </AnimatePresence>
            {node.outcome === 'best' && done && (
              <span className="mt-0.5 rounded-full bg-[var(--evo-brand)] px-1.5 text-[10px] font-semibold text-white">全局最优</span>
            )}
          </motion.button>
        );
      })}
    </div>
  );
}

function TransferPath({ transfer, from, to, flying }: { transfer: Transfer; from: Point; to: Point; flying: boolean }) {
  const pathRef = useRef<SVGPathElement>(null);
  const dotRef = useRef<SVGCircleElement>(null);
  const d = `M${from.x} ${from.y + 14} C${from.x + 60} ${(from.y + to.y) / 2}, ${to.x - 60} ${(from.y + to.y) / 2}, ${to.x} ${to.y - 14 * Math.sign(to.y - from.y)}`;

  useEffect(() => {
    if (!flying) return;
    const path = pathRef.current;
    const dot = dotRef.current;
    if (!path || !dot) return;
    const len = path.getTotalLength();
    const start = performance.now();
    let raf = 0;
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / 1100);
      const e = 1 - Math.pow(1 - t, 3);
      const p = path.getPointAtLength(len * e);
      dot.setAttribute('cx', String(p.x));
      dot.setAttribute('cy', String(p.y));
      dot.setAttribute('opacity', t >= 1 ? '0' : '1');
      if (t < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [flying, d]);

  const color = transfer.success ? '#2563EB' : '#F87171';
  const mid = { x: (from.x + to.x) / 2, y: (from.y + to.y) / 2 };
  return (
    <g>
      <motion.path
        ref={pathRef}
        d={d}
        fill="none"
        stroke={color}
        strokeWidth={1.8}
        strokeDasharray={transfer.success ? undefined : '5 4'}
        initial={{ pathLength: 0, opacity: 0 }}
        animate={{ pathLength: 1, opacity: 0.9 }}
        transition={{ duration: 1.1, ease: [0.16, 1, 0.3, 1] }}
      />
      <circle ref={dotRef} r={5} fill={color} opacity={0}>
        <animate attributeName="r" values="4;6;4" dur="0.6s" repeatCount="indefinite" />
      </circle>
      <motion.g initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.6 }}>
        <rect x={mid.x - 62} y={mid.y - 10} width={124} height={20} rx={10} fill="#fff" stroke={color} strokeOpacity={0.4} />
        <text x={mid.x} y={mid.y + 4} textAnchor="middle" fontSize={10.5} fill={color} fontWeight={600}>
          {transfer.success ? '知识注入' : '注入失败'} · {transfer.gain.replace(' ROS', '')}
        </text>
      </motion.g>
    </g>
  );
}
