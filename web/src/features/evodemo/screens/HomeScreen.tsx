import { AnimatePresence, motion } from 'motion/react';
import { useEffect, useState } from 'react';

import { EvoBot } from '../bot/EvoBot';
import type { BotShape } from '../bot/shapes';
import { KGTE_CASE } from '../cases/kgte';
import { PAPER_CASE } from '../cases/paper';
import type { CaseId } from '../cases/types';
import type { IconName } from '../ui';
import { Icon } from '../ui';

export interface TaskDraft {
  text: string;
  evaluation: string;
  seed: string;
}

export const SEED_OPTIONS = [PAPER_CASE.seed, KGTE_CASE.seed, '基线算法', '上传代码'] as const;
const EVAL_OPTIONS = [PAPER_CASE.evaluation, KGTE_CASE.evaluation, 'AUC-PR · 本地 evaluator.py', '自定义评估脚本'] as const;
const SPEC_OPTIONS = ['HDD SMART 日志 · 提前 7 天', '内存 CE 日志 · 提前 1 天', 'SSD 遥测 · 提前 3 天'] as const;

const SUGGESTIONS = [
  { label: '最新论文组合出新算法', text: PAPER_CASE.sampleTask, seed: PAPER_CASE.seed, evaluation: PAPER_CASE.evaluation },
  { label: 'HDD 三岛进化 · 云端进化本地评估', text: KGTE_CASE.sampleTask, seed: KGTE_CASE.seed, evaluation: KGTE_CASE.evaluation },
  { label: '内存 CE 告警预测', text: '根据内存可纠正错误（CE）日志，提前 1 天预测不可纠正错误。' },
];

const HISTORY: { name: string; meta: string; status: string; tone: 'done' | 'running' | 'idle'; open?: CaseId }[] = [
  { name: '论文组合 · 发现新算法', meta: 'TabM × Mitra-v2 共识一致性融合（CAF）· Q2 精确率 64.71%', status: '已完成', tone: 'done', open: 'paper' },
  { name: 'HDD 故障预测', meta: 'ROS 36.50 · 1 条新知识', status: '已完成', tone: 'done', open: 'kgte' },
  { name: 'Backblaze 跨数据集迁移', meta: '云端进化中 · 第 4 / 6 轮', status: '62%', tone: 'running' },
  { name: '阿里 SSD 预测', meta: '等待确认服务器与评估器', status: '待确认', tone: 'idle' },
];

const SHAPE_CYCLE: BotShape[] = ['circle', 'squircle', 'hex', 'circle', 'diamond', 'circle', 'triangle'];

export function HomeScreen({
  draft,
  onDraft,
  onSubmit,
  onOpenHistory,
}: {
  draft: TaskDraft;
  onDraft: (d: TaskDraft) => void;
  onSubmit: () => void;
  onOpenHistory: (id: CaseId) => void;
}) {
  const [shapeIndex, setShapeIndex] = useState(0);
  const [focused, setFocused] = useState(false);
  const [menu, setMenu] = useState<'spec' | 'eval' | 'seed' | null>(null);

  useEffect(() => {
    if (focused) return;
    const timer = window.setInterval(() => setShapeIndex((i) => (i + 1) % SHAPE_CYCLE.length), 3200);
    return () => window.clearInterval(timer);
  }, [focused]);

  const typing = focused && draft.text.length > 0;
  const shape = focused ? 'circle' : SHAPE_CYCLE[shapeIndex];
  const canSend = draft.text.trim().length > 0;

  return (
    <div className="flex h-full flex-col items-center overflow-auto px-6 pt-[6vh] pb-10">
      <motion.div layoutId="hero-bot" className="relative" transition={{ type: 'spring', stiffness: 140, damping: 16 }}>
        <div className="absolute inset-[-30%] rounded-full bg-[radial-gradient(circle,rgb(37_99_235/0.14),transparent_65%)]" />
        <EvoBot size={112} shape={shape} mood={typing ? 'listen' : focused ? 'look' : 'idle'} follow={!typing} />
      </motion.div>

      <motion.h1
        className="mt-6 text-center text-[34px] font-bold tracking-tight"
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.1 }}
      >
        想让哪个算法自己进化？
      </motion.h1>
      <p className="mt-2 text-center text-[15px] text-[var(--evo-muted)]">
        你描述任务、选好初始解（比如最新论文），它自动组合进化、按冻结规则验证，并把有效的规律写成新知识。
      </p>

      <motion.div
        className="evo-card relative mt-7 w-full max-w-[760px] p-4 shadow-[0_12px_40px_-12px_rgb(37_99_235/0.25)]"
        animate={{ borderColor: focused ? '#2563EB' : '#E3E8F0' }}
      >
        <textarea
          value={draft.text}
          onChange={(e) => onDraft({ ...draft, text: e.target.value })}
          onFocus={() => setFocused(true)}
          onBlur={() => setFocused(false)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey && canSend) {
              e.preventDefault();
              onSubmit();
            }
          }}
          rows={3}
          placeholder="描述你的任务，例如：用 SMART 日志提前 7 天预测硬盘故障，评估用 ROS…"
          className="w-full resize-none bg-transparent text-[15px] leading-relaxed outline-none placeholder:text-[var(--evo-subtle)]"
        />
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <FieldChip icon="doc" label="任务说明" value={draft.text ? SPEC_OPTIONS[0] : '未填写'} open={menu === 'spec'} onToggle={() => setMenu(menu === 'spec' ? null : 'spec')} options={SPEC_OPTIONS} onPick={() => setMenu(null)} />
          <FieldChip icon="flask" label="评估方式" value={draft.evaluation} open={menu === 'eval'} onToggle={() => setMenu(menu === 'eval' ? null : 'eval')} options={EVAL_OPTIONS} onPick={(v) => { onDraft({ ...draft, evaluation: v }); setMenu(null); }} />
          <FieldChip icon="seed" label="初始解" value={draft.seed} open={menu === 'seed'} onToggle={() => setMenu(menu === 'seed' ? null : 'seed')} options={SEED_OPTIONS} onPick={(v) => { onDraft({ ...draft, seed: v }); setMenu(null); }} />
          <div className="flex-1" />
          <motion.button
            className="evo-btn evo-btn--primary disabled:opacity-40"
            disabled={!canSend}
            onClick={onSubmit}
            whileHover={canSend ? { scale: 1.03 } : undefined}
          >
            开始进化
            <Icon name="send" />
          </motion.button>
        </div>
      </motion.div>

      <div className="mt-4 flex flex-wrap justify-center gap-2">
        {SUGGESTIONS.map((s) => (
          <button
            key={s.label}
            className="evo-chip"
            onClick={() => onDraft({ ...draft, text: s.text, seed: s.seed ?? draft.seed, evaluation: s.evaluation ?? draft.evaluation })}
          >
            {s.label}
          </button>
        ))}
      </div>

      <div className="mt-10 w-full max-w-[760px]">
        <div className="mb-2 flex items-center justify-between text-[13px]">
          <span className="font-semibold">历史任务</span>
          <span className="text-[var(--evo-subtle)]">实验、模型 API、服务器配置已移到右上角「设置」</span>
        </div>
        <div className="space-y-2">
          {HISTORY.map((h, i) => (
            <motion.button
              key={h.name}
              className="evo-card flex w-full items-center gap-3 px-4 py-3 text-left transition-colors hover:border-[var(--evo-brand)]"
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.15 + i * 0.05 }}
              onClick={() => h.open && onOpenHistory(h.open)}
            >
              <span
                className={`size-2 rounded-full ${h.tone === 'done' ? 'bg-[var(--evo-good)]' : h.tone === 'running' ? 'bg-[var(--evo-brand)] animate-pulse' : 'bg-slate-300'}`}
              />
              <span className="font-medium">{h.name}</span>
              <span className="text-[13px] text-[var(--evo-muted)]">{h.meta}</span>
              <span className="flex-1" />
              <span className={`text-xs ${h.tone === 'running' ? 'text-[var(--evo-brand)]' : 'text-[var(--evo-muted)]'}`}>{h.status}</span>
              <span className="text-[var(--evo-subtle)]">›</span>
            </motion.button>
          ))}
        </div>
      </div>
    </div>
  );
}

function FieldChip({
  icon,
  label,
  value,
  open,
  onToggle,
  options,
  onPick,
}: {
  icon: IconName;
  label: string;
  value: string;
  open: boolean;
  onToggle: () => void;
  options: readonly string[];
  onPick: (v: string) => void;
}) {
  return (
    <div className="relative">
      <button className="evo-chip" data-active={open} onClick={onToggle}>
        <Icon name={icon} size={14} />
        <span className="text-[var(--evo-fg)]">{label}</span>
        <span className="max-w-[180px] truncate">{value}</span>
      </button>
      <AnimatePresence>
        {open && (
          <motion.div
            className="evo-card absolute top-[calc(100%+6px)] left-0 z-20 min-w-[240px] p-1.5 shadow-xl"
            initial={{ opacity: 0, y: -4, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -4, scale: 0.98 }}
            transition={{ duration: 0.15 }}
          >
            {options.map((o) => (
              <button
                key={o}
                className={`block w-full rounded-lg px-3 py-2 text-left text-[13px] hover:bg-[var(--evo-brand-50)] ${o === value ? 'text-[var(--evo-brand)]' : ''}`}
                onClick={() => onPick(o)}
              >
                {o}
              </button>
            ))}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
