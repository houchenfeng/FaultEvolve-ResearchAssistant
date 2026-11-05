/**
 * 三层反思与修复链的纯逻辑测试（TODO 5.5）。
 *
 * 前提事实：真实 demo 运行里这三类事件一次都没触发（mock 通路不走反思与修复），
 * 所以这里全部用**合成事件与合成节点**验证，拿真实运行"验证通过"等于没测。
 */
import { describe, expect, it } from 'vitest';

import type { EventResponse, TreeNodeDto } from '@/generated/api';
import {
  buildReflections,
  buildRepairChain,
  EDGE_KIND_LABELS,
  isRepairer,
  REFLECTION_LAYERS,
  repairBookkeeping,
  summarizeLoop,
} from '@/features/workbench/reflection';

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
    ...overrides,
  };
}

function event(id: number, type: string, payload: Record<string, unknown> = {}): EventResponse {
  return {
    id,
    run_id: 'run-1',
    type,
    payload,
    ts: `2026-10-02T00:00:${String(id).padStart(2, '0')}`,
    is_known_type: true,
  };
}

describe('三层反思', () => {
  it('三层顺序固定为 设计 → 实现 → 机制', () => {
    expect(REFLECTION_LAYERS).toEqual(['design', 'implementation', 'mechanism']);
  });

  it('缺哪层就缺哪层，不拿别的层顶替', () => {
    const entries = buildReflections([event(1, 'reflection_design', { text: '第一版设计' })]);
    expect(entries).toHaveLength(3);
    expect(entries[0]?.text).toBe('第一版设计');
    expect(entries[1]?.event).toBeNull();
    expect(entries[2]?.event).toBeNull();
  });

  it('缺失的层 text 为 null 而不是空串（空串会冒充"反思了但没内容"）', () => {
    const entries = buildReflections([]);
    expect(entries.every((entry) => entry.text === null)).toBe(true);
    expect(entries.every((entry) => entry.label.length > 0)).toBe(true);
  });

  it('同一层多次反思取最后一次（最新的认知才代表当前状态）', () => {
    const entries = buildReflections([
      event(1, 'reflection_design', { text: '旧理解' }),
      event(2, 'reflection_design', { text: '新理解' }),
    ]);
    expect(entries[0]?.text).toBe('新理解');
    expect(entries[0]?.event?.id).toBe(2);
  });

  it('payload 的字段名不统一时依次尝试', () => {
    expect(buildReflections([event(1, 'reflection_design', { summary: '用 summary' })])[0]?.text).toBe(
      '用 summary',
    );
    expect(buildReflections([event(1, 'reflection_design', { reason: '用 reason' })])[0]?.text).toBe(
      '用 reason',
    );
  });

  it('payload 里没有文本字段时 text 为 null，不编造', () => {
    const entries = buildReflections([event(1, 'reflection_design', { unrelated: 1 })]);
    expect(entries[0]?.event).not.toBeNull();
    expect(entries[0]?.text).toBeNull();
  });

  it('空白字符串不算内容', () => {
    expect(buildReflections([event(1, 'reflection_design', { text: '   ' })])[0]?.text).toBeNull();
  });
});

describe('修复链（走 repair_parent_id，不走事件流）', () => {
  const failed = node({ id: 'failed-01', score: 3 });
  const repairer = node({
    id: 'repair-01',
    depth: 1,
    operator: 'repair',
    score: 8,
    repair_parent_id: 'failed-01',
    repair_count: 2,
    repair_exhausted: false,
  });

  it('还原出失败节点与修复节点', () => {
    const chain = buildRepairChain([failed, repairer]);
    expect(chain).toHaveLength(1);
    expect(chain[0]?.failedId).toBe('failed-01');
    expect(chain[0]?.repairerId).toBe('repair-01');
  });

  it('分数变化算得出来时给出数值', () => {
    expect(buildRepairChain([failed, repairer])[0]?.scoreDelta).toBeCloseTo(5, 6);
  });

  it('任一侧缺分数时 scoreDelta 为 null，不当成"没变化"', () => {
    const noScore = node({ id: 'repair-02', repair_parent_id: 'failed-01', score: null });
    expect(buildRepairChain([failed, noScore])[0]?.scoreDelta).toBeNull();
  });

  it('没有 repair_parent_id 的节点不进链', () => {
    expect(buildRepairChain([failed, node({ id: 'other-01' })])).toEqual([]);
  });

  it('悬空的 repair_parent_id 不生成假链（树已报过 warning）', () => {
    const dangling = node({ id: 'repair-03', repair_parent_id: 'ghost' });
    expect(buildRepairChain([dangling])).toEqual([]);
  });

  it('同一个失败节点被多次修复时每次都是独立一环', () => {
    const second = node({ id: 'repair-04', repair_parent_id: 'failed-01', score: 9 });
    expect(buildRepairChain([failed, repairer, second])).toHaveLength(2);
  });

  it('结果按失败节点 id 排序，顺序稳定可比较', () => {
    // 三条链：rb 修 b-failed，repairer 与 ra 各自修 failed-01（同一失败节点修两次）。
    const b = node({ id: 'b-failed', score: 1 });
    const rb = node({ id: 'rb-01', repair_parent_id: 'b-failed', score: 2 });
    const ra = node({ id: 'ra-01', repair_parent_id: 'failed-01', score: 2 });
    expect(buildRepairChain([rb, b, ra, failed, repairer]).map((l) => l.failedId)).toEqual([
      'b-failed',
      'failed-01',
      'failed-01',
    ]);
  });

  it('修复者身份可单独查询（修复节点自己持有 repair_parent_id）', () => {
    // 引擎 tree.py：新建的修复节点带 operator=REPAIR 且 repair_parent_id=失败节点 id。
    expect(isRepairer(repairer)).toBe(true);
    expect(isRepairer(failed)).toBe(false);
  });

  it('悬空的 repair_parent_id 仍算修复者（它确实尝试过修复）', () => {
    // 指向的节点不在列表里是数据问题，身份判定不该受影响。
    expect(isRepairer(node({ id: 'repair-03', repair_parent_id: 'ghost' }))).toBe(true);
  });

  it('修复次数与耗尽标志透传，缺失时是 null', () => {
    const link = buildRepairChain([failed, repairer])[0]!;
    expect(link.repairCount).toBe(2);
    expect(link.exhausted).toBe(false);
    expect(link.repairerStatus).toBe('done');
  });

  // 下面三条钉的是**引擎的落点**：计数与耗尽写在被修的失败节点上
  // （engine.py:2009 / engine.py:2006），而 repair_parent_id 指针在修复者身上。
  // 只盯修复者读，真实运行里永远读到 null —— 这个 bug 就是在造
  // hdd_mvp_faildemo_4b81c0d2 这份 fixture 时才暴露出来的。
  it('记账以失败节点为准，不看修复者身上同名的字段', () => {
    const failedNode = node({ id: 'f-01', repair_count: 3, repair_exhausted: true });
    const repairerNode = node({
      id: 'r-01',
      repair_parent_id: 'f-01',
      repair_count: 0,
      repair_exhausted: false,
    });
    const link = buildRepairChain([failedNode, repairerNode])[0]!;
    expect(link.repairCount).toBe(3);
    expect(link.exhausted).toBe(true);
  });

  it('失败节点自己没记时退回修复者（不静默变空）', () => {
    const bare = node({ id: 'f-02' });
    const carried = node({ id: 'r-02', repair_parent_id: 'f-02', repair_count: 2 });
    const link = buildRepairChain([bare, carried])[0]!;
    expect(link.repairCount).toBe(2);
  });

  it('两侧都没记就是 null，不是 0 / false', () => {
    const link = buildRepairChain([node({ id: 'f-03' }), node({ id: 'r-03', repair_parent_id: 'f-03' })])[0]!;
    expect(link.repairCount).toBeNull();
    expect(link.exhausted).toBeNull();
  });

  it('repairBookkeeping 直接调用时同样以失败节点优先', () => {
    expect(
      repairBookkeeping(
        node({ id: 'f', repair_count: 1, repair_exhausted: false }),
        node({ id: 'r', repair_count: 9, repair_exhausted: true }),
      ),
    ).toEqual({ count: 1, exhausted: false });
  });
});

describe('闭环汇总', () => {
  it('四档计数与修复链长度都对得上', () => {
    const nodes = [
      node({ id: 'a', is_best: true, within_noise_band: false, delta_score: 2 }),
      node({ id: 'b', within_noise_band: false, delta_score: 1 }),
      node({ id: 'c', within_noise_band: true, delta_score: 0.1, score: 2 }),
      node({ id: 'd', within_noise_band: null, delta_score: null }),
      node({ id: 'e', delta_score: 1, noise_delta: null, within_noise_band: null, score: null }),
      // c 分数 2，f 修到 9 ⇒ 修复成功。
      node({ id: 'f', repair_parent_id: 'c', score: 9 }),
    ];
    const summary = summarizeLoop(nodes, []);
    expect(summary.improvedCount).toBe(2);
    expect(summary.noiseCount).toBe(1);
    // d 没有 Δ（根节点常态）不计入 unknown；e 有 Δ 但缺噪声估计才算。
    expect(summary.unknownCount).toBe(1);
    // 6 个节点里只有 e 的 score 显式为 null（helper 默认给 10），其余 5 个都算已评估。
    expect(summary.evaluatedCount).toBe(5);
    expect(summary.repairCount).toBe(1);
    expect(summary.repairSucceeded).toBe(1);
  });

  it('修复未带来提升时计为失败', () => {
    const nodes = [
      node({ id: 'failed', score: 5 }),
      node({ id: 'repair', repair_parent_id: 'failed', score: 5 }),
    ];
    expect(summarizeLoop(nodes, []).repairFailed).toBe(1);
  });

  it('修复耗尽标记为 true 时计为失败', () => {
    const nodes = [
      node({ id: 'failed', score: 1 }),
      node({ id: 'repair', repair_parent_id: 'failed', score: 99, repair_exhausted: true }),
    ];
    const summary = summarizeLoop(nodes, []);
    // 分数涨了但引擎说耗尽了：两次都计入，两个口径各有其道理。
    expect(summary.repairSucceeded).toBe(1);
    expect(summary.repairFailed).toBe(1);
  });

  it('反思层数按实际触发的事件数统计', () => {
    const events = [event(1, 'reflection_design'), event(2, 'reflection_mechanism')];
    expect(summarizeLoop([], events).reflectionLayersPresent).toBe(2);
    expect(summarizeLoop([], []).reflectionLayersPresent).toBe(0);
  });

  it('空树空事件返回全零，不抛异常', () => {
    const summary = summarizeLoop([], []);
    expect(summary.evaluatedCount).toBe(0);
    expect(summary.repairCount).toBe(0);
  });
});

describe('边类型标签', () => {
  it('三种边都有中文标签，供图例使用', () => {
    expect(EDGE_KIND_LABELS.parent).toBe('父子');
    expect(EDGE_KIND_LABELS.crossover_second_parent).toBe('交叉第二父');
    expect(EDGE_KIND_LABELS.repair).toBe('修复');
  });
});
