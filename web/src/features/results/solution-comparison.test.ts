import { describe, expect, it } from 'vitest';

import { initialNodeIdOf, solutionComparison } from '@/features/results/solution-comparison';
import type { NodeEvaluationResponse, TreeNodeDto, TreeResponse } from '@/generated/api';

const outcome = { initial_score: 20, best_score: 30 };
function evaluation(nodeId: string, score: number, metric: Record<string, unknown>): NodeEvaluationResponse {
  return { node_id: nodeId, validity: 1, combined_score: score, metric: { split: 'val', ...metric } };
}

describe('方案效果对比', () => {
  it('uses real measurements, preserves zero and marks missing values', () => {
    const { metrics } = solutionComparison(outcome,
      evaluation('init', 20, { recall: 0, run_time_s: 60 }),
      evaluation('best', 30, { recall: 0.8, false_alarm_rate: 0.002, run_time_s: 30 }),
    );
    expect(metrics.find((m) => m.key === 'recall')).toMatchObject({ initial: 0, best: 80, maximum: 100 });
    expect(metrics.find((m) => m.key === 'false_alarm_rate')).toMatchObject({ initial: null, best: 0.2, direction: '越低越好' });
    expect(metrics.find((m) => m.key === 'run_time_s')).toMatchObject({ initial: 60, best: 30, maximum: 60 });
  });

  it('does not compare different splits, invalid evaluations or inconsistent snapshots', () => {
    const initial = evaluation('init', 20, { recall: 0.5 });
    for (const best of [
      evaluation('best', 30, { split: 'test', recall: 0.7 }),
      evaluation('best', 30, { split: null, recall: 0.7 }),
      { ...evaluation('best', 30, { recall: 0.7 }), validity: 0 },
      evaluation('best', 29, { recall: 0.7 }),
    ]) {
      expect(solutionComparison(outcome, initial, best).metrics).toHaveLength(1);
    }
  });

  it('rejects nonfinite, out-of-range and string metric values', () => {
    const result = solutionComparison({ initial_score: NaN, best_score: Infinity }, null, null);
    expect(result.metrics[0]).toMatchObject({ initial: null, best: null, maximum: 100 });
    const { metrics } = solutionComparison(outcome,
      evaluation('init', 20, { recall: Infinity, auprc: -1, precision: '0.5' }),
      evaluation('best', 30, { recall: NaN, auprc: 2, precision: true }),
    );
    expect(metrics).toHaveLength(1);
  });

  it('selects the best island baseline and never guesses among ambiguous roots', () => {
    const nodes = [
      { id: 'a0', operator: 'init', depth: 0, island_id: 'a' },
      { id: 'b0', operator: 'init', depth: 0, island_id: 'b' },
      { id: 'b1', operator: 'refine', depth: 1, parent_id: 'b0', island_id: 'b' },
    ] as TreeNodeDto[];
    const tree: TreeResponse = { contract_version: '1.3.0', data_state: 'complete', run_id: 'test', nodes, edges: [] };
    expect(initialNodeIdOf(tree, 'b1')).toBe('b0');
    expect(initialNodeIdOf(tree, 'unknown')).toBeNull();
    expect(initialNodeIdOf({ ...tree, nodes: [...nodes, { ...nodes[1], id: 'b2' }] }, 'b1')).toBeNull();
    expect(initialNodeIdOf(undefined)).toBeNull();
  });
});
