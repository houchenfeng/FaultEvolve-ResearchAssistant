import { AnimatePresence, motion } from 'motion/react';
import { useEffect, useState } from 'react';

import { EvoBot } from '../bot/EvoBot';
import type { IconName } from '../ui';
import { Icon } from '../ui';
import type { TaskDraft } from './HomeScreen';
import { SEED_OPTIONS } from './HomeScreen';

const CHECKS: { icon: IconName; title: string; value: string; ok: string }[] = [
  { icon: 'server', title: '云端进化服务器', value: 'hcf@10.0.3.21 · ssh_cloud', ok: 'SSH 已连接 · known_hosts 校验通过' },
  { icon: 'laptop', title: '本地评估器', value: 'evaluator.py · 数据目录可读', ok: '沙箱就绪 · 数据不出本地' },
  { icon: 'cloud', title: '模型服务', value: 'qwen3-coder-plus / qwen3-max', ok: 'API 可用' },
];

export function ConfirmScreen({
  draft,
  onDraft,
  onConfirm,
  onBack,
  onOpenSettings,
}: {
  draft: TaskDraft;
  onDraft: (d: TaskDraft) => void;
  onConfirm: () => void;
  onBack: () => void;
  onOpenSettings: () => void;
}) {
  const [checked, setChecked] = useState(0);
  const [rounds, setRounds] = useState(6);
  const ready = checked >= CHECKS.length;

  useEffect(() => {
    if (checked >= CHECKS.length) return;
    const timer = window.setTimeout(() => setChecked((c) => c + 1), checked === 0 ? 900 : 650);
    return () => window.clearTimeout(timer);
  }, [checked]);

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
              开始前我想确认 <span className="text-[var(--evo-brand)]">5</span> 件事
            </div>
            <div className="mt-1 text-[13px] text-[var(--evo-muted)]">连接检查会自动完成，初始解与预算需要你确认。</div>

            <div className="mt-4 space-y-2">
              {CHECKS.map((c, i) => (
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
                <div className="mt-2 text-xs text-[var(--evo-muted)]">
                  {draft.seed === '注入已有知识' && '把知识库中已确认的规律（如 SMART 末端趋势）作为先验注入三岛初始候选。'}
                  {draft.seed === '基线算法' && '从各岛的规则 / 树模型 / 阈值基线开始。'}
                  {draft.seed === '检索论文并复现' && '先检索相关论文并复现方法作为初始解（演示模式下使用预置结果）。'}
                  {draft.seed === '上传代码' && '使用你提供的算法实现作为根节点。'}
                </div>
              </div>

              <div className="rounded-xl border border-[var(--evo-border)] px-3.5 py-3">
                <div className="flex items-center gap-3">
                  <span className="text-[var(--evo-brand)]">
                    <Icon name="flask" size={18} />
                  </span>
                  <span className="text-[13px] font-medium">进化预算</span>
                  <span className="flex-1" />
                  <span className="evo-mono text-xs text-[var(--evo-muted)]">
                    3 岛 × {rounds} 轮 · 约 {rounds * 7} 分钟
                  </span>
                </div>
                <input
                  type="range"
                  min={3}
                  max={10}
                  value={rounds}
                  onChange={(e) => setRounds(Number(e.target.value))}
                  className="mt-2 w-full accent-[#2563EB]"
                />
              </div>
            </div>

            <div className="mt-4 flex items-center gap-2 text-xs text-[var(--evo-muted)]">
              <Icon name="shield" size={14} />
              云端只会看到分数与聚合统计，原始数据始终留在本地。
            </div>

            <div className="mt-5 flex justify-end gap-2">
              <button className="evo-btn evo-btn--ghost" onClick={onBack}>
                返回修改
              </button>
              <button className="evo-btn evo-btn--ghost" onClick={onOpenSettings}>
                修改设置
              </button>
              <motion.button
                className="evo-btn evo-btn--primary disabled:opacity-40"
                disabled={!ready}
                onClick={onConfirm}
                animate={ready ? { scale: [1, 1.05, 1] } : {}}
                transition={{ duration: 0.5 }}
              >
                确认，开始进化
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
      </motion.div>
    </div>
  );
}
