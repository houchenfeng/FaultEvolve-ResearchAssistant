/**
 * 结果与报告页的推导逻辑（PRD 13.1–13.3 / 13.5，TODO 6.4）。
 *
 * 这一页的纪律和知识发现页一样：**每个数字都要能指回一个 DTO 字段**。
 * PRD 13.5 要求报告里的每个数字可追溯到 run_summary.json / tree.json /
 * events.jsonl / fe.db / discovery 制品，所以这里的每一行都带一个 `source`，
 * 直接渲染到界面上——追溯性不是文档里的一句话，是页面上看得见的一列。
 *
 * 三处必须报暂不支持的缺口（都查证过源码，不是猜的）：
 *
 * 1. **分项指标没有类型化 DTO。** F1_p10 / AUPRC / R@FAR / 时间因子 / precision /
 *    recall / 误告率 / 漏告率在 `contracts.py` 里一个都没有（全仓 grep 无匹配），
 *    只存在于引擎侧 `tasks/hdd_adapter.py:219-221`。唯一可能透出它们的地方是
 *    `NodeEvaluationResponse.metric: dict[str, Any]`（`contracts.py:797`），
 *    那是**无键保证**的透传字典。⇒ 本页照实渲染后端实际给了哪些键，
 *    但**不假定**任何一个键存在，也不为缺失的键补 0。
 *
 * 2. **相对提升不渲染。** 契约只给 `improvement`（绝对提升）。用
 *    `improvement / initial_score` 现算一个百分比，就是在前端制造第二个评分真源
 *    （PRD §2.2），而且 `initial_score` 可能为 0 或 null。⇒ 报暂不支持。
 *
 * 3. **运行级波动带不存在。** `RunOutcomeResponse` 没有 noise 字段。
 *    同一任务的并排展示在运行对比页，且只在列表带 `task_id` 时可用。
 *    ⇒ 但**节点级**的波动判定是真的：`TreeNodeDTO.within_noise_band`
 *    （`contracts.py:731`）由后端 `_within_noise()` 算好（`replay_service.py:1031-1035`），
 *    PRD 13.3 那句「未形成明确改进证据」就落在它上面。
 */
import type {
  ArtifactResponse,
  NodeEvaluationResponse,
  ReportManifestResponse,
  RunDetailResponse,
  ScoreboardEntryResponse,
  TreeNodeDto,
  TreeResponse,
} from '@/generated/api';

import { NOT_RECORDED, countCell, rateCell, type Cell } from '@/features/discovery/card-logic';
// 波动带判定只能有一个出处（TODO 5.4：「不要让多个前端组件各自判断显著性」）。
// 这里只负责把 `classifyNoiseBand` 的三档翻成结果页要说的话，不重读那个字段。
import { classifyNoiseBand } from '@/features/workbench/significance';

// --------------------------------------------------------------------------
// 数值格式
// --------------------------------------------------------------------------

/** 分数固定两位：与 `tree-adapter.ts:128-131` 同精度，同一个量不能两页不一样。 */
export function scoreCell(value: number | null | undefined): Cell {
  return value == null ? { value: NOT_RECORDED, recorded: false } : { value: value.toFixed(2), recorded: true };
}

/** 秒。一位小数够读出量级，再多只是在展示 JSON 里的浮点尾巴。 */
export function secondsCell(value: number | null | undefined): Cell {
  return value == null ? { value: NOT_RECORDED, recorded: false } : { value: `${value.toFixed(1)} s`, recorded: true };
}

export function textCell(value: string | null | undefined): Cell {
  return value == null || value.length === 0
    ? { value: NOT_RECORDED, recorded: false }
    : { value, recorded: true };
}

// --------------------------------------------------------------------------
// 13.1 结果总览
// --------------------------------------------------------------------------

/** 一行结果 + 它的来源。`source` 会被渲染出来（PRD 13.5 的可追溯要求）。 */
export interface SourceRow {
  label: string;
  cell: Cell;
  source: string;
}

const SUMMARY = 'run_summary.json';
const BUDGET = 'run_summary.json（预算段）';

/**
 * PRD 13.1「核心指标」九项。全部来自 `RunOutcomeResponse`（`contracts.py:520-534`）
 * 与 `RunBudgetResponse`（`contracts.py:493-517`），两者都由 `replay_groups.py:56-71`
 * 从 run_summary.json 一比一搬过来——前端不参与计算。
 *
 * 「相对提升（百分比）」不在契约里，本页不展示。
 */
export function outcomeRows(detail: RunDetailResponse | null | undefined): SourceRow[] {
  const outcome = detail?.outcome ?? null;
  const budget = detail?.budget ?? null;
  return [
    { label: '初始 ROS', cell: scoreCell(outcome?.initial_score), source: SUMMARY },
    { label: '最佳 ROS', cell: scoreCell(outcome?.best_score), source: SUMMARY },
    { label: '绝对提升', cell: scoreCell(outcome?.improvement), source: SUMMARY },
    { label: '最佳节点', cell: textCell(outcome?.best_node_id), source: SUMMARY },
    { label: '完成轮次', cell: countCell(outcome?.iterations_done), source: SUMMARY },
    { label: '有效节点率', cell: rateCell(outcome?.valid_rate), source: SUMMARY },
    { label: '达到目标轮次', cell: countCell(outcome?.rounds_to_target), source: SUMMARY },
    { label: '达到目标耗时', cell: secondsCell(outcome?.time_to_target_s), source: SUMMARY },
    { label: '达到目标 Token', cell: countCell(outcome?.tokens_to_target), source: SUMMARY },
    { label: '总 Token', cell: countCell(budget?.total_tokens), source: BUDGET },
    { label: '总耗时', cell: secondsCell(budget?.wall_time_s), source: BUDGET },
  ];
}

// --------------------------------------------------------------------------
// 13.1 分项指标（无键保证的透传字典）
// --------------------------------------------------------------------------

export interface MetricRow {
  key: string;
  cell: Cell;
}

/**
 * 分项指标一节的四态。分成四态而不是「成功/失败」两态，是因为
 * 「压根没发请求」（没有最佳节点）、「发了但失败」、「发了、成功了、字典是空的」
 * 三者指向完全不同的下一步，混成一个「无数据」会逼读者去猜。
 */
export type MetricsState = 'skipped' | 'pending' | 'error' | 'ready';

/**
 * `NodeEvaluationResponse.metric` 是 `dict[str, Any]`，**契约不保证任何键**
 * （`replay_service.py:931` 只在它是 dict 时原样透传）。
 *
 * 所以这里只做一件事：把后端实际给出的键按名字排序后逐个渲染。
 * - 不预置 F1_p10 / AUPRC / R@FAR 这些名字：预置了就得给它们编一个值；
 * - 不重算任何比率；
 * - 数值一律原样格式化，整数不加小数点，浮点四位（比率常小于 0.001）。
 */
export function metricRows(metric: NodeEvaluationResponse['metric'] | undefined): MetricRow[] {
  if (!metric || typeof metric !== 'object') return [];
  return Object.keys(metric)
    .sort()
    .map((key) => ({ key, cell: metricCell(metric[key]) }));
}

function metricCell(value: unknown): Cell {
  if (value == null) return { value: NOT_RECORDED, recorded: false };
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) return { value: NOT_RECORDED, recorded: false };
    return {
      value: Number.isInteger(value) ? String(value) : value.toFixed(4),
      recorded: true,
    };
  }
  if (typeof value === 'boolean') return { value: value ? '是' : '否', recorded: true };
  if (typeof value === 'string') {
    return value.length === 0 ? { value: NOT_RECORDED, recorded: false } : { value, recorded: true };
  }
  // 数组/对象也是后端给的真实内容，藏起来反而丢信息；React 会转义，不存在注入。
  return { value: JSON.stringify(value), recorded: true };
}

// --------------------------------------------------------------------------
// 13.3 波动带判定（节点级是真的，运行级不存在）
// --------------------------------------------------------------------------

/**
 * 最佳节点 id 有两个出处：`RunOutcomeResponse.best_node_id`（run_summary 原样搬来）
 * 与 `TreeResponse.best_node_id`。它们不会「各说一个不同的节点」——后端把 summary 里
 * 的 id 拿去树里核对，核对不过就置 null 并写一条 `field="best_node_id"` 的
 * ContractWarning（`replay_service.py:753-760,787`）。
 *
 * ⇒ 取 run_summary 的那个：它就是上面「最佳 ROS / 最佳节点」两行的出处，
 * 同一页上下必须指同一个节点。核对不过的情况由 `TreeResponse.warnings`
 * 照实渲染（见 ComparisonSection），不在前端另做一遍同样的核对。
 */
export function bestNodeIdOf(
  detail: RunDetailResponse | null | undefined,
  tree: TreeResponse | null | undefined,
): string | null {
  return detail?.outcome?.best_node_id ?? tree?.best_node_id ?? null;
}

export type NoiseBandLabel = ReturnType<typeof classifyNoiseBand>;

export interface NoiseVerdict {
  /** PRD 13.3 的原话落在 'within' 这一支。 */
  label: string;
  tone: 'success' | 'warning' | 'neutral';
  reason: string;
  band: NoiseBandLabel;
}

/**
 * `within_noise_band` 是**三值**：true / false / null。
 * `contracts.py:727-730` 明确要求 null 时 UI 说「无法判断」——
 * 折成 false 会把「后端没算出来」讲成「这是有效改进」。
 *
 * 措辞与树页/时间轴不同是故意的：那边标「噪声内 / 有效改进」是给单个节点看的，
 * 这里要回答的是「这次提升算不算改进」（PRD 13.3 指定的原话）。
 * 判定出自同一个字段、同一个函数，所以两处不会互相打脸。
 */
export function noiseVerdict(node: TreeNodeDto | null | undefined): NoiseVerdict {
  const band = classifyNoiseBand(node);
  const delta = node?.delta_score;
  const noise = node?.noise_delta;
  const measured =
    delta == null || noise == null
      ? '差值或波动带未记录'
      : `差值 ${delta.toFixed(3)}，波动带 ±${Math.abs(noise).toFixed(3)}`;

  if (band === 'within') {
    return {
      label: '未形成明确改进证据',
      tone: 'warning',
      band,
      reason: `该节点相对其基线的提升落在已知波动范围内（${measured}）。按 PRD 13.3，这不得当成改进。树页与时间轴把同一档标作「噪声内」。`,
    };
  }
  if (band === 'beyond') {
    return {
      label: '改进超出波动范围',
      tone: 'success',
      band,
      reason: `后端判定该提升大于波动带（${measured}）。判定由 replay_service._within_noise 给出，前端不重算。`,
    };
  }
  return {
    label: '无法判断',
    tone: 'neutral',
    band,
    reason: `后端没有给出 within_noise_band（${measured}）。这既不是「有改进」也不是「没有改进」。`,
  };
}

export interface NoiseSummary {
  total: Cell;
  scored: Cell;
  /** 有对比基线（delta_score 非空）的节点，是下面三个计数的分母。 */
  compared: Cell;
  within: Cell;
  beyond: Cell;
  unknown: Cell;
}

/**
 * 分母必须是「有对比基线的节点」而不是全部节点：根节点没有 delta，
 * 混进去会让「无法判断」凭空多出一个，看起来像后端漏算。
 * 三个计数一律走 `classifyNoiseBand`，所以 within + beyond + unknown === compared 恒成立。
 *
 * `nodes === undefined` 表示进化树**没取到**，与「取到了但是空树」是两件事：
 * 前者一律未记录，后者才是真的 0。这条与知识卡页 `adopted_count` 的处置同理。
 */
export function noiseSummary(nodes: TreeNodeDto[] | undefined): NoiseSummary {
  if (nodes == null) {
    const unknown: Cell = { value: NOT_RECORDED, recorded: false };
    return {
      total: unknown,
      scored: unknown,
      compared: unknown,
      within: unknown,
      beyond: unknown,
      unknown,
    };
  }
  const scored = nodes.filter((node) => node.score != null);
  const compared = nodes.filter((node) => node.delta_score != null);
  const bands = compared.map((node) => classifyNoiseBand(node));
  return {
    total: countCell(nodes.length),
    scored: countCell(scored.length),
    compared: countCell(compared.length),
    within: countCell(bands.filter((band) => band === 'within').length),
    beyond: countCell(bands.filter((band) => band === 'beyond').length),
    unknown: countCell(bands.filter((band) => band === 'unknown').length),
  };
}

// --------------------------------------------------------------------------
// 13.2 Top-K 候选
// --------------------------------------------------------------------------

export const DEFAULT_TOP_K = 10;

export interface TopKRow {
  rank: Cell;
  nodeId: string;
  score: Cell;
  operator: string | null;
  depth: Cell;
  isBest: boolean;
  /** 只有当制品清单里确实存在且 `downloadable` 为真时才有值。 */
  programArtifactId: string | null;
  /**
   * null = 制品清单**没取到**，无从判断；false = 取到了，但这个候选没有可下载代码。
   * 两者在界面上必须分开：把「不知道」画成「不可下载」，会让一次请求故障
   * 看起来像后端真的拒绝了下载。
   */
  downloadable: boolean | null;
}

/**
 * `/api/runs/{id}/leaderboard` 返回的已经是**排好序**的列表
 * （`replay_service.py:1038-1059`：按分数排序、未评分的排最后，`rank` 由后端给）。
 * 所以这里只截断，**不重排也不重新编号**——重排就等于在前端另立一个排名真源。
 *
 * 候选代码的 artifact_id 形如 `program-{node_id}`（引擎按 `programs/{node_id}.py`
 * 落盘，`engine.py:3039`；服务端按同规则签发 id，`replay_service.py:1547-1552`）。
 * 但**不靠拼字符串下结论**：只有该 id 真的出现在 `/artifacts` 清单里、
 * 且 `downloadable === true` 时才给出下载入口。
 */
export function topKRows(
  entries: ScoreboardEntryResponse[] | undefined,
  artifacts: ArtifactResponse[] | undefined,
  k: number = DEFAULT_TOP_K,
): TopKRow[] {
  const known = artifacts != null;
  const downloadable = new Set(
    (artifacts ?? []).filter((item) => item.downloadable).map((item) => item.artifact_id),
  );
  return (entries ?? []).slice(0, k).map((entry) => {
    const programArtifactId = `program-${entry.node_id}`;
    const present = downloadable.has(programArtifactId);
    return {
      rank: countCell(entry.rank),
      nodeId: entry.node_id,
      score: scoreCell(entry.score),
      operator: entry.operator ?? null,
      depth: countCell(entry.depth),
      isBest: entry.is_best === true,
      programArtifactId: present ? programArtifactId : null,
      downloadable: known ? present : null,
    };
  });
}

// --------------------------------------------------------------------------
// 13.5 报告 manifest
// --------------------------------------------------------------------------

export interface ReportRow {
  artifactId: string;
  displayName: string;
  mediaType: Cell;
  sizeBytes: Cell;
  state: string;
  /** 清单本身没有这个字段，从 `/artifacts` 关联；关联不上就不给下载入口。 */
  downloadable: boolean | null;
}

export function sizeCell(bytes: number | null | undefined): Cell {
  if (bytes == null || !Number.isFinite(bytes)) return { value: NOT_RECORDED, recorded: false };
  if (bytes < 1024) return { value: `${bytes} B`, recorded: true };
  if (bytes < 1024 * 1024) return { value: `${(bytes / 1024).toFixed(1)} KB`, recorded: true };
  return { value: `${(bytes / (1024 * 1024)).toFixed(1)} MB`, recorded: true };
}

/**
 * `ReportManifestResponse.available` 的语义要照实转达：它是 `bool(files)`
 * （`replay_service.py:1635`），即「运行目录下有没有已导出的报告文件」。
 * **false 不代表导出失败**，本阶段根本不生成报告（`contracts.py:1018-1022`）。
 */
export function reportRows(
  manifest: ReportManifestResponse | null | undefined,
  artifacts: ArtifactResponse[] | undefined,
): ReportRow[] {
  const byId = new Map((artifacts ?? []).map((item) => [item.artifact_id, item]));
  return (manifest?.files ?? []).map((file) => {
    const artifact = byId.get(file.artifact_id);
    return {
      artifactId: file.artifact_id,
      displayName: file.display_name,
      mediaType: textCell(file.media_type),
      sizeBytes: sizeCell(file.size_bytes),
      state: file.state,
      downloadable: artifact == null ? null : artifact.downloadable,
    };
  });
}
