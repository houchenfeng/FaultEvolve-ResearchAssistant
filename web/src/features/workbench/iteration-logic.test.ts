/**
 * 事件流整理的纯逻辑测试（TODO 5.6）。
 *
 * 覆盖三个真实问题：轮询重放导致的事件重复、事件流没有"第几代"字段、
 * 以及前端不该硬编码事件类型清单（后端 catalog 已通过 meta 暴露）。
 */
import { describe, expect, it } from 'vitest';

import type { EventResponse } from '@/generated/api';
import {
  countEventTypes,
  dedupeEvents,
  EMPTY_EVENT_FILTER,
  eventLabel,
  eventTone,
  filterEvents,
  generationStats,
  nodeIdOf,
  splitGenerations,
} from './iteration-logic';
import { KNOWN_EVENT_NAMES } from './use-event-stream';

function event(id: number, type: string, payload: Record<string, unknown> = {}, ts = ''): EventResponse {
  return {
    id,
    run_id: 'run-1',
    type,
    payload,
    ts: ts || `2026-10-02T00:00:${String(id).padStart(2, '0')}`,
    is_known_type: true,
  };
}

describe('去重', () => {
  it('同一个 id 出现两次只保留一条', () => {
    // 轮询用 after_id 增量拉，但 Query 重放缓存会让同一个事件再次到达。
    const events = [event(1, 'init_evaluated'), event(1, 'init_evaluated'), event(2, 'run_finished')];
    expect(dedupeEvents(events)).toHaveLength(2);
  });

  it('重复时保留先出现的那条（后到的可能是旧缓存）', () => {
    const first = event(1, 'init_evaluated', { note: '本轮真实响应' });
    const replay = event(1, 'init_evaluated', { note: '重放的旧缓存' });
    expect(dedupeEvents([first, replay])[0]?.payload?.note).toBe('本轮真实响应');
  });

  it('按 id 升序输出，与到达顺序无关', () => {
    const events = [event(3, 'c'), event(1, 'a'), event(2, 'b')];
    expect(dedupeEvents(events).map((e) => e.id)).toEqual([1, 2, 3]);
  });

  it('没有 id 的事件无法去重，原样保留（契约允许 id 为 null）', () => {
    // 契约里 id 是 `int | None`，两种缺失形态都要覆盖。
    const nullId = { run_id: 'r', type: 'no-id', id: null, payload: {} };
    const missingId = { run_id: 'r', type: 'no-id', payload: {} };
    const result = dedupeEvents([event(1, 'a'), nullId, missingId, event(1, 'a')]);
    expect(result.filter((e) => e.id === null)).toHaveLength(1);
    expect(result.filter((e) => e.id === undefined)).toHaveLength(1);
    expect(result.filter((e) => e.id === 1)).toHaveLength(1);
  });

  it('空数组不炸', () => {
    expect(dedupeEvents([])).toEqual([]);
  });
});

describe('代际切分', () => {
  const stream = [
    event(1, 'init_evaluated'),
    event(2, 'smoke_passed'),
    event(3, 'iteration_complete'),
    event(4, 'operator_selected'),
    event(5, 'iteration_complete'),
    event(6, 'run_finished'),
  ];

  it('按 iteration_complete 切分，最后一段即使没有标记也保留', () => {
    const generations = splitGenerations(stream);
    expect(generations).toHaveLength(3);
    expect(generations[0]?.events.map((e) => e.id)).toEqual([1, 2, 3]);
    expect(generations[1]?.events.map((e) => e.id)).toEqual([4, 5]);
    // run_finished 之后没有 iteration_complete，仍要显示为一代（运行已结束）。
    expect(generations[2]?.events.map((e) => e.id)).toEqual([6]);
  });

  it('iteration_complete 归属它结束的那一代', () => {
    // 否则"这一代做成了什么"和"这一代结束了"会被拆到两组。
    const generations = splitGenerations(stream);
    expect(generations[0]?.events.at(-1)?.type).toBe('iteration_complete');
  });

  it('代 index 从 0 连续递增', () => {
    expect(splitGenerations(stream).map((g) => g.index)).toEqual([0, 1, 2]);
  });

  it('id 唯一，可直接用作 React key', () => {
    const ids = splitGenerations(stream).map((g) => g.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it('完全重复的事件流不会切出多余的代', () => {
    expect(splitGenerations([...stream, ...stream])).toHaveLength(3);
  });

  it('空流返回空数组', () => {
    expect(splitGenerations([])).toEqual([]);
  });
});

describe('代统计', () => {
  it('已正常收尾的代 closed 为 true', () => {
    const closed = splitGenerations([event(1, 'a'), event(2, 'iteration_complete')])[0];
    expect(closed && generationStats(closed).closed).toBe(true);
  });

  it('没有结束标记的代 closed 为 false（UI 要显示"进行中"）', () => {
    const open = splitGenerations([event(1, 'a')])[0];
    expect(open && generationStats(open).closed).toBe(false);
  });

  it('前端不认识的事件类型单独计数，不混进已知事件', () => {
    // helper 恒设 is_known_type: true，所以这里必须显式覆盖成 false。
    const events = [
      { ...event(1, 'brand_new_event'), is_known_type: false },
      event(2, 'known_one'),
    ];
    const stats = generationStats(splitGenerations(events)[0]!);
    expect(stats.unknownCount).toBe(1);
    expect(stats.knownCount).toBe(1);
    expect(stats.eventCount).toBe(2);
  });

  it('时间戳缺失时给空串，不编造时间', () => {
    const stats = generationStats(splitGenerations([{ run_id: 'r', type: 'x' }])[0]!);
    expect(stats.firstTs).toBe('');
    expect(stats.lastTs).toBe('');
  });
});

describe('节点 id 提取', () => {
  it('按多个候选键名依次尝试', () => {
    expect(nodeIdOf(event(1, 'x', { node_id: 'n1' }))).toBe('n1');
    expect(nodeIdOf(event(1, 'x', { node: 'n2' }))).toBe('n2');
    expect(nodeIdOf(event(1, 'x', { child_id: 'n3' }))).toBe('n3');
  });

  it('取不到返回 null，不猜', () => {
    expect(nodeIdOf(event(1, 'x', { unrelated: 'value' }))).toBe(null);
    expect(nodeIdOf(event(1, 'x'))).toBe(null);
  });
});

describe('过滤', () => {
  const events = [
    event(1, 'iteration_complete', { node_id: 'n1' }),
    event(2, 'repair_failed', { node_id: 'n2' }),
    { run_id: 'r', type: 'mystery', is_known_type: false, payload: {} },
  ];

  it('按类型过滤', () => {
    const result = filterEvents(events, { ...EMPTY_EVENT_FILTER, types: ['iteration_complete'] });
    expect(result.map((e) => e.id)).toEqual([1]);
  });

  it('hideUnknown 隐藏前端不认识的事件', () => {
    const result = filterEvents(events, { ...EMPTY_EVENT_FILTER, hideUnknown: true });
    expect(result.map((e) => e.type)).not.toContain('mystery');
  });

  it('按节点过滤，payload 里没有该节点的事件被排除', () => {
    const result = filterEvents(events, { ...EMPTY_EVENT_FILTER, nodeId: 'n1' });
    expect(result.map((e) => e.id)).toEqual([1]);
  });

  it('关键词匹配 type 与 payload', () => {
    expect(filterEvents(events, { ...EMPTY_EVENT_FILTER, keyword: 'repair' })).toHaveLength(1);
    expect(filterEvents(events, { ...EMPTY_EVENT_FILTER, keyword: 'n2' })).toHaveLength(1);
    expect(filterEvents(events, { ...EMPTY_EVENT_FILTER, keyword: '查无此词' })).toHaveLength(0);
  });

  it('过滤前先去重，不会因重放而多出一条', () => {
    const duplicated = [events[0]!, events[0]!, events[1]!];
    expect(filterEvents(duplicated, { ...EMPTY_EVENT_FILTER, types: ['iteration_complete'] })).toHaveLength(1);
  });
});

describe('标签与配色', () => {
  it('已知事件出中文，未知事件回落到原文（不编造译名）', () => {
    expect(eventLabel('iteration_complete')).toBe('一代完成');
    expect(eventLabel('some_future_event')).toBe('some_future_event');
  });

  it('失败类事件标红，预算类标黄，成功类标绿', () => {
    expect(eventTone('repair_failed')).toBe('error');
    expect(eventTone('budget_stop')).toBe('warn');
    expect(eventTone('iteration_complete')).toBe('success');
    expect(eventTone('operator_selected')).toBe('normal');
  });

  it('未知事件的配色是 normal，不当成错误', () => {
    // 引擎加新事件时页面不该突然变红一片。
    expect(eventTone('brand_new')).toBe('normal');
  });

  it('浏览器能收到的事件全部有中文标签（漏一个就会在时间轴上露出英文类型名）', () => {
    // KNOWN_EVENT_NAMES 是真正会被订阅、从而能到达前端的事件集合
    // （SSE 按事件名投递，没注册的名字根本到不了浏览器）。它与引擎 catalog
    // 是否一致由 Python 侧 tests/webapi/test_engine_catalog.py 盯着；
    // 这里只管一件事：译名一个不漏。
    const untranslated = KNOWN_EVENT_NAMES.filter((type) => eventLabel(type) === type);
    expect(untranslated).toEqual([]);
  });

  it('交换与中断各有各的句子，拒绝事件标红（D6.4 时间轴要求）', () => {
    expect(eventLabel('exchange_rejected')).toBe('摘要投递被拒');
    expect(eventLabel('exchange_applied')).toBe('摘要被采用');
    expect(eventLabel('exchange_delivered')).toBe('摘要已投递');
    expect(eventLabel('run_interrupted')).toBe('运行被中断');
    // PRD §9.6：错误类事件必须一眼可辨，摘要投递被拒属于错误类。
    expect(eventTone('exchange_rejected')).toBe('error');
  });
});

describe('类型计数', () => {
  it('按次数降序，同数按类型名排序（顺序稳定）', () => {
    const events = [
      event(1, 'b_type'),
      event(2, 'a_type'),
      event(3, 'a_type'),
      event(4, 'c_type'),
    ];
    expect(countEventTypes(events).map((x) => x.type)).toEqual(['a_type', 'b_type', 'c_type']);
    expect(countEventTypes(events)[0]?.count).toBe(2);
  });

  it('空流返回空数组', () => {
    expect(countEventTypes([])).toEqual([]);
  });
});
