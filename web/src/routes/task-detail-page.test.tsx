/**
 * 任务详情页的路由级集成测试（PRD §7.8 / TODO §4.6）。
 *
 * 走真实路由树与真实 QueryClient，只 mock 生成的 SDK：这样验的是
 * 「深链接 → 三个请求 → 四个区渲染」整条链路，不是单个组件的 props 透传。
 *
 * 单独建文件而不加进 App.test.tsx：那一处属于另一条工作线正在改的文件。
 */
import { render, screen, waitFor } from '@testing-library/react';
import { createMemoryHistory } from '@tanstack/react-router';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { AppProviders } from '@/app/providers';
import { createAppRouter } from '@/app/router';
import type {
  MetaResponse,
  TaskDatasetCardResponse,
  TaskDetailResponse,
  TaskReadinessResponse,
} from '@/generated/api';
import { createQueryClient } from '@/lib/query-client';
import { useUiStore } from '@/stores/ui-store';

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
  demo_run_ids: ['hdd_mvp_demo_7510f100'],
  engine_version: '0.0.0',
  nav_modules: ['overview', 'workbench', 'knowledge', 'results'],
  process_control_enabled: false,
  stream_transport: 'sse',
};

/** problem.md 里塞进 HTML，用来验证前端不做 Markdown/HTML 渲染。 */
const HOSTILE_PROBLEM_MD = [
  '# 硬盘故障预测',
  '',
  '<script>window.__pwned = true;</script>',
  '<img src="x" onerror="window.__pwned = true">',
  '',
  '数据目录：public。',
].join('\n');

const DETAIL: TaskDetailResponse = {
  task_id: 'hdd_mvp',
  display_name: 'HDD 故障预测（演示）',
  adapter: 'hdd',
  problem_md: HOSTILE_PROBLEM_MD,
  prompt_md: '写一个 predict 函数。',
  required_files: ['evaluator.py', 'init.py', 'problem.md', 'prompt.md'],
  missing_files: [],
  candidate_files: ['init.py', 'rule_baseline.py'],
  data_dirs: ['public'],
  knowledge_enabled: true,
  config_schema_available: true,
};

const CARD: TaskDatasetCardResponse = {
  task_id: 'hdd_mvp',
  display_name: 'HDD 故障预测（演示）',
  adapter: 'hdd',
  is_stub: false,
  device_type: 'HDD',
  summary: '硬盘故障预测。',
  data_ready: true,
  data_missing: [],
  evaluator_ready: true,
  init_ready: true,
  knowledge_card_count: 18,
  metrics: {
    primary_metric: 'ROS',
    target_direction: 'higher',
    target_score: 32,
    initial_score: null,
    score_source: 'unavailable',
  },
};

const READINESS: TaskReadinessResponse = {
  task_id: 'hdd_mvp',
  ready: true,
  checks: [],
  adapter: 'hdd',
  resolved_path: null,
};

/** 每个 it 可以覆盖其中一项，制造单请求失败的场景。 */
const failures: { detail?: boolean; card?: boolean; readiness?: boolean } = {};

function failIf(flag: boolean | undefined, code: string) {
  return flag
    ? { error: { error_code: code, message: 'boom' }, response: { status: 500 } }
    : undefined;
}

vi.mock('@/generated/api', () => ({
  metaApiMetaGet: vi.fn(async () => ({ data: META, response: { status: 200 } })),
  getRunApiRunsRunIdGet: vi.fn(async () => ({ data: {}, response: { status: 200 } })),
  getTaskApiTasksTaskIdGet: vi.fn(async () => {
    const failed = failIf(failures.detail, 'task.not_found');
    return failed ?? { data: DETAIL, response: { status: 200 } };
  }),
  getTaskCardApiTasksTaskIdCardGet: vi.fn(async () => {
    const failed = failIf(failures.card, 'task.not_found');
    return failed ?? { data: CARD, response: { status: 200 } };
  }),
  getTaskReadinessApiTasksTaskIdReadinessGet: vi.fn(async () => {
    const failed = failIf(failures.readiness, 'task.not_found');
    return failed ?? { data: READINESS, response: { status: 200 } };
  }),
}));

function renderTaskPage(taskId = 'hdd_mvp') {
  const router = createAppRouter({
    history: createMemoryHistory({ initialEntries: [`/overview/tasks/${taskId}`] }),
  });
  return render(<AppProviders router={router} queryClient={createQueryClient()} />);
}

/**
 * 等到 detail 请求落地。
 *
 * 必须显式等：路由是异步加载的，而且 `createQueryClient` 默认 `retry: 1`，
 * 失败路径要经过一次退避重试才落定。四个区标题在 pending 阶段就已经渲染，
 * 拿它们当"加载完成"的信号会读到占位值（这正是本文件最初 7 个红的成因）。
 */
async function waitLoaded(container: HTMLElement) {
  await waitFor(() => expect(container.querySelector('[data-problem-md]')).not.toBeNull(), {
    timeout: 5000,
  });
}

async function waitErrorCode(code: string) {
  await waitFor(() => expect(screen.getByText(code)).toBeInTheDocument(), { timeout: 5000 });
}

beforeEach(() => {
  localStorage.clear();
  failures.detail = false;
  failures.card = false;
  failures.readiness = false;
  delete (window as { __pwned?: boolean }).__pwned;
  useUiStore.setState({
    currentRunId: null,
    selectedNodeId: null,
    expandedPanels: [],
    theme: 'light',
    workbenchTab: 'tree',
  });
});

describe('任务详情页（PRD §7.8）', () => {
  it('深链接渲染出三个区标题', async () => {
    renderTaskPage();
    expect(await screen.findByText('任务说明')).toBeInTheDocument();
    expect(screen.getByText('评价契约')).toBeInTheDocument();
    expect(screen.getByText('就绪检查')).toBeInTheDocument();
    expect(screen.queryByText('历史运行')).not.toBeInTheDocument();
  });

  it('problem.md 当纯文本渲染：HTML 原样可见且不执行', async () => {
    const { container } = renderTaskPage();
    const pre = await waitFor(() => {
      const node = container.querySelector('[data-problem-md]');
      expect(node).not.toBeNull();
      return node as HTMLElement;
    });

    expect(pre.textContent).toContain('<script>window.__pwned = true;</script>');
    expect(pre.querySelector('script')).toBeNull();
    expect(pre.querySelector('img')).toBeNull();
    expect((window as { __pwned?: boolean }).__pwned).toBeUndefined();
  });

  it('文件清单只渲染名字，页面上不存在任何下载入口', async () => {
    const { container } = renderTaskPage();
    await waitLoaded(container);

    expect(screen.getByText('evaluator.py')).toBeInTheDocument();
    expect(screen.getByText('rule_baseline.py')).toBeInTheDocument();
    expect(screen.getByText('public')).toBeInTheDocument();

    expect(container.querySelectorAll('[download]')).toHaveLength(0);
    expect(container.querySelectorAll('a[href^="blob:"], a[href^="http"]')).toHaveLength(0);
    expect(screen.queryByRole('button', { name: /下载/ })).toBeNull();
    expect(screen.queryByText(/下载/)).toBeNull();
  });

  it('就绪检查恰好六行，Qwen 显示「未检查」而不是通过', async () => {
    const { container } = renderTaskPage();
    await waitLoaded(container);

    const rows = container.querySelectorAll('[data-readiness-row]');
    expect([...rows].map((row) => row.getAttribute('data-readiness-row'))).toEqual([
      'data',
      'evaluator',
      'init',
      'prompt',
      'knowledge',
      'qwen',
    ]);

    for (const id of ['data', 'evaluator', 'init', 'prompt', 'knowledge']) {
      expect(container.querySelector(`[data-readiness-row="${id}"]`)?.textContent).toContain('通过');
    }

    const qwen = container.querySelector('[data-readiness-row="qwen"]');
    expect(qwen?.textContent).toContain('未检查');
    expect(qwen?.textContent).toContain('llm_key_present');
  });

  it('评价契约：初始基线分显示「待评估」，页面上不出现任何假定分数', async () => {
    const { container } = renderTaskPage();
    await waitLoaded(container);

    const initial = container.querySelector('[data-score-row="初始基线分"]');
    expect(initial?.textContent).toBe('待评估');
    expect(initial?.getAttribute('data-score-state')).toBe('not_recorded');

    expect(container.querySelector('[data-score-row="主指标"]')?.textContent).toBe('ROS');
    expect(container.querySelector('[data-score-row="目标分数"]')?.textContent).toBe('32');
    // 22.81 是 README 里的真实初始分，但**这次响应里没有**，就不能出现。
    expect(container.textContent).not.toContain('22.81');
  });

  it('侧栏仍然只有四个模块，任务详情不新增导航项', async () => {
    const { container } = renderTaskPage();
    await screen.findByText('任务说明');
    expect(container.querySelectorAll('[data-nav-item]')).toHaveLength(4);
  });
});

describe('任务详情页的降级行为', () => {
  it('readiness 请求失败：报错，但另外两个请求拿到的事实照常渲染', async () => {
    failures.readiness = true;
    const { container } = renderTaskPage();

    await waitErrorCode('task.not_found');
    await waitLoaded(container);
    // 区 1 的数据来自 detail，区 2 的数据来自 card，都不该因为 readiness 挂了而消失。
    expect(container.querySelector('[data-problem-md]')?.textContent).toContain('硬盘故障预测');
    expect(container.querySelector('[data-score-row="主指标"]')?.textContent).toBe('ROS');

    // 六个检查项由 card 驱动，card 成功就照常判定；行数不变。
    const rows = container.querySelectorAll('[data-readiness-row]');
    expect(rows).toHaveLength(6);
    for (const id of ['data', 'evaluator', 'init', 'prompt', 'knowledge']) {
      expect(container.querySelector(`[data-readiness-row="${id}"]`)?.textContent).toContain('通过');
    }
    expect(container.querySelector('[data-readiness-row="qwen"]')?.textContent).toContain('未检查');

    // 只有 readiness 独家提供的阻塞项清单降级，且必须说「未记录」而不是「没有阻塞项」：
    // 后者会把一个接口故障画成任务健康。
    expect(container.textContent).toContain('阻塞项未记录');
    expect(container.textContent).not.toContain('没有阻塞项');
  });

  it('card 请求失败：六个检查项全部「未检查」，评价契约显示读取失败', async () => {
    failures.card = true;
    const { container } = renderTaskPage();

    await waitErrorCode('task.not_found');
    await waitLoaded(container);
    const rows = container.querySelectorAll('[data-readiness-row]');
    expect(rows).toHaveLength(6);
    for (const row of rows) {
      expect(row.textContent).toContain('未检查');
    }
    expect(container.querySelector('[data-score-row="主指标"]')?.textContent).toBe('请求失败');
  });

  it('detail 请求失败：任务说明区不伪造内容，标题回落到 card', async () => {
    failures.detail = true;
    const { container } = renderTaskPage();

    await waitErrorCode('task.not_found');
    // detail 挂了就永远不会有 [data-problem-md]，改用 card 驱动的评分行当落定信号。
    await waitFor(
      () => expect(container.querySelector('[data-score-row="主指标"]')?.textContent).toBe('ROS'),
      { timeout: 5000 },
    );

    expect(container.querySelector('[data-problem-md]')).toBeNull();
    // 文件清单四项都拿不到 ⇒ 多处「未记录」，但绝不能是编造的文件名。
    expect(screen.getAllByText('未记录').length).toBeGreaterThanOrEqual(3);
    expect(screen.getByRole('heading', { level: 1, name: 'HDD 故障预测（演示）' })).toBeInTheDocument();

    // card 仍然成功：数据 / evaluator / init 照常判定，只有依赖 detail 的两项降级。
    for (const id of ['data', 'evaluator', 'init']) {
      expect(container.querySelector(`[data-readiness-row="${id}"]`)?.textContent).toContain('通过');
    }
    for (const id of ['prompt', 'knowledge']) {
      expect(container.querySelector(`[data-readiness-row="${id}"]`)?.textContent).toContain('未检查');
    }
  });

  it('三个请求全失败：标题回落到路由参数，页面仍给出错误码而不是空白', async () => {
    failures.detail = true;
    failures.card = true;
    failures.readiness = true;
    const { container } = renderTaskPage();

    await waitErrorCode('task.not_found');
    expect(screen.getByRole('heading', { level: 1, name: 'hdd_mvp' })).toBeInTheDocument();
    expect(container.querySelectorAll('[data-readiness-row]')).toHaveLength(6);
  });
});

describe('受保护名称的纵深防御（PRD §7.8 内容安全）', () => {
  it('detail 漏出 holdout 目录名时，页面报缺陷且不渲染该名字', async () => {
    const original = DETAIL.data_dirs;
    DETAIL.data_dirs = ['public', 'holdout'];
    try {
      const { container } = renderTaskPage();
      await waitLoaded(container);

      const alert = container.querySelector('[data-protected-leak]');
      expect(alert).not.toBeNull();
      expect(alert?.textContent).toContain('这是一个缺陷');
      expect(container.textContent).not.toContain('holdout');
      // 就绪检查的「数据」行会把数据目录拼进说明文本，那里同样不能漏。
      expect(container.querySelector('[data-readiness-row="data"]')?.textContent).toContain('public');
    } finally {
      DETAIL.data_dirs = original;
    }
  });

  it('card 的 data_missing 漏出 holdout 文件名时，同样报缺陷且不渲染', async () => {
    const original = CARD.data_missing;
    CARD.data_missing = ['holdout_labels.csv'];
    try {
      const { container } = renderTaskPage();
      await waitLoaded(container);

      expect(container.querySelector('[data-protected-leak]')).not.toBeNull();
      expect(container.textContent).not.toContain('holdout');
    } finally {
      CARD.data_missing = original;
    }
  });
});
