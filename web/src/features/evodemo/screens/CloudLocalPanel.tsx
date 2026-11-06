/**
 * 云端进化 / 本地评估分离演示：候选代码从云端穿过数据边界落入本地沙箱，
 * 只有分数回传到云端。
 */
import { AnimatePresence, motion } from 'motion/react';

import { EvoBot } from '../bot/EvoBot';
import { NODE_BY_ID } from '../demo-script';
import { Icon } from '../ui';
import type { PlayerView } from '../use-demo-player';

const PIPELINE = ['云端提出假设', 'SSH 下发代码', '本地沙箱评估', '回传分数', '云端反思进化'];

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
  const localMood = evaluating ? 'eval' : result ? (result.outcome === 'failed' || result.outcome === 'pruned' ? 'fail' : 'happy') : 'idle';

  return (
    <div className="evo-card flex h-full overflow-hidden">
      <div className="relative flex-1">
        <div className="absolute inset-x-0 top-0 flex h-1/2 items-center gap-4 bg-gradient-to-b from-[#EEF4FF] to-transparent px-5">
          <div className="w-[190px] shrink-0">
            <div className="flex items-center gap-1.5 text-[13px] font-semibold text-[var(--evo-brand)]">
              <Icon name="server" size={15} /> 云端进化 · SSH 服务器
            </div>
            <div className="evo-mono mt-0.5 text-[11px] text-[var(--evo-muted)]">hcf@10.0.3.21 · qwen3-coder-plus</div>
          </div>
          <EvoBot size={40} mood={proposing ? 'think' : stage === 3 ? 'look' : 'idle'} />
          <div className="evo-mono min-w-0 flex-1 truncate rounded-lg bg-slate-900 px-3 py-1.5 text-[11px] text-slate-200">
            <span className="text-sky-400">$</span> fe evolve local benchmark/hdd_mvp --run-id c89e2a01 · round {view.round}
            {proposing && <span className="text-emerald-400">  ✓ generated {candidates.length} candidates</span>}
            {stage === 3 && result && <span className="text-amber-300">  ← score {result.id}={result.score.toFixed(2)}</span>}
          </div>
        </div>

        <div className="absolute inset-x-0 top-1/2 flex -translate-y-1/2 items-center gap-2 px-5">
          <div className="h-0 flex-1 border-t-2 border-dashed border-[#93B4F5]" />
          <span className="flex items-center gap-1 rounded-full border border-[#93B4F5] bg-white px-2.5 py-0.5 text-[11px] text-[var(--evo-brand)]">
            <Icon name="lock" size={11} /> 数据边界 · 仅分数与聚合统计可通过
          </span>
          <div className="h-0 flex-1 border-t-2 border-dashed border-[#93B4F5]" />
        </div>

        <div className="absolute inset-x-0 bottom-0 flex h-1/2 items-center gap-4 px-5">
          <div className="w-[190px] shrink-0">
            <div className="flex items-center gap-1.5 text-[13px] font-semibold">
              <Icon name="laptop" size={15} /> 本地评估 · 沙箱
            </div>
            <div className="evo-mono mt-0.5 text-[11px] text-[var(--evo-muted)]">evaluator.py · 原始数据不出本地</div>
          </div>
          <EvoBot size={40} shape="squircle" mood={localMood} />
          <div className="flex items-center gap-1.5 rounded-lg border border-[var(--evo-border)] bg-white px-2.5 py-1.5 text-[11px] text-[var(--evo-muted)]">
            <Icon name="lock" size={12} /> SMART 遥测 · 工单
          </div>
        </div>

        <div className="pointer-events-none absolute inset-0 left-[290px] right-6">
          <AnimatePresence>
            {candidates.map((id, i) => (
              <motion.div
                key={`${view.index}-${id}`}
                className="evo-mono absolute flex items-center gap-1 rounded-md border border-[#BFD3FB] bg-white px-2 py-1 text-[11px] font-semibold text-[var(--evo-brand)] shadow-sm"
                style={{ left: `${40 + i * 84}px` }}
                initial={proposing ? { top: '8%', opacity: 0, scale: 0.6 } : { top: '30%', opacity: 1 }}
                animate={proposing ? { top: '30%', opacity: 1, scale: 1 } : { top: '72%', opacity: 1, scale: 1 }}
                exit={{ opacity: 0, scale: 0.8 }}
                transition={{ delay: i * 0.05, duration: 0.8, ease: [0.65, 0, 0.35, 1] }}
              >
                {'</>'} {id}.py
              </motion.div>
            ))}
            {result && (
              <motion.div
                key={`score-${view.index}`}
                className={`evo-mono absolute left-[140px] rounded-full px-2.5 py-1 text-[11px] font-bold text-white shadow ${result.outcome === 'failed' || result.outcome === 'pruned' ? 'bg-slate-400' : 'bg-[var(--evo-brand)]'}`}
                initial={{ top: '72%', opacity: 0 }}
                animate={{ top: ['72%', '30%'], opacity: [0, 1, 1, 0] }}
                transition={{ duration: 0.7, ease: [0.16, 1, 0.3, 1] }}
              >
                ↑ {result.id} {result.score.toFixed(2)}
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </div>

      <div className="w-[190px] shrink-0 border-l border-[var(--evo-border)] px-4 py-3">
        <div className="mb-2 text-xs font-semibold text-[var(--evo-muted)]">执行流转</div>
        {PIPELINE.map((label, i) => {
          const on = i === stage || (stage === 2 && i === 1);
          const past = stage === 5 || (stage >= 0 && i < stage);
          return (
            <div key={label} className="flex items-center gap-2 py-1">
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
