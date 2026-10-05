/**
 * 结果页的读数逻辑（TODO 6.4）。
 *
 * TODO 6.4 要展示：初始/最佳/提升、分项指标、Top-K、运行波动和诚实提示、
 * 数据边界审计、制品下载。本模块只做纯计算，所有数字**直接来自 API DTO**
 * （PRD 原话），不在这里重新算任何评测量。
 *
 * ## 三条容易写错的地方，本模块专门处理
 *
 * 1. **提升的方向**。`TaskCardMetrics.target_direction` 可能是 `lower`
 *    （某些数据集越小越好）。`improvement` 直接取得还好，凡是要自己比大小
 *    的地方都必须按方向取号，否则"越优越负"。
 * 2. **波动区间**。`|提升| ≤ 噪声带` 时必须说「未形成明确改进证据」，
 *    不能报一个带正号的提升幅度 —— 那是把噪声当成果（TODO 5.4 的同一原则）。
 * 3. **下载只能凭服务端铸的 id**。绝不接受路径、绝不由用户输入拼 URL。
 *    `ArtifactResponse.downloadable === false` 的制品（数据库、日志）不提供
 *    下载入口；`holdout` / `eval_only` 一类名字一律拒绝，即使有人手工传进来。
 */
import type { ArtifactState, ReportFileResponse } from '@/generated/api';
import { presentValue, type CardTone, type FieldView } from '@/features/discovery/card-logic';

// --------------------------------------------------------------------------
// 初始 / 最佳 / 提升（TODO 6.4 第一条）
// --------------------------------------------------------------------------

/** `TaskCardMetrics.target_direction` 的两种取值；默认 `higher`。 */
export type TargetDirection = 'higher' | 'lower';

export function normalizeDirection(direction: string | null | undefined): TargetDirection {
  return direction === 'lower' ? 'lower' : 'higher';
}

export interface HeadlineNumbers {
  initial: FieldView;
  best: FieldView;
  improvement: FieldView;
  direction: TargetDirection;
  /** 最佳是否真的优于初始（按方向判断）。没有双侧数字时为 `null`。 */
  improved: boolean | null;
}

/**
 * 初始/最佳/提升三个数字。
 *
 * `improvement` 优先用 DTO 给的值（那是评测器算的）；只有在它缺失而初始/最佳
 * 都在时才自己减 —— 并且按方向取号，因为"提升"在 `lower` 任务里是 `初始-最佳`。
 */
export function headlineNumbers(
  initial: number | null | undefined,
  best: number | null | undefined,
  improvement: number | null | undefined,
  direction: string | null | undefined,
): HeadlineNumbers {
  const dir = normalizeDirection(direction);
  const hasPair = typeof initial === 'number' && typeof best === 'number';

  let derived = improvement;
  if ((derived === null || derived === undefined) && hasPair) {
    derived = dir === 'lower' ? (initial as number) - (best as number) : (best as number) - (initial as number);
  }

  return {
    initial: presentValue(initial, (v) => Number(v).toFixed(4)),
    best: presentValue(best, (v) => Number(v).toFixed(4)),
    improvement:
      derived === null || derived === undefined
        ? { state: 'unrecorded', text: '未记录', tone: 'muted' }
        : {
            state: 'recorded',
            text: `${derived >= 0 ? '+' : ''}${derived.toFixed(4)}`,
            // 无提升甚至倒退时不用绿色：颜色是结论，不是装饰
            tone: derived > 0 ? 'positive' : 'muted',
          },
    direction: dir,
    improved: typeof derived === 'number' ? derived > 0 : null,
  };
}

// --------------------------------------------------------------------------
// 运行波动与诚实提示（TODO 6.4 第四条）
// --------------------------------------------------------------------------

export interface NoiseVerdict {
  /** 是否落在噪声带内 —— `null` 表示带宽不可得，**不是**"落在带内"。 */
  withinBand: boolean | null;
  /** 必须显示的那句提示；无需提示时 `null`。 */
  note: string | null;
  tone: CardTone;
}

const NO_CLEAR_EVIDENCE = '未形成明确改进证据';

/**
 * 提升是否超出噪声带。
 *
 * 三条分支对应三种不同的话：
 * - 带宽可得且 `|Δ| ≤ 带宽` → **「未形成明确改进证据」**（PRD/TODO 硬要求）
 * - 带宽可得且超出 → 报超出
 * - 带宽不可得 → 说"无法判断"，**不**默认说"超出"
 */
export function noiseBandVerdict(
  improvement: number | null | undefined,
  noiseDelta: number | null | undefined,
): NoiseVerdict {
  if (improvement === null || improvement === undefined) {
    return { withinBand: null, note: null, tone: 'muted' };
  }
  if (noiseDelta === null || noiseDelta === undefined) {
    return {
      withinBand: null,
      note: `缺少噪声带估计，无法判断 +${improvement.toFixed(4)} 是否算真实改进`,
      tone: 'muted',
    };
  }
  const band = Math.abs(noiseDelta);
  if (Math.abs(improvement) <= band) {
    return {
      withinBand: true,
      note: `${NO_CLEAR_EVIDENCE}：提升 ${improvement >= 0 ? '+' : ''}${improvement.toFixed(4)} 落在运行波动 ±${band.toFixed(4)} 内`,
      tone: 'muted',
    };
  }
  return {
    withinBand: false,
    note: `提升 ${improvement >= 0 ? '+' : ''}${improvement.toFixed(4)} 超出运行波动 ±${band.toFixed(4)}`,
    tone: 'positive',
  };
}

/** 提示语常量，供测试与页面文案引用，避免两处各写一份。 */
export const NO_CLEAR_EVIDENCE_TEXT = NO_CLEAR_EVIDENCE;

// --------------------------------------------------------------------------
// 分项指标（TODO 6.4 第二条）
// --------------------------------------------------------------------------

export interface MetricRow {
  key: string;
  label: string;
  view: FieldView;
  /** 该指标是否可与其它运行横向比较（见 §多数据集）。 */
  comparable: boolean;
}

/**
 * 一次运行的分项指标。
 *
 * 只列 `RunOutcomeResponse` 里**确实存在**的字段 —— 不造"派生指标"，
 * 因为 TODO 6.4 明写"所有数字直接来自 API DTO"。
 */
export function metricRows(outcome: Record<string, unknown> | null | undefined): MetricRow[] {
  const rows: Array<{ key: string; label: string; format: (v: number | string) => string }> = [
    { key: 'iterations_done', label: '完成代数', format: (v) => String(v) },
    { key: 'iteration_events', label: '写码事件', format: (v) => String(v) },
    { key: 'valid_rate', label: '有效率', format: (v) => `${(Number(v) * 100).toFixed(1)}%` },
    { key: 'rounds_to_target', label: '达到目标轮次', format: (v) => String(v) },
    {
      key: 'time_to_target_s',
      label: '达到目标耗时',
      format: (v) => `${Number(v).toFixed(1)} s`,
    },
    { key: 'tokens_to_target', label: '达到目标 token', format: (v) => String(v) },
    { key: 'stop_reason', label: '停止原因', format: (v) => String(v) },
  ];

  return rows.map((row) => {
    const raw = outcome?.[row.key];
    const usable =
      typeof raw === 'number' || (typeof raw === 'string' && raw.trim() !== '');
    return {
      key: row.key,
      label: row.label,
      view: usable
        ? presentValue(raw as number | string, row.format)
        : { state: 'unrecorded' as const, text: '未记录', tone: 'muted' as const },
      comparable: usable,
    };
  });
}

// --------------------------------------------------------------------------
// Top-K（TODO 6.4 第三条）
// --------------------------------------------------------------------------

export interface LeaderboardLike {
  rank?: number;
  node_id: string;
  score?: number | null;
  is_best?: boolean;
  id?: string;
}

/**
 * 取前 K 名。
 *
 * 排序规则：**先按 `rank`（服务端已排好），没有 rank 才按分数降序**。
 * 不自己重排是因为节点分数可能相同而服务端用了稳定的次级规则，
 * 前端重排会让两个页面的名次不一致。
 */
export function topK<T extends LeaderboardLike>(entries: T[], k: number): T[] {
  if (k <= 0) return [];
  const hasRank = entries.every((entry) => typeof entry.rank === 'number');
  const ordered = hasRank
    ? [...entries].sort((a, b) => (a.rank as number) - (b.rank as number))
    : [...entries].sort((a, b) => (b.score ?? Number.NEGATIVE_INFINITY) - (a.score ?? Number.NEGATIVE_INFINITY));
  return ordered.slice(0, k);
}

// --------------------------------------------------------------------------
// 多数据集对比（TODO 6.4 测试要求：不可比较字段显示 N/A）
// --------------------------------------------------------------------------

export interface RunMetricSlice {
  /** 数据集 / 任务标识 —— 相同才可横向排名。 */
  datasetId: string;
  runId: string;
  outcome: Record<string, unknown> | null | undefined;
}

export interface ComparisonRow {
  key: string;
  label: string;
  /** 每个运行一格；缺的那个是 `null`（渲染成 N/A）。 */
  cells: FieldView[];
  /** 全部运行都有该指标才是 `true`；否则该行整体报 N/A。 */
  comparable: boolean;
  /** 不是所有运行都来自同一数据集。 */
  acrossDatasets: boolean;
}

export interface ComparisonTable {
  rows: ComparisonRow[];
  /** 是否可以横向排名（PRD 12.x：不同数据集之间**不可**直接排名）。 */
  rankable: boolean;
  /** 不可排名时的说明。 */
  note: string | null;
  datasetIds: string[];
}

const NA_VIEW: FieldView = { state: 'not_applicable', text: 'N/A', tone: 'muted' };

/**
 * 跨运行对比。
 *
 * PRD 12.x 的两条规矩都在这里落地：
 * - **只比较共有指标**：某个运行没有该指标时，整行标 N/A（不是显示 0）
 * - **不同数据集不可直接横向排名**：`datasetId` 不止一个时 `rankable=false`
 */
export function comparisonTable(slices: RunMetricSlice[]): ComparisonTable {
  if (slices.length === 0) {
    return { rows: [], rankable: false, note: '没有可对比的运行', datasetIds: [] };
  }

  const datasetIds = [...new Set(slices.map((slice) => slice.datasetId))];
  const acrossDatasets = datasetIds.length > 1;

  // 以第一次运行的指标集为基准，顺序稳定
  const template = metricRows(slices[0].outcome);
  const rows: ComparisonRow[] = template.map((row) => {
    const cells = slices.map((slice) => {
      const raw = slice.outcome?.[row.key];
      const usable =
        typeof raw === 'number' || (typeof raw === 'string' && raw.trim() !== '');
      if (!usable) return NA_VIEW;
      // 复用 metricRows 的格式化，避免两处话术不一致
      const same = metricRows(slice.outcome).find((candidate) => candidate.key === row.key);
      return same ? same.view : NA_VIEW;
    });
    // PRD 12.x：「只比较共有指标」。只要有一个运行缺该指标，整行就都不可比，
    // 因此**整行**显示 N/A —— 不是只把缺的那格打码，那会诱导读者拿剩下的
    // 数字横着比，而它们本来就不在同一口径上。
    const comparable = cells.every((cell) => cell.state === 'recorded');
    return {
      key: row.key,
      label: row.label,
      cells: comparable ? cells : cells.map(() => ({ ...NA_VIEW })),
      comparable,
      acrossDatasets,
    };
  });

  return {
    rows,
    rankable: !acrossDatasets,
    note: acrossDatasets
      ? `这 ${slices.length} 个运行来自 ${datasetIds.length} 个不同数据集（${datasetIds.join('、')}），只比较共有指标，任务之间不可直接横向排名`
      : null,
    datasetIds,
  };
}

// --------------------------------------------------------------------------
// 数据边界审计（TODO 6.4 第五条）
// --------------------------------------------------------------------------

export interface BoundaryRow {
  key: string;
  view: FieldView;
  /** 状态是否值得提醒（missing / invalid）。 */
  noteworthy: boolean;
}

const STATE_VIEWS: Record<ArtifactState, { text: string; tone: CardTone }> = {
  available: { text: '可读', tone: 'positive' },
  missing: { text: '不存在', tone: 'muted' },
  invalid: { text: '不可解析', tone: 'warning' },
};

/**
 * 数据边界审计：每个产物读到了什么。
 *
 * `available` 只说明**文件在**，不说明里面有数据 —— 实测 demo 就是
 * `available` + 0 行。所以这里只报"可读性"，数量由各自的页面负责。
 */
export function boundaryAudit(
  artifactStates: Record<string, ArtifactState> | null | undefined,
  warnings: { field?: string; reason?: string }[] | null | undefined,
): { rows: BoundaryRow[]; warnings: { field: string; reason: string }[]; hasIssues: boolean } {
  const rows: BoundaryRow[] = Object.entries(artifactStates ?? {})
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([key, state]) => {
      const known = STATE_VIEWS[state] ?? { text: String(state), tone: 'muted' as CardTone };
      return {
        key,
        view: { state: state === 'available' ? 'recorded' : 'unrecorded', text: known.text, tone: known.tone },
        noteworthy: state !== 'available',
      };
    });

  const contractWarnings = (warnings ?? []).map((warning) => ({
    field: warning.field ?? '',
    reason: warning.reason ?? '',
  }));

  return {
    rows,
    warnings: contractWarnings,
    hasIssues: rows.some((row) => row.noteworthy) || contractWarnings.length > 0,
  };
}

// --------------------------------------------------------------------------
// 制品下载（TODO 6.4 第六条 + 两条测试要求）
// --------------------------------------------------------------------------

/**
 * 服务端铸 id 的形状 —— 与 `webapi/paths.py` 的 `_ID_PATTERN` 逐字一致：
 * `^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$`，且不允许 `..`。
 *
 * 前端复刻这条规则的意义：**在请求发出前就拒掉不可能成功的输入**，
 * 这样任何用户可控的值都不可能变成路径的一部分。
 */
const ARTIFACT_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/;

/** 与 `common/codecheck.py` 的 `FORBIDDEN_PATTERNS["evaluator-only path"]` 同源。 */
const PROTECTED_NAME_PATTERN = /eval_only|holdout|val_labels|test_labels/i;

export type DownloadRefusalReason =
  | 'non_downloadable'
  | 'invalid_id'
  | 'protected_name'
  | 'not_available';

export interface DownloadRefusal {
  allowed: false;
  reason: DownloadRefusalReason;
  message: string;
}

export interface DownloadDescriptor {
  allowed: true;
  /** **只有这一种**构造方式：`/api/runs/{run_id}/artifacts/{artifact_id}`。 */
  url: string;
  /** 服务端给的显示名（只取 basename）。 */
  filename: string;
  mediaType: string;
  sizeBytes: number | null;
}

export type DownloadDecision = DownloadDescriptor | DownloadRefusal;

function refuse(reason: DownloadRefusalReason, message: string): DownloadRefusal {
  return { allowed: false, reason, message };
}

/** 服务端 `Content-Disposition` 只带 basename —— 前端也跟着只认 basename。 */
function basename(name: string): string {
  const parts = name.split(/[/\\]/);
  return parts[parts.length - 1] ?? name;
}

/**
 * 为一个制品生成下载描述。
 *
 * **拒绝的四种情况**（都会被显式说明，不是静默失败）：
 * 1. `downloadable === false` —— 数据库 / 日志这类引擎内部制品
 * 2. id 不符合服务端铸 id 形状 —— 含路径分隔符、`..`、盘符、超长
 * 3. id 命中受保护名字（`holdout` / `eval_only` / `val_labels` / `test_labels`）
 * 4. `state !== 'available'`
 *
 * 第 3 条是**纵深防御**：正常路径下这些名字根本不会出现在目录里（服务端只
 * 铸白名单 id），但既然前端是最后一道，就不该假设上游一定干净。
 */
export function downloadDescriptor(
  runId: string,
  file: {
    artifact_id: string;
    display_name: string;
    media_type: string;
    size_bytes?: number | null;
    state?: ArtifactState | null;
    downloadable?: boolean;
  },
): DownloadDecision {
  if (file.downloadable === false) {
    return refuse('non_downloadable', '该制品不开放下载（引擎内部产物）');
  }
  if (file.state && file.state !== 'available') {
    return refuse('not_available', `该制品当前不可用（${file.state}）`);
  }
  if (PROTECTED_NAME_PATTERN.test(file.artifact_id) || PROTECTED_NAME_PATTERN.test(file.display_name)) {
    return refuse('protected_name', '该制品属于评测保留区，任何情况下都不提供下载');
  }
  if (!ARTIFACT_ID_PATTERN.test(file.artifact_id) || file.artifact_id.includes('..')) {
    return refuse('invalid_id', '制品 id 不是服务端铸出的形状，已拒绝');
  }
  if (!runId) {
    return refuse('invalid_id', '缺少运行 id');
  }

  return {
    allowed: true,
    // 逐段编码：run_id 与 artifact_id 各自 encode，不拼裸字符串
    url: `/api/runs/${encodeURIComponent(runId)}/artifacts/${encodeURIComponent(file.artifact_id)}`,
    filename: basename(file.display_name) || file.artifact_id,
    mediaType: file.media_type || 'application/octet-stream',
    sizeBytes: typeof file.size_bytes === 'number' ? file.size_bytes : null,
  };
}

/** 报告清单里的文件都可下载（服务端只收 `kind === 'report'`）。 */
export function reportDownload(runId: string, file: ReportFileResponse): DownloadDecision {
  return downloadDescriptor(runId, { ...file, downloadable: true });
}

/** 人读的体积；不可得时给「未知」而不是 0 B。 */
export function formatBytes(bytes: number | null | undefined): FieldView {
  if (typeof bytes !== 'number') {
    return { state: 'unrecorded', text: '未知', tone: 'muted' };
  }
  if (bytes < 1024) return { state: 'recorded', text: `${bytes} B`, tone: 'neutral' };
  if (bytes < 1024 * 1024) return { state: 'recorded', text: `${(bytes / 1024).toFixed(1)} KB`, tone: 'neutral' };
  return { state: 'recorded', text: `${(bytes / 1024 / 1024).toFixed(2)} MB`, tone: 'neutral' };
}
