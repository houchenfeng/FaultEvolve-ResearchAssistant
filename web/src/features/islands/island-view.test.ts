/**
 * 三岛推导层的行为测试（TODO D6.4）。
 *
 * 每条测试都在验一个"界面会不会说谎"的问题，而不是验函数存在：
 * `null` 会不会被显示成 0、四件事会不会被合并成一个数、
 * 账本差 1 个 token 会不会被抹平、岛状态与运行状态矛盾会不会被藏起来。
 *
 * 数据形状取自实测 fixture `tests/fixtures/runs/hdd_mvp_islands_15l4nd01`
 * （三岛各 7 节点、1 条摘要、2 次投递、12 次采用、12 次已评估、
 * 逐岛成本 3300/3300/3600、总量 10200），但这里只留断言需要的字段。
 */
import { describe, expect, it } from 'vitest';

import type {
  IslandViewResponse,
  RunIslandsResponse,
  TreeNodeDto,
} from '@/generated/api';
import type { TreeEdgeInput } from '@/features/workbench/tree-adapter';
import {
  LEGACY_ISLAND,
  confidenceLabel,
  deliveryReasonLabel,
  exchangeFacts,
  formatCount,
  formatScore,
  formatUsd,
  globalBestNote,
  graftCountsByIsland,
  islandRows,
  islandShape,
  islandTreeStats,
  profileFocus,
  reconcileAttempts,
  reconcileCost,
  stopReasonLabel,
  summaryKindLabel,
  treeIsSplit,
} from '@/features/islands/island-view';

function node(overrides: Partial<TreeNodeDto> = {}): TreeNodeDto {
  return {
    id: 'n-00000001',
    branch_id: 'main',
    depth: 0,
    operator: 'refine',
    hypothesis_status: 'undetermined',
    status: 'done',
    island_id: 'a',
    score: 10,
    delta_score: 0.5,
    within_noise_band: false,
    ...overrides,
  };
}

function view(overrides: Partial<IslandViewResponse> = {}): IslandViewResponse {
  return {
    island_id: 'a',
    status: 'running',
    profile: 'performance',
    attempts: 6,
    valid_evaluations: 7,
    invalid_evaluations: 0,
    best_score: 22.8074,
    stop_reason: '',
    ...overrides,
  };
}

function islands(overrides: Partial<RunIslandsResponse> = {}): RunIslandsResponse {
  return {
    state: 'available',
    source: 'run_summary.json',
    detail: '',
    islands: { a: view(), b: view({ island_id: 'b', profile: 'miss_alert' }) },
    exchange: {
      summaries: 1,
      by_kind: { best: 1, failure: 0, knowledge: 0 },
      deliveries: 2,
      accepted: 2,
      rejected: 0,
      applications: 12,
      evaluated_applications: 12,
    },
    cost: {
      total_tokens: 10200,
      by_island: {
        a: { tokens: 3300, calls: 11, unresolved_calls: 0, cached_calls: 0, by_stage: { generate: 2200 } },
        b: { tokens: 3300, calls: 11, unresolved_calls: 0, cached_calls: 0 },
        c: { tokens: 3600, calls: 12, unresolved_calls: 0, cached_calls: 0 },
      },
      shared_tokens: 0,
      unresolved_calls: 0,
      cost_usd: null,
      cost_basis: 'unknown',
    },
    attempt_total: 12,
    ...overrides,
  };
}

const graft: TreeEdgeInput = { source: 'n-a-best', target: 'n-b-cx', kind: 'summary_cross' };

describe('未记录不是 0', () => {
  it('缺计数时给「未记录」，缺分数时给「未评分」', () => {
    // 0 会讲出一个假故事：「从没跑过」和「跑了但没产出」看起来一模一样。
    expect(formatCount(null)).toBe('未记录');
    expect(formatCount(undefined)).toBe('未记录');
    expect(formatCount(0)).toBe('0');
    expect(formatScore(null)).toBe('未评分');
    expect(formatScore(0)).toBe('0.00');
  });

  it('没报价的模型不编造美元成本', () => {
    expect(formatUsd({ cost_basis: 'unknown', cost_usd: null })).toBe('未记录（计价依据：unknown）');
    // 即使 cost_usd 有值，只要依据不是 recorded 就不显示金额。
    expect(formatUsd({ cost_basis: 'estimated', cost_usd: 1.5 })).toContain('estimated');
    expect(formatUsd({ cost_basis: 'recorded', cost_usd: 0.123456 })).toBe('$0.1235');
  });

  it('未知取值回落原文，不留空白', () => {
    expect(summaryKindLabel('brand_new_kind')).toBe('brand_new_kind');
    expect(confidenceLabel('brand_new_level')).toBe('brand_new_level');
    expect(stopReasonLabel('')).toBe('未停止（仍在配额内）');
    expect(deliveryReasonLabel('some_future_reason')).toBe('some_future_reason');
  });

  it('单次观察不写成已确认的规律', () => {
    // 需求 §6：单次 HDD 观察不得升级为跨任务规律。
    expect(confidenceLabel('single_observation')).toContain('未复现');
    expect(profileFocus('performance')).toBe('优先提升综合指标，允许在多个维度上权衡。');
    expect(profileFocus('new_profile')).toContain('new_profile');
  });
});

describe('嫁接边按岛计数', () => {
  const nodes = [
    node({ id: 'n-a-best', island_id: 'a' }),
    node({ id: 'n-b-cx', island_id: 'b' }),
    node({ id: 'n-c-cx', island_id: 'c' }),
  ];

  it('入边记到目标岛、出边记到源岛', () => {
    const counts = graftCountsByIsland(nodes, [
      graft,
      { source: 'n-a-best', target: 'n-c-cx', kind: 'summary_cross' },
    ]);
    expect(counts.get('b')).toEqual({ incoming: 1, outgoing: 0 });
    expect(counts.get('c')).toEqual({ incoming: 1, outgoing: 0 });
    expect(counts.get('a')).toEqual({ incoming: 0, outgoing: 2 });
  });

  it('普通父子边不进交换计数', () => {
    const counts = graftCountsByIsland(nodes, [
      { source: 'n-a-best', target: 'n-b-cx', kind: 'parent' },
    ]);
    expect(counts.size).toBe(0);
  });

  it('端点不在节点列表里的边被跳过，不产生幽灵岛计数', () => {
    const counts = graftCountsByIsland(nodes, [
      { source: 'gone', target: 'n-b-cx', kind: 'summary_cross' },
    ]);
    expect(counts.get('b')).toEqual({ incoming: 1, outgoing: 0 });
    expect(counts.has('gone')).toBe(false);
  });
});

describe('单岛树统计', () => {
  const nodes = [
    node({ id: 'a1', island_id: 'a', score: 30, delta_score: 2, within_noise_band: false }),
    node({ id: 'a2', island_id: 'a', score: 20, delta_score: 2, within_noise_band: true }),
    node({ id: 'a3', island_id: 'a', score: null, delta_score: null, within_noise_band: null }),
    node({ id: 'b1', island_id: 'b', score: 99, delta_score: 5, within_noise_band: false }),
  ];

  it('本岛最优只在本岛节点里算', () => {
    // b 岛有 99 分，但 a 岛的最优仍是 a1：全局最优不属于任何单岛视图。
    const stats = islandTreeStats('a', nodes, []);
    expect(stats.bestNodeId).toBe('a1');
    expect(stats.bestScore).toBe(30);
    expect(stats.nodeCount).toBe(3);
  });

  it('只有超出噪声带的正 Δ 才算有效改进', () => {
    // a2 的 Δ=2 但落在噪声带内，不能算改进（PRD §9.4）。
    expect(islandTreeStats('a', nodes, []).improvedCount).toBe(1);
  });

  it('无分数的节点不影响最优', () => {
    const only = islandTreeStats('a', [node({ id: 'x', score: null })], []);
    expect(only.bestScore).toBeNull();
    expect(only.bestNodeId).toBeNull();
  });

  it('同分取先出现的节点，两次调用结果一致', () => {
    const tied = [
      node({ id: 'first', island_id: 'a', score: 5 }),
      node({ id: 'second', island_id: 'a', score: 5 }),
    ];
    expect(islandTreeStats('a', tied, []).bestNodeId).toBe('first');
    expect(islandTreeStats('a', tied, [])).toEqual(islandTreeStats('a', tied, []));
  });
});

describe('岛列表', () => {
  const nodes = [
    node({ id: 'a1', island_id: 'a', score: 22.8074 }),
    node({ id: 'b1', island_id: 'b', score: 22.8074 }),
    node({ id: 'c1', island_id: 'c', score: 12 }),
  ];
  const edges: TreeEdgeInput[] = [{ source: 'a1', target: 'c1', kind: 'summary_cross' }];

  it('树里有但没记账的岛仍然出现在列表里，字段是「未记录」', () => {
    const rows = islandRows(islands(), nodes, edges, 'completed');
    const c = rows.find((row) => row.islandId === 'c');
    expect(c?.view).toBeNull();
    expect(c?.statusLabel).toBe('未记录');
    expect(c?.profileText).toBe('未记录');
    expect(c?.tree.nodeCount).toBe(1);
  });

  it('岛按 id 排序，历史单岛的记录排最后', () => {
    const rows = islandRows(islands(), nodes, edges, 'completed');
    expect(rows.map((row) => row.islandId)).toEqual(['a', 'b', 'c']);
    // 旧引擎的 `legacy_island_spec()` 用空串当岛 id，`_island_stop_summary`
    // 就按空串写进 run_summary，所以这条是真的会出现的。
    const legacy = islandRows(
      islands({ islands: { '': view({ island_id: LEGACY_ISLAND }) } }),
      nodes,
      edges,
      'completed',
    );
    expect(legacy.at(-1)?.islandId).toBe(LEGACY_ISLAND);
    expect(legacy.at(-1)?.title).toBe('未分岛（历史单树）');
  });

  it('树里只有空串岛、又没有记账时不编出岛列表', () => {
    // 界面此时按单树渲染（`islandShape` 给 legacy-single），列表必须是空的：
    // 凭空造一个「岛」会让历史运行看起来像多岛运行。
    const rows = islandRows(
      { ...islands(), islands: {} },
      [node({ id: 'x', island_id: LEGACY_ISLAND })],
      [],
      'completed',
    );
    expect(rows).toEqual([]);
  });

  it('运行已结束但岛还写着 running 时，明说而不是藏起来', () => {
    const rows = islandRows(islands(), nodes, edges, 'completed');
    expect(rows[0].stalenessNote).toContain('仍记录为 running');
    // 运行仍在进行时不该出现这条说明。
    const running = islandRows(islands(), nodes, edges, 'running');
    expect(running[0].stalenessNote).toBeNull();
  });

  it('run_summary 的本岛最优与树里实测不一致时报不一致', () => {
    const rows = islandRows(islands(), nodes, edges, 'completed');
    expect(rows[0].bestScoreConsistent).toBe(true);
    const drifted = islandRows(
      islands({
        islands: { a: view({ best_score: 99 }), b: view({ island_id: 'b', best_score: 22.8074 }) },
      }),
      nodes,
      edges,
      'completed',
    );
    expect(drifted[0].bestScoreConsistent).toBe(false);
  });

  it('记账里缺一个岛时列表仍完整，缺的字段是未记录', () => {
    const rows = islandRows(
      islands({ islands: { a: view() }, cost: null }),
      nodes,
      edges,
      'completed',
    );
    expect(rows.map((row) => row.islandId)).toEqual(['a', 'b', 'c']);
    expect(rows[1].cost).toBeNull();
    expect(rows[1].view).toBeNull();
    expect(rows[1].stopLabel).toBe('未记录');
  });
});

describe('交换四件事', () => {
  it('六个计数各占一行，谁也不并进谁', () => {
    const facts = exchangeFacts(islands().exchange);
    expect(facts.map((fact) => fact.key)).toEqual([
      'summaries',
      'deliveries',
      'accepted',
      'rejected',
      'applications',
      'evaluated_applications',
    ]);
    const byKey = Object.fromEntries(facts.map((fact) => [fact.key, fact.value]));
    // 实测 fixture：1 条摘要 → 2 次投递 → 2 次采纳 → 12 次采用。
    // 任何"合并成一个交换数"的实现都会让这里相等。
    expect(byKey.summaries).toBe('1');
    expect(byKey.deliveries).toBe('2');
    expect(byKey.accepted).toBe('2');
    expect(byKey.applications).toBe('12');
    expect(byKey.summaries).not.toBe(byKey.applications);
  });

  it('没有交换层时每行都是「未记录」', () => {
    for (const fact of exchangeFacts(null)) {
      expect(fact.value).toBe('未记录');
    }
  });
});

describe('成本对账', () => {
  it('各岛加未归属等于总量时判自洽', () => {
    const result = reconcileCost(islands().cost);
    expect(result.state).toBe('balanced');
    expect(result.islandTokens).toBe(10200);
    expect(result.gap).toBe(0);
  });

  it('差一个 token 也如实报差额，不抹平', () => {
    const cost = { ...islands().cost, total_tokens: 10201 };
    const result = reconcileCost(cost);
    expect(result.state).toBe('unbalanced');
    expect(result.gap).toBe(1);
    expect(result.message).toContain('相差 1');
  });

  it('缺分项或缺总量时说不清，而不是当作 0', () => {
    expect(reconcileCost(null).state).toBe('unknown');
    expect(reconcileCost({ total_tokens: 100, by_island: {} }).state).toBe('unknown');
    expect(reconcileCost({ by_island: { a: { tokens: 5 } } }).state).toBe('unknown');
  });
});

describe('尝试数对账', () => {
  it('三个数一致才算 match', () => {
    // 各岛 attempts 6+6=12，attempt_total 12，iterations_done 12。
    expect(reconcileAttempts(islands(), 12).state).toBe('match');
  });

  it('界面自己求和，attempt_total 与岛级数据不符时报 mismatch', () => {
    const result = reconcileAttempts(islands({ attempt_total: 9 }), 12);
    expect(result.state).toBe('mismatch');
    expect(result.summedFromIslands).toBe(12);
    expect(result.message).toContain('9');
  });

  it('两边任缺其一就是 unknown，不猜', () => {
    expect(reconcileAttempts(islands(), null).state).toBe('unknown');
    expect(reconcileAttempts(islands({ attempt_total: null }), 12).state).toBe('unknown');
  });

  it('岛没记 attempts 时求和为 0，但仍按 unknown 处理缺量的情况', () => {
    const result = reconcileAttempts(
      islands({ islands: { a: view({ attempts: null }) }, attempt_total: null }),
      3,
    );
    expect(result.state).toBe('unknown');
    expect(result.summedFromIslands).toBe(0);
  });
});

describe('单树与三岛的区分', () => {
  it('available 且有岛 ⇒ islands', () => {
    expect(islandShape(islands())).toBe('islands');
  });

  it('missing（历史单树运行）⇒ legacy-single，不是错误', () => {
    // 契约的 detail 已经写明"单树运行早于多岛引擎"，界面必须画一棵树而不是三个空岛。
    const legacy = { ...islands({ islands: {} }), state: 'missing' } as RunIslandsResponse;
    expect(islandShape(legacy)).toBe('legacy-single');
  });

  it('invalid ⇒ unreadable，交给错误态渲染', () => {
    expect(islandShape({ ...islands(), state: 'invalid' })).toBe('unreadable');
    expect(islandShape(null)).toBe('unreadable');
  });

  it('available 但 islands 为空也按单树处理，不编出三个岛', () => {
    expect(islandShape({ ...islands(), islands: {} })).toBe('legacy-single');
  });
});

describe('树的实际分岛情况', () => {
  it('两个以上岛才算并列树', () => {
    expect(
      treeIsSplit([node({ id: 'a', island_id: 'a' }), node({ id: 'b', island_id: 'b' })]),
    ).toBe(true);
    expect(treeIsSplit([node({ id: 'a', island_id: 'a' })])).toBe(false);
    // 历史单树：所有节点 island_id 为空串。
    expect(treeIsSplit([node({ id: 'a', island_id: LEGACY_ISLAND })])).toBe(false);
  });
});

describe('确定性', () => {
  it('同一份数据两次推导结果完全相同', () => {
    // 布局与渲染都依赖这一点：漂移会让每次重绘都重排一次岛列表。
    const nodes = [node({ id: 'b1', island_id: 'b' }), node({ id: 'a1', island_id: 'a' })];
    const first = islandRows(islands(), nodes, [graft], 'completed');
    const second = islandRows(islands(), nodes, [graft], 'completed');
    expect(JSON.stringify(first)).toBe(JSON.stringify(second));
    expect(first.map((row) => row.islandId)).toEqual(['a', 'b']);
  });
});

describe('全局最优落在哪里（概览页与结果页共用同一句话）', () => {
  const nodes = [
    node({ id: 'n-a', island_id: 'a' }),
    node({ id: 'n-b', island_id: 'b' }),
    node({ id: 'n-legacy', island_id: LEGACY_ISLAND }),
  ];

  it('节点在树里就是它自己的 island_id，不按顺序猜', () => {
    expect(globalBestNote(nodes, 'n-b')).toBe('（落在岛 b）');
  });

  it('节点不在树里时明说只有 run_summary 记了它', () => {
    expect(globalBestNote(nodes, 'n-missing')).toBe(
      '（该节点不在树里，只有 run_summary.json 记了它）',
    );
  });

  it('节点没有岛标记时不拿别的岛顶替', () => {
    expect(globalBestNote(nodes, 'n-legacy')).toBe('（该节点没有岛标记）');
  });

  it('没有全局最优节点就没有这句话', () => {
    expect(globalBestNote(nodes, null)).toBe('');
  });
});
