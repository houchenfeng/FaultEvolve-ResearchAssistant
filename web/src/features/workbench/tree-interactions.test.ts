/**
 * 树交互纯逻辑的测试（PRD §10.2 后四条 + §10.5 折叠策略）。
 *
 * 重点验三件容易做错的事：
 * 1. **折叠只影响显示**，绝不改底层节点数组（PRD §10.5 硬要求）。
 * 2. **crossover 的菱形结构不能死循环** —— 两个父指向同一子节点，上溯会成环。
 * 3. **"低价值"用后端已给的 `within_noise_band`**，不是前端另立标准。
 */
import { describe, expect, it } from 'vitest';

import type { TreeNodeDto } from '@/generated/api';
import {
  ancestorPaths,
  canCompare,
  clearCompare,
  collapseAllResult,
  collapsibleIds,
  collectAncestorPaths,
  COMPARE_LIMIT,
  defaultCollapsedIds,
  descendantsOf,
  edgesWithin,
  expandAll,
  locateNode,
  MAX_ANCESTOR_PATHS,
  NOTHING_COLLAPSED,
  relatedNodeIds,
  toggleCollapse,
  toggleCompare,
  visibleNodeIds,
} from '@/features/workbench/tree-interactions';

function node(overrides: Partial<TreeNodeDto> = {}): TreeNodeDto {
  return {
    id: 'n-00000001',
    branch_id: 'main',
    depth: 0,
    operator: 'init',
    hypothesis_status: 'undetermined',
    status: 'done',
    score: 10,
    delta_score: null,
    noise_delta: null,
    within_noise_band: null,
    adopted_card_ids: [],
    offered_card_ids: [],
    ...overrides,
  };
}

/** root → a → b，root → c：两条分支。 */
const SIMPLE_EDGES = [
  { source: 'root', target: 'a' },
  { source: 'a', target: 'b' },
  { source: 'root', target: 'c' },
];

/** crossover 造成的菱形：x 有两个父（p1、p2），p1 与 p2 都源自 root。 */
const DIAMOND_EDGES = [
  { source: 'root', target: 'p1' },
  { source: 'root', target: 'p2' },
  { source: 'p1', target: 'x', kind: 'parent' },
  { source: 'p2', target: 'x', kind: 'crossover_second_parent' },
];

describe('可折叠节点', () => {
  it('有子节点的是父，没有子节点的不是', () => {
    const result = collapsibleIds(SIMPLE_EDGES);
    expect([...result].sort()).toEqual(['a', 'root']);
  });

  it('叶子节点不可折叠（没有可展开的东西）', () => {
    expect(collapsibleIds(SIMPLE_EDGES).has('b')).toBe(false);
    expect(collapsibleIds(SIMPLE_EDGES).has('c')).toBe(false);
  });

  it('crossover 的第二父也算父（边有两条就都算）', () => {
    expect(collapsibleIds(DIAMOND_EDGES).has('p2')).toBe(true);
  });

  it('空边集返回空集合', () => {
    expect([...collapsibleIds([])]).toEqual([]);
  });
});

describe('后代集合', () => {
  it('含自己与全部后代', () => {
    const result = descendantsOf('root', SIMPLE_EDGES);
    expect([...result].sort()).toEqual(['a', 'b', 'c', 'root']);
  });

  it('菱形结构不会死循环', () => {
    // x 的两个父 p1/p2 都回溯到 root，朴素实现会在这里转圈。
    const result = descendantsOf('root', DIAMOND_EDGES);
    expect([...result].sort()).toEqual(['p1', 'p2', 'root', 'x']);
  });

  it('自己成环时也终止（脏数据防护）', () => {
    const cyclic = [
      { source: 'a', target: 'b' },
      { source: 'b', target: 'a' },
    ];
    expect(descendantsOf('a', cyclic).size).toBeGreaterThan(0);
  });
});

describe('折叠后的可见集合', () => {
  const all = ['root', 'a', 'b', 'c'];

  it('未折叠时全部可见', () => {
    expect([...visibleNodeIds(all, SIMPLE_EDGES, NOTHING_COLLAPSED)].sort()).toEqual(
      [...all].sort(),
    );
  });

  it('折叠某个节点时，它自己仍可见（否则没法展开）', () => {
    const visible = visibleNodeIds(all, SIMPLE_EDGES, new Set(['a']));
    expect(visible.has('a')).toBe(true);
    expect(visible.has('b')).toBe(false);
    expect(visible.has('c')).toBe(true);
  });

  it('折叠根时只剩根', () => {
    const visible = visibleNodeIds(all, SIMPLE_EDGES, new Set(['root']));
    expect([...visible]).toEqual(['root']);
  });

  it('深层折叠：b 自己被折叠所以仍可见，c 不受影响', () => {
    // 折叠 {a, b}：b 自己被折叠 ⇒ 仍可见（要有展开按钮）；b 无子节点，
    // 所以没有"更深一层"被藏。c 是 root 的另一支，完全不受影响。
    const visible = visibleNodeIds(all, SIMPLE_EDGES, new Set(['a', 'b']));
    expect([...visible].sort()).toEqual(['a', 'b', 'c', 'root']);
  });

  it('只折叠 a 时 b 被藏（b 未被折叠，是 a 的后代）', () => {
    const visible = visibleNodeIds(all, SIMPLE_EDGES, new Set(['a']));
    expect(visible.has('b')).toBe(false);
    expect([...visible].sort()).toEqual(['a', 'c', 'root']);
  });

  it('折叠不存在的节点不改变任何东西', () => {
    const visible = visibleNodeIds(all, SIMPLE_EDGES, new Set(['ghost']));
    expect(visible.size).toBe(4);
  });

  it('菱形结构里折叠一父只藏它那一支', () => {
    const allDiamond = ['root', 'p1', 'p2', 'x'];
    const visible = visibleNodeIds(allDiamond, DIAMOND_EDGES, new Set(['p1']));
    expect(visible.has('p1')).toBe(true);
    // x 还有 p2 这条父链，所以仍然可见 —— 这正是"任一父链"语义的体现。
    expect(visible.has('x')).toBe(true);
    expect(visible.has('p2')).toBe(true);
  });
});

describe('折叠状态切换（不 mutate 入参）', () => {
  it('切换后返回新集合，原集合不变', () => {
    const before = new Set(['x']);
    const after = toggleCollapse(before, 'root');
    expect(before.has('root')).toBe(false);
    expect(after.has('root')).toBe(true);
  });

  it('再切一次即取消', () => {
    const once = toggleCollapse(new Set(), 'root');
    const twice = toggleCollapse(once, 'root');
    expect(twice.has('root')).toBe(false);
    expect(twice.size).toBe(0);
  });

  it('expandAll 返回空集合', () => {
    expect(expandAll().size).toBe(0);
  });
});

describe('全部折叠的边界', () => {
  it('单节点树不折叠，并说明原因', () => {
    const result = collapseAllResult(new Set(['only']), 1);
    expect(result.collapsed.size).toBe(0);
    expect(result.warning).toContain('只有一个节点');
  });

  it('没有可折叠节点时不折叠', () => {
    const result = collapseAllResult(new Set(), 5);
    expect(result.collapsed.size).toBe(0);
    expect(result.warning).toContain('没有子节点');
  });

  it('正常情况直接全折且无警告', () => {
    const result = collapseAllResult(new Set(['a', 'root']), 5);
    expect(result.collapsed.size).toBe(2);
    expect(result.warning).toBeNull();
  });
});

describe('默认折叠「低价值」子树（PRD 10.5）', () => {
  const root = node({ id: 'root', parent_id: null, within_noise_band: null });
  const noise = node({ id: 'noise', parent_id: 'root', within_noise_band: true });
  const noiseLeaf = node({ id: 'noise-leaf', parent_id: 'noise', within_noise_band: true });
  const progress = node({ id: 'progress', parent_id: 'root', within_noise_band: false });
  const edges = [
    { source: 'root', target: 'noise' },
    { source: 'noise', target: 'noise-leaf' },
    { source: 'root', target: 'progress' },
  ];
  const nodes = [root, noise, noiseLeaf, progress];

  it('整条 noise 子树被折，progress 分支保留', () => {
    const collapsed = defaultCollapsedIds(nodes, edges);
    expect(collapsed.has('noise')).toBe(true);
    expect(collapsed.has('progress')).toBe(false);
  });

  it('根节点永不自动折叠（藏掉根会让人以为树空了）', () => {
    expect(defaultCollapsedIds(nodes, edges).has('root')).toBe(false);
  });

  it('noise 节点的后代里有 progress 时不折（否则藏掉改进路径）', () => {
    const buried = node({ id: 'buried', parent_id: 'root', within_noise_band: true });
    const treasure = node({ id: 'treasure', parent_id: 'buried', within_noise_band: false });
    const collapsed = defaultCollapsedIds(
      [...nodes, buried, treasure],
      [...edges, { source: 'root', target: 'buried' }, { source: 'buried', target: 'treasure' }],
    );
    expect(collapsed.has('buried')).toBe(false);
  });

  it('best 节点也算「有价值」', () => {
    const buried = node({ id: 'buried2', parent_id: 'root', within_noise_band: true });
    const best = node({ id: 'best2', parent_id: 'buried2', is_best: true, within_noise_band: true });
    const collapsed = defaultCollapsedIds(
      [...nodes, buried, best],
      [...edges, { source: 'root', target: 'buried2' }, { source: 'buried2', target: 'best2' }],
    );
    expect(collapsed.has('buried2')).toBe(false);
  });

  it('progress 节点本身不被折（它是结论不是噪声）', () => {
    expect(defaultCollapsedIds(nodes, edges).has('progress')).toBe(false);
  });

  it('空树返回空集合', () => {
    expect(defaultCollapsedIds([], []).size).toBe(0);
  });
});

describe('祖先路径追溯（双亲高亮）', () => {
  it('单链返回一条路径', () => {
    const paths = ancestorPaths('b', SIMPLE_EDGES);
    expect(paths).toEqual([['b', 'a', 'root']]);
  });

  it('crossover 节点返回两条路径（两个父都要亮）', () => {
    const paths = ancestorPaths('x', DIAMOND_EDGES);
    expect(paths).toHaveLength(2);
    expect(paths).toEqual([
      ['x', 'p1', 'root'],
      ['x', 'p2', 'root'],
    ]);
  });

  it('根节点返回自己一条路径', () => {
    expect(ancestorPaths('root', SIMPLE_EDGES)).toEqual([['root']]);
  });

  it('环状数据不会死循环', () => {
    const cyclic = [
      { source: 'a', target: 'b' },
      { source: 'b', target: 'c' },
      { source: 'c', target: 'a' },
    ];
    expect(() => ancestorPaths('a', cyclic)).not.toThrow();
  });

  it('路径数超过上限时截断并如实标记，而不是继续枚举', () => {
    // 每一层都是 crossover ⇒ 路径数 = 2^深度。不设上限的话 20 层就是百万条，
    // 浏览器会直接卡死 —— 上限是防这个的，不是防测试跑得慢。
    const edges: Array<{ source: string; target: string }> = [];
    const depth = 20;
    for (let i = 1; i <= depth; i += 1) {
      edges.push({ source: `n${i - 1}`, target: `n${i}` });
      edges.push({ source: `n${Math.max(0, i - 2)}`, target: `n${i}` });
    }
    const result = collectAncestorPaths(`n${depth}`, edges);
    expect(result.paths.length).toBeLessThanOrEqual(MAX_ANCESTOR_PATHS);
    expect(result.truncated).toBe(true);
  });

  it('未超上限时 truncated 为 false', () => {
    expect(collectAncestorPaths('x', DIAMOND_EDGES).truncated).toBe(false);
  });

  it('relatedNodeIds 汇总所有路径上的节点', () => {
    expect([...relatedNodeIds('x', DIAMOND_EDGES)].sort()).toEqual(['p1', 'p2', 'root', 'x']);
  });

  it('relatedNodeIds 在全 crossover 树上仍是 O(祖先数) 而不随路径数爆炸', () => {
    // 它要的是并集，枚举路径是 2^深度 —— 早先的实现因此在 100 节点上就跑不完。
    const edges: Array<{ source: string; target: string }> = [];
    const depth = 16;
    for (let i = 1; i <= depth; i += 1) {
      edges.push({ source: `n${i - 1}`, target: `n${i}` });
      edges.push({ source: `n${Math.max(0, i - 2)}`, target: `n${i}` });
    }
    const ids = relatedNodeIds(`n${depth}`, edges);
    expect(ids.has(`n${depth}`)).toBe(true);
    expect(ids.has('n0')).toBe(true);
    expect(ids.size).toBeLessThanOrEqual(depth + 1);
  });

  it('edgesWithin 只留两端都在集合里的边', () => {
    const ids = relatedNodeIds('p1', DIAMOND_EDGES);
    const inside = edgesWithin(ids, DIAMOND_EDGES);
    // p2 → x 这条边因 p2 不在集合里而排除。
    expect(inside.every((e) => ids.has(e.source) && ids.has(e.target))).toBe(true);
    expect(inside.some((e) => e.target === 'x' && e.source === 'p2')).toBe(false);
  });
});

describe('对比选择', () => {
  it('最多两个', () => {
    expect(COMPARE_LIMIT).toBe(2);
  });

  it('选中两个后 canCompare 为真', () => {
    const selection = toggleCompare(toggleCompare([], 'a'), 'b');
    expect(canCompare(selection)).toBe(true);
  });

  it('选满两个后再选，替换最旧的（不卡住用户）', () => {
    let selection = toggleCompare(toggleCompare([], 'a'), 'b');
    selection = toggleCompare(selection, 'c');
    expect(selection).toEqual(['b', 'c']);
  });

  it('再点已选中的节点即取消', () => {
    const selection = toggleCompare(['a', 'b'], 'a');
    expect(selection).toEqual(['b']);
  });

  it('只选一个时不能对比', () => {
    expect(canCompare(toggleCompare([], 'a'))).toBe(false);
  });

  it('clearCompare 清空', () => {
    expect(clearCompare()).toEqual([]);
  });

  it('不 mutate 入参', () => {
    const before = ['a'];
    toggleCompare(before, 'b');
    expect(before).toEqual(['a']);
  });
});

describe('跨页定位', () => {
  const filter = { bestPathOnly: false, withinBandOnly: false, scoredOnly: false };

  it('节点可见时直接可定位', () => {
    const outcome = locateNode('a', new Set(['root', 'a']), filter);
    expect(outcome).toEqual({ visible: true, hiddenByFilter: false, blockingFilters: [] });
  });

  it('节点被筛掉且有过滤条件开启时报出是哪一条挡住的', () => {
    const outcome = locateNode('hidden', new Set(['root']), {
      bestPathOnly: true,
      withinBandOnly: true,
      scoredOnly: false,
    });
    expect(outcome.visible).toBe(false);
    expect(outcome.hiddenByFilter).toBe(true);
    expect(outcome.blockingFilters).toEqual(['bestPathOnly', 'withinBandOnly']);
  });

  it('节点不在可见集但没有过滤条件（是折叠/未加载），不算被过滤', () => {
    const outcome = locateNode('collapsed-away', new Set(['root']), filter);
    expect(outcome.visible).toBe(false);
    expect(outcome.hiddenByFilter).toBe(false);
    expect(outcome.blockingFilters).toEqual([]);
  });
});

describe('「只影响显示」的硬约束（PRD 10.5）', () => {
  it('全部交互函数都不修改传入的边数组', () => {
    const edges = SIMPLE_EDGES.map((e) => ({ ...e }));
    const snapshot = JSON.stringify(edges);
    collapsibleIds(edges);
    descendantsOf('root', edges);
    visibleNodeIds(['root', 'a', 'b', 'c'], edges, new Set(['a']));
    ancestorPaths('b', edges);
    relatedNodeIds('b', edges);
    edgesWithin(new Set(['root', 'a', 'b']), edges);
    expect(JSON.stringify(edges)).toBe(snapshot);
  });

  it('折叠/路径函数不修改传入的节点数组', () => {
    const nodes = [
      node({ id: 'root', parent_id: null }),
      node({ id: 'noise', parent_id: 'root', within_noise_band: true }),
    ];
    const snapshot = JSON.stringify(nodes);
    defaultCollapsedIds(nodes, SIMPLE_EDGES);
    expect(JSON.stringify(nodes)).toBe(snapshot);
  });
});
