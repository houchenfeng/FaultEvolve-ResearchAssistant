/**
 * 运行控制条测试（TODO 7.x / PRD §9.4）。
 *
 * 覆盖的是"界面会不会说谎"，不是"按钮长什么样"：
 * - 进程已退出时不给"取消"，进程存活时不给"恢复/追加"；
 * - 不是本服务启动的运行（404 `run.not_found`）不摆控制按钮，也不假装它是"已完成"；
 * - 追加轮次传出去的是**增量**（`additional_iterations`），不是新的总数。
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { RunLiveResponse } from '@/generated/api';
import {
  appendRoundsApiRunsRunIdRoundsPost,
  cancelRunApiRunsRunIdCancelPost,
  getRunLiveApiRunsRunIdLiveGet,
  resumeRunApiRunsRunIdResumePost,
} from '@/generated/api';
import { RunControls } from '@/features/workbench/RunControls';

vi.mock('@/generated/api', () => ({
  getRunLiveApiRunsRunIdLiveGet: vi.fn(),
  cancelRunApiRunsRunIdCancelPost: vi.fn(),
  resumeRunApiRunsRunIdResumePost: vi.fn(),
  appendRoundsApiRunsRunIdRoundsPost: vi.fn(),
}));

const liveGet = vi.mocked(getRunLiveApiRunsRunIdLiveGet);
const cancelPost = vi.mocked(cancelRunApiRunsRunIdCancelPost);
const resumePost = vi.mocked(resumeRunApiRunsRunIdResumePost);
const appendPost = vi.mocked(appendRoundsApiRunsRunIdRoundsPost);

function live(overrides: Partial<RunLiveResponse> = {}): RunLiveResponse {
  return {
    contract_version: '1.6.0',
    run_id: 'run-1',
    registered: true,
    status: 'running',
    execution_backend: 'local_cloud',
    process_alive: true,
    pid: 4321,
    created_at: '2026-10-03T02:00:00Z',
    finished_at: null,
    exit_code: null,
    log_artifacts: ['logs/run.log'],
    detail: '已启动',
    ...overrides,
  };
}

/** 让 `/live` 立刻返回给定进程态。 */
function stubLive(payload: RunLiveResponse) {
  liveGet.mockResolvedValue({ data: payload, response: { status: 200 } } as never);
}

function stubControl(result: Record<string, unknown>) {
  return { data: result, response: { status: 200 } } as never;
}

function renderControls() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <RunControls runId="run-1" />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  stubLive(live());
});

describe('RunControls', () => {
  it('进程存活：显示进行中与 PID，可取消，不可恢复/追加', async () => {
    renderControls();

    expect(await screen.findByText('进行中')).toBeInTheDocument();
    expect(screen.getByText(/PID 4321/)).toBeInTheDocument();
    expect(screen.getByText(/进程存活/)).toBeInTheDocument();

    expect(screen.getByRole('button', { name: '取消运行' })).toBeEnabled();
    expect(screen.getByRole('button', { name: '恢复运行' })).toBeDisabled();
    expect(screen.getByRole('button', { name: '追加轮次' })).toBeDisabled();
  });

  it('点取消：调 cancel 端点，成功后把服务端的 detail 就地显示出来', async () => {
    const user = userEvent.setup();
    cancelPost.mockResolvedValue(
      stubControl({
        run_id: 'run-1',
        status: 'cancelled',
        action: 'cancel',
        applied: true,
        detail: '已停止进程，已有制品保留',
      }),
    );
    renderControls();

    await user.click(await screen.findByRole('button', { name: '取消运行' }));
    expect(cancelPost).toHaveBeenCalledWith({ path: { run_id: 'run-1' } });
    expect(await screen.findByText('已停止进程，已有制品保留')).toBeInTheDocument();
  });

  it('服务端拒绝取消（409）时显示的是归一化后的话，不是原始异常', async () => {
    const user = userEvent.setup();
    cancelPost.mockResolvedValue({
      error: { error_code: 'not_supported', message: '该生命周期操作当前不可用' },
      response: { status: 409 },
    } as never);
    renderControls();

    await user.click(await screen.findByRole('button', { name: '取消运行' }));
    const notice = await screen.findByText(/该能力当前版本尚未实现/);
    expect(notice).toBeInTheDocument();
  });

  it('进程已退出且状态可恢复：取消禁用，恢复可点并调 resume', async () => {
    const user = userEvent.setup();
    stubLive(live({ status: 'interrupted', process_alive: false, finished_at: null }));
    resumePost.mockResolvedValue(
      stubControl({
        run_id: 'run-1',
        status: 'running',
        action: 'resume',
        applied: true,
        detail: '已在原运行上继续',
      }),
    );
    renderControls();

    expect(await screen.findByText('已中断')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '取消运行' })).toBeDisabled();

    await user.click(screen.getByRole('button', { name: '恢复运行' }));
    expect(resumePost).toHaveBeenCalledWith({ path: { run_id: 'run-1' } });
    expect(await screen.findByText(/已在原运行上继续/)).toBeInTheDocument();
  });

  it('已完成：取消/恢复都禁用，但可以追加轮次，且传的是增量', async () => {
    const user = userEvent.setup();
    stubLive(live({ status: 'completed', process_alive: false, exit_code: 0 }));
    appendPost.mockResolvedValue(
      stubControl({
        run_id: 'run-1',
        status: 'running',
        action: 'resume',
        applied: true,
        detail: '已在原运行上追加 12 轮',
      }),
    );
    renderControls();

    expect(await screen.findByText('已完成')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '取消运行' })).toBeDisabled();
    expect(screen.getByRole('button', { name: '恢复运行' })).toBeDisabled();

    const input = screen.getByLabelText('追加轮次数量');
    await user.clear(input);
    await user.type(input, '12');
    await user.click(screen.getByRole('button', { name: '追加轮次' }));

    expect(appendPost).toHaveBeenCalledWith({
      path: { run_id: 'run-1' },
      body: { additional_iterations: 12 },
    });
    expect(await screen.findByText(/已在原运行上追加 12 轮/)).toBeInTheDocument();
  });

  it('非法轮次数（0）在前端就挡住，不发请求', async () => {
    const user = userEvent.setup();
    stubLive(live({ status: 'completed', process_alive: false }));
    renderControls();

    const input = await screen.findByLabelText('追加轮次数量');
    await user.clear(input);
    await user.type(input, '0');
    const submit = screen.getByRole('button', { name: '追加轮次' });
    expect(submit).toBeDisabled();

    await user.click(submit);
    expect(appendPost).not.toHaveBeenCalled();
  });

  it('不是本服务启动的运行（404 run.not_found）：如实说明，不摆控制按钮', async () => {
    liveGet.mockResolvedValue({
      error: { error_code: 'run.not_found', message: '该运行不是由本服务启动的' },
      response: { status: 404 },
    } as never);
    renderControls();

    expect(await screen.findByText(/不是由本服务启动的/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '取消运行' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '恢复运行' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '追加轮次' })).not.toBeInTheDocument();
  });

  it('读取进程态失败（非 404）时给出可读原因与下一步建议', async () => {
    liveGet.mockResolvedValue({
      error: { error_code: 'internal', message: 'boom' },
      response: { status: 500 },
    } as never);
    renderControls();

    const notice = await screen.findByText(/服务内部错误/);
    expect(notice).toBeInTheDocument();
    await waitFor(() => expect(liveGet).toHaveBeenCalled());
  });
});
