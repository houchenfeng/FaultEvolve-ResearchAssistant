/**
 * 工作台性能测试（TODO 5.8）。
 *
 * 为什么全部用合成树而不是真实 fixture：demo 运行只有 **6 节点 / 19 事件**，
 * 比 TODO 要求的 100/500/1000 节点差两个数量级。拿 6 个节点跑性能断言，
 * 数字好看但什么都没证明 —— 这正是「合成数据全绿 ≠ 修好」的反面。
 *
 * 阈值故意设得宽松（比实测值宽 3–5 倍）：CI 机器比笔记本慢，
 * 阈值卡太紧只会变成随机红灯。真正要防的是**复杂度退化**，
 * 那是 1000 节点那条与 100 节点那条的比值在盯着。
 *
 * ## 为什么布局预算要在独占 CPU 下测
 *
 * 1000 节点的 dagre 布局**独占**跑要 0.97 s，多 worker 并发时被抢 CPU
 * 会飘到 7 s（实测 7046 ms，×7）。同一份代码、同一台机器，差的只是
 * 有没有人在旁边跑别的 —— 拿这种数字当性能预算，测的是调度器不是算法。
 *
 * 所以 `FE_PERF_EXCLUSIVE=1`（`pnpm test:perf` 会设）是布局预算的正式入口：
 * 只有它为真时才断言墙钟耗时。普通 `vitest run` 照常跑其余全部用例
 * （结构正确性、纯度、复杂度比值），只把墙钟断言标成 skipped 并说明原因。
 */
import { describe, expect, it } from 'vitest';

import type { EventResponse, TreeNodeDto } from '@/generated/api';
import {
  buildFlowGraph,
  buildSyntheticTree,
  EMPTY_TREE_FILTER,
  filterTree,
  layoutTree,
  passesFilter,
  toFlowEdges,
  toFlowNodes,
  type TreeEdgeInput,
} from '@/features/workbench/tree-adapter';
import {
  ancestorPaths,
  collapsibleIds,
  collectAncestorPaths,
  defaultCollapsedIds,
  edgesWithin,
  MAX_ANCESTOR_PATHS,
  relatedNodeIds,
  visibleNodeIds,
} from '@/features/workbench/tree-interactions';
import {
  buildRepairChain,
  isRepairer,
  summarizeLoop,
} from '@/features/workbench/reflection';
import {
  dedupeEvents,
  generationStats,
  splitGenerations,
} from '@/features/workbench/iteration-logic';

/**
 * 墙钟预算是否有效。
 *
 * 只有显式要求独占 CPU 时才为真。`describe.skipIf` 用它把整段布局预算
 * 在并发运行下标成 skipped —— **不静默跳过**：vitest 会在报告里列出
 * 跳过原因，`pnpm test` 也不会因此变绿而掩盖退化。
 */
const PERF_EXCLUSIVE = process.env.FE_PERF_EXCLUSIVE === '1';

/** 把毫秒数换算成「够不够用」的可读结论，失败时一眼看出差多少倍。 */
function budget(label: string, ms: number, limitMs: number) {
  console.log(`  ${label}: ${ms.toFixed(0)} ms（阈值 ${limitMs} ms）`);
  return expect(ms).toBeLessThan(limitMs);
}

/**
 * 跑 `rounds` 次、返回**耗时最小**的那一次结果。
 *
 * 为什么不是单次采样：CPU 抢占只会让样本变大、不会让它变小，所以最小值是
 * "这台机器真能跑多快"的稳定估计，而单次采样在负载下会把调度噪声报成
 * 算法退化。实测同一份代码同一台机器，1000 节点布局在 850 ms（独占）到
 * 3363 ms（同进程里跑了另外 17 个测试文件之后）之间摇摆 —— 阈值 3000 ms
 * 恰好落在这个区间里，于是同一份代码会一会儿红一会儿绿。
 *
 * 结构断言（长度、坐标）与墙钟无关，取哪一次的结果都成立。
 */
function minOf<T extends { ms: number }>(rounds: number, run: () => T): T {
  let best: T | null = null;
  for (let i = 0; i < rounds; i += 1) {
    const sample = run();
    if (best === null || sample.ms < best.ms) best = sample;
  }
  return best as T;
}

describe('性能：树布局与筛选（TODO 5.8）', () => {
  // 1000 节点：布局、筛选、折叠三条路径都要能在人眼可感的范围内完成。
  const big = buildSyntheticTree(1000, 4);
  const bigFlow = toFlowNodes(big.nodes, []);
  const bigEdges = toFlowEdges(big.edges as TreeEdgeInput[]);

  // 墙钟断言只在独占 CPU 时有效：并发下同一段 dagre 从 0.97 s 飘到 7 s。
  it.skipIf(!PERF_EXCLUSIVE)('1000 节点的 dagre 布局在 3 秒内完成', () => {
    const { laid, ms } = minOf(3, () => {
      const started = performance.now();
      const laidRun = layoutTree(bigFlow, bigEdges);
      return { ms: performance.now() - started, laid: laidRun };
    });
    expect(laid).toHaveLength(1000);
    // 坐标必须真的算出来了，不能全留在原点。
    expect(new Set(laid.map((n) => `${n.position.x},${n.position.y}`)).size).toBeGreaterThan(100);
    budget('1000 节点布局（3 次取最小）', ms, 3000);
  }, 60_000);

  it('布局是纯函数：同样输入两次调用坐标完全相同', () => {
    // 这一点是 D-B 决策的前提。坐标会抖的布局没法做截图回归测试。
    //
    // 超时显式给到 20 s：这条要把 1000 节点布局**跑两遍**（实测单遍 2.1 s），
    // vitest 默认 5 s 会在坐标比对之前就把测试掐掉——那时失败原因是超时，
    // 不是"坐标不一致"，会把纯度回归伪装成性能问题。
    const first = layoutTree(bigFlow, bigEdges);
    const second = layoutTree(bigFlow, bigEdges);
    expect(second.map((n) => n.position)).toEqual(first.map((n) => n.position));
  }, 20_000);

  it('1000 节点的全量筛选（不含 dagre 布局）在 200 ms 内完成', () => {
    // `filterTree` 的返回值里节点是**已经布局好的**，所以直接量它会把
    // dagre 的 1.8–2.1 s 算进筛选头上——上一条已经用 3000 ms 阈值单独把关
    // 布局，这里再量一遍只会让两条测试用同一个数字、其中一个必然先红。
    //
    // 拆分口径：节点筛选 + 边筛选 + 节点/边组装是我们的活，交给 dagre 的
    // 布局不是。这一条管前者，上一条管后者。
    const started = performance.now();
    const kept = big.nodes.filter((node) =>
      passesFilter(node, EMPTY_TREE_FILTER, []),
    );
    const keptIds = new Set(kept.map((node) => node.id));
    const keptEdges = big.edges.filter(
      (edge) =>
        keptIds.has((edge as TreeEdgeInput).source) &&
        keptIds.has((edge as TreeEdgeInput).target),
    );
    const flowNodes = toFlowNodes(kept, []);
    const flowEdges = toFlowEdges(keptEdges as TreeEdgeInput[]);
    const ms = performance.now() - started;
    // 口径不能悄悄变窄：组装结果必须与 filterTree 的输入一致。
    expect(flowNodes).toHaveLength(1000);
    expect(flowEdges.length).toBe(big.edges.length);
    expect(flowNodes).toHaveLength(bigFlow.length);
    budget('1000 节点筛选（不含布局）', ms, 200);
  });

  it('1000 节点的筛选判定本身在 100 ms 内完成（不含布局）', () => {
    // 布局是 dagre 的活，筛选是我们的活。混在一起量会让人误以为筛选慢。
    const kept = big.nodes.filter((node) =>
      passesFilter(node, EMPTY_TREE_FILTER, []),
    );
    const started = performance.now();
    for (let round = 0; round < 10; round += 1) {
      big.nodes.filter((node) => passesFilter(node, EMPTY_TREE_FILTER, []));
    }
    const ms = (performance.now() - started) / 10;
    expect(kept).toHaveLength(1000);
    budget('1000 节点筛选判定 ×10 均摊', ms, 100);
  });

  it('折叠可见性计算在 500 ms 内完成', () => {
    const collapsed = defaultCollapsedIds(big.nodes, big.edges as TreeEdgeInput[]);
    const started = performance.now();
    const visible = visibleNodeIds(
      bigFlow.map((n) => n.id),
      bigEdges,
      collapsed,
    );
    const ms = performance.now() - started;
    expect(visible.size).toBeGreaterThan(0);
    expect(visible.size).toBeLessThanOrEqual(1000);
    budget('1000 节点折叠计算', ms, 500);
  });

  /**
   * §12.6 唯一一条写了具体数字的预算：500 节点树**初次可交互** < 2 s。
   *
   * "可交互"不是"布局算完"，而是页面上首帧真正要跑的那一串：适配 →
   * 布局 → 默认折叠集合 → 可见集合 → 组装成画布节点。只量 `layoutTree`
   * 会把其余几步漏在预算外，页面照样卡；所以这里用 `buildFlowGraph`
   * 一次跑通整条首帧路径，跟 `TreeCanvas` 首次渲染干的事对齐。
   */
  it.skipIf(!PERF_EXCLUSIVE)('500 节点树首帧（适配+布局+折叠+可见）在 2 秒内完成', () => {
    const medium = buildSyntheticTree(500, 4);
    const mediumEdges = medium.edges as TreeEdgeInput[];
    const { laid, ms } = minOf(3, () => {
      const started = performance.now();
      // 与 TreeCanvas 首帧同一条链：筛选 → 默认折叠 → 可见集合 → 布局。
      // 末位 `false` 与 TreeCanvas 一致：折叠裁剪之后还要再布局一次，
      // 这里算的坐标必然作废。**这条预算测的就是"只算一次"的代价** ——
      // 传 true 会把 dagre 跑两遍，数字翻倍且不是页面真正干的事。
      const filtered = filterTree(medium.nodes, mediumEdges, EMPTY_TREE_FILTER, [], false);
      const collapsed = defaultCollapsedIds(medium.nodes, mediumEdges);
      const visible = visibleNodeIds(
        filtered.nodes.map((node) => node.id),
        mediumEdges,
        collapsed,
      );
      const kept = filtered.nodes.filter((node) => visible.has(node.id));
      const keptIds = new Set(kept.map((node) => node.id));
      // `filterTree` 出来的节点已经是画布节点（TreeFlowNode），`layoutTree` 直接
      // 吃它 —— 再套一层 `toFlowNodes` 是重复适配，tsc 也会因为缺 DTO 字段而拒绝。
      const result = layoutTree(
        kept,
        filtered.edges.filter(
          (edge) => keptIds.has(edge.source) && keptIds.has(edge.target),
        ),
      );
      return { ms: performance.now() - started, laid: result };
    });
    // 结构口径：真的算出了图，不是提前 return 空。
    expect(laid.length).toBeGreaterThan(0);
    expect(laid.length).toBeLessThanOrEqual(500);
    expect(new Set(laid.map((n) => `${n.position.x},${n.position.y}`)).size).toBeGreaterThan(50);
    budget('500 节点首帧（3 次取最小）', ms, 2000);
  }, 60_000);
});

describe('性能：规模增长不是指数级（TODO 5.8）', () => {
  /**
   * 这一条比任何绝对阈值都有价值。
   *
   * 节点数翻 5 倍（200 → 1000），如果布局耗时涨了 25 倍以上，说明算法里有
   * 平方项甚至更糟的东西 —— 这种退化在 200 节点时看不出来，到 1000 节点
   * 才会让用户界面卡死。绝对阈值会因机器而异，**增长倍率不会**。
   *
   * 但它仍要跑真实布局，所以和上面那条一样需要独占 CPU：分子分母都是墙钟，
   * 分子被抢 CPU 而分母没有，比值会失真。
   *
   * **用"3 次取最小"而不是单次采样**：抢占只会让样本变大、不会让它变小，
   * 所以最小值才是这台机器"真能跑多快"的稳定估计。实测同一份代码同一台机器，
   * 单次采样的比值在 ×10.6 与 ×26 之间摇摆（后者就是分子被抢占、分母刚好没被
   * 抢到的假信号）—— 那会把调度噪声报成算法退化，正是这条断言最该避免的事。
   */
  it.skipIf(!PERF_EXCLUSIVE)('节点数 ×5，布局耗时增长远小于 25 倍', () => {
    const timeFor = (count: number) => {
      const tree = buildSyntheticTree(count, 4);
      const flow = toFlowNodes(tree.nodes, []);
      const edges = toFlowEdges(tree.edges as TreeEdgeInput[]);
      const started = performance.now();
      layoutTree(flow, edges);
      return performance.now() - started;
    };
    // 先跑一次小的把 JIT 预热排除掉，否则第一次调用天然最慢。
    timeFor(200);
    const bestOf = (count: number, rounds: number) => {
      let best = Number.POSITIVE_INFINITY;
      for (let i = 0; i < rounds; i += 1) best = Math.min(best, timeFor(count));
      return best;
    };
    const small = bestOf(200, 3);
    const large = bestOf(1000, 3);
    const ratio = small > 0 ? large / small : 1;
    console.log(
      `  200 节点 ${small.toFixed(0)} ms → 1000 节点 ${large.toFixed(0)} ms（×${ratio.toFixed(1)}，各取 3 次最小）`,
    );
    expect(ratio).toBeLessThan(25);
  }, 60_000);
});

describe('性能：事件流处理（TODO 5.8）', () => {
  /** 造 1000 条事件，payload 里带 node_id 以便走最贵的路径。 */
  function manyEvents(count: number): EventResponse[] {
    const types = [
      'init_evaluated',
      'node_evaluated',
      'repair_success',
      'reflection_design',
      'knowledge_adopted',
    ];
    return Array.from({ length: count }, (_, i) => ({
      id: i + 1,
      run_id: 'perf',
      ts: new Date(1_700_000_000_000 + i * 1000).toISOString(),
      type: types[i % types.length]!,
      is_known_type: true,
      payload: { node_id: `node-${i % 50}`, text: `第 ${i} 步`, value: i },
    }));
  }

  it('1000 条事件的去重 + 切分 + 统计在 1 秒内完成', () => {
    const events = manyEvents(1000);
    const started = performance.now();
    const deduped = dedupeEvents(events);
    const generations = splitGenerations(deduped);
    const stats = generations.map((g) => generationStats(g));
    const ms = performance.now() - started;
    expect(deduped).toHaveLength(1000);
    expect(stats.length).toBeGreaterThan(0);
    budget('1000 事件处理', ms, 1000);
  });
});

describe('性能：树上的图算法（TODO 5.8）', () => {
  const tree = buildSyntheticTree(500, 4);
  const edges = toFlowEdges(tree.edges as TreeEdgeInput[]);

  it('500 节点上做 100 次双亲路径追溯在 2 秒内完成', () => {
    const targets = tree.nodes.slice(1, 101);
    const started = performance.now();
    const total = targets.reduce((sum, node) => sum + ancestorPaths(node.id, edges).length, 0);
    const ms = performance.now() - started;
    expect(total).toBeGreaterThanOrEqual(targets.length);
    budget('100 次祖先路径追溯', ms, 2000);
  });

  it('最坏情况（每个节点都是 crossover）也不失控', () => {
    // crossoverEvery=1 ⇒ 每层都分叉 ⇒ 路径数 2^深度。这不是真实引擎会产生的
    // 形状，但它是**必须不崩**的边界：演示数据里 crossover 是 0 次，所以只有
    // 合成数据能碰到它。早先没有上限时，100 节点的这种树就跑不完。
    const worst = buildSyntheticTree(300, 4, 1);
    const worstEdges = toFlowEdges(worst.edges as TreeEdgeInput[]);
    const started = performance.now();
    let capped = 0;
    for (const node of worst.nodes) {
      const result = collectAncestorPaths(node.id, worstEdges);
      expect(result.paths.length).toBeLessThanOrEqual(MAX_ANCESTOR_PATHS);
      if (result.truncated) capped += 1;
    }
    const ms = performance.now() - started;
    // 触顶是预期行为（并且必须被标记出来），不是失败。
    expect(capped).toBeGreaterThan(0);
    budget('300 节点全 crossover 追溯', ms, 1000);
  });

  it('最坏情况下 relatedNodeIds 仍是 O(祖先数)', () => {
    const worst = buildSyntheticTree(300, 4, 1);
    const worstEdges = toFlowEdges(worst.edges as TreeEdgeInput[]);
    const started = performance.now();
    for (const node of worst.nodes) relatedNodeIds(node.id, worstEdges);
    const ms = performance.now() - started;
    budget('300 节点全 crossover 相关集合', ms, 1000);
  });

  it('500 节点上批量算可折叠集合与相关节点在 1 秒内完成', () => {
    const started = performance.now();
    const collapsible = collapsibleIds(edges);
    const related = tree.nodes.slice(0, 100).map((n) => relatedNodeIds(n.id, edges).size);
    const within = edgesWithin(new Set(tree.nodes.slice(0, 20).map((n) => n.id)), edges).length;
    const ms = performance.now() - started;
    expect(collapsible.size).toBeGreaterThan(0);
    expect(related).toHaveLength(100);
    expect(within).toBeGreaterThanOrEqual(0);
    budget('批量图查询', ms, 1000);
  });
});

describe('性能：节点级聚合（TODO 5.8）', () => {
  it('1000 节点的修复链 / 修复者判定 / 闭环汇总在 1 秒内完成', () => {
    const nodes: TreeNodeDto[] = buildSyntheticTree(1000, 4).nodes;
    // 给 5% 的节点挂上 repair_parent_id，模拟真实修复比例。
    for (let i = 20; i < nodes.length; i += 20) {
      const target = nodes[i - 1];
      if (target) nodes[i] = { ...nodes[i]!, repair_parent_id: target.id };
    }
    const events: EventResponse[] = [
      {
        id: 1,
        run_id: 'perf',
        ts: '2026-10-02T00:00:00',
        type: 'reflection_design',
        is_known_type: true,
        payload: { node_id: nodes[1]!.id, text: '重新设计评分函数' },
      },
    ];

    const started = performance.now();
    const chain = buildRepairChain(nodes);
    const repairers = nodes.filter((n) => isRepairer(n)).length;
    const summary = summarizeLoop(nodes, events);
    const ms = performance.now() - started;
    expect(chain.length).toBeGreaterThan(0);
    expect(repairers).toBeGreaterThan(0);
    expect(summary.repairCount).toBe(chain.length);
    expect(summary.reflectionLayersPresent).toBe(1);
    budget('1000 节点聚合', ms, 1000);
  });

  it('1000 节点构造完整图（适配 + 布局一次到位）不重复计算坐标', () => {
    const tree = buildSyntheticTree(1000, 4);
    // 墙钟断言只在独占 CPU 时有效，且要取多次最小值（见 `minOf` 的说明）。
    const rounds = PERF_EXCLUSIVE ? 3 : 1;
    const { graph, ms } = minOf(rounds, () => {
      const started = performance.now();
      const built = buildFlowGraph(tree.nodes, tree.edges as TreeEdgeInput[]);
      return { ms: performance.now() - started, graph: built };
    });
    // 坐标断言始终有效：它是结构正确性，不是墙钟。
    expect(graph.nodes).toHaveLength(1000);
    expect(graph.edges.length).toBeGreaterThan(900);
    // 坐标必须真的算出来了，不能全留在原点（"不重复计算"的可观测后果）。
    const distinct = new Set(
      graph.nodes.map((n) => `${n.position.x},${n.position.y}`),
    ).size;
    expect(distinct).toBeGreaterThan(100);
    // 墙钟部分只在独占 CPU 时断言：这条量的是 dagre，和上面那条同源。
    if (PERF_EXCLUSIVE) {
      budget('1000 节点整图构建（3 次取最小）', ms, 3000);
    } else {
      console.log(
        `  1000 节点整图构建: ${ms.toFixed(0)} ms（墙钟断言跳过；用 pnpm test:perf 跑）`,
      );
    }
  }, 60_000);
});
