/**
 * discovery 各产物的**实名**类型（阶段 6 共用）。
 *
 * ## 为什么要有这一层
 *
 * 契约里 `phenomena` / `claims` / `theories` / `matches` / `certificates` 都是
 * `list[dict[str, Any]]` —— 服务端故意开放（引擎的产物 schema 会演进），
 * 生成的 TS 类型因此是 `Array<{[key: string]: unknown}>`，前端拿不到任何字段名。
 *
 * 但字段明明存在，而且**在引擎侧有明确的数据类**：
 * `discovery/schemas.py` 的 `Claim` / `ClaimTestResult` / `Mechanism` /
 * `MatchResult` / `Certificate`。本文件把它们抄成 TS 类型，作为前端的显示契约。
 *
 * **抄的规则**：字段名与可空性和 `discovery/schemas.py` 逐字一致（含 `Literal`
 * 与 `Enum` 的取值）。凡是不确定的一律标成可选 —— 因为服务端确实可能给出
 * 比这里更少的东西（payload 会被覆盖，见 `claim-logic.ts`）。
 */
import type { ArtifactState, DiscoveryResponse as GeneratedDiscoveryResponse } from '@/generated/api';

// --------------------------------------------------------------------------
// discovery/schemas.py::ClaimTestResult
// --------------------------------------------------------------------------

/** 一次假设检验的结果。`phenomena[].payload` 就是这个形状。 */
export interface ClaimTestPayload {
  split?: string;
  n?: number;
  n_pos?: number;
  n_neg?: number;
  effect?: number;
  ci_low?: number;
  ci_high?: number;
  p?: number;
  /** e-value。 */
  e?: number;
  direction_ok?: boolean;
  temporal_ok?: boolean | null;
  rho_max_abs?: number | null;
  incr_gain?: number | null;
  incr_ci_low?: number | null;
  incr_ci_high?: number | null;
  /** 评分阶段会被追加进 payload（`pipeline.py` 的 `{**payload, "grade": ...}`）。 */
  grade?: string;
}

// --------------------------------------------------------------------------
// discovery/schemas.py::Claim
// --------------------------------------------------------------------------

/** 一条预注册主张。**只有未评分/未沙箱失败时** payload 才保留这些散文。 */
export interface ClaimPayload {
  id?: string;
  experiment_id?: string;
  origin_node_id?: string;
  source?: 'insight' | 'top_node' | 'discover_op' | string;
  title?: string;
  condition?: string;
  feature_code?: string;
  outcome?: string;
  direction?: '+' | '-' | string;
  scope?: string;
  falsifier?: string;
  category?: string;
  tags?: string[];
  prereg_hash?: string;
  status?: string;
  grade?: string | null;
  confirms?: string | null;
  revises?: string | null;
}

/** `claim` 表的镜像列 —— 与 payload 合并后一并交到前端。 */
export interface ClaimRowFields extends ClaimPayload {
  round?: number;
  created_at?: string;
  payload_json?: string;
  /** 沙箱失败时 payload 只剩这个键。 */
  error?: string;
}

// --------------------------------------------------------------------------
// discovery/schemas.py::Mechanism
// --------------------------------------------------------------------------

export type MechanismRoleKey =
  | 'claim'
  | 'llm_rival'
  | 'confound'
  | 'artifact'
  | 'censor'
  | 'other';

export type MechanismStatusKey = 'proposed' | 'established' | 'refuted' | 'undetermined';

/** 一条机制假设。`theories[]` 的元素（契约名 theories，引擎名 Mechanism）。 */
export interface MechanismPayload {
  id?: string;
  claim_id?: string;
  role?: MechanismRoleKey | string;
  title?: string;
  nodes?: string[];
  edges?: [string, string, '+' | '-'][];
  predictions?: Record<string, 1 | -1>;
  patch_count?: number;
  status?: MechanismStatusKey | string;
  parent_id?: string | null;
  /** `mechanism` 表的镜像列。 */
  family_id?: string;
}

// --------------------------------------------------------------------------
// discovery/schemas.py::MatchResult
// --------------------------------------------------------------------------

/** 一场机制辩论的结果。`matches[]` 的元素。 */
export interface MatchPayload {
  mech_a?: string;
  mech_b?: string;
  test_type?: string;
  test_id?: string;
  slice_id?: string;
  stat?: number;
  ci_low?: number;
  ci_high?: number;
  p?: number;
  e_raw?: number;
  log_bf_trunc?: number;
  /** `"a"` / `"b"` / `"none"` —— 注意不是机制 id。 */
  supports?: 'a' | 'b' | 'none' | string;
  decisive?: boolean;
  min_detectable?: number | null;
  /** `match` 表的镜像列。 */
  family_id?: string;
  round?: number;
}

// --------------------------------------------------------------------------
// discovery/schemas.py::Certificate
// --------------------------------------------------------------------------

/** 一张"某机制胜过某对手"的证书。`certificates[]` 的元素。 */
export interface CertificatePayload {
  mechanism_id?: string;
  rival_id?: string;
  test_id?: string;
  test_type?: string;
  env?: string;
  stat?: number;
  ci?: [number, number];
  e_value?: number;
  prereg_hash?: string;
  date?: string;
}

// --------------------------------------------------------------------------
// discovery/schemas.py::ControlReport
// --------------------------------------------------------------------------

/** 一次阴性对照的报告。`controls[]` 的元素。 */
export interface ControlReportPayload {
  neg_trials?: number;
  neg_false_positives?: number;
  neg_fpr?: number;
  /** 植入效应按名字分组的恢复率。 */
  planted?: Record<string, Record<string, number>>;
  passed?: boolean;
}

// --------------------------------------------------------------------------
// 接口响应（把开放字典换成上面的实名类型）
// --------------------------------------------------------------------------

/**
 * `/runs/{id}/discovery` 的响应，开放字典已实名化。
 *
 * 用 `Omit` 覆盖而不是重定义，是为了让生成层新增的字段（比如以后的
 * `preregistration_v2`）**自动透传**，不必来改这里；只有我们要给它类型的
 * 那几个字段被替换。
 */
export interface DiscoveryResponse
  extends Omit<
    GeneratedDiscoveryResponse,
    'phenomena' | 'claims' | 'theories' | 'matches' | 'certificates' | 'controls'
  > {
  phenomena?: PhenomenonEntryPayload[];
  claims?: ClaimRowFields[];
  theories?: MechanismPayload[];
  matches?: MatchPayload[];
  certificates?: CertificatePayload[];
  controls?: ControlReportPayload[];
}

/** `discovery/phenomena.json` 的条目 —— 三键，就这三个。 */
export interface PhenomenonEntryPayload {
  claim_id?: string;
  grade?: string;
  payload?: ClaimTestPayload;
}

/** 产物状态的三态（与契约 `ArtifactState` 同源）。 */
export type DiscoveryArtifactState = ArtifactState;

/** 空列表 + state 的通用读取结果，供各页面统一渲染"空但有表 / 表都没有"。 */
export interface SourcedList<T> {
  items: T[];
  state: DiscoveryArtifactState | undefined;
}
