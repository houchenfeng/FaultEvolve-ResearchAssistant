import { describe, expect, it } from 'vitest';

import { timelineGaps } from '@/features/workbench/timeline-gap';

describe('时间轴缺口', () => {
  it('事件条数少于完成轮次时写明差额，且不编造分数', () => {
    const gaps = timelineGaps({ iterationsDone: 10, iterationEvents: 7 });
    expect(gaps).toEqual([
      {
        id: 'iteration-shortfall',
        text: '制品记录完成 10 轮，iteration_complete 事件 7 条，少 3 条。时间轴不补这些轮次的分数。',
      },
    ]);
    expect(gaps[0].text).not.toMatch(/\d+\.\d+/);
  });

  it('条数一致时不报缺口', () => {
    expect(timelineGaps({ iterationsDone: 4, iterationEvents: 4 })).toEqual([]);
  });

  it('一边未记录时不把缺失当成 0', () => {
    const gaps = timelineGaps({ iterationsDone: 5, iterationEvents: null });
    expect(gaps[0].text).toContain('未记录');
    expect(gaps[0].text).not.toContain('少 5');
  });

  it('原样展示事件页 warning，不与轮次差额合并成一个新数字', () => {
    const gaps = timelineGaps({
      iterationsDone: 2,
      iterationEvents: 2,
      warnings: [{ field: 'events', reason: 'jsonl 12 行，数据库 15 行' }],
    });
    expect(gaps.map((gap) => gap.text)).toEqual(['jsonl 12 行，数据库 15 行']);
  });
});
