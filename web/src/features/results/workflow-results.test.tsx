import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { WorkflowResults } from '@/features/results/WorkflowResults';
import type { WorkflowResponse } from '@/generated/api';

const evidence: WorkflowResponse = {
  run_id: 'run', state: 'finished', phase: 'complete', data_state: 'available', search_state: 'available',
  final_best_score: 41.7797, evolution_best_score: 41.0619, best_origin: 'hierarchical_hpo', best_artifact_id: 'workflow-best',
  data: { state: 'passed', before_rows: 5, after_rows: 4, before_samples: 4, after_samples: 4,
    transformations: [{ rule: 'drop_exact_history_duplicates', affected: 1, reason: '删除完全重复行' }] },
  search: { completed_trials: 3, max_trials: 5, default_barrier_open: true, stop_reason: 'trial_budget_exhausted',
    routes: [{ route_id: 'a', default_score: 30, best_score: 41.7797, visits: 2 }, { route_id: 'b', visits: 1 }],
    trials: [
      { trial_number: 1, candidate_id: 'a-default', route_id: 'a', depth: 0, score: 30, decision: 'default_observed' },
      { trial_number: 2, candidate_id: 'b-failed', route_id: 'b', depth: 0, score: null, status: 'failed' },
      { trial_number: 3, candidate_id: 'a-tuned', route_id: 'a', parent_id: 'a-default', depth: 1, score: 41.7797,
        decision: 'keep', changed_parameter: 'C', parameters: { C: .5 }, reward: .1, reason: 'metric_improvement' },
    ] },
  effect_state: 'available',
  effect: {
    solutions: [
      { key: 'baseline', label: '初始方案', performance: { combined_score: 22.8, precision: .198, recall: .336, false_alarm_rate: .0034, missed_detection_rate: .664 },
        complexity: { model_families: ['LogisticRegression'], estimated_parameters: 15, ensemble_fits: 1, source_lines: 62, branch_points: 4 } },
      { key: 'final', label: '分层调优最终', performance: { combined_score: 41.8, precision: .388, recall: .491, false_alarm_rate: .001933, missed_detection_rate: .509 },
        complexity: { model_families: ['LGBMClassifier'], estimated_parameters: 63525, ensemble_fits: 3, source_lines: 103, branch_points: 11 } },
    ],
    token_usage: { total_tokens: 74679, generate_tokens: 60094, reflect_tokens: 14585, hierarchical_tokens: 0 },
    note: '验证集结果。',
    convergence: { target_score: 33.7, target_reached: true, rounds_to_target: 1, time_to_target_s: 123.4, tokens_to_target: 20360,
      evolution_rounds: 3, evolution_stop_reason: 'max_iterations', hpo_trials: 24, hpo_best_trial: 5, hpo_elapsed_s: 267.5,
      hpo_stop_reason: 'trial_budget_exhausted',
      evolution_curve: [{ round: 1, score: 36.8, best_so_far: 36.8, elapsed_s: 123.4 }, { round: 2, score: 38.9, best_so_far: 38.9, elapsed_s: 286.7 }],
      hpo_curve: [{ trial: 5, best_so_far: 41.8 }] },
    automation: { stages: 3, evolution_attempts: 3, hpo_trials: 24, total_steps: 30, manual_interventions: 0,
      automatic_coverage: 1, end_to_end_unattended: true, self_recovered_failures: 0, unrecovered_adapter_errors: 0 },
  },
};

function show(data?: WorkflowResponse, error: unknown = null) {
  return render(<WorkflowResults runId="run" data={data} error={error} pending={false} onRetry={vi.fn()} />);
}

describe('统一运行结果', () => {
  it('renders preprocessing, the measured final score and downloadable final candidate', async () => {
    show(evidence);
    expect(screen.getByText(/历史行 5 → 4/)).toBeInTheDocument();
    expect(screen.getByText(/最终最佳：41.7797/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '下载最终程序' })).toHaveAttribute('href', '/api/runs/run/artifacts/workflow-best');
    expect(screen.getByRole('img', { name: '分层试验实测评分曲线' })).toBeInTheDocument();
    const table = screen.getByRole('table', { name: '分层搜索试验记录' });
    const failed = within(table).getAllByRole('row')[2];
    expect(failed).toHaveTextContent('未记录');
    await userEvent.selectOptions(screen.getByRole('combobox', { name: '筛选分层搜索路线' }), 'a');
    expect(within(table).getAllByRole('row')).toHaveLength(3);
    expect(within(table).queryByText('b-failed')).not.toBeInTheDocument();
    await userEvent.click(within(table).getByText('C'));
    expect(within(table).getByText(/"C": 0.5/)).toBeInTheDocument();
  });

  it('keeps absent records distinct from corrupted or failed requests', () => {
    const { unmount } = show({ run_id: 'run', data_state: 'missing', search_state: 'missing' });
    expect(screen.getByText('这次运行未记录分层搜索试验。')).toBeInTheDocument();
    unmount();
    show({ run_id: 'run', data_state: 'missing', search_state: 'invalid' });
    expect(screen.getByRole('alert')).toHaveTextContent('分层搜索记录损坏');
    expect(screen.queryByRole('img')).not.toBeInTheDocument();
  });
});

describe('effect report', () => {
  it('shows performance, false/missed alarms, parameters and token usage per solution', () => {
    show(evidence);
    const table = within(screen.getByRole('table', { name: '各方案的预测性能与模型复杂度对比' }));
    expect(table.getByRole('columnheader', { name: '分层调优最终' })).toBeInTheDocument();
    const row = (name: string) => table.getByRole('row', { name: new RegExp(name) });
    expect(row('召回率')).toHaveTextContent('33.60%');
    expect(row('召回率')).toHaveTextContent('49.10%');
    expect(row('误告率')).toHaveTextContent('0.193%');
    expect(row('漏告率')).toHaveTextContent('50.90%');
    expect(row('估计参数量')).toHaveTextContent('63,525');
    expect(screen.getByText(/共 74,679/)).toBeInTheDocument();
  });

  it('shows convergence to target, the best-so-far curve and automation coverage', () => {
    show(evidence);
    expect(screen.getByText(/第 1 轮达到，用时 2\.1 分钟，累计 20,360 token/)).toBeInTheDocument();
    const curve = within(screen.getByRole('table', { name: '逐轮最佳评分' }));
    expect(curve.getByRole('row', { name: /演化第 2 轮/ })).toHaveTextContent('38.9000');
    expect(curve.getByRole('row', { name: /调优第 5 次/ })).toHaveTextContent('41.8000');
    expect(screen.getByText('自动化覆盖率 100.0%')).toBeInTheDocument();
    expect(screen.getByText(/人工介入 0 次，全流程无人值守/)).toBeInTheDocument();
  });

  it('says so when a target was set but not reached', () => {
    const missed = { ...evidence.effect!, convergence: { ...evidence.effect!.convergence!, target_reached: false, rounds_to_target: null } };
    show({ ...evidence, effect: missed });
    expect(screen.getByText(/目标分 33\.7000：本次未达到/)).toBeInTheDocument();
  });

  it('flags a damaged effect record instead of showing numbers', () => {
    show({ ...evidence, effect: undefined, effect_state: 'invalid' });
    expect(screen.getByRole('alert', { name: '' }) ?? null).toBeTruthy();
    expect(screen.getByText('效果记录损坏，预测性能与复杂度未知。')).toBeInTheDocument();
  });
});
