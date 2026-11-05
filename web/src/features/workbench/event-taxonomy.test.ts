/**
 * 事件分类表（`event-taxonomy.ts`）的测试。
 *
 * 跨到 Python 侧的对齐由 `tests/webapi/test_engine_catalog.py` 负责——只有那边
 * 读得到引擎源码里的 `log_event` 字面量。本文件只测这份表**自身**的性质：互斥、
 * 完整、有标签，以及表外类型的降级行为。
 */
import { describe, expect, it } from 'vitest';

import {
  CATEGORY_LABELS,
  EVENT_CATEGORIES,
  categoryLabel,
  classifiedEventTypes,
  eventCategory,
} from '@/features/workbench/event-taxonomy';

describe('事件分类表（PRD §16.2）', () => {
  it('正好十二个粗类，且互不重复', () => {
    expect(EVENT_CATEGORIES).toHaveLength(12);
    expect(new Set(EVENT_CATEGORIES).size).toBe(12);
  });

  it('每个粗类都有中文标签', () => {
    for (const category of EVENT_CATEGORIES) {
      expect(categoryLabel(category)).not.toBe('');
      expect(categoryLabel(category)).toBe(CATEGORY_LABELS[category]);
    }
  });

  it('一个类型只属于一个粗类（表由构造期反查表保证，重复会直接抛）', () => {
    const seen = new Map<string, string>();
    for (const type of classifiedEventTypes()) {
      const category = eventCategory(type);
      expect(category).not.toBeNull();
      expect(seen.has(type)).toBe(false);
      seen.set(type, category as string);
    }
  });

  it('node_created 落在「节点创建」里，而不是被塞进「迭代完成」', () => {
    // 这条是阶段 8 引擎补事件的理由：PRD 要一个独立的节点创建事件，
    // 前端必须真的能用它，而不是拿 iteration_complete 顶替。
    expect(eventCategory('node_created')).toBe('node_created');
    expect(eventCategory('iteration_complete')).toBe('iteration');
  });

  it('表外的类型返回 null，不编造粗类——但仍然会被渲染', () => {
    // TODO §13.4：未知事件要可见。返回 null 让调用方降级显示类型原文，
    // 编一个粗类才是把"不认识"藏起来。
    expect(eventCategory('some_type_from_the_future')).toBeNull();
  });

  it('逐结构参数试验属于评估，不增加外层迭代计数', () => {
    expect(eventCategory('structure_tuning_started')).toBe('evaluation');
    expect(eventCategory('structure_tuning_trial')).toBe('evaluation');
    expect(eventCategory('structure_tuning_complete')).toBe('evaluation');
    expect(eventCategory('iteration_complete')).toBe('iteration');
  });

  it('没有独立事件的分类保持为空', () => {
    const empty = EVENT_CATEGORIES.filter((category) => {
      const members = classifiedEventTypes().filter((type) => eventCategory(type) === category);
      return members.length === 0;
    });
    expect(empty).toEqual(['best_node', 'budget']);
  });
});
