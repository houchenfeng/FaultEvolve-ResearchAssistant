/**
 * Demo 回放脚本：把 HDD 展示运行的三岛进化树展开成确定性的步骤序列。
 *
 * 每一轮（树深度）分三段：云端提出候选 → SSH 下发到本地沙箱评估 → 逐个回传分数。
 * 真实模式下同一组步骤由 SSE 事件流驱动（node_created → 评估 → iteration_complete），
 * 页面只消费 `DemoStep`，不关心来源。
 */
import type { IslandKey, ShowcaseNode } from '@/features/showcase/hdd-showcase-data';
import { SHOWCASE_ISLANDS, TRANSFERS } from '@/features/showcase/hdd-showcase-data';

import type { ReportInput } from './report';

export type NodeOutcome = 'improved' | 'failed' | 'pruned' | 'best' | 'baseline';

export interface DemoNode extends ShowcaseNode {
  outcome: NodeOutcome;
}

export type DemoStep =
  | { kind: 'propose'; round: number; nodeIds: string[]; injects: Transfer[] }
  | { kind: 'evaluate'; round: number; nodeIds: string[] }
  | { kind: 'result'; round: number; nodeId: string; bestScore: number; isNewBest: boolean }
  | { kind: 'finish'; bestScore: number };

export interface Transfer {
  from: string;
  to: string;
  label: string;
  success: boolean;
  gain: string;
}

export interface DemoEvent {
  id: string;
  tag: string;
  text: string;
  tone: 'info' | 'good' | 'bad' | 'cloud' | 'inject';
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

/** 机制辩论赛脚本，台词取自 HDD 展示运行的确认式知识主张。 */
export const DEBATE_ROUNDS = [
  { round: '开场陈述', speaker: 'proponent', line: '窗口末端 SMART 194 越高，短期故障风险越高。我主张它是可复现的正向信号。' },
  { round: '第一轮质询', speaker: 'confounder', line: '会不会是盘龄、型号批次或负载在背后同时推高了两者？' },
  { round: '数据举证', speaker: 'statistician', line: '确认集 n = 9,262，效应估计 0.3124，95% CI [0.278, 0.346]，BH 校正后通过。' },
  { round: '第二轮反驳', speaker: 'proponent', line: '方向与时间切片一致：direction_ok、temporal_ok 均为 true。' },
  { round: '机制追问', speaker: 'critic', line: '16 场机制对局全部平局，统计显著不等于因果机制。' },
  { round: '最终裁决', speaker: 'judge', line: '升级为 CONFIRMED 确认式知识；机制尚未建立，不写成因果定律。' },
] as const;

export type DebateRole = (typeof DEBATE_ROUNDS)[number]['speaker'];

export const DEBATE_CAST: Record<DebateRole, { name: string; en: string; shape: 'circle' | 'hex' | 'squircle' | 'triangle'; color: string }> = {
  proponent: { name: '支持方', en: 'Proponent', shape: 'circle', color: '#2563EB' },
  confounder: { name: '混杂方', en: 'Confounder', shape: 'hex', color: '#64748B' },
  statistician: { name: '统计裁判', en: 'Statistician', shape: 'squircle', color: '#0EA5E9' },
  critic: { name: '批评方', en: 'Critic', shape: 'triangle', color: '#6366F1' },
  judge: { name: '总裁判', en: 'Judge', shape: 'circle', color: '#1E3A8A' },
};

export const EVIDENCE_CHAIN = ['现象抽取', '预注册', '确认检验', '多重控制', '机制辩论', '跨切片外推'];

/** 讲解页输入：节点来自演示进化树，主张来自展示运行的 discovery/phenomena.json。 */
export const DEMO_REPORT_INPUT: ReportInput = {
  runId: 'hdd_mvp_showcase_c89e2a01',
  taskName: 'HDD 短期故障预测',
  metricName: 'ROS',
  extraMetrics: [
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
      n: 9262,
      effect: 0.3124,
      ciLow: 0.2781,
      ciHigh: 0.3459,
      fdr: 'BH 通过',
      boundary: '机制对局未分胜负，结论表述为可复现的关联指示，不写成因果定律。',
    },
    { id: 'C-showcase-0002', title: '未命名主张', grade: 'refuted', n: 9262, effect: 0.02, ciLow: -0.01, ciHigh: 0.05 },
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
