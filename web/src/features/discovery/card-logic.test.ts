/**
 * 知识卡推导逻辑的单元测试（PRD 12.2 / TODO 6.1）。
 *
 * 重点盯两条会「骗人」的路径：
 *  1. 后端的 0 和 null 必须区分——0 是真实计数，null 是查不到（PRD §2.3）；
 *  2. `adopted_count = null` 在 fe.db 可读与不可读时含义相反，只能靠制品状态区分。
 */
import { describe, expect, it } from 'vitest';

import {
  CARD_LABELS,
  EMPTY_CARD_FILTER,
  LOCAL_LABEL_DISCLAIMER,
  NOT_RECORDED,
  adoptionSummaryRows,
  buildCardRows,
  cardEmptyState,
  cardLabelStorageKey,
  countCell,
  deltaCell,
  filterCards,
  isCardLabel,
  rateCell,
  readCardLabels,
  writeCardLabel,
  type CardRow,
} from '@/features/discovery/card-logic';
import type {
  KnowledgeCardResponse,
  KnowledgeCardStatResponse,
  RunKnowledgeResponse,
} from '@/generated/api';

/** 最小可用的 Storage 替身；`throwOn` 用来模拟隐私模式下存储被禁用。 */
function makeStorage(
  initial: Record<string, string> = {},
  options: { throwOn?: 'get' | 'set' } = {},
): Storage {
  const map = new Map(Object.entries(initial));
  return {
    get length() {
      return map.size;
    },
    clear: () => map.clear(),
    getItem: (key: string) => {
      if (options.throwOn === 'get') throw new Error('storage disabled');
      return map.has(key) ? (map.get(key) as string) : null;
    },
    key: (index: number) => [...map.keys()][index] ?? null,
    removeItem: (key: string) => void map.delete(key),
    setItem: (key: string, value: string) => {
      if (options.throwOn === 'set') throw new Error('quota exceeded');
      map.set(key, value);
    },
  };
}

function card(overrides: Partial<KnowledgeCardResponse> = {}): KnowledgeCardResponse {
  return {
    card_id: 'card_a',
    offered_count: null,
    adopted_count: null,
    refuted_count: null,
    invalid_count: null,
    mean_delta: null,
    adopted_iterations: [],
    adopted_node_ids: [],
    ...overrides,
  };
}

function row(overrides: Partial<CardRow> = {}): CardRow {
  return {
    cardId: 'card_a',
    title: null,
    category: null,
    claim: null,
    sourceKind: null,
    conditions: null,
    priority: null,
    sources: [],
    offered: countCell(null),
    adopted: countCell(null),
    refuted: countCell(null),
    invalid: countCell(null),
    meanDelta: deltaCell(null),
    adoptedIterations: [],
    adoptedNodeIds: [],
    statN: countCell(null),
    label: null,
    ...overrides,
  };
}

describe('格子：0 是数据，null 才是未记录', () => {
  it('countCell 保留 0，只把 null/undefined 写成未记录', () => {
    expect(countCell(0)).toEqual({ value: '0', recorded: true });
    expect(countCell(7)).toEqual({ value: '7', recorded: true });
    expect(countCell(null)).toEqual({ value: NOT_RECORDED, recorded: false });
    expect(countCell(undefined)).toEqual({ value: NOT_RECORDED, recorded: false });
  });

  it('deltaCell 用三位小数，且负增益照实显示', () => {
    expect(deltaCell(0)).toEqual({ value: '0.000', recorded: true });
    expect(deltaCell(0.1234)).toEqual({ value: '0.123', recorded: true });
    expect(deltaCell(-2.5)).toEqual({ value: '-2.500', recorded: true });
    expect(deltaCell(null).recorded).toBe(false);
  });

  it('rateCell 换算成百分数，0 不等于未记录', () => {
    expect(rateCell(0)).toEqual({ value: '0.0%', recorded: true });
    expect(rateCell(0.25)).toEqual({ value: '25.0%', recorded: true });
    expect(rateCell(1)).toEqual({ value: '100.0%', recorded: true });
    expect(rateCell(null).recorded).toBe(false);
  });
});

describe('buildCardRows：adopted_count = null 的两种成因', () => {
  it('fe.db 不可读时写未记录，绝不写 0', () => {
    const rows = buildCardRows([card({ adopted_count: null })], undefined, {
      databaseAvailable: false,
    });
    expect(rows[0].adopted).toEqual({ value: NOT_RECORDED, recorded: false });
  });

  it('fe.db 可读且没有采纳节点时，null 就是 0（replay_service.py:1307 的写法）', () => {
    const rows = buildCardRows([card({ adopted_count: null, adopted_node_ids: [] })], undefined, {
      databaseAvailable: true,
    });
    expect(rows[0].adopted).toEqual({ value: '0', recorded: true });
  });

  it('fe.db 可读时以采纳节点数补齐', () => {
    const rows = buildCardRows(
      [card({ adopted_count: null, adopted_node_ids: ['n1', 'n2'] })],
      undefined,
      { databaseAvailable: true },
    );
    expect(rows[0].adopted).toEqual({ value: '2', recorded: true });
  });

  it('后端给了 adopted_count 就直接用，不受制品状态影响', () => {
    for (const databaseAvailable of [true, false]) {
      const rows = buildCardRows([card({ adopted_count: 4 })], undefined, { databaseAvailable });
      expect(rows[0].adopted).toEqual({ value: '4', recorded: true });
    }
  });

  it('其余计数照实透传，包括 0', () => {
    const rows = buildCardRows(
      [
        card({
          card_id: 'c1',
          offered_count: 0,
          refuted_count: 3,
          invalid_count: null,
          mean_delta: null,
          adopted_iterations: [2, 5],
        }),
      ],
      undefined,
      { databaseAvailable: true },
    );
    expect(rows[0].offered).toEqual({ value: '0', recorded: true });
    expect(rows[0].refuted).toEqual({ value: '3', recorded: true });
    expect(rows[0].invalid.recorded).toBe(false);
    // 均值为 null 时不得显示 0.000：n == 0 表示均值未知（replay_service.py:1292）。
    expect(rows[0].meanDelta).toEqual({ value: NOT_RECORDED, recorded: false });
    expect(rows[0].adoptedIterations).toEqual([2, 5]);
  });

  it('按 card_id 合并 run_summary 的样本数，匹配不上就是未记录', () => {
    const stats: KnowledgeCardStatResponse[] = [
      { card_id: 'c1', n: 6, sum_delta: 1.5, mean_delta: 0.25, refuted_count: 1 },
    ];
    const rows = buildCardRows([card({ card_id: 'c1' }), card({ card_id: 'c2' })], stats, {
      databaseAvailable: true,
    });
    expect(rows[0].statN).toEqual({ value: '6', recorded: true });
    expect(rows[1].statN).toEqual({ value: NOT_RECORDED, recorded: false });
  });

  it('本地标记按卡片 ID 挂上，没有标记的保持 null', () => {
    const rows = buildCardRows([card({ card_id: 'c1' }), card({ card_id: 'c2' })], undefined, {
      databaseAvailable: true,
      labels: { c1: '存疑' },
    });
    expect(rows[0].label).toBe('存疑');
    expect(rows[1].label).toBeNull();
  });
});

describe('filterCards', () => {
  const rows = [
    row({ cardId: 'hdd_smart_5' }),
    row({ cardId: 'ssd_wear_1', label: '信任' }),
    row({ cardId: 'mem_leak', label: '排除' }),
  ];

  it('空筛选返回全部', () => {
    expect(filterCards(rows, EMPTY_CARD_FILTER)).toHaveLength(3);
  });

  it('按卡片 ID 大小写不敏感搜索', () => {
    expect(filterCards(rows, { query: 'HDD', label: 'any', category: 'any' }).map((r) => r.cardId)).toEqual([
      'hdd_smart_5',
    ]);
    expect(filterCards(rows, { query: '  wear  ', label: 'any', category: 'any' }).map((r) => r.cardId)).toEqual([
      'ssd_wear_1',
    ]);
  });

  it('按本地标记筛选，与搜索可以叠加', () => {
    expect(filterCards(rows, { query: '', label: '信任', category: 'any' }).map((r) => r.cardId)).toEqual([
      'ssd_wear_1',
    ]);
    expect(filterCards(rows, { query: 'mem', label: '信任', category: 'any' })).toHaveLength(0);
    expect(filterCards(rows, { query: 'mem', label: '排除', category: 'any' }).map((r) => r.cardId)).toEqual([
      'mem_leak',
    ]);
  });

  it('搜索也能命中本地标记文字', () => {
    expect(filterCards(rows, { query: '存疑', label: 'any', category: 'any' })).toHaveLength(0);
    expect(filterCards(rows, { query: '信任', label: 'any', category: 'any' }).map((r) => r.cardId)).toEqual([
      'ssd_wear_1',
    ]);
  });

  it('搜不到时返回空数组，由调用方解释原因', () => {
    expect(filterCards(rows, { query: 'zzz', label: 'any', category: 'any' })).toHaveLength(0);
  });
});

describe('本地标记的读写（只存在浏览器里）', () => {
  const runId = 'hdd_mvp_demo_7510f100';

  it('key 带 runId，两次运行不会互相覆盖', () => {
    expect(cardLabelStorageKey(runId)).toBe(`fe.card-labels.${runId}`);
    const storage = makeStorage();
    writeCardLabel('run_a', 'c1', '信任', storage);
    writeCardLabel('run_b', 'c1', '排除', storage);
    expect(readCardLabels('run_a', storage)).toEqual({ c1: '信任' });
    expect(readCardLabels('run_b', storage)).toEqual({ c1: '排除' });
  });

  it('写入后读回，label 传 null 表示撤销标记', () => {
    const storage = makeStorage();
    writeCardLabel(runId, 'c1', '信任', storage);
    writeCardLabel(runId, 'c2', '存疑', storage);
    expect(readCardLabels(runId, storage)).toEqual({ c1: '信任', c2: '存疑' });

    const next = writeCardLabel(runId, 'c1', null, storage);
    expect(next).toEqual({ c2: '存疑' });
    expect(readCardLabels(runId, storage)).toEqual({ c2: '存疑' });
  });

  it('标记集合恰好是 PRD 12.2 的三项，不多不少', () => {
    expect([...CARD_LABELS]).toEqual(['信任', '存疑', '排除']);
    expect(isCardLabel('信任')).toBe(true);
    expect(isCardLabel('点赞')).toBe(false);
    expect(isCardLabel(null)).toBe(false);
    expect(isCardLabel(0)).toBe(false);
  });

  it('存储内容被改坏时当成没有标记，不抛异常', () => {
    const key = cardLabelStorageKey(runId);
    expect(readCardLabels(runId, makeStorage({ [key]: '{不是 JSON' }))).toEqual({});
    expect(readCardLabels(runId, makeStorage({ [key]: '[1,2,3]' }))).toEqual({});
    expect(readCardLabels(runId, makeStorage({ [key]: '"信任"' }))).toEqual({});
    expect(readCardLabels(runId, makeStorage({ [key]: 'null' }))).toEqual({});
  });

  it('未知标记值被逐条丢弃，合法值保留', () => {
    const key = cardLabelStorageKey(runId);
    const storage = makeStorage({ [key]: '{"c1":"点赞","c2":"排除","c3":42}' });
    expect(readCardLabels(runId, storage)).toEqual({ c2: '排除' });
  });

  it('存储被禁用时读回空、写入只留在内存里，页面不崩', () => {
    expect(readCardLabels(runId, makeStorage({}, { throwOn: 'get' }))).toEqual({});
    const next = writeCardLabel(runId, 'c1', '信任', makeStorage({}, { throwOn: 'set' }));
    expect(next).toEqual({ c1: '信任' });
  });

  it('免责声明必须点明不影响真实运行', () => {
    expect(LOCAL_LABEL_DISCLAIMER).toContain('不影响真实运行');
  });
});

describe('adoptionSummaryRows', () => {
  it('knowledge 为 null 时四行全部未记录', () => {
    const rows = adoptionSummaryRows(null);
    expect(rows.map((r) => r.label)).toEqual([
      '提供过的卡片数',
      '被采纳的卡片数',
      '采纳后有效的卡片数',
      '卡片采纳率',
    ]);
    for (const item of rows) expect(item.cell.recorded).toBe(false);
  });

  it('有值就照实换算，0 采纳率是 0.0% 而不是未记录', () => {
    const knowledge: RunKnowledgeResponse = {
      cards_offered: 18,
      cards_adopted: 0,
      cards_adopted_valid: null,
      card_adoption_rate: 0,
    };
    const rows = adoptionSummaryRows(knowledge);
    expect(rows[0].cell).toEqual({ value: '18', recorded: true });
    expect(rows[1].cell).toEqual({ value: '0', recorded: true });
    expect(rows[2].cell).toEqual({ value: NOT_RECORDED, recorded: false });
    expect(rows[3].cell).toEqual({ value: '0.0%', recorded: true });
  });
});

describe('cardEmptyState：空结果必须解释为什么空（PRD 12.1）', () => {
  it('fe.db 缺失或不可解析时，说「读不到」而不是「没有卡片」', () => {
    for (const state of ['missing', 'invalid'] as const) {
      const empty = cardEmptyState(state, null);
      expect(empty.title).toBe('读不到这次运行的知识卡');
      expect(empty.reason).toContain('node_adopted_cards');
      expect(empty.reason).toContain('不代表这次运行没有用过知识卡');
      expect(empty.reason).toContain(state === 'invalid' ? '不可解析' : '缺失');
    }
  });

  it('运行详情没取到时说「无法判断」，不冤枉这份运行', () => {
    const empty = cardEmptyState('unknown', null);
    expect(empty.title).toBe('暂时无法判断这次运行有没有知识卡');
    expect(empty.reason).toContain('无法区分');
  });

  it('fe.db 可读且汇总记录为 0：才是真的没有提供过卡片', () => {
    const empty = cardEmptyState('available', { cards_offered: 0 });
    expect(empty.title).toBe('这次运行没有提供过知识卡');
    expect(empty.reason).toContain('提供过的卡片数 = 0');
  });

  it('fe.db 可读但汇总里没有 cards_offered：只说清单为空，不编造计数', () => {
    const empty = cardEmptyState('available', null);
    expect(empty.title).toBe('这次运行没有提供过知识卡');
    expect(empty.reason).toContain('没有记录「提供过的卡片数」');
    expect(empty.reason).not.toContain('= 0');
  });
});
