/**
 * 树适配层的纯逻辑测试（TODO 5.1 / 5.7）。
 *
 * 三条重点：
 * 1. **null 不变 0**。契约明写未评分必须渲染「未评分」，这里逐个字段验。
 * 2. **布局是纯函数**。同一份数据算两次坐标必须完全相同（否则节点每次渲染都跳）。
 * 3. **性能用合成树**。真实 demo 只有 6 节点，拿它跑 1000 节点性能测试是自欺。
 */
import { describe, expect, it } from 'vitest';

import type { TreeNodeDto } from '@/generated/api';
import {
  bandStateOf,
  buildFlowGraph,
  buildSyntheticTree,
  EMPTY_TREE_FILTER,
  filterTree,
  islandOptions,
  layoutTree,
  passesFilter,
  rankBands,
  shortId,
  TREE_NODE_HEIGHT,
  TREE_NODE_WIDTH,
  toFlowEdges,
  toFlowNodes,
  toTreeNodeData,
  type TreeEdgeInput,
} from '@/features/workbench/tree-adapter';

function node(overrides: Partial<TreeNodeDto> = {}): TreeNodeDto {
  return {
    id: 'aaaaaaaa-1111-2222-3333-444444444444',
    branch_id: 'main',
    depth: 0,
    operator: 'init',
    hypothesis_status: 'undetermined',
    status: 'done',
    score: 22.81,
    delta_score: null,
    noise_delta: null,
    within_noise_band: null,
    adopted_card_ids: [],
    ...overrides,
  };
}

const ROOT = node({ id: 'root-0001' });
const CHILD = node({ id: 'child-0001', depth: 1, parent_id: 'root-0001', operator: 'refine' });
const SIBLING = node({ id: 'sibling-01', depth: 1, parent_id: 'root-0001', operator: 'refine' });

const PARENT_EDGE: TreeEdgeInput = { source: 'root-0001', target: 'child-0001', kind: 'parent' };
const SECOND_EDGE: TreeEdgeInput = {
  source: 'sibling-01',
  target: 'child-0001',
  kind: 'crossover_second_parent',
};
const REPAIR_EDGE: TreeEdgeInput = { source: 'child-0001', target: 'sibling-01', kind: 'repair' };
const GRAFT_EDGE: TreeEdgeInput = {
  source: 'root-0001',
  target: 'sibling-01',
  kind: 'summary_cross',
};

describe('节点数据派生', () => {
  it('短 ID 截到 8 位，完整 ID 仍可从 node.id 取回', () => {
    const data = toTreeNodeData(node({ id: '0123456789abcdef' }));
    expect(data.shortId).toBe('01234567');
    expect(data.node.id).toBe('0123456789abcdef');
  });

  it('8 位以内原样返回，不做无意义的截断', () => {
    expect(shortId('abc')).toBe('abc');
  });

  it('未评分渲染成「未评分」而不是 0', () => {
    // 契约 TreeNodeDto 的注释明确要求：score 是 None 时 UI 必须渲染「未评分」，never 0。
    expect(toTreeNodeData(node({ score: null })).scoreLabel).toBe('未评分');
    expect(toTreeNodeData(node({ score: undefined })).scoreLabel).toBe('未评分');
  });

  it('真实分数 0 显示为 0.00，与「未评分」区分开', () => {
    // 这是最容易写错的一处：0 是有效分数，不能被当成缺失。
    expect(toTreeNodeData(node({ score: 0 })).scoreLabel).toBe('0.00');
  });

  it('缺失的 Δ 显示为破折号，正负号分明', () => {
    expect(toTreeNodeData(node({ delta_score: null })).deltaLabel).toBe('—');
    expect(toTreeNodeData(node({ delta_score: 1.5 })).deltaLabel).toBe('+1.50');
    expect(toTreeNodeData(node({ delta_score: -1.5 })).deltaLabel).toBe('-1.50');
  });

  it('噪声带是三态，null 不等于 false', () => {
    expect(bandStateOf(node({ within_noise_band: true }))).toBe('inside');
    expect(bandStateOf(node({ within_noise_band: false }))).toBe('outside');
    expect(bandStateOf(node({ within_noise_band: null }))).toBe('unknown');
  });

  it('知识卡数量按采纳列表长度算，缺失列表当 0', () => {
    expect(toTreeNodeData(node({ adopted_card_ids: ['a', 'b'] })).cardCount).toBe(2);
    expect(toTreeNodeData(node({ adopted_card_ids: undefined })).cardCount).toBe(0);
  });

  it('算子与状态都出中文标签', () => {
    const data = toTreeNodeData(node({ operator: 'crossover', status: 'abandoned' }));
    expect(data.operatorLabel).toBe('交叉');
    expect(data.statusLabel).toBe('已放弃');
  });
});

describe('边：三种关系视觉可分（TODO 5.1）', () => {
  it('三种边各自的线型不同，crossover 与 repair 是虚线', () => {
    const edges = toFlowEdges([PARENT_EDGE, SECOND_EDGE, REPAIR_EDGE]);
    const [parent, crossover, repair] = edges;
    expect(parent?.style?.strokeDasharray).toBeUndefined();
    expect(crossover?.style?.strokeDasharray).toBe('6 4');
    expect(repair?.style?.strokeDasharray).toBe('2 3');
    // 线色也必须不同，否则虚线差异在深色主题下看不清。
    expect(new Set(edges.map((edge) => edge.style?.stroke)).size).toBe(3);
  });

  it('边 id 含 kind，同一对节点的不同关系不会互相覆盖', () => {
    const edges = toFlowEdges([PARENT_EDGE, SECOND_EDGE]);
    expect(new Set(edges.map((edge) => edge.id)).size).toBe(2);
  });

  it('边 data 里保留 kind，节点详情抽屉靠它判断关系类型', () => {
    expect(toFlowEdges([SECOND_EDGE])[0]?.data?.kind).toBe('crossover_second_parent');
  });

  it('crossover 与 repair 边带中文标签，普通父边不带', () => {
    const edges = toFlowEdges([PARENT_EDGE, SECOND_EDGE, REPAIR_EDGE]);
    expect(edges[0]?.label).toBeUndefined();
    expect(edges[1]?.label).toBe('交叉');
    expect(edges[2]?.label).toBe('修复');
  });

  it('摘要嫁接边用自己的线型，不退回父边样式', () => {
    const [graft] = toFlowEdges([GRAFT_EDGE]);
    expect(graft?.label).toBe('外岛摘要');
    expect(graft?.data?.kind).toBe('summary_cross');
    expect(graft?.style?.stroke).toBe('var(--color-success-500)');
    const [parent] = toFlowEdges([PARENT_EDGE]);
    expect(parent?.style?.stroke).not.toBe(graft?.style?.stroke);
  });
});

describe('嫁接边不参与排序（TODO D6.3）', () => {
  // 两棵互不相干的岛树：a 的根与 b 的根。b 的某个候选用过 a 的摘要。
  const ISLAND_A = node({ id: 'a-root', island_id: 'a' });
  const ISLAND_B = node({ id: 'b-root', island_id: 'b' });
  const B_CHILD = node({ id: 'b-child', island_id: 'b', depth: 1, parent_id: 'b-root' });
  const hierarchy = toFlowEdges([
    { source: 'b-root', target: 'b-child', kind: 'parent' },
  ]);
  const withGraft = toFlowEdges([
    { source: 'b-root', target: 'b-child', kind: 'parent' },
    { source: 'a-root', target: 'b-child', kind: 'summary_cross' },
  ]);
  const laid = () =>
    layoutTree(toFlowNodes([ISLAND_A, ISLAND_B, B_CHILD]), hierarchy);

  it('加一条跨岛嫁接边，三个节点的坐标一个都不动', () => {
    const plain = laid();
    const grafted = layoutTree(toFlowNodes([ISLAND_A, ISLAND_B, B_CHILD]), withGraft);
    expect(grafted.map((n) => [n.id, n.position.x, n.position.y])).toEqual(
      plain.map((n) => [n.id, n.position.x, n.position.y]),
    );
  });

  it('但这条边照样渲染出来，读者能看见经验从哪来', () => {
    const graph = buildFlowGraph([ISLAND_A, ISLAND_B, B_CHILD], [
      { source: 'b-root', target: 'b-child', kind: 'parent' },
      { source: 'a-root', target: 'b-child', kind: 'summary_cross' },
    ]);
    expect(graph.edges.filter((e) => e.data?.kind === 'summary_cross')).toHaveLength(1);
  });
});

describe('布局是纯函数', () => {
  const nodes = toFlowNodes([ROOT, CHILD, SIBLING]);
  const edges = toFlowEdges([PARENT_EDGE, { source: 'root-0001', target: 'sibling-01', kind: 'parent' }]);

  it('同一份数据算两次，坐标逐个相同', () => {
    const first = layoutTree(nodes, edges);
    const second = layoutTree(nodes, edges);
    expect(first.map((n) => n.position)).toEqual(second.map((n) => n.position));
  });

  it('坐标是整数，不出现小数抖动', () => {
    for (const item of layoutTree(nodes, edges)) {
      expect(Number.isInteger(item.position.x)).toBe(true);
      expect(Number.isInteger(item.position.y)).toBe(true);
    }
  });

  it('子节点排在父节点下方（TB 方向）', () => {
    const laid = layoutTree(nodes, edges);
    const rootY = laid.find((n) => n.id === 'root-0001')?.position.y ?? 0;
    const childY = laid.find((n) => n.id === 'child-0001')?.position.y ?? 0;
    expect(childY).toBeGreaterThan(rootY);
  });

  it('保留输入顺序：布局不该让"第一个节点"随坐标漂移', () => {
    const laid = layoutTree(nodes, edges);
    expect(laid.map((n) => n.id)).toEqual(['root-0001', 'child-0001', 'sibling-01']);
  });

  it('边指向不存在的节点时不抛错，只是那条边不参与布局', () => {
    // 后端边的端点未必都在节点列表里（悬空父节点只产 warning）。
    const dangling = toFlowEdges([{ source: 'ghost', target: 'child-0001', kind: 'parent' }]);
    expect(() => layoutTree(nodes, [...edges, ...dangling])).not.toThrow();
  });

  it('空树返回空数组', () => {
    expect(layoutTree([], [])).toEqual([]);
  });
});

describe('过滤（TODO 5.2）', () => {
  const nodes = [
    ROOT,
    CHILD,
    node({ id: 'noisy-01', delta_score: 0.1, noise_delta: 1.0, within_noise_band: true }),
    node({ id: 'scored-1', score: 5 }),
    node({ id: 'scored-0', score: null }),
  ];

  it('只看最优路径时只保留路径上的节点', () => {
    const result = filterTree(nodes, [], { ...EMPTY_TREE_FILTER, bestPathOnly: true }, [
      'root-0001',
      'child-0001',
    ]);
    expect(result.nodes.map((n) => n.id).sort()).toEqual(['child-0001', 'root-0001']);
    expect(result.hiddenCount).toBe(3);
  });

  it('只看噪声带内时，带外与未知都不算', () => {
    const inside = nodes.filter((n) => bandStateOf(n) === 'inside');
    const result = filterTree(nodes, [], { ...EMPTY_TREE_FILTER, withinBandOnly: true });
    expect(result.nodes.length).toBe(inside.length);
  });

  it('只看已评分时，score 为 null 的被排除', () => {
    const result = filterTree(nodes, [], { ...EMPTY_TREE_FILTER, scoredOnly: true });
    expect(result.nodes.map((n) => n.id)).not.toContain('scored-0');
  });

  it('按 operator 过滤，空数组表示不过滤', () => {
    const onlyRefine = filterTree(nodes, [], { ...EMPTY_TREE_FILTER, operators: ['refine'] });
    expect(onlyRefine.nodes.every((n) => n.data.node.operator === 'refine')).toBe(true);
    expect(filterTree(nodes, [], EMPTY_TREE_FILTER).nodes.length).toBe(nodes.length);
  });

  it('隐藏指定状态的节点', () => {
    const result = filterTree(nodes, [], { ...EMPTY_TREE_FILTER, hiddenStatuses: ['abandoned'] });
    expect(result.nodes.every((n) => n.data.node.status !== 'abandoned')).toBe(true);
  });

  it('关键词匹配短 ID 与 intent，都不匹配时全空', () => {
    const withIntent = [...nodes, node({ id: 'zzz-00001', intent: '提升召回率' })];
    const hit = filterTree(withIntent, [], { ...EMPTY_TREE_FILTER, keyword: '召回' });
    expect(hit.nodes.map((n) => n.id)).toEqual(['zzz-00001']);
    expect(filterTree(withIntent, [], { ...EMPTY_TREE_FILTER, keyword: '不存在的词' }).nodes).toEqual([]);
  });

  it('端点被隐藏的边不能留在图里（否则会连到空气）', () => {
    const result = filterTree(
      nodes,
      [PARENT_EDGE, { source: 'root-0001', target: 'noisy-01', kind: 'parent' }],
      { ...EMPTY_TREE_FILTER, bestPathOnly: true },
      ['root-0001'],
    );
    // 只剩 root 时，所有边都该消失。
    expect(result.edges).toEqual([]);
  });

  it('过滤后重新布局，不会保留原坐标', () => {
    // 全部节点是 init 的直接子节点（同层），所以 y 在过滤前后都一样（层间距固定），
    // 会变的是 x：少两个兄弟后，剩下的子节点会向中心靠拢。查 x 才检得出"重排了"。
    const full = buildFlowGraph(nodes, [
      PARENT_EDGE,
      { source: 'root-0001', target: 'sibling-01', kind: 'parent' },
    ]);
    const filtered = filterTree(
      nodes,
      [],
      { ...EMPTY_TREE_FILTER, bestPathOnly: true },
      ['root-0001', 'child-0001'],
    );
    const fullChild = full.nodes.find((n) => n.id === 'child-0001')?.position.x;
    const filteredChild = filtered.nodes.find((n) => n.id === 'child-0001')?.position.x;
    expect(filteredChild).not.toBe(fullChild);
  });

  it('layout=false 时不算坐标，交给调用方自己排（§12.6 不重复布局）', () => {
    // TreeCanvas 在过滤之后还要按折叠裁节点，那次裁剪让这里的坐标必然作废，
    // 所以只让它筛。500 节点实测：算两次 1.6 s，算一次 0.21 s。
    const result = filterTree(nodes, [], EMPTY_TREE_FILTER, [], false);
    expect(result.nodes).toHaveLength(nodes.length);
    expect(result.nodes.every((n) => n.position.x === 0 && n.position.y === 0)).toBe(true);
    // 边与隐藏计数不受影响：这一步只是"不排布"，不是"少做事"。
    expect(result.hiddenCount).toBe(0);
  });

  it('passesFilter 是纯谓词，可单独使用', () => {
    expect(passesFilter(ROOT, EMPTY_TREE_FILTER, [])).toBe(true);
    expect(passesFilter(ROOT, { ...EMPTY_TREE_FILTER, bestPathOnly: true }, [])).toBe(false);
  });
});

describe('岛切换（TODO D6.4）', () => {
  const A = node({ id: 'a-root', island_id: 'a' });
  const A1 = node({ id: 'a-child', island_id: 'a', depth: 1, parent_id: 'a-root', operator: 'refine' });
  const B = node({ id: 'b-root', island_id: 'b' });
  const LEGACY = node({ id: 'old-root' });
  const all = [A, A1, B, LEGACY];
  const edges: TreeEdgeInput[] = [
    { source: 'a-root', target: 'a-child', kind: 'parent' },
    { source: 'a-root', target: 'b-root', kind: 'summary_cross' },
  ];

  it('默认不过滤：所有岛与历史单树节点一起出现（并列树）', () => {
    const result = filterTree(all, edges, EMPTY_TREE_FILTER);
    expect(result.nodes).toHaveLength(4);
    expect(result.hiddenCount).toBe(0);
  });

  it('选中一个岛只留它的节点，跨岛嫁接边随之消失', () => {
    // 边只要有一端被藏就不能画，否则会连到空气。这也是"单岛视图看不到交换边"
    // 的原因 —— 想看交换必须回到并列视图，界面不能假装那条边还在。
    const result = filterTree(all, edges, { ...EMPTY_TREE_FILTER, islands: ['a'] });
    expect(result.nodes.map((n) => n.id)).toEqual(['a-root', 'a-child']);
    // `kind` 在 `data` 里（React Flow 的 Edge 形状），断言写错位置会永远为 undefined。
    expect(result.edges.map((e) => e.data?.kind)).toEqual(['parent']);
  });

  it('多选两岛用来做对比，单选做不到', () => {
    const result = filterTree(all, edges, { ...EMPTY_TREE_FILTER, islands: ['a', 'b'] });
    expect(result.nodes.map((n) => n.id)).toEqual(['a-root', 'a-child', 'b-root']);
    expect(result.edges).toHaveLength(2);
  });

  it('空串岛 id 能被选中，不会被当成"没选"', () => {
    // 契约里历史单树节点的 island_id 是空串。`if (filter.islands.length)` 之外
    // 任何 falsy 判断都会让"只看历史单树"退化成一闪而过的全量视图。
    const result = filterTree(all, edges, { ...EMPTY_TREE_FILTER, islands: [''] });
    expect(result.nodes.map((n) => n.id)).toEqual(['old-root']);
  });

  it('节点数据带着岛归属与中文标签', () => {
    expect(toTreeNodeData(A).islandId).toBe('a');
    expect(toTreeNodeData(A).islandLabel).toBe('岛 a');
    // 缺字段（旧运行目录）与显式空串都归到"未分岛"。
    expect(toTreeNodeData(LEGACY).islandId).toBe('');
    expect(toTreeNodeData(LEGACY).islandLabel).toBe('未分岛（历史单树）');
  });

  it('筛选条的岛列表只列树里真实出现过的岛，并给出计数', () => {
    const options = islandOptions(all);
    expect(options).toEqual([
      { id: 'a', label: '岛 a', count: 2 },
      { id: 'b', label: '岛 b', count: 1 },
      { id: '', label: '未分岛（历史单树）', count: 1 },
    ]);
  });

  it('配置里有但从没产出节点的岛不出现在筛选条上', () => {
    // 引擎可能配了三岛而某一岛一个节点都没有；摆一个点不动的芯片
    // 会让人以为筛选坏了。
    expect(islandOptions([A, B]).map((option) => option.id)).toEqual(['a', 'b']);
    expect(islandOptions([])).toEqual([]);
  });
});

describe('完整图构建', () => {
  it('best_path 上的节点带 isOnBestPath 标记', () => {
    const graph = buildFlowGraph([ROOT, CHILD], [PARENT_EDGE], ['root-0001', 'child-0001']);
    expect(graph.nodes.every((n) => n.data.isOnBestPath)).toBe(true);
  });

  it('is_best 节点的显著性优先于噪声带判定', () => {
    // 既是 best 又落在噪声带内：必须显示 best，否则最优节点看起来像没进展。
    const best = node({ id: 'best-0001', is_best: true, within_noise_band: true });
    const graph = buildFlowGraph([best], []);
    expect(graph.nodes[0]?.data.significance).toBe('best');
  });
});

describe('合成树（性能测试用）', () => {
  it.each([100, 500, 1000])('%i 节点规模下生成成功且结构合法', (count) => {
    const { nodes, edges } = buildSyntheticTree(count);
    expect(nodes).toHaveLength(count);
    // 每个非根节点恰好一条父边。
    expect(edges.filter((e) => e.kind === 'parent')).toHaveLength(count - 1);
    // 边不能指向不存在的节点。
    const ids = new Set(nodes.map((n) => n.id));
    expect(edges.every((e) => ids.has(e.source) && ids.has(e.target))).toBe(true);
  });

  it('深度是对数级，不退化成链', () => {
    // 1000 节点若退化成链，布局会慢到卡死，深度必须受控。
    const { nodes } = buildSyntheticTree(1000, 4);
    const maxDepth = Math.max(...nodes.map((n) => n.depth));
    expect(maxDepth).toBeLessThan(20);
  });

  it('1000 节点布局在可接受耗时内完成', () => {
    const { nodes, edges } = buildSyntheticTree(1000);
    const started = performance.now();
    const graph = buildFlowGraph(nodes, edges);
    const elapsed = performance.now() - started;
    expect(graph.nodes).toHaveLength(1000);
    // 墙钟断言只在独占 CPU 时有效：1000 节点布局独占跑 0.97 s，多 worker
    // 并发时被抢 CPU 会飘到 6 s 以上（实测 6049 ms）—— 那是调度噪声不是
    // 算法退化。`pnpm test:perf` 设 FE_PERF_EXCLUSIVE=1 跑真正的预算。
    if (process.env.FE_PERF_EXCLUSIVE === '1') {
      // 宽松阈值，只拦"数量级退化"这类真问题；精确预算见 workbench-performance。
      expect(elapsed).toBeLessThan(3000);
    } else {
      console.log(
        `  1000 节点布局: ${elapsed.toFixed(0)} ms（墙钟断言跳过；用 pnpm test:perf 跑）`,
      );
    }
  }, 20_000);

  it('宽度为 1 时也合法（退化成链的边界）', () => {
    const { nodes, edges } = buildSyntheticTree(10, 1);
    expect(nodes).toHaveLength(10);
    expect(edges.filter((e) => e.kind === 'parent')).toHaveLength(9);
  });

  it('节点数为 0 或 1 时不产生边', () => {
    expect(buildSyntheticTree(0).edges).toEqual([]);
    expect(buildSyntheticTree(1).edges).toEqual([]);
  });
});

/**
 * 代数分带（概念图左侧那一条条「第 N 代 (n)」的竖带）。
 *
 * 分带是纯几何，所以整条不碰 DOM：坐标算偏了在浏览器里只表现为"带子挪了一点"，
 * 肉眼几乎不会发现，必须在这里钉住。
 */
describe('代数分带 rankBands', () => {
  function laidOut() {
    const { nodes, edges } = buildSyntheticTree(12, 3);
    return layoutTree(toFlowNodes(nodes), toFlowEdges(edges));
  }

  it('每一代一条带子，按代数升序且不重复', () => {
    const bands = rankBands(laidOut());
    expect(bands.length).toBeGreaterThan(1);
    const depths = bands.map((b) => b.depth);
    expect(depths).toEqual([...depths].sort((a, b) => a - b));
    expect(new Set(depths).size).toBe(depths.length);
  });

  it('计数之和等于节点总数（没有节点被漏掉或重复计入）', () => {
    const nodes = laidOut();
    const bands = rankBands(nodes);
    expect(bands.reduce((sum, band) => sum + band.count, 0)).toBe(nodes.length);
    expect(bands.every((band) => band.count > 0)).toBe(true);
  });

  it('所有条带共用同一个横向范围（等宽等左边界，不参差）', () => {
    const bands = rankBands(laidOut());
    expect(new Set(bands.map((band) => band.x)).size).toBe(1);
    expect(new Set(bands.map((band) => band.width)).size).toBe(1);
  });

  it('横向范围是整个树宽 + 左右 padding，纵向按代各自包围', () => {
    const nodes = laidOut();
    const paddingX = 18;
    const paddingTop = 30;
    const paddingBottom = 14;
    const bands = rankBands(nodes, { paddingX, paddingTop, paddingBottom });

    const minX = Math.min(...nodes.map((node) => node.position.x));
    const maxX = Math.max(...nodes.map((node) => node.position.x));
    expect(bands[0].x).toBe(minX - paddingX);
    expect(bands[0].width).toBe(maxX + TREE_NODE_WIDTH - minX + paddingX * 2);

    // 每个节点都必须落在横向范围内（含卡片自身宽度）。
    for (const node of nodes) {
      expect(node.position.x).toBeGreaterThanOrEqual(bands[0].x + paddingX);
      expect(node.position.x + TREE_NODE_WIDTH).toBeLessThanOrEqual(
        bands[0].x + bands[0].width - paddingX,
      );
    }

    for (const band of bands) {
      const members = nodes.filter((node) => node.data.depth === band.depth);
      expect(members).toHaveLength(band.count);
      const minY = Math.min(...members.map((node) => node.position.y));
      const maxY = Math.max(...members.map((node) => node.position.y));
      // 上留白要单独留得更大：条带标题写在这条留白里。
      expect(band.y).toBe(minY - paddingTop);
      expect(band.y + band.height).toBe(maxY + TREE_NODE_HEIGHT + paddingBottom);
      expect(paddingTop).toBeGreaterThan(paddingBottom);
    }
  });

  it('纯函数：同样输入两次算出的坐标完全相同', () => {
    expect(rankBands(laidOut())).toEqual(rankBands(laidOut()));
  });

  it('缺 depth 的节点不进任何带子（不编造代数）', () => {
    const nodes = laidOut();
    // 把第一个节点的 depth 抹掉，模拟旧版本引擎没写这个字段。
    const broken = nodes.map((node, index) =>
      index === 0 ? { ...node, data: { ...node.data, depth: undefined as unknown as number } } : node,
    );
    const total = rankBands(broken).reduce((sum, band) => sum + band.count, 0);
    expect(total).toBe(nodes.length - 1);
  });

  it('空树返回空数组（不留一条空带子）', () => {
    expect(rankBands([])).toEqual([]);
  });
});
