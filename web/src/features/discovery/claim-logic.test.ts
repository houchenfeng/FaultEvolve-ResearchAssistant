/**
 * 现象与假设检验的渲染（TODO 6.2，含阶段 6 测试要求 1 / 2 / 3）。
 *
 * 三个要求各有一段：
 * - 「discovery disabled 空状态」→ `describe('空状态')`
 * - 「claim sandbox failure」→ `describe('沙箱失败')`
 * - 「confirmed/refuted/undetermined 映射」→ `describe('grade 映射')`
 *
 * 其余断言来自引擎的真实写入行为（`discovery/pipeline.py`），不是假想：
 * 评分为 `{**ClaimTestResult, "grade": ...}`、沙箱失败为 `{"error": ...}`，
 * 两者都把散文覆盖掉。
 */
import { describe, expect, it } from 'vitest';

import {
  buildPhenomenaView,
  buildPhenomenonRow,
  claimsById,
  effectVerdict,
  gradeVerdict,
  PROSE_LOST_AFTER_GRADING,
  phenomenaEmptyReason,
  proseLossNote,
  sandboxFailure,
  sandboxNote,
  testStatistics,
} from '@/features/discovery/claim-logic';
import type { DiscoveryResponse, ClaimRowFields } from '@/features/discovery/types';

function discovery(overrides: Partial<DiscoveryResponse> = {}): DiscoveryResponse {
  return {
    run_id: 'hdd_mvp_demo_7510f100',
    contract_version: '1.5.0',
    enabled: true,
    phenomena: [],
    claims: [],
    ...overrides,
  } as DiscoveryResponse;
}

describe('空状态（测试要求：discovery disabled 空状态）', () => {
  it('未启用时报"未启用"，而不是"没有现象"', () => {
    const view = buildPhenomenaView(discovery({ enabled: false }));
    expect(view.rows).toEqual([]);
    expect(phenomenaEmptyReason(view)).toBe('知识发现未启用，本次运行没有进行假设检验');
  });

  it('启用了但文件不存在 ⇒ 说的是"没有这个文件"', () => {
    const view = buildPhenomenaView(
      discovery({ enabled: true, phenomena_state: 'missing' }),
    );
    expect(phenomenaEmptyReason(view)).toContain('没有现象文件');
  });

  it('启用了、文件在、但一条现象都没有 ⇒ 第三句话', () => {
    const view = buildPhenomenaView(
      discovery({ enabled: true, phenomena_state: 'available' }),
    );
    expect(phenomenaEmptyReason(view)).toBe('知识发现已启用，但本次运行没有产生任何现象记录');
  });

  it('有行时不需要空状态文案', () => {
    const view = buildPhenomenaView(
      discovery({ phenomena: [{ claim_id: 'C-1', grade: 'confirmed' }] }),
    );
    expect(phenomenaEmptyReason(view)).toBeNull();
  });
});

describe('grade 映射（测试要求：confirmed/refuted/undetermined）', () => {
  it('五个取值各有中文名与语义', () => {
    expect(gradeVerdict('confirmed').label).toBe('已证实');
    expect(gradeVerdict('revised').label).toBe('已修正');
    expect(gradeVerdict('discovered').label).toBe('新发现');
    expect(gradeVerdict('refuted').label).toBe('被否证');
    expect(gradeVerdict('undetermined').label).toBe('未定');
  });

  it('undetermined 是"证据不足"，不是"没有评级"', () => {
    const undetermined = gradeVerdict('undetermined');
    expect(undetermined.key).toBe('undetermined');
    expect(undetermined.reason).toContain('不足以');
    // 不能把它说成"没有效应"
    expect(undetermined.reason).toContain('不等于');
  });

  it('null / undefined / 未知值归到"未评级"，不猜', () => {
    for (const value of [null, undefined, '', 'something_new']) {
      const verdict = gradeVerdict(value);
      expect(verdict.key).toBeNull();
      expect(verdict.label).toBe('未评级');
    }
  });

  it('色调：证实/修正为正，否证为警示，未定为中性，未评级为暗', () => {
    expect(gradeVerdict('confirmed').tone).toBe('positive');
    expect(gradeVerdict('revised').tone).toBe('positive');
    expect(gradeVerdict('discovered').tone).toBe('brand');
    expect(gradeVerdict('refuted').tone).toBe('warning');
    expect(gradeVerdict('undetermined').tone).toBe('neutral');
    expect(gradeVerdict(null).tone).toBe('muted');
  });
});

describe('沙箱失败（测试要求：claim sandbox failure）', () => {
  const failed: ClaimRowFields = {
    id: 'C-7510f100-0002',
    status: 'sandbox_failed',
    // 引擎写的就是这个：update_claim(payload_json=json.dumps({"error": ...}))
    error: 'TimeoutError: 沙箱执行超时 30s',
  };

  it('识别沙箱失败并带出错误文本', () => {
    const failure = sandboxFailure(failed);
    expect(failure).not.toBeNull();
    expect(failure?.claimId).toBe('C-7510f100-0002');
    expect(failure?.detail.text).toContain('沙箱执行超时');
  });

  it('非沙箱失败的行返回 null', () => {
    expect(sandboxFailure({ id: 'C-1', status: 'graded' })).toBeNull();
    expect(sandboxFailure({ id: 'C-1', status: 'proposed' })).toBeNull();
  });

  it('状态是失败但错误详情没写 ⇒ 明说详情缺失，不编错误', () => {
    const failure = sandboxFailure({ id: 'C-9', status: 'sandbox_failed' });
    expect(failure?.detail.state).toBe('unrecorded');
    expect(failure?.detail.text).toBe('未记录');
    expect(failure?.reason).toContain('没有写进这份数据');
  });

  it('空字符串错误不算有详情', () => {
    expect(sandboxFailure({ id: 'C-9', status: 'sandbox_failed', error: '   ' })?.detail.state).toBe(
      'unrecorded',
    );
  });

  it('整页横幅能数出失败数，且无失败时不给横幅', () => {
    const view = buildPhenomenaView(discovery({ claims: [failed] }));
    expect(view.sandboxFailedCount).toBe(1);
    expect(sandboxNote(view)).toContain('1 条主张在沙箱里执行失败');

    expect(sandboxNote(buildPhenomenaView(discovery()))).toBeNull();
  });
});

describe('effect / CI', () => {
  it('CI 跨 0 ⇒ 不能当证据（即使 point estimate 为正）', () => {
    const verdict = effectVerdict(
      { effect: 0.001, ci_low: -0.02, ci_high: 0.03 },
      '+',
    );
    expect(verdict.crossesZero).toBe(true);
    expect(verdict.tone).toBe('muted');
    expect(verdict.reason).toContain('不能当作证据');
  });

  it('CI 不跨 0 且方向一致 ⇒ 正向', () => {
    const verdict = effectVerdict({ effect: 0.012, ci_low: 0.003, ci_high: 0.031 }, '+');
    expect(verdict.crossesZero).toBe(false);
    expect(verdict.matchesDirection).toBe(true);
    expect(verdict.tone).toBe('positive');
  });

  it('CI 不跨 0 但方向相反 ⇒ 警示', () => {
    const verdict = effectVerdict({ effect: -0.012, ci_low: -0.031, ci_high: -0.003 }, '+');
    expect(verdict.matchesDirection).toBe(false);
    expect(verdict.tone).toBe('warning');
    expect(verdict.reason).toContain('方向与预注册相反');
  });

  it('没有检验结果 ⇒ 未记录，不是"效应为 0"', () => {
    expect(effectVerdict(null, '+').state).toBe('unrecorded');
    expect(effectVerdict({}, '+').state).toBe('unrecorded');
  });

  it('没有 CI 时只说点估计，显著性判为"无法判断"', () => {
    const verdict = effectVerdict({ effect: 0.5 }, '+');
    expect(verdict.crossesZero).toBeNull();
    expect(verdict.reason).toContain('无法判断');
  });

  it('文本里带 effect 与区间，可直接渲染', () => {
    const verdict = effectVerdict({ effect: 0.012, ci_low: 0.003, ci_high: 0.031 }, '+');
    expect(verdict.text).toBe('effect +0.0120 [0.0030, 0.0310]');
  });
});

describe('检验统计数字', () => {
  it('n / p / e / 划分拼成一行', () => {
    const view = testStatistics({ n: 120, n_pos: 70, n_neg: 50, p: 0.0031, e: 12.5, split: 'confirm' });
    expect(view.text).toContain('n=120（70+ / 50-）');
    expect(view.text).toContain('p=0.0031');
    expect(view.text).toContain('e=12.500');
    expect(view.text).toContain('划分=confirm');
  });

  it('空 payload ⇒ 未记录', () => {
    expect(testStatistics(null).state).toBe('unrecorded');
    expect(testStatistics({ split: 'confirm' }).text).toBe('划分=confirm');
  });
});

describe('散文被覆盖（引擎覆盖式写入的后果）', () => {
  it('评分为 graded 的 claim 散文缺了 ⇒ 报未记录且解释原因', () => {
    const claim: ClaimRowFields = {
      id: 'C-1',
      status: 'graded',
      grade: 'confirmed',
      // 引擎评分后 payload 只剩测试结果 + grade，散文（title/condition/…）
      // 全部不在这一行里了 —— 这就是断言"未记录"的原因
      round: 0,
    };
    const row = buildPhenomenonRow({ claim_id: 'C-1', grade: 'confirmed' }, claimsById([claim]));
    expect(row.title.state).toBe('unrecorded');
    expect(row.condition.state).toBe('unrecorded');
    expect(row.falsifier.state).toBe('unrecorded');
    expect(row.status.text).toBe('已评分');
  });

  it('still proposed 的 claim 散文还在 ⇒ 正常显示', () => {
    const claim: ClaimRowFields = {
      id: 'C-2',
      status: 'proposed',
      title: '冷启动对早期收敛有正向作用',
      condition: 'iterations < 5',
      feature_code: 'warm_start_ratio',
      outcome: 'score',
      scope: 'hdd_mvp / public',
      falsifier: '若 CI 跨 0 则否证',
    };
    const row = buildPhenomenonRow({ claim_id: 'C-2' }, claimsById([claim]));
    expect(row.title.text).toBe('冷启动对早期收敛有正向作用');
    expect(row.condition.text).toBe('iterations < 5');
    expect(row.feature.text).toBe('warm_start_ratio');
    expect(row.scope.text).toBe('hdd_mvp / public');
    expect(row.falsifier.text).toBe('若 CI 跨 0 则否证');
  });

  it('整页横幅只在真有被覆盖的行时出现', () => {
    const graded: ClaimRowFields = { id: 'C-1', status: 'graded', grade: 'refuted' };
    const view = buildPhenomenaView(
      discovery({ phenomena: [{ claim_id: 'C-1', grade: 'refuted' }], claims: [graded] }),
    );
    expect(view.proseLostCount).toBe(1);
    expect(proseLossNote(view)).toContain(PROSE_LOST_AFTER_GRADING);

    expect(proseLossNote(buildPhenomenaView(discovery()))).toBeNull();
  });

  it('现象有、claim 行没有 ⇒ orphan 被暴露，不静默', () => {
    const view = buildPhenomenaView(
      discovery({ phenomena: [{ claim_id: 'C-missing', grade: 'confirmed' }], claims: [] }),
    );
    expect(view.orphanCount).toBe(1);
    expect(view.rows[0].hasClaimRow).toBe(false);
  });

  it('grade 优先取现象条目的值，回落到 claim 行', () => {
    const claim: ClaimRowFields = { id: 'C-1', status: 'graded', grade: 'refuted' };
    const index = claimsById([claim]);

    // phenomena 里写了 grade ⇒ 用它
    expect(buildPhenomenonRow({ claim_id: 'C-1', grade: 'confirmed' }, index).grade.key).toBe(
      'confirmed',
    );
    // 现象里没有 ⇒ 回落到 claim 行
    expect(buildPhenomenonRow({ claim_id: 'C-1' }, index).grade.key).toBe('refuted');
  });

  it('claimsById 对重复 id 保留第一条，顺序不影响结果', () => {
    const index = claimsById([
      { id: 'C-1', status: 'graded', title: '第一条' },
      { id: 'C-1', status: 'proposed', title: '第二条' },
    ]);
    expect(index.get('C-1')?.title).toBe('第一条');
    expect(index.size).toBe(1);
  });

  it('没有 id 的行不进索引', () => {
    const index = claimsById([{ status: 'proposed' }, { id: '', status: 'proposed' }]);
    expect(index.size).toBe(0);
  });
});
