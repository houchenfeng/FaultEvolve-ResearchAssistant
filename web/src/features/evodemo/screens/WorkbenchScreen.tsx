import { AnimatePresence, motion } from 'motion/react';
import type { ReactNode } from 'react';
import { useState } from 'react';

import { EvoBot } from '../bot/EvoBot';
import type { DemoCase } from '../cases/types';
import { BASELINE_SCORE, NODE_BY_ID } from '../demo-script';
import { AnimatedNumber, Icon } from '../ui';
import { useDemoPlayer, useLanding } from '../use-demo-player';
import type { PlayerView } from '../use-demo-player';
import { CloudLocalPanel } from './CloudLocalPanel';
import { EvolutionCanvas } from './EvolutionCanvas';

const TONE_CLASS = {
  info: 'bg-slate-100 text-slate-500',
  good: 'bg-green-50 text-[var(--evo-good)]',
  bad: 'bg-red-50 text-[var(--evo-bad)]',
  cloud: 'bg-[var(--evo-brand-50)] text-[var(--evo-brand)]',
  inject: 'bg-indigo-50 text-indigo-600',
} as const;

/** 进场时主角 Bot 跳到中央的遮罩，配合 `useLanding` 使用。 */
export function LandingOverlay({ show, title, sub }: { show: boolean; title: string; sub: string }) {
  return (
    <AnimatePresence>
      {show && (
        <motion.div
          className="absolute inset-0 z-30 flex flex-col items-center justify-center bg-white/60 backdrop-blur-[2px]"
          exit={{ opacity: 0 }}
          transition={{ duration: 0.4 }}
        >
          <motion.div layoutId="hero-bot" transition={{ type: 'spring', stiffness: 110, damping: 13 }}>
            <EvoBot size={104} mood="happy" />
          </motion.div>
          <motion.div className="mt-5 text-lg font-semibold" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.5 }}>
            {title}
          </motion.div>
          <motion.div className="mt-1 text-sm text-[var(--evo-muted)]" initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.7 }}>
            {sub}
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

export function EventFeed({ view }: { view: PlayerView }) {
  return (
    <div className="evo-card flex min-h-0 flex-1 flex-col p-4">
      <div className="mb-2 text-xs font-semibold text-[var(--evo-muted)]">实时事件</div>
      <div className="evo-scroll min-h-0 flex-1 space-y-1.5 overflow-auto">
        <AnimatePresence initial={false}>
          {view.events.slice(0, 14).map((e) => (
            <motion.div
              key={e.id}
              layout
              className="flex items-start gap-2 text-[12px]"
              initial={{ opacity: 0, x: 12 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0 }}
            >
              <span className={`evo-mono mt-px shrink-0 rounded px-1.5 text-[10px] font-semibold ${TONE_CLASS[e.tone]}`}>{e.tag}</span>
              <span className="leading-snug">{e.text}</span>
            </motion.div>
          ))}
        </AnimatePresence>
      </div>
    </div>
  );
}

export function PlayerControls({ player, total }: { player: ReturnType<typeof useDemoPlayer>; total: number }) {
  return (
    <div className="evo-card flex items-center gap-1.5 p-2">
      <button className="evo-btn evo-btn--ghost !px-2.5" onClick={player.toggle} aria-label="播放/暂停">
        <Icon name={player.playing ? 'pause' : 'play'} />
      </button>
      <button className="evo-btn evo-btn--ghost !px-2.5" onClick={player.restart} aria-label="重新播放">
        <Icon name="restart" />
      </button>
      <button className="evo-btn evo-btn--ghost !px-2.5" onClick={player.skipToEnd} aria-label="跳到结束">
        <Icon name="skip" />
      </button>
      {[1, 2, 4].map((s) => (
        <button key={s} className="evo-chip !px-2 !py-1" data-active={player.speed === s} onClick={() => player.setSpeed(s)}>
          {s}×
        </button>
      ))}
      <div className="flex-1" />
      <span className="evo-mono text-[11px] text-[var(--evo-subtle)]">
        {Math.max(0, player.view.index + 1)}/{total}
      </span>
    </div>
  );
}

export function NextButton({ show, onClick, children }: { show: boolean; onClick: () => void; children: ReactNode }) {
  return (
    <AnimatePresence>
      {show && (
        <motion.button
          className="evo-btn evo-btn--primary justify-center !py-3"
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0 }}
          onClick={onClick}
        >
          {children} <Icon name="arrow" />
        </motion.button>
      )}
    </AnimatePresence>
  );
}

export function WorkbenchScreen({ demo, onNext, skipIntro }: { demo: DemoCase; onNext: () => void; skipIntro: boolean }) {
  const landed = useLanding(skipIntro);
  const player = useDemoPlayer(demo, landed);
  const { view } = player;
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const focusId = selectedId ?? view.lastResultId;
  const focus = focusId ? NODE_BY_ID.get(focusId) : undefined;
  const best = view.best ?? BASELINE_SCORE;

  return (
    <div className="relative grid h-full grid-cols-[minmax(0,1fr)_330px] gap-4 p-4">
      <div className="flex min-h-0 flex-col gap-4">
        <div className="evo-card relative min-h-0 flex-1 p-3">
          <div className="mb-2 flex items-center gap-3 px-1">
            <div className="text-[16px] font-semibold">KGTE 三岛协同进化</div>
            <div className="text-xs text-[var(--evo-muted)]">每个节点是一个候选算法 · 云端生成 · 本地打分 · 失败剪枝 · 知识跨岛迁移</div>
            <div className="flex-1" />
            <Legend />
          </div>
          <div className="relative h-[calc(100%-36px)]">
            <EvolutionCanvas view={view} selectedId={selectedId} onSelect={setSelectedId} />
          </div>
        </div>
        <div className="h-[200px] shrink-0">
          <CloudLocalPanel view={view} pipeline={demo.pipeline} />
        </div>
      </div>

      <div className="flex min-h-0 flex-col gap-3">
        <div className="evo-card p-4">
          <div className="flex items-center justify-between text-xs text-[var(--evo-muted)]">
            <span>最优 ROS</span>
            <span className="evo-mono">第 {view.round} / 6 轮</span>
          </div>
          <div className="mt-1 flex items-end gap-2">
            <AnimatedNumber value={best} className="evo-mono text-[44px] leading-none font-bold text-[var(--evo-brand)]" />
            {view.bestId && <span className="mb-1 rounded-md bg-[var(--evo-brand-50)] px-1.5 text-xs font-semibold text-[var(--evo-brand)]">{view.bestId}</span>}
          </div>
          <div className="evo-mono mt-1 text-xs text-[var(--evo-muted)]">
            基线 {BASELINE_SCORE.toFixed(2)} →{' '}
            <span className="font-semibold text-[var(--evo-good)]">+{(best - BASELINE_SCORE).toFixed(2)}</span>
          </div>
          <Sparkline values={view.bestHistory} />
        </div>

        <div className="evo-card min-h-[150px] p-4">
          <AnimatePresence mode="wait">
            {focus ? (
              <motion.div key={focus.id} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} transition={{ duration: 0.2 }}>
                <div className="flex items-center gap-2">
                  <span className="evo-mono text-xs font-semibold text-[var(--evo-brand)]">{focus.id}</span>
                  <span className="text-[14px] font-semibold">{focus.title}</span>
                  <span className="rounded bg-slate-100 px-1.5 text-[10px] text-slate-500">{focus.operator}</span>
                </div>
                <div className="evo-mono mt-2 grid grid-cols-3 gap-2 text-center text-[11px]">
                  <Stat label="ROS" value={focus.score.toFixed(2)} />
                  <Stat label="Q" value={focus.q.toFixed(2)} />
                  <Stat label="Jev" value={focus.jev.toFixed(2)} />
                </div>
                <div className="mt-2 text-xs leading-relaxed text-[var(--evo-muted)]">
                  <span className="font-medium text-[var(--evo-fg)]">反思：</span>
                  {focus.reflection}
                </div>
              </motion.div>
            ) : (
              <div className="flex h-full items-center gap-3 text-xs text-[var(--evo-muted)]">
                <EvoBot size={30} mood="think" /> 等待第一批候选…
              </div>
            )}
          </AnimatePresence>
        </div>

        <EventFeed view={view} />
        <PlayerControls player={player} total={demo.steps.length} />
        <NextButton show={view.finished} onClick={onNext}>
          进入新知识发现 · 机制辩论赛
        </NextButton>
      </div>

      <LandingOverlay show={!landed} title="分裂成三个岛，开始协同进化" sub="时序特征岛 · 模型集成岛 · 运维阈值岛" />
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg bg-slate-50 py-1.5">
      <div className="text-[10px] text-[var(--evo-subtle)]">{label}</div>
      <div className="font-semibold">{value}</div>
    </div>
  );
}

function Sparkline({ values }: { values: number[] }) {
  const w = 290;
  const h = 46;
  if (values.length < 2) return <div className="mt-3 h-[46px] rounded-lg bg-slate-50" />;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const pts = values.map((v, i) => [(i / (values.length - 1)) * w, h - 4 - ((v - min) / (max - min || 1)) * (h - 8)] as const);
  const line = pts.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(' ');
  const last = pts[pts.length - 1];
  return (
    <svg className="mt-3" width="100%" viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" height={h}>
      <polygon points={`0,${h} ${line} ${w},${h}`} fill="rgb(37 99 235 / 0.08)" />
      <polyline points={line} fill="none" stroke="#2563EB" strokeWidth={2} strokeLinejoin="round" />
      <circle cx={last[0]} cy={last[1]} r={3.5} fill="#2563EB" />
    </svg>
  );
}

function Legend() {
  const items = [
    { mood: 'eval' as const, label: '评估中' },
    { mood: 'happy' as const, label: '改进' },
    { mood: 'fail' as const, label: '失败' },
    { mood: 'pruned' as const, label: '剪枝' },
  ];
  return (
    <div className="flex items-center gap-3 text-[11px] text-[var(--evo-muted)]">
      {items.map((i) => (
        <span key={i.label} className="flex items-center gap-1">
          <EvoBot size={16} mood={i.mood} animated={false} />
          {i.label}
        </span>
      ))}
      <span className="flex items-center gap-1">
        <span className="h-0.5 w-4 bg-[var(--evo-brand)]" />
        知识注入
      </span>
    </div>
  );
}
