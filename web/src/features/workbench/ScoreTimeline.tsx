/**
 * 分数时间轴（TODO 5.6 / PRD §9.6）。
 *
 * 画的是 `ScorePointResponse` 序列：横轴是迭代，纵轴是分数。
 * **噪声带用后端给的 `within_noise_band`**，不在这里重新判定（TODO 5.4）。
 */
import { useMemo } from 'react';

import type { ScorePointResponse } from '@/generated/api';

export interface ScoreTimelineProps {
  points: ScorePointResponse[];
  bestPath: string[];
  onLocateNode?: (nodeId: string) => void;
  highlightNodeId?: string | null;
}

export function ScoreTimeline({ points, bestPath, onLocateNode, highlightNodeId }: ScoreTimelineProps) {
  const scored = useMemo(
    () => points.filter((point) => typeof point.score === 'number'),
    [points],
  );
  const bestSet = useMemo(() => new Set(bestPath), [bestPath]);

  const bounds = useMemo(() => {
    if (scored.length === 0) return null;
    const scores = scored.map((point) => point.score as number);
    const min = Math.min(...scores);
    const max = Math.max(...scores);
    // 全平的时候也要有一个高度，否则除零。
    const span = max - min || 1;
    return { min, max, span };
  }, [scored]);

  if (!bounds || scored.length === 0) {
    return (
      <div className="px-3 py-4 text-[11px] text-fg-subtle" data-testid="score-timeline">
        没有已评分的节点，无法绘制分数曲线
      </div>
    );
  }

  const width = 100;
  const height = 28;
  const xOf = (index: number) => (scored.length === 1 ? width / 2 : (index / (scored.length - 1)) * width);
  const yOf = (score: number) => height - ((score - bounds.min) / bounds.span) * height;

  const path = scored
    .map((point, index) => `${index === 0 ? 'M' : 'L'} ${xOf(index).toFixed(2)} ${yOf(point.score as number).toFixed(2)}`)
    .join(' ');

  return (
    <div className="flex flex-col gap-1.5 px-3 py-2" data-testid="score-timeline">
      <div className="flex items-center justify-between text-[11px] text-fg-muted">
        <span>分数曲线（{scored.length} 个已评分节点）</span>
        <span className="tabular">
          {bounds.min.toFixed(3)} – {bounds.max.toFixed(3)}
        </span>
      </div>

      <svg viewBox={`0 0 ${width} ${height}`} className="h-16 w-full" preserveAspectRatio="none" role="img">
        <title>分数随迭代变化</title>
        <path d={path} fill="none" stroke="var(--color-brand-500)" strokeWidth="0.8" vectorEffect="non-scaling-stroke" />
        {scored.map((point, index) => {
          const inBand = point.within_noise_band === true;
          const unknown = point.within_noise_band === null || point.within_noise_band === undefined;
          const onBest = bestSet.has(point.node_id);
          return (
            <circle
              key={point.node_id}
              cx={xOf(index)}
              cy={yOf(point.score as number)}
              r={highlightNodeId === point.node_id ? 1.8 : 1}
              fill={
                unknown
                  ? 'var(--color-border-strong)'
                  : inBand
                    ? 'var(--color-neutral-500)'
                    : 'var(--color-success-500)'
              }
              stroke={onBest ? 'var(--color-brand-600)' : 'none'}
              strokeWidth="0.6"
              vectorEffect="non-scaling-stroke"
            />
          );
        })}
      </svg>

      <div className="flex flex-wrap items-center gap-3 text-[11px] text-fg-muted">
        <LegendDot color="var(--color-success-500)" label="超出噪声带" />
        <LegendDot color="var(--color-neutral-500)" label="噪声内" />
        <LegendDot color="var(--color-border-strong)" label="无法判断" />
        <LegendDot color="var(--color-brand-600)" label="最优路径（描边）" />
      </div>

      {onLocateNode ? (
        <div className="flex flex-wrap gap-1">
          {scored.map((point) => (
            <button
              key={point.node_id}
              type="button"
              onClick={() => onLocateNode(point.node_id)}
              className={`tabular rounded-card border px-1.5 py-px text-[10px] ${
                highlightNodeId === point.node_id
                  ? 'border-brand-500 text-brand-600 dark:text-brand-300'
                  : 'border-border-subtle text-fg-muted hover:border-brand-500'
              }`}
              title={`第 ${point.iteration ?? '?'} 次迭代 · ${
                point.within_noise_band === null || point.within_noise_band === undefined
                  ? '噪声带未知'
                  : point.within_noise_band
                    ? '噪声内'
                    : '有效改进'
              }`}
            >
              {point.node_id.slice(0, 8)} {(point.score as number).toFixed(2)}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function LegendDot({ color, label }: { color: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-1">
      <span className="size-1.5 rounded-full" style={{ background: color }} />
      {label}
    </span>
  );
}
