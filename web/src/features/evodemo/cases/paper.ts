/**
 * 案例一：以最新 SOTA 论文为初始解，自进化自动组合出新算法（Mitra-v2 × TabM 几何均值）。
 *
 * 节点与晋升判定来自真实实验的 nodes.json（三批：batch01r1 / batch02 / batch03，经
 * 裁剪后存为 paper-combination.nodes.json）；机制解释与知识表述来自
 * experiments/paper_combinations_b02_20261106/DISCOVERY_CASE.md。
 */
import type { BotShape } from '../bot/shapes';
import { buildRunReport, operatorLabel } from '../report';
import type { ReportInput, ReportNode } from '../report';
import raw from './paper-combination.nodes.json';
import type { DemoCase, DemoEvent, DemoStep } from './types';

type Quarter = 'recent_2026q1' | 'replication_2026q2';
type CheckKey = 'precision_beats_both' | 'far_no_worse_than_both' | 'far_within_target' | 'recall_guard' | 'minimum_alarms';

interface QuarterMetrics {
  precision: number;
  far: number;
  recall: number;
  true_positive_count: number;
  false_positive_count: number;
  alarm_count: number;
  far_upper95?: number;
  far_upper_family95?: number;
}

/** nodes.json 中单个节点的形状（只保留讲解需要的字段）。 */
export interface CombinationArtifactNode {
  id: string;
  batch: string;
  depth: number;
  operator: string;
  parents: string[];
  metrics: Partial<Record<Quarter, QuarterMetrics>>;
  decision?: { candidate: boolean; domains: Partial<Record<Quarter, { checks: Record<CheckKey, boolean> }>> };
}

export const QUARTERS: { key: Quarter; label: string }[] = [
  { key: 'recent_2026q1', label: 'Q1' },
  { key: 'replication_2026q2', label: 'Q2' },
];

export const CHECKS: { key: CheckKey; label: string }[] = [
  { key: 'precision_beats_both', label: '精确率高于双父' },
  { key: 'far_no_worse_than_both', label: '误告不高于双父' },
  { key: 'far_within_target', label: '误告 ≤ 0.2%' },
  { key: 'recall_guard', label: '召回保护' },
  { key: 'minimum_alarms', label: '告警 ≥ 10 次' },
];

export interface PaperMeta {
  id: string;
  name: string;
  venue: string;
  idea: string;
  shape: BotShape;
  ready: boolean;
}

export const PAPERS: PaperMeta[] = [
  { id: 'tabm', name: 'TabM', venue: 'ICLR 2025', idea: '任务内训练 · 参数高效集成', shape: 'squircle', ready: true },
  { id: 'tabiclv2', name: 'TabICLv2', venue: 'ICML 2026', idea: '表格基础模型 · 上下文推理', shape: 'hex', ready: true },
  { id: 'modernnca', name: 'ModernNCA', venue: 'ICLR 2025', idea: '学习距离空间 · 近邻聚合', shape: 'diamond', ready: true },
  { id: 'mitra', name: 'Mitra-v2', venue: '2026-09 技术报告', idea: '合成先验预训练 · 上下文推理', shape: 'circle', ready: true },
  { id: 'tabpfn35', name: 'TabPFN-3.5', venue: '2026-09 技术报告', idea: '权重需非商业许可 · 未运行', shape: 'triangle', ready: false },
];

const PAPER_BY_ID = new Map(PAPERS.map((p) => [p.id, p]));

export const WINNER_ID = 'mix-29b3832fa231e045ba5a';

const SHORT: Record<string, string> = { tabm: 'TabM', tabiclv2: 'TabICLv2', modernnca: 'ModernNCA', mitra: 'Mitra', [WINNER_ID]: '√(Mitra·TabM)' };

const OP_GLYPH: Record<string, string> = { fixed_mean: '(p+q)/2', agreement_geomean: '√pq', learned_disagreement: 'σ(αz−λ|Δz|)' };

const OP_SHAPE: Record<string, BotShape> = { fixed_mean: 'squircle', agreement_geomean: 'circle', learned_disagreement: 'hex' };

export type PaperOutcome = 'paper' | 'silent' | 'promoted' | 'rejected';

export interface PaperNode {
  id: string;
  label: string;
  glyph?: string;
  shape: BotShape;
  column: number;
  row: number;
  parents: string[];
  operator: string;
  outcome: PaperOutcome;
  metrics: Partial<Record<Quarter, QuarterMetrics>>;
  checks?: Partial<Record<Quarter, Record<CheckKey, boolean>>>;
  reason?: string;
}

export const COLUMNS = [
  { title: '论文父算法', sub: '最新 SOTA 作为初始解' },
  { title: '第 1 批组合', sub: '3 个父代 × 2 种算子' },
  { title: '第 2 批组合', sub: '新论文 Mitra-v2 加入' },
  { title: '第 3 批组合', sub: '学习式融合 · 胜者再组合' },
];

const COLUMN_OF_BATCH: Record<string, number> = { batch01: 1, batch02: 2, batch03: 3 };

const artifact = (raw as { nodes: CombinationArtifactNode[] }).nodes.filter((n) => n.operator !== 'lambda_zero');
const ARTIFACT_BY_ID = new Map(artifact.map((n) => [n.id, n]));

function pct(v: number, digits = 2) {
  return `${(v * 100).toFixed(digits)}%`;
}

/**
 * 由冻结检查推出第一条未通过的原因，并指出是被哪个父算法比下去。
 * 无告警的父算法（精确率分母为零）放到最后比较，避免用“高于 0% 误告”这种没有信息量的理由。
 */
function failReason(node: CombinationArtifactNode): string | undefined {
  const domains = node.decision?.domains;
  if (!domains || node.decision?.candidate) return undefined;
  for (const q of QUARTERS) {
    const checks = domains[q.key]?.checks;
    const m = node.metrics[q.key];
    if (!checks || !m) continue;
    const parentMetrics = node.parents
      .map((id) => ({ id, m: ARTIFACT_BY_ID.get(id)?.metrics[q.key] }))
      .sort((a, b) => Number((a.m?.alarm_count ?? 0) === 0) - Number((b.m?.alarm_count ?? 0) === 0));
    if (!checks.far_no_worse_than_both) {
      const worse = parentMetrics.find((p) => p.m && m.far > p.m.far);
      if (worse?.m) return `${q.label} 误告 ${pct(m.far, 4)} 高于 ${SHORT[worse.id] ?? worse.id} 的 ${pct(worse.m.far, 4)}`;
    }
    if (!checks.precision_beats_both) {
      const better = parentMetrics.find((p) => p.m && m.precision <= p.m.precision);
      if (better?.m) return `${q.label} 精确率 ${pct(m.precision)} 不高于 ${SHORT[better.id] ?? better.id} 的 ${pct(better.m.precision)}`;
    }
    const failed = CHECKS.find((c) => !checks[c.key]);
    if (failed) return `${q.label} 未通过「${failed.label}」`;
  }
  return undefined;
}

function comboLabel(node: CombinationArtifactNode) {
  return node.parents.map((p) => SHORT[p] ?? p).join(' × ');
}

const PAPER_ROWS = PAPERS.map((p) => p.id);

export const PAPER_NODES: PaperNode[] = [
  ...PAPERS.map((p, row) => {
    const a = ARTIFACT_BY_ID.get(p.id);
    const silent = a !== undefined && QUARTERS.every((q) => (a.metrics[q.key]?.alarm_count ?? 0) === 0);
    return {
      id: p.id,
      label: p.name,
      shape: p.shape,
      column: 0,
      row,
      parents: [],
      operator: 'paper_baseline',
      outcome: (silent ? 'silent' : 'paper') as PaperOutcome,
      metrics: a?.metrics ?? {},
    };
  }),
  ...(['batch01', 'batch02', 'batch03'] as const).flatMap((batch) =>
    artifact
      .filter((n) => n.batch === batch && n.operator !== 'paper_baseline')
      .sort((a, b) => [...a.parents].sort().join().localeCompare([...b.parents].sort().join()) || a.operator.localeCompare(b.operator))
      .map((n, row) => ({
        id: n.id,
        label: comboLabel(n),
        glyph: OP_GLYPH[n.operator],
        shape: OP_SHAPE[n.operator] ?? 'circle',
        column: COLUMN_OF_BATCH[batch],
        row,
        parents: n.parents,
        operator: n.operator,
        outcome: (n.decision?.candidate ? 'promoted' : 'rejected') as PaperOutcome,
        metrics: n.metrics,
        checks: Object.fromEntries(QUARTERS.map((q) => [q.key, n.decision?.domains[q.key]?.checks])) as PaperNode['checks'],
        reason: failReason(n),
      })),
  ),
];

export const PAPER_NODE_BY_ID = new Map(PAPER_NODES.map((n) => [n.id, n]));

export function rowsInColumn(column: number) {
  return column === 0 ? PAPER_ROWS.length : PAPER_NODES.filter((n) => n.column === column).length;
}

/* ---------- 回放步骤 ---------- */

const ROUNDS: { batch: string; ids: string[]; text: string }[] = [
  { batch: 'batch01', ids: ['tabm', 'tabiclv2', 'modernnca'], text: '复现 3 篇论文为父算法（TabPFN-3.5 许可受限，跳过）' },
  { batch: 'batch01', ids: PAPER_NODES.filter((n) => n.column === 1).map((n) => n.id), text: '两两组合 · 算术平均 / 几何均值' },
  { batch: 'batch02', ids: ['mitra'], text: '新论文 Mitra-v2（2026-09）加入父代池' },
  { batch: 'batch02', ids: PAPER_NODES.filter((n) => n.column === 2).map((n) => n.id), text: 'Mitra-v2 与 3 个旧父代各组合两次' },
  { batch: 'batch03', ids: PAPER_NODES.filter((n) => n.column === 3).map((n) => n.id), text: '学习式分歧惩罚 · 胜出组合继续作为父代' },
];

export const BATCH_OF_ROUND = ROUNDS.map((r) => r.batch);

function buildSteps(): DemoStep[] {
  const steps: DemoStep[] = [];
  let promoted = 0;
  ROUNDS.forEach((r, round) => {
    steps.push({ kind: 'propose', round, nodeIds: r.ids, injects: [] });
    steps.push({ kind: 'evaluate', round, nodeIds: r.ids });
    for (const id of r.ids) {
      const isNewBest = PAPER_NODE_BY_ID.get(id)?.outcome === 'promoted';
      if (isNewBest) promoted += 1;
      steps.push({ kind: 'result', round, nodeId: id, bestScore: promoted, isNewBest });
    }
  });
  steps.push({ kind: 'finish', bestScore: promoted });
  return steps;
}

function describe(step: DemoStep, index: number): DemoEvent | null {
  const id = `e${index}`;
  switch (step.kind) {
    case 'propose':
      return { id, tag: `R${step.round}`, text: ROUNDS[step.round].text, tone: step.round === 2 ? 'inject' : 'cloud' };
    case 'evaluate':
      return { id, tag: `R${step.round}`, text: `SSH 下发 ${step.nodeIds.length} 个节点 → 服务器按冻结协议运行`, tone: 'info' };
    case 'result': {
      const node = PAPER_NODE_BY_ID.get(step.nodeId);
      if (!node) return null;
      const q1 = node.metrics.recent_2026q1;
      const q2 = node.metrics.replication_2026q2;
      const summary = q1 && q2 ? `精确率 ${pct(q1.precision, 1)} / ${pct(q2.precision, 1)}` : '';
      if (node.outcome === 'paper') return { id, tag: node.label, text: `父算法复现完成 · ${summary}`, tone: 'info' };
      if (node.outcome === 'silent') return { id, tag: node.label, text: '复现完成，但两个季度均无告警', tone: 'bad' };
      if (node.outcome === 'promoted') return { id, tag: '晋升', text: `${node.label} ${node.glyph} · 两域 10 项检查全过 · ${summary}`, tone: 'good' };
      return { id, tag: node.glyph ?? '×', text: `${node.label} 未晋升：${node.reason ?? ''}`, tone: 'bad' };
    }
    case 'finish':
      return { id, tag: 'DONE', text: `三批 ${PAPER_NODES.filter((n) => n.column > 0).length} 个组合，${step.bestScore} 个晋升为新算法候选`, tone: 'good' };
  }
}

/* ---------- 讲解报告 ---------- */

function toReportNode(n: PaperNode): ReportNode {
  const q1 = n.metrics.recent_2026q1;
  const q2 = n.metrics.replication_2026q2;
  const paper = PAPER_BY_ID.get(n.id);
  return {
    id: n.id,
    parentIds: n.parents,
    depth: n.column === 0 ? 0 : (ARTIFACT_BY_ID.get(n.id)?.depth ?? 1),
    score: (q1?.precision ?? 0) * 100,
    operator: n.operator,
    title: n.column === 0 ? n.label : `${n.label} · ${operatorLabel(n.operator)}`,
    subtitle: paper ? `${paper.venue} · ${paper.idea}` : n.glyph,
    group: n.column === 0 ? '论文父算法' : COLUMNS[n.column].title,
    status: n.outcome === 'rejected' ? 'pruned' : 'ok',
    note: n.reason,
    metrics: {
      q1_far: (q1?.far ?? 0) * 100,
      q1_recall: (q1?.recall ?? 0) * 100,
      q2_precision: (q2?.precision ?? 0) * 100,
      q2_far: (q2?.far ?? 0) * 100,
      q2_recall: (q2?.recall ?? 0) * 100,
    },
  };
}

export const PAPER_REPORT_INPUT: ReportInput = {
  runId: 'paper_combinations_b02_20261106',
  taskName: 'HDD 7 天故障预警 · 论文组合',
  metric: { label: 'Q1 精确率', unit: '%', digits: 2 },
  metrics: [
    { key: 'q1_far', label: 'Q1 误告率', unit: '%', digits: 4, higherIsBetter: false },
    { key: 'q1_recall', label: 'Q1 召回率', unit: '%', digits: 2 },
    { key: 'q2_precision', label: 'Q2 精确率', unit: '%', digits: 2 },
    { key: 'q2_far', label: 'Q2 误告率', unit: '%', digits: 4, higherIsBetter: false },
    { key: 'q2_recall', label: 'Q2 召回率', unit: '%', digits: 2 },
  ],
  selectedId: WINNER_ID,
  nodes: PAPER_NODES.filter((n) => PAPER_BY_ID.get(n.id)?.ready !== false).map(toReportNode),
  formula: { expression: 'g(x) = √( p_TabM(x) · q_Mitra(x) )', decision: 'g(x) ≥ t = 0.6366 时告警 · t 取三期负例校准阈值的最大值' },
  insights: [
    {
      title: '平均风险减去分歧项',
      formula: '√(pq) = (p+q)/2 − (√p−√q)²/2',
      body: '第一项是两个模型的平均风险，第二项是非负的分歧惩罚：判断相同时惩罚为零，平均风险相同时分歧越大分数越低。它既关心“平均觉得有多危险”，也关心“这个危险判断得到了多少相互支持”。',
    },
    {
      title: '共识风险 × 一致性折扣',
      formula: 'g = B·r = r·exp[−min J(z)]',
      body: 'r 在对数几率空间平等汇总两个判断，是同时最靠近两个父分布的最优共识；B 是两个预测分布的 Bhattacharyya 亲和系数，−log B 是两者无法完全一致的最小代价。组合先形成共识，再按分歧代价对共识做指数折扣。',
    },
    {
      title: '为什么能提高精确率',
      formula: 'P/(1−P) = π/(1−π) × TPR/FPR',
      body: '稀有事件里提高精确率的核心是提高 TPR/FPR。相对 TabM，Q1 检出 138→88（−36%）、误告 12→4（−67%）；Q2 检出 231→163（−29%）、误告 6→3（−50%）。误告下降比例超过检出下降比例，告警中的真实故障比例就上升。',
    },
  ],
  claims: [
    {
      id: 'algorithm-mix-29b3832fa231e045ba5a',
      title: '当任务内学习模型与预训练上下文模型的分歧能标记一部分不可靠高分时，可以把预测一致性作为告警筛选信号，改善稀有事件的告警精确率',
      grade: 'candidate',
      evidence: [
        { label: '父算法', value: 'TabM（任务内训练）× Mitra-v2（预训练上下文）' },
        { label: '组合规则', value: '几何均值 · 无新增融合参数' },
        { label: 'Q1 / Q2 精确率', value: '42.82% / 64.71%', good: true },
        { label: 'Q1 / Q2 误告率', value: '0.0402% / 0.0301%', good: true },
        { label: '两域晋升检查', value: '10 / 10 通过', good: true },
        { label: '取舍', value: '召回位于两个父算法之间' },
      ],
      boundary: '证据来自两个开发季度，等待未见季度独立确认；保存公式、谱系、固定阈值和父子对照，作为可继续组合的知识节点。',
    },
    { id: 'batch03-learned-penalty', title: '让融合自己学习分歧惩罚可以进一步改进（λ 学成 0，未产生增量）', grade: 'refuted' },
  ],
  artifacts: [
    { label: '发现案例与数理解释', path: 'paper_combinations_b02_20261106/DISCOVERY_CASE.md' },
    { label: '候选知识卡', path: 'paper_combinations_b02_20261106/knowledge_candidate.md' },
    { label: '节点与晋升判定', path: 'evidence/batch02/nodes.json' },
    { label: '完整父子指标', path: 'evidence/batch02/records.json' },
    { label: '冻结清单', path: 'evidence/batch02/manifest.json' },
    { label: '第 3 批学习式融合', path: 'paper_combinations_b03_20261106/RESULTS.md' },
    { label: '发现与解释提示词', path: 'paper_combinations_20261106/DISCOVERY_PROMPTS.md' },
  ],
};

export const PAPER_CASE: DemoCase = {
  id: 'paper',
  name: '论文组合 · 自动发现新算法',
  badge: '真实实验回放 · 论文组合三批',
  seed: '最新 SOTA 论文作为初始解',
  sampleTask: '以近两年有官方实现的表格 SOTA 论文为初始解，在 HDD 7 天故障预警上自动组合出精确率更高、误告更少的新算法。',
  evaluation: '精确率 / 误告率 / 召回 · 双域晋升',
  confirm: {
    checks: [
      { icon: 'server', title: 'GPU 服务器', value: 'hcf@gpu · /home/hcf/faultevolve', ok: 'SSH 已连接 · 运行锁与 6 小时时限就绪' },
      { icon: 'doc', title: '论文检索与可用性核验', value: '5 篇候选 · 官方实现 / 权重 / 许可证', ok: '4 篇可运行 · 1 篇许可受限' },
      { icon: 'flask', title: '冻结晋升协议', value: 'protocol.json · 两个季度 × 5 项检查', ok: '阈值只用校准负例确定' },
    ],
    seedNote: '检索近两年有官方实现的表格 SOTA 论文，复现为父算法，再自动两两组合；论文自己的榜单成绩不计入本项目测量。',
    budget: { label: '组合预算', min: 2, max: 6, initial: 6, describe: (n) => `每批 ≤ ${n} 个组合 · 深度 ≤ 2` },
    privacy: '逐盘预测、盘号与标签只留在服务器，本地只取回聚合指标做晋升判定。',
    preview: {
      title: '候选论文',
      rows: PAPERS.map((p) => ({ label: `${p.name} · ${p.venue}`, sub: p.idea, ok: p.ready })),
    },
  },
  steps: buildSteps(),
  transfers: [],
  describeStep: describe,
  pipeline: {
    cloud: { title: 'GPU 服务器 · SSH', host: 'hcf@gpu', command: (round) => `bash launch.sh · ${BATCH_OF_ROUND[round] ?? 'batch03'}` },
    local: { title: '本地 · 冻结协议与晋升判定', file: 'protocol.json', note: '逐盘预测、盘号、标签只留在服务器' },
    boundary: '数据边界 · 仅聚合指标可通过',
    lanes: { cloud: '服务器运行', local: '待下发节点' },
    stages: ['本地冻结协议', 'SSH 下发节点', '服务器运行', '回传聚合指标', '本地晋升判定'],
    origin: 'local',
    candidateLabel: (id) => {
      const n = PAPER_NODE_BY_ID.get(id);
      return n ? `${n.label}${n.glyph ? ` ${n.glyph}` : ''}` : id;
    },
    result: (id) => {
      const n = PAPER_NODE_BY_ID.get(id);
      if (!n) return { label: id, ok: true };
      if (n.column === 0) return { label: `${n.label} 已复现`, ok: n.outcome === 'paper' };
      return { label: `${n.label} ${n.outcome === 'promoted' ? '晋升 ✓' : '未过'}`, ok: n.outcome === 'promoted' };
    },
  },
  debate: {
    eyebrow: '新知识发现 · 算法辩论赛',
    title: 'Mitra-v2 × TabM 几何均值：共识风险 × 一致性折扣',
    highlight: '共识风险 × 一致性折扣',
    rounds: [
      {
        round: '发现陈述',
        speaker: 'proponent',
        line: 'TabM 从硬盘数据里学，Mitra-v2 带着预训练先验看上下文。两种学习方式对同一块盘给出不同风险，几何均值把这种分歧变成了告警筛选信号。',
      },
      { round: '质询', speaker: 'critic', line: '几何均值是已知运算。凭什么说它是新知识，而不只是换了个平均？' },
      {
        round: '第一层本质',
        speaker: 'statistician',
        line: '√pq = (p+q)/2 − (√p−√q)²/2。平均风险减去非负的分歧惩罚：0.95 和 0.25 的孤立高分，会排到两个都给 0.58 的一致判断之后。',
      },
      {
        round: '第二层本质',
        speaker: 'statistician',
        line: '再分解成 g = B·r：r 是对数几率空间里同时最靠近两个父分布的最优共识，B 是一致性系数，−log B 是无法一致的最小代价。组合 = 共识风险 × 一致性折扣。',
      },
      {
        round: '为什么有效',
        speaker: 'proponent',
        line: '精确率几率 = 先验几率 × TPR/FPR。相对 TabM，Q1 检出降 36%、误告降 67%，误告降得更多，所以 Q1/Q2 精确率 42.8% / 64.7%，同时超过两个父算法。',
      },
      {
        round: '对照与代价',
        speaker: 'confounder',
        line: '同一对父算法用算术平均，Q1 误告高于 Mitra，没过；第 3 批让模型自学分歧惩罚，λ 学成 0，也没过。代价是召回介于两个父算法之间。',
      },
      {
        round: '最终裁决',
        speaker: 'judge',
        line: '新知识不是公式本身，而是“任务内学习与预训练上下文的一致性，可以作为稀有故障告警的筛选信号”。保存为可继续组合的知识节点。',
      },
    ],
    cast: {
      proponent: { name: '发现方', en: 'Discoverer', shape: 'circle', color: '#2563EB' },
      critic: { name: '质疑方', en: 'Critic', shape: 'triangle', color: '#6366F1' },
      statistician: { name: '数理推导', en: 'Mathematician', shape: 'squircle', color: '#0EA5E9' },
      confounder: { name: '对照方', en: 'Ablation', shape: 'hex', color: '#64748B' },
      judge: { name: '总裁判', en: 'Judge', shape: 'circle', color: '#1E3A8A' },
    },
    verdict: [
      { label: '父算法', value: 'TabM × Mitra-v2', round: 0 },
      { label: '第一层 · 平均风险 − 分歧项', value: '√pq = (p+q)/2 − (√p−√q)²/2', round: 2, good: true },
      { label: '第二层 · 共识 × 一致性折扣', value: 'g = B · r = r · exp(−min J)', round: 3, good: true },
      { label: '精确率条件', value: 'TPR/FPR ↑ · 误告降幅 > 检出降幅', round: 4, good: true },
      { label: 'Q1 / Q2 精确率', value: '42.82% / 64.71%', round: 4 },
      { label: '同父对照', value: '算术平均 ✗ · 学习式惩罚 ✗', round: 5 },
    ],
    outcome: { title: '新知识节点', sub: '共识风险 × 一致性折扣 · 待未见季度确认' },
    chain: ['候选晋升', '新颖性质询', '平均风险 − 分歧', '共识 × 一致性折扣', '精确率机制', '同父消融', '知识入库'],
  },
  report: buildRunReport(PAPER_REPORT_INPUT),
};
