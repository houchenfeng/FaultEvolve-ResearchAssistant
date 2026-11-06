/**
 * 进化工作台 · 混合云实时：本地与云端协作的真实运行。
 *
 * 主区是实时进化树：服务器每写出一个候选就长出一个节点；同一时刻弹出的“本地评估域”子窗口
 * 跟着节点走——正在评估哪个节点，窗口就展示它在平板场景上的评估流水与预警；点任一节点可回看。
 * 右侧是运行控制与三端事件。数据来自 `/api/edge/*`。
 */
import { AnimatePresence, motion } from 'motion/react';
import { useRef, useState } from 'react';

import type { RemoteCandidate, RemoteState } from '@/features/hybrid/edge-api';

import { EvoBot } from '../bot/EvoBot';
import { Icon } from '../ui';
import { NextButton } from './WorkbenchScreen';
import type { LiveMode } from './hybrid-parts';
import { EventColumn, RemoteControls, TriDomain, useHybridData } from './hybrid-parts';
import { LocalEvalWindow } from './LocalEvalWindow';

export function LiveWorkbenchScreen({
  mode,
  generations,
  autoStart,
  onNext,
}: {
  mode: LiveMode;
  generations: number;
  autoStart: boolean;
  onNext: () => void;
}) {
  const { edge, remote, gpu, gate } = useHybridData();
  const [windowOpen, setWindowOpen] = useState(true);
  const [pinned, setPinned] = useState<string | null>(null);
  const area = useRef<HTMLDivElement>(null);
  if (gate || !edge || !remote) return <>{gate}</>;

  const finished = !remote.running && remote.phase === 'done';
  const evaluating = remote.candidates.find((c) => c.status === 'evaluating');
  const latest = evaluating ?? remote.candidates[remote.candidates.length - 1];
  const focus = (pinned && remote.candidates.find((c) => c.id === pinned)) || latest;

  return (
    <div className="grid h-full grid-rows-[auto_minmax(0,1fr)] gap-3 p-4" data-evo-live="true">
      <TriDomain edge={edge} remote={remote} gpu={gpu} />
      <div className="grid min-h-0 grid-cols-[minmax(0,1fr)_360px] gap-3">
        <div ref={area} className="evo-card relative flex min-h-0 flex-col overflow-hidden p-4">
          <div className="flex items-center gap-2">
            <div className="text-xs font-semibold text-[var(--evo-muted)]">实时进化树 · 服务器生成，本机逐个评估</div>
            <span className="evo-mono text-[10.5px] text-[var(--evo-subtle)]">
              {remote.candidates.length} 个节点 · 第 {remote.remote.generation ?? 0}/{remote.remote.generations ?? '-'} 代
            </span>
            {!windowOpen && (
              <button className="evo-chip ml-auto" onClick={() => setWindowOpen(true)}>
                <Icon name="laptop" size={12} /> 本地评估窗口
              </button>
            )}
          </div>
          <LiveTree remote={remote} focusId={focus?.id} onSelect={(id) => setPinned(id)} />
          <AnimatePresence>
            {windowOpen && (
              <LocalEvalWindow
                edge={edge}
                remote={remote}
                gpu={gpu}
                focus={focus}
                following={!pinned}
                onFollow={() => setPinned(null)}
                onClose={() => setWindowOpen(false)}
                bounds={area}
              />
            )}
          </AnimatePresence>
        </div>
        <div className="flex min-h-0 flex-col gap-3">
          <RemoteControls remote={remote} initialMode={mode} initialGenerations={generations} autoStart={autoStart} />
          <EventColumn edge={edge} remote={remote} />
          <NextButton show={finished} onClick={onNext}>
            进入新知识发现 · 机制辩论赛
          </NextButton>
        </div>
      </div>
    </div>
  );
}

const COL = 196;
const ROW = 74;
const W = 164;
const H = 58;

interface TreeNode {
  id: string;
  parent: string | null;
  depth: number;
  row: number;
  cand?: RemoteCandidate;
  score?: number;
}

function layout(remote: RemoteState): TreeNode[] {
  const nodes = new Map<string, TreeNode>();
  const scoreOf = new Map((remote.remote.population ?? []).map((p) => [p.id, p.score]));
  const add = (id: string, parent: string | null, cand?: RemoteCandidate) => {
    if (nodes.has(id)) return;
    const p = parent ? nodes.get(parent) : undefined;
    nodes.set(id, { id, parent: p ? parent : null, depth: p ? p.depth + 1 : 0, row: 0, cand, score: cand?.ros ?? scoreOf.get(id) });
  };
  for (const c of remote.candidates) {
    if (c.parent && !nodes.has(c.parent)) add(c.parent, null);
    add(c.id, c.parent, c);
  }
  const perDepth = new Map<number, number>();
  for (const n of nodes.values()) {
    n.row = perDepth.get(n.depth) ?? 0;
    perDepth.set(n.depth, n.row + 1);
  }
  return [...nodes.values()];
}

function LiveTree({ remote, focusId, onSelect }: { remote: RemoteState; focusId?: string; onSelect: (id: string) => void }) {
  const nodes = layout(remote);
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const bestId = remote.remote.best?.id;
  const width = Math.max(...nodes.map((n) => n.depth), 0) * COL + W + 24;
  const height = Math.max(...nodes.map((n) => n.row), 0) * ROW + H + 24;
  const pos = (n: TreeNode) => ({ x: 12 + n.depth * COL, y: 12 + n.row * ROW });

  if (nodes.length === 0) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-3 text-[13px] text-[var(--evo-muted)]">
        <EvoBot size={64} mood={remote.running ? 'think' : 'listen'} />
        {remote.running ? '服务器正在生成第一个候选…' : '在右侧启动远端进化：服务器每写出一个候选，这里就长出一个节点，并在本机评估'}
      </div>
    );
  }

  return (
    <div className="evo-scroll mt-3 min-h-0 flex-1 overflow-auto">
      <div className="relative" style={{ width, height }}>
        <svg className="absolute inset-0" width={width} height={height}>
          {nodes.map((n) => {
            const parent = n.parent ? byId.get(n.parent) : undefined;
            if (!parent) return null;
            const a = pos(parent);
            const b = pos(n);
            const x1 = a.x + W;
            const y1 = a.y + H / 2;
            const x2 = b.x;
            const y2 = b.y + H / 2;
            const live = n.cand?.status === 'evaluating';
            return (
              <path
                key={n.id}
                d={`M${x1},${y1} C${x1 + 30},${y1} ${x2 - 30},${y2} ${x2},${y2}`}
                fill="none"
                stroke={live ? 'var(--evo-brand)' : '#CBD5E1'}
                strokeWidth={live ? 2 : 1.5}
                strokeDasharray={live ? '5 4' : undefined}
              />
            );
          })}
        </svg>
        <AnimatePresence initial={false}>
          {nodes.map((n) => {
            const { x, y } = pos(n);
            const c = n.cand;
            const evaluating = c?.status === 'evaluating';
            const focused = n.id === focusId;
            const tone = evaluating
              ? 'border-[var(--evo-brand)] bg-[var(--evo-brand-50)]'
              : c?.status === 'invalid'
                ? 'border-slate-200 bg-slate-50 opacity-70'
                : n.id === bestId
                  ? 'border-amber-300 bg-amber-50'
                  : 'border-[var(--evo-border)] bg-white';
            return (
              <motion.button
                key={n.id}
                initial={{ opacity: 0, scale: 0.6 }}
                animate={{ opacity: 1, scale: 1 }}
                transition={{ type: 'spring', stiffness: 320, damping: 24 }}
                className={`absolute flex items-center gap-2 rounded-xl border px-2.5 text-left ${tone} ${focused ? 'ring-2 ring-[var(--evo-brand)] ring-offset-2' : ''}`}
                style={{ left: x, top: y, width: W, height: H }}
                onClick={() => c && onSelect(n.id)}
                disabled={!c}
              >
                <EvoBot size={26} mood={evaluating ? 'eval' : c?.status === 'invalid' ? 'fail' : n.id === bestId ? 'best' : c ? 'happy' : 'idle'} />
                <div className="min-w-0 flex-1">
                  <div className="evo-mono truncate text-[11.5px] font-semibold">{n.id}</div>
                  <div className="truncate text-[10.5px] text-[var(--evo-muted)]">
                    {!c ? '初始解' : evaluating ? '本机评估中…' : c.status === 'invalid' ? '无效' : `ROS ${n.score?.toFixed(2) ?? '—'}`}
                  </div>
                </div>
                {evaluating && (
                  <motion.span
                    className="absolute -top-1.5 -right-1.5 rounded-full bg-[var(--evo-brand)] px-1.5 text-[9.5px] font-semibold text-white"
                    animate={{ opacity: [1, 0.4, 1] }}
                    transition={{ duration: 1.2, repeat: Infinity }}
                  >
                    评估
                  </motion.span>
                )}
              </motion.button>
            );
          })}
        </AnimatePresence>
      </div>
    </div>
  );
}
