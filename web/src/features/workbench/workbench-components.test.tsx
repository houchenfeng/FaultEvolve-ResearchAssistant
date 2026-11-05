/**
 * 工作台组件测试（TODO 5.1–5.7 的组件半边）。
 *
 * 重点覆盖 PRD 明确要求的**行为**而不是快照：
 * - 未评分不显示成 0（TODO 5.2 硬要求）
 * - 状态不能只靠颜色（PRD §10.1）
 * - 代码只读、不可编辑（PRD §10.3）
 * - 指标缺失显示「未记录」（PRD §10.3）
 * - 折叠/筛选后计数正确（PRD §10.5）
 */
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ReactFlowProvider } from '@xyflow/react';
import { describe, expect, it, vi } from 'vitest';

import type {
  EventResponse,
  NodeDetailResponse,
  ScoreboardEntryResponse,
  ScorePointResponse,
  TreeEdgeKind,
  TreeNodeDto,
} from '@/generated/api';
import { BudgetPanel } from '@/features/workbench/BudgetPanel';
import { EventStream } from '@/features/workbench/EventStream';
import { LeaderboardPanel } from '@/features/workbench/LeaderboardPanel';
import { NodeDrawer } from '@/features/workbench/NodeDrawer';
import { ScoreTimeline } from '@/features/workbench/ScoreTimeline';
import { EDGE_KIND_LABELS } from '@/features/workbench/reflection';
import { significanceAccent } from '@/features/workbench/significance';
import { TreeEdgeLegend, TreeNodeCard, TreeSignificanceLegend } from '@/features/workbench/TreeNodeCard';
import { TreeFilters } from '@/features/workbench/TreeFilters';
import {
  EDGE_STYLE,
  EMPTY_TREE_FILTER,
  toTreeNodeData,
  type TreeFilter,
} from '@/features/workbench/tree-adapter';

function node(overrides: Partial<TreeNodeDto> = {}): TreeNodeDto {
  return {
    id: 'abcd1234efgh',
    branch_id: 'main',
    depth: 0,
    operator: 'init',
    hypothesis_status: 'undetermined',
    status: 'done',
    score: 22.81,
    delta_score: 0.5,
    noise_delta: 0.1,
    within_noise_band: false,
    adopted_card_ids: [],
    offered_card_ids: [],
    ...overrides,
  };
}

function detail(overrides: Partial<NodeDetailResponse> = {}): NodeDetailResponse {
  return {
    contract_version: '1.5.0',
    run_id: 'run-1',
    node: node(),
    artifact: null,
    evaluation: null,
    insights: [],
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

describe('节点卡：八项视觉信息（PRD 10.1）', () => {
  function renderCard(data: Partial<TreeNodeDto> = {}, extra: Record<string, unknown> = {}) {
    const n = node(data);
    // 派生字段一律走生产路径的 `toTreeNodeData`，不在测试里手搓第二份：
    // 手搓的那份会和适配层各自漂移，届时"测试通过"就不代表组件显示对了。
    return render(
      <TreeNodeCard
        data={{ ...toTreeNodeData(n), ...extra }}
        id={n.id}
        type="treeNode"
      />,
      // 节点卡里有 <Handle>，它读的是 React Flow 的 store。生产路径上
      // TreeCanvas 已经提供了 provider，测试要还原同样的祖先环境。
      { wrapper: ReactFlowProvider },
    );
  }

  it('未评分显示「未评分」而不是 0', () => {
    renderCard({ score: null });
    expect(screen.getByText('未评分')).toBeInTheDocument();
    expect(screen.queryByText('0.00')).not.toBeInTheDocument();
  });

  it('真实的 0 分显示为 0.00，与未评分区分', () => {
    renderCard({ score: 0 });
    expect(screen.getByText('0.00')).toBeInTheDocument();
  });

  it('短 ID 与算子、状态都显示', () => {
    renderCard({ operator: 'refine' });
    expect(screen.getByText('abcd1234')).toBeInTheDocument();
    expect(screen.getByText('精炼')).toBeInTheDocument();
  });

  it('状态既有符号也有文字，不只靠颜色（PRD 10.1 硬要求）', () => {
    renderCard({ status: 'invalid' }, { statusLabel: '非法' });
    // 符号与文字同时存在，色盲用户也能区分。
    expect(screen.getByText('✕')).toBeInTheDocument();
    expect(screen.getByText('非法')).toBeInTheDocument();
  });

  it('最优节点有文字标注而不只是星号', () => {
    renderCard({ is_best: true });
    expect(screen.getByText(/最优/)).toBeInTheDocument();
  });

  it('crossover 节点标出「双亲」', () => {
    renderCard({ second_parent_ids: ['parent-01'] }, { hasSecondParent: true });
    expect(screen.getByText(/双亲/)).toBeInTheDocument();
  });

  it('知识卡数与投放数分别显示', () => {
    renderCard(
      { adopted_card_ids: ['FE01', 'M01'], offered_card_ids: ['M01', 'T01', 'E01'] },
      { cardCount: 2, offeredCardCount: 3 },
    );
    expect(screen.getByText(/卡 2/)).toBeInTheDocument();
    expect(screen.getByText('/3')).toBeInTheDocument();
  });

  it('预置注入的卡单独标出（不在投放列表里的那些）', () => {
    renderCard({ adopted_card_ids: ['FE01'] }, { cardCount: 1, injectedCardIds: ['FE01'] });
    expect(screen.getByText(/预置 1/)).toBeInTheDocument();
  });

  it('Δ 有正负号', () => {
    renderCard({ delta_score: -1.5 }, { deltaLabel: '-1.50' });
    expect(screen.getByText(/Δ -1.50/)).toBeInTheDocument();
  });

  // —— 三岛（TODO D6.4）的节点卡半边：岛归属必须在节点上看得见 ——

  it('有岛的节点显示岛字母，title 给出完整说明', () => {
    const { container } = renderCard({ island_id: 'b' });
    const badge = container.querySelector('[data-island="b"]');
    expect(badge).not.toBeNull();
    expect(badge?.textContent).toBe('b');
    expect(badge?.getAttribute('title')).toBe('所属进化岛：岛 b');
  });

  it('历史单树运行（island_id 空串）不显示岛徽标', () => {
    // 显示「未分岛」会让人以为存在一个名叫"未分岛"的岛。
    const { container } = renderCard({ island_id: '' });
    expect(container.querySelector('[data-island]')).toBeNull();
  });

  // ——「显著性分档必须视觉可辨」（TODO 5.4）的组件半边 ——

  it('「无法判断」用虚线边框，与实线的「噪声内」分开（只有深浅差别不算分档）', () => {
    const card = (container: HTMLElement) =>
      container.querySelector('[data-testid^="tree-node-"]') as HTMLElement;

    // within_noise_band = null ⇒ 无法判断（缺噪声估计，不是"没有改进"）
    expect(card(renderCard({ within_noise_band: null }).container).className).toContain(
      'border-dashed',
    );

    // 同一个节点补上噪声带判定后必须是实线 —— 否则"虚线"就只是装饰，
    // 不能承载"未定"这层含义。
    expect(card(renderCard({ within_noise_band: true }).container).className).not.toContain(
      'border-dashed',
    );
  });
});

describe('边图例', () => {
  it('四种边都有文字标签（不只靠线型区分）', () => {
    render(<TreeEdgeLegend />);
    expect(screen.getByText('父子')).toBeInTheDocument();
    expect(screen.getByText('交叉第二父')).toBeInTheDocument();
    expect(screen.getByText('修复')).toBeInTheDocument();
    // D6.3 加的第四种边（外岛摘要嫁接）。它此前不在图例里 —— 画布上出现
    // 绿色长虚线时用户没有对照物，只能猜。
    expect(screen.getByText('外岛摘要嫁接')).toBeInTheDocument();
  });

  it('图例样本与画布读同一张线型表：每条边的 stroke/dash 都等于 EDGE_STYLE', () => {
    render(<TreeEdgeLegend />);
    for (const kind of Object.keys(EDGE_STYLE) as TreeEdgeKind[]) {
      const line = screen.getByText(EDGE_KIND_LABELS[kind]).closest('span')?.querySelector('line');
      expect(line, `kind=${kind} 的图例样本缺失`).not.toBeNull();
      // 期望值取自 EDGE_STYLE 本身：图例若被改回自己手写一份颜色表，
      // 只要两处有一点不一致这里就会失败（D6.3 漏更新图例就是这么发生的）。
      expect(line?.getAttribute('stroke')).toBe(EDGE_STYLE[kind].stroke);
      expect(line?.getAttribute('stroke-dasharray')).toBe(EDGE_STYLE[kind].dash ?? null);
    }
  });

  it('最优路径也有文字标签 —— 它是叠加的高亮，不是第四种边类型', () => {
    render(<TreeEdgeLegend />);
    expect(screen.getByText('最佳路径')).toBeInTheDocument();
  });
});

describe('显著性图例', () => {
  it('四档都有文字标签（不能只给四个色块）', () => {
    render(<TreeSignificanceLegend />);
    for (const label of ['当前最优', '有效改进', '噪声内', '无法判断']) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
  });
});

describe('筛选条：岛切换（TODO D6.4）', () => {
  const three = [
    node({ id: 'a1', island_id: 'a' }),
    node({ id: 'b1', island_id: 'b' }),
    node({ id: 'c1', island_id: 'c' }),
  ];

  function filters(filter: TreeFilter = EMPTY_TREE_FILTER, nodes: TreeNodeDto[] = three) {
    const onChange = vi.fn();
    render(
      <TreeFilters filter={filter} onChange={onChange} nodes={nodes} collapsedCount={0} />,
    );
    return { onChange };
  }

  it('分出多个岛时每岛一枚芯片，带该岛节点计数', () => {
    filters();
    for (const label of ['岛 a 1', '岛 b 1', '岛 c 1']) {
      expect(screen.getByRole('button', { name: label })).toBeInTheDocument();
    }
  });

  it('点芯片把该岛提交给父组件（本组件是无状态受控表单）', async () => {
    const { onChange } = filters();
    await userEvent.click(screen.getByRole('button', { name: '岛 b 1' }));
    expect(onChange).toHaveBeenCalledWith({ ...EMPTY_TREE_FILTER, islands: ['b'] });
  });

  it('单岛与历史单树运行不显示岛芯片', () => {
    // 摆一排点不动的芯片会让人以为还有别的岛被藏起来了。
    render(
      <TreeFilters
        filter={EMPTY_TREE_FILTER}
        onChange={vi.fn()}
        nodes={[node({ id: 'x', island_id: '' })]}
        collapsedCount={0}
      />,
    );
    expect(screen.queryByText(/^进化岛$/)).not.toBeInTheDocument();
  });

  it('没筛选岛时没有「看全部岛」；选中后出现，点了提交空岛筛选', async () => {
    const onChange = vi.fn();
    const { rerender } = render(
      <TreeFilters filter={EMPTY_TREE_FILTER} onChange={onChange} nodes={three} collapsedCount={0} />,
    );
    expect(screen.queryByRole('button', { name: '看全部岛' })).not.toBeInTheDocument();
    // 受控组件：父组件把选中态换回来（生产路径上就是 `filter.islands`）。
    rerender(
      <TreeFilters
        filter={{ ...EMPTY_TREE_FILTER, islands: ['a'] }}
        onChange={onChange}
        nodes={three}
        collapsedCount={0}
      />,
    );
    await userEvent.click(screen.getByRole('button', { name: '看全部岛' }));
    // 清空提交 `islands: []` 而不是"把每个岛都列一遍" —— 后者在引擎加第四个
    // 岛时会漏掉它。
    expect(onChange).toHaveBeenCalledWith({ ...EMPTY_TREE_FILTER, islands: [] });
  });

  it('岛筛选生效后「清除筛选」按钮才在（默认状态不显示）', () => {
    render(
      <TreeFilters
        filter={{ ...EMPTY_TREE_FILTER, islands: ['a'] }}
        onChange={vi.fn()}
        nodes={three}
        collapsedCount={0}
      />,
    );
    expect(screen.getByRole('button', { name: '清除筛选' })).toBeInTheDocument();
  });
});

describe('节点卡：显著性分档的边框', () => {
  it('边框色由显著性分档决定，四档各不相同（TODO 5.4 分档要视觉可辨）', () => {
    const colors = (['best', 'progress', 'noise', 'unknown'] as const).map(significanceAccent);
    expect(new Set(colors).size).toBe(4);
  });
});

describe('节点详情抽屉：五个标签（TODO 5.3）', () => {
  it('五个标签都在', () => {
    render(<NodeDrawer detail={detail()} events={[]} onClose={() => {}} />);
    for (const label of ['概览', '指标', '代码差异', '知识与记忆', '事件与成本']) {
      expect(screen.getByRole('button', { name: label })).toBeInTheDocument();
    }
  });

  it('概览显示显著性的可读解释', () => {
    render(<NodeDrawer detail={detail()} events={[]} onClose={() => {}} />);
    // 断言完整解释句而不是「超出噪声带」四个字 —— 后者同时出现在档位标签和
    // 解释句里，getByText 会因为匹配到两个元素而失败。
    expect(screen.getByText(/超出噪声带 ±0\.100/)).toBeInTheDocument();
  });

  it('头部显示节点所属的岛（TODO D6.4）', () => {
    const { container } = render(
      <NodeDrawer detail={detail({ node: node({ island_id: 'b' }) })} events={[]} onClose={() => {}} />,
    );
    expect(container.querySelector('[data-island="b"]')).toHaveTextContent('所属进化岛：岛 b');
  });

  it('历史单树节点（island_id 空串）不显示岛行，也不写「未分岛」', () => {
    const { container } = render(
      <NodeDrawer detail={detail({ node: node({ island_id: '' }) })} events={[]} onClose={() => {}} />,
    );
    expect(container.querySelector('[data-island]')).toBeNull();
    expect(screen.queryByText(/未分岛/)).not.toBeInTheDocument();
  });

  it('无法判断时明说无法判断，不显示"无改进"', () => {
    render(
      <NodeDrawer
        detail={detail({ node: node({ within_noise_band: null, delta_score: null }) })}
        events={[]}
        onClose={() => {}}
      />,
    );
    expect(screen.getByText(/该节点没有记录 Δ，无法判断/)).toBeInTheDocument();
    expect(screen.queryByText('有效改进')).not.toBeInTheDocument();
  });

  it('指标缺失显示「未记录」而不是 0', async () => {
    render(
      <NodeDrawer
        detail={detail({ evaluation: { node_id: 'abcd1234efgh', metric: {} } })}
        events={[]}
        onClose={() => {}}
      />,
    );
    await userEvent.click(screen.getByRole('button', { name: '指标' }));
    expect(screen.getAllByText('未记录').length).toBeGreaterThan(0);
    expect(screen.queryByText('0.0000')).not.toBeInTheDocument();
  });

  it('evaluator 的额外指标全部列出', async () => {
    render(
      <NodeDrawer
        detail={
          detail({
            evaluation: {
              node_id: 'abcd1234efgh',
              metric: { F1: 0.82, AUPRC: 0.51, R_at_FAR: 0.9 },
            },
          })
        }
        events={[]}
        onClose={() => {}}
      />,
    );
    await userEvent.click(screen.getByRole('button', { name: '指标' }));
    expect(screen.getByText('F1')).toBeInTheDocument();
    expect(screen.getByText('0.8200')).toBeInTheDocument();
    expect(screen.getByText('R_at_FAR')).toBeInTheDocument();
  });

  it('代码只读：没有可编辑控件（PRD 10.3 硬要求）', async () => {
    render(
      <NodeDrawer
        detail={detail({ artifact: { node_id: 'abcd1234efgh', state: 'available', code: 'print(1)' } })}
        events={[]}
        onClose={() => {}}
      />,
    );
    await userEvent.click(screen.getByRole('button', { name: '代码差异' }));
    expect(screen.getByText('print(1)')).toBeInTheDocument();
    // textarea / contentEditable 一个都不能有。
    expect(document.querySelector('textarea')).toBeNull();
    expect(document.querySelector('[contenteditable]')).toBeNull();
    expect(document.querySelector('input')).toBeNull();
  });

  it('无 diff 时说明原因，不显示空白', async () => {
    render(<NodeDrawer detail={detail()} events={[]} onClose={() => {}} />);
    await userEvent.click(screen.getByRole('button', { name: '代码差异' }));
    expect(screen.getByText(/没有可显示的差异/)).toBeInTheDocument();
  });

  it('知识页把采纳卡与投放卡分开，并解释预置注入', async () => {
    render(
      <NodeDrawer
        detail={detail({
          node: node({ adopted_card_ids: ['FE01', 'M01'], offered_card_ids: ['M01', 'T01'] }),
          adopted_card_ids: ['FE01', 'M01'],
        })}
        events={[]}
        onClose={() => {}}
      />,
    );
    await userEvent.click(screen.getByRole('button', { name: '知识与记忆' }));
    expect(screen.getByText('FE01')).toBeInTheDocument();
    // 明确告诉用户 FE01 没有投放记录，而不是显示成"2/2"。
    expect(screen.getByText(/预置注入/)).toBeInTheDocument();
  });

  it('三层反思全都没发生时给一句概括，而不是三行占位', async () => {
    render(<NodeDrawer detail={detail()} events={[]} onClose={() => {}} />);
    await userEvent.click(screen.getByRole('button', { name: '知识与记忆' }));
    expect(screen.getByText('该节点没有反思记录')).toBeInTheDocument();
    expect(screen.queryByText('（未发生）')).not.toBeInTheDocument();
  });

  it('只有一层发生时，其余两层逐层标明未发生', async () => {
    render(
      <NodeDrawer
        detail={detail()}
        events={[
          event(1, 'reflection_design', { node_id: 'abcd1234efgh', text: '重新设计评分函数' }),
        ]}
        onClose={() => {}}
      />,
    );
    await userEvent.click(screen.getByRole('button', { name: '知识与记忆' }));
    // 有内容的那层不标未发生，缺的两层才标 —— 这才看得出"缺哪一层"。
    expect(screen.getAllByText('（未发生）')).toHaveLength(2);
    expect(screen.queryByText('该节点没有反思记录')).not.toBeInTheDocument();
  });

  it('反思事件能在抽屉里显示出来', async () => {
    render(
      <NodeDrawer
        detail={detail()}
        events={[
          event(1, 'reflection_design', { node_id: 'abcd1234efgh', text: '重新设计评分函数' }),
        ]}
        onClose={() => {}}
      />,
    );
    await userEvent.click(screen.getByRole('button', { name: '知识与记忆' }));
    expect(screen.getByText('重新设计评分函数')).toBeInTheDocument();
  });

  it('相关事件按节点过滤，只显示自己的', async () => {
    render(
      <NodeDrawer
        detail={detail()}
        events={[
          event(1, 'repair_failed', { node_id: 'abcd1234efgh' }),
          event(2, 'repair_failed', { node_id: 'other-node' }),
        ]}
        onClose={() => {}}
      />,
    );
    await userEvent.click(screen.getByRole('button', { name: '事件与成本' }));
    const section = screen.getByText(/相关事件（1）/);
    expect(section).toBeInTheDocument();
  });

  // 引擎把 repair_count / repair_exhausted 写在**被修的失败节点**上
  // （engine.py:2009 / engine.py:2006），而 repair_parent_id 指针在修复者身上。
  // 抽屉只盯当前节点读会读到 0 / false，于是「重试 N 次」「已耗尽」在真实运行
  // 里永远不显示 —— 有了 nodeById 才能顺着指针反查回去。
  it('修复来源显示被修节点的重试次数与耗尽标志', async () => {
    const failedNode = node({ id: 'fa11ed02', repair_count: 3, repair_exhausted: true });
    const repairer = node({
      id: 'f1xed002',
      repair_parent_id: 'fa11ed02',
      // 修复者自己身上的同名字段恒为 0 / false，不该被采信。
      repair_count: 0,
      repair_exhausted: false,
    });
    render(
      <NodeDrawer
        detail={detail({ node: repairer })}
        events={[]}
        nodeById={new Map([[failedNode.id, failedNode]])}
        onClose={() => {}}
      />,
    );
    await userEvent.click(screen.getByRole('button', { name: '概览' }));
    expect(screen.getByText(/重试 3 次/)).toBeInTheDocument();
    expect(screen.getByText(/已耗尽/)).toBeInTheDocument();
  });

  it('拿不到索引时退回读当前节点，不崩也不显示假的 0', async () => {
    render(
      <NodeDrawer
        detail={detail({
          node: node({ id: 'f1xed002', repair_parent_id: 'fa11ed02', repair_count: null }),
        })}
        events={[]}
        onClose={() => {}}
      />,
    );
    await userEvent.click(screen.getByRole('button', { name: '概览' }));
    expect(screen.getByText('修复来源')).toBeInTheDocument();
    expect(screen.queryByText(/重试/)).not.toBeInTheDocument();
  });

  it('修复者不在「事件与成本」里重复显示一个无意义的 0 次', async () => {
    const failedNode = node({ id: 'fa11ed02', repair_count: 3 });
    render(
      <NodeDrawer
        detail={detail({ node: node({ id: 'f1xed002', repair_parent_id: 'fa11ed02' }) })}
        events={[]}
        nodeById={new Map([[failedNode.id, failedNode]])}
        onClose={() => {}}
      />,
    );
    await userEvent.click(screen.getByRole('button', { name: '事件与成本' }));
    expect(screen.queryByText('修复重试')).not.toBeInTheDocument();
  });
});

describe('事件流（TODO 5.6）', () => {
  it('按 iteration_complete 分代', () => {
    render(
      <EventStream
        events={[
          event(1, 'init_evaluated'),
          event(2, 'iteration_complete'),
          event(3, 'operator_selected'),
        ]}
      />,
    );
    expect(screen.getByText('第 0 代')).toBeInTheDocument();
    expect(screen.getByText('第 1 代')).toBeInTheDocument();
  });

  it('已知事件出中文标签', () => {
    render(<EventStream events={[event(1, 'init_evaluated')]} />);
    expect(screen.getByText('初始程序已评估')).toBeInTheDocument();
  });

  it('未知类型原样显示并标记，不当成错误', () => {
    render(
      <EventStream events={[{ ...event(1, 'brand_new_event'), is_known_type: false }]} />,
    );
    // 原样显示原始 type，不替换成中文标签也不吞掉。
    expect(screen.getByText('brand_new_event')).toBeInTheDocument();
    // 「未知类型」在统计条和隐藏按钮里各出现一次，所以锚定带数字的那条。
    expect(screen.getByText('1 个未知类型')).toBeInTheDocument();
  });

  it('可以隐藏前端不认识的事件', async () => {
    render(
      <EventStream
        events={[
          { ...event(1, 'mystery_one'), is_known_type: false },
          event(2, 'init_evaluated'),
        ]}
      />,
    );
    expect(screen.getByText('mystery_one')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /隐藏未知类型/ }));
    expect(screen.queryByText('mystery_one')).not.toBeInTheDocument();
  });

  it('空事件流给出说明而不是空白', () => {
    render(<EventStream events={[]} />);
    expect(screen.getByText(/没有事件记录/)).toBeInTheDocument();
  });

  it('带 node_id 的事件显示定位按钮并回调', async () => {
    const onLocate = vi.fn();
    render(
      <EventStream events={[event(1, 'repair_failed', { node_id: 'node-xyz' })]} onLocateNode={onLocate} />,
    );
    await userEvent.click(screen.getByRole('button', { name: '定位' }));
    expect(onLocate).toHaveBeenCalledWith('node-xyz');
  });

  it('没有 node_id 的事件不显示定位按钮', () => {
    render(<EventStream events={[event(1, 'run_finished')]} onLocateNode={() => {}} />);
    expect(screen.queryByRole('button', { name: '定位' })).not.toBeInTheDocument();
  });

  it('1000 条事件只渲染视口内那一窗口（TODO §12.6）', () => {
    // 虚拟化之前这里会往 DOM 里塞 1000 行，滚动就开始掉帧。
    // jsdom 没有布局引擎（clientHeight 恒 0），组件拿兜底视口高度算窗口，
    // 所以这里断言的是"渲染行数与事件总数无关"这件事本身。
    const many = Array.from({ length: 1000 }, (_, index) =>
      event(index + 1, 'operator_selected'),
    );
    const { container } = render(<EventStream events={many} />);
    const rows = container.querySelectorAll('[data-event-row]');
    expect(rows.length).toBeLessThan(80);
    expect(rows.length).toBeGreaterThan(0);
  });

  it('虚拟化的滚动条仍按整份事件撑开，不是塌成视口高度', () => {
    const many = Array.from({ length: 1000 }, (_, index) =>
      event(index + 1, 'operator_selected'),
    );
    const { container } = render(<EventStream events={many} />);
    const spacer = container.querySelector<HTMLElement>(
      '[data-testid="event-stream-scroller"] > div',
    );
    // 1 个代标题 26px + 1000 行 × 22px。
    expect(spacer?.style.height).toBe(`${26 + 1000 * 22}px`);
  });

  it('折叠一代之后总高度按该代的事件数收缩', async () => {
    const many = Array.from({ length: 600 }, (_, index) =>
      event(index + 1, 'operator_selected'),
    );
    const { container } = render(<EventStream events={many} />);
    const before = container.querySelector<HTMLElement>(
      '[data-testid="event-stream-scroller"] > div',
    )?.style.height;
    await userEvent.click(screen.getByTestId('generation-0'));
    const after = container.querySelector<HTMLElement>(
      '[data-testid="event-stream-scroller"] > div',
    )?.style.height;
    expect(after).toBe('26px');
    expect(before).not.toBe(after);
  });
});

describe('分数时间轴', () => {
  function point(overrides: Partial<ScorePointResponse> = {}): ScorePointResponse {
    return { node_id: 'n1', score: 1, ...overrides };
  }

  it('无已评分节点时说明原因', () => {
    render(<ScoreTimeline points={[]} bestPath={[]} />);
    expect(screen.getByText(/没有已评分的节点/)).toBeInTheDocument();
  });

  it('全平分数不崩（除零）', () => {
    render(
      <ScoreTimeline
        points={[point({ node_id: 'a', score: 5 }), point({ node_id: 'b', score: 5 })]}
        bestPath={[]}
      />,
    );
    expect(screen.getByTestId('score-timeline')).toBeInTheDocument();
  });

  it('未评分的点被排除，不当作 0 画进曲线', () => {
    render(
      <ScoreTimeline
        points={[point({ node_id: 'a', score: 5 }), point({ node_id: 'b', score: null })]}
        bestPath={[]}
      />,
    );
    expect(screen.getByText(/1 个已评分节点/)).toBeInTheDocument();
  });

  it('噪声带未知时图例仍完整', () => {
    render(
      <ScoreTimeline
        points={[point({ node_id: 'a', score: 1, within_noise_band: null })]}
        bestPath={[]}
      />,
    );
    expect(screen.getByText('无法判断')).toBeInTheDocument();
  });
});

describe('排行榜（TODO 5.7）', () => {
  function entry(overrides: Partial<ScoreboardEntryResponse> = {}): ScoreboardEntryResponse {
    return { node_id: 'abcd1234efgh', rank: 1, ...overrides };
  }

  it('空榜给出说明', () => {
    render(<LeaderboardPanel entries={[]} />);
    expect(screen.getByText(/还没有可排名的节点/)).toBeInTheDocument();
  });

  it('未评分显示「未评分」而不是 0', () => {
    render(<LeaderboardPanel entries={[entry({ score: null })]} />);
    expect(screen.getByText('未评分')).toBeInTheDocument();
  });

  it('最优条目有标记', () => {
    render(<LeaderboardPanel entries={[entry({ is_best: true })]} />);
    expect(screen.getByText('★')).toBeInTheDocument();
  });

  it('点击条目回调定位', async () => {
    const onLocate = vi.fn();
    render(<LeaderboardPanel entries={[entry()]} onLocateNode={onLocate} />);
    await userEvent.click(screen.getByRole('button', { name: 'abcd1234' }));
    expect(onLocate).toHaveBeenCalledWith('abcd1234efgh');
  });
});

describe('预算面板（TODO 5.7）', () => {
  it('总 token 缺失时显示未记录', () => {
    render(<BudgetPanel budget={{}} />);
    // 空 budget 下每一行都是「未记录」—— 所以用 getAllByText 并断言数量，
    // 顺便钉住"没有任何一处显示 0"。
    expect(screen.getAllByText('未记录').length).toBeGreaterThan(1);
    expect(screen.queryByText('0')).not.toBeInTheDocument();
  });

  it('分项缺失不显示 0，也不进占比分母', () => {
    render(<BudgetPanel budget={{ total_tokens: 1000, generate_tokens: 400, reflect_tokens: 600 }} />);
    // 修复那一行是「未记录」，不是 0
    const rows = screen.getAllByText('未记录');
    expect(rows.length).toBeGreaterThan(0);
    // 已记录分项合计 = 总数，所以不显示差额提示
    expect(screen.queryByText(/未单独计量的部分/)).not.toBeInTheDocument();
  });

  it('分项之和不足总数时说明差额，而不是假装归一', () => {
    render(<BudgetPanel budget={{ total_tokens: 1000, generate_tokens: 300 }} />);
    expect(screen.getByText(/未单独计量的部分/)).toBeInTheDocument();
  });

  it('预算停止时显示停止原因', () => {
    render(<BudgetPanel budget={{ total_tokens: 100, budget_stop_reason: 'token 上限' }} />);
    expect(screen.getAllByText(/token 上限/).length).toBeGreaterThan(0);
  });

  it('总 token 为 0 时不除零', () => {
    render(<BudgetPanel budget={{ total_tokens: 0, generate_tokens: 0 }} />);
    expect(screen.getByTestId('budget-panel')).toBeInTheDocument();
  });
});

// 让 TS 知道这个文件里用到的边类型（避免 unused import 警告）。
export type { TreeEdgeKind };
