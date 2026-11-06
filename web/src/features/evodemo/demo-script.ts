/**
 * KGTE 三岛进化案例的回放脚本：把 HDD 展示运行的三岛进化树展开成确定性的步骤序列。
 *
 * 每一轮（树深度）分三段：云端提出候选 → SSH 下发到本地沙箱评估 → 逐个回传分数。
 * 真实模式下同一组步骤由 SSE 事件流驱动（node_created → 评估 → iteration_complete），
 * 页面只消费 `DemoStep`，不关心来源。
 */
import type { IslandKey, ShowcaseNode } from '@/features/showcase/hdd-showcase-data';
import { SHOWCASE_ISLANDS, TRANSFERS } from '@/features/showcase/hdd-showcase-data';

import type { DemoEvent, DemoStep, Transfer } from './cases/types';
import type { ReportInput } from './report';

export type NodeOutcome = 'improved' | 'failed' | 'pruned' | 'best' | 'baseline';

export interface DemoNode extends ShowcaseNode {
  outcome: NodeOutcome;
}

export const ISLAND_ORDER: IslandKey[] = ['temporal', 'ensemble', 'operations'];

export const ISLAND_META: Record<IslandKey, { name: string; focus: string }> = Object.fromEntries(
  SHOWCASE_ISLANDS.map((island) => [island.key, { name: island.name, focus: island.focus }]),
) as Record<IslandKey, { name: string; focus: string }>;

const GLOBAL_BEST_ID = 'T6';

export const DEMO_NODES: DemoNode[] = SHOWCASE_ISLANDS.flatMap((island) =>
  island.nodes.map((node) => ({
    ...node,
    outcome:
      node.depth === 0
        ? 'baseline'
        : node.id === GLOBAL_BEST_ID
          ? 'best'
          : node.state === 'failed'
            ? 'failed'
            : node.state === 'pruned'
              ? 'pruned'
              : 'improved',
  })),
);

export const NODE_BY_ID = new Map(DEMO_NODES.map((node) => [node.id, node]));

export const DEMO_TRANSFERS: Transfer[] = TRANSFERS.map((t) => ({
  from: t.from,
  to: t.to,
  label: t.label,
  success: t.outcome === '成功',
  gain: t.gain,
}));

export const MAX_DEPTH = Math.max(...DEMO_NODES.map((node) => node.depth));
export const BASELINE_SCORE = Math.max(...DEMO_NODES.filter((n) => n.depth === 0).map((n) => n.score));
export const FINAL_SCORE = Math.max(...DEMO_NODES.map((n) => n.score));

export function buildDemoSteps(): DemoStep[] {
  const steps: DemoStep[] = [];
  let best = Number.NEGATIVE_INFINITY;
  for (let depth = 0; depth <= MAX_DEPTH; depth += 1) {
    const round = DEMO_NODES.filter((node) => node.depth === depth).sort(
      (a, b) => ISLAND_ORDER.indexOf(a.island) - ISLAND_ORDER.indexOf(b.island) || a.y - b.y,
    );
    if (round.length === 0) continue;
    const ids = round.map((node) => node.id);
    steps.push({
      kind: 'propose',
      round: depth,
      nodeIds: ids,
      injects: DEMO_TRANSFERS.filter((t) => ids.includes(t.to)),
    });
    steps.push({ kind: 'evaluate', round: depth, nodeIds: ids });
    for (const node of round) {
      const isNewBest = node.score > best;
      best = Math.max(best, node.score);
      steps.push({ kind: 'result', round: depth, nodeId: node.id, bestScore: best, isNewBest });
    }
  }
  steps.push({ kind: 'finish', bestScore: best });
  return steps;
}

export function describeStep(step: DemoStep, index: number): DemoEvent | null {
  const id = `e${index}`;
  switch (step.kind) {
    case 'propose':
      return {
        id,
        tag: `R${step.round}`,
        text:
          step.round === 0
            ? `云端初始化三岛基线：${step.nodeIds.join('、')}`
            : `云端 Qwen 生成 ${step.nodeIds.length} 个新候选${step.injects.length ? `，含 ${step.injects.length} 次跨岛注入` : ''}`,
        tone: step.injects.length ? 'inject' : 'cloud',
      };
    case 'evaluate':
      return { id, tag: `R${step.round}`, text: `SSH 下发 ${step.nodeIds.length} 份候选代码 → 本地沙箱评估`, tone: 'info' };
    case 'result': {
      const node = NODE_BY_ID.get(step.nodeId);
      if (!node) return null;
      const delta = node.delta === 0 ? '' : ` (${node.delta > 0 ? '+' : ''}${node.delta.toFixed(2)})`;
      const verb =
        node.outcome === 'failed'
          ? '失败回退'
          : node.outcome === 'pruned'
            ? '落入噪声带，剪枝'
            : node.outcome === 'best'
              ? '刷新全局最优'
              : node.outcome === 'baseline'
                ? '基线完成'
                : '评估完成';
      return {
        id,
        tag: node.id,
        text: `${node.title} ${verb} · ROS ${node.score.toFixed(2)}${delta}`,
        tone: node.outcome === 'failed' || node.outcome === 'pruned' ? 'bad' : node.outcome === 'baseline' ? 'info' : 'good',
      };
    }
    case 'finish':
      return { id, tag: 'DONE', text: `进化结束 · 最优 ROS ${step.bestScore.toFixed(2)}`, tone: 'good' };
  }
}

/** 讲解页输入：节点来自演示进化树，主张来自展示运行的 discovery/phenomena.json。 */
export const DEMO_REPORT_INPUT: ReportInput = {
  runId: 'hdd_mvp_showcase_c89e2a01',
  taskName: 'HDD 短期故障预测',
  metric: { label: 'ROS' },
  metrics: [
    { key: 'q', label: 'Q 稳定性' },
    { key: 'jev', label: 'Jev 评审' },
  ],
  nodes: DEMO_NODES.map((n) => ({
    id: n.id,
    parentId: n.parentId,
    depth: n.depth,
    score: n.score,
    operator: n.operator,
    title: n.title,
    reflection: n.reflection,
    group: ISLAND_META[n.island].name,
    status: n.outcome === 'failed' ? 'failed' : n.outcome === 'pruned' ? 'pruned' : 'ok',
    metrics: { q: n.q, jev: n.jev },
  })),
  transfers: DEMO_TRANSFERS,
  claims: [
    {
      id: 'C-89f4bdd1-0010',
      title: '窗口末端 smart_194_normalized 与短期 HDD 故障信号正相关',
      grade: 'confirmed',
      evidence: [
        { label: '确认集样本', value: 'n = 9,262' },
        { label: '效应估计', value: '0.3124' },
        { label: '95% CI', value: '[0.278, 0.346]' },
        { label: '多重校正', value: 'BH 通过', good: true },
      ],
      boundary: '机制对局未分胜负，结论表述为可复现的关联指示，不写成因果定律。',
    },
    { id: 'C-showcase-0002', title: '未命名主张', grade: 'refuted' },
  ],
  artifacts: [
    { label: '进化树', path: 'tree.json' },
    { label: '事件流', path: 'events.jsonl' },
    { label: '运行摘要', path: 'run_summary.json' },
    { label: '候选程序', path: 'programs/*.py' },
    { label: '知识发现证据', path: 'discovery/certificates.json · preregistration.json' },
    { label: '最终算法说明', path: 'reports/final_algorithm_README.md' },
  ],
};
