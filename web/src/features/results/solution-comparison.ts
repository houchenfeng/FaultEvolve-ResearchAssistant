/** Display evaluator measurements without inferring missing baselines or splits. */
import type { NodeEvaluationResponse, RunOutcomeResponse, TreeResponse } from '@/generated/api';

export function initialNodeIdOf(tree: TreeResponse | null | undefined, bestNodeId?: string | null): string | null {
  const children = new Set(tree?.edges.map((edge) => edge.target));
  const roots = tree?.nodes.filter(
    (node) => node.operator === 'init' && node.depth === 0 && !node.parent_id && !children.has(node.id),
  ) ?? [];
  if (roots.length === 1) return roots[0].id;
  const island = tree?.nodes.find((node) => node.id === bestNodeId)?.island_id;
  const islandRoots = island ? roots.filter((node) => node.island_id === island) : [];
  return islandRoots.length === 1 ? islandRoots[0].id : null;
}

export interface ComparisonMetric {
  key: string;
  label: string;
  unit: string;
  direction: string;
  initial: number | null;
  best: number | null;
  maximum: number;
  source: string;
}

function finite(value: unknown, max = Infinity): number | null {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= max
    ? value : null;
}

const RATE_METRICS = [
  ['f1_p10', '稳健 F1（下分位）', '越高越好'],
  ['auprc', '排序质量 AUPRC', '越高越好'],
  ['recall_at_far', '误告预算内召回率', '越高越好'],
  ['precision', '告警准确率', '越高越好'],
  ['recall', '故障召回率', '越高越好'],
  ['false_alarm_rate', '误告率', '越低越好'],
  ['missed_detection_rate', '漏告率', '越低越好'],
  ['f1', 'F1', '越高越好'],
] as const;

export function solutionComparison(
  outcome: RunOutcomeResponse | null | undefined,
  initial: NodeEvaluationResponse | null | undefined,
  best: NodeEvaluationResponse | null | undefined,
): { metrics: ComparisonMetric[]; note: string } {
  const initialScore = finite(outcome?.initial_score);
  const bestScore = finite(outcome?.best_score);
  const metrics: ComparisonMetric[] = [{
    key: 'combined_score', label: '综合评分 ROS', unit: '分', direction: '越高越好',
    initial: initialScore, best: bestScore,
    maximum: Math.max(100, initialScore ?? 0, bestScore ?? 0), source: 'run_summary.json → initial_score / best_score',
  }];
  if (!initial || !best || initial.validity !== 1 || best.validity !== 1) {
    return { metrics, note: '初始方案或最优方案的有效评估记录尚未齐备，分项对比暂不可用。' };
  }
  if (initial.combined_score !== initialScore || best.combined_score !== bestScore) {
    return { metrics, note: '节点评分与运行摘要不一致，分项对比暂停；请核对运行产物是否来自同一快照。' };
  }
  const split = initial.metric?.split;
  if (typeof split !== 'string' || !split || split !== best.metric?.split) {
    return { metrics, note: '两份评估的划分未记录或不一致，分项指标暂不对比。' };
  }
  for (const [key, label, direction] of RATE_METRICS) {
    const before = finite(initial.metric?.[key], 1);
    const after = finite(best.metric?.[key], 1);
    // At least one measured value is useful; the other is explicitly missing.
    if (before === null && after === null) continue;
    metrics.push({
      key, label, unit: '%', direction,
      initial: before === null ? null : before * 100,
      best: after === null ? null : after * 100,
      maximum: 100, source: `本地评估 → metric.${key}`,
    });
  }
  const beforeTime = finite(initial.metric?.run_time_s);
  const afterTime = finite(best.metric?.run_time_s);
  if (beforeTime !== null || afterTime !== null) {
    metrics.push({
      key: 'run_time_s', label: '方案运行时间', unit: '秒', direction: '越低越好',
      initial: beforeTime, best: afterTime,
      maximum: Math.max(1, beforeTime ?? 0, afterTime ?? 0), source: '本地评估 → metric.run_time_s',
    });
  }
  return { metrics, note: `分项指标来自同一 ${split} 划分的本地评估；图中差异不代表统计显著性。` };
}
