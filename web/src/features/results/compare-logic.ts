/**
 * 同一任务的两次运行并排（PRD §13.3）。
 *
 * 只搬运行详情里已经有的字段。不减分、不重算 ROS、不补波动带。
 * 分项指标只保留两边 metric 字典都有的键。
 */
import type { NodeEvaluationResponse, RunDetailResponse, RunSummaryResponse } from '@/generated/api';

import { countCell, type Cell } from '@/features/discovery/card-logic';
import { metricRows, scoreCell, textCell } from '@/features/results/results-logic';

export const NOISE_UNRECORDED =
  '本次制品未记录运行波动，不能判断分差是否超出噪声。';

export function comparableTaskIds(runs: RunSummaryResponse[]): string[] {
  const counts = new Map<string, number>();
  for (const run of runs) {
    const taskId = run.task_id?.trim();
    if (!taskId) continue;
    counts.set(taskId, (counts.get(taskId) ?? 0) + 1);
  }
  return [...counts.entries()]
    .filter(([, count]) => count >= 2)
    .map(([taskId]) => taskId)
    .sort();
}

export function runsForTask(runs: RunSummaryResponse[], taskId: string): RunSummaryResponse[] {
  return runs.filter((run) => run.task_id === taskId);
}

export interface ComparePair {
  label: string;
  left: Cell;
  right: Cell;
}

export function compareOutcomeRows(
  left: RunDetailResponse | null | undefined,
  right: RunDetailResponse | null | undefined,
): ComparePair[] {
  const a = left?.outcome;
  const b = right?.outcome;
  return [
    { label: '初始 ROS', left: scoreCell(a?.initial_score), right: scoreCell(b?.initial_score) },
    { label: '最佳 ROS', left: scoreCell(a?.best_score), right: scoreCell(b?.best_score) },
    { label: '完成轮次', left: countCell(a?.iterations_done), right: countCell(b?.iterations_done) },
    { label: '停止原因', left: textCell(a?.stop_reason), right: textCell(b?.stop_reason) },
  ];
}

export function sharedMetricRows(
  left: NodeEvaluationResponse['metric'] | undefined,
  right: NodeEvaluationResponse['metric'] | undefined,
): ComparePair[] {
  const leftCells = new Map(metricRows(left).map((row) => [row.key, row.cell]));
  const rightCells = new Map(metricRows(right).map((row) => [row.key, row.cell]));
  return [...leftCells.keys()]
    .filter((key) => rightCells.has(key))
    .sort()
    .map((key) => ({
      label: key,
      left: leftCells.get(key) ?? { value: '未记录', recorded: false },
      right: rightCells.get(key) ?? { value: '未记录', recorded: false },
    }));
}
