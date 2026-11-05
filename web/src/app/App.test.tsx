/**
 * 应用外壳集成测试（TODO 阶段 3 测试）。
 *
 * 覆盖：侧栏严格四项、当前路由高亮、深链接刷新可恢复当前运行、
 * 不存在的运行给出明确错误而不是无限 loading。
 */
import { render, screen, waitFor } from '@testing-library/react';
import { createMemoryHistory } from '@tanstack/react-router';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { AppProviders } from '@/app/providers';
import { createAppRouter } from '@/app/router';
import type { MetaResponse, RunSummaryResponse, TaskDatasetCardResponse, TaskSummaryResponse } from '@/generated/api';
import { createQueryClient } from '@/lib/query-client';
import { useUiStore } from '@/stores/ui-store';

const META: MetaResponse = {
  auth_required: false,
  contract_version: '1.5.0',
  default_deployment_mode: 'local_cloud',
  deployment_modes: [
    {
      available: false,
      mode: 'local_cloud',
      supported_transports: ['local_cloud', 'ssh_cloud'],
      detail: '纯云端执行后端尚未配置',
    },
  ],
  // 产品配置是空的（D6.5）：总览必须完全不依赖这个字段 —— 列表来自
  // /api/runs 的来源索引，而不是"demo 是哪个固定 ID"。
  demo_run_ids: [],
  engine_version: '0.0.0',
  nav_modules: ['overview', 'workbench', 'knowledge', 'results'],
  process_control_enabled: false,
  stream_transport: 'sse',
};

/** 两份真实运行形态：三岛运行 + 历史单树运行。列表必须两份都出现。 */
const THREE_ISLAND_RUN = 'hdd_mvp_islands_15l4nd01';
const LEGACY_RUN = 'hdd_mvp_demo_7510f100';

const RUNS: RunSummaryResponse[] = [
  {
    run_id: THREE_ISLAND_RUN,
    status: 'finished',
    data_state: 'complete',
    best_score: 22.8,
    improvement: 0,
    iterations_done: 3,
  },
  {
    run_id: LEGACY_RUN,
    status: 'finished',
    data_state: 'complete',
    best_score: 33.7,
    improvement: 10.89,
    iterations_done: 18,
  },
];

const TASKS: TaskSummaryResponse[] = [
  { task_id: 'hdd_mvp', display_name: 'HDD 故障预测（演示）', adapter: 'hdd', has_evaluator: true, has_init: true, is_stub: false },
  { task_id: 'smartmem', display_name: 'SmartMem（示例）', adapter: 'smartmem', has_evaluator: false, has_init: false, is_stub: true },
];

function taskCard(taskId: string): TaskDatasetCardResponse {
  if (taskId === 'smartmem') {
    return {
      task_id: 'smartmem',
      display_name: 'SmartMem（示例）',
      adapter: 'smartmem',
      is_stub: true,
      summary: '示例数据集。',
      blocked_reason: '示例数据集：尚未提供 evaluator / init 工件',
    };
  }
  return {
    task_id: 'hdd_mvp',
    display_name: 'HDD 故障预测（演示）',
    adapter: 'hdd',
    is_stub: false,
    summary: '硬盘故障预测。',
    device_type: 'HDD',
    data_ready: true,
    data_missing: [],
    evaluator_ready: true,
    init_ready: true,
    knowledge_card_count: 51,
    metrics: { primary_metric: 'ROS', target_score: 33.7, initial_score: 22.81 },
  };
}

vi.mock('@/generated/api', () => ({
  metaApiMetaGet: vi.fn(async () => ({ data: META, response: { status: 200 } })),
  listRunsApiRunsGet: vi.fn(async () => ({ data: RUNS, response: { status: 200 } })),
  listTasksApiTasksGet: vi.fn(async () => ({ data: TASKS, response: { status: 200 } })),
  listServersApiServersGet: vi.fn(async () => ({
    data: {
      profiles: [{ profile_id: 'p_local', display_name: '本机', mode: 'local_cloud', has_private_key: false, secret_masked: true }],
      default_profile_id: 'p_local',
      ssh_available: false,
    },
    response: { status: 200 },
  })),
  getTaskCardApiTasksTaskIdCardGet: vi.fn(
    async ({ path }: { path: { task_id: string } }) => ({
      data: taskCard(path.task_id),
      response: { status: 200 },
    }),
  ),
  // 阶段 7：运行布局会问注册表"这个运行是不是本服务启动的"。这些用例跑的都是
  // 历史/演示运行，所以统一回 404 —— 于是"注册表里没有"这条路被显式走到，
  // 而不是靠一个未 mock 的函数抛 TypeError 碰巧成立。
  getRunLiveApiRunsRunIdLiveGet: vi.fn(async () => ({
    error: { error_code: 'run.not_found', message: '该运行不是由本服务启动的' },
    response: { status: 404 },
  })),
  getRunApiRunsRunIdGet: vi.fn(
    async ({ path }: { path: { run_id: string } }) =>
      path.run_id === 'hafi_missing'
        ? {
            error: { error_code: 'run.not_found', message: 'Run not found' },
            response: { status: 404 },
          }
        : {
            data: {
              run_id: path.run_id,
              data_state: 'complete',
              contract_version: '1.5.0',
              artifact_states: {},
              outcome: {
                status: 'finished',
                best_score: 33.7,
                improvement: 10.89,
                iterations_done: 18,
              },
            },
            response: { status: 200 },
          },
  ),
}));

function renderApp(initialPath: string) {
  const router = createAppRouter({
    history: createMemoryHistory({ initialEntries: [initialPath] }),
  });
  const queryClient = createQueryClient();
  const view = render(<AppProviders router={router} queryClient={queryClient} />);
  return { view, router };
}

beforeEach(() => {
  localStorage.clear();
  useUiStore.setState({
    currentRunId: null,
    selectedNodeId: null,
    expandedPanels: [],
    theme: 'light',
    workbenchTab: 'tree',
  });
});

describe('应用外壳', () => {
  it('左侧栏严格只有四个模块，且不含设置/帮助入口', async () => {
    const { view } = renderApp('/');
    await screen.findByText('任务中心');

    const navItems = view.container.querySelectorAll('[data-nav-item]');
    expect(navItems).toHaveLength(4);
    expect([...navItems].map((node) => node.getAttribute('data-nav-item'))).toEqual([
      'overview',
      'workbench',
      'knowledge',
      'results',
    ]);

    // 设置与帮助在顶部栏，不占侧栏。
    const rail = view.container.querySelector('aside[aria-label="主导航"]');
    expect(rail).not.toBeNull();
    expect(rail?.querySelectorAll('[data-nav-item]')).toHaveLength(4);
  });

  it('总览页展示可回放的运行列表（API 返回几条就列几条，不按固定 ID 过滤）', async () => {
    renderApp('/');
    expect(await screen.findByText(THREE_ISLAND_RUN)).toBeInTheDocument();
    expect(screen.getByText(LEGACY_RUN)).toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: '查看证据' })).toHaveLength(2);
  });

  it('任务卡按 API 返回逐个渲染：就绪的可进、未就绪的禁用并说明原因', async () => {
    const { view } = renderApp('/');
    await screen.findByText('HDD 故障预测（演示）');
    const readyCard = view.container.querySelector('[data-dataset-card="hdd_mvp"]');
    expect(readyCard).not.toBeNull();
    const readyButton = readyCard?.querySelector('button');
    expect(readyButton).toBeTruthy();
    expect(readyButton?.hasAttribute('disabled')).toBe(false);

    // 未就绪的 stub 任务同样如实呈现（PRD 7.7：按实际就绪状态，不隐藏），
    // 但入口按钮禁用 —— 这里的期望值随 API 走，不是一份任务白名单。
    // 先等卡片数据落定（blocked_reason 到了按钮才会禁用），否则读到的
    // 是仍在 pending 的卡片：按钮还没上 disabled。
    const stubCard = view.container.querySelector('[data-dataset-card="smartmem"]');
    expect(stubCard).not.toBeNull();
    await waitFor(() => {
      expect(stubCard?.querySelector('button')?.hasAttribute('disabled')).toBe(true);
    });
  });

  it('数据集卡的数字来自 API 而非硬编码（mock 换值界面跟着变）', async () => {
    renderApp('/');
    expect(await screen.findByText('ROS')).toBeInTheDocument();
    expect(screen.getByText('51')).toBeInTheDocument();
  });

  it('总览不出现按 demo_run_ids 固定 ID 的入口（demo_run_ids 为空时也一样）', async () => {
    renderApp('/');
    await screen.findByText('任务中心');
    expect(screen.queryByRole('link', { name: '进入 HDD 案例' })).not.toBeInTheDocument();
    expect(document.querySelector('[data-showcase-run-link]')).toBeNull();
  });

  it('深链接打开运行后，会把它写回 UI store（刷新可恢复当前运行）', async () => {
    renderApp(`/runs/${THREE_ISLAND_RUN}`);
    await waitFor(() => {
      expect(useUiStore.getState().currentRunId).toBe(THREE_ISLAND_RUN);
    });
    // 运行页的深链接标签存在，但不进入侧栏。
    // 用 link 角色定位：工作台标题条上还有一个同名的面板切换**按钮**，
    // 只看文本会命中两个（阶段 7 加了控制条与标题条之后才出现的歧义）。
    expect(await screen.findByRole('link', { name: '进化树' })).toBeInTheDocument();
  });

  it('不存在的运行给出明确错误，而不是一直 loading', async () => {
    renderApp('/runs/hafi_missing');

    expect(await screen.findByText('无法打开这个运行')).toBeInTheDocument();
    expect(screen.getByText('run.not_found')).toBeInTheDocument();
    expect(screen.queryByText('正在读取运行…')).not.toBeInTheDocument();
  });

  it('未知路由显示 404 页面而非空白', async () => {
    renderApp('/nope');
    expect(await screen.findByText('页面不存在')).toBeInTheDocument();
  });
});
