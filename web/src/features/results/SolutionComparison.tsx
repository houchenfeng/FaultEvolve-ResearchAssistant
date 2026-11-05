import { useState } from 'react';

import type { ComparisonMetric } from '@/features/results/solution-comparison';

interface SolutionComparisonProps {
  metrics: ComparisonMetric[];
  note: string;
  bestNodeId: string | null;
  initialNodeId: string | null;
  intent: string | null;
  onOpenNode: (nodeId: string) => void;
  baselineError: boolean;
  onRetryBaseline: () => void;
}

function valueLabel(value: number | null, unit: string): string {
  return value === null ? '未记录' : `${value.toFixed(unit === '%' ? 3 : 2)} ${unit}`;
}

export function SolutionComparison({
  metrics, note, bestNodeId, initialNodeId, intent, onOpenNode, baselineError, onRetryBaseline,
}: SolutionComparisonProps) {
  const [selected, setSelected] = useState('combined_score');
  const metric = metrics.find((item) => item.key === selected) ?? metrics[0];
  if (!metric) return null;

  return (
    <section className="fe-card p-4 sm:p-5" data-solution-comparison>
      <header className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold text-fg">方案效果对比</h2>
          <p className="mt-1 text-xs text-fg-subtle">初始方案与代码演化最优节点的实测表现；分层调优结果见下方</p>
        </div>
        <label className="flex items-center gap-2 text-xs text-fg-muted">
          对比指标
          <select
            aria-label="对比指标"
            className="rounded border border-border-subtle bg-surface px-2 py-1.5 text-fg"
            value={metric.key}
            onChange={(event) => setSelected(event.target.value)}
          >
            {metrics.map((item) => <option key={item.key} value={item.key}>{item.label}</option>)}
          </select>
        </label>
      </header>
      <div className="grid gap-6 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
        <figure aria-label={`${metric.label}：初始方案与最优方案对比`} className="min-w-0">
          <figcaption className="mb-4 flex justify-between text-xs text-fg-muted">
            <span>{metric.label}</span><span>{metric.direction}</span>
          </figcaption>
          <div className="flex flex-col gap-5">
            {([
              ['initial', '初始方案', metric.initial, 'bg-fg-subtle'],
              ['best', '最优方案', metric.best, 'bg-brand-500'],
            ] as const).map(([key, label, value, color]) => (
              <div key={key} data-solution-bar={key} data-recorded={value !== null}>
                <div className="mb-1.5 flex justify-between gap-2 text-xs">
                  <span className="text-fg-muted">{label}</span>
                  <strong className="tabular text-fg">{valueLabel(value, metric.unit)}</strong>
                </div>
                <div
                  role="img"
                  aria-label={`${label}：${valueLabel(value, metric.unit)}`}
                  title={`${label} · ${metric.label}：${valueLabel(value, metric.unit)}`}
                  className="h-5 overflow-hidden rounded bg-surface-muted"
                >
                  {value !== null ? (
                    <div className={`h-full rounded ${color}`} style={{ width: `${value / metric.maximum * 100}%` }} />
                  ) : null}
                </div>
              </div>
            ))}
          </div>
          <div className="mt-2 flex justify-between text-[10px] text-fg-subtle" aria-hidden="true">
            <span>0</span><span>{valueLabel(metric.maximum, metric.unit)}</span>
          </div>
          <p className="mt-3 text-[11px] text-fg-subtle">{note}</p>
          {baselineError ? (
            <p className="mt-2 text-xs text-warning-700">
              初始方案评估读取失败。
              <button className="ml-2 underline" onClick={onRetryBaseline}>重试初始方案</button>
            </p>
          ) : null}
        </figure>
        <aside className="min-w-0 border-t border-border-subtle pt-4 lg:border-l lg:border-t-0 lg:pl-5 lg:pt-0">
          <h3 className="text-xs font-medium text-fg-muted">最优方案的变更意图</h3>
          <p className="mt-2 whitespace-pre-wrap break-words text-sm text-fg">
            {intent || '本次运行未记录方案说明。'}
          </p>
          <p className="mt-2 text-[11px] text-fg-subtle">变更意图用于解释方案，实际效果以评估指标为准。</p>
          <div className="mt-3 flex flex-wrap gap-2">
            {initialNodeId ? <button className="fe-btn fe-btn-secondary fe-btn-sm" onClick={() => onOpenNode(initialNodeId)}>查看初始方案</button> : null}
            {bestNodeId ? <button className="fe-btn fe-btn-secondary fe-btn-sm" onClick={() => onOpenNode(bestNodeId)}>查看最优方案</button> : null}
          </div>
        </aside>
      </div>
      <details className="mt-4 border-t border-border-subtle pt-3 text-[11px] text-fg-subtle">
        <summary className="cursor-pointer">查看指标来源</summary>
        <p className="mt-2">{metric.source}</p>
        <p>初始节点：{initialNodeId ?? '未确认唯一初始节点'}；最优节点：{bestNodeId ?? '未记录'}</p>
      </details>
    </section>
  );
}
