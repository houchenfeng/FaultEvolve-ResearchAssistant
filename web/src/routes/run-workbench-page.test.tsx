/**
 * 工作台页的**页面级**测试：专测"刚启动的运行打开时是什么样"。
 *
 * 这条路径是用真浏览器冒烟抓出来的，不是单测想出来的：
 * 点了「启动运行」→ 跳 /runs/<id> → 那一刻运行目录里只有
 * `evolve.effective.yaml` + `logs/`，回放层如实报 `run.unreadable`，
 * 旧实现直接把整页换成「无法打开这个运行 · 重试无法解决」——
 * 没有控制条、没有自动恢复，用户刚点完启动就吃了一个死路。
 *
 * 所以要断言的是**三种输入的三种输出**，而不是组件长什么样：
 * 1. 注册表里有它 + 进程在跑 + 制品读不到 → 说"还没产生"，给控制条，不给错误面板；
 * 2. 注册表里有它 + 进程已死 + 制品读不到 → 说清退出码，并把日志末尾摊开；
 * 3. 注册表里没有 + 制品也读不到 → 这才是错误面板该出现的地方。
 */
import { render, screen } from '@testing-library/react';
import { createMemoryHistory } from '@tanstack/react-router';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { AppProviders } from '@/app/providers';
import { createAppRouter } from '@/app/router';
import type { RunLiveResponse, TreeResponse } from '@/generated/api';
import { createQueryClient } from '@/lib/query-client';
import { useUiStore } from '@/stores/ui-store';

const UNREADABLE = {
  error: { error_code: 'run.unreadable', message: '既没有可读的 run_summary.json，也没有 fe.db' },
  response: { status: 200 },
};

/**
 * 需要逐条控制返回值的端点。用 `vi.hoisted` 是为了让 `vi.mock` 的工厂
 * （被提升到 import 之前）还能拿到同一批 `vi.fn()`，而不是再 import 一次模块
 * —— 依赖顶层 await 去取被 mock 的模块在 hoist 规则下很脆。
 */
const apiMocks = vi.hoisted(() => ({
  getRunApiRunsRunIdGet: vi.fn(),
  getTreeApiRunsRunIdTreeGet: vi.fn(),
  getRunLiveApiRunsRunIdLiveGet: vi.fn(),
  cancelRunApiRunsRunIdCancelPost: vi.fn(),
  pauseRunApiRunsRunIdPausePost: vi.fn(),
  resumeRunApiRunsRunIdResumePost: vi.fn(),
  appendRoundsApiRunsRunIdRoundsPost: vi.fn(),
}));

const runGet = apiMocks.getRunApiRunsRunIdGet;
const treeGet = apiMocks.getTreeApiRunsRunIdTreeGet;
const liveGet = apiMocks.getRunLiveApiRunsRunIdLiveGet;

const TREE: TreeResponse = {
  contract_version: '1.7.0',
  run_id: 'run-1',
  data_state: 'complete',
  nodes: [],
  edges: [],
  best_path: [],
  warnings: [],
};

const RUN_DETAIL = {
  contract_version: '1.7.0',
  run_id: 'run-1',
  data_state: 'complete',
  task_id: 'demo',
  warnings: [],
  summary: null,
  budget: null,
  discovery: null,
};

function live(overrides: Partial<RunLiveResponse> = {}): RunLiveResponse {
  return {
    contract_version: '1.7.0',
    run_id: 'run-1',
    registered: true,
    status: 'running',
    process_alive: true,
    pid: 1234,
    created_at: '2026-10-03T02:00:00Z',
    finished_at: null,
    exit_code: null,
    detail: '',
    log_artifacts: [],
    log_tail: null,
    log_tail_truncated: false,
    ...overrides,
  };
}

vi.mock('@/generated/api', () => ({
  metaApiMetaGet: vi.fn(async () => ({
    data: {
      auth_required: false,
      contract_version: '1.7.0',
      default_deployment_mode: 'local_cloud',
      deployment_modes: [],
      engine_version: '0.0.0',
      nav_modules: ['overview', 'workbench'],
      process_control_enabled: true,
      run_registry_configured: true,
      stream_transport: 'sse',
    },
    response: { status: 200 },
  })),
  listRunsApiRunsGet: vi.fn(async () => ({ data: [], response: { status: 200 } })),
  listTasksApiTasksGet: vi.fn(async () => ({ data: [], response: { status: 200 } })),
  listServersApiServersGet: vi.fn(async () => ({
    data: { profiles: [], default_profile_id: null, ssh_available: false },
    response: { status: 200 },
  })),
  getEventsApiRunsRunIdEventsGet: vi.fn(async () => ({
    data: { events: [] },
    response: { status: 200 },
  })),
  ...apiMocks,
}));

function renderWorkbench() {
  const router = createAppRouter({
    history: createMemoryHistory({ initialEntries: ['/runs/run-1'] }),
  });
  return render(<AppProviders router={router} queryClient={createQueryClient()} />);
}

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  useUiStore.setState({
    currentRunId: null,
    selectedNodeId: null,
    expandedPanels: [],
    theme: 'light',
    workbenchTab: 'tree',
  });
});

describe('工作台（刚刚启动的运行）', () => {
  it('进程在跑但制品还没产生：说"还没产生"，给控制条，不给错误面板', async () => {
    liveGet.mockResolvedValue({ data: live(), response: { status: 200 } } as never);
    runGet.mockResolvedValue(UNREADABLE as never);
    treeGet.mockResolvedValue(UNREADABLE as never);

    renderWorkbench();

    expect(await screen.findByText(/引擎正在运行，制品尚未产生。/)).toBeInTheDocument();
    // 控制条必须在：这是用户唯一能"停掉它"的地方
    expect(await screen.findByText('运行控制')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '取消运行' })).toBeEnabled();
    // 旧实现的那句话不该再出现
    expect(screen.queryByText(/无法打开这个运行/)).not.toBeInTheDocument();
  });

  it('进程已退出且没有制品：说清退出码，并把脱敏日志末尾摊开', async () => {
    liveGet.mockResolvedValue({
      data: live({
        status: 'interrupted',
        process_alive: false,
        exit_code: 1,
        detail: '进程已消失且未产出运行摘要',
        log_tail: 'Error: DASHSCOPE_API_KEY not set. Use --mock for offline testing.',
        log_tail_truncated: false,
      }),
      response: { status: 200 },
    } as never);
    runGet.mockResolvedValue(UNREADABLE as never);
    treeGet.mockResolvedValue(UNREADABLE as never);

    renderWorkbench();

    expect(await screen.findByText(/这次运行没有产出可回放的制品。/)).toBeInTheDocument();
    // 「退出码 1」在页面上出现两次（这句说明 + 控制条里的进程行），所以断言整句。
    expect(screen.getByText(/进程已退出（退出码 1）/)).toBeInTheDocument();
    // 唯一能解释"为什么死了"的那句话，必须真的在页面上
    expect(screen.getByText(/DASHSCOPE_API_KEY not set/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '取消运行' })).toBeDisabled();
    expect(screen.getByRole('button', { name: '恢复运行' })).toBeEnabled();
  });

  it('不是本服务启动的运行且制品读不出来：这才是错误面板该出现的地方', async () => {
    liveGet.mockResolvedValue({
      error: { error_code: 'run.not_found', message: '该运行不是由本服务启动的' },
      response: { status: 404 },
    } as never);
    runGet.mockResolvedValue(UNREADABLE as never);
    treeGet.mockResolvedValue(UNREADABLE as never);

    renderWorkbench();

    expect(await screen.findByText(/无法打开这个运行/)).toBeInTheDocument();
    expect(screen.queryByText('运行控制')).not.toBeInTheDocument();
  });

  it('制品可读时照旧渲染工作台（树 + 闭环摘要 + 控制条）', async () => {
    liveGet.mockResolvedValue({
      data: live({ status: 'completed', process_alive: false, exit_code: 0 }),
      response: { status: 200 },
    } as never);
    runGet.mockResolvedValue({ data: RUN_DETAIL, response: { status: 200 } } as never);
    treeGet.mockResolvedValue({ data: TREE, response: { status: 200 } } as never);

    renderWorkbench();

    /*
     * 必须用 findByText 等**制品落定后才会出现**的那句话来等：左边侧栏里就有一个
     * 叫「进化工作台」的导航项，`waitFor(getByText('进化工作台'))` 会在第 0 ms 通过，
     * 于是后面的断言全落在 query 还没落数据的那一刻，看起来像"页面坏了"。
     */
    expect(await screen.findByText(/闭环：已评估/)).toBeInTheDocument();
    // 标题用 heading 角色断言，别用文本：左侧栏也有一个同名的「进化工作台」导航项。
    expect(screen.getByRole('heading', { name: '进化工作台' })).toBeInTheDocument();
    expect(screen.getByText('运行控制')).toBeInTheDocument();
    expect(screen.queryByText(/无法打开这个运行/)).not.toBeInTheDocument();
  });
});
