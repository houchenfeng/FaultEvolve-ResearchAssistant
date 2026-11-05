import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ComparePage } from '@/routes/ComparePage';

const listRuns = vi.fn();
const getRun = vi.fn();
const getNode = vi.fn();

vi.mock('@/generated/api', () => ({
  listRunsApiRunsGet: (...args: unknown[]) => listRuns(...args),
  getRunApiRunsRunIdGet: (...args: unknown[]) => getRun(...args),
  getNodeApiRunsRunIdNodesNodeIdGet: (...args: unknown[]) => getNode(...args),
}));

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ComparePage />
    </QueryClientProvider>,
  );
}

describe('运行对比页', () => {
  beforeEach(() => {
    listRuns.mockReset();
    getRun.mockReset();
    getNode.mockReset();
  });

  it('没有任务身份时不渲染分数表', async () => {
    listRuns.mockResolvedValue({
      data: [
        { run_id: 'a', data_state: 'complete', task_id: null, best_score: 36.5 },
        { run_id: 'b', data_state: 'complete', task_id: null, best_score: 22.81 },
      ],
      error: undefined,
    });
    renderPage();
    expect(await screen.findByText(/不并排罗列分数/)).toBeInTheDocument();
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
    expect(screen.queryByText('36.50')).not.toBeInTheDocument();
  });

  it('同一任务的两次运行并排展示制品分数', async () => {
    listRuns.mockResolvedValue({
      data: [
        { run_id: 'a', data_state: 'complete', task_id: 'hdd_mvp' },
        { run_id: 'b', data_state: 'complete', task_id: 'hdd_mvp' },
      ],
      error: undefined,
    });
    getRun.mockImplementation(async (options: { path: { run_id: string } }) => ({
      data: {
        run_id: options.path.run_id,
        contract_version: '1.8.0',
        data_state: 'complete',
        outcome: {
          initial_score: 22.81,
          best_score: options.path.run_id === 'a' ? 30 : 28,
          iterations_done: 10,
          stop_reason: 'max_iterations',
          best_node_id: null,
        },
      },
      error: undefined,
    }));
    renderPage();
    expect(await screen.findByRole('table')).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByText('30.00')).toBeInTheDocument();
      expect(screen.getByText('28.00')).toBeInTheDocument();
    });
    expect(screen.getByText(/不能判断分差是否超出噪声/)).toBeInTheDocument();
    expect(screen.queryByText('分差')).not.toBeInTheDocument();
  });
});
