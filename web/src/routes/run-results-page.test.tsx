/**
 * 结果与报告页的路由级集成测试（PRD 13.1–13.5 / TODO 6.4）。
 *
 * 走真实路由树 + 真实 QueryClient，只 mock 生成的 SDK。验的是整条链路：
 * 深链接 → RunLayout 的运行详情 → 六个请求 → 四节渲染。
 */
import { createMemoryHistory } from '@tanstack/react-router';
import { render, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { AppProviders } from '@/app/providers';
import { createAppRouter } from '@/app/router';
import type {
  MetaResponse,
  NodeDetailResponse,
  ReportManifestResponse,
  RunDetailResponse,
  ScoreboardEntryResponse,
  TreeNodeDto,
  TreeResponse,
} from '@/generated/api';
import { createQueryClient } from '@/lib/query-client';
import { useUiStore } from '@/stores/ui-store';

const RUN_ID = 'hdd_mvp_demo_7510f100';

const META: MetaResponse = {
  auth_required: false,
  contract_version: '1.3.0',
  default_deployment_mode: 'local_cloud',
  deployment_modes: [{ available: true, mode: 'local_cloud', supported_transports: ['local_cloud'] }],
  demo_run_ids: [RUN_ID],
  engine_version: '0.4.1',
  nav_modules: ['overview', 'workbench', 'knowledge', 'results'],
  process_control_enabled: false,
  stream_transport: 'sse',
};

const state: {
  detail: RunDetailResponse | null;
  leaderboard: ScoreboardEntryResponse[] | null;
  tree: TreeResponse | null;
  artifactsFail: boolean;
  report: ReportManifestResponse | null;
  node: NodeDetailResponse | null;
  initialNode: NodeDetailResponse | null;
  baselineFail: boolean;
} = {
  detail: null,
  leaderboard: null,
  tree: null,
  artifactsFail: false,
  report: null,
  node: null,
  initialNode: null,
  baselineFail: false,
};

function detail(overrides: Partial<RunDetailResponse> = {}): RunDetailResponse {
  return {
    run_id: RUN_ID,
    contract_version: '1.3.0',
    data_state: 'complete',
    artifact_states: {
      run_summary: 'available',
      tree: 'available',
      events: 'available',
      database: 'available',
      programs: 'available',
      logs: 'available',
    },
    outcome: { status: 'completed', best_score: 25.4, improvement: 2.59, best_node_id: 'node-1' },
    ...overrides,
  };
}

function tree(overrides: Partial<TreeResponse> = {}): TreeResponse {
  return {
    run_id: RUN_ID,
    contract_version: '1.3.0',
    data_state: 'complete',
    nodes: [
      {
        id: 'node-1',
        branch_id: 'main',
        depth: 0,
        hypothesis_status: 'supported',
        operator: 'init',
        status: 'done',
        score: 25.4,
        delta_score: 2.59,
        noise_delta: 1.0,
        within_noise_band: false,
        is_best: true,
      } as TreeNodeDto,
    ],
    edges: [],
    best_node_id: 'node-1',
    warnings: [],
    ...overrides,
  };
}

vi.mock('@/generated/api', () => ({
  getWorkflowApiRunsRunIdWorkflowGet: vi.fn(async () => ({
    data: { run_id: RUN_ID, data_state: 'missing', search_state: 'missing' }, response: { status: 200 },
  })),
  metaApiMetaGet: vi.fn(async () => ({ data: META, response: { status: 200 } })),
  getRunApiRunsRunIdGet: vi.fn(async () => ({
    data: state.detail ?? detail(),
    response: { status: 200 },
  })),
  getLeaderboardApiRunsRunIdLeaderboardGet: vi.fn(async () => ({
    data: state.leaderboard ?? [],
    response: { status: 200 },
  })),
  getTreeApiRunsRunIdTreeGet: vi.fn(async () => ({
    data: state.tree ?? tree(),
    response: { status: 200 },
  })),
  listArtifactsApiRunsRunIdArtifactsGet: vi.fn(async () =>
    state.artifactsFail
      ? { error: { error_code: 'artifact.unreadable', message: 'boom' }, response: { status: 500 } }
      : { data: { artifacts: [] }, response: { status: 200 } },
  ),
  getReportManifestApiRunsRunIdReportsManifestGet: vi.fn(async () => ({
    data: state.report,
    response: { status: 200 },
  })),
  getNodeApiRunsRunIdNodesNodeIdGet: vi.fn(async ({ path }: { path: { node_id: string } }) => {
    if (path.node_id === 'node-0') {
      return state.baselineFail
        ? { error: { error_code: 'artifact.unreadable', message: 'boom' }, response: { status: 500 } }
        : { data: state.initialNode, response: { status: 200 } };
    }
    return { data: state.node, response: { status: 200 } };
  }),
}));

function renderResultsPage(runId = RUN_ID) {
  const router = createAppRouter({
    history: createMemoryHistory({ initialEntries: [`/runs/${runId}/results`] }),
  });
  const view = render(<AppProviders router={router} queryClient={createQueryClient()} />);
  return { ...view, router };
}

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

beforeEach(() => {
  state.detail = null;
  state.leaderboard = null;
  state.tree = null;
  state.artifactsFail = false;
  state.report = null;
  state.node = null;
  state.initialNode = null;
  state.baselineFail = false;
  useUiStore.setState({
    currentRunId: null,
    selectedNodeId: null,
    expandedPanels: [],
    theme: 'light',
    workbenchTab: 'tree',
  });
});

function setupMeasuredSolutions() {
  const initial = { ...tree().nodes[0], id: 'node-0', score: 20, is_best: false };
  const best = { ...tree().nodes[0], parent_id: 'node-0', depth: 1, operator: 'refine' as const, score: 30 };
  state.tree = tree({ nodes: [initial, best], edges: [{ source: initial.id, target: best.id, kind: 'parent' }] });
  state.detail = detail({ outcome: { initial_score: 20, best_score: 30, best_node_id: best.id } });
  state.initialNode = {
    contract_version: '1.3.0', run_id: RUN_ID, node: initial,
    evaluation: { node_id: initial.id, validity: 1, combined_score: 20, metric: { split: 'val', recall: 0 } },
  };
  state.node = {
    contract_version: '1.3.0', run_id: RUN_ID, node: best,
    evaluation: { node_id: best.id, validity: 1, combined_score: 30, metric: { split: 'val', recall: 0.8 } },
  };
}

describe('方案效果对比交互', () => {
  it('loads the initial evaluation and switches from score to measured recall', async () => {
    setupMeasuredSolutions();
    const user = userEvent.setup();
    const { container } = renderResultsPage();
    await waitFor(() => expect(container.querySelector('option[value="recall"]')).not.toBeNull());
    const section = container.querySelector('[data-solution-comparison]') as HTMLElement;
    await user.selectOptions(within(section).getByRole('combobox', { name: '对比指标' }), 'recall');
    expect(within(section).getByRole('img', { name: '初始方案：0.000 %' })).toBeInTheDocument();
    expect(within(section).getByRole('img', { name: '最优方案：80.000 %' })).toBeInTheDocument();
    await user.click(within(section).getByText('查看指标来源'));
    expect(within(section).getByText('本地评估 → metric.recall')).toBeVisible();
  });

  it('keeps summary scores during baseline failure and recovers after retry', async () => {
    setupMeasuredSolutions();
    state.baselineFail = true;
    const user = userEvent.setup();
    const { container } = renderResultsPage();
    await waitFor(() => expect(container.querySelector('[data-solution-comparison]')?.textContent).toContain('重试初始方案'));
    const section = container.querySelector('[data-solution-comparison]') as HTMLElement;
    expect(within(section).getByRole('img', { name: '最优方案：30.00 分' })).toBeInTheDocument();
    expect(section.querySelector('option[value="recall"]')).toBeNull();
    state.baselineFail = false;
    await user.click(within(section).getByRole('button', { name: '重试初始方案' }));
    await waitFor(() => expect(section.querySelector('option[value="recall"]')).not.toBeNull());
  });
});

describe('结果与报告页结构', () => {
  it('渲染出四节 + 审计入口，侧栏仍然只有四个模块', async () => {
    const { container } = renderResultsPage();
    await waitSettled(container, 'data-outcome');
    await waitSettled(container, 'data-topk');
    await waitSettled(container, 'data-comparison');
    await waitSettled(container, 'data-report');

    expect(container.querySelector('[data-results-page]')).not.toBeNull();
    expect(container.querySelector('[data-audit-link]')).not.toBeNull();
    expect(container.querySelectorAll('[data-nav-item]')).toHaveLength(4);
  });

  it('最佳节点缺失时，分项指标显示「未记录」而不是 0', async () => {
    state.detail = detail({
      outcome: { status: 'completed', best_score: null, improvement: null, best_node_id: null },
    });
    state.tree = tree({ best_node_id: null, nodes: [] });
    const { container } = renderResultsPage();
    await waitSettled(container, 'data-outcome');

    const metrics = container.querySelector('[data-metrics]') as HTMLElement;
    expect(metrics).not.toBeNull();
    expect(metrics.querySelector('[data-metrics-skipped]')).not.toBeNull();
  });
});
