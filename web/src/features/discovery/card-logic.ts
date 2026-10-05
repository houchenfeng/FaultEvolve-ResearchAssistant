/**
 * 知识卡页的推导逻辑（PRD 12.2 / TODO 6.1）。
 *
 * 与 KnowledgeCardList 分文件：react-refresh 要求组件文件只导出组件，
 * 这些纯函数要被测试直接引用（同 task-detail-logic.ts 的分工）。
 *
 * 贯穿全文件的一条规则：**后端给 null 就写「未记录」，绝不显示 0**
 * （PRD §2.3）。这条在知识卡上尤其要紧，因为 `replay_service.py:1289-1294`
 * 自己注明了「n == 0 表示从未有过有效采纳，均值是未知而不是零」。
 */
import type {
  KnowledgeCardResponse,
  KnowledgeCardStatResponse,
  RunKnowledgeResponse,
} from '@/generated/api';

export const NOT_RECORDED = '未记录';

/** 一个数格子：值 + 它到底是「查到了」还是「没记录」。 */
export interface Cell {
  value: string;
  recorded: boolean;
}

const UNKNOWN: Cell = { value: NOT_RECORDED, recorded: false };

// --------------------------------------------------------------------------
// 兼容旧 API（origin/main 的 report-logic / tournament-logic 仍用这套类型）
// --------------------------------------------------------------------------

export type FieldState = 'recorded' | 'unrecorded' | 'not_applicable';

export type CardTone = 'brand' | 'positive' | 'neutral' | 'muted' | 'warning';

export interface FieldView {
  state: FieldState;
  text: string;
  tone: CardTone;
}

export function cellToFieldView(cell: Cell, tone: CardTone = 'neutral'): FieldView {
  return {
    state: cell.recorded ? 'recorded' : 'unrecorded',
    text: cell.value,
    tone,
  };
}

export function countCell(count: number | null | undefined): Cell {
  return count == null ? UNKNOWN : { value: String(count), recorded: true };
}

/** 与 `significance.ts` 的 delta 保持同一精度，免得同一个量在两页显示不一样。 */
export function deltaCell(delta: number | null | undefined): Cell {
  return delta == null ? UNKNOWN : { value: delta.toFixed(3), recorded: true };
}

/** 比率换算成百分数显示，此外不做任何加工。 */
export function rateCell(rate: number | null | undefined): Cell {
  return rate == null ? UNKNOWN : { value: `${(rate * 100).toFixed(1)}%`, recorded: true };
}

// --------------------------------------------------------------------------
// 本地标记（信任 / 存疑 / 排除）
// --------------------------------------------------------------------------

/**
 * PRD 12.2：这三个标记「仅作为浏览器或用户界面标记，并明确不影响真实运行」。
 *
 * 契约里没有写回端点（`KnowledgeCardResponse.local_label` 只读，
 * `replay_service.py` 也从不设置它），所以标记**只存在浏览器本地**：
 * 这恰好是 PRD 要求的语义——它不该影响运行，也就不该进运行制品。
 */
export const CARD_LABELS = ['信任', '存疑', '排除'] as const;

export type CardLabel = (typeof CARD_LABELS)[number];

export function isCardLabel(value: unknown): value is CardLabel {
  return typeof value === 'string' && (CARD_LABELS as readonly string[]).includes(value);
}

export function cardLabelStorageKey(runId: string): string {
  return `fe.card-labels.${runId}`;
}

/**
 * 读本地标记。存储内容属于系统边界（用户可能手改、旧版本可能留下别的形状），
 * 所以逐条校验：读不出就当成没有标记，不抛异常。
 */
export function readCardLabels(runId: string, storage: Storage): Record<string, CardLabel> {
  let raw: string | null;
  try {
    raw = storage.getItem(cardLabelStorageKey(runId));
  } catch {
    return {};
  }
  if (!raw) return {};
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return {};
  }
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return {};
  const result: Record<string, CardLabel> = {};
  for (const [cardId, label] of Object.entries(parsed as Record<string, unknown>)) {
    if (isCardLabel(label)) result[cardId] = label;
  }
  return result;
}

export function writeCardLabel(
  runId: string,
  cardId: string,
  label: CardLabel | null,
  storage: Storage,
): Record<string, CardLabel> {
  const next = { ...readCardLabels(runId, storage) };
  if (label === null) delete next[cardId];
  else next[cardId] = label;
  try {
    storage.setItem(cardLabelStorageKey(runId), JSON.stringify(next));
  } catch {
    // 存储写满或被禁用时，标记就只活在内存里；不值得为此让整页崩掉。
  }
  return next;
}

// --------------------------------------------------------------------------
// 卡片行
// --------------------------------------------------------------------------

export interface CardSource {
  sourceId: string;
  title: string | null;
  url: string | null;
  /** sources.yaml 的 takeaway。没有就保持 null，不用统计量去写一段摘要。 */
  takeaway: string | null;
}

export interface CardRow {
  cardId: string;
  title: string | null;
  category: string | null;
  claim: string | null;
  sourceKind: string | null;
  conditions: string | null;
  /** 知识库卡片上的 1–5 优先级，不是由平均 Δ 推出来的。 */
  priority: number | null;
  sources: CardSource[];
  offered: Cell;
  adopted: Cell;
  refuted: Cell;
  invalid: Cell;
  meanDelta: Cell;
  /** 采用它的代（depth）与节点，PRD 12.2 要求能看到「在哪些节点、哪些代被采用」。 */
  adoptedIterations: number[];
  adoptedNodeIds: string[];
  /** `card_stats` 表里的样本数；均值为 null 时用它解释「为什么没有均值」。 */
  statN: Cell;
  label: CardLabel | null;
}

const CATEGORY_LABELS: Record<string, string> = {
  feature_engineering: '特征工程',
  model: '模型',
  evaluation: '评价',
  pitfalls: '陷阱',
  thresholding: '阈值',
  labeling: '标注',
  imbalance: '不平衡',
  transfer: '迁移',
  ensembling: '集成',
};

const SOURCE_KIND_LABELS: Record<string, string> = {
  paper: '论文',
  blog: '博客',
  benchmark: '基准',
};

export function categoryLabel(category: string): string {
  return CATEGORY_LABELS[category] ?? category;
}

export function sourceKindLabel(kind: string): string {
  return SOURCE_KIND_LABELS[kind] ?? kind;
}

/** 只有 http(s) 能变成链接。其它方案（javascript:、file:）一律不当链接。 */
export function httpUrl(url: string | null | undefined): string | null {
  if (!url || /\s/.test(url)) return null;
  try {
    const parsed = new URL(url);
    if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') return null;
    return url;
  } catch {
    return null;
  }
}

/**
 * `adopted_count` 为 null 有**两种**成因，不能一律显示「未记录」也不能一律显示 0：
 *
 * - `fe.db` 不可读 ⇒ `node_adopted_cards` 表根本没读到 ⇒ 真的是未知；
 * - `fe.db` 可读但这张卡没有采纳节点 ⇒ `replay_service.py:1307` 把 0 写成了 None。
 *
 * 区分二者只能靠 `artifact_states.database`，所以它必须由调用方传进来。
 * 猜错任一边都会骗人：前者显示 0 是「把没查到画成没有问题」，
 * 后者显示未记录则把一份完整的运行说得像缺数据。
 */
export function buildCardRows(
  cards: KnowledgeCardResponse[],
  stats: KnowledgeCardStatResponse[] | undefined,
  options: { databaseAvailable: boolean; labels?: Record<string, CardLabel> },
): CardRow[] {
  const statByCard = new Map((stats ?? []).map((stat) => [stat.card_id, stat]));
  const labels = options.labels ?? {};

  return cards.map((card) => {
    const stat = statByCard.get(card.card_id);
    const nodeIds = card.adopted_node_ids ?? [];
    const adopted: Cell =
      card.adopted_count != null
        ? { value: String(card.adopted_count), recorded: true }
        : options.databaseAvailable
          ? { value: String(nodeIds.length), recorded: true }
          : UNKNOWN;

    return {
      cardId: card.card_id,
      title: card.title ?? null,
      category: card.category ?? null,
      claim: card.claim ?? null,
      sourceKind: card.source_kind ?? null,
      conditions: card.conditions ?? null,
      priority: card.priority ?? null,
      sources: (card.sources ?? []).map((source) => ({
        sourceId: source.source_id,
        title: source.title ?? null,
        url: source.url ?? null,
        takeaway: source.takeaway ?? null,
      })),
      offered: countCell(card.offered_count),
      adopted,
      refuted: countCell(card.refuted_count),
      invalid: countCell(card.invalid_count),
      meanDelta: deltaCell(card.mean_delta),
      adoptedIterations: card.adopted_iterations ?? [],
      adoptedNodeIds: nodeIds,
      statN: countCell(stat?.n),
      label: labels[card.card_id] ?? null,
    };
  });
}

export interface CardFilter {
  query: string;
  label: CardLabel | 'any';
  category: string | 'any';
}

export const EMPTY_CARD_FILTER: CardFilter = { query: '', label: 'any', category: 'any' };

/**
 * 搜索覆盖卡片 ID、标题、claim 和本地标记。类别来自知识库，没有类别时不做空的下拉框。
 */
export function filterCards(rows: CardRow[], filter: CardFilter): CardRow[] {
  const query = filter.query.trim().toLowerCase();
  const category = filter.category ?? 'any';
  return rows.filter((row) => {
    if (filter.label !== 'any' && row.label !== filter.label) return false;
    if (category !== 'any' && row.category !== category) return false;
    if (!query) return true;
    const haystack = [row.cardId, row.title, row.claim, row.label]
      .filter((part): part is string => Boolean(part))
      .join(' ')
      .toLowerCase();
    return haystack.includes(query);
  });
}

export function cardHasProse(row: CardRow): boolean {
  return (
    row.title != null ||
    row.category != null ||
    row.claim != null ||
    row.sourceKind != null ||
    row.conditions != null ||
    row.priority != null ||
    row.sources.length > 0
  );
}

// --------------------------------------------------------------------------
// 采用汇总（来自 run_summary.json，不是 fe.db）
// --------------------------------------------------------------------------

export interface AdoptionSummaryRow {
  label: string;
  cell: Cell;
}

export function adoptionSummaryRows(knowledge: RunKnowledgeResponse | null): AdoptionSummaryRow[] {
  return [
    { label: '提供过的卡片数', cell: countCell(knowledge?.cards_offered) },
    { label: '被采纳的卡片数', cell: countCell(knowledge?.cards_adopted) },
    { label: '采纳后有效的卡片数', cell: countCell(knowledge?.cards_adopted_valid) },
    { label: '卡片采纳率', cell: rateCell(knowledge?.card_adoption_rate) },
  ];
}

// --------------------------------------------------------------------------
// 契约没有的部分
// --------------------------------------------------------------------------

/**
 * 本地标记必须与这句话同时出现（PRD 12.2 明确要求）。
 * `affects_run` 由后端给出且恒为 false，页面如实回显而不是自己断言。
 */
export const LOCAL_LABEL_DISCLAIMER = '仅浏览器本地标记，不影响真实运行';

export const PROSE_ABSENCE_NOTE =
  '标题、类别、claim、来源和适用条件按卡片 ID 对照任务知识库。对不上，或这次运行没有登记任务时，这些格子是未记录。知识库优先级是卡片上的 1–5，不是由平均 Δ 算出来的。';

export const TRUST_MARKER_NOTE = '本地标记，不影响运行';

export function presentValue(
  value: string | number | null | undefined,
  format: (v: string | number) => string = (v) => String(v),
): FieldView {
  if (value == null) {
    return { state: 'unrecorded', text: NOT_RECORDED, tone: 'muted' };
  }
  return { state: 'recorded', text: format(value), tone: 'neutral' };
}

// --------------------------------------------------------------------------
// 空结果解释（PRD 12.1：真实发现为空时解释为什么为空）
// --------------------------------------------------------------------------

export interface CardEmptyState {
  title: string;
  reason: string;
  nextStep: string;
}

/**
 * 一张卡都没有，可能是三件不同的事，绝不能一律说「这次运行没有知识卡」：
 *
 * - `fe.db` 读不到 ⇒ 卡片清单**主要**来自它的四张表，读不到就等于查不出来，
 *   此时说「没有知识卡」是把查询失败讲成事实；
 * - 运行详情没取到（`unknown`）⇒ 连 `fe.db` 状态都不知道，只能说「无法判断」；
 * - 两者都正常 ⇒ 才是真的没有提供过卡片。
 */
export function cardEmptyState(
  databaseState: string,
  knowledge: RunKnowledgeResponse | null,
): CardEmptyState {
  const offered = knowledge?.cards_offered ?? null;

  if (databaseState === 'missing' || databaseState === 'invalid') {
    return {
      title: '读不到这次运行的知识卡',
      reason: `fe.db ${databaseState === 'invalid' ? '不可解析' : '缺失'}，而卡片清单主要来自它的四张统计表（card_stats / branch_offered_cards / branch_refuted_cards / node_adopted_cards）。这是查询不到，不代表这次运行没有用过知识卡。`,
      nextStep: '到「工作台总览」确认该运行的制品状态（artifact_states.database），必要时重新导出运行制品。',
    };
  }

  if (databaseState !== 'available') {
    return {
      title: '暂时无法判断这次运行有没有知识卡',
      reason: '运行详情没有取到，拿不到 fe.db 的制品状态，因此无法区分「没有卡片」和「查不到卡片」。',
      nextStep: '重试运行详情请求；若仍然失败，请检查 Web API 是否在线。',
    };
  }

  return {
    title: '这次运行没有提供过知识卡',
    reason:
      offered === null
        ? 'fe.db 可读，但卡片清单为空，且 run_summary.json 里没有记录「提供过的卡片数」。'
        : `fe.db 可读，卡片清单为空；run_summary.json 记录「提供过的卡片数 = ${offered}」。`,
    nextStep: '若要看到卡片采用情况，需要在任务配置里启用知识卡或自动检索，再重跑一次。',
  };
}
