import tree from '../../../../showcase/runs/hdd_mvp_showcase_c89e2a01/tree.json';

import { PAPER_CASE, PAPER_NODES, WINNER_ID } from './cases/paper';
import { DEMO_REPORT_INPUT } from './demo-script';
import { CHAPTERS, buildRunReport, chapterTitles, narrate, reportInputFromTree } from './report';

describe('buildRunReport · chain', () => {
  it('derives the KGTE story from data alone', () => {
    const report = buildRunReport(DEMO_REPORT_INPUT);
    expect(report.structure).toBe('chain');
    expect(report.best.id).toBe('T6');
    expect(report.lineage.map((n) => n.id)).toEqual(['T0', 'T1A', 'T2C', 'T3B', 'T4A', 'T5A', 'T6']);
    expect(report.keyImprovements[0].node.id).toBe('T6');
    expect(report.steps.filter((s) => s.borrowedFrom).map((s) => s.node.id)).toEqual(['T4A', 'T6']);
    expect(report.confirmed).toHaveLength(1);
    expect(chapterTitles(report)[2]).toBe('改进点');
  });

  it('works on a real single-branch tree.json without any demo data', () => {
    const report = buildRunReport(reportInputFromTree(tree, { taskName: 'HDD', metric: { label: 'ROS' }, claims: [] }));
    expect(report.best.id).toBe('n18a3b4dd');
    expect(report.root.id).toBe('n0a1b2c3');
    expect(report.lineage.at(-1)).toBe(report.best);
    expect(report.counts.failed).toBe(2);
    for (let i = 0; i < CHAPTERS.length; i += 1) {
      expect(narrate(report, i)).not.toMatch(/undefined|NaN/);
    }
    expect(narrate(report, 3)).toContain('没有产生新知识');
  });

  it('respects lower-is-better metrics', () => {
    const report = buildRunReport({
      runId: 'r',
      taskName: 't',
      metric: { label: 'loss', higherIsBetter: false },
      nodes: [
        { id: 'a', depth: 0, score: 1, operator: 'init', title: 'a', status: 'ok' },
        { id: 'b', parentId: 'a', depth: 1, score: 0.4, operator: 'refine', title: 'b', status: 'ok' },
        { id: 'c', parentId: 'a', depth: 1, score: 2, operator: 'refine', title: 'c', status: 'ok' },
      ],
    });
    expect(report.best.id).toBe('b');
    expect(report.gain).toBeCloseTo(0.6);
  });
});

describe('paper combination case', () => {
  const report = PAPER_CASE.report;

  it('promotes exactly the Mitra × TabM geometric mean, as recorded in nodes.json', () => {
    expect(PAPER_NODES.filter((n) => n.outcome === 'promoted').map((n) => n.id)).toEqual([WINNER_ID]);
    expect(PAPER_NODES.find((n) => n.id === 'modernnca')?.outcome).toBe('silent');
    expect(PAPER_CASE.steps.at(-1)).toEqual({ kind: 'finish', bestScore: 1 });
  });

  it('explains rejections with the parent that won the failing check', () => {
    const mean = PAPER_NODES.find((n) => n.operator === 'fixed_mean' && [...n.parents].sort().join() === 'mitra,tabm');
    expect(mean?.reason).toBe('Q1 误告 0.0703% 高于 Mitra 的 0.0603%');
  });

  it('reports a combination against both parents', () => {
    expect(report.structure).toBe('combination');
    expect(report.parents.map((p) => p.id).sort()).toEqual(['mitra', 'tabm']);
    expect(report.wins.map((r) => r.def.label)).toEqual(['Q1 精确率', 'Q1 误告率', 'Q2 精确率', 'Q2 误告率']);
    expect(report.tradeoffs.map((r) => r.def.label)).toEqual(['Q1 召回率', 'Q2 召回率']);
    const q1 = report.metricRows[0];
    expect(q1.best).toBeCloseTo(42.818, 2);
    expect(q1.delta).toBeCloseTo(42.818 - 29.847, 2);
  });

  it('uses same-parent siblings as the operator ablation', () => {
    expect(report.siblings.map((s) => s.operator).sort()).toEqual(['fixed_mean', 'learned_disagreement']);
    expect(report.siblings.every((s) => s.status === 'pruned')).toBe(true);
  });

  it('narrates the essence chapter from the knowledge card', () => {
    expect(chapterTitles(report)[2]).toBe('本质创新');
    expect(narrate(report, 2)).toContain('「共识风险 × 一致性折扣」');
    expect(narrate(report, 3)).toContain('候选知识');
    for (let i = 0; i < CHAPTERS.length; i += 1) {
      expect(narrate(report, i)).not.toMatch(/undefined|NaN/);
    }
  });
});
