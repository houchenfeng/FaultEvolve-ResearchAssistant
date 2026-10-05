/**
 * 机制辩论赛的分区逻辑（TODO 6.3）。
 *
 * TODO 6.3 要求按六个阶段展示，并且**必须把 Qwen 论点与数据裁决分区显示**。
 * 两条要求落到数据上就是两件事：
 *
 * 1. **按 `Mechanism.role` 分区**。六个 role 取值
 *    （`claim` / `llm_rival` / `confound` / `artifact` / `censor` / `other`）
 *    恰好对应"谁是主张、谁是对手、谁是反驳"。
 * 2. **把"论点"和"裁决"分成两组**。论点由 LLM 生成（`llm_rival` 是它的产物，
 *    机制的 `title` 也是），裁决由数据给出（`matches[].supports` 与
 *    `certificates[]`）。混在一列里显示会让人分不清哪句是模型猜的、哪句是
 *    数据支持的 —— 这正是 PRD 那条"必须分区"的理由。
 *
 * ## 数据从哪来
 *
 * | 展示项 | 来源 |
 * |---|---|
 * | 主张 | `theories[]` 里 `role='claim'` |
 * | 对手机制 | `role='llm_rival'` |
 * | 正反论点 | `matches[].supports`（`'a'`/`'b'`/`'none'`）配 `decisive` |
 * | 预注册检验 | `Matches.test_type` + `certificates[].test_type` |
 * | 数据裁决 | `mechanisms[].status`（established/refuted/undetermined） |
 * | 证书/否证记忆 | `certificates[]` |
 *
 * ⚠️ `MatchResult.supports` 的取值是 **`'a'` / `'b'` / `'none'`**（哪一方赢），
 * 不是机制 id。把它当成 id 去查表会静默查空 —— 本模块用 `mech_a`/`mech_b`
 * 还原成机制 id 再说话。
 */
import type {
  CertificatePayload,
  DiscoveryResponse,
  MatchPayload,
  MechanismPayload,
  MechanismRoleKey,
} from '@/features/discovery/types';
import type { CardTone, FieldView } from '@/features/discovery/card-logic';

// --------------------------------------------------------------------------
// role 分区
// --------------------------------------------------------------------------

interface RoleVerdict {
  label: string;
  tone: CardTone;
  /** 这个 role 在辩论赛里的位置。 */
  stage: string;
}

/**
 * 六个 role 的显示名 —— 与 `discovery/schemas.py` 的 `MechanismRole` 逐字对应。
 *
 * 未知 role 不丢：`partitionMechanisms` 会把它收进 `other` 并保留原值，
 * 因为契约允许引擎加新 role，假装不认识会让机制凭空消失。
 */
const ROLE_VERDICTS: Record<MechanismRoleKey, RoleVerdict> = {
  claim: { label: '主张', tone: 'brand', stage: '1. 主张' },
  llm_rival: { label: '对手机制', tone: 'warning', stage: '2. 对手机制' },
  confound: { label: '混淆因素', tone: 'warning', stage: '3. 正反论点' },
  artifact: { label: '数据处理产物', tone: 'muted', stage: '3. 正反论点' },
  censor: { label: '随机性/审查项', tone: 'muted', stage: '3. 正反论点' },
  other: { label: '其他机制', tone: 'neutral', stage: '3. 正反论点' },
};

export function roleVerdict(role: string | null | undefined): RoleVerdict & {
  key: MechanismRoleKey | 'unknown';
} {
  if (role && role in ROLE_VERDICTS) {
    return { key: role as MechanismRoleKey, ...ROLE_VERDICTS[role as MechanismRoleKey] };
  }
  return {
    key: 'unknown',
    label: role ? `未识别机制（${role}）` : '未记录角色',
    tone: 'muted',
    stage: '3. 正反论点',
  };
}

/**
 * 机制状态 → 裁决用语。
 *
 * `status` 的四个取值与 `Mechanism.status` 的 `Literal` 一致。这里刻意不把
 * `proposed` 说成"未决" —— 它是"还没比"，与 `undetermined`（"比了但分不出"）
 * 是两件事。
 */
const STATUS_VERDICTS: Record<string, { label: string; tone: CardTone; reason: string }> = {
  proposed: { label: '待检验', tone: 'muted', reason: '已提出但尚未进入辩论' },
  established: { label: '数据支持', tone: 'positive', reason: '辩论中胜出，已发放证书' },
  refuted: { label: '数据否证', tone: 'warning', reason: '辩论中落败，记入否证记忆' },
  undetermined: { label: '证据不足', tone: 'neutral', reason: '打了但没分出胜负' },
};

export function mechanismStatusVerdict(status: string | null | undefined): {
  label: string;
  tone: CardTone;
  reason: string;
} {
  if (status && status in STATUS_VERDICTS) return STATUS_VERDICTS[status];
  return { label: status || '未记录', tone: 'muted', reason: '这一行没有可识别的状态' };
}

// --------------------------------------------------------------------------
// 集合分组
// --------------------------------------------------------------------------

export interface MechanismGroup {
  key: MechanismRoleKey | 'unknown';
  label: string;
  tone: CardTone;
  stage: string;
  items: MechanismPayload[];
}

export interface MechanismPartition {
  /** 按 role 分的组，顺序固定（claim → llm_rival → confound → … → unknown）。 */
  groups: MechanismGroup[];
  /** 主张单列，页面顶部显示。 */
  claim: MechanismPayload[];
  /** 对手与反驳（`llm_rival` / `confound` / `artifact` / `censor` / `other`）。 */
  rivals: MechanismPayload[];
  /** 已建立的机制数 —— 与 `run_summary.mechanisms_established` 应当吻合。 */
  establishedCount: number;
  refutedCount: number;
}

const ROLE_ORDER: (MechanismRoleKey | 'unknown')[] = [
  'claim',
  'llm_rival',
  'confound',
  'artifact',
  'censor',
  'other',
  'unknown',
];

/** unknown 组的标签：一种未知值就点名，多种就报个数（详见调用处注释）。 */
function unknownLabel(items: MechanismPayload[]): string {
  const raw = [
    ...new Set(
      items
        .map((item) => item.role)
        .filter((role): role is string => typeof role === 'string' && role !== ''),
    ),
  ];
  if (raw.length === 1) return `未识别机制（${raw[0]}）`;
  if (raw.length === 0) return '未记录角色';
  return `未识别机制（${raw.length} 种）`;
}

/**
 * 按 role 分组。
 *
 * 排序有意固定：分区的顺序就是 TODO 6.3 的阶段顺序，让每次渲染都稳定
 * （否则同一次运行的两次刷新可能给出不同的分组顺序）。
 */
export function partitionMechanisms(mechanisms: MechanismPayload[]): MechanismPartition {
  const buckets = new Map<MechanismRoleKey | 'unknown', MechanismPayload[]>();
  for (const mechanism of mechanisms) {
    const key = roleVerdict(mechanism.role).key;
    const bucket = buckets.get(key);
    if (bucket) bucket.push(mechanism);
    else buckets.set(key, [mechanism]);
  }

  const groups: MechanismGroup[] = [];
  for (const key of ROLE_ORDER) {
    const items = buckets.get(key);
    if (!items || items.length === 0) continue;
    const verdict = key === 'unknown' ? roleVerdict(undefined) : roleVerdict(key);
    groups.push({
      key,
      // unknown 组的标签带上**原始 role 值**：契约允许引擎加新 role，
      // 笼统写"未识别"会让新增的那一类彻底看不出来。只有一种未知值时报出
      // 它，多种时说不清是哪些，就报个数。
      label: key === 'unknown' ? unknownLabel(items) : verdict.label,
      tone: verdict.tone,
      stage: verdict.stage,
      items,
    });
  }

  const claim = buckets.get('claim') ?? [];
  const rivals = ROLE_ORDER.filter((key) => key !== 'claim')
    .flatMap((key) => buckets.get(key) ?? []);

  return {
    groups,
    claim,
    rivals,
    establishedCount: mechanisms.filter((m) => m.status === 'established').length,
    refutedCount: mechanisms.filter((m) => m.status === 'refuted').length,
  };
}

// --------------------------------------------------------------------------
// 正反论点（TODO 6.3「正反论点」）
// --------------------------------------------------------------------------

export type MatchOutcome = 'a_wins' | 'b_wins' | 'tie' | 'unknown';

export interface MatchVerdict {
  outcome: MatchOutcome;
  /** 胜方机制 id；平局/未知时为 `null`。 */
  winner: string | null;
  loser: string | null;
  label: string;
  tone: CardTone;
  reason: string;
  /** 是否分出胜负（`decisive`）。未分胜负的场次不能当证据。 */
  decisive: boolean;
  /** `stat` + `ci` 的可读串。 */
  statistics: FieldView;
}

/**
 * 一场辩论的裁决。
 *
 * **判定顺序**：`supports` 决定胜负 → `decisive` 决定它算不算证据 →
 * `stat`/`ci` 只是数字。反过来（先看数字大小）会把"统计上略胜但不显著"
 * 读成"赢了"。
 */
export function matchVerdict(match: MatchPayload): MatchVerdict {
  const a = typeof match.mech_a === 'string' ? match.mech_a : '';
  const b = typeof match.mech_b === 'string' ? match.mech_b : '';
  const decisive = match.decisive === true;

  const statistics: FieldView =
    typeof match.stat === 'number'
      ? {
          state: 'recorded',
          text: [
            `stat=${match.stat.toFixed(4)}`,
            typeof match.ci_low === 'number' && typeof match.ci_high === 'number'
              ? `[${match.ci_low.toFixed(4)}, ${match.ci_high.toFixed(4)}]`
              : null,
            typeof match.p === 'number' ? `p=${match.p.toFixed(4)}` : null,
            typeof match.e_raw === 'number' ? `e=${match.e_raw.toFixed(3)}` : null,
          ]
            .filter((part): part is string => part !== null)
            .join(' · '),
          tone: 'neutral',
        }
      : { state: 'unrecorded', text: '未记录', tone: 'muted' };

  if (match.supports === 'a') {
    return {
      outcome: 'a_wins',
      winner: a || null,
      loser: b || null,
      label: decisive ? 'a 方胜' : 'a 方略胜（未达决定）',
      tone: decisive ? 'positive' : 'muted',
      decisive,
      reason: decisive
        ? '胜负达到决定性阈值，可作为裁决依据'
        : '统计上偏向 a 方，但未达到决定性阈值，不能单独作为裁决依据',
      statistics,
    };
  }
  if (match.supports === 'b') {
    return {
      outcome: 'b_wins',
      winner: b || null,
      loser: a || null,
      label: decisive ? 'b 方胜' : 'b 方略胜（未达决定）',
      tone: decisive ? 'positive' : 'muted',
      decisive,
      reason: decisive
        ? '胜负达到决定性阈值，可作为裁决依据'
        : '统计上偏向 b 方，但未达到决定性阈值，不能单独作为裁决依据',
      statistics,
    };
  }
  if (match.supports === 'none') {
    return {
      outcome: 'tie',
      winner: null,
      loser: null,
      label: '未分胜负',
      tone: 'neutral',
      decisive: false,
      reason: '这一场两个机制都没有得到支持',
      statistics,
    };
  }
  return {
    outcome: 'unknown',
    winner: null,
    loser: null,
    label: '未记录裁决',
    tone: 'muted',
    decisive,
    reason: '这场的 supports 字段没有被记录，无法判断谁胜',
    statistics,
  };
}

/** 把 `supports` 的 `'a'`/`'b'` 还原成机制 id，供页面做高亮/跳转。 */
export function supportingMechanismId(match: MatchPayload): string | null {
  const verdict = matchVerdict(match);
  return verdict.winner;
}

/** 按家族（`family_id`）分组比赛 —— 一个家族是一次完整辩论。 */
export interface MatchFamily {
  familyId: string;
  matches: MatchPayload[];
  decisiveCount: number;
  /** 家族里被数据支持最多的机制 id；平手时 `null`。 */
  champion: string | null;
}

export function groupMatchesByFamily(matches: MatchPayload[]): MatchFamily[] {
  const buckets = new Map<string, MatchPayload[]>();
  for (const match of matches) {
    const family = typeof match.family_id === 'string' ? match.family_id : '';
    const bucket = buckets.get(family);
    if (bucket) bucket.push(match);
    else buckets.set(family, [match]);
  }

  const families: MatchFamily[] = [];
  for (const [familyId, items] of buckets) {
    const wins = new Map<string, number>();
    let decisiveCount = 0;
    for (const match of items) {
      const verdict = matchVerdict(match);
      if (verdict.decisive) decisiveCount += 1;
      if (verdict.winner) wins.set(verdict.winner, (wins.get(verdict.winner) ?? 0) + 1);
    }

    let champion: string | null = null;
    let best = 0;
    let tied = false;
    for (const [id, count] of wins) {
      if (count > best) {
        best = count;
        champion = id;
        tied = false;
      } else if (count === best) {
        // 并列第一 ⇒ 没有唯一冠军，宁可报 null 也不随便挑一个
        tied = true;
      }
    }
    families.push({
      familyId,
      matches: items,
      decisiveCount,
      champion: tied ? null : champion,
    });
  }
  return families;
}

// --------------------------------------------------------------------------
// 证书 / 否证记忆（TODO 6.3「证书/否证记忆」）
// --------------------------------------------------------------------------

export interface CertificateView {
  mechanismId: string;
  rivalId: string;
  /** `机制 A 胜过 机制 B` 这类一句话。 */
  headline: string;
  /** `e_value` 的解读 —— e-BH 里 e 是证据强度，越大越强。 */
  evidence: FieldView;
  /** 证书环境 / 测试类型 / 日期。 */
  context: FieldView;
  preregHash: string;
  /** 校验过的预注册哈希显示成短前缀。 */
  preregShort: string;
}

export function certificateView(certificate: CertificatePayload): CertificateView {
  const mechanismId = certificate.mechanism_id ?? '';
  const rivalId = certificate.rival_id ?? '';

  const evidence: FieldView =
    typeof certificate.e_value === 'number'
      ? {
          state: 'recorded',
          text: `e=${certificate.e_value.toFixed(4)}`,
          tone: certificate.e_value > 1 ? 'positive' : 'muted',
        }
      : { state: 'unrecorded', text: '未记录', tone: 'muted' };

  const contextParts = [
    typeof certificate.env === 'string' && certificate.env ? `环境=${certificate.env}` : null,
    typeof certificate.test_type === 'string' && certificate.test_type
      ? `检验=${certificate.test_type}`
      : null,
    typeof certificate.stat === 'number' ? `stat=${certificate.stat.toFixed(4)}` : null,
    certificate.date ? certificate.date : null,
  ].filter((part): part is string => part !== null);

  const preregHash = typeof certificate.prereg_hash === 'string' ? certificate.prereg_hash : '';

  return {
    mechanismId,
    rivalId,
    headline: `${shortId(mechanismId)} 胜过 ${shortId(rivalId)}`,
    evidence,
    context:
      contextParts.length > 0
        ? { state: 'recorded', text: contextParts.join(' · '), tone: 'neutral' }
        : { state: 'unrecorded', text: '未记录', tone: 'muted' },
    preregHash,
    // 哈希太长，卡片上只放前 10 位；完整值放 title 属性
    preregShort: preregHash ? preregHash.slice(0, 10) : '未记录预注册',
  };
}

// --------------------------------------------------------------------------
// 整页视图
// --------------------------------------------------------------------------

export interface TournamentView {
  /** 辩论赛是否启用（`discovery.enabled`）。 */
  enabled: boolean | null;
  partition: MechanismPartition;
  families: MatchFamily[];
  totalMatches: number;
  decisiveMatches: number;
  certificates: CertificateView[];
  /** 数组为空但表在（`state=available`）—— 要显示"跑了但没产出"。 */
  tableAvailableButEmpty: boolean;
  /** 表都读不到（`state=missing`）。 */
  tableMissing: boolean;
}

/**
 * 整页视图。
 *
 * 注意 `enabled` 与"有没有数据"是**两件事**：实测 demo `enabled=true`、四个
 * `*_state` 全是 `AVAILABLE`，但六个数组全是 `[]`。所以页面必须能同时说
 * "辩论赛启用了"和"没有产出"，不能靠 `enabled` 推断后者。
 */
export function buildTournamentView(discovery: DiscoveryResponse): TournamentView {
  const mechanisms = discovery.theories ?? [];
  const matches = discovery.matches ?? [];
  const certificates = discovery.certificates ?? [];

  const partition = partitionMechanisms(mechanisms);
  return {
    enabled: discovery.enabled ?? null,
    partition,
    families: groupMatchesByFamily(matches),
    totalMatches: matches.length,
    decisiveMatches: matches.filter((match) => matchVerdict(match).decisive).length,
    certificates: certificates.map(certificateView),
    tableAvailableButEmpty:
      mechanisms.length === 0 &&
      matches.length === 0 &&
      discovery.mechanisms_state === 'available' &&
      discovery.matches_state === 'available',
    tableMissing:
      discovery.mechanisms_state === 'missing' || discovery.matches_state === 'missing',
  };
}

/** 空状态文案。三种"空"必须说不同的话。 */
export function tournamentEmptyReason(view: TournamentView): string | null {
  if (view.totalMatches > 0 || view.partition.groups.length > 0) return null;
  if (view.tableMissing) {
    return '这次运行的数据库里没有机制/比赛表，无法展示辩论赛';
  }
  if (view.enabled === false) {
    return '知识发现未启用，本次运行没有进行机制辩论';
  }
  if (view.tableAvailableButEmpty) {
    return '机制辩论已就绪，但本次运行没有建立或否证任何机制';
  }
  return '没有可展示的机制辩论数据';
}

/** 机制标题；缺散文时**不编**，用 id 的短前缀代替并标注。 */
export function mechanismLabel(mechanism: MechanismPayload): { text: string; invented: boolean } {
  if (typeof mechanism.title === 'string' && mechanism.title.trim() !== '') {
    return { text: mechanism.title, invented: false };
  }
  return {
    text: `${shortId(mechanism.id ?? '')}（无标题）`,
    invented: false,
  };
}

function shortId(id: string): string {
  return id.length > 10 ? id.slice(0, 10) : id || '未记录';
}
