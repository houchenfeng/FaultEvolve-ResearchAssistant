/**
 * 现象层与机制辩论赛的推导逻辑（PRD 12.3–12.5 / TODO 6.2–6.3）。
 *
 * 这一层的处境和知识卡完全不同，必须先说清楚，否则后面的取舍看起来像偷懒：
 *
 * `DiscoveryResponse` 的六个列表在契约里全是 `list[dict[str, Any]]`
 * （TS 侧 `Array<{[key: string]: unknown}>`），**没有任何字段保证**。它们的真实形状
 * 只能从写入方读出来：
 *
 * - `phenomena[]` = `{claim_id, grade, payload}`，`payload` 是 `ClaimTestResult.model_dump()`
 *   的 15 个键（`discovery/pipeline.py:227,303`；`discovery/schemas.py:43-58`）；
 * - `preregistration[]` = `{claim_id, hash}`，只有这两项（`pipeline.py:152`）；
 * - `controls[]` = `ControlReport.model_dump()`（`schemas.py:61-66`）；
 * - `certificates[]` = `Certificate.model_dump()`（`schemas.py:122-132`）；
 * - `theories[]` **恒为空**：`discovery/certificates.py:49-50` 无条件 `json.dump([], f)`，
 *   仓库里也不存在任何 theory schema；
 * - `matches[]` **恒为空**：`replay_service.py:1453-1468` 的构造器从不传 `matches=`。
 *   `MatchResult`（`schemas.py:105-119`）只写进 SQLite，没有任何端点读它。
 *
 * 所以本文件里每个读取器都容错，但**绝不补默认值冒充数据**：读不到就是「未记录」。
 * 这与 PRD §2.3 是同一条纪律——未知不等于零，未定不等于否证。
 */
import type { BadgeTone } from '@/components/ui/StatusBadge';
import type { EventResponse, RunDiscoveryResponse } from '@/generated/api';

import { NOT_RECORDED, type Cell } from '@/features/discovery/card-logic';

// --------------------------------------------------------------------------
// 判级词汇
// --------------------------------------------------------------------------

/**
 * `Grade` 枚举有**五个**值（`discovery/schemas.py:14-19`），比 PRD 12.3 列的四个
 * 多一个 `discovered`。多出来的这个不能丢，也不能并进 `confirmed`——
 * 「新发现」和「已确认」在证据强度上是两回事，合并就等于替后端下结论。
 */
export const GRADES = [
  'confirmed',
  'revised',
  'discovered',
  'refuted',
  'undetermined',
] as const;

export type GradeValue = (typeof GRADES)[number];

export function isGrade(value: unknown): value is GradeValue {
  return typeof value === 'string' && (GRADES as readonly string[]).includes(value);
}

export const GRADE_LABEL: Record<GradeValue, string> = {
  confirmed: '已确认',
  revised: '已修正',
  discovered: '新发现',
  refuted: '已否证',
  undetermined: '未定',
};

export const GRADE_TONE: Record<GradeValue, BadgeTone> = {
  confirmed: 'success',
  revised: 'info',
  discovered: 'brand',
  refuted: 'danger',
  // 「未定」用中性色：它不是失败，PRD §2.3 明确要求未定不得当成否证。
  undetermined: 'neutral',
};

// --------------------------------------------------------------------------
// 原始读取器
// --------------------------------------------------------------------------

type Raw = Record<string, unknown>;

function asRaw(value: unknown): Raw {
  return value && typeof value === 'object' && !Array.isArray(value) ? (value as Raw) : {};
}

function num(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function bool(value: unknown): boolean | null {
  return typeof value === 'boolean' ? value : null;
}

function str(value: unknown): string | null {
  return typeof value === 'string' && value.length > 0 ? value : null;
}

export function countCellOf(value: unknown): Cell {
  const n = num(value);
  return n == null
    ? { value: NOT_RECORDED, recorded: false }
    : { value: String(n), recorded: true };
}

/** 统计量统一四位小数：p 值可能远小于 0.001，三位会被截成 0.000 而失去信息。 */
export function statCell(value: unknown, digits = 4): Cell {
  const n = num(value);
  return n == null
    ? { value: NOT_RECORDED, recorded: false }
    : { value: n.toFixed(digits), recorded: true };
}

/** 三值布尔：是 / 否 / 未记录。绝不能把 null 折成「否」。 */
export function flagCell(value: unknown): Cell {
  const b = bool(value);
  if (b == null) return { value: NOT_RECORDED, recorded: false };
  return { value: b ? '是' : '否', recorded: true };
}

// --------------------------------------------------------------------------
// 现象层（PRD 12.3）
// --------------------------------------------------------------------------

export interface PhenomenonRow {
  claimId: string;
  /** 判级；契约外的字符串落在 `rawGrade`，此处为 null。 */
  grade: GradeValue | null;
  /** 后端给的原始判级字符串，原样保留以便回显未知值。 */
  rawGrade: string | null;
  split: Cell;
  n: Cell;
  nPos: Cell;
  nNeg: Cell;
  effect: Cell;
  ciLow: Cell;
  ciHigh: Cell;
  p: Cell;
  e: Cell;
  directionOk: Cell;
  temporalOk: Cell;
  rhoMaxAbs: Cell;
  incrGain: Cell;
  incrCiLow: Cell;
  incrCiHigh: Cell;
  /** 预注册哈希，来自 `preregistration.json` 按 claim_id 关联。 */
  preregHash: string | null;
}

export function buildPhenomenonRows(
  phenomena: Raw[] | undefined,
  preregistration: Raw[] | undefined,
): PhenomenonRow[] {
  const hashByClaim = new Map<string, string>();
  for (const item of preregistration ?? []) {
    const raw = asRaw(item);
    const claimId = str(raw.claim_id);
    const hash = str(raw.hash);
    if (claimId && hash) hashByClaim.set(claimId, hash);
  }

  return (phenomena ?? []).map((item) => {
    const raw = asRaw(item);
    const payload = asRaw(raw.payload);
    const claimId = str(raw.claim_id) ?? NOT_RECORDED;
    const rawGrade = str(raw.grade);
    return {
      claimId,
      grade: isGrade(rawGrade) ? rawGrade : null,
      rawGrade,
      split: { value: str(payload.split) ?? NOT_RECORDED, recorded: str(payload.split) != null },
      n: countCellOf(payload.n),
      nPos: countCellOf(payload.n_pos),
      nNeg: countCellOf(payload.n_neg),
      effect: statCell(payload.effect),
      ciLow: statCell(payload.ci_low),
      ciHigh: statCell(payload.ci_high),
      p: statCell(payload.p),
      e: statCell(payload.e),
      directionOk: flagCell(payload.direction_ok),
      temporalOk: flagCell(payload.temporal_ok),
      rhoMaxAbs: statCell(payload.rho_max_abs),
      incrGain: statCell(payload.incr_gain),
      incrCiLow: statCell(payload.incr_ci_low),
      incrCiHigh: statCell(payload.incr_ci_high),
      preregHash: hashByClaim.get(claimId) ?? null,
    };
  });
}

// --------------------------------------------------------------------------
// 沙箱与检验错误（PRD 12.3 最后一项）
// --------------------------------------------------------------------------

/**
 * 沙箱失败的 claim **不会**出现在 `phenomena.json` 里：`pipeline.py:174-178` 把
 * `{"error": ...}` 写进 SQLite 的 `claim.payload_json` 之后就 `continue` 了，
 * 从不进入检验与判级。所以错误只能从事件流拿。
 *
 * 事件流是可用且已脱敏的：`replay_service.py:990-1003` 对 payload 走
 * `sanitize_value`，且 `EVENT_TYPES` 只用于打 `is_known_type` 标记、**不做过滤**
 * （`catalog.py:41-43` 自己写明「未知类型也必须渲染」）。
 */
export interface SandboxFailure {
  claimId: string;
  errorType: string | null;
  error: string | null;
  stage: string | null;
}

export const SANDBOX_FAILED_EVENT = 'claim_sandbox_failed';

export function collectSandboxFailures(events: EventResponse[]): SandboxFailure[] {
  const failures: SandboxFailure[] = [];
  for (const event of events) {
    if (event.type !== SANDBOX_FAILED_EVENT) continue;
    const payload = asRaw(event.payload);
    failures.push({
      claimId: str(payload.claim_id) ?? NOT_RECORDED,
      errorType: str(payload.error_type),
      error: str(payload.error),
      stage: str(payload.stage),
    });
  }
  return failures;
}

/**
 * 把失败按 claim_id 分成两堆：
 * - `matched`：既失败又有检验结果的 claim（罕见，但两者不互斥，不能只留一边）；
 * - `untested`：失败了、因此**从未进入检验**的 claim。
 *
 * 分开是必须的。合成一张表会让「沙箱失败」看起来像一种判级结果，
 * 而 PRD §2.3 的纪律是：没跑成检验就没有结论，不能与「未定」混为一谈。
 */
export function partitionSandboxFailures(
  rows: PhenomenonRow[],
  failures: SandboxFailure[],
): { matched: SandboxFailure[]; untested: SandboxFailure[] } {
  const tested = new Set(rows.map((row) => row.claimId));
  return {
    matched: failures.filter((failure) => tested.has(failure.claimId)),
    untested: failures.filter((failure) => !tested.has(failure.claimId)),
  };
}

// --------------------------------------------------------------------------
// 对照（负对照与植入信号回收）
// --------------------------------------------------------------------------

export interface ControlRow {
  negTrials: Cell;
  negFalsePositives: Cell;
  negFpr: Cell;
  /** `planted` 是 `{名称: {trials, recovered}}`；回收率由后端给，前端不重算。 */
  planted: { name: string; trials: number | null; recovered: number | null }[];
  passed: Cell;
}

export function buildControlRows(controls: Raw[] | undefined): ControlRow[] {
  return (controls ?? []).map((item) => {
    const raw = asRaw(item);
    const plantedRaw = asRaw(raw.planted);
    const planted = Object.keys(plantedRaw)
      .sort()
      .map((name) => {
        const entry = asRaw(plantedRaw[name]);
        return {
          name,
          trials: num(entry.trials),
          recovered: num(entry.recovered),
        };
      });
    return {
      negTrials: countCellOf(raw.neg_trials),
      negFalsePositives: countCellOf(raw.neg_false_positives),
      negFpr: statCell(raw.neg_fpr),
      planted,
      passed: flagCell(raw.passed),
    };
  });
}

// --------------------------------------------------------------------------
// 证书（PRD 12.4 里唯一有据可查的部分）
// --------------------------------------------------------------------------

export interface CertificateRow {
  mechanismId: string;
  rivalId: string;
  testId: string;
  testType: Cell;
  env: Cell;
  stat: Cell;
  /** `Certificate.ci` 是二元组，落盘成 `[low, high]`。 */
  ciLow: Cell;
  ciHigh: Cell;
  eValue: Cell;
  preregHash: string | null;
  date: Cell;
}

export function buildCertificateRows(certificates: Raw[] | undefined): CertificateRow[] {
  return (certificates ?? []).map((item) => {
    const raw = asRaw(item);
    const ci = Array.isArray(raw.ci) ? raw.ci : [];
    return {
      mechanismId: str(raw.mechanism_id) ?? NOT_RECORDED,
      rivalId: str(raw.rival_id) ?? NOT_RECORDED,
      testId: str(raw.test_id) ?? NOT_RECORDED,
      testType: { value: str(raw.test_type) ?? NOT_RECORDED, recorded: str(raw.test_type) != null },
      env: { value: str(raw.env) ?? NOT_RECORDED, recorded: str(raw.env) != null },
      stat: statCell(raw.stat),
      ciLow: statCell(ci[0]),
      ciHigh: statCell(ci[1]),
      eValue: statCell(raw.e_value),
      preregHash: str(raw.prereg_hash),
      date: { value: str(raw.date) ?? NOT_RECORDED, recorded: str(raw.date) != null },
    };
  });
}

// --------------------------------------------------------------------------
// 辩论赛计数（来自 run_summary，不是 discovery 制品）
// --------------------------------------------------------------------------

export interface CounterRow {
  label: string;
  cell: Cell;
}

/**
 * PRD 12.4 要的「对阵关系 / 判别检验 / 比赛结果」是**逐场**数据，契约里没有；
 * 但 `RunDiscoveryResponse` 有一组**计数**是真的（`contracts.py:573-611`）。
 *
 * 展示计数而不展示逐场明细，是这一节能做到的上限。关键红线：
 * `decisive_matches` 是「有多少场判出了胜负」的**数量**，不是「谁赢了」。
 * 前端绝不用它反推一个胜者——PRD 12.4 写明胜负只能由预注册检验与
 * evaluator/统计证据决定，而逐场证据没有暴露出来。
 */
export function tournamentCounterRows(discovery: RunDiscoveryResponse | null): CounterRow[] {
  return [
    { label: '辩论轮数', cell: countCellOf(discovery?.tournament_rounds) },
    { label: '已进行对阵', cell: countCellOf(discovery?.matches_played) },
    { label: '判出胜负的对阵', cell: countCellOf(discovery?.decisive_matches) },
    { label: '功效不足的平局', cell: countCellOf(discovery?.underpowered_draws) },
    { label: '签发的证书', cell: countCellOf(discovery?.certificates_issued) },
    { label: '最小可检测效应', cell: statCell(discovery?.min_detectable_effect) },
  ];
}

export function mechanismCounterRows(discovery: RunDiscoveryResponse | null): CounterRow[] {
  return [
    { label: '提出的机制', cell: countCellOf(discovery?.mechanisms_proposed) },
    { label: '确立的机制', cell: countCellOf(discovery?.mechanisms_established) },
    { label: '被否证的机制', cell: countCellOf(discovery?.mechanisms_refuted) },
    { label: '机制修补次数', cell: countCellOf(discovery?.mechanism_patches) },
    { label: '机制卡数量', cell: countCellOf(discovery?.mechanism_cards_count) },
  ];
}

/**
 * 这三项是**方法学校验**，不是演化成绩：植入机制能否被回收、LLM 排序与数据排序
 * 是否一致、打乱环境后是否还会误通过。它们恰好是 PRD 12.4「跨环境不变性」
 * 在契约里唯一真实存在的投影，所以单独一组，避免和上面的调度计数混读。
 */
export function validityCounterRows(discovery: RunDiscoveryResponse | null): CounterRow[] {
  return [
    { label: '植入机制回收率', cell: statCell(discovery?.planted_mechanism_recovered) },
    { label: 'LLM 与数据的 Kendall τ', cell: statCell(discovery?.llm_vs_data_kendall_tau) },
    { label: '打乱环境后的误通过率', cell: statCell(discovery?.shuffled_env_false_pass) },
    { label: '负对照假阳性数', cell: countCellOf(discovery?.neg_control_false_positives) },
    { label: '负对照 FPR', cell: statCell(discovery?.neg_control_fpr) },
  ];
}

// --------------------------------------------------------------------------
// 空结果解释（PRD 12.1）
// --------------------------------------------------------------------------

export interface DiscoveryEmptyState {
  title: string;
  reason: string;
  nextStep: string;
}

/**
 * `enabled` 是「运行目录下有没有 `discovery/`」（`replay_service.py:1461`），
 * `*_state` 才区分「文件没写过」（missing）与「写过但是空的」（available + []）。
 *
 * 这两件事必须分开说。`_read_json_list` 的注释写得很清楚：引擎用 `[]` 表示
 * 「跑了但什么都没发现」，那是 available，不是 missing。把后者说成「没开启知识发现」
 * 会让用户以为改个配置重跑就有了，而真相是跑了并且一无所获。
 */
export function discoveryEmptyState(
  enabled: boolean | null | undefined,
  state: string | undefined,
  what: string,
): DiscoveryEmptyState {
  if (enabled === false) {
    return {
      title: `这次运行没有开启知识发现`,
      reason: `运行目录下没有 discovery/ 制品，因此没有${what}。这是配置选择，不是失败。`,
      nextStep: '若要看到发现结果，需要在运行配置里启用 discovery.enabled，再重跑一次。',
    };
  }
  if (state === 'missing') {
    return {
      title: `没有写出${what}文件`,
      reason: `discovery/ 目录存在，但${what}对应的 JSON 文件从未被写出。可能是这一轮在写盘前就中止了。`,
      nextStep: '到「代际时间轴」查看 discovery_round_* 与 claim_* 事件，确认流水线走到哪一步。',
    };
  }
  return {
    title: `${what}为空`,
    reason: `文件存在且可解析，内容就是空列表 []。按 discovery/pipeline.py 的写法，这表示流水线跑完了但没有产出${what}——是真实的空结果，不是读取失败。`,
    nextStep: '若与预期不符，检查 discovery.tournament.enabled 与沙箱是否大量失败（见本页「沙箱失败」一节）。',
  };
}

