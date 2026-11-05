import { describe, expect, it } from 'vitest';

import {
  comparableTaskIds,
  compareOutcomeRows,
  sharedMetricRows,
} from '@/features/results/compare-logic';
import type { RunSummaryResponse } from '@/generated/api';

function run(id: string, taskId: string | null): RunSummaryResponse {
  return { run_id: id, data_state: 'complete', task_id: taskId };
}

describe('同一任务分组', () => {
  it('没有 task_id 的运行不参与对比', () => {
    expect(
      comparableTaskIds([run('a', null), run('b', null), run('c', 'hdd_mvp')]),
    ).toEqual([]);
  });

  it('同一任务至少两次才可对比', () => {
    expect(
      comparableTaskIds([
        run('a', 'hdd_mvp'),
        run('b', 'hdd_mvp'),
        run('c', 'ssd'),
      ]),
    ).toEqual(['hdd_mvp']);
  });
});

describe('并排字段', () => {
  it('只展示制品里的数，不计算分差', () => {
    const rows = compareOutcomeRows(
      {
        run_id: 'a',
        contract_version: '1.8.0',
        data_state: 'complete',
        outcome: { initial_score: 22.81, best_score: 30, iterations_done: 10, stop_reason: 'max_iterations' },
      },
      {
        run_id: 'b',
        contract_version: '1.8.0',
        data_state: 'complete',
        outcome: { initial_score: 22.81, best_score: null, iterations_done: 4, stop_reason: null },
      },
    );
    expect(rows.map((row) => row.label)).toEqual(['初始 ROS', '最佳 ROS', '完成轮次', '停止原因']);
    expect(rows[1].right).toEqual({ value: '未记录', recorded: false });
    expect(rows.some((row) => row.label.includes('分差'))).toBe(false);
  });

  it('分项指标只保留两边都有的键', () => {
    const rows = sharedMetricRows(
      { f1: 0.2, auprc: 0.1 },
      { f1: 0.3, recall: 0.4 },
    );
    expect(rows.map((row) => row.label)).toEqual(['f1']);
  });
});
