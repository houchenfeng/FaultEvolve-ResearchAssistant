import { AnimatePresence, motion } from 'motion/react';
import type { CSSProperties } from 'react';
import { useEffect, useState } from 'react';

import { EvoBot } from '../bot/EvoBot';
import type { DebateRole, DebateScript } from '../cases/types';
import { Icon, Typewriter } from '../ui';

const SEATS: Record<DebateRole, { x: number; y: number }> = {
  judge: { x: 50, y: 17 },
  proponent: { x: 13, y: 48 },
  statistician: { x: 87, y: 48 },
  confounder: { x: 22, y: 82 },
  critic: { x: 78, y: 82 },
};

function Title({ script }: { script: DebateScript }) {
  const { title, highlight } = script;
  const at = highlight ? title.indexOf(highlight) : -1;
  if (!highlight || at < 0) return <>{title}</>;
  return (
    <>
      {title.slice(0, at)}
      <span className="text-[var(--evo-brand)]">{highlight}</span>
      {title.slice(at + highlight.length)}
    </>
  );
}

export function TournamentScreen({ script, onNext }: { script: DebateScript; onNext: () => void }) {
  const [round, setRound] = useState(0);
  const [playing, setPlaying] = useState(true);
  const { rounds, cast, verdict, chain } = script;
  const current = rounds[round];
  const final = round === rounds.length - 1;

  useEffect(() => {
    if (!playing || final) return;
    const timer = window.setTimeout(() => setRound((r) => r + 1), Math.max(4200, current.line.length * 70));
    return () => window.clearTimeout(timer);
  }, [playing, round, final, current.line.length]);

  const speakerSeat = SEATS[current.speaker];

  return (
    <div className="grid h-full grid-rows-[auto_minmax(0,1fr)_auto] gap-4 p-5">
      <div className="flex items-center gap-4">
        <div>
          <div className="text-xs text-[var(--evo-muted)]">{script.eyebrow}</div>
          <div className="mt-1 text-[22px] font-bold">
            <Title script={script} />
          </div>
        </div>
        <div className="flex-1" />
        <button className="evo-btn evo-btn--ghost !px-2.5" onClick={() => setPlaying((p) => !p)}>
          <Icon name={playing ? 'pause' : 'play'} />
        </button>
        <button className="evo-btn evo-btn--ghost" onClick={() => setRound(0)}>
          <Icon name="restart" /> 重播
        </button>
        <button className="evo-btn evo-btn--ghost" onClick={() => setRound(rounds.length - 1)} disabled={final}>
          <Icon name="skip" /> 跳到裁决
        </button>
      </div>

      <div className="grid min-h-0 grid-cols-[200px_minmax(0,1fr)_330px] gap-4">
        <div className="evo-card overflow-auto p-3">
          <div className="mb-2 px-1 text-xs font-semibold text-[var(--evo-muted)]">轮次</div>
          {rounds.map((r, i) => (
            <button
              key={r.round}
              className={`flex w-full items-center gap-2.5 rounded-lg px-2 py-2 text-left text-[13px] transition-colors ${i === round ? 'bg-[var(--evo-brand-50)] font-semibold text-[var(--evo-brand)]' : i < round ? 'text-[var(--evo-fg)]' : 'text-[var(--evo-subtle)]'}`}
              onClick={() => setRound(i)}
            >
              <span className={`flex size-5 shrink-0 items-center justify-center rounded-full text-[10px] ${i <= round ? 'bg-[var(--evo-brand)] text-white' : 'bg-slate-100'}`}>{i + 1}</span>
              {r.round}
            </button>
          ))}
        </div>

        <div className="evo-card relative overflow-hidden">
          <div className="absolute top-1/2 left-1/2 h-[46%] w-[56%] -translate-x-1/2 -translate-y-[30%] rounded-[50%] border border-[var(--evo-brand-100)] bg-[radial-gradient(ellipse,#EEF4FF,transparent_70%)]" />
          {(Object.keys(SEATS) as DebateRole[]).map((role) => {
            const seat = SEATS[role];
            const member = cast[role];
            const speaking = role === current.speaker;
            const dx = speakerSeat.x - seat.x;
            const dy = speakerSeat.y - seat.y;
            const dist = Math.hypot(dx, dy) || 1;
            const verdictMood = final && role === 'judge' ? 'happy' : speaking ? 'talk' : 'listen';
            return (
              <motion.div
                key={role}
                className="absolute flex -translate-x-1/2 -translate-y-1/2 flex-col items-center"
                style={{ left: `${seat.x}%`, top: `${seat.y}%` }}
                animate={{ scale: speaking ? 1.22 : 0.92, opacity: speaking ? 1 : 0.62 }}
                transition={{ type: 'spring', stiffness: 220, damping: 18 }}
              >
                <EvoBot
                  size={role === 'judge' ? 100 : 88}
                  shape={member.shape}
                  color={member.color}
                  mood={verdictMood}
                  gaze={speaking ? undefined : { x: dx / dist, y: dy / dist }}
                />
                <div className="mt-1.5 text-center">
                  <div className="text-[13px] font-semibold">{member.name}</div>
                  <div className="text-[10px] text-[var(--evo-muted)]">{member.en}</div>
                </div>
              </motion.div>
            );
          })}

          <AnimatePresence mode="wait">
            <motion.div
              key={round}
              className="evo-card absolute w-[min(400px,44%)] px-4 py-3 text-[13.5px] leading-relaxed shadow-xl"
              style={bubblePosition(current.speaker)}
              initial={{ opacity: 0, scale: 0.9, y: 8 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.95 }}
              transition={{ type: 'spring', stiffness: 300, damping: 24 }}
            >
              <span className={`absolute size-3 rotate-45 bg-white ${TAIL_CLASS[tailSide(current.speaker)]}`} />
              <div className="mb-1 text-[11px] font-semibold" style={{ color: cast[current.speaker].color }}>
                {cast[current.speaker].name} · {current.round}
              </div>
              <Typewriter text={current.line} speed={34} />
            </motion.div>
          </AnimatePresence>
        </div>

        <div className="evo-card flex min-h-0 flex-col p-4">
          <div className="text-xs font-semibold text-[var(--evo-muted)]">当前裁决</div>
          <AnimatePresence mode="wait">
            {final ? (
              <motion.div
                key="settled"
                className="mt-2 rounded-xl bg-[var(--evo-brand)] px-4 py-3 text-center text-white"
                initial={{ scale: 0.6, opacity: 0 }}
                animate={{ scale: 1, opacity: 1 }}
                transition={{ type: 'spring', stiffness: 260, damping: 14, delay: 0.6 }}
              >
                <div className="text-[22px] font-bold tracking-wide">{script.outcome.title}</div>
                <div className="text-xs opacity-90">{script.outcome.sub}</div>
              </motion.div>
            ) : (
              <motion.div key="pending" className="mt-2 rounded-xl border border-dashed border-[var(--evo-border)] px-4 py-3 text-center text-[var(--evo-muted)]" exit={{ opacity: 0 }}>
                <div className="text-[18px] font-semibold">审议中…</div>
                <div className="text-xs">逐轮补齐推导与证据</div>
              </motion.div>
            )}
          </AnimatePresence>
          <div className="evo-scroll mt-3 min-h-0 flex-1 space-y-1.5 overflow-auto">
            {verdict.map((v) => {
              const shown = round >= v.round;
              const long = v.value.length > 18;
              return (
                <motion.div
                  key={v.label}
                  className={`rounded-lg px-3 py-2 text-[12px] ${long ? 'block' : 'flex items-center justify-between'} ${shown && v.good ? 'bg-[var(--evo-brand-50)]' : 'bg-slate-50'}`}
                  animate={{ opacity: shown ? 1 : 0.3 }}
                >
                  <div className="text-[var(--evo-muted)]">{v.label}</div>
                  <div className={`evo-mono font-semibold ${long ? 'mt-0.5 text-[12.5px]' : ''} ${shown && v.good ? 'text-[var(--evo-brand)]' : ''}`}>{shown ? v.value : '—'}</div>
                </motion.div>
              );
            })}
          </div>
          {final && (
            <motion.button className="evo-btn evo-btn--primary mt-3 justify-center" initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 1.2 }} onClick={onNext}>
              查看结果讲解 <Icon name="arrow" />
            </motion.button>
          )}
        </div>
      </div>

      <div className="evo-card flex items-center gap-4 px-5 py-3">
        <span className="shrink-0 text-xs font-semibold text-[var(--evo-muted)]">证据链</span>
        <div className="grid flex-1" style={{ gridTemplateColumns: `repeat(${chain.length}, minmax(0, 1fr))` }}>
          {chain.map((label, i) => {
            const lit = i <= round;
            return (
              <div key={label} className="relative flex flex-col items-center gap-1">
                {i < chain.length - 1 && (
                  <div className="absolute top-[5px] left-1/2 h-0.5 w-full overflow-hidden rounded bg-slate-200">
                    <motion.div className="absolute inset-y-0 left-0 bg-[var(--evo-brand)]" animate={{ width: i < round ? '100%' : '0%' }} transition={{ duration: 0.6 }} />
                  </div>
                )}
                <motion.span
                  className="relative size-3 shrink-0 rounded-full"
                  animate={{ backgroundColor: lit ? '#2563EB' : '#E2E8F0', scale: i === round ? [1, 1.5, 1] : 1 }}
                  transition={{ duration: 0.6 }}
                />
                <span className={`max-w-full truncate text-[11.5px] ${lit ? 'font-medium' : 'text-[var(--evo-subtle)]'}`}>{label}</span>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

/** 气泡尾巴朝向发言者：裁判在气泡上方，其余席位在气泡左右两侧且与气泡垂直居中。 */
const TAIL_CLASS = {
  top: '-top-[7px] left-1/2 -translate-x-1/2 border-t border-l border-[var(--evo-border)]',
  left: 'top-1/2 -left-[7px] -translate-y-1/2 border-b border-l border-[var(--evo-border)]',
  right: 'top-1/2 -right-[7px] -translate-y-1/2 border-t border-r border-[var(--evo-border)]',
} as const;

function tailSide(role: DebateRole): keyof typeof TAIL_CLASS {
  if (role === 'judge') return 'top';
  return SEATS[role].x < 50 ? 'left' : 'right';
}

function bubblePosition(role: DebateRole): CSSProperties {
  const seat = SEATS[role];
  if (role === 'judge') return { left: '50%', top: `${seat.y + 16}%`, translate: '-50% 0' };
  const vertical = { top: `${seat.y}%`, translate: '0 -50%' };
  return seat.x < 50 ? { left: `${seat.x + 9}%`, ...vertical } : { right: `${100 - seat.x + 9}%`, ...vertical };
}
