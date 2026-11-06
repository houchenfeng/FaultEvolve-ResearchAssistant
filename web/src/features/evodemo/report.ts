/**
 * 结果讲解的数据模型：任何一次运行只要提供进化树节点、可选的跨分支注入与知识主张，
 * 就能推导出讲解页需要的全部内容（最优方案谱系、改进点、指标对比、新知识、复现清单）。
 *
 * 讲解页只读 `RunReport`，不认识具体任务；demo 与真实运行（tree.json + run_summary.json
 * + discovery/*）各自负责把数据整理成 `ReportInput`。
 */

export interface ReportNode {
  id: string;
  parentId?: string;
  depth: number;
  score: number;
  operator: string;
  title: string;
  reflection?: string;
  /** 所属分支 / 岛，用于判断改动是否来自其他分支。 */
  group?: string;
  status: 'ok' | 'failed' | 'pruned';
  metrics?: Record<string, number>;
}

export interface ReportTransfer {
  from: string;
  to: string;
  label: string;
  success: boolean;
}

export interface ReportClaim {
  id: string;
  title: string;
  grade: 'confirmed' | 'discovered' | 'refuted' | 'undetermined';
  n?: number;
  effect?: number;
  ciLow?: number;
  ciHigh?: number;
  fdr?: string;
  boundary?: string;
}

export interface ReportInput {
  runId: string;
  taskName: string;
  metricName: string;
  higherIsBetter?: boolean;
  /** 除主指标外，节点上还要对比的指标，key 对应 `ReportNode.metrics`。 */
  extraMetrics?: { key: string; label: string }[];
  nodes: ReportNode[];
  transfers?: ReportTransfer[];
  claims?: ReportClaim[];
  artifacts?: { label: string; path: string }[];
}

export interface ReportStep {
  node: ReportNode;
  parent: ReportNode;
  delta: number;
  operatorLabel: string;
  /** 这一步吸收了其他分支的知识（注入算子或跨分支迁移的目标）。 */
  borrowedFrom?: string;
}

export interface RunReport {
  input: ReportInput;
  best: ReportNode;
  root: ReportNode;
  lineage: ReportNode[];
  steps: ReportStep[];
  keyImprovements: ReportStep[];
  gain: number;
  gainPct: number;
  metricRows: { label: string; from: number; to: number }[];
  counts: { total: number; failed: number; pruned: number; groups: number };
  confirmed: ReportClaim[];
  otherClaims: ReportClaim[];
}

const OPERATOR_LABELS: Record<string, string> = {
  init: '初始解',
  mutate: '变异',
  refine: '精炼',
  crossover: '交叉',
  inject: '知识注入',
  repair: '修复',
  recall_focus: '召回补强',
  threshold_calibrate: '阈值校准',
};

export function operatorLabel(op: string): string {
  return OPERATOR_LABELS[op.toLowerCase()] ?? op;
}

export function buildRunReport(input: ReportInput): RunReport {
  const sign = input.higherIsBetter === false ? -1 : 1;
  const byId = new Map(input.nodes.map((n) => [n.id, n]));
  const valid = input.nodes.filter((n) => n.status === 'ok');
  if (valid.length === 0) throw new Error('运行中没有有效节点，无法生成讲解');

  const best = valid.reduce((a, b) => (sign * b.score > sign * a.score ? b : a));
  const lineage: ReportNode[] = [];
  for (let n: ReportNode | undefined = best; n; n = n.parentId ? byId.get(n.parentId) : undefined) {
    lineage.unshift(n);
  }
  const root = lineage[0];

  const steps: ReportStep[] = lineage.slice(1).map((node, i) => {
    const parent = lineage[i];
    const transfer = input.transfers?.find((t) => t.to === node.id && t.success);
    const source = transfer ? byId.get(transfer.from) : undefined;
    const injected = node.operator.toLowerCase() === 'inject' || transfer !== undefined;
    return {
      node,
      parent,
      delta: sign * (node.score - parent.score),
      operatorLabel: operatorLabel(node.operator),
      borrowedFrom: injected ? (source?.group ?? transfer?.label ?? '其他分支') : undefined,
    };
  });

  const keyImprovements = steps
    .filter((s) => s.delta > 0)
    .sort((a, b) => b.delta - a.delta)
    .slice(0, 3);

  const gain = sign * (best.score - root.score);
  const metricRows = [
    { label: input.metricName, from: root.score, to: best.score },
    ...(input.extraMetrics ?? [])
      .filter((m) => root.metrics?.[m.key] !== undefined && best.metrics?.[m.key] !== undefined)
      .map((m) => ({ label: m.label, from: root.metrics![m.key], to: best.metrics![m.key] })),
  ];

  const claims = input.claims ?? [];
  return {
    input,
    best,
    root,
    lineage,
    steps,
    keyImprovements,
    gain,
    gainPct: root.score === 0 ? 0 : (gain / Math.abs(root.score)) * 100,
    metricRows,
    counts: {
      total: input.nodes.length,
      failed: input.nodes.filter((n) => n.status === 'failed').length,
      pruned: input.nodes.filter((n) => n.status === 'pruned').length,
      groups: new Set(input.nodes.map((n) => n.group ?? 'main')).size,
    },
    confirmed: claims.filter((c) => c.grade === 'confirmed'),
    otherClaims: claims.filter((c) => c.grade !== 'confirmed'),
  };
}

/** 运行产物 `tree.json` 的最小形状（引擎写出的 nodes + edges）。 */
export interface TreeArtifact {
  experiment_id: string;
  nodes: { id: string; depth: number; operator: string; score: number; status: string; intent?: string; branch_id?: string }[];
  edges: { source: string; target: string }[];
}

export function reportInputFromTree(
  tree: TreeArtifact,
  meta: Pick<ReportInput, 'taskName' | 'metricName' | 'higherIsBetter' | 'claims' | 'artifacts'>,
): ReportInput {
  const parentOf = new Map(tree.edges.map((e) => [e.target, e.source]));
  return {
    ...meta,
    runId: tree.experiment_id,
    nodes: tree.nodes.map((n) => ({
      id: n.id,
      parentId: parentOf.get(n.id),
      depth: n.depth,
      score: n.score,
      operator: n.operator,
      title: n.intent ?? n.operator,
      group: n.branch_id,
      status: n.status === 'done' ? 'ok' : 'failed',
    })),
  };
}

export const CHAPTERS = ['最终方案', '提升了什么', '改进点', '新知识', '可复现性'] as const;

export function narrate(report: RunReport, chapter: number): string {
  const { best, root, steps, keyImprovements, counts, confirmed, otherClaims, input } = report;
  const fmt = (v: number) => v.toFixed(2);
  switch (chapter) {
    case 0: {
      const borrowed = steps.filter((s) => s.borrowedFrom).length;
      return `最终方案 ${best.id}「${best.title}」从「${root.title}」出发，经过 ${steps.length} 代改动叠加而成${borrowed ? `，其中 ${borrowed} 步吸收了其他分支的知识` : ''}。`;
    }
    case 1:
      return `${input.metricName} 从 ${fmt(root.score)} 提升到 ${fmt(best.score)}（${report.gainPct >= 0 ? '+' : ''}${report.gainPct.toFixed(1)}%）。本次共评估 ${counts.total} 个候选，${counts.failed} 个失败回退，${counts.pruned} 个被剪枝。`;
    case 2:
      return keyImprovements.length
        ? `相对基线，贡献最大的 ${keyImprovements.length} 处改进是：${keyImprovements.map((s) => `「${s.node.title}」`).join('、')}。`
        : '最优方案就是初始解，本次进化没有找到更好的改动。';
    case 3:
      return confirmed.length
        ? `进化过程中确认了 ${confirmed.length} 条新知识：${confirmed[0].title}。`
        : `本次运行没有产生确认式知识${otherClaims.length ? `，${otherClaims.length} 条候选主张未通过检验` : ''}。`;
    default:
      return `每个候选的代码、分数、事件和决策都已落盘，按下面的清单可以复现运行 ${input.runId}。`;
  }
}
