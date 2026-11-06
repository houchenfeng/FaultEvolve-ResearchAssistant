/**
 * 路演演示外壳：对话 → 确认 → 进化 → 知识发现 → 结果讲解。
 *
 * 所有阶段同时挂在一个 LayoutGroup 里，主角 Bot 用同一个 layoutId，
 * 阶段切换时由 motion 的共享布局动画把它“跳”到新位置。
 */
import { AnimatePresence, LayoutGroup, motion } from 'motion/react';
import { useState } from 'react';

import { DEMO_REPORT_INPUT } from './demo-script';
import './evodemo.css';
import { buildRunReport } from './report';
import type { TaskDraft } from './screens/HomeScreen';
import { HomeScreen } from './screens/HomeScreen';
import { ConfirmScreen } from './screens/ConfirmScreen';
import { ResultsScreen } from './screens/ResultsScreen';
import { TournamentScreen } from './screens/TournamentScreen';
import { WorkbenchScreen } from './screens/WorkbenchScreen';
import { BrandMark, Icon, SettingsPanel } from './ui';

type Stage = 'home' | 'confirm' | 'workbench' | 'tournament' | 'results';

const STAGES: { key: Stage; label: string }[] = [
  { key: 'home', label: '对话' },
  { key: 'confirm', label: '确认' },
  { key: 'workbench', label: '进化工作台' },
  { key: 'tournament', label: '知识发现' },
  { key: 'results', label: '结果讲解' },
];

const DEFAULT_DRAFT: TaskDraft = {
  text: '',
  evaluation: 'ROS · 本地 evaluator.py',
  seed: '注入已有知识',
};

const DEMO_REPORT = buildRunReport(DEMO_REPORT_INPUT);

const SAMPLE_TASK = '用 SMART 日志提前 7 天预测硬盘故障，评估用 ROS，误报预算 3%。';

export function EvoDemoApp() {
  const [stage, setStage] = useState<Stage>('home');
  const [draft, setDraft] = useState<TaskDraft>(DEFAULT_DRAFT);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [cameFromConfirm, setCameFromConfirm] = useState(false);

  const go = (next: Stage) => {
    if (next === 'confirm' && !draft.text.trim()) setDraft((d) => ({ ...d, text: SAMPLE_TASK }));
    setCameFromConfirm(stage === 'confirm' && next === 'workbench');
    setStage(next);
  };

  return (
    <div className="evo-demo flex flex-col">
      <header className="relative z-20 flex h-14 shrink-0 items-center gap-4 border-b border-[var(--evo-border)] bg-white/70 px-5 backdrop-blur">
        <button className="flex items-center gap-2" onClick={() => go('home')}>
          <BrandMark size={26} />
          <span className="text-[15px] font-bold tracking-tight">FaultEvolve</span>
          <span className="hidden text-xs text-[var(--evo-muted)] xl:inline">自演化故障预测智能体</span>
        </button>

        <nav className="mx-auto flex items-center gap-1 rounded-full border border-[var(--evo-border)] bg-white p-1">
          {STAGES.map((s, i) => {
            const active = s.key === stage;
            return (
              <button key={s.key} className="relative rounded-full px-3.5 py-1 text-[12.5px]" onClick={() => go(s.key)}>
                {active && <motion.span layoutId="stage-pill" className="absolute inset-0 rounded-full bg-[var(--evo-brand)]" transition={{ type: 'spring', stiffness: 380, damping: 32 }} />}
                <span className={`relative ${active ? 'font-semibold text-white' : 'text-[var(--evo-muted)]'}`}>
                  {i + 1} {s.label}
                </span>
              </button>
            );
          })}
        </nav>

        <span className="flex items-center gap-1.5 rounded-full border border-amber-200 bg-amber-50 px-2.5 py-1 text-[11.5px] text-amber-700">
          <span className="size-1.5 rounded-full bg-amber-500" /> 演示数据 · HDD 展示运行
        </span>
        <span className="hidden items-center gap-1.5 rounded-full border border-green-200 bg-green-50 px-2.5 py-1 text-[11.5px] text-green-700 lg:flex">
          <span className="size-1.5 rounded-full bg-green-500" /> 本地评估 · 云端进化 已就绪
        </span>
        <button className="flex items-center gap-1 rounded-lg px-2 py-1.5 text-[13px] text-[var(--evo-muted)] hover:bg-slate-100" onClick={() => setSettingsOpen(true)}>
          <Icon name="gear" /> 设置
        </button>
      </header>

      <LayoutGroup>
        <main className="relative min-h-0 flex-1">
          <AnimatePresence>
            <motion.div
              key={stage}
              className="absolute inset-0"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.35 }}
            >
              {stage === 'home' && <HomeScreen draft={draft} onDraft={setDraft} onSubmit={() => go('confirm')} onOpenHistory={() => go('results')} />}
              {stage === 'confirm' && (
                <ConfirmScreen draft={draft} onDraft={setDraft} onConfirm={() => go('workbench')} onBack={() => go('home')} onOpenSettings={() => setSettingsOpen(true)} />
              )}
              {stage === 'workbench' && <WorkbenchScreen skipIntro={!cameFromConfirm} onNext={() => go('tournament')} />}
              {stage === 'tournament' && <TournamentScreen onNext={() => go('results')} />}
              {stage === 'results' && (
                <ResultsScreen
                  report={DEMO_REPORT}
                  onRestart={() => {
                    setDraft(DEFAULT_DRAFT);
                    go('home');
                  }}
                />
              )}
            </motion.div>
          </AnimatePresence>
        </main>
      </LayoutGroup>

      <SettingsPanel open={settingsOpen} onClose={() => setSettingsOpen(false)} />
    </div>
  );
}
