/**
 * 三岛组件的行为测试（TODO D6.4 的组件半边）。
 *
 * 判定逻辑已在 `island-view.test.ts` 里逐条验过，这里只验**渲染出来的话**：
 * 岛的数据是不是从 props/接口来的、缺失有没有说「未记录」、
 * 四个交换计数有没有被并成一个、未评估的候选有没有被写成 0 分。
 *
 * `useRunSummaries` 被 mock 掉：这个测试要控制的是接口返回的三种形态
 * （available / missing / 请求失败），而不是让测试去起一个后端。
 */
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type {
  ExchangeSummaryResponse,
  RunIslandsResponse,
  RunSummariesResponse,
  TreeNodeDto,
} from '@/generated/api';
import { ExchangePanel } from '@/features/islands/ExchangePanel';
import { IslandOverview } from '@/features/islands/IslandOverview';
import { SummaryDigest } from '@/features/islands/SummaryDigest';
import { IslandBestsSection } from '@/features/results/IslandBestsSection';

const summariesQuery = vi.hoisted(() => vi.fn());
vi.mock('@/features/islands/use-islands', () => ({
  useRunSummaries: summariesQuery,
  SUMMARIES_POLL_MS: 3_000,
}));

function node(overrides: Partial<TreeNodeDto> = {}): TreeNodeDto {
  return {
    id: 'n-a-0001',
    branch_id: 'main',
    depth: 1,
    operator: 'refine',
    hypothesis_status: 'open',
    status: 'done',
    island_id: 'a',
    score: 22.8074,
    delta_score: 0.4,
    within_noise_band: false,
    ...overrides,
  };
}

const NODES: TreeNodeDto[] = [
  node({ id: 'n-a-best', island_id: 'a', score: 22.8074 }),
  node({ id: 'n-b-mid', island_id: 'b', score: 18 }),
  node({ id: 'n-c-graft', island_id: 'c', score: 12, operator: 'summary_cross' }),
];

const EDGES = [
  { source: 'n-a-best', target: 'n-b-mid', kind: 'parent' as const },
  { source: 'n-a-best', target: 'n-c-graft', kind: 'summary_cross' as const },
];

function islandsBody(overrides: Partial<RunIslandsResponse> = {}): RunIslandsResponse {
  return {
    state: 'available',
    source: 'run_summary.json',
    detail: '',
    islands: {
      a: {
        island_id: 'a',
        status: 'running',
        profile: 'performance',
        attempts: 6,
        valid_evaluations: 7,
        invalid_evaluations: 0,
        best_score: 22.8074,
        stop_reason: '',
      },
      b: {
        island_id: 'b',
        status: 'finished',
        profile: 'miss_alert',
        attempts: 6,
        valid_evaluations: 7,
        invalid_evaluations: 0,
        best_score: 18,
        stop_reason: 'max_attempts',
      },
    },
    exchange: {
      summaries: 1,
      by_kind: { best: 1 },
      deliveries: 2,
      accepted: 2,
      rejected: 0,
      applications: 12,
      evaluated_applications: 12,
    },
    cost: {
      total_tokens: 10200,
      by_island: {
        a: { tokens: 3300, calls: 11, by_stage: { generate: 2200 } },
        b: { tokens: 3300, calls: 11 },
        c: { tokens: 3600, calls: 12 },
      },
      shared_tokens: 0,
      cost_usd: null,
      cost_basis: 'unknown',
    },
    attempt_total: 12,
    ...overrides,
  };
}

function summaryBody(overrides: Partial<RunSummariesResponse> = {}): RunSummariesResponse {
  return {
    contract_version: '1.14.0',
    run_id: 'run-1',
    state: 'available',
    detail: '',
    summaries: [summary()],
    summary_count: 1,
    delivery_count: 2,
    application_count: 12,
    evaluated_application_count: 11,
    ...overrides,
  };
}

function summary(overrides: Partial<ExchangeSummaryResponse> = {}): ExchangeSummaryResponse {
  return {
    summary_id: 'sum-89d09670abcd',
    kind: 'best',
    source_island_id: 'a',
    source_node_id: 'n-a-best',
    summary_text: '岛 a 的最优程序在阈值 0.42 处召回最高；同指纹下未见更优。',
    conditions: '同一评估器指纹、同一任务指纹',
    evidence: ['node:n-a-best', 'artifact:hash-only'],
    metrics: { combined_score: 22.8074, rounds: 18 },
    confidence_status: 'single_observation',
    created_at: '2026-10-08T02:11:00+00:00',
    deliveries: [
      {
        delivery_id: 'del-0001',
        summary_id: 'sum-89d09670abcd',
        source_island_id: 'a',
        target_island_id: 'b',
        status: 'accepted',
        reason: '',
      },
      {
        delivery_id: 'del-0002',
        summary_id: 'sum-89d09670abcd',
        source_island_id: 'a',
        target_island_id: 'c',
        status: 'rejected',
        reason: 'superseded_by_newer_best',
      },
    ],
    applications: [
      {
        application_id: 'app-0001',
        delivery_id: 'del-0001',
        candidate_node_id: 'n-c-graft',
        target_island_id: 'c',
        score: 12,
        evaluated: true,
      },
      {
        application_id: 'app-0002',
        delivery_id: 'del-0001',
        candidate_node_id: 'n-b-unrated',
        target_island_id: 'b',
        score: null,
        evaluated: false,
      },
    ],
    ...overrides,
  };
}

function mockQuery(result: Record<string, unknown>) {
  summariesQuery.mockReturnValue({
    isPending: false,
    isError: false,
    error: null,
    data: undefined,
    refetch: vi.fn(),
    ...result,
  });
}

beforeEach(() => {
  summariesQuery.mockReset();
});

describe('三岛概览', () => {
  it('每个岛一张卡，策略说明用中文写出来', () => {
    render(
      <IslandOverview islands={islandsBody()} nodes={NODES} edges={EDGES} runStatus="running" />,
    );
    expect(screen.getByText('岛 a')).toBeInTheDocument();
    expect(screen.getByText('岛 b')).toBeInTheDocument();
    // 策略文本取自 profile，不是运行里编出来的。
    expect(screen.getByText('优先降低漏报与误报：关注假阴性分组与召回-精确率折中。')).toBeInTheDocument();
  });

  it('树里存在但没记账的岛也出现在列表里，缺的字段显示「未记录」', () => {
    render(
      <IslandOverview islands={islandsBody()} nodes={NODES} edges={EDGES} runStatus="running" />,
    );
    const card = screen.getByTestId('island-overview').querySelector('[data-island-card="c"]');
    expect(card).not.toBeNull();
    // 「未记录」出现多次（尝试/有效/非法），所以按这一张卡的范围查。
    expect(card?.textContent).toContain('未记录');
    expect(card?.textContent).not.toContain('岛 c 0');
    // 树里实测的节点数不受记账缺失影响。
    expect(card?.textContent).toContain('树内节点');
  });

  it('本岛最优取本岛树里实测的分数，可点击定位节点', async () => {
    const onSelectNode = vi.fn();
    render(
      <IslandOverview
        islands={islandsBody()}
        nodes={NODES}
        edges={EDGES}
        runStatus="running"
        onSelectNode={onSelectNode}
      />,
    );
    const best = screen.getByTestId('island-overview').querySelector('[data-island-best="b"]');
    expect(best?.textContent).toBe('18.00');
    await userEvent.click(screen.getByTitle('完整 ID：n-b-mid'));
    expect(onSelectNode).toHaveBeenCalledWith('n-b-mid');
  });

  it('全局最优与岛最优同时显示且各自标明含义', () => {
    render(
      <IslandOverview
        islands={islandsBody()}
        nodes={NODES}
        edges={EDGES}
        runStatus="running"
        globalBest={{ nodeId: 'n-a-best', score: 22.8074 }}
      />,
    );
    const panel = screen.getByTestId('island-overview');
    // 岛 a 的本岛最优也是 22.81，所以两处都要能各自定位到 —— 这正是
    // 用户最容易搞混的地方，标签文字必须把它们分开。
    expect(panel.querySelector('[data-global-best]')?.textContent).toBe('22.81');
    expect(panel.querySelector('[data-island-best="a"]')?.textContent).toBe('22.81');
    // 「落在哪个岛」是从树里读出来的（各岛节点集合不相交），不是按顺序猜的。
    expect(panel.textContent).toContain('（落在岛 a）');
  });

  it.each([
    ['节点不在树里时只说它不在树里', 'n-not-in-tree', '（该节点不在树里，只有 run_summary.json 记了它）'],
    ['节点没有岛标记时不编一个岛名', 'n-legacy', '（该节点没有岛标记）'],
  ])('%s', (_name, nodeId, expected) => {
    render(
      <IslandOverview
        islands={islandsBody()}
        nodes={[...NODES, node({ id: 'n-legacy', island_id: '' })]}
        edges={EDGES}
        runStatus="running"
        globalBest={{ nodeId, score: 21 }}
      />,
    );
    expect(screen.getByTestId('island-overview').textContent).toContain(expected);
  });

  it('运行已结束而岛还写着 running 时，卡片上明说', () => {
    render(
      <IslandOverview islands={islandsBody()} nodes={NODES} edges={EDGES} runStatus="completed" />,
    );
    const stale = screen.getByTestId('island-overview').querySelector('[data-island-stale="a"]');
    expect(stale?.textContent).toContain('仍记录为 running');
  });

  it('成本对账不自洽时把差额显示出来，不抹平', () => {
    const drifted = {
      ...islandsBody(),
      cost: { ...islandsBody().cost, total_tokens: 10201 },
    };
    render(<IslandOverview islands={drifted} nodes={NODES} edges={EDGES} runStatus="running" />);
    const line = screen.getByTestId('island-overview').querySelector('[data-cost-reconciliation]');
    expect(line?.getAttribute('data-cost-reconciliation')).toBe('unbalanced');
    expect(line?.textContent).toContain('相差 1');
  });

  it('尝试数与全局评估数不等时报 mismatch，并把三个数都写出来', () => {
    render(
      <IslandOverview
        islands={islandsBody({ attempt_total: 9 })}
        nodes={NODES}
        edges={EDGES}
        runStatus="running"
        iterationsDone={7}
      />,
    );
    const line = screen
      .getByTestId('island-overview')
      .querySelector('[data-attempt-reconciliation]');
    expect(line?.getAttribute('data-attempt-reconciliation')).toBe('mismatch');
    expect(line?.textContent).toContain('12');
    expect(line?.textContent).toContain('7');
  });

  it('历史单树运行不画岛卡，改成一条「没有产出岛记账」的说明', () => {
    // 契约要求 state=missing 时界面"显示一棵树而不是编三个岛"。
    render(
      <IslandOverview
        islands={{
          state: 'missing',
          detail: '该运行没有摘要交换层：单树运行早于多岛引擎，界面不必展示交换视图',
        }}
        nodes={[node({ id: 'old', island_id: '' })]}
        edges={[]}
        runStatus="completed"
      />,
    );
    expect(screen.queryByTestId('island-overview')).toBeNull();
    expect(screen.getByRole('status')).toHaveTextContent('单树运行早于多岛引擎');
  });

  it('岛记账读不出来（invalid）时说"读不出来"，不画空卡', () => {
    render(
      <IslandOverview
        islands={{ state: 'invalid', detail: 'islands 块不是合法对象' }}
        nodes={NODES}
        edges={EDGES}
        runStatus="failed"
      />,
    );
    expect(screen.getByText('岛记账读不出来')).toBeInTheDocument();
    expect(screen.getByText('islands 块不是合法对象')).toBeInTheDocument();
  });

  it('交换四件事按六个独立计数显示，谁也不并进谁', () => {
    render(
      <IslandOverview islands={islandsBody()} nodes={NODES} edges={EDGES} runStatus="running" />,
    );
    const read = (key: string) =>
      screen.getByTestId('island-overview').querySelector(`[data-exchange-fact="${key}"]`)
        ?.textContent;
    expect(read('summaries')).toBe('1');
    expect(read('deliveries')).toBe('2');
    expect(read('accepted')).toBe('2');
    expect(read('applications')).toBe('12');
    expect(read('evaluated_applications')).toBe('12');
    expect(read('rejected')).toBe('0');
  });
});

describe('知识页：岛间摘要与知识卡分开', () => {
  it('摘要不是知识卡：标题旁明说它不会登记成知识卡', () => {
    mockQuery({ data: summaryBody() });
    render(<SummaryDigest runId="run-1" />);
    const section = document.querySelector('[data-summary-digest]');
    expect(section?.textContent).toContain('岛间摘要');
    expect(section?.textContent).toContain('不是任务知识库里的知识卡');
    expect(section?.textContent).toContain('也不会自动登记成知识卡');
  });

  it('单次观察带「未复现」，不出现「已确认」', () => {
    mockQuery({ data: summaryBody({ summaries: [summary({ confidence_status: 'single_observation' })] }) });
    render(<SummaryDigest runId="run-1" />);
    const section = document.querySelector('[data-summary-digest]');
    expect(section?.textContent).toContain('单次观察（未复现）');
    expect(section?.textContent).not.toContain('已确认');
  });

  it('读不到摘要时说"这一节读不到"，不说成"没有摘要"', () => {
    mockQuery({ isError: true, error: { error_code: 'run.unreadable', message: '没有可读制品' } });
    render(<SummaryDigest runId="run-1" />);
    const section = document.querySelector('[data-summary-digest]');
    expect(section?.textContent).toContain('岛间摘要读不出来');
    expect(section?.textContent).toContain('这不表示这次运行没有摘要');
  });

  it('单树运行没有交换层：照实说，不画空列表', () => {
    mockQuery({ data: summaryBody({ state: 'missing', detail: '单树运行早于多岛引擎' }) });
    render(<SummaryDigest runId="run-1" />);
    expect(document.querySelector('[data-summary-digest]')?.textContent).toContain(
      '单树运行早于多岛引擎',
    );
  });

  it('投递与采用分开显示，各自算各自的', () => {
    mockQuery({ data: summaryBody() });
    render(<SummaryDigest runId="run-1" />);
    const item = document.querySelector('[data-digest-summary="sum-89d09670abcd"]');
    expect(item?.textContent).toContain('投递 2 · 采用 2');
    expect(item?.textContent).toContain('岛 a → 岛 b');
    expect(item?.textContent).toContain('岛 a → 岛 c');
  });
});

describe('结果页：全局最优与各岛最优', () => {
  const renderSection = (overrides: Partial<Parameters<typeof IslandBestsSection>[0]> = {}) =>
    render(
      <IslandBestsSection
        islands={islandsBody()}
        nodes={NODES}
        edges={EDGES}
        treeState="ready"
        runStatus="running"
        globalBest={{ nodeId: 'n-a-best', score: 22.8074 }}
        onOpenNode={() => {}}
        {...overrides}
      />,
    );

  it('全局最优标在它所属的那一行，别的行是 —', () => {
    renderSection();
    const section = document.querySelector('[data-island-bests="islands"]');
    const held = section?.querySelector('[data-holds-global-best="true"]');
    expect(held?.getAttribute('data-island-best-row')).toBe('a');
    expect(held?.textContent).toContain('在本岛');
    expect(section?.querySelector('[data-holds-global-best="false"]')?.textContent).toContain('—');
  });

  it('本岛最优同时给出树内实测与 run_summary 记的数', () => {
    renderSection();
    const row = document.querySelector('[data-island-best-row="b"]');
    expect(row?.querySelector('[data-island-best="b"]')?.textContent).toBe('18.00');
    expect(row?.textContent).toContain('run_summary 记 18.00');
  });

  it('两个数不一致时明说，不挑一个显示', () => {
    renderSection({
      islands: islandsBody({
        islands: { b: { island_id: 'b', status: 'finished', best_score: 19 } },
      }),
    });
    expect(document.querySelector('[data-island-best-row="b"]')?.textContent).toContain(
      '（与实测不一致）',
    );
  });

  it('树没读到就说算不了，不把「没读到」画成 0 个节点', () => {
    renderSection({ treeState: 'error' });
    const section = document.querySelector('[data-island-bests="error"]');
    expect(section?.textContent).toContain('进化树读取失败');
    expect(section?.textContent).toContain('这不表示各岛的分数是 0');
    expect(document.querySelector('[data-island-bests="islands"]')).toBeNull();
  });

  it('历史单树没有岛级记账：说清楚，不画空表', () => {
    renderSection({
      islands: { state: 'missing', detail: '单树运行早于多岛引擎' },
      nodes: [node({ id: 'old', island_id: '' })],
    });
    const section = document.querySelector('[data-island-bests="legacy-single"]');
    expect(section?.textContent).toContain('没有岛级记账');
    expect(section?.textContent).toContain('不表示各岛都是 0 分');
    expect(section?.textContent).toContain('22.81');
  });
});

describe('采用详情', () => {
  it('四个交换计数并排显示，且各自独立', () => {
    mockQuery({ data: summaryBody() });
    render(<ExchangePanel runId="run-1" />);
    expect(screen.getByText('发布 1')).toBeInTheDocument();
    expect(screen.getByText('投递 2')).toBeInTheDocument();
    expect(screen.getByText('采用 12')).toBeInTheDocument();
    expect(screen.getByText('已评估 11')).toBeInTheDocument();
  });

  it('未评估的候选写「未评估」，不显示 0 分', () => {
    mockQuery({ data: summaryBody() });
    render(<ExchangePanel runId="run-1" />);
    const row = document.querySelector('[data-application-score="app-0002"]');
    expect(row?.textContent).toBe('未评估');
    // 已评估的那一行才显示自己的分数。
    expect(document.querySelector('[data-application-score="app-0001"]')?.textContent).toBe('12.00');
  });

  it('候选分数旁明说它不是摘要带来的收益', () => {
    mockQuery({ data: summaryBody() });
    render(<ExchangePanel runId="run-1" />);
    expect(screen.getByText(/该候选自己/)).toBeInTheDocument();
  });

  it('单次观察不渲染成已确认的规律', () => {
    mockQuery({ data: summaryBody() });
    render(<ExchangePanel runId="run-1" />);
    expect(screen.getByText('单次观察（未复现）')).toBeInTheDocument();
    expect(screen.queryByText(/已确认/)).not.toBeInTheDocument();
  });

  it('投递的采纳与拒绝分开显示，拒绝带原因', () => {
    mockQuery({ data: summaryBody() });
    render(<ExchangePanel runId="run-1" />);
    const row = (id: string) => document.querySelector(`[data-delivery="${id}"]`);
    expect(row('del-0001')?.textContent).toContain('岛 a → 岛 b');
    expect(row('del-0001')?.textContent).toContain('已采纳');
    expect(row('del-0002')?.textContent).toContain('岛 a → 岛 c');
    expect(row('del-0002')?.textContent).toContain('已拒绝');
    // 机器码翻译成人话，同时 title 保留原值可查。
    expect(row('del-0002')?.textContent).toContain('已被该源岛更新的摘要取代');
    expect(row('del-0002')?.querySelector('[title="原因原值：superseded_by_newer_best"]')).not.toBeNull();
  });

  it('node: 证据可跳转，其他形态的证据原样显示且不伪装成文件链接', async () => {
    mockQuery({ data: summaryBody() });
    const onSelectNode = vi.fn();
    render(<ExchangePanel runId="run-1" onSelectNode={onSelectNode} />);
    const link = screen.getByRole('button', { name: 'n-a-best' });
    const other = screen.getByText('artifact:hash-only');
    expect(other.tagName).toBe('SPAN');
    await userEvent.click(link);
    expect(onSelectNode).toHaveBeenCalledWith('n-a-best');
  });

  it('候选节点可点击定位', async () => {
    mockQuery({ data: summaryBody() });
    const onSelectNode = vi.fn();
    render(<ExchangePanel runId="run-1" onSelectNode={onSelectNode} />);
    await userEvent.click(screen.getByRole('button', { name: 'n-c-graf' }));
    expect(onSelectNode).toHaveBeenCalledWith('n-c-graft');
  });

  it('available 但一条摘要都没有时说明"还没发布"，不是错误也不是空表', () => {
    mockQuery({ data: summaryBody({ summaries: [], summary_count: 0, delivery_count: 0, application_count: 0, evaluated_application_count: 0 }) });
    render(<ExchangePanel runId="run-1" />);
    expect(screen.getByText('这次运行还没有发布摘要')).toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent('exchange_interval');
  });

  it('missing（历史单树）说明该运行没有交换层', () => {
    mockQuery({
      data: {
        ...summaryBody(),
        state: 'missing',
        detail: '该运行没有摘要交换层：单树运行早于多岛引擎',
        summaries: [],
      },
    });
    render(<ExchangePanel runId="run-1" />);
    expect(screen.getByRole('status')).toHaveTextContent('单树运行早于多岛引擎');
    expect(screen.queryByTestId('exchange-panel')).toBeNull();
  });

  it('请求失败时给错误面板而不是空白', () => {
    mockQuery({
      isError: true,
      error: { error_code: 'run.unreadable', message: '读不出来' },
    });
    render(<ExchangePanel runId="run-1" />);
    // 面板标题被本面板改写成「摘要交换层读不出来」，所以断言稳定错误码与建议，
    // 而不是那句会被改写的话术。
    const alert = screen.getByRole('alert');
    expect(alert).toHaveTextContent('摘要交换层读不出来');
    expect(alert).toHaveTextContent('run.unreadable');
    expect(alert).toHaveTextContent('请检查制品目录');
  });
});
