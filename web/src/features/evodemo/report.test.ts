import tree from '../../../../showcase/runs/hdd_mvp_showcase_c89e2a01/tree.json';

import { DEMO_REPORT_INPUT } from './demo-script';
import { CHAPTERS, buildRunReport, narrate, reportInputFromTree } from './report';

describe('buildRunReport', () => {
  it('derives the demo story from data alone', () => {
    const report = buildRunReport(DEMO_REPORT_INPUT);
    expect(report.best.id).toBe('T6');
    expect(report.lineage.map((n) => n.id)).toEqual(['T0', 'T1A', 'T2C', 'T3B', 'T4A', 'T5A', 'T6']);
    expect(report.keyImprovements[0].node.id).toBe('T6');
    expect(report.steps.filter((s) => s.borrowedFrom).map((s) => s.node.id)).toEqual(['T4A', 'T6']);
    expect(report.confirmed).toHaveLength(1);
  });

  it('works on a real single-branch tree.json without any demo data', () => {
    const report = buildRunReport(
      reportInputFromTree(tree, { taskName: 'HDD', metricName: 'ROS', claims: [] }),
    );
    expect(report.best.id).toBe('n18a3b4dd');
    expect(report.root.id).toBe('n0a1b2c3');
    expect(report.lineage.at(-1)).toBe(report.best);
    expect(report.counts.failed).toBe(2);
    expect(report.steps.every((s) => s.parent.id === s.node.parentId)).toBe(true);
    for (let i = 0; i < CHAPTERS.length; i += 1) {
      expect(narrate(report, i)).not.toMatch(/undefined|NaN/);
    }
    expect(narrate(report, 3)).toContain('没有产生确认式知识');
  });

  it('respects lower-is-better metrics', () => {
    const report = buildRunReport({
      runId: 'r',
      taskName: 't',
      metricName: 'loss',
      higherIsBetter: false,
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
