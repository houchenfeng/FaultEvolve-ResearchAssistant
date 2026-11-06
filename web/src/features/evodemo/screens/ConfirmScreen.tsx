import { AnimatePresence, motion } from 'motion/react';
import { useEffect, useState } from 'react';

import { EvoBot } from '../bot/EvoBot';
import type { DemoCase } from '../cases/types';
import { Icon } from '../ui';
import type { TaskDraft } from './HomeScreen';
import { SEED_OPTIONS } from './HomeScreen';
import type { RunMode } from './hybrid-parts';
import { LiveChecks, RunModePicker } from './LiveChecks';

const OTHER_SEED_NOTES: Record<string, string> = {
  基线算法: '从各岛的规则 / 树模型 / 阈值基线开始。',
  上传代码: '使用你提供的算法实现作为根节点。',
};

const LIVE_PREVIEW = {
  title: '混合云实时会话 · 每个进化节点都在本机评估',
  rows: [
    { label: '平板 · 机房数字孪生', sub: '推送 300 块 HDD 的 SMART 遥测，接收告警', ok: true },
    { label: '本机评估域 · GPU', sub: '每个候选都在平板场景上评估，弹出评估窗口逐个展示', ok: true },
    { label: '远端服务器 · 自进化', sub: '经跳板机 SSH，按回传分数选择父代、生成下一代', ok: true },
    { label: '数据边界', sub: '只回传 ROS、捕获数、误报数等白名单分数', ok: true },
  ],
};

export function ConfirmScreen({
  demo,
  draft,
  onDraft,
  onConfirm,
  onBack,
  onOpenSettings,
  runMode,
  onRunMode,
}: {
  demo: DemoCase;
  draft: TaskDraft;
  onDraft: (d: TaskDraft) => void;
  onConfirm: () => void;
  onBack: () => void;
  onOpenSettings: () => void;
  runMode: RunMode;
  onRunMode: (m: RunMode) => void;
}) {
  const { checks, budget, preview } = demo.confirm;
  const [checked, setChecked] = useState(0);
  const [rounds, setRounds] = useState(budget.initial);
  const ready = checked >= checks.length;
  const live = runMode !== 'replay';
  const offScript = !live && draft.text.trim() !== '' && draft.text !== demo.sampleTask;
  const shownPreview = live ? LIVE_PREVIEW : preview;

  useEffect(() => {
    if (checked >= checks.length) return;
    const timer = window.setTimeout(() => setChecked((c) => c + 1), checked === 0 ? 900 : 650);
    return () => window.clearTimeout(timer);
  }, [checked, checks.length]);

  return (
    <div className="grid h-full grid-cols-[minmax(0,1fr)_minmax(0,0.85fr)] gap-10 overflow-auto px-10 py-8">
      <div className="mx-auto w-full max-w-[640px]">
        <div className="flex items-start justify-end gap-3">
          <motion.div
            className="max-w-[460px] rounded-2xl rounded-tr-md bg-[var(--evo-brand-50)] px-4 py-3 text-[15px] leading-relaxed"
            initial={{ opacity: 0, x: 20 }}
            animate={{ opacity: 1, x: 0 }}
          >
            {draft.text}
            <div className="mt-2 flex flex-wrap gap-1.5 text-xs text-[var(--evo-muted)]">
              <span className="rounded-full bg-white px-2 py-0.5">评估：{draft.evaluation}</span>
              <span className="rounded-full bg-white px-2 py-0.5">初始解：{draft.seed}</span>
            </div>
          </motion.div>
        </div>

        <div className="mt-6 flex items-start gap-4">
          <motion.div layoutId="hero-bot" transition={{ type: 'spring', stiffness: 140, damping: 16 }}>
            <EvoBot size={64} mood={ready ? 'happy' : 'asking'} gaze={{ x: 0.6, y: 0.2 }} />
          </motion.div>

          <motion.div
            className="evo-card flex-1 p-5 shadow-[0_12px_40px_-16px_rgb(15_23_42/0.18)]"
            initial={{ opacity: 0, y: 14 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.25 }}
          >
            <div className="text-[17px] font-semibold">
              开始前我想确认 <span className="text-[var(--evo-brand)]">{(live ? 4 : checks.length) + 2}</span> 件事
            </div>
            <div className="mt-1 text-[13px] text-[var(--evo-muted)]">连接检查会自动完成，初始解与预算需要你确认。</div>

            <div className="mt-4 space-y-2">
              <RunModePicker value={runMode} onChange={onRunMode} />
              <LiveChecks mode={runMode} />
              {!live && checks.map((c, i) => (
                <div key={c.title} className="flex items-center gap-3 rounded-xl border border-[var(--evo-border)] px-3.5 py-2.5">
                  <span className="text-[var(--evo-brand)]">
                    <Icon name={c.icon} size={18} />
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="text-[13px] font-medium">{c.title}</div>
                    <div className="evo-mono truncate text-xs text-[var(--evo-muted)]">{c.value}</div>
                  </div>
                  <AnimatePresence mode="wait">
                    {i < checked ? (
                      <motion.span
                        key="ok"
                        className="flex items-center gap-1 text-xs text-[var(--evo-good)]"
                        initial={{ opacity: 0, scale: 0.6 }}
                        animate={{ opacity: 1, scale: 1 }}
                      >
                        <Icon name="check" size={14} />
                        {c.ok}
                      </motion.span>
                    ) : (
                      <motion.span key="wait" className="flex items-center gap-1.5 text-xs text-[var(--evo-muted)]" exit={{ opacity: 0 }}>
                        <span className="evo-spin inline-block size-3 rounded-full border-2 border-[var(--evo-brand)] border-t-transparent" />
                        检查中
                      </motion.span>
                    )}
                  </AnimatePresence>
                </div>
              ))}

              <div className="rounded-xl border border-[var(--evo-border)] px-3.5 py-3">
                <div className="mb-2 flex items-center gap-3">
                  <span className="text-[var(--evo-brand)]">
                    <Icon name="seed" size={18} />
                  </span>
                  <span className="text-[13px] font-medium">初始解从哪里来？</span>
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {SEED_OPTIONS.map((s) => (
                    <button key={s} className="evo-chip" data-active={draft.seed === s} onClick={() => onDraft({ ...draft, seed: s })}>
                      {draft.seed === s && <Icon name="check" size={12} />}
                      {s}
                    </button>
                  ))}
                </div>
                <div className="mt-2 text-xs leading-relaxed text-[var(--evo-muted)]">{draft.seed === demo.seed ? demo.confirm.seedNote : OTHER_SEED_NOTES[draft.seed]}</div>
              </div>

              <div className="rounded-xl border border-[var(--evo-border)] px-3.5 py-3">
                <div className="flex items-center gap-3">
                  <span className="text-[var(--evo-brand)]">
                    <Icon name="flask" size={18} />
                  </span>
                  <span className="text-[13px] font-medium">{budget.label}</span>
                  <span className="flex-1" />
                  <span className="evo-mono text-xs text-[var(--evo-muted)]">{budget.describe(rounds)}</span>
                </div>
                <input
                  type="range"
                  min={budget.min}
                  max={budget.max}
                  value={rounds}
                  onChange={(e) => setRounds(Number(e.target.value))}
                  className="mt-2 w-full accent-[#2563EB]"
                />
              </div>
            </div>

            <div className="mt-4 flex items-center gap-2 text-xs text-[var(--evo-muted)]">
              <Icon name="shield" size={14} />
              {live ? '服务器只拿到 ROS、捕获数、误报数等白名单分数；平板遥测、标签与逐盘分数留在本机。' : demo.confirm.privacy}
            </div>
            {offScript && (
              <div className="mt-2 rounded-lg bg-amber-50 px-3 py-2 text-xs leading-relaxed text-amber-700">
                这个任务暂无录制好的实验，演示将回放「{demo.name}」的真实实验过程。
              </div>
            )}

            <div className="mt-5 flex justify-end gap-2">
              <button className="evo-btn evo-btn--ghost" onClick={onBack}>
                返回修改
              </button>
              <button className="evo-btn evo-btn--ghost" onClick={onOpenSettings}>
                修改设置
              </button>
              <motion.button
                className="evo-btn evo-btn--primary disabled:opacity-40"
                disabled={!ready && !live}
                onClick={onConfirm}
                animate={ready ? { scale: [1, 1.05, 1] } : {}}
                transition={{ duration: 0.5 }}
              >
                {live ? '确认，接入混合云开始进化' : '确认，开始进化'}
                <Icon name="arrow" />
              </motion.button>
            </div>
          </motion.div>
        </div>
      </div>

      <motion.div
        className="relative hidden flex-col justify-center lg:flex"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ delay: 0.4 }}
      >
        <div className="text-sm text-[var(--evo-muted)]">即将进入</div>
        <div className="mt-1 flex items-center gap-2 text-2xl font-bold">
          进化工作台 <Icon name="arrow" size={22} />
        </div>
        {shownPreview ? (
          <div className="mt-5 rounded-2xl border border-dashed border-[var(--evo-border)] bg-white/50 p-5">
            <div className="mb-2 text-xs font-semibold text-[var(--evo-muted)]">{shownPreview.title}</div>
            {shownPreview.rows.map((r, i) => (
              <motion.div
                key={r.label}
                className="flex items-center gap-3 border-b border-dashed border-[var(--evo-border)] py-2.5 last:border-0"
                initial={{ opacity: 0, x: 12 }}
                animate={{ opacity: r.ok ? 1 : 0.5, x: 0 }}
                transition={{ delay: 0.5 + i * 0.12 }}
              >
                <span className={`size-2 shrink-0 rounded-full ${r.ok ? 'bg-[var(--evo-brand)]' : 'bg-slate-300'}`} />
                <div className="min-w-0">
                  <div className="text-[13px] font-medium">{r.label}</div>
                  <div className="text-[11.5px] text-[var(--evo-muted)]">{r.sub}</div>
                </div>
              </motion.div>
            ))}
            <div className="mt-3 border-t border-dashed border-[var(--evo-border)] pt-3 text-xs text-[var(--evo-muted)]">
              {live ? '服务器生成候选 ⇢ 本机在平板场景上评估 ⇢ 白名单分数回传 ⇢ 服务器选择下一代' : demo.pipeline.stages.join(' ⇢ ')}
            </div>
          </div>
        ) : (
        <div className="mt-5 rounded-2xl border border-dashed border-[var(--evo-border)] bg-white/50 p-5">
          {['时序特征岛', '模型集成岛', '运维阈值岛'].map((name, row) => (
            <div key={name} className="flex items-center gap-3 py-3">
              <span className="w-20 text-xs text-[var(--evo-muted)]">{name}</span>
              {Array.from({ length: 5 }).map((_, i) => (
                <motion.span
                  key={i}
                  className="size-5 rounded-full bg-[var(--evo-brand-100)]"
                  animate={{ opacity: [0.35, 1, 0.35] }}
                  transition={{ duration: 1.6, repeat: Infinity, delay: row * 0.2 + i * 0.12 }}
                />
              ))}
            </div>
          ))}
          <div className="mt-3 border-t border-dashed border-[var(--evo-border)] pt-3 text-xs text-[var(--evo-muted)]">
            云端 · 提出假设 ⇢ 数据边界 ⇢ 本地 · 评估打分
          </div>
        </div>
        )}
      </motion.div>
    </div>
  );
}
