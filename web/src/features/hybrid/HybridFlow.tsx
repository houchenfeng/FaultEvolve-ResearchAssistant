/**
 * 顶部"数据边界"流转条：上半是云端，下半是本地评估域，中间一条虚线就是边界。
 * 当前步骤由本地评估域的真实状态推出，不是动画循环。
 */
import type { EdgeState, Evaluation } from './edge-api';

const STEPS = [
  { key: 'cloud', title: '云端提出候选', where: 'cloud', hint: 'Qwen 生成 · KGTE 岛群 · J-PUCT' },
  { key: 'ship', title: '候选代码下发', where: 'cloud', hint: '只下发代码，不带数据' },
  { key: 'ingest', title: '边缘遥测接入', where: 'local', hint: '平板 → 笔记本（局域网）' },
  { key: 'eval', title: '本地沙箱 + GPU 评估', where: 'local', hint: 'evaluator.py · 配对 bootstrap' },
  { key: 'upload', title: '白名单回传分数', where: 'local', hint: '仅分数与聚合统计' },
] as const;

function activeStep(state: EdgeState | undefined, evaluation: Evaluation | undefined): number {
  if (evaluation?.status === 'running') return 3;
  if (state?.stream.phase === 'scoring') return 3;
  if (state?.stream.phase === 'ingesting' || state?.stream.phase === 'observing') return 2;
  if ((state?.uploads.length ?? 0) > 0) return 4;
  return 0;
}

export function HybridFlow({ state, evaluation }: { state?: EdgeState; evaluation?: Evaluation }) {
  const active = activeStep(state, evaluation);
  return (
    <section className="fe-card overflow-hidden p-0" data-hybrid-flow="true">
      <div className="grid grid-cols-5">
        {STEPS.map((step, i) => {
          const done = i < active;
          const now = i === active;
          return (
            <div
              key={step.key}
              className={`relative flex flex-col gap-1 px-3 py-3 ${step.where === 'cloud' ? 'bg-brand-50/60 dark:bg-brand-500/5' : 'bg-success-50/50 dark:bg-success-500/5'} ${i > 0 ? 'border-l border-border-subtle' : ''}`}
            >
              <div className="flex items-center gap-2">
                <span
                  className={`flex h-6 w-6 items-center justify-center rounded-full text-[11px] font-semibold ${
                    now
                      ? 'bg-brand-500 text-white shadow-[0_0_0_4px_rgba(0,120,212,0.18)]'
                      : done
                        ? 'bg-success-500 text-white'
                        : 'border border-border-strong text-fg-muted'
                  }`}
                >
                  {done ? '✓' : i + 1}
                </span>
                <span className="text-xs font-semibold text-fg">{step.title}</span>
              </div>
              <span className="pl-8 text-[11px] text-fg-muted">{step.hint}</span>
              <span className={`pl-8 text-[10px] font-medium ${step.where === 'cloud' ? 'text-brand-600' : 'text-success-700 dark:text-success-500'}`}>
                {step.where === 'cloud' ? '云端 · 服务器回放' : '本地评估域 · 实时'}
              </span>
            </div>
          );
        })}
      </div>
      <div className="flex items-center gap-2 border-t border-dashed border-warning-500/60 bg-warning-50/60 px-3 py-1.5 text-[11px] text-warning-700 dark:bg-warning-500/5 dark:text-warning-500">
        <span className="font-semibold">数据边界</span>
        <span>原始遥测、标签、逐盘预测与模型权重留在本机；越过边界的只有白名单内的分数与聚合统计。</span>
      </div>
    </section>
  );
}
