/**
 * 云端进化 / 本地评估分离演示：候选代码从云端穿过数据边界落入本地沙箱，
 * 只有分数回传到云端。
 *
 * 飞行的代码卡只在右侧独立的“传送通道”里移动，不与左侧说明、终端重叠。
 */
import { AnimatePresence, motion } from 'motion/react';

import { EvoBot } from '../bot/EvoBot';
import { NODE_BY_ID } from '../demo-script';
import { Icon } from '../ui';
import type { PlayerView } from '../use-demo-player';

const PIPELINE = ['云端提出假设', 'SSH 下发代码', '本地沙箱评估', '回传分数', '云端反思进化'];

const CLOUD_Y = '25%';
const LOCAL_Y = '75%';

function activeStage(view: PlayerView): number {
  const s = view.step;
  if (!s) return -1;
  if (s.kind === 'propose') return s.round === 0 ? 0 : 4;
  if (s.kind === 'evaluate') return 2;
  if (s.kind === 'result') return 3;
  return 5;
}

export function CloudLocalPanel({ view }: { view: PlayerView }) {
  const s = view.step;
  const stage = activeStage(view);
  const proposing = s?.kind === 'propose';
  const evaluating = s?.kind === 'evaluate';
  const result = s?.kind === 'result' ? NODE_BY_ID.get(s.nodeId) : undefined;
  const candidates = s && (s.kind === 'propose' || s.kind === 'evaluate') ? s.nodeIds : [];
  const failed = result?.outcome === 'failed' || result?.outcome === 'pruned';
  const localMood = evaluating ? 'eval' : result ? (failed ? 'fail' : 'happy') : 'idle';

  return (
    <div className="evo-card flex h-full overflow-hidden">
      <div className="relative min-w-0 flex-1">
        <div className="absolute inset-x-0 top-0 h-1/2 bg-gradient-to-b from-[#EEF4FF] to-transparent" />
        <div className="absolute inset-x-4 top-1/2 border-t-2 border-dashed border-[#93B4F5]" />

        <div className="relative grid h-full grid-cols-[minmax(0,1fr)_minmax(260px,46%)]">
          <div className="grid min-w-0 grid-rows-2 px-5">
            <div className="flex min-w-0 items-center gap-3">
              <EvoBot size={40} mood={proposing ? 'think' : stage === 3 ? 'look' : 'idle'} />
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-1.5 text-[13px] font-semibold text-[var(--evo-brand)]">
                  <Icon name="server" size={15} /> 云端进化 · SSH 服务器
                  <span className="evo-mono truncate text-[11px] font-normal text-[var(--evo-muted)]">hcf@10.0.3.21</span>
                </div>
                <div className="evo-mono mt-1 truncate rounded-md bg-slate-900 px-2.5 py-1 text-[11px] text-slate-200">
                  <span className="text-sky-400">$</span> fe evolve local benchmark/hdd_mvp · round {view.round}
                  {proposing && <span className="text-emerald-400"> ✓ {candidates.length} candidates</span>}
                  {stage === 3 && result && <span className="text-amber-300"> ← {result.id}={result.score.toFixed(2)}</span>}
                </div>
              </div>
            </div>
            <div className="flex min-w-0 items-center gap-3">
              <EvoBot size={40} shape="squircle" mood={localMood} />
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-1.5 text-[13px] font-semibold">
                  <Icon name="laptop" size={15} /> 本地评估 · 沙箱
                  <span className="evo-mono truncate text-[11px] font-normal text-[var(--evo-muted)]">evaluator.py</span>
                </div>
                <div className="mt-1 flex items-center gap-1.5 text-[11px] text-[var(--evo-muted)]">
                  <Icon name="lock" size={12} /> SMART 遥测与工单只在本地读取
                </div>
              </div>
            </div>
          </div>

          <div className="relative min-w-0 border-l border-dashed border-[var(--evo-border)]">
            <span className="absolute top-2 left-3 text-[10.5px] text-[var(--evo-subtle)]">候选队列</span>
            <span className="absolute bottom-2 left-3 text-[10.5px] text-[var(--evo-subtle)]">沙箱评估</span>
            <span className="absolute top-1/2 right-3 flex -translate-y-1/2 items-center gap-1 rounded-full border border-[#93B4F5] bg-white px-2 py-0.5 text-[10.5px] text-[var(--evo-brand)]">
              <Icon name="lock" size={10} /> 数据边界 · 仅分数可通过
            </span>

            <AnimatePresence>
              {candidates.length > 0 && (
                <motion.div
                  key={`cards-${view.round}`}
                  className="absolute left-3 flex -translate-y-1/2 flex-wrap gap-1.5 pr-3"
                  initial={{ top: CLOUD_Y, opacity: 0 }}
                  animate={{ top: evaluating ? LOCAL_Y : CLOUD_Y, opacity: 1 }}
                  exit={{ opacity: 0, scale: 0.9 }}
                  transition={{ duration: 0.9, ease: [0.65, 0, 0.35, 1] }}
                >
                  {candidates.map((id, i) => (
                    <motion.span
                      key={id}
                      className={`evo-mono rounded-md border px-1.5 py-0.5 text-[11px] font-semibold shadow-sm ${evaluating ? 'border-[var(--evo-brand)] bg-[var(--evo-brand-50)] text-[var(--evo-brand)]' : 'border-[#BFD3FB] bg-white text-[var(--evo-brand)]'}`}
                      initial={{ opacity: 0, y: -8, scale: 0.7 }}
                      animate={{ opacity: 1, y: 0, scale: 1 }}
                      transition={{ delay: i * 0.06, type: 'spring', stiffness: 320, damping: 22 }}
                    >
                      {id}.py
                    </motion.span>
                  ))}
                </motion.div>
              )}
              {result && (
                <motion.span
                  key={`score-${view.index}`}
                  className={`evo-mono absolute left-3 -translate-y-1/2 rounded-full px-2.5 py-0.5 text-[11px] font-bold text-white shadow ${failed ? 'bg-slate-400' : 'bg-[var(--evo-brand)]'}`}
                  initial={{ top: LOCAL_Y, opacity: 0 }}
                  animate={{ top: [LOCAL_Y, CLOUD_Y], opacity: [0, 1, 1, 0] }}
                  transition={{ duration: 0.7, ease: [0.16, 1, 0.3, 1] }}
                >
                  ↑ {result.id} {result.score.toFixed(2)}
                </motion.span>
              )}
            </AnimatePresence>
          </div>
        </div>
      </div>

      <div className="w-[170px] shrink-0 border-l border-[var(--evo-border)] px-4 py-3">
        <div className="mb-1.5 text-xs font-semibold text-[var(--evo-muted)]">执行流转</div>
        {PIPELINE.map((label, i) => {
          const on = i === stage || (stage === 2 && i === 1);
          const past = stage === 5 || (stage >= 0 && i < stage);
          return (
            <div key={label} className="flex items-center gap-2 py-[3px]">
              <motion.span
                className={`flex size-5 items-center justify-center rounded-full text-[10px] font-semibold ${on ? 'bg-[var(--evo-brand)] text-white' : past ? 'bg-[var(--evo-brand-100)] text-[var(--evo-brand)]' : 'bg-slate-100 text-slate-400'}`}
                animate={on ? { scale: [1, 1.18, 1] } : { scale: 1 }}
                transition={on ? { duration: 0.9, repeat: Infinity } : {}}
              >
                {i + 1}
              </motion.span>
              <span className={`text-[12px] ${on ? 'font-semibold text-[var(--evo-brand)]' : 'text-[var(--evo-muted)]'}`}>{label}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
