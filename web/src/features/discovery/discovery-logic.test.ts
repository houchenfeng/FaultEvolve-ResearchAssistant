/**
 * 现象层与辩论赛推导逻辑的单元测试（PRD 12.3–12.5 / TODO 6.2–6.3）。
 *
 * 这些读取器面对的是 `list[dict[str, Any]]`——契约不保证任何字段。所以除了
 * 「0 不等于未记录」这条通用纪律，还要专门验：形状不对时退化成未记录，
 * 而不是抛异常，也不是拿默认值顶上。
 */
import { describe, expect, it } from 'vitest';

import {
  GRADES,
  GRADE_LABEL,
  GRADE_TONE,
  buildCertificateRows,
  buildControlRows,
  buildPhenomenonRows,
  collectSandboxFailures,
  countCellOf,
  discoveryEmptyState,
  flagCell,
  isGrade,
  mechanismCounterRows,
  partitionSandboxFailures,
  statCell,
  tournamentCounterRows,
  validityCounterRows,
} from '@/features/discovery/discovery-logic';
import type { EventResponse, RunDiscoveryResponse } from '@/generated/api';

/** `ClaimTestResult.model_dump()` 的 15 个键，取值都刻意可分辨。 */
const FULL_PAYLOAD = {
  split: 'val',
  n: 1200,
  n_pos: 30,
  n_neg: 1170,
  effect: 0.0825,
  ci_low: 0.031,
  ci_high: 0.134,
  p: 0.00021,
  e: 12.5,
  direction_ok: true,
  temporal_ok: false,
  rho_max_abs: 0.07,
  incr_gain: 0.015,
  incr_ci_low: -0.002,
  incr_ci_high: 0.032,
};

function event(type: string, payload: Record<string, unknown>): EventResponse {
  return { run_id: 'r1', type, payload, ts: '', is_known_type: false };
}

describe('判级词汇：五个值，一个都不能少', () => {
  it('Grade 枚举的五个值全部在册，含 PRD 12.3 漏掉的 discovered', () => {
    expect([...GRADES]).toEqual([
      'confirmed',
      'revised',
      'discovered',
      'refuted',
      'undetermined',
    ]);
  });

  it('isGrade 只认这五个字符串', () => {
    for (const grade of GRADES) expect(isGrade(grade)).toBe(true);
    // supported / refuted / inconclusive 属于 HypothesisStatus（树节点），不是 Grade。
    expect(isGrade('supported')).toBe(false);
    expect(isGrade('inconclusive')).toBe(false);
    expect(isGrade('')).toBe(false);
    expect(isGrade(null)).toBe(false);
    expect(isGrade(3)).toBe(false);
  });

  it('每个判级都有中文标签与配色，且 discovered 没有被并进 confirmed', () => {
    for (const grade of GRADES) {
      expect(GRADE_LABEL[grade]).toBeTruthy();
      expect(GRADE_TONE[grade]).toBeTruthy();
    }
    expect(GRADE_LABEL.discovered).not.toBe(GRADE_LABEL.confirmed);
    expect(GRADE_TONE.discovered).not.toBe(GRADE_TONE.confirmed);
  });

  it('「未定」用中性色，不得与「已否证」同色（PRD §2.3：未定不等于否证）', () => {
    expect(GRADE_TONE.undetermined).toBe('neutral');
    expect(GRADE_TONE.refuted).toBe('danger');
  });
});

describe('原始读取器：形状不对就退化成未记录', () => {
  it('0 是数据，null / undefined / 非数值才是未记录', () => {
    expect(countCellOf(0)).toEqual({ value: '0', recorded: true });
    expect(countCellOf(null).recorded).toBe(false);
    expect(countCellOf(undefined).recorded).toBe(false);
    expect(countCellOf('12').recorded).toBe(false);
    expect(countCellOf(true).recorded).toBe(false);
  });

  it('NaN 与 Infinity 不算已记录：渲染出来会是 "NaN" 而不是一个数', () => {
    expect(countCellOf(Number.NaN).recorded).toBe(false);
    expect(statCell(Number.POSITIVE_INFINITY).recorded).toBe(false);
  });

  it('统计量默认四位小数，p 值不会被截成 0.000', () => {
    expect(statCell(0.00021)).toEqual({ value: '0.0002', recorded: true });
    expect(statCell(0.00021, 6).value).toBe('0.000210');
    expect(statCell(0).value).toBe('0.0000');
  });

  it('三值布尔：false 是「否」，null 是未记录，两者不同', () => {
    expect(flagCell(true)).toEqual({ value: '是', recorded: true });
    expect(flagCell(false)).toEqual({ value: '否', recorded: true });
    expect(flagCell(null)).toEqual({ value: '未记录', recorded: false });
    expect(flagCell('true').recorded).toBe(false);
  });
});

describe('buildPhenomenonRows', () => {
  it('完整 payload 的 15 个键全部落位', () => {
    const [row] = buildPhenomenonRows(
      [{ claim_id: 'C1', grade: 'confirmed', payload: FULL_PAYLOAD }],
      [],
    );
    expect(row.claimId).toBe('C1');
    expect(row.grade).toBe('confirmed');
    expect(row.rawGrade).toBe('confirmed');
    expect(row.split).toEqual({ value: 'val', recorded: true });
    expect(row.n).toEqual({ value: '1200', recorded: true });
    expect(row.nPos).toEqual({ value: '30', recorded: true });
    expect(row.nNeg.value).toBe('1170');
    expect(row.effect.value).toBe('0.0825');
    expect(row.ciLow.value).toBe('0.0310');
    expect(row.ciHigh.value).toBe('0.1340');
    expect(row.p.value).toBe('0.0002');
    expect(row.e.value).toBe('12.5000');
    expect(row.directionOk).toEqual({ value: '是', recorded: true });
    // temporal_ok = false 必须显示「否」，不能被当成缺失。
    expect(row.temporalOk).toEqual({ value: '否', recorded: true });
    expect(row.rhoMaxAbs.value).toBe('0.0700');
    expect(row.incrGain.value).toBe('0.0150');
    expect(row.incrCiLow.value).toBe('-0.0020');
    expect(row.incrCiHigh.value).toBe('0.0320');
  });

  it('五个可选统计量为 null 时显示未记录', () => {
    const [row] = buildPhenomenonRows(
      [
        {
          claim_id: 'C1',
          grade: 'undetermined',
          payload: {
            ...FULL_PAYLOAD,
            temporal_ok: null,
            rho_max_abs: null,
            incr_gain: null,
            incr_ci_low: null,
            incr_ci_high: null,
          },
        },
      ],
      [],
    );
    const optionals = [
      row.temporalOk,
      row.rhoMaxAbs,
      row.incrGain,
      row.incrCiLow,
      row.incrCiHigh,
    ];
    for (const cell of optionals) {
      expect(cell).toEqual({ value: '未记录', recorded: false });
    }
  });

  it('payload 整个缺失时不抛异常，所有统计格子都是未记录', () => {
    const [row] = buildPhenomenonRows([{ claim_id: 'C1', grade: 'refuted' }], []);
    expect(row.grade).toBe('refuted');
    expect(row.effect.recorded).toBe(false);
    expect(row.n.recorded).toBe(false);
    expect(row.directionOk.recorded).toBe(false);
  });

  it('契约外的判级字符串：grade 为 null，rawGrade 原样保留', () => {
    const [row] = buildPhenomenonRows([{ claim_id: 'C1', grade: 'supported' }], []);
    expect(row.grade).toBeNull();
    expect(row.rawGrade).toBe('supported');
  });

  it('非对象条目与缺 claim_id 都退化成未记录而不是崩掉', () => {
    const rows = buildPhenomenonRows(
      [null as never, 'oops' as never, { grade: 'confirmed' }],
      [],
    );
    expect(rows).toHaveLength(3);
    for (const row of rows) expect(row.claimId).toBe('未记录');
    expect(rows[2].grade).toBe('confirmed');
  });

  it('预注册哈希按 claim_id 关联，关联不上就是 null', () => {
    const rows = buildPhenomenonRows(
      [
        { claim_id: 'C1', grade: 'confirmed', payload: FULL_PAYLOAD },
        { claim_id: 'C2', grade: 'refuted', payload: FULL_PAYLOAD },
      ],
      [{ claim_id: 'C1', hash: 'abc123def456' }],
    );
    expect(rows[0].preregHash).toBe('abc123def456');
    expect(rows[1].preregHash).toBeNull();
  });

  it('preregistration 条目缺 hash 时不建立关联', () => {
    const rows = buildPhenomenonRows([{ claim_id: 'C1', grade: 'confirmed' }], [{ claim_id: 'C1' }]);
    expect(rows[0].preregHash).toBeNull();
  });

  it('undefined 列表返回空数组', () => {
    expect(buildPhenomenonRows(undefined, undefined)).toEqual([]);
  });
});

describe('沙箱失败只能从事件流拿', () => {
  it('只挑 claim_sandbox_failed，其余事件类型忽略', () => {
    const failures = collectSandboxFailures([
      event('claim_proposed', { claim_id: 'C1' }),
      event('claim_sandbox_failed', {
        claim_id: 'C2',
        error_type: 'SyntaxError',
        error: 'unexpected EOF',
        stage: 'sandbox',
      }),
      event('claim_graded', { claim_id: 'C3', grade: 'confirmed' }),
      event('claim_sandbox_failed', { claim_id: 'C4' }),
    ]);
    expect(failures).toHaveLength(2);
    expect(failures[0]).toEqual({
      claimId: 'C2',
      errorType: 'SyntaxError',
      error: 'unexpected EOF',
      stage: 'sandbox',
    });
  });

  it('缺字段时退化成 null / 未记录，不编造错误文本', () => {
    const [failure] = collectSandboxFailures([event('claim_sandbox_failed', {})]);
    expect(failure.claimId).toBe('未记录');
    expect(failure.errorType).toBeNull();
    expect(failure.error).toBeNull();
    expect(failure.stage).toBeNull();
  });

  it('payload 不是对象时不抛异常', () => {
    const broken = { run_id: 'r1', type: 'claim_sandbox_failed', payload: 'x' } as never;
    expect(collectSandboxFailures([broken])).toHaveLength(1);
  });
});

describe('partitionSandboxFailures：失败与「未定」必须分开', () => {
  const tested = buildPhenomenonRows(
    [
      { claim_id: 'C1', grade: 'confirmed', payload: FULL_PAYLOAD },
      { claim_id: 'C2', grade: 'undetermined', payload: FULL_PAYLOAD },
    ],
    [],
  );

  it('有检验结果的落 matched，没有的落 untested', () => {
    const failures = collectSandboxFailures([
      event('claim_sandbox_failed', { claim_id: 'C1' }),
      event('claim_sandbox_failed', { claim_id: 'C9' }),
    ]);
    const parts = partitionSandboxFailures(tested, failures);
    expect(parts.matched.map((f) => f.claimId)).toEqual(['C1']);
    expect(parts.untested.map((f) => f.claimId)).toEqual(['C9']);
  });

  it('同一条失败不会同时出现在两边', () => {
    const failures = collectSandboxFailures([event('claim_sandbox_failed', { claim_id: 'C9' })]);
    const parts = partitionSandboxFailures(tested, failures);
    expect(parts.matched).toHaveLength(0);
    expect(parts.untested).toHaveLength(1);
  });

  it('没有任何现象行时，全部失败都是 untested', () => {
    const failures = collectSandboxFailures([
      event('claim_sandbox_failed', { claim_id: 'C1' }),
      event('claim_sandbox_failed', { claim_id: 'C2' }),
    ]);
    const parts = partitionSandboxFailures([], failures);
    expect(parts.matched).toHaveLength(0);
    expect(parts.untested).toHaveLength(2);
  });
});

describe('buildControlRows', () => {
  it('ControlReport 五个字段落位，passed 是三值', () => {
    const [row] = buildControlRows([
      {
        neg_trials: 200,
        neg_false_positives: 0,
        neg_fpr: 0,
        planted: { signal_a: { trials: 20, recovered: 18 } },
        passed: true,
      },
    ]);
    expect(row.negTrials).toEqual({ value: '200', recorded: true });
    expect(row.negFalsePositives).toEqual({ value: '0', recorded: true });
    expect(row.negFpr).toEqual({ value: '0.0000', recorded: true });
    expect(row.passed).toEqual({ value: '是', recorded: true });
    expect(row.planted).toEqual([{ name: 'signal_a', trials: 20, recovered: 18 }]);
  });

  it('passed = false 显示「否」，缺失显示未记录', () => {
    const rows = buildControlRows([{ passed: false }, {}]);
    expect(rows[0].passed).toEqual({ value: '否', recorded: true });
    expect(rows[1].passed).toEqual({ value: '未记录', recorded: false });
  });

  it('planted 按名称排序，保证两次渲染顺序一致', () => {
    const [row] = buildControlRows([
      { planted: { zeta: { trials: 1, recovered: 1 }, alpha: { trials: 2, recovered: 0 } } },
    ]);
    expect(row.planted.map((entry) => entry.name)).toEqual(['alpha', 'zeta']);
  });

  it('planted 内层缺值时是 null，不是 0', () => {
    const [row] = buildControlRows([{ planted: { alpha: {} } }]);
    expect(row.planted[0]).toEqual({ name: 'alpha', trials: null, recovered: null });
  });

  it('planted 不是对象时当成空', () => {
    const [row] = buildControlRows([{ planted: 'nope' }]);
    expect(row.planted).toEqual([]);
  });
});

describe('buildCertificateRows', () => {
  const CERT = {
    mechanism_id: 'M1',
    rival_id: 'R1',
    test_id: 'T-cross-env',
    test_type: 'invariance',
    env: 'hdd_val',
    stat: 3.2,
    ci: [1.1, 5.4],
    e_value: 18.7,
    prereg_hash: 'deadbeefcafe1234',
    date: '2026-10-02T10:00:00+00:00',
  };

  it('十个字段全部落位，ci 二元组拆成上下界', () => {
    const [row] = buildCertificateRows([CERT]);
    expect(row.mechanismId).toBe('M1');
    expect(row.rivalId).toBe('R1');
    expect(row.testId).toBe('T-cross-env');
    expect(row.testType).toEqual({ value: 'invariance', recorded: true });
    expect(row.env).toEqual({ value: 'hdd_val', recorded: true });
    expect(row.stat.value).toBe('3.2000');
    expect(row.ciLow.value).toBe('1.1000');
    expect(row.ciHigh.value).toBe('5.4000');
    expect(row.eValue.value).toBe('18.7000');
    expect(row.preregHash).toBe('deadbeefcafe1234');
    expect(row.date.value).toBe('2026-10-02T10:00:00+00:00');
  });

  it('ci 缺失或不是数组时上下界都是未记录', () => {
    for (const ci of [undefined, null, 'x', 5]) {
      const [row] = buildCertificateRows([{ ...CERT, ci }]);
      expect(row.ciLow.recorded).toBe(false);
      expect(row.ciHigh.recorded).toBe(false);
    }
  });

  it('ci 只有一元时下界有值、上界未记录', () => {
    const [row] = buildCertificateRows([{ ...CERT, ci: [1.1] }]);
    expect(row.ciLow.value).toBe('1.1000');
    expect(row.ciHigh.recorded).toBe(false);
  });

  it('没有 status 字段可读，因此不产出任何状态', () => {
    const [row] = buildCertificateRows([{ ...CERT, status: 'valid' }]);
    // 后端即使多写了 status，前端也不渲染它：Certificate 没有这个字段，
    // 显示出来就等于自设判级标准。
    expect(Object.keys(row)).not.toContain('status');
  });
});

describe('计数组：来自 run_summary，不是 discovery 制品', () => {
  it('discovery 为 null 时三组计数全部未记录', () => {
    for (const rows of [
      mechanismCounterRows(null),
      tournamentCounterRows(null),
      validityCounterRows(null),
    ]) {
      expect(rows.length).toBeGreaterThan(0);
      for (const row of rows) expect(row.cell.recorded).toBe(false);
    }
  });

  it('辩论赛计数的标签不含任何胜负措辞', () => {
    const labels = tournamentCounterRows(null).map((row) => row.label);
    expect(labels).toEqual([
      '辩论轮数',
      '已进行对阵',
      '判出胜负的对阵',
      '功效不足的平局',
      '签发的证书',
      '最小可检测效应',
    ]);
    for (const label of labels) {
      expect(label).not.toMatch(/胜者|获胜|最优机制|推荐/);
    }
  });

  it('计数为 0 时显示 0，不显示未记录', () => {
    const discovery: RunDiscoveryResponse = {
      matches_played: 0,
      decisive_matches: 0,
      certificates_issued: 0,
      mechanisms_proposed: 4,
      tournament_rounds: 2,
      min_detectable_effect: 0.05,
    };
    const byLabel = new Map(tournamentCounterRows(discovery).map((r) => [r.label, r.cell]));
    expect(byLabel.get('已进行对阵')).toEqual({ value: '0', recorded: true });
    expect(byLabel.get('判出胜负的对阵')).toEqual({ value: '0', recorded: true });
    expect(byLabel.get('辩论轮数')).toEqual({ value: '2', recorded: true });
    expect(byLabel.get('最小可检测效应')?.value).toBe('0.0500');

    const mech = new Map(mechanismCounterRows(discovery).map((r) => [r.label, r.cell]));
    expect(mech.get('提出的机制')).toEqual({ value: '4', recorded: true });
    // 没给的字段仍然是未记录，不能因为同对象里有别的值就补 0。
    expect(mech.get('确立的机制')?.recorded).toBe(false);
  });

  it('方法学校验组包含植入回收、Kendall τ 与打乱环境误通过率', () => {
    const labels = validityCounterRows(null).map((row) => row.label);
    expect(labels).toContain('植入机制回收率');
    expect(labels).toContain('LLM 与数据的 Kendall τ');
    expect(labels).toContain('打乱环境后的误通过率');
    expect(labels).toContain('负对照 FPR');
  });
});

describe('discoveryEmptyState：三种空各不相同（PRD 12.1）', () => {
  it('enabled = false：是配置选择，不是失败', () => {
    const empty = discoveryEmptyState(false, 'missing', '现象记录');
    expect(empty.title).toBe('这次运行没有开启知识发现');
    expect(empty.reason).toContain('配置选择，不是失败');
    expect(empty.nextStep).toContain('discovery.enabled');
  });

  it('制品目录在但文件从未写出：说 missing，并指向事件流', () => {
    const empty = discoveryEmptyState(true, 'missing', '现象记录');
    expect(empty.title).toBe('没有写出现象记录文件');
    expect(empty.reason).toContain('从未被写出');
    expect(empty.nextStep).toContain('claim_*');
  });

  it('available + 空列表：流水线跑完了但没产出，是真实的空结果', () => {
    const empty = discoveryEmptyState(true, 'available', '现象记录');
    expect(empty.title).toBe('现象记录为空');
    expect(empty.reason).toContain('真实的空结果，不是读取失败');
  });

  it('enabled 为 null 时不宣称「没开启」，落到文件状态判断', () => {
    const empty = discoveryEmptyState(null, 'available', '现象记录');
    expect(empty.title).toBe('现象记录为空');
    expect(empty.reason).not.toContain('没有开启');
  });
});


