/**
 * 知识发现页的路由级集成测试（PRD 12.1–12.5 / TODO 6.1–6.3）。
 *
 * 走真实路由树 + 真实 QueryClient，只 mock 生成的 SDK。验的是整条链路：
 * 深链接 → RunLayout 的运行详情 → 卡片清单 / 发现制品 / 事件流 → 四节渲染。
 *
 * 本页最容易被做错的几件事，各自都有专门的用例盯着：
 *  - `adopted_count = null` 在 fe.db 可读与不可读时含义相反；
 *  - 卡片正文按知识库对照；对不上时显示未记录，不把非 http 字符串画成链接，
 *    绝不能填空字符串或编造文本冒充；
 *  - 「未定」不是「否证」，沙箱失败不是判级；
 *  - `decisive_matches` 是数量，不得被读成胜者；
 *  - 三个请求互相独立，一个挂了不得连带抹掉另外两个已经拿到的事实。
 */
import { createMemoryHistory } from '@tanstack/react-router';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { AppProviders } from '@/app/providers';
import { createAppRouter } from '@/app/router';
import type {
  DiscoveryResponse,
  EventResponse,
  KnowledgeCardResponse,
  MetaResponse,
  RunDetailResponse,
  RunDiscoveryResponse,
} from '@/generated/api';
import { createQueryClient } from '@/lib/query-client';
import { useUiStore } from '@/stores/ui-store';

const RUN_ID = 'hdd_mvp_demo_7510f100';

const META: MetaResponse = {
  auth_required: false,
  contract_version: '1.3.0',
  default_deployment_mode: 'local_cloud',
  deployment_modes: [
    {
      available: false,
      mode: 'local_cloud',
      supported_transports: ['local_cloud', 'ssh_cloud'],
      detail: '纯云端执行后端尚未配置',
    },
  ],
  demo_run_ids: [RUN_ID],
  engine_version: '0.0.0',
  nav_modules: ['overview', 'workbench', 'knowledge', 'results'],
  process_control_enabled: false,
  stream_transport: 'sse',
};

/** 每个 it 可覆盖，制造不同的制品状态与响应。 */
const state: {
  database: 'available' | 'missing' | 'invalid';
  cards: KnowledgeCardResponse[];
  cardsFail: boolean;
  knowledge: RunDetailResponse['knowledge'];
  runDiscovery: RunDiscoveryResponse | null;
  discovery: DiscoveryResponse;
  discoveryFail: boolean;
  events: EventResponse[];
  eventsFail: boolean;
} = {
  database: 'available',
  cards: [],
  cardsFail: false,
  knowledge: null,
  runDiscovery: null,
  discovery: emptyDiscovery(),
  discoveryFail: false,
  events: [],
  eventsFail: false,
};

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

function emptyDiscovery(overrides: Partial<DiscoveryResponse> = {}): DiscoveryResponse {
  return {
    run_id: RUN_ID,
    contract_version: '1.3.0',
    enabled: true,
    phenomena_state: 'available',
    preregistration_state: 'available',
    controls_state: 'available',
    discovered_cards_state: 'available',
    phenomena: [],
    preregistration: [],
    controls: [],
    certificates: [],
    // 这两个恒为空是后端的事实，不是省略：theories.json 被硬编码成 []，
    // matches= 从不传（discovery-logic.ts 的头注释有出处）。
    theories: [],
    matches: [],
    warnings: [],
    discovered_card_ids: [],
    ...overrides,
  };
}

/**
 * `ClaimTestResult.model_dump()` 的 15 个键（discovery/schemas.py:43-58）。
 * 这里给全，因为现象卡的可信度就在于「每个键都有对应位置」。
 */
function payload(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    split: 'val',
    n: 4200,
    n_pos: 31,
    n_neg: 4169,
    effect: 0.1834,
    ci_low: 0.0912,
    ci_high: 0.2756,
    p: 0.00042,
    e: 12.7,
    direction_ok: true,
    temporal_ok: true,
    rho_max_abs: 0.11,
    incr_gain: 0.0231,
    incr_ci_low: 0.004,
    incr_ci_high: 0.0422,
    ...overrides,
  };
}

function phenomenon(
  claimId: string,
  grade: string,
  payloadOverrides: Record<string, unknown> = {},
): Record<string, unknown> {
  return { claim_id: claimId, grade, payload: payload(payloadOverrides) };
}

function sandboxFailedEvent(
  claimId: string,
  overrides: Record<string, unknown> = {},
): EventResponse {
  return {
    run_id: RUN_ID,
    id: 1,
    type: 'claim_sandbox_failed',
    is_known_type: false,
    ts: '2026-10-01T08:00:00+00:00',
    payload: {
      claim_id: claimId,
      error_type: 'RuntimeError',
      error: 'sandbox timeout after 30s',
      stage: 'execute',
      ...overrides,
    },
  };
}

vi.mock('@/generated/api', () => ({
  metaApiMetaGet: vi.fn(async () => ({ data: META, response: { status: 200 } })),
  getRunApiRunsRunIdGet: vi.fn(async () => ({
    data: {
      run_id: RUN_ID,
      contract_version: '1.3.0',
      data_state: 'complete',
      artifact_states: {
        run_summary: 'available',
        tree: 'available',
        events: 'available',
        database: state.database,
        programs: 'available',
        logs: 'available',
        discovery: 'missing',
      },
      knowledge: state.knowledge,
      discovery: state.runDiscovery,
      outcome: { status: 'completed', best_score: 25.4, improvement: 2.59 },
    },
    response: { status: 200 },
  })),
  getKnowledgeCardsApiRunsRunIdKnowledgeCardsGet: vi.fn(async () =>
    state.cardsFail
      ? { error: { error_code: 'artifact.unreadable', message: 'boom' }, response: { status: 500 } }
      : { data: state.cards, response: { status: 200 } },
  ),
  getDiscoveryApiRunsRunIdDiscoveryGet: vi.fn(async () =>
    state.discoveryFail
      ? { error: { error_code: 'artifact.unreadable', message: 'boom' }, response: { status: 500 } }
      : { data: state.discovery, response: { status: 200 } },
  ),
  // 点采纳节点会跳进化树，这里让树页拿到一个空树而不是抛未 mock 的错。
  getTreeApiRunsRunIdTreeGet: vi.fn(async () => ({
    data: { run_id: RUN_ID, contract_version: '1.3.0', data_state: 'complete', nodes: [], edges: [] },
    response: { status: 200 },
  })),
  getEventsApiRunsRunIdEventsGet: vi.fn(async () =>
    state.eventsFail
      ? { error: { error_code: 'events.unavailable', message: 'boom' }, response: { status: 500 } }
      : {
          data: {
            run_id: RUN_ID,
            contract_version: '1.3.0',
            data_state: 'complete',
            events: state.events,
          },
          response: { status: 200 },
        },
  ),
  // 跳转前已经把节点写进 store，树页会立刻去取它的详情。
  getNodeApiRunsRunIdNodesNodeIdGet: vi.fn(async () => ({
    data: { run_id: RUN_ID, node_id: 'n2a', contract_version: '1.3.0' },
    response: { status: 200 },
  })),
}));

function renderKnowledgePage(runId = RUN_ID) {
  const router = createAppRouter({
    history: createMemoryHistory({ initialEntries: [`/runs/${runId}/knowledge`] }),
  });
  const view = render(<AppProviders router={router} queryClient={createQueryClient()} />);
  return { ...view, router };
}

/**
 * 等到某一节落定：钩子元素存在（路由是懒加载的，首帧整页都还没挂上），
 * 且状态不再是 pending。返回落定后的状态，失败路径的用例可以直接断言 'error'。
 *
 * 不能用 `[data-card-summary]` 这类三态都渲染的元素当信号：那会在 pending
 * 阶段就返回，读到占位值——本页最初 31 个红的成因正是这个。
 */
async function waitSettled(container: HTMLElement, hook: string): Promise<string | null> {
  await waitFor(
    () => {
      const node = container.querySelector(`[${hook}]`);
      expect(node).not.toBeNull();
      expect(node?.getAttribute(hook)).not.toBe('pending');
    },
    { timeout: 5000 },
  );
  return container.querySelector(`[${hook}]`)?.getAttribute(hook) ?? null;
}

/** 等到卡片清单落地。 */
async function waitLoaded(container: HTMLElement) {
  await waitSettled(container, 'data-cards-state');
}

/** 等到发现制品落地。 */
async function waitPhenomena(container: HTMLElement) {
  return waitSettled(container, 'data-phenomena-state');
}

function adoptedCell(container: HTMLElement, cardId: string) {
  const cell = container.querySelector(`[data-card-row="${cardId}"] [data-card-cell="adopted"]`);
  return {
    text: cell?.textContent ?? null,
    recorded: cell?.getAttribute('data-recorded') ?? null,
  };
}

beforeEach(() => {
  localStorage.clear();
  state.database = 'available';
  state.cards = [];
  state.cardsFail = false;
  state.knowledge = null;
  state.runDiscovery = null;
  state.discovery = emptyDiscovery();
  state.discoveryFail = false;
  state.events = [];
  state.eventsFail = false;
  useUiStore.setState({
    currentRunId: null,
    selectedNodeId: null,
    expandedPanels: [],
    theme: 'light',
    workbenchTab: 'tree',
  });
});

describe('知识发现页结构（PRD 12.1–12.5）', () => {
  it('深链接渲染出四节，侧栏仍然只有四个模块', async () => {
    const { container } = renderKnowledgePage();
    await waitLoaded(container);
    await waitPhenomena(container);

    for (const name of ['知识卡', '现象层', '机制层与辩论赛']) {
      expect(screen.getByRole('heading', { name })).toBeInTheDocument();
    }
    expect(screen.queryByRole('heading', { name: '理论与跨数据集迁移' })).not.toBeInTheDocument();
    expect(container.querySelectorAll('[data-nav-item]')).toHaveLength(4);
  });

  it('没有对上知识库时正文显示未记录，并且不出现外链', async () => {
    const { container } = renderKnowledgePage();
    await waitLoaded(container);

    const section = container.querySelector('[data-card-prose]') as HTMLElement;
    expect(section.querySelector('[data-prose-unmatched]')).not.toBeNull();
    expect(section.textContent).toContain('未记录');
    expect(container.querySelectorAll('a[href^="http"], a[href^="blob:"]')).toHaveLength(0);
    expect(container.querySelectorAll('[download]')).toHaveLength(0);
  });

  it('http 来源渲染成链接，非 http 字符串只显示文字', async () => {
    state.cards = [
      card({
        card_id: 'FE01',
        title: '窗口差分',
        category: 'feature_engineering',
        claim: '差分能提高排序',
        source_kind: 'paper',
        conditions: '全厂商',
        priority: 1,
        sources: [
          {
            source_id: 'paper_a',
            title: '一篇论文',
            url: 'https://example.com/paper',
            takeaway: '累计计数的跳变比绝对值更有信息。',
          },
          { source_id: 'note_b', title: '不能点', url: 'javascript:alert(1)', takeaway: null },
        ],
      }),
    ];
    const { container } = renderKnowledgePage();
    await waitLoaded(container);

    const section = container.querySelector('[data-card-prose]') as HTMLElement;
    expect(section.querySelector('[data-card-prose-row="FE01"]')?.textContent).toContain('窗口差分');
    expect(section.querySelector('[data-card-prose-row="FE01"]')?.textContent).toContain('特征工程');
    expect(section.querySelector('[data-card-prose-row="FE01"]')?.textContent).toContain('差分能提高排序');
    expect(section.querySelector('[data-card-prose-row="FE01"]')?.textContent).toContain('全厂商');
    expect(section.querySelector('[data-source-takeaway="paper_a"]')?.textContent).toContain(
      '累计计数的跳变比绝对值更有信息。',
    );
    expect(section.querySelector('[data-source-takeaway="note_b"]')?.textContent).toBe('未记录');
    expect(container.querySelector('[data-card-title="FE01"]')?.textContent).toBe('窗口差分');
    const link = section.querySelector('a[data-source-link="paper_a"]');
    expect(link?.getAttribute('href')).toBe('https://example.com/paper');
    expect(section.querySelector('[data-source-text="note_b"]')?.textContent).toBe('不能点');
    expect(section.querySelectorAll('a[href^="javascript:"]')).toHaveLength(0);
  });

  it('采用汇总四格在 knowledge 为 null 时全部未记录，不显示 0', async () => {
    const { container } = renderKnowledgePage();
    await waitLoaded(container);

    for (const label of ['提供过的卡片数', '被采纳的卡片数', '采纳后有效的卡片数', '卡片采纳率']) {
      const cell = container.querySelector(`[data-summary-cell="${label}"]`);
      expect(cell?.textContent).toBe('未记录');
      expect(cell?.getAttribute('data-recorded')).toBe('false');
    }
  });

  it('采用汇总有值时照实换算，0 采纳率显示 0.0% 而不是未记录', async () => {
    state.knowledge = {
      cards_offered: 18,
      cards_adopted: 5,
      cards_adopted_valid: 3,
      card_adoption_rate: 0.2778,
      card_stats: [{ card_id: 'card_a', n: 6, sum_delta: 1.5, mean_delta: 0.25 }],
    };
    const { container } = renderKnowledgePage();
    await waitLoaded(container);

    expect(container.querySelector('[data-summary-cell="提供过的卡片数"]')?.textContent).toBe('18');
    expect(container.querySelector('[data-summary-cell="卡片采纳率"]')?.textContent).toBe('27.8%');
    expect(
      container.querySelector('[data-summary-cell="卡片采纳率"]')?.getAttribute('data-recorded'),
    ).toBe('true');
  });
});

describe('卡片表格的计数语义', () => {
  it('后端给的 0 照实显示为 0，null 显示未记录', async () => {
    state.cards = [
      card({
        card_id: 'c_zero',
        offered_count: 0,
        adopted_count: 0,
        refuted_count: null,
        mean_delta: null,
      }),
    ];
    const { container } = renderKnowledgePage();
    await waitLoaded(container);

    const rowNode = container.querySelector('[data-card-row="c_zero"]');
    expect(rowNode?.querySelector('[data-card-cell="offered"]')?.textContent).toBe('0');
    expect(adoptedCell(container, 'c_zero')).toEqual({ text: '0', recorded: 'true' });
    expect(rowNode?.querySelector('[data-card-cell="refuted"]')?.textContent).toBe('未记录');
    // 均值为 null 时不得显示 0.000：n == 0 表示均值未知（replay_service.py:1292）。
    expect(rowNode?.querySelector('[data-card-cell="mean_delta"]')?.textContent).toBe('未记录');
  });

  it('fe.db 可读且 adopted_count = null：显示 0，因为那正是后端的写法', async () => {
    state.database = 'available';
    state.cards = [card({ card_id: 'c1', adopted_count: null, adopted_node_ids: [] })];
    const { container } = renderKnowledgePage();
    await waitLoaded(container);

    expect(adoptedCell(container, 'c1')).toEqual({ text: '0', recorded: 'true' });
    expect(container.querySelector('[data-database-unavailable]')).toBeNull();
  });

  it('fe.db 缺失且 adopted_count = null：显示未记录，并给出警告条', async () => {
    state.database = 'missing';
    state.cards = [card({ card_id: 'c1', adopted_count: null })];
    const { container } = renderKnowledgePage();
    await waitLoaded(container);

    expect(adoptedCell(container, 'c1')).toEqual({ text: '未记录', recorded: 'false' });
    const warning = container.querySelector('[data-database-unavailable]');
    expect(warning).not.toBeNull();
    expect(warning?.getAttribute('data-database-state')).toBe('missing');
    expect(warning?.textContent).toContain('不表示没有采纳过');
  });

  it('fe.db 不可解析时警告条说「不可解析」而不是「缺失」', async () => {
    state.database = 'invalid';
    state.cards = [card({ card_id: 'c1' })];
    const { container } = renderKnowledgePage();
    await waitLoaded(container);

    const warning = container.querySelector('[data-database-unavailable]');
    expect(warning?.getAttribute('data-database-state')).toBe('invalid');
    expect(warning?.textContent).toContain('不可解析');
  });

  it('采用代与采纳节点照实渲染，节点是可点按钮', async () => {
    state.cards = [
      card({ card_id: 'c1', adopted_iterations: [2, 5], adopted_node_ids: ['n2a', 'n5b'] }),
    ];
    const { container } = renderKnowledgePage();
    await waitLoaded(container);

    const rowNode = container.querySelector('[data-card-row="c1"]');
    expect(rowNode?.textContent).toContain('2、5');
    expect(container.querySelector('[data-node-link="n2a"]')).not.toBeNull();
    expect(container.querySelector('[data-node-link="n5b"]')).not.toBeNull();
  });

  it('点采纳节点：写入选中节点并跳到进化树', async () => {
    state.cards = [card({ card_id: 'c1', adopted_node_ids: ['n2a'] })];
    const { container, router } = renderKnowledgePage();
    await waitLoaded(container);

    fireEvent.click(container.querySelector('[data-node-link="n2a"]') as HTMLElement);

    await waitFor(() => expect(useUiStore.getState().selectedNodeId).toBe('n2a'));
    await waitFor(() => expect(router.state.location.pathname).toBe(`/runs/${RUN_ID}/tree`));
  });
});

describe('空清单必须解释为什么空（PRD 12.1）', () => {
  it('fe.db 缺失：说读不到，不说没有知识卡', async () => {
    state.database = 'missing';
    const { container } = renderKnowledgePage();
    await waitLoaded(container);

    expect(screen.getByText('读不到这次运行的知识卡')).toBeInTheDocument();
    expect(container.textContent).toContain('不代表这次运行没有用过知识卡');
    // 空清单不该渲染成一张看起来正常、其实没有数据的空表格。
    expect(container.querySelectorAll('table')).toHaveLength(0);
  });

  it('fe.db 可读且 cards_offered = 0：才是真的没有提供过卡片', async () => {
    state.database = 'available';
    state.knowledge = { cards_offered: 0, cards_adopted: 0 };
    const { container } = renderKnowledgePage();
    await waitLoaded(container);

    expect(screen.getByText('这次运行没有提供过知识卡')).toBeInTheDocument();
    expect(container.textContent).toContain('提供过的卡片数 = 0');
    expect(container.textContent).not.toContain('读不到这次运行的知识卡');
  });

  it('筛选把所有卡片滤掉时给出清空入口，与「一张都没有」区分开', async () => {
    state.cards = [card({ card_id: 'hdd_smart_5' })];
    const { container } = renderKnowledgePage();
    await waitLoaded(container);

    fireEvent.change(screen.getByLabelText('搜索卡片 ID、标题或 claim'), {
      target: { value: 'zzz' },
    });

    expect(container.textContent).toContain('没有卡片符合当前筛选条件');
    expect(screen.queryByText('这次运行没有提供过知识卡')).toBeNull();

    fireEvent.click(screen.getByText('清空筛选'));
    expect(container.querySelector('[data-card-row="hdd_smart_5"]')).not.toBeNull();
  });
});

describe('卡片清单请求失败', () => {
  it('报出错误码与重试，不渲染空表格冒充「没有卡片」', async () => {
    state.cardsFail = true;
    const { container } = renderKnowledgePage();

    await waitFor(() => expect(screen.getByText('artifact.unreadable')).toBeInTheDocument(), {
      timeout: 5000,
    });
    expect(screen.getByText('读不到知识卡清单')).toBeInTheDocument();
    expect(container.querySelectorAll('table')).toHaveLength(0);
    expect(screen.queryByText('这次运行没有提供过知识卡')).toBeNull();
    expect(screen.queryByRole('button', { name: /重试/ })).not.toBeNull();
  });
});

describe('本地标记（信任 / 存疑 / 排除）', () => {
  it('三个选项与「不影响真实运行」同时出现', async () => {
    state.cards = [card({ card_id: 'c1' })];
    const { container } = renderKnowledgePage();
    await waitLoaded(container);

    const select = container.querySelector('[data-label-select="c1"]') as HTMLSelectElement;
    expect([...select.options].map((option) => option.textContent)).toEqual([
      '无标记',
      '信任',
      '存疑',
      '排除',
    ]);
    expect(container.textContent).toContain('仅浏览器本地标记，不影响真实运行');
  });

  it('选择标记写进 localStorage，且 key 带 runId', async () => {
    state.cards = [card({ card_id: 'c1' })];
    const { container } = renderKnowledgePage();
    await waitLoaded(container);

    fireEvent.change(container.querySelector('[data-label-select="c1"]') as HTMLElement, {
      target: { value: '存疑' },
    });

    await waitFor(() =>
      expect(localStorage.getItem(`fe.card-labels.${RUN_ID}`)).toBe('{"c1":"存疑"}'),
    );
  });

  it('标记可撤销，撤销后从存储里删掉该键', async () => {
    localStorage.setItem(`fe.card-labels.${RUN_ID}`, '{"c1":"排除"}');
    state.cards = [card({ card_id: 'c1' })];
    const { container } = renderKnowledgePage();
    await waitLoaded(container);

    expect(
      (container.querySelector('[data-label-select="c1"]') as HTMLSelectElement).value,
    ).toBe('排除');

    fireEvent.change(container.querySelector('[data-label-select="c1"]') as HTMLElement, {
      target: { value: '' },
    });

    await waitFor(() => expect(localStorage.getItem(`fe.card-labels.${RUN_ID}`)).toBe('{}'));
  });

  it('标记跨挂载保留，并能按标记筛选', async () => {
    localStorage.setItem(`fe.card-labels.${RUN_ID}`, '{"c1":"信任","c2":"排除"}');
    state.cards = [card({ card_id: 'c1' }), card({ card_id: 'c2' })];

    const first = renderKnowledgePage();
    await waitLoaded(first.container);
    expect(first.container.querySelectorAll('[data-card-row]')).toHaveLength(2);
    first.unmount();

    // 重新挂载：useState 初始化器从 localStorage 读回，验的是刷新后不丢。
    const { container } = renderKnowledgePage();
    await waitLoaded(container);
    expect(
      (container.querySelector('[data-label-select="c1"]') as HTMLSelectElement).value,
    ).toBe('信任');

    fireEvent.change(screen.getByLabelText('按本地标记筛选'), { target: { value: '排除' } });
    expect(container.querySelector('[data-card-row="c1"]')).toBeNull();
    expect(container.querySelector('[data-card-row="c2"]')).not.toBeNull();
    expect(container.textContent).toContain('1 / 2 张');
  });

  it('存储里被改坏的标记不会让页面崩掉', async () => {
    localStorage.setItem(`fe.card-labels.${RUN_ID}`, '{不是 JSON');
    state.cards = [card({ card_id: 'c1' })];
    const { container } = renderKnowledgePage();
    await waitLoaded(container);

    expect(container.querySelector('[data-card-row="c1"]')).not.toBeNull();
    expect(
      (container.querySelector('[data-label-select="c1"]') as HTMLSelectElement).value,
    ).toBe('');
  });
});

describe('现象层（PRD 12.3）', () => {
  it('判级图例列出五个取值，并明写「未定」不等于「已否证」', async () => {
    state.discovery = emptyDiscovery({
      phenomena: [phenomenon('claim_a', 'confirmed'), phenomenon('claim_b', 'undetermined')],
    });
    const { container } = renderKnowledgePage();
    await waitPhenomena(container);

    const legend = container.querySelector('[data-grade-legend]') as HTMLElement;
    // `discovered` 是 Grade 枚举里比 PRD 12.3 多出来的一个，不能并进 confirmed。
    for (const grade of ['confirmed', 'revised', 'discovered', 'refuted', 'undetermined']) {
      expect(legend.textContent).toContain(grade);
    }
    expect(legend.textContent).toContain('新发现');
    expect(legend.textContent).toContain('不等于「已否证」');

    const undetermined = container.querySelector('[data-phenomenon-card="claim_b"] [data-grade]');
    expect(undetermined?.getAttribute('data-grade')).toBe('undetermined');
    expect(undetermined?.textContent).toBe('未定');
    expect(undetermined?.textContent).not.toContain('否证');
  });

  it('现象卡逐格渲染统计量，0 与 null 分开对待，p 值保留四位', async () => {
    state.discovery = emptyDiscovery({
      phenomena: [phenomenon('claim_a', 'revised', { p: 0.00042, rho_max_abs: 0 })],
    });
    const { container } = renderKnowledgePage();
    await waitPhenomena(container);

    const cardNode = container.querySelector('[data-phenomenon-card="claim_a"]') as HTMLElement;
    const stat = (name: string) => cardNode.querySelector(`[data-stat="${name}"]`);

    expect(stat('effect')?.textContent).toBe('0.1834');
    expect(stat('ci_low')?.textContent).toBe('0.0912');
    expect(stat('n')?.textContent).toBe('4200');
    expect(stat('n_pos')?.textContent).toBe('31');
    expect(stat('direction_ok')?.textContent).toBe('是');
    // 三位小数会把 0.00042 截成 0.000，那就丢掉了「显著」这个信息。
    expect(stat('p')?.textContent).toBe('0.0004');
    expect(stat('p')?.textContent).not.toBe('0.000');
    // 后端给的 0 就是 0，不得显示成未记录。
    expect(stat('rho_max_abs')?.textContent).toBe('0.0000');
    expect(stat('rho_max_abs')?.getAttribute('data-recorded')).toBe('true');
  });

  it('缺失的统计量显示未记录，不显示 0', async () => {
    state.discovery = emptyDiscovery({
      phenomena: [
        {
          claim_id: 'claim_a',
          grade: 'undetermined',
          // incr_* 三个键是 ClaimTestResult 里可选的（schemas.py:43-58）。
          payload: payload({ incr_gain: null, incr_ci_low: null, incr_ci_high: null }),
        },
      ],
    });
    const { container } = renderKnowledgePage();
    await waitPhenomena(container);

    const cardNode = container.querySelector('[data-phenomenon-card="claim_a"]') as HTMLElement;
    for (const name of ['incr_gain', 'incr_ci_low', 'incr_ci_high']) {
      const node = cardNode.querySelector(`[data-stat="${name}"]`);
      expect(node?.textContent).toBe('未记录');
      expect(node?.getAttribute('data-recorded')).toBe('false');
    }
    // 同页还有效应量 CI，两组必须各有自己的钩子，不能共用 ci_low。
    expect(cardNode.querySelector('[data-stat="ci_low"]')?.textContent).toBe('0.0912');
  });

  it('预注册哈希按 claim_id 关联，关联不上时说未记录', async () => {
    state.discovery = emptyDiscovery({
      phenomena: [phenomenon('claim_a', 'confirmed'), phenomenon('claim_b', 'refuted')],
      preregistration: [{ claim_id: 'claim_a', hash: 'a1b2c3d4e5f60718' }],
    });
    const { container } = renderKnowledgePage();
    await waitPhenomena(container);

    const hash = container.querySelector('[data-prereg-hash="claim_a"]');
    expect(hash?.textContent).toBe('预注册 a1b2c3d4');
    expect(hash?.getAttribute('title')).toBe('a1b2c3d4e5f60718');
    expect(
      container.querySelector('[data-phenomenon-card="claim_b"]')?.textContent,
    ).toContain('预注册哈希未记录');
  });

  it('契约外的判级字符串原样回显，不猜它对应五个里的哪一个', async () => {
    state.discovery = emptyDiscovery({ phenomena: [phenomenon('claim_x', 'maybe')] });
    const { container } = renderKnowledgePage();
    await waitPhenomena(container);

    const badge = container.querySelector('[data-phenomenon-card="claim_x"] [data-grade]');
    expect(badge?.getAttribute('data-grade')).toBe('unknown');
    expect(badge?.textContent).toContain('未知判级 maybe');
  });

  it('沙箱失败的 claim 单列一节，明说没有判级，也不给现象卡', async () => {
    state.discovery = emptyDiscovery({ phenomena: [phenomenon('claim_a', 'confirmed')] });
    state.events = [
      sandboxFailedEvent('claim_z'),
      // 非沙箱失败事件不得被顺手算进来。
      { run_id: RUN_ID, id: 2, type: 'node_done', payload: { claim_id: 'claim_q' } },
    ];
    const { container } = renderKnowledgePage();
    await waitPhenomena(container);

    expect(container.querySelectorAll('[data-sandbox-failure]')).toHaveLength(1);
    const section = container.querySelector('[data-sandbox-untested]') as HTMLElement;
    expect(section).not.toBeNull();
    expect(section.textContent).toContain('没有统计结果，因此没有判级');
    expect(section.textContent).toContain('检验根本没跑成');
    expect(section.querySelector('[data-sandbox-failure="claim_z"]')?.textContent).toContain(
      'sandbox timeout after 30s',
    );
    // 失败不等于「已否证」，所以它绝不能出现在现象卡列表里。
    expect(container.querySelector('[data-phenomenon-card="claim_z"]')).toBeNull();
  });

  it('既有检验结果又有沙箱失败：报制品矛盾，两边都列出来', async () => {
    state.discovery = emptyDiscovery({ phenomena: [phenomenon('claim_a', 'confirmed')] });
    state.events = [sandboxFailedEvent('claim_a')];
    const { container } = renderKnowledgePage();
    await waitPhenomena(container);

    expect(container.querySelector('[data-sandbox-untested]')).toBeNull();
    const section = container.querySelector('[data-sandbox-inconsistent]') as HTMLElement;
    expect(section).not.toBeNull();
    expect(section.textContent).toContain('制品互相矛盾');
    expect(section.querySelector('[data-sandbox-failure="claim_a"]')).not.toBeNull();
    // 检验结果照常在，不因矛盾就被抹掉。
    expect(container.querySelector('[data-phenomenon-card="claim_a"]')).not.toBeNull();
  });

  it('事件流读取失败：说无法判断，不假装没有沙箱失败', async () => {
    state.discovery = emptyDiscovery({ phenomena: [phenomenon('claim_a', 'confirmed')] });
    state.eventsFail = true;
    const { container } = renderKnowledgePage();
    await waitPhenomena(container);

    const notice = container.querySelector('[data-events-unavailable]') as HTMLElement;
    expect(notice).not.toBeNull();
    expect(notice.textContent).toContain('events.unavailable');
    expect(notice.textContent).toContain('不表示没有沙箱失败');
    expect(container.querySelector('[data-sandbox-untested]')).toBeNull();
  });

  it('契约警告按字段名渲染', async () => {
    state.discovery = emptyDiscovery({
      warnings: [{ field: 'phenomena[0].payload.p', reason: '缺少 p 值，判级降为未定' }],
    });
    const { container } = renderKnowledgePage();
    await waitPhenomena(container);

    const warning = container.querySelector('[data-contract-warning="phenomena[0].payload.p"]');
    expect(warning?.textContent).toBe('缺少 p 值，判级降为未定');
  });

  it('本轮沉淀的知识卡 id 列出来', async () => {
    state.discovery = emptyDiscovery({
      phenomena: [phenomenon('claim_a', 'discovered')],
      discovered_card_ids: ['hdd_smart_5', 'hdd_realloc_9'],
    });
    const { container } = renderKnowledgePage();
    await waitPhenomena(container);

    const node = container.querySelector('[data-discovered-cards]') as HTMLElement;
    expect(node.textContent).toContain('hdd_smart_5');
    expect(node.textContent).toContain('hdd_realloc_9');
  });

  it('三种「空」分开解释：没开启 / 文件没写出 / 真的是空列表', async () => {
    const cases = [
      {
        overrides: { enabled: false },
        title: '这次运行没有开启知识发现',
        reason: '配置选择，不是失败',
      },
      {
        overrides: { enabled: true, phenomena_state: 'missing' as const },
        title: '没有写出现象记录文件',
        reason: '从未被写出',
      },
      {
        overrides: { enabled: true, phenomena_state: 'available' as const },
        title: '现象记录为空',
        reason: '真实的空结果，不是读取失败',
      },
    ];

    for (const testCase of cases) {
      state.discovery = emptyDiscovery(testCase.overrides);
      const { container, unmount } = renderKnowledgePage();
      await waitPhenomena(container);

      expect(screen.getByText(testCase.title)).toBeInTheDocument();
      expect(container.textContent).toContain(testCase.reason);
      // 空结果不该被画成一张看起来正常的空表格。
      expect(container.querySelectorAll('[data-phenomenon-card]')).toHaveLength(0);
      unmount();
    }
  });

});

describe('机制层与辩论赛（PRD 12.4）', () => {
  const COUNTERS: RunDiscoveryResponse = {
    mechanisms_proposed: 6,
    mechanisms_established: 2,
    mechanisms_refuted: 1,
    mechanism_patches: 3,
    mechanism_cards_count: 4,
    tournament_rounds: 2,
    matches_played: 9,
    decisive_matches: 4,
    underpowered_draws: 5,
    certificates_issued: 2,
    min_detectable_effect: 0.0812,
    planted_mechanism_recovered: 0.75,
    llm_vs_data_kendall_tau: 0.31,
    shuffled_env_false_pass: 0.02,
    neg_control_false_positives: 1,
    neg_control_fpr: 0.05,
  };

  it('三组计数照实渲染，null 显示未记录', async () => {
    state.runDiscovery = COUNTERS;
    const first = renderKnowledgePage();
    await waitLoaded(first.container);

    const stat = (label: string) => first.container.querySelector(`[data-stat="${label}"]`);
    expect(stat('提出的机制')?.textContent).toBe('6');
    expect(stat('判出胜负的对阵')?.textContent).toBe('4');
    expect(stat('最小可检测效应')?.textContent).toBe('0.0812');
    expect(stat('植入机制回收率')?.textContent).toBe('0.7500');
    expect(stat('LLM 与数据的 Kendall τ')?.textContent).toBe('0.3100');
    first.unmount();

    // run_summary 里没有 discovery 段时，计数是「未记录」而不是 0。
    state.runDiscovery = null;
    const second = renderKnowledgePage();
    await waitLoaded(second.container);
    expect(second.container.querySelector('[data-stat="提出的机制"]')?.textContent).toBe('未记录');
    expect(
      second.container.querySelector('[data-stat="提出的机制"]')?.getAttribute('data-recorded'),
    ).toBe('false');
    second.unmount();
  });

  it('不给出任何胜者、排名或推荐机制，`判出胜负的对阵` 只是一个数量', async () => {
    state.runDiscovery = COUNTERS;
    state.discovery = emptyDiscovery({
      certificates: [
        {
          mechanism_id: 'mech_smart5',
          rival_id: 'mech_rival_llm',
          test_id: 't_disc_01',
          test_type: 'bootstrap_diff',
          env: 'hdd',
          stat: 0.214,
          ci: [0.081, 0.347],
          e_value: 9.4,
          prereg_hash: 'deadbeefcafe1234',
          date: '2026-10-01T09:00:00+00:00',
        },
      ],
    });
    const { container } = renderKnowledgePage();
    await waitPhenomena(container);

    const section = container.querySelector('[data-tournament]') as HTMLElement;
    const disclaimer = section.querySelector('[data-no-verdict]') as HTMLElement;
    expect(disclaimer.textContent).toContain('不给出胜者、排名或推荐机制');
    expect(disclaimer.textContent).toContain('不能读成「哪一方赢了」');

    for (const node of section.querySelectorAll('[data-stat]')) {
      expect(node.getAttribute('data-stat')).not.toMatch(/胜者|获胜|赢家|最优机制|推荐机制|排名/);
    }
    expect(section.textContent).not.toMatch(/胜出|夺冠|最佳机制是/);
  });

  it('对照表渲染负对照与植入信号回收，回收率由后端给、前端不重算', async () => {
    state.discovery = emptyDiscovery({
      controls: [
        {
          neg_trials: 200,
          neg_false_positives: 3,
          neg_fpr: 0.015,
          // 键序故意打乱：展示时按名称排序，读数才可复现。
          planted: {
            planted_b: { trials: 10, recovered: null },
            planted_a: { trials: 20, recovered: 15 },
          },
          passed: true,
        },
      ],
    });
    const { container } = renderKnowledgePage();
    await waitPhenomena(container);

    const row = container.querySelector('[data-control-row="0"]') as HTMLElement;
    expect(row).not.toBeNull();
    expect(row.querySelector('[data-stat="neg_trials"]')?.textContent).toBe('200');
    expect(row.querySelector('[data-stat="neg_fpr"]')?.textContent).toBe('0.0150');
    expect(row.textContent).toContain('是');

    const plantedText = [...row.querySelectorAll('li')].map((li) => li.textContent);
    expect(plantedText[0]).toContain('planted_a');
    expect(plantedText[0]).toContain('15 / 20');
    // 内层的 null 也是未记录，不能折成 0。
    expect(plantedText[1]).toContain('planted_b');
    expect(plantedText[1]).toContain('未记录 / 10');
  });

  it('证书表九列照实渲染，ci 二元组拆成上下界，且没有自设的「状态」列', async () => {
    state.discovery = emptyDiscovery({
      certificates: [
        {
          mechanism_id: 'mech_smart5',
          rival_id: 'mech_rival_llm',
          test_id: 't_disc_01',
          test_type: 'bootstrap_diff',
          env: 'hdd',
          stat: 0.214,
          ci: [0.081, 0.347],
          e_value: 9.4,
          prereg_hash: 'deadbeefcafe1234',
          date: '2026-10-01T09:00:00+00:00',
        },
      ],
    });
    const { container } = renderKnowledgePage();
    await waitPhenomena(container);

    const section = container.querySelector('[data-certificates]') as HTMLElement;
    // Certificate 没有 status 字段；前端不得从 e_value 推一个「有效/失效」出来。
    expect(section.querySelector('thead')?.textContent).not.toContain('状态');

    const row = section.querySelector('[data-certificate-row="mech_smart5"]') as HTMLElement;
    expect(row.querySelectorAll('td')).toHaveLength(9);
    expect(row.textContent).toContain('mech_rival_llm');
    expect(row.textContent).toContain('bootstrap_diff');
    expect(row.querySelector('[data-stat="stat"]')?.textContent).toBe('0.2140');
    expect(row.querySelector('[data-stat="ci_low"]')?.textContent).toBe('0.0810');
    expect(row.querySelector('[data-stat="ci_high"]')?.textContent).toBe('0.3470');
    expect(row.querySelector('[data-stat="e_value"]')?.textContent).toBe('9.4000');
    expect(row.textContent).toContain('deadbeef');
    expect(row.textContent).toContain('2026-10-01T09:00:00+00:00');
  });

  it('没有对照与证书时给出解释，不渲染空表格', async () => {
    const { container } = renderKnowledgePage();
    await waitPhenomena(container);

    const controls = container.querySelector('[data-controls]') as HTMLElement;
    expect(controls.textContent).toContain('没有对照记录');
    expect(controls.querySelectorAll('table')).toHaveLength(0);

    const certificates = container.querySelector('[data-certificates]') as HTMLElement;
    expect(certificates.textContent).toContain('没有签发任何证书');
    expect(certificates.querySelectorAll('table')).toHaveLength(0);
  });

  it('不展示 Elo 等未落盘字段', async () => {
    state.runDiscovery = COUNTERS;
    const { container } = renderKnowledgePage();
    await waitLoaded(container);

    const section = container.querySelector('[data-tournament]') as HTMLElement;
    expect(section.querySelector('[data-stat="Elo"]')).toBeNull();
  });
});

describe('三个请求互相隔离', () => {
  it('卡片清单失败：现象层与辩论赛照常渲染已经拿到的事实', async () => {
    state.cardsFail = true;
    state.runDiscovery = { decisive_matches: 4, certificates_issued: 2 };
    state.discovery = emptyDiscovery({ phenomena: [phenomenon('claim_a', 'confirmed')] });
    const { container } = renderKnowledgePage();

    await waitFor(() => expect(screen.getByText('读不到知识卡清单')).toBeInTheDocument(), {
      timeout: 5000,
    });
    await waitPhenomena(container);

    expect(container.querySelector('[data-phenomenon-card="claim_a"]')).not.toBeNull();
    expect(container.querySelector('[data-stat="判出胜负的对阵"]')?.textContent).toBe('4');
    // 采用汇总来自运行详情，与卡片清单无关，同样不该消失。
    expect(container.querySelector('[data-card-summary]')).not.toBeNull();
  });

  it('发现制品失败：报出错误码与重试，知识卡照常渲染', async () => {
    state.discoveryFail = true;
    state.cards = [card({ card_id: 'c1', adopted_count: 2 })];
    const { container } = renderKnowledgePage();

    expect(await waitPhenomena(container)).toBe('error');
    expect(screen.getByText('读不到发现制品')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /重试/ })).not.toBeNull();

    await waitLoaded(container);
    expect(container.querySelector('[data-card-row="c1"]')).not.toBeNull();
    // 现象层挂了不得连带宣称「没有现象记录」。
    expect(container.textContent).not.toContain('现象记录为空');
    // 辩论赛的计数来自运行详情，仍然照实显示未记录而不是被抹掉。
    expect(container.querySelector('[data-no-verdict]')).not.toBeNull();
  });
});
