/**
 * 机制辩论赛的分区（TODO 6.3，含阶段 6 测试要求 4「tournament 未启用」）。
 *
 * 最要紧的一条断言是「必须把 Qwen 论点与数据裁决分区显示」：
 * `partitionMechanisms` 把 `claim` 与其余 role 分开，`matchVerdict` 把
 * `supports` 翻译成胜方 —— 论点（LLM 生成）与裁决（数据给出）从数据结构上
 * 就是两组，不靠前端自觉。
 */
import { describe, expect, it } from 'vitest';

import {
  buildTournamentView,
  certificateView,
  groupMatchesByFamily,
  matchVerdict,
  mechanismLabel,
  mechanismStatusVerdict,
  partitionMechanisms,
  roleVerdict,
  supportingMechanismId,
  tournamentEmptyReason,
} from '@/features/discovery/tournament-logic';
import type { DiscoveryResponse, MechanismPayload } from '@/features/discovery/types';

function discovery(overrides: Partial<DiscoveryResponse> = {}): DiscoveryResponse {
  return {
    run_id: 'hdd_mvp_demo_7510f100',
    contract_version: '1.5.0',
    enabled: true,
    theories: [],
    matches: [],
    certificates: [],
    ...overrides,
  } as DiscoveryResponse;
}

const ROLES = ['claim', 'llm_rival', 'confound', 'artifact', 'censor', 'other'] as const;

function mechanism(id: string, role: string, overrides: Partial<MechanismPayload> = {}): MechanismPayload {
  return { id, role, status: 'proposed', ...overrides };
}

describe('role 分区（六个取值与 schemas.py 一致）', () => {
  it('六种 role 各有中文名', () => {
    expect(roleVerdict('claim').label).toBe('主张');
    expect(roleVerdict('llm_rival').label).toBe('对手机制');
    expect(roleVerdict('confound').label).toBe('混淆因素');
    expect(roleVerdict('artifact').label).toBe('数据处理产物');
    expect(roleVerdict('censor').label).toBe('随机性/审查项');
    expect(roleVerdict('other').label).toBe('其他机制');
  });

  it('主张被单独拎出来，其余 role 都算对手机制', () => {
    const partition = partitionMechanisms([
      mechanism('m-claim', 'claim'),
      mechanism('m-rival', 'llm_rival'),
      mechanism('m-conf', 'confound'),
      mechanism('m-art', 'artifact'),
      mechanism('m-cen', 'censor'),
      mechanism('m-oth', 'other'),
    ]);
    expect(partition.claim.map((m) => m.id)).toEqual(['m-claim']);
    expect(partition.rivals.map((m) => m.id)).toEqual([
      'm-rival',
      'm-conf',
      'm-art',
      'm-cen',
      'm-oth',
    ]);
    expect(partition.groups).toHaveLength(6);
  });

  it('分组顺序固定，两次调用结果一致', () => {
    const input = ROLES.map((role, i) => mechanism(`m${i}`, role));
    const first = partitionMechanisms(input).groups.map((group) => group.key);
    const second = partitionMechanisms([...input].reverse()).groups.map((group) => group.key);
    expect(first).toEqual([...ROLES]);
    expect(second).toEqual([...ROLES]);
  });

  it('未知 role 不丢，进 unknown 组并保留原值', () => {
    const partition = partitionMechanisms([mechanism('m-x', 'brand_new_role')]);
    expect(partition.groups).toHaveLength(1);
    expect(partition.groups[0].key).toBe('unknown');
    expect(partition.groups[0].label).toContain('brand_new_role');
    expect(partition.groups[0].items[0].id).toBe('m-x');
  });

  it('缺 role 也有位置，不静默消失', () => {
    const partition = partitionMechanisms([mechanism('m-1', undefined as unknown as string)]);
    expect(partition.groups[0].key).toBe('unknown');
    expect(partition.groups[0].label).toBe('未记录角色');
  });

  it('数出已建立与已否证的数量', () => {
    const partition = partitionMechanisms([
      mechanism('a', 'claim', { status: 'established' }),
      mechanism('b', 'llm_rival', { status: 'established' }),
      mechanism('c', 'confound', { status: 'refuted' }),
    ]);
    expect(partition.establishedCount).toBe(2);
    expect(partition.refutedCount).toBe(1);
  });

  it('空输入不炸', () => {
    const partition = partitionMechanisms([]);
    expect(partition.groups).toEqual([]);
    expect(partition.claim).toEqual([]);
    expect(partition.rivals).toEqual([]);
  });
});

describe('机制状态裁决用语', () => {
  it('proposed 是"待检验"，不是"未决"（与 undetermined 分开）', () => {
    expect(mechanismStatusVerdict('proposed').label).toBe('待检验');
    expect(mechanismStatusVerdict('proposed').reason).toContain('尚未进入辩论');
    expect(mechanismStatusVerdict('undetermined').label).toBe('证据不足');
    expect(mechanismStatusVerdict('undetermined').reason).toContain('没分出胜负');
  });

  it('established / refuted 各说各的', () => {
    expect(mechanismStatusVerdict('established').label).toBe('数据支持');
    expect(mechanismStatusVerdict('refuted').label).toBe('数据否证');
    expect(mechanismStatusVerdict('established').tone).toBe('positive');
    expect(mechanismStatusVerdict('refuted').tone).toBe('warning');
  });

  it('未知状态原样显示', () => {
    expect(mechanismStatusVerdict('weird').label).toBe('weird');
    expect(mechanismStatusVerdict(null).label).toBe('未记录');
  });
});

describe('正反论点：supports 是 a/b/none，不是机制 id', () => {
  it('supports=a ⇒ mech_a 胜，winner 是机制 id', () => {
    const verdict = matchVerdict({ mech_a: 'M-1', mech_b: 'M-2', supports: 'a', decisive: true });
    expect(verdict.outcome).toBe('a_wins');
    expect(verdict.winner).toBe('M-1');
    expect(verdict.loser).toBe('M-2');
    expect(verdict.tone).toBe('positive');
  });

  it('supports=b ⇒ mech_b 胜', () => {
    const verdict = matchVerdict({ mech_a: 'M-1', mech_b: 'M-2', supports: 'b', decisive: true });
    expect(verdict.outcome).toBe('b_wins');
    expect(verdict.winner).toBe('M-2');
  });

  it('supports=none ⇒ 未分胜负', () => {
    const verdict = matchVerdict({ mech_a: 'M-1', mech_b: 'M-2', supports: 'none' });
    expect(verdict.outcome).toBe('tie');
    expect(verdict.winner).toBeNull();
  });

  it('未达决定阈值时不能当裁决依据（即使有胜方）', () => {
    const verdict = matchVerdict({ mech_a: 'M-1', mech_b: 'M-2', supports: 'a', decisive: false });
    expect(verdict.winner).toBe('M-1');
    expect(verdict.decisive).toBe(false);
    expect(verdict.tone).toBe('muted');
    expect(verdict.reason).toContain('不能单独作为裁决依据');
  });

  it('supports 缺失时不猜胜方', () => {
    const verdict = matchVerdict({ mech_a: 'M-1', mech_b: 'M-2' });
    expect(verdict.outcome).toBe('unknown');
    expect(verdict.winner).toBeNull();
    expect(verdict.reason).toContain('没有被记录');
  });

  it('统计数字成一行；缺 stat 时报未记录', () => {
    const withStat = matchVerdict({
      mech_a: 'A',
      mech_b: 'B',
      supports: 'a',
      stat: 1.2345,
      ci_low: 0.5,
      ci_high: 2.0,
      p: 0.001,
      e_raw: 20,
    });
    expect(withStat.statistics.text).toContain('stat=1.2345');
    expect(withStat.statistics.text).toContain('[0.5000, 2.0000]');
    expect(withStat.statistics.text).toContain('e=20.000');

    expect(matchVerdict({ mech_a: 'A', mech_b: 'B' }).statistics.state).toBe('unrecorded');
  });

  it('supportingMechanismId 直接给出要高亮的机制', () => {
    expect(supportingMechanismId({ mech_a: 'A', mech_b: 'B', supports: 'b' })).toBe('B');
    expect(supportingMechanismId({ mech_a: 'A', mech_b: 'B', supports: 'none' })).toBeNull();
  });
});

describe('按家族分组（一次家族 = 一场完整辩论）', () => {
  it('分组并数出决定性场次', () => {
    const families = groupMatchesByFamily([
      { family_id: 'f1', mech_a: 'A', mech_b: 'B', supports: 'a', decisive: true },
      { family_id: 'f1', mech_a: 'A', mech_b: 'C', supports: 'a', decisive: false },
      { family_id: 'f2', mech_a: 'D', mech_b: 'E', supports: 'b', decisive: true },
    ]);
    expect(families).toHaveLength(2);
    const f1 = families.find((family) => family.familyId === 'f1');
    expect(f1?.matches).toHaveLength(2);
    expect(f1?.decisiveCount).toBe(1);
    expect(f1?.champion).toBe('A');
  });

  it('胜场并列时不给冠军（宁可 null 也不随便挑）', () => {
    const families = groupMatchesByFamily([
      { family_id: 'f1', mech_a: 'A', mech_b: 'B', supports: 'a' },
      { family_id: 'f1', mech_a: 'A', mech_b: 'B', supports: 'b' },
    ]);
    expect(families[0].champion).toBeNull();
  });

  it('没有 family_id 的场次归到空串组，不丢', () => {
    const families = groupMatchesByFamily([{ mech_a: 'A', mech_b: 'B', supports: 'a' }]);
    expect(families).toHaveLength(1);
    expect(families[0].familyId).toBe('');
  });
});

describe('证书', () => {
  it('headline 说清谁胜过谁', () => {
    const view = certificateView({ mechanism_id: 'M-abcdef1234', rival_id: 'M-rival5678' });
    expect(view.headline).toBe('M-abcdef12 胜过 M-rival567');
  });

  it('e 值 > 1 为正色（证据支持），否则暗淡', () => {
    expect(certificateView({ e_value: 20 }).evidence.tone).toBe('positive');
    expect(certificateView({ e_value: 0.5 }).evidence.tone).toBe('muted');
    expect(certificateView({}).evidence.state).toBe('unrecorded');
  });

  it('上下文拼环境/检验/统计/日期；全缺时报未记录', () => {
    const view = certificateView({
      env: 'public',
      test_type: 'permutation',
      stat: 1.5,
      date: '2026-10-02',
    });
    expect(view.context.text).toContain('环境=public');
    expect(view.context.text).toContain('检验=permutation');
    expect(view.context.text).toContain('stat=1.5000');
    expect(view.context.text).toContain('2026-10-02');

    expect(certificateView({}).context.state).toBe('unrecorded');
  });

  it('预注册哈希截前 10 位，缺值时明说', () => {
    expect(certificateView({ prereg_hash: 'abcdef0123456789' }).preregShort).toBe('abcdef0123');
    expect(certificateView({}).preregShort).toBe('未记录预注册');
  });
});

describe('整页视图', () => {
  it('demo 的真实形状：启用了、表在、但全空', () => {
    const view = buildTournamentView(
      discovery({ enabled: true, mechanisms_state: 'available', matches_state: 'available' }),
    );
    expect(view.enabled).toBe(true);
    expect(view.tableAvailableButEmpty).toBe(true);
    expect(view.tableMissing).toBe(false);
    expect(tournamentEmptyReason(view)).toBe('机制辩论已就绪，但本次运行没有建立或否证任何机制');
  });

  it('未启用（测试要求：tournament 未启用）', () => {
    const view = buildTournamentView(
      discovery({ enabled: false, mechanisms_state: 'missing', matches_state: 'missing' }),
    );
    // 表也缺 → 优先报"没有表"，因为这是更硬的事实
    expect(view.tableMissing).toBe(true);
    expect(tournamentEmptyReason(view)).toContain('没有机制/比赛表');

    // 表在但未启用 → 报未启用
    const enabledOff = buildTournamentView(
      discovery({ enabled: false, mechanisms_state: 'available', matches_state: 'available' }),
    );
    expect(tournamentEmptyReason(enabledOff)).toBe('知识发现未启用，本次运行没有进行机制辩论');
  });

  it('有数据时不给空状态文案', () => {
    const view = buildTournamentView(
      discovery({ theories: [mechanism('M-1', 'claim')] }),
    );
    expect(tournamentEmptyReason(view)).toBeNull();
  });

  it('汇总比赛场次与决定性场次', () => {
    const view = buildTournamentView(
      discovery({
        matches: [
          { mech_a: 'A', mech_b: 'B', supports: 'a', decisive: true, family_id: 'f1' },
          { mech_a: 'A', mech_b: 'C', supports: 'a', decisive: false, family_id: 'f1' },
        ],
      }),
    );
    expect(view.totalMatches).toBe(2);
    expect(view.decisiveMatches).toBe(1);
    expect(view.families).toHaveLength(1);
  });

  it('enabled 缺失时报 null，不默认成 true', () => {
    expect(buildTournamentView(discovery({ enabled: null })).enabled).toBeNull();
  });
});

describe('机制标题', () => {
  it('有标题就用标题', () => {
    expect(mechanismLabel({ id: 'M-1', title: '冷启动假说' })).toEqual({
      text: '冷启动假说',
      invented: false,
    });
  });

  it('没标题时用 id 短前缀并标注，不编标题', () => {
    const label = mechanismLabel({ id: 'M-abcdef123456' });
    expect(label.text).toBe('M-abcdef12（无标题）');
    expect(label.invented).toBe(false);
  });

  it('空白标题不算标题', () => {
    expect(mechanismLabel({ id: 'M-1', title: '   ' }).text).toContain('无标题');
  });
});
