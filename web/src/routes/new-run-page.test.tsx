/**
 * 新建运行六步流程：创建请求只在最后一步出现，已有校验保持不变。
 */
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { UserEvent } from '@testing-library/user-event';
import { createMemoryHistory } from '@tanstack/react-router';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { AppProviders } from '@/app/providers';
import { createAppRouter } from '@/app/router';
import type { MetaResponse, TaskDatasetCardResponse, TaskSummaryResponse } from '@/generated/api';
import { createRunApiRunsPost } from '@/generated/api';
import { createQueryClient } from '@/lib/query-client';
import { useIntakeStore } from '@/stores/intake-store';
import { useUiStore } from '@/stores/ui-store';

const META: MetaResponse = {
  auth_required: false,
  contract_version: '1.5.0',
  default_deployment_mode: 'local_cloud',
  deployment_modes: [
    { mode: 'local_cloud', available: true, supported_transports: ['local_cloud'], detail: '本机可用' },
    { mode: 'ssh_cloud', available: true, supported_transports: ['ssh_cloud'], detail: '远端可用' },
    { mode: 'local_desktop', available: false, supported_transports: [], detail: 'P0 不提供该模式' },
  ],
  demo_run_ids: [],
  engine_version: '0.0.0',
  nav_modules: ['overview', 'workbench', 'knowledge', 'results'],
  process_control_enabled: true,
  run_registry_configured: true,
  qwen_configured: false,
  stream_transport: 'sse',
};

const TASKS: TaskSummaryResponse[] = [
  {
    task_id: 'hdd_mvp',
    display_name: 'HDD 故障预测（演示）',
    adapter: 'hdd',
    has_evaluator: true,
    has_init: true,
    is_stub: false,
  },
  {
    task_id: 'smartmem',
    display_name: 'SmartMem（示例）',
    adapter: 'smartmem',
    has_evaluator: false,
    has_init: false,
    is_stub: true,
  },
];

const CARD: TaskDatasetCardResponse = {
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
  knowledge_card_count: 12,
  metrics: { primary_metric: 'ROS', initial_score: null },
};

vi.mock('@/generated/api', () => ({
  metaApiMetaGet: vi.fn(async () => ({ data: META, response: { status: 200 } })),
  getRunApiRunsRunIdGet: vi.fn(async () => ({ data: {}, response: { status: 200 } })),
  listTasksApiTasksGet: vi.fn(async () => ({ data: TASKS, response: { status: 200 } })),
  getTaskApiTasksTaskIdGet: vi.fn(async () => ({
    data: {
      task_id: 'hdd_mvp',
      display_name: 'HDD 故障预测（演示）',
      adapter: 'hdd',
      problem_md: '',
      prompt_md: '',
      required_files: [],
      missing_files: [],
      candidate_files: [],
      data_dirs: [],
      knowledge_enabled: true,
      config_schema_available: true,
    },
    response: { status: 200 },
  })),
  getTaskCardApiTasksTaskIdCardGet: vi.fn(async () => ({ data: CARD, response: { status: 200 } })),
  listServersApiServersGet: vi.fn(async () => ({
    data: {
      profiles: [
        {
          profile_id: 'p_local',
          display_name: '本机',
          mode: 'local_cloud',
          has_private_key: false,
          secret_masked: true,
        },
      ],
      default_profile_id: 'p_local',
      ssh_available: false,
    },
    response: { status: 200 },
  })),
  listPresetsApiPresetsGet: vi.fn(async () => ({
    data: {
      presets: [
        {
          name: 'quick',
          display_name_zh: '快速演示',
          summary_zh: '少量轮次',
          config: { budget: { max_iterations: 3, max_wall_hours: 0.5, max_tokens: 1000 } },
        },
        {
          name: 'standard',
          display_name_zh: '标准进化',
          summary_zh: '默认强度',
          config: { budget: { max_iterations: 20, max_wall_hours: 6, max_tokens: 200000 } },
        },
        {
          name: 'deep',
          display_name_zh: '深度进化',
          summary_zh: '完整强度',
          config: { budget: { max_iterations: 50, max_wall_hours: 24, max_tokens: 800000 } },
        },
      ],
    },
    response: { status: 200 },
  })),
  createRunApiRunsPost: vi.fn(() => new Promise(() => undefined)),
  mergePresetApiPresetsNameMergePost: vi.fn(async () => ({ data: {}, response: { status: 200 } })),
  upsertServerApiServersPost: vi.fn(async () => ({ data: {}, response: { status: 200 } })),
  deleteServerApiServersProfileIdDelete: vi.fn(async () => ({ data: {}, response: { status: 200 } })),
  probeServerApiServersProfileIdProbePost: vi.fn(async () => ({ data: {}, response: { status: 200 } })),
  checkPathApiServersProfileIdCheckPathPost: vi.fn(async () => ({ data: {}, response: { status: 200 } })),
}));

function renderNewRun() {
  const router = createAppRouter({
    history: createMemoryHistory({ initialEntries: ['/runs/new'] }),
  });
  return render(<AppProviders router={router} queryClient={createQueryClient()} />);
}

async function selectHdd(user: UserEvent) {
  await user.click(await screen.findByRole('radio', { name: /HDD 故障预测/ }));
}

async function clickNext(user: UserEvent) {
  const next = screen.getByRole('button', { name: '下一步' });
  await waitFor(() => expect(next).toBeEnabled());
  await user.click(next);
}

async function advance(user: UserEvent, times: number) {
  for (let i = 0; i < times; i += 1) {
    await clickNext(user);
    if (i === 0) {
      await screen.findByRole('heading', { name: '服务器与目录' });
      await waitFor(() => expect(useIntakeStore.getState().serverProfileId).toBe('p_local'));
    }
  }
}

beforeEach(() => {
  localStorage.clear();
  vi.mocked(createRunApiRunsPost).mockClear();
  useIntakeStore.setState({
    taskId: null,
    serverProfileId: null,
    preset: 'standard',
    patch: {},
    knowledgeMode: 'default',
    notes: '',
    presetPreview: 'idle',
  });
  useUiStore.setState({
    currentRunId: null,
    selectedNodeId: null,
    expandedPanels: [],
    theme: 'light',
    workbenchTab: 'tree',
  });
});

describe('新建运行六步流程', () => {
  it('启动按钮只在最后一步出现，前面的「下一步」不发创建请求', async () => {
    const user = userEvent.setup();
    renderNewRun();

    expect(await screen.findByText('尚未选择任务')).toBeInTheDocument();
    expect(screen.getByText(/不提供自由输入路径/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '启动运行' })).not.toBeInTheDocument();
    expect(document.querySelector('input[type="file"]')).toBeNull();
    expect(await screen.findByRole('radio', { name: /SmartMem/ })).toBeDisabled();

    await selectHdd(user);
    expect(await screen.findByText('任务工件（三项必填）')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '启动运行' })).not.toBeInTheDocument();

    await advance(user, 4);
    expect(screen.getByRole('heading', { name: '高级设置' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '启动运行' })).not.toBeInTheDocument();
    expect(createRunApiRunsPost).not.toHaveBeenCalled();
  });

  it('最后一步在 Qwen 未配置且未勾选 mock 时不能启动，勾选后才发创建请求', async () => {
    const user = userEvent.setup();
    renderNewRun();
    await selectHdd(user);
    await advance(user, 5);

    expect(screen.getByRole('button', { name: /确认并启动/ })).toHaveAttribute('aria-current', 'step');
    const launch = screen.getByRole('button', { name: '启动运行' });
    expect(launch).toBeDisabled();
    expect(screen.getByText(/未配置 Qwen 密钥/)).toBeInTheDocument();
    expect(createRunApiRunsPost).not.toHaveBeenCalled();

    await user.click(screen.getByRole('checkbox', { name: /使用 mock LLM/ }));
    expect(screen.getByRole('button', { name: '启动运行' })).toBeEnabled();
    await user.click(screen.getByRole('button', { name: '启动运行' }));

    await waitFor(() => expect(createRunApiRunsPost).toHaveBeenCalledTimes(1));
    expect(createRunApiRunsPost).toHaveBeenCalledWith({
      body: {
        task_id: 'hdd_mvp',
        server_profile_id: 'p_local',
        preset: 'standard',
        config_patch: {},
        mock_llm: true,
        seed: null,
      },
    });
  });

  it('知识簇选项保持禁用', async () => {
    const user = userEvent.setup();
    renderNewRun();
    await selectHdd(user);
    await advance(user, 2);

    expect(screen.getByRole('heading', { name: '知识注入' })).toBeInTheDocument();
    const disabled = screen.getByText('选择已有知识类别 / 知识簇').closest('label');
    expect(disabled?.querySelector('input')?.hasAttribute('disabled')).toBe(true);
    expect(screen.getByText(/引擎尚无类别过滤字段/)).toBeInTheDocument();
    expect(screen.getByLabelText('使用任务默认知识包')).toBeEnabled();
    expect(screen.queryByRole('button', { name: '启动运行' })).not.toBeInTheDocument();
  });

  it('修改高级设置会标成已自定义，并能恢复档位默认值', async () => {
    const user = userEvent.setup();
    renderNewRun();
    await selectHdd(user);
    await advance(user, 4);

    const iterations = screen.getByLabelText(/迭代上限/);
    await user.clear(iterations);
    await user.type(iterations, '12');
    expect(screen.getByText('已自定义')).toBeInTheDocument();
    expect(useIntakeStore.getState().patch).toEqual({ budget: { max_iterations: 12 } });

    await user.click(screen.getByRole('button', { name: '恢复默认' }));
    expect(screen.queryByText('已自定义')).not.toBeInTheDocument();
    expect(useIntakeStore.getState().patch).toEqual({});
    expect(iterations).toHaveValue(null);
  });

  it('确认页的纯云端保持选中，混合与纯本地只打开说明', async () => {
    const user = userEvent.setup();
    renderNewRun();
    await selectHdd(user);
    await advance(user, 5);

    const cloud = screen.getByRole('button', { name: /纯云端/ });
    const hybrid = screen.getByRole('button', { name: /混合模式/ });
    const local = screen.getByRole('button', { name: /纯本地/ });
    expect(cloud).toHaveAttribute('aria-pressed', 'true');
    expect(hybrid).toHaveAttribute('aria-disabled', 'true');
    expect(hybrid).not.toHaveAttribute('disabled');
    expect(local).toHaveAttribute('aria-disabled', 'true');
    expect(local).not.toHaveAttribute('disabled');

    await user.click(hybrid);
    expect(screen.getByRole('dialog', { name: '部署模式说明' })).toHaveTextContent('本地私有评估');
    expect(cloud).toHaveAttribute('aria-pressed', 'true');
    expect(hybrid).toHaveAttribute('aria-pressed', 'false');
    await user.click(screen.getByRole('button', { name: '知道了' }));

    await user.click(local);
    expect(screen.getByRole('dialog', { name: '部署模式说明' })).toHaveTextContent('P0 不提供该模式');
    expect(cloud).toHaveAttribute('aria-pressed', 'true');
    expect(local).toHaveAttribute('aria-pressed', 'false');
  });

  it('已到达的步骤可以返回再进入', async () => {
    const user = userEvent.setup();
    renderNewRun();
    await selectHdd(user);
    await advance(user, 2);

    await user.click(screen.getByRole('button', { name: '上一步' }));
    expect(screen.getByRole('heading', { name: '服务器与目录' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '执行目标' })).toHaveAttribute('aria-current', 'step');

    await user.click(screen.getByRole('button', { name: /选择任务/ }));
    expect(screen.getByRole('heading', { name: '选择任务' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '启动运行' })).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /知识注入/ }));
    expect(screen.getByRole('heading', { name: '知识注入' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /确认并启动/ })).toBeDisabled();
  });
});
