/**
 * 结果与报告推导逻辑的单元测试（PRD 13.1–13.5 / TODO 6.4）。
 *
 * 除了通用的「null 不等于 0」，这一页有三条专属纪律必须被测试钉住：
 * 1. Top-K **不重排**——后端已经排好序并给了 rank，前端重排就是另立排名真源；
 * 2. 下载入口只在制品清单核对通过时出现，清单没取到时是「未知」而不是「不可下载」；
 * 3. 分项指标不预置任何键名，也不为缺失的键补 0。
 */
import { describe, expect, it } from 'vitest';

import {
  DEFAULT_TOP_K,
  bestNodeIdOf,
  islandBestRows,
  metricRows,
  noiseSummary,
  noiseVerdict,
  outcomeRows,
  reportRows,
  scoreCell,
  secondsCell,
  sizeCell,
  textCell,
  topKRows,
} from '@/features/results/results-logic';
import type {
  ArtifactResponse,
  ReportManifestResponse,
  RunDetailResponse,
  RunIslandsResponse,
  ScoreboardEntryResponse,
  TreeNodeDto,
  TreeResponse,
} from '@/generated/api';

function detail(overrides: Partial<RunDetailResponse> = {}): RunDetailResponse {
  return {
    run_id: 'run_demo',
    contract_version: '1.3.0',
    data_state: 'complete',
    ...overrides,
  };
}

function tree(overrides: Partial<TreeResponse> = {}): TreeResponse {
  return {
    run_id: 'run_demo',
    contract_version: '1.3.0',
    data_state: 'complete',
    nodes: [],
    edges: [],
    ...overrides,
  };
}

function node(overrides: Partial<TreeNodeDto> = {}): TreeNodeDto {
  return {
    id: 'n1',
    branch_id: 'b1',
    depth: 0,
    hypothesis_status: 'undetermined',
    operator: 'init',
    status: 'done',
    ...overrides,
  };
}

function artifact(overrides: Partial<ArtifactResponse> = {}): ArtifactResponse {
  return {
    run_id: 'run_demo',
    artifact_id: 'run_summary',
    kind: 'summary',
    display_name: 'run_summary.json',
    media_type: 'application/json',
    downloadable: true,
    state: 'available',
    ...overrides,
  };
}

describe('数值格式', () => {
  it('分数固定两位，null 是未记录而不是 0.00', () => {
    expect(scoreCell(22.81)).toEqual({ value: '22.81', recorded: true });
    expect(scoreCell(0)).toEqual({ value: '0.00', recorded: true });
    expect(scoreCell(null)).toEqual({ value: '未记录', recorded: false });
    expect(scoreCell(undefined)).toEqual({ value: '未记录', recorded: false });
  });

  it('0 秒是记录到的 0，不是未记录', () => {
    expect(secondsCell(0)).toEqual({ value: '0.0 s', recorded: true });
    expect(secondsCell(null)).toEqual({ value: '未记录', recorded: false });
  });

  it('空字符串算未记录：后端用 "" 当缺省值', () => {
    expect(textCell('')).toEqual({ value: '未记录', recorded: false });
    expect(textCell('n2a')).toEqual({ value: 'n2a', recorded: true });
  });

  it('大小按量级换单位，负数与非有限值不编造', () => {
    expect(sizeCell(512)).toEqual({ value: '512 B', recorded: true });
    expect(sizeCell(2048)).toEqual({ value: '2.0 KB', recorded: true });
    expect(sizeCell(3 * 1024 * 1024)).toEqual({ value: '3.0 MB', recorded: true });
    expect(sizeCell(null)).toEqual({ value: '未记录', recorded: false });
    expect(sizeCell(Number.NaN)).toEqual({ value: '未记录', recorded: false });
  });
});

describe('13.1 结果总览', () => {
  it('detail 为 null 时十一行全部未记录，一行都不少', () => {
    const rows = outcomeRows(null);
    expect(rows).toHaveLength(11);
    expect(rows.every((row) => row.cell.recorded === false)).toBe(true);
    // 每一行都必须带来源，PRD 13.5 的可追溯要求是靠这一列落地的。
    expect(rows.every((row) => row.source.length > 0)).toBe(true);
  });

  it('有值时按两位/一位小数渲染，且来源分段正确', () => {
    const rows = outcomeRows(
      detail({
        outcome: {
          initial_score: 22.81,
          best_score: 25.4,
          improvement: 2.59,
          best_node_id: 'n2a',
          iterations_done: 7,
          valid_rate: 0.4286,
          rounds_to_target: null,
          time_to_target_s: null,
          tokens_to_target: null,
        },
        budget: { total_tokens: 123456, wall_time_s: 1830.25 },
      }),
    );
    const byLabel = Object.fromEntries(rows.map((row) => [row.label, row]));

    expect(byLabel['初始 ROS'].cell).toEqual({ value: '22.81', recorded: true });
    expect(byLabel['最佳 ROS'].cell).toEqual({ value: '25.40', recorded: true });
    expect(byLabel['绝对提升'].cell).toEqual({ value: '2.59', recorded: true });
    expect(byLabel['最佳节点'].cell).toEqual({ value: 'n2a', recorded: true });
    expect(byLabel['有效节点率'].cell).toEqual({ value: '42.9%', recorded: true });
    expect(byLabel['总 Token'].cell).toEqual({ value: '123456', recorded: true });
    expect(byLabel['总耗时'].cell).toEqual({ value: '1830.3 s', recorded: true });

    // 没达到目标时这三项是 null，必须留成未记录——填 0 会读成「0 轮就达标了」。
    expect(byLabel['达到目标轮次'].cell.recorded).toBe(false);
    expect(byLabel['达到目标耗时'].cell.recorded).toBe(false);
    expect(byLabel['达到目标 Token'].cell.recorded).toBe(false);

    expect(byLabel['初始 ROS'].source).toBe('run_summary.json');
    expect(byLabel['总 Token'].source).toBe('run_summary.json（预算段）');
  });

  it('总览里没有「相对提升」这一行', () => {
    const labels = outcomeRows(detail({ outcome: { improvement: 2.59 } })).map(
      (row) => row.label,
    );
    expect(labels.some((label) => label.includes('相对'))).toBe(false);
  });
});

describe('13.1 分项指标（无键保证的透传字典）', () => {
  it('字典缺失时是空列表，不是八个预置名字配 0', () => {
    // null 不在契约里：后端 `metric=metric if isinstance(metric, dict) else {}`
    // （replay_service.py:931），所以只测 undefined 与空字典两种真实情况。
    expect(metricRows(undefined)).toEqual([]);
    expect(metricRows({})).toEqual([]);
  });

  it('输出的键就是后端给的键，一个不多一个不少', () => {
    const rows = metricRows({ whatever_the_backend_sent: 1 });
    expect(rows.map((row) => row.key)).toEqual(['whatever_the_backend_sent']);
  });

  it('后端给什么键就渲染什么键，并按键名排序', () => {
    const rows = metricRows({ recall: 0.0231, f1_p10: 0.1834, n_pos: 31 });
    expect(rows.map((row) => row.key)).toEqual(['f1_p10', 'n_pos', 'recall']);
    expect(rows[0].cell).toEqual({ value: '0.1834', recorded: true });
    // 整数不加小数点：31.0000 会让人以为是浮点测量值。
    expect(rows[1].cell).toEqual({ value: '31', recorded: true });
  });

  it('null、空串与非有限值都是未记录，布尔翻成是否', () => {
    const rows = metricRows({ a: null, b: '', c: Number.POSITIVE_INFINITY, d: true, e: false });
    const byKey = Object.fromEntries(rows.map((row) => [row.key, row.cell]));
    expect(byKey.a).toEqual({ value: '未记录', recorded: false });
    expect(byKey.b).toEqual({ value: '未记录', recorded: false });
    expect(byKey.c).toEqual({ value: '未记录', recorded: false });
    expect(byKey.d).toEqual({ value: '是', recorded: true });
    expect(byKey.e).toEqual({ value: '否', recorded: true });
  });

  it('嵌套结构照实序列化，不悄悄丢掉', () => {
    const rows = metricRows({ per_fold: [1, 2] });
    expect(rows[0].cell).toEqual({ value: '[1,2]', recorded: true });
  });
});

describe('13.3 波动判定', () => {
  it('最佳节点 id 优先取 run_summary，树只是兜底', () => {
    expect(bestNodeIdOf(detail({ outcome: { best_node_id: 'a' } }), tree({ best_node_id: 'b' })))
      .toBe('a');
    expect(bestNodeIdOf(detail(), tree({ best_node_id: 'b' }))).toBe('b');
    expect(bestNodeIdOf(null, null)).toBeNull();
  });

  it('带内说「未形成明确改进证据」，带外说改进成立，null 说无法判断', () => {
    const within = noiseVerdict(node({ delta_score: 0.4, noise_delta: 1.2, within_noise_band: true }));
    expect(within.label).toBe('未形成明确改进证据');
    expect(within.tone).toBe('warning');
    expect(within.band).toBe('within');
    expect(within.reason).toContain('0.400');
    expect(within.reason).toContain('1.200');

    const beyond = noiseVerdict(node({ delta_score: 2.5, noise_delta: 1.2, within_noise_band: false }));
    expect(beyond.label).toBe('改进超出波动范围');
    expect(beyond.tone).toBe('success');

    const unknown = noiseVerdict(node({ delta_score: null, noise_delta: null }));
    expect(unknown.label).toBe('无法判断');
    expect(unknown.tone).toBe('neutral');
    expect(unknown.band).toBe('unknown');
    // 「无法判断」不得被写成任何一种改进结论。
    expect(unknown.reason).not.toContain('有效改进');
  });

  it('节点为 null 时是无法判断，不是「没有改进」', () => {
    expect(noiseVerdict(null).band).toBe('unknown');
    expect(noiseVerdict(undefined).label).toBe('无法判断');
  });

  it('进化树没取到时六个计数全部未记录，不得显示 0', () => {
    const summary = noiseSummary(undefined);
    for (const cell of Object.values(summary)) {
      expect(cell).toEqual({ value: '未记录', recorded: false });
    }
  });

  it('空树是真的 0，与「没取到」区分开', () => {
    expect(noiseSummary([]).total).toEqual({ value: '0', recorded: true });
  });

  it('后三项的分母是有对比基线的节点，三项之和恒等于它', () => {
    const summary = noiseSummary([
      node({ id: 'root', score: 22.81 }),
      node({ id: 'a', score: 23.2, delta_score: 0.39, within_noise_band: true }),
      node({ id: 'b', score: 25.4, delta_score: 2.59, within_noise_band: false }),
      node({ id: 'c', score: 24.0, delta_score: 1.1, within_noise_band: null }),
      node({ id: 'd', score: null }),
    ]);
    expect(summary.total).toEqual({ value: '5', recorded: true });
    expect(summary.scored).toEqual({ value: '4', recorded: true });
    expect(summary.compared).toEqual({ value: '3', recorded: true });
    expect(summary.within).toEqual({ value: '1', recorded: true });
    expect(summary.beyond).toEqual({ value: '1', recorded: true });
    expect(summary.unknown).toEqual({ value: '1', recorded: true });
  });

});

describe('13.2 Top-K 候选', () => {
  function entry(overrides: Partial<ScoreboardEntryResponse> = {}): ScoreboardEntryResponse {
    return {
      rank: 1,
      node_id: 'n1',
      score: 25.4,
      operator: 'refine',
      depth: 1,
      is_best: false,
      ...overrides,
    };
  }

  it('不重排也不重新编号：后端给的顺序与 rank 原样保留', () => {
    // 故意给一个「分数看起来乱序」的榜单。前端若重排，这个用例就会红。
    const rows = topKRows(
      [
        entry({ rank: 1, node_id: 'a', score: 25.4 }),
        entry({ rank: 2, node_id: 'b', score: null }),
        entry({ rank: 3, node_id: 'c', score: 30.0 }),
      ],
      [],
    );
    expect(rows.map((row) => row.nodeId)).toEqual(['a', 'b', 'c']);
    expect(rows.map((row) => row.rank.value)).toEqual(['1', '2', '3']);
    // 未评分显示「未评分」口径的未记录，绝不显示 0.00。
    expect(rows[1].score).toEqual({ value: '未记录', recorded: false });
  });

  it('按 k 截断，默认 10', () => {
    expect(DEFAULT_TOP_K).toBe(10);
    const many = Array.from({ length: 25 }, (_unused, index) =>
      entry({ rank: index + 1, node_id: `n${index}` }),
    );
    expect(topKRows(many, [])).toHaveLength(10);
    expect(topKRows(many, [], 3)).toHaveLength(3);
  });

  it('下载入口只在清单核对通过时出现', () => {
    const entries = [entry({ node_id: 'a' }), entry({ rank: 2, node_id: 'b' })];
    const rows = topKRows(entries, [
      artifact({ artifact_id: 'program-a', kind: 'program', downloadable: true }),
      // 存在但服务端拒绝下载（database / log 属于 _NON_DOWNLOADABLE_KINDS）。
      artifact({ artifact_id: 'program-b', kind: 'program', downloadable: false }),
    ]);
    expect(rows[0].programArtifactId).toBe('program-a');
    expect(rows[0].downloadable).toBe(true);
    expect(rows[1].programArtifactId).toBeNull();
    expect(rows[1].downloadable).toBe(false);
  });

  it('清单没取到时是 null（未知），不是 false（不可下载）', () => {
    const rows = topKRows([entry({ node_id: 'a' })], undefined);
    expect(rows[0].downloadable).toBeNull();
    expect(rows[0].programArtifactId).toBeNull();
  });

  it('榜单没取到时是空列表而不是抛异常', () => {
    expect(topKRows(undefined, undefined)).toEqual([]);
  });
});

describe('13.5 报告 manifest', () => {
  function manifest(overrides: Partial<ReportManifestResponse> = {}): ReportManifestResponse {
    return {
      run_id: 'run_demo',
      contract_version: '1.3.0',
      available: false,
      files: [],
      warnings: [],
      ...overrides,
    };
  }

  it('清单为 null 时是空列表，available 由路由单独传 null', () => {
    expect(reportRows(null, undefined)).toEqual([]);
    expect(reportRows(manifest(), undefined)).toEqual([]);
  });

  it('downloadable 三态：核对通过 / 服务端拒绝 / 清单里没有这一项', () => {
    const files = [
      {
        artifact_id: 'report-x.md',
        display_name: 'report-x.md',
        media_type: 'text/markdown',
        size_bytes: 2048,
        state: 'available' as const,
      },
      {
        artifact_id: 'report-y.json',
        display_name: 'report-y.json',
        media_type: 'application/json',
        size_bytes: null,
        state: 'available' as const,
      },
    ];
    const rows = reportRows(manifest({ available: true, files }), [
      artifact({ artifact_id: 'report-x.md', downloadable: true }),
      artifact({ artifact_id: 'report-y.json', downloadable: false }),
    ]);
    expect(rows.map((row) => row.downloadable)).toEqual([true, false]);
    expect(rows[0].sizeBytes).toEqual({ value: '2.0 KB', recorded: true });
    expect(rows[1].sizeBytes).toEqual({ value: '未记录', recorded: false });

    // 制品清单整个没取到 ⇒ 全部未知，不得顺势说成不可下载。
    const unknown = reportRows(manifest({ available: true, files }), undefined);
    expect(unknown.map((row) => row.downloadable)).toEqual([null, null]);
  });

});

describe('各岛最优（TODO D6.4：全局最优与各岛最优，缺失值有状态）', () => {
  function islands(overrides: Partial<RunIslandsResponse> = {}): RunIslandsResponse {
    return {
      state: 'available',
      source: 'run_summary.json',
      detail: '',
      islands: {
        a: {
          island_id: 'a',
          status: 'finished',
          profile: 'performance',
          attempts: 6,
          valid_evaluations: 7,
          invalid_evaluations: 0,
          best_score: 22.807355886970594,
          stop_reason: 'max_attempts',
        },
        b: {
          island_id: 'b',
          status: 'finished',
          profile: 'miss_alert',
          attempts: 6,
          valid_evaluations: 7,
          invalid_evaluations: 0,
          best_score: 18,
          stop_reason: 'stalled',
        },
      },
      ...overrides,
    };
  }

  const nodes: TreeNodeDto[] = [
    node({ id: 'a-root', island_id: 'a', score: 22.807355886970594, delta_score: 0 }),
    node({ id: 'a-child', island_id: 'a', score: 20, delta_score: -2 }),
    node({ id: 'b-root', island_id: 'b', score: 18 }),
  ];

  it('全局最优标在它真正所属的那一行，其余行为 false', () => {
    const rows = islandBestRows(islands(), nodes, [], null, 'a-root');
    expect(rows.map((row) => row.islandId)).toEqual(['a', 'b']);
    expect(rows.map((row) => row.holdsGlobalBest)).toEqual([true, false]);
    expect(rows[0].bestScore).toBe(22.807355886970594);
    expect(rows[0].title).toBe('岛 a');
  });

  it('本岛最优取本岛树内实测，run_summary 记的那份并列保留并标出不一致', () => {
    const drifted: RunIslandsResponse = {
      ...islands(),
      islands: {
        a: { island_id: 'a', status: 'finished', best_score: 22.807355886970594 },
        b: { island_id: 'b', status: 'finished', best_score: 19 },
      },
    };
    const rows = islandBestRows(drifted, nodes, [], null, null);
    const b = rows.find((row) => row.islandId === 'b');
    expect(b?.bestScore).toBe(18);
    expect(b?.recordedBestScore).toBe(19);
    expect(b?.bestScoreConsistent).toBe(false);
  });

  it('没有已评分节点的岛显示未评分与零节点，不写成 0 分', () => {
    const rows = islandBestRows(
      islands(),
      [node({ id: 'a-root', island_id: 'a', score: 22.8 })],
      [],
      null,
      null,
    );
    const b = rows.find((row) => row.islandId === 'b');
    expect(b?.bestScore).toBeNull();
    expect(b?.bestNodeId).toBeNull();
    expect(b?.nodeCount).toBe(0);
  });

  it('全局最优节点不在树里时，没有任何一行被标上', () => {
    // 这种情况只能说明 run_summary 记的节点没出现在树里，不能顺手把某个岛的
    // 最优当成它就是全局最优。
    const rows = islandBestRows(islands(), nodes, [], null, 'n-missing');
    expect(rows.some((row) => row.holdsGlobalBest)).toBe(false);
  });

  it('历史单树没有岛级记账，行列表为空而不是编一个岛出来', () => {
    const legacy = islandBestRows(
      { state: 'missing', detail: '' },
      [node({ id: 'r', island_id: '' })],
      [],
      null,
      null,
    );
    expect(legacy).toEqual([]);
  });
});
