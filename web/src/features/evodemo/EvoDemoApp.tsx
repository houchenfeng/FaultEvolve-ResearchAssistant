/**
 * 路演演示外壳：对话 → 确认 → 进化 → 知识发现 → 结果讲解。
 *
 * 所有阶段同时挂在一个 LayoutGroup 里，主角 Bot 用同一个 layoutId，
 * 阶段切换时由 motion 的共享布局动画把它“跳”到新位置。
 * 当前演示哪个案例由初始解决定：最新论文 → 论文组合案例，其余 → KGTE 三岛进化。
 * 进化工作台有两种运行方式：回放真实实验，或接入混合云实时运行——平板数据进本机评估域、
 * 本机 GPU 评估、远端服务器自进化，三端协作都在工作台里展示。
 */
import { AnimatePresence, LayoutGroup, motion } from 'motion/react';
import { useState } from 'react';

import { CASES, DEFAULT_CASE, caseForSeed } from './cases';
import type { CaseId } from './cases/types';
import './evodemo.css';
import type { TaskDraft } from './screens/HomeScreen';
import { HomeScreen } from './screens/HomeScreen';
import { ConfirmScreen } from './screens/ConfirmScreen';
import type { RunMode } from './screens/hybrid-parts';
import { LiveWorkbenchScreen } from './screens/LiveWorkbenchScreen';
import { PaperWorkbenchScreen } from './screens/PaperWorkbenchScreen';
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

const LIVE_GENERATIONS = 2;

/** `?stage=` 直达某一幕；`hybrid` / `live` 直达进化工作台的混合云实时模式。 */
function initialRoute(): { stage: Stage; runMode: RunMode } {
  const wanted = new URLSearchParams(window.location.search).get('stage');
  if (wanted === 'hybrid' || wanted === 'live') return { stage: 'workbench', runMode: 'demo' };
  return { stage: STAGES.find((s) => s.key === wanted)?.key ?? 'home', runMode: 'replay' };
}

const DEFAULT_DRAFT: TaskDraft = {
  text: '',
  evaluation: DEFAULT_CASE.evaluation,
  seed: DEFAULT_CASE.seed,
};

export function EvoDemoApp() {
  const [route] = useState(initialRoute);
  const [stage, setStage] = useState<Stage>(route.stage);
  const [runMode, setRunMode] = useState<RunMode>(route.runMode);
  const [autoStart, setAutoStart] = useState(false);
  const [draft, setDraft] = useState<TaskDraft>(DEFAULT_DRAFT);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [cameFromConfirm, setCameFromConfirm] = useState(false);
  const demo = caseForSeed(draft.seed);
  const live = runMode !== 'replay';

  const go = (next: Stage) => {
    if (next === 'confirm' && !draft.text.trim()) setDraft((d) => ({ ...d, text: demo.sampleTask }));
    setCameFromConfirm(stage === 'confirm' && next === 'workbench');
    if (next !== 'workbench') setAutoStart(false);
    setStage(next);
  };

  const confirm = () => {
    setAutoStart(live);
    go('workbench');
  };

  const openCase = (id: CaseId) => {
    const target = CASES[id];
    setDraft({ text: target.sampleTask, evaluation: target.evaluation, seed: target.seed });
    setCameFromConfirm(false);
    setRunMode('replay');
    setStage('results');
  };

  const liveBadge = runMode === 'real' ? '混合云 · 真实运行' : '混合云 · 演示回放';
  const showLive = live && stage === 'workbench';

  return (
    <div className="evo-demo flex flex-col">
      <header className="relative z-20 flex h-14 shrink-0 items-center gap-4 border-b border-[var(--evo-border)] bg-white/70 px-5 backdrop-blur">
        <button className="flex items-center gap-2" onClick={() => go('home')}>
          <BrandMark size={26} />
          <span className="text-[15px] font-bold tracking-tight">FaultEvolve</span>
          <span className="hidden text-xs text-[var(--evo-muted)] 2xl:inline">自演化故障预测智能体</span>
        </button>

        <nav className="mx-auto flex items-center gap-1 rounded-full border border-[var(--evo-border)] bg-white p-1">
          {STAGES.map((s, i) => {
            const active = s.key === stage;
            return (
              <button key={s.key} className="relative rounded-full px-3.5 py-1 text-[12.5px] whitespace-nowrap" onClick={() => go(s.key)}>
                {active && <motion.span layoutId="stage-pill" className="absolute inset-0 rounded-full bg-[var(--evo-brand)]" transition={{ type: 'spring', stiffness: 380, damping: 32 }} />}
                <span className={`relative ${active ? 'font-semibold text-white' : 'text-[var(--evo-muted)]'}`}>
                  {i + 1} {s.label}
                </span>
              </button>
            );
          })}
        </nav>

        {stage === 'workbench' && (
          <div className="flex items-center gap-1 rounded-full border border-[var(--evo-border)] bg-white p-0.5 text-[11.5px]">
            <button className={`rounded-full px-2.5 py-1 ${!live ? 'bg-slate-900 text-white' : 'text-[var(--evo-muted)]'}`} onClick={() => setRunMode('replay')}>
              回放
            </button>
            <button
              className={`rounded-full px-2.5 py-1 whitespace-nowrap ${live ? 'bg-slate-900 text-white' : 'text-[var(--evo-muted)]'}`}
              onClick={() => {
                setAutoStart(false);
                setRunMode(runMode === 'real' ? 'real' : 'demo');
              }}
            >
              混合云模式
            </button>
          </div>
        )}
        <span className="flex items-center gap-1.5 rounded-full border border-amber-200 bg-amber-50 px-2.5 py-1 text-[11.5px] whitespace-nowrap text-amber-700">
          <span className="size-1.5 rounded-full bg-amber-500" /> {showLive ? '实时 · 非回放' : demo.badge}
        </span>
        <span className="hidden items-center gap-1.5 rounded-full border border-green-200 bg-green-50 px-2.5 py-1 text-[11.5px] whitespace-nowrap text-green-700 xl:flex">
          <span className="size-1.5 rounded-full bg-green-500" /> {showLive ? liveBadge : demo.name}
        </span>
        <button className="flex items-center gap-1 rounded-lg px-2 py-1.5 text-[13px] whitespace-nowrap text-[var(--evo-muted)] hover:bg-slate-100" onClick={() => setSettingsOpen(true)}>
          <Icon name="gear" /> 设置
        </button>
      </header>

      <LayoutGroup>
        <main className="relative min-h-0 flex-1">
          <AnimatePresence>
            <motion.div
              key={`${stage}-${demo.id}-${showLive ? runMode : 'replay'}`}
              className="absolute inset-0"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.35 }}
            >
              {stage === 'home' && <HomeScreen draft={draft} onDraft={setDraft} onSubmit={() => go('confirm')} onOpenHistory={openCase} />}
              {stage === 'confirm' && (
                <ConfirmScreen
                  demo={demo}
                  draft={draft}
                  onDraft={setDraft}
                  onConfirm={confirm}
                  onBack={() => go('home')}
                  onOpenSettings={() => setSettingsOpen(true)}
                  runMode={runMode}
                  onRunMode={setRunMode}
                />
              )}
              {stage === 'workbench' &&
                (showLive ? (
                  <LiveWorkbenchScreen mode={runMode === 'real' ? 'real' : 'demo'} generations={LIVE_GENERATIONS} autoStart={autoStart} onNext={() => go('tournament')} />
                ) : demo.id === 'paper' ? (
                  <PaperWorkbenchScreen demo={demo} skipIntro={!cameFromConfirm} onNext={() => go('tournament')} />
                ) : (
                  <WorkbenchScreen demo={demo} skipIntro={!cameFromConfirm} onNext={() => go('tournament')} />
                ))}
              {stage === 'tournament' && <TournamentScreen script={demo.debate} onNext={() => go('results')} />}
              {stage === 'results' && (
                <ResultsScreen
                  report={demo.report}
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
