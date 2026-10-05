/**
 * 现象与假设检验的渲染逻辑（TODO 6.2）。
 *
 * TODO 6.2 要求每行显示：condition / feature / outcome / effect·CI / scope /
 * falsifier / grade·status / sandbox error。
 *
 * ## 数据从哪来（这是本模块最要紧的一条）
 *
 * 八个字段来自三个源，缺一不可：
 *
 * | 字段 | 来源 |
 * |---|---|
 * | effect / ci / p / e / direction_ok | `discovery.phenomena[].payload`（`ClaimTestResult`） |
 * | grade / status | `discovery.claims[]`（`claim` 表的镜像列 + payload） |
 * | condition / feature / outcome / scope / falsifier | `discovery.claims[].payload`（`Claim` 散文） |
 * | sandbox error | `discovery.claims[]` 里 `status='sandbox_failed'` 那行 |
 *
 * ## 散文为什么经常是「未记录」
 *
 * 引擎把 `claim.payload_json` 写了三次，**后写覆盖先写**：
 *
 * 1. `create_claim` → 完整 `Claim`（散文在）
 * 2. 沙箱失败 → `{"error": ...}`（散文被覆盖掉）
 * 3. 评分 → `{**ClaimTestResult, "grade": ...}`（散文又被覆盖）
 *
 * 所以跑完一轮之后，凡是进过第 2 或第 3 步的 claim，散文在**任何制品里都
 * 不存在了**（事件流只记 `{claim_id, source}`，没有散文）。这是引擎侧的
 * 覆盖式写入，不是本层的读法问题。
 *
 * 本模块因此把"散文未记录"做成一个**显式状态**并给出真实原因，绝不编内容。
 * 修掉它要改 `discovery/pipeline.py` 的 `update_claim` 调用点（引擎范围，
 * 本阶段明确不碰），而且只对之后的运行有效。
 */
import type {
  ClaimRowFields,
  ClaimTestPayload,
  DiscoveryResponse,
  PhenomenonEntryPayload,
} from '@/features/discovery/types';
import { presentValue, type CardTone, type FieldView } from '@/features/discovery/card-logic';

// --------------------------------------------------------------------------
// grade / status（TODO 6.2「grade/status」）
// --------------------------------------------------------------------------

/**
 * `Grade` 五个取值 —— 与 `discovery/schemas.py` 的 `Grade` 枚举逐字对应。
 *
 * `undetermined` 是**真实取值**，不是"没有 grade"。所以"没评级"（`null`）
 * 必须与它分开：前者是"没跑完/没评"，后者是"跑完了但证据不足以判定"。
 */
export type GradeKey = 'confirmed' | 'revised' | 'discovered' | 'refuted' | 'undetermined';

interface GradeVerdict {
  label: string;
  tone: CardTone;
  /** 一句话解释这个 grade 意味着什么。 */
  reason: string;
}

const GRADE_VERDICTS: Record<GradeKey, GradeVerdict> = {
  confirmed: {
    label: '已证实',
    tone: 'positive',
    reason: '预注册检验通过，效应方向与幅度都落在预期内',
  },
  revised: {
    label: '已修正',
    tone: 'positive',
    reason: '方向成立但幅度与预期不符，记录为修正后的主张',
  },
  discovered: {
    label: '新发现',
    tone: 'brand',
    reason: '检验通过但不在预注册范围内，作为新发现入册',
  },
  refuted: {
    label: '被否证',
    tone: 'warning',
    reason: '数据显示效应不存在或方向相反',
  },
  undetermined: {
    label: '未定',
    tone: 'neutral',
    reason: '证据不足以证实或否证 —— 不等于"没有效应"',
  },
};

const GRADE_UNRATED: GradeVerdict = {
  label: '未评级',
  tone: 'muted',
  reason: '这次运行没有给该主张打分（可能未跑到评分阶段）',
};

const KNOWN_GRADES = new Set<string>(Object.keys(GRADE_VERDICTS));

/** `grade` → 视图。`null`/未知值都归到「未评级」，不猜。 */
export function gradeVerdict(grade: string | null | undefined): GradeVerdict & {
  key: GradeKey | null;
} {
  if (grade === null || grade === undefined || !KNOWN_GRADES.has(grade)) {
    return { key: null, ...GRADE_UNRATED };
  }
  return { key: grade as GradeKey, ...GRADE_VERDICTS[grade as GradeKey] };
}

/** `claim` 表 status 的三个实际取值（`store.update_claim` 只允许这三条路）。 */
export type ClaimStatusKey = 'proposed' | 'sandbox_failed' | 'graded';

const CLAIM_STATUS_LABELS: Record<string, { label: string; tone: CardTone; note: string }> = {
  proposed: { label: '已提出', tone: 'neutral', note: '已写入预注册，尚未检验' },
  sandbox_failed: {
    label: '沙箱失败',
    tone: 'warning',
    note: '特征脚本在沙箱里跑失败，该主张未被检验',
  },
  graded: { label: '已评分', tone: 'brand', note: '检验完成并已给出 grade' },
};

/**
 * `status` → 视图。未知取值**原样透传**，因为 status 在契约里是自由字符串，
 * 假装认识它比显示原文更危险。
 */
export function claimStatusView(status: string | null | undefined): FieldView & {
  key: ClaimStatusKey | null;
  note: string;
} {
  if (status === null || status === undefined || status === '') {
    return {
      key: null,
      state: 'unrecorded',
      text: '未记录',
      tone: 'muted',
      note: '这一行没有状态信息',
    };
  }
  const known = CLAIM_STATUS_LABELS[status];
  if (known) {
    return { key: status as ClaimStatusKey, state: 'recorded', text: known.label, tone: known.tone, note: known.note };
  }
  return {
    key: null,
    state: 'recorded',
    text: status,
    tone: 'muted',
    note: '契约里的 status 是自由字符串，这里原样显示未识别的取值',
  };
}

// --------------------------------------------------------------------------
// effect / CI（TODO 6.2「effect/CI」）
// --------------------------------------------------------------------------

export interface EffectVerdict {
  /** 可直接渲染的 `effect [+0.012, +0.031]`。 */
  text: string;
  state: 'recorded' | 'unrecorded';
  tone: CardTone;
  /** 95% 置信区间是否跨越 0 —— 这是"能否当证据"的分水岭。 */
  crossesZero: boolean | null;
  /** 效应方向是否与预注册的 `direction` 一致。 */
  matchesDirection: boolean | null;
  reason: string;
}

/**
 * 效应与置信区间。
 *
 * 判定顺序有意如此：**先看 CI 是否跨 0**，再看方向。只报"effect 为正"而不报
 * CI 跨 0 是最常见的误导 —— 一个 `+0.001 [-0.02, +0.03]` 的效应不该被读成
 * "有正向作用"。
 */
export function effectVerdict(
  payload: ClaimTestPayload | null | undefined,
  direction: string | null | undefined,
): EffectVerdict {
  const effect = payload?.effect;
  const low = payload?.ci_low;
  const high = payload?.ci_high;

  if (typeof effect !== 'number') {
    return {
      text: '未记录',
      state: 'unrecorded',
      tone: 'muted',
      crossesZero: null,
      matchesDirection: null,
      reason: '该主张没有检验结果（未检验、或沙箱失败）',
    };
  }

  const hasCi = typeof low === 'number' && typeof high === 'number';
  const crossesZero = hasCi ? low <= 0 && high >= 0 : null;
  const expected = direction === '+' ? 1 : direction === '-' ? -1 : 0;
  const matchesDirection =
    expected === 0 ? null : Math.sign(effect) === expected;

  const ciText = hasCi
    ? ` [${(low as number).toFixed(4)}, ${(high as number).toFixed(4)}]`
    : '（无置信区间）';

  let tone: CardTone = 'neutral';
  let reason: string;
  if (crossesZero === true) {
    tone = 'muted';
    reason = '95% 置信区间跨 0，这个效应不能当作证据';
  } else if (crossesZero === false && matchesDirection === false) {
    tone = 'warning';
    reason = '置信区间不跨 0，但方向与预注册相反';
  } else if (crossesZero === false) {
    tone = 'positive';
    reason = '置信区间不跨 0，效应方向与预注册一致';
  } else {
    reason = '没有置信区间，只能看到点估计，无法判断显著性';
  }

  return {
    text: `effect ${effect >= 0 ? '+' : ''}${effect.toFixed(4)}${ciText}`,
    state: 'recorded',
    tone,
    crossesZero,
    matchesDirection,
    reason,
  };
}

/** `p` / `e` / 样本量 —— 检验的"体检数字"，单独一行。 */
export function testStatistics(payload: ClaimTestPayload | null | undefined): FieldView {
  if (!payload) {
    return { state: 'unrecorded', text: '未记录', tone: 'muted' };
  }
  const parts: string[] = [];
  if (typeof payload.n === 'number') {
    const pos = typeof payload.n_pos === 'number' ? payload.n_pos : '?';
    const neg = typeof payload.n_neg === 'number' ? payload.n_neg : '?';
    parts.push(`n=${payload.n}（${pos}+ / ${neg}-）`);
  }
  if (typeof payload.p === 'number') parts.push(`p=${payload.p.toFixed(4)}`);
  if (typeof payload.e === 'number') parts.push(`e=${payload.e.toFixed(3)}`);
  if (typeof payload.split === 'string' && payload.split) parts.push(`划分=${payload.split}`);
  if (parts.length === 0) {
    return { state: 'unrecorded', text: '未记录', tone: 'muted' };
  }
  return { state: 'recorded', text: parts.join(' · '), tone: 'neutral' };
}

// --------------------------------------------------------------------------
// sandbox failure（TODO 6.2「sandbox error」）
// --------------------------------------------------------------------------

export interface SandboxFailure {
  claimId: string;
  /** 错误摘要；没有就报「未记录」，不编。 */
  detail: FieldView;
  reason: string;
}

/**
 * 从一条 claim 行里取沙箱失败信息。
 *
 * 引擎在沙箱失败时写 `status='sandbox_failed'` 并把 payload 换成
 * `{"error": ...}`，所以错误文本就在 payload 的 `error` 键上。事件流里
 * 另有 `error_type` / `stage` / `duration_s`，但那些不在这个接口的数据里 ——
 * 本函数只报它**真的拿到了**的东西。
 */
export function sandboxFailure(claim: ClaimRowFields): SandboxFailure | null {
  if (claim.status !== 'sandbox_failed') return null;
  const claimId = String(claim.id ?? '');
  const raw = claim.error;
  const detail: FieldView =
    typeof raw === 'string' && raw.trim() !== ''
      ? { state: 'recorded', text: raw.trim(), tone: 'warning' }
      : {
          state: 'unrecorded',
          text: '未记录',
          tone: 'warning',
        };
  return {
    claimId,
    detail,
    reason:
      detail.state === 'unrecorded'
        ? '状态是沙箱失败，但错误详情没有写进这份数据'
        : '特征脚本在沙箱里失败，主张未被检验',
  };
}

// --------------------------------------------------------------------------
// 一行现象（把三个源拼起来）
// --------------------------------------------------------------------------

/** `discovery/phenomena.json` 的条目形状在 `types.ts` 里定义，这里只是别名。 */
export type PhenomenonEntry = PhenomenonEntryPayload;

export interface PhenomenonRow {
  claimId: string;
  /** 主张标题；散文被覆盖时是显式「未记录」而不是空。 */
  title: FieldView;
  condition: FieldView;
  feature: FieldView;
  outcome: FieldView;
  scope: FieldView;
  falsifier: FieldView;
  /** 该行有 claim 行吗 —— 没有就是"现象记了但主张行丢了"。 */
  hasClaimRow: boolean;
  grade: ReturnType<typeof gradeVerdict>;
  status: ReturnType<typeof claimStatusView>;
  effect: EffectVerdict;
  statistics: FieldView;
  sandbox: SandboxFailure | null;
}

/** 散文缺失时的原因（区分"被覆盖"与"本来就没这一步"）。 */
const PROSE_LOST_AFTER_GRADING =
  '评分时该主张的 payload 被检验结果覆盖，散文已不可得（引擎覆盖式写入，非本页缺陷）';

/** 从 `discovery.claims` 建 id → 该行 的索引。重复 id 时**保留第一条**。 */
export function claimsById(claims: ClaimRowFields[]): Map<string, ClaimRowFields> {
  const index = new Map<string, ClaimRowFields>();
  for (const claim of claims) {
    const id = claim.id;
    if (typeof id === 'string' && id && !index.has(id)) {
      index.set(id, claim);
    }
  }
  return index;
}

/** 从一个 claim 行里取一段散文 → 三态视图。 */
function proseOf(claim: ClaimRowFields | undefined, key: keyof ClaimRowFields): FieldView {
  if (!claim) {
    return { state: 'unrecorded', text: '未记录', tone: 'muted' };
  }
  const value = claim[key];
  if (typeof value !== 'string' || value === '') {
    return { state: 'unrecorded', text: '未记录', tone: 'muted' };
  }
  return presentValue(value);
}

/**
 * 把 `phenomena` 的每条与 `claims` 的那行拼成一行视图。
 *
 * `phenomena` 提供 effect/CI，`claims` 提供散文与 status。「现象有、claim 行
 * 没有」是一种真实可能（claim 表被清过、或 bundle 只拷了 discovery 目录），
 * `hasClaimRow` 把它暴露出来，UI 可以据此提示数据不完整。
 */
export function buildPhenomenonRow(
  entry: PhenomenonEntry,
  index: Map<string, ClaimRowFields>,
): PhenomenonRow {
  const claimId = typeof entry.claim_id === 'string' ? entry.claim_id : '';
  const claim = index.get(claimId);
  const status = claimStatusView(
    typeof claim?.status === 'string' ? claim.status : undefined,
  );
  const direction = typeof claim?.direction === 'string' ? claim.direction : undefined;

  // 散文整体缺失时，把原因写进标题的 tone 之外的说明位（由页面展示）
  const title = proseOf(claim, 'title');
  if (title.state === 'unrecorded' && status.key === 'graded') {
    title.tone = 'muted';
  }

  return {
    claimId,
    title,
    condition: proseOf(claim, 'condition'),
    feature: proseOf(claim, 'feature_code'),
    outcome: proseOf(claim, 'outcome'),
    scope: proseOf(claim, 'scope'),
    falsifier: proseOf(claim, 'falsifier'),
    hasClaimRow: claim !== undefined,
    grade: gradeVerdict(
      typeof entry.grade === 'string'
        ? entry.grade
        : typeof claim?.grade === 'string'
          ? claim.grade
          : undefined,
    ),
    status,
    effect: effectVerdict(entry.payload, direction),
    statistics: testStatistics(entry.payload),
    sandbox: claim ? sandboxFailure(claim) : null,
  };
}

/** 整页的行 + 汇总。 */
export interface PhenomenaView {
  rows: PhenomenonRow[];
  /** 有多少行的散文被覆盖掉了 —— 决定是否显示那条解释横幅。 */
  proseLostCount: number;
  /** 有多少现象找不到对应的 claim 行。 */
  orphanCount: number;
  sandboxFailedCount: number;
  /** discovery 是否根本没启用。 */
  enabled: boolean | null;
  /** `phenomena_state`：`available`（文件在，可能空）/ `missing`（没这个文件）。 */
  phenomenaState: string | undefined;
}

export function buildPhenomenaView(discovery: DiscoveryResponse): PhenomenaView {
  const index = claimsById(discovery.claims ?? []);
  const rows = (discovery.phenomena ?? []).map((entry) =>
    buildPhenomenonRow(entry, index),
  );

  const proseLostCount = rows.filter(
    (row) => row.title.state === 'unrecorded' && row.status.key === 'graded',
  ).length;
  const orphanCount = rows.filter((row) => !row.hasClaimRow).length;
  const sandboxFailedCount = (discovery.claims ?? []).filter(
    (claim) => claim.status === 'sandbox_failed',
  ).length;

  return {
    rows,
    proseLostCount,
    orphanCount,
    sandboxFailedCount,
    enabled: discovery.enabled ?? null,
    phenomenaState: discovery.phenomena_state,
  };
}

/**
 * 空状态的**原因**（TODO 6.4 测试要求「discovery disabled 空状态」）。
 *
 * 三种"空"要说三句不同的话：没启用 / 没这个文件 / 启用了但没现象。
 * 有行时返回 `null`（不需要空状态文案）。
 */
export function phenomenaEmptyReason(view: PhenomenaView): string | null {
  if (view.rows.length > 0) return null;
  if (view.enabled === false) {
    return '知识发现未启用，本次运行没有进行假设检验';
  }
  if (view.phenomenaState === 'missing') {
    return '这次运行的产出目录里没有现象文件（discovery/phenomena.json 不存在）';
  }
  return '知识发现已启用，但本次运行没有产生任何现象记录';
}

/** 散文被覆盖时的解释文案（页面横幅用）。 */
export function proseLossNote(view: PhenomenaView): string | null {
  if (view.proseLostCount === 0) return null;
  return `${view.proseLostCount} 条主张的散文未记录 —— ${PROSE_LOST_AFTER_GRADING}`;
}

/** 沙箱失败横幅：即使没有 phenomena 行，失败本身也要被看见。 */
export function sandboxNote(view: PhenomenaView): string | null {
  if (view.sandboxFailedCount === 0) return null;
  return `有 ${view.sandboxFailedCount} 条主张在沙箱里执行失败，这些主张未被检验`;
}

export { PROSE_LOST_AFTER_GRADING };
