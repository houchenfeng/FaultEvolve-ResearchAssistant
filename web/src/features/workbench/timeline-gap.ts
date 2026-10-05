/**
 * 时间轴缺口（PRD §22.1.11）。
 *
 * 只转述后端已经记下的两个数和事件页 warning：
 * `RunOutcomeResponse.iterations_done` / `iteration_events`，以及
 * `EventPageResponse.warnings`（jsonl 与数据库条数不一致等）。
 *
 * 不数当前已加载的事件列表。事件接口有分页，少拉一页会被误报成缺轮次。
 * 也不补分数点。
 */
import type { ContractWarning } from '@/generated/api';

export interface TimelineGap {
  id: string;
  text: string;
}

export function timelineGaps(input: {
  iterationsDone: number | null | undefined;
  iterationEvents: number | null | undefined;
  warnings?: ContractWarning[] | null;
}): TimelineGap[] {
  const gaps: TimelineGap[] = [];

  for (const warning of input.warnings ?? []) {
    const reason = warning.reason?.trim();
    if (!reason) continue;
    gaps.push({
      id: `warning:${warning.field}:${reason}`,
      text: reason,
    });
  }

  const done = input.iterationsDone;
  const recorded = input.iterationEvents;
  if (done == null && recorded == null) return gaps;

  if (done == null || recorded == null) {
    gaps.push({
      id: 'iteration-unrecorded',
      text:
        done == null
          ? '完成轮次未记录，不能判断事件是否少了轮次。'
          : `完成轮次已记录为 ${done}，iteration_events 未记录，不能判断事件是否少了轮次。`,
    });
    return gaps;
  }

  if (recorded < done) {
    gaps.push({
      id: 'iteration-shortfall',
      text: `制品记录完成 ${done} 轮，iteration_complete 事件 ${recorded} 条，少 ${done - recorded} 条。时间轴不补这些轮次的分数。`,
    });
  } else if (recorded > done) {
    gaps.push({
      id: 'iteration-surplus',
      text: `iteration_complete 事件 ${recorded} 条，多于完成轮次 ${done}。多出的事件不会被当成额外得分。`,
    });
  }

  return gaps;
}
