/**
 * 显著性四档的判定与解释（TODO 5.4）。
 *
 * 最重要的一条：`unknown` 必须与 `noise` 严格分开。
 * 前者是"没有数据，无法判断"，后者是"有数据，判定为噪声"。
 * 混为一谈会让用户以为系统知道结果其实不知道 —— PRD §9.4 明确禁止。
 */
import { describe, expect, it } from 'vitest';

import type { TreeNodeDto } from '@/generated/api';
import {
  bandStateOf,
} from '@/features/workbench/tree-adapter';
import {
  classifySignificance,
  explainSignificance,
  significanceAccent,
  significanceCounts,
} from '@/features/workbench/significance';

function node(overrides: Partial<TreeNodeDto> = {}): TreeNodeDto {
  return {
    id: 'n-00000001',
    branch_id: 'main',
    depth: 0,
    operator: 'init',
    hypothesis_status: 'undetermined',
    status: 'done',
    score: 10,
    delta_score: 0.5,
    noise_delta: 1,
    within_noise_band: false,
    ...overrides,
  };
}

describe('四档判定', () => {
  it('超出噪声带 ⇒ progress', () => {
    expect(classifySignificance(node({ within_noise_band: false }))).toBe('progress');
  });

  it('落在噪声带内 ⇒ noise', () => {
    expect(classifySignificance(node({ within_noise_band: true }))).toBe('noise');
  });

  it('噪声带未知 ⇒ unknown，不是 noise', () => {
    // 这一条是本模块存在的理由：null 判成 noise 会谎报"我们确认这是噪声"。
    expect(classifySignificance(node({ within_noise_band: null }))).toBe('unknown');
    expect(classifySignificance(node({ within_noise_band: undefined }))).toBe('unknown');
  });

  it('缺 Δ 时（根节点常见）也是 unknown', () => {
    expect(classifySignificance(node({ delta_score: null, within_noise_band: null }))).toBe(
      'unknown',
    );
  });

  it('is_best 优先于一切其它判定', () => {
    // 最优节点即使落在噪声带内也必须显示为 best，否则用户找不到当前最优解。
    expect(
      classifySignificance(node({ is_best: true, within_noise_band: true })),
    ).toBe('best');
    expect(classifySignificance(node({ is_best: true, within_noise_band: null }))).toBe('best');
  });
});

describe('解释文案', () => {
  it('有效改进带上具体 Δ 与噪声带数值', () => {
    const verdict = explainSignificance(node({ delta_score: 2.5, noise_delta: 0.5 }));
    expect(verdict.label).toBe('有效改进');
    expect(verdict.reason).toContain('2.500');
    expect(verdict.reason).toContain('0.500');
  });

  it('噪声内的变化说清"不能作为证据"', () => {
    const verdict = explainSignificance(
      node({ within_noise_band: true, delta_score: 0.1, noise_delta: 1 }),
    );
    expect(verdict.label).toBe('噪声内');
    expect(verdict.reason).toContain('不能作为改进证据');
  });

  it('无 Δ 时明说"没有记录 Δ"，不编造数值', () => {
    const verdict = explainSignificance(node({ delta_score: null, within_noise_band: null }));
    expect(verdict.label).toBe('无法判断');
    expect(verdict.reason).toContain('没有记录 Δ');
    expect(verdict.reason).not.toContain('NaN');
  });

  it('有 Δ 但缺噪声估计时，说明缺的是噪声估计', () => {
    const verdict = explainSignificance(
      node({ delta_score: 1.2, noise_delta: null, within_noise_band: null }),
    );
    expect(verdict.reason).toContain('缺少噪声估计');
    expect(verdict.reason).toContain('1.200');
  });

  it('未评分的最优节点不会显示 NaN', () => {
    const verdict = explainSignificance(node({ is_best: true, score: null }));
    expect(verdict.reason).toContain('未评分');
  });

  it('四档的 tone 各不相同，视觉可分', () => {
    const tones = new Set(
      ([
        node({ is_best: true }),
        node({ within_noise_band: false }),
        node({ within_noise_band: true }),
        node({ within_noise_band: null }),
      ] as TreeNodeDto[]).map((item) => explainSignificance(item).tone),
    );
    expect(tones.size).toBe(4);
  });
});

describe('与树适配层判定一致', () => {
  it('同一个节点在两处得到同一档（TODO 5.4 禁止多处各自判断）', () => {
    const sample = node({ within_noise_band: true });
    const fromSignificance = classifySignificance(sample);
    const fromBand = bandStateOf(sample);
    // noise 档 ⇔ 噪声带内；progress 档 ⇔ 噪声带外。
    expect(fromSignificance === 'noise').toBe(fromBand === 'inside');
    expect(fromSignificance === 'progress').toBe(fromBand === 'outside');
  });

  it('accent 四档给出不同色值', () => {
    const accents = new Set(
      (['best', 'progress', 'noise', 'unknown'] as const).map(significanceAccent),
    );
    expect(accents.size).toBe(4);
  });
});

describe('分布统计', () => {
  it('四档计数之和等于节点总数', () => {
    const nodes = [
      node({ is_best: true }),
      node({ within_noise_band: false }),
      node({ within_noise_band: true }),
      node({ within_noise_band: null }),
    ];
    const counts = significanceCounts(nodes);
    expect(Object.values(counts).reduce((sum, n) => sum + n, 0)).toBe(nodes.length);
    expect(counts.best).toBe(1);
  });

  it('空树返回全零', () => {
    expect(significanceCounts([])).toEqual({ best: 0, progress: 0, noise: 0, unknown: 0 });
  });
});
