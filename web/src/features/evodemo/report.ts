/**
 * 结果讲解的数据模型：任何一次运行只要提供进化树节点、可选的跨分支注入、机制解释与知识主张，
 * 就能推导出讲解页需要的全部内容（最终方案结构、指标对照、改进点、新知识、复现清单）。
 *
 * 讲解页只读 `RunReport`，不认识具体任务；demo 与真实运行（tree.json / nodes.json +
 * 知识卡）各自负责把数据整理成 `ReportInput`。
 *
 * 两种形态由数据自动区分：
 * - chain：最终方案沿单父谱系逐代改进而来，讲“哪几代改动贡献最大”；
 * - combination：最终方案由多个父算法组合而成，讲“相对每个父算法赢在哪、代价是什么、
 *   同一组父算法换其他组合方式为什么不行”。
 */

export interface MetricDef {
  key: string;
  label: string;
  higherIsBetter?: boolean;
  unit?: '%';
  digits?: number;
}

export interface ReportNode {
  id: string;
  /** 单父谱系用 parentId；组合类节点用 parentIds（两者都给时以 parentIds 为准）。 */
  parentId?: string;
  parentIds?: string[];
  depth: number;
  score: number;
  operator: string;
  title: string;
  subtitle?: string;
  reflection?: string;
  /** 所属分支 / 岛 / 批次，用于判断改动是否来自其他分支。 */
  group?: string;
  status: 'ok' | 'failed' | 'pruned';
  /** 一句话判定说明，例如未通过筛选的原因。 */
  note?: string;
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
  grade: 'confirmed' | 'candidate' | 'discovered' | 'refuted' | 'undetermined';
  evidence?: { label: string; value: string; good?: boolean }[];
  boundary?: string;
  /** 事先冻结的反证标准：满足任一条即撤销该主张。 */
  falsifiers?: string[];
}

export interface ReportInsight {
  title: string;
  formula?: string;
  body: string;
}

export interface ReportInput {
  runId: string;
  taskName: string;
  /** 主指标，对应 `ReportNode.score`。 */
  metric: Omit<MetricDef, 'key'>;
  /** 其余对照指标，key 对应 `ReportNode.metrics`。 */
  metrics?: MetricDef[];
  /** 运行最终选定的节点；缺省时取主指标最优的有效节点。 */
  selectedId?: string;
  nodes: ReportNode[];
  transfers?: ReportTransfer[];
  /** 最终算法的决策规则，例如组合公式与告警条件。 */
  formula?: { expression: string; decision?: string };
  /** 为什么有效：机制解释，来自运行沉淀的知识卡。 */
  insights?: ReportInsight[];
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

export interface MetricRow {
  def: MetricDef;
  /** 与 `RunReport.baselines` 一一对应。 */
  baselines: number[];
  best: number;
  /** 相对最强对照的改善量（已按指标方向取正）。 */
  delta: number;
  beatsAll: boolean;
  losesToAny: boolean;
}

export interface RunReport {
  input: ReportInput;
  structure: 'chain' | 'combination';
  best: ReportNode;
  root: ReportNode;
  parents: ReportNode[];
  /** 讲解时拿来对照的节点：组合 = 直接父算法，谱系 = 初始解。 */
  baselines: ReportNode[];
  lineage: ReportNode[];
  steps: ReportStep[];
  keyImprovements: ReportStep[];
  metricRows: MetricRow[];
  wins: MetricRow[];
  tradeoffs: MetricRow[];
  /** 父算法完全相同、组合方式不同的节点：天然的算子消融。 */
  siblings: ReportNode[];
  gain: number;
  gainPct: number;
  counts: { total: number; failed: number; pruned: number; groups: number };
  confirmed: ReportClaim[];
  candidates: ReportClaim[];
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
  paper_baseline: '论文复现',
  fixed_mean: '算术平均',
  agreement_geomean: '几何均值',
  learned_disagreement: '学习式分歧惩罚',
  lambda_zero: 'λ=0 对照',
};

export function operatorLabel(op: string): string {
  return OPERATOR_LABELS[op.toLowerCase()] ?? op;
}

export const SCORE_KEY = '__score';

export function primaryDef(input: ReportInput): MetricDef {
  return { key: SCORE_KEY, ...input.metric };
}

export function metricValue(node: ReportNode, key: string): number | undefined {
  return key === SCORE_KEY ? node.score : node.metrics?.[key];
}

export function formatMetric(def: Omit<MetricDef, 'key'>, value: number): string {
  return `${value.toFixed(def.digits ?? 2)}${def.unit ?? ''}`;
}

export function formatDelta(def: Omit<MetricDef, 'key'>, delta: number): string {
  const sign = delta > 0 ? '+' : delta < 0 ? '−' : '±';
  return `${sign}${Math.abs(delta).toFixed(def.digits ?? 2)}${def.unit === '%' ? 'pp' : ''}`;
}

export function parentsOf(node: ReportNode): string[] {
  if (node.parentIds?.length) return node.parentIds;
  return node.parentId ? [node.parentId] : [];
}

function direction(def: Pick<MetricDef, 'higherIsBetter'>): 1 | -1 {
  return def.higherIsBetter === false ? -1 : 1;
}

export function buildRunReport(input: ReportInput): RunReport {
  const primary = primaryDef(input);
  const sign = direction(primary);
  const byId = new Map(input.nodes.map((n) => [n.id, n]));
  const valid = input.nodes.filter((n) => n.status === 'ok');
  if (valid.length === 0) throw new Error('运行中没有有效节点，无法生成讲解');

  const selected = input.selectedId ? byId.get(input.selectedId) : undefined;
  if (input.selectedId && !selected) throw new Error(`选定节点 ${input.selectedId} 不在运行节点中`);
  const best = selected ?? valid.reduce((a, b) => (sign * b.score > sign * a.score ? b : a));
  const parents = parentsOf(best).map((id) => byId.get(id)).filter((n): n is ReportNode => n !== undefined);
  const structure = parents.length > 1 ? 'combination' : 'chain';

  const lineage: ReportNode[] = [];
  if (structure === 'chain') {
    for (let n: ReportNode | undefined = best; n; n = byId.get(parentsOf(n)[0] ?? '')) lineage.unshift(n);
  } else {
    lineage.push(best);
  }
  const root = structure === 'chain' ? lineage[0] : best;
  const baselines = structure === 'combination' ? parents : [root];

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

  const metricRows: MetricRow[] = [primary, ...(input.metrics ?? [])].flatMap((def) => {
    const b = metricValue(best, def.key);
    const base = baselines.map((n) => metricValue(n, def.key));
    if (b === undefined || base.some((v) => v === undefined)) return [];
    const s = direction(def);
    const values = base as number[];
    const strongest = values.reduce((x, y) => (s * y > s * x ? y : x));
    return [
      {
        def,
        baselines: values,
        best: b,
        delta: s * (b - strongest),
        beatsAll: values.every((v) => s * b > s * v),
        losesToAny: values.some((v) => s * b < s * v),
      },
    ];
  });

  const parentKey = (n: ReportNode) => [...parentsOf(n)].sort().join('|');
  const siblings =
    structure === 'combination'
      ? input.nodes.filter((n) => n.id !== best.id && parentKey(n) === parentKey(best))
      : [];

  const strongestBaseline = baselines.reduce((a, b) => (sign * b.score > sign * a.score ? b : a));
  const gain = sign * (best.score - strongestBaseline.score);
  const claims = input.claims ?? [];
  return {
    input,
    structure,
    best,
    root,
    parents,
    baselines,
    lineage,
    steps,
    keyImprovements,
    metricRows,
    wins: metricRows.filter((r) => r.beatsAll),
    tradeoffs: metricRows.filter((r) => r.losesToAny),
    siblings,
    gain,
    gainPct: strongestBaseline.score === 0 ? 0 : (gain / Math.abs(strongestBaseline.score)) * 100,
    counts: {
      total: input.nodes.length,
      failed: input.nodes.filter((n) => n.status === 'failed').length,
      pruned: input.nodes.filter((n) => n.status === 'pruned').length,
      groups: new Set(input.nodes.map((n) => n.group ?? 'main')).size,
    },
    confirmed: claims.filter((c) => c.grade === 'confirmed'),
    candidates: claims.filter((c) => c.grade === 'candidate'),
    otherClaims: claims.filter((c) => c.grade !== 'confirmed' && c.grade !== 'candidate'),
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
  meta: Pick<ReportInput, 'taskName' | 'metric' | 'claims' | 'artifacts'>,
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

/** 有机制解释时，第 3 章讲的是算法的本质创新，而不是逐代改动。 */
export function chapterTitles(report: RunReport): string[] {
  return CHAPTERS.map((title, i) => (i === 2 && report.input.insights?.length ? '本质创新' : title));
}

export function narrate(report: RunReport, chapter: number): string {
  const { best, root, parents, steps, keyImprovements, counts, confirmed, candidates, otherClaims, input } = report;
  const primary = primaryDef(input);
  const names = (nodes: ReportNode[]) => nodes.map((n) => `「${n.title}」`).join('和');
  const combination = report.structure === 'combination';
  switch (chapter) {
    case 0: {
      if (combination) {
        return `最终方案「${best.title}」把${names(parents)}用「${operatorLabel(best.operator)}」组合起来${input.formula ? `：${input.formula.expression}` : ''}。`;
      }
      const borrowed = steps.filter((s) => s.borrowedFrom).length;
      return `最终方案 ${best.id}「${best.title}」从「${root.title}」出发，经过 ${steps.length} 代改动叠加而成${borrowed ? `，其中 ${borrowed} 步吸收了其他分支的知识` : ''}。`;
    }
    case 1: {
      const tally = `本次共评估 ${counts.total} 个候选${counts.failed ? `，${counts.failed} 个失败回退` : ''}${counts.pruned ? `，${counts.pruned} 个未通过筛选` : ''}。`;
      if (combination) {
        const wins = report.wins.map((r) => r.def.label).join('、');
        return `相对两个父算法，${wins || '没有指标'}同时更优${report.tradeoffs.length ? `；代价在${report.tradeoffs.map((r) => r.def.label).join('、')}` : ''}。${tally}`;
      }
      return `${primary.label} 从 ${formatMetric(primary, root.score)} 提升到 ${formatMetric(primary, best.score)}（${report.gainPct >= 0 ? '+' : ''}${report.gainPct.toFixed(1)}%）。${tally}`;
    }
    case 2: {
      const failedSiblings = report.siblings.filter((s) => s.status !== 'ok');
      const ablation = failedSiblings.length
        ? `同一对父算法换成${[...new Set(failedSiblings.map((s) => operatorLabel(s.operator)))].join('、')}都没有通过。`
        : '';
      if (input.insights?.length) {
        return `本质创新分 ${input.insights.length} 层：${input.insights.map((s) => `「${s.title}」`).join('，')}。${ablation}`;
      }
      if (combination) return `关键在「${operatorLabel(best.operator)}」这一组合方式。${ablation}`;
      return keyImprovements.length
        ? `相对基线，贡献最大的 ${keyImprovements.length} 处改进是：${keyImprovements.map((s) => `「${s.node.title}」`).join('、')}。`
        : '最优方案就是初始解，本次进化没有找到更好的改动。';
    }
    case 3:
      if (confirmed.length) return `进化过程中确认了 ${confirmed.length} 条新知识：${confirmed[0].title}。`;
      if (candidates.length) return `沉淀出 ${candidates.length} 条候选知识：${candidates[0].title}。它已通过开发筛选，等待未见数据独立确认。`;
      return `本次运行没有产生新知识${otherClaims.length ? `，${otherClaims.length} 条主张未通过检验` : ''}。`;
    default:
      return `每个候选的代码、指标、事件和判定都已落盘，按下面的清单可以复现运行 ${input.runId}。`;
  }
}
