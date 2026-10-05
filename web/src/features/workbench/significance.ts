/**
 * 节点显著性的可读解释（TODO 5.4 / PRD §9.4）。
 *
 * 为什么要单独一个模块：TODO 5.4 明写"不要让多个前端组件各自判断显著性"。
 * 树上的节点卡、节点抽屉、时间轴、排行榜四处都要显示同一个判定，
 * 各写一份必然出现"树上说带内、抽屉说带外"。
 *
 * 判定本身由**后端**给出（`TreeNodeDTO.within_noise_band`，契约 1.2.0），
 * 这里只负责把三态翻成用户看得懂的话，不重新计算。
 */
import type { TreeNodeDto } from '@/generated/api';

export type Significance = 'best' | 'progress' | 'noise' | 'unknown';

export interface SignificanceVerdict {
  significance: Significance;
  /** 短标签，直接放节点卡上。 */
  label: string;
  /** 一句话解释，鼠标悬停或抽屉里显示。 */
  reason: string;
  /** 语义色键，交给 CSS 变量，组件里不写死颜色。 */
  tone: 'best' | 'positive' | 'muted' | 'neutral';
}

/**
 * 四档判定：
 * - `best`     最优节点，全局唯一
 * - `progress` 改进超出噪声带，是真实的进步
 * - `noise`    变化落在噪声带内，不能当证据
 * - `unknown`  没有 delta 或没有噪声估计 —— 不是"无改进"，是"不知道"
 */
export function classifySignificance(node: TreeNodeDto): Significance {
  if (node.is_best) return 'best';
  const band = node.within_noise_band;
  if (band === null || band === undefined) return 'unknown';
  return band ? 'noise' : 'progress';
}

/**
 * 只看波动带，不看 `is_best`。
 *
 * 为什么需要它：`classifySignificance` 把 `is_best` 短路成 `'best'`，那在树上是对的
 * （最优节点必须一眼可辨），但结果页要回答的是另一个问题——「**这个最优节点自己的
 * 提升**站不站得住」（PRD 13.3）。一个节点完全可以既是最优、其相对基线的提升又落在
 * 波动带内。所以在 `classifySignificance` 里加参数会让两处语义纠缠，
 * 单开一个只判波动带的函数更清楚，判定依据仍然是后端那一个字段。
 */
export type NoiseBand = 'within' | 'beyond' | 'unknown';

export function classifyNoiseBand(node: TreeNodeDto | null | undefined): NoiseBand {
  const band = node?.within_noise_band;
  if (band === null || band === undefined) return 'unknown';
  return band ? 'within' : 'beyond';
}

const VERDICTS: Record<Significance, Omit<SignificanceVerdict, 'reason'>> = {
  // `best` 用独立的 'best' 色而不是复用 'positive'：全局最优只有一个，
  // 它必须在一堆"有效改进"里一眼被认出来（TODO 5.4 显著性分档要视觉可辨）。
  best: { significance: 'best', label: '当前最优', tone: 'best' },
  progress: { significance: 'progress', label: '有效改进', tone: 'positive' },
  noise: { significance: 'noise', label: '噪声内', tone: 'muted' },
  unknown: { significance: 'unknown', label: '无法判断', tone: 'neutral' },
};

/** 解释里带上具体数值，否则"有效改进"对读者没有任何信息量。 */
function reasonFor(node: TreeNodeDto, significance: Significance): string {
  const delta = node.delta_score;
  const noise = node.noise_delta;
  const deltaText = delta === null || delta === undefined ? '无' : delta.toFixed(3);
  const noiseText = noise === null || noise === undefined ? '未知' : noise.toFixed(3);

  switch (significance) {
    case 'best':
      return `当前全局最优节点（分数 ${node.score?.toFixed(3) ?? '未评分'}）`;
    case 'progress':
      return `Δ=${deltaText} 超出噪声带 ±${noiseText}，可视为真实改进`;
    case 'noise':
      return `Δ=${deltaText} 落在噪声带 ±${noiseText} 内，不能作为改进证据`;
    case 'unknown':
      return delta === null || delta === undefined
        ? '该节点没有记录 Δ，无法判断是否真实改进'
        : `缺少噪声估计（±未知），无法与 Δ=${deltaText} 比较`;
  }
}

export function explainSignificance(node: TreeNodeDto): SignificanceVerdict {
  const significance = classifySignificance(node);
  return { ...VERDICTS[significance], reason: reasonFor(node, significance) };
}

/**
 * 节点卡的边框色，四档各一个（TODO 5.4：显著性分档必须视觉可辨）。
 *
 * 取值依据两件事：
 * 1. 概念图（`docs/images/frontend-concepts/02-evolution-workbench.png`）里
 *    节点边框就是状态色，四档用绿 / 蓝 / 橙 / 灰四族，而不是深浅不同的同一族灰。
 * 2. 语义要诚实：`noise`（Δ 落在噪声带内）**不是失败**，所以不能用
 *    `danger-500`（那是 `invalid` 节点的语义，两者会在同一张图上并存）。
 *    它表达的是"存疑"，用告警色才对。
 *
 * 曾经的 `noise` 是 `border-strong`、`unknown` 是 `border-subtle` —— 两个都是
 * 浅灰，分档等于没分。`unknown` 现在靠**虚线**边框区分（概念图里未定态也是虚线）。
 */
export function significanceAccent(significance: Significance): string {
  switch (significance) {
    case 'best':
      return 'var(--color-brand-600)';
    case 'progress':
      return 'var(--color-success-500)';
    case 'noise':
      return 'var(--color-warning-500)';
    case 'unknown':
      return 'var(--color-border-strong)';
  }
}

/**
 * 哪些显著性用**虚线**边框。
 *
 * 只有「无法判断」用虚线：它表示"缺数据、不能下结论"，与"结论是不显著"
 * 是两回事（后者用实线告警色）。概念图里未定态（休眠种子）也是虚线边框。
 * 其余三档靠 `significanceAccent` 的色相区分，不叠加线型，避免两条编码打架。
 */
export const SIGNIFICANCE_DASHED_BORDER: Record<Significance, boolean> = {
  best: false,
  progress: false,
  noise: false,
  unknown: true,
};

/** 统计四档数量，用于树页顶部的分布条。 */
export function significanceCounts(nodes: TreeNodeDto[]): Record<Significance, number> {
  const counts: Record<Significance, number> = { best: 0, progress: 0, noise: 0, unknown: 0 };
  for (const node of nodes) {
    counts[classifySignificance(node)] += 1;
  }
  return counts;
}
