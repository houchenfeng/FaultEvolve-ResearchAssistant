/**
 * 数据边界与审计页的路由级集成测试（PRD 13.4 / TODO 6.4）。
 *
 * 走真实路由树 + 真实 QueryClient，只 mock 生成的 SDK。验的是整条链路：
 * 深链接 → RunLayout 的运行详情 → /api/meta + /artifacts → 两节渲染 + 五项暂不支持。
 *
 * 本页最容易被做错的几件事：
 *  - 纯云端模式下不得宣称「零数据出域」，必须用「受控云端环境」；
 *  - PRD 13.4 七项里只有两项有据，其余五项必须报暂不支持；
 *  - 禁止字段扫描只报数量，不渲染名字本身。
 */
import { createMemoryHistory } from '@tanstack/react-router';
import { render, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { AppProviders } from '@/app/providers';
import { createAppRouter } from '@/app/router';
import type { ArtifactResponse, MetaResponse, RunDetailResponse } from '@/generated/api';
import { createQueryClient } from '@/lib/query-client';
import { useUiStore } from '@/stores/ui-store';

const RUN_ID = 'hdd_mvp_demo_7510f100';

const META: MetaResponse = {
  auth_required: false,
  contract_version: '1.3.0',
  default_deployment_mode: 'local_cloud',
  deployment_modes: [
    {
      available: true,
      detail: '纯云端',
      mode: 'local_cloud',
      supported_transports: ['local_cloud'],
    },
  ],
  demo_run_ids: [RUN_ID],
  engine_version: '0.4.1',
  nav_modules: ['overview', 'workbench', 'knowledge', 'results'],
  process_control_enabled: false,
  stream_transport: 'sse',
};

const state: {
  detail: RunDetailResponse | null;
  artifacts: ArtifactResponse[] | null;
} = {
  detail: null,
  artifacts: null,
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

function artifact(overrides: Partial<ArtifactResponse> = {}): ArtifactResponse {
  return {
    artifact_id: 'run-summary',
    display_name: 'run_summary.json',
    downloadable: false,
    kind: 'summary',
    media_type: 'application/json',
    run_id: RUN_ID,
    size_bytes: 2048,
    state: 'available',
    ...overrides,
  };
}

vi.mock('@/generated/api', () => ({
  metaApiMetaGet: vi.fn(async () => ({ data: META, response: { status: 200 } })),
  getRunApiRunsRunIdGet: vi.fn(async () => ({
    data: state.detail ?? detail(),
    response: { status: 200 },
  })),
  listArtifactsApiRunsRunIdArtifactsGet: vi.fn(async () => ({
    data: state.artifacts != null ? { artifacts: state.artifacts } : null,
    response: { status: 200 },
  })),
}));

function renderAuditPage(runId = RUN_ID) {
  const router = createAppRouter({
    history: createMemoryHistory({ initialEntries: [`/runs/${runId}/audit`] }),
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
  state.artifacts = null;
  useUiStore.setState({
    currentRunId: null,
    selectedNodeId: null,
    expandedPanels: [],
    theme: 'light',
    workbenchTab: 'tree',
  });
});

describe('数据边界与审计页结构', () => {
  it('渲染出边界声明 + 两节有据内容 + 返回结果页入口', async () => {
    const { container } = renderAuditPage();
    await waitSettled(container, 'data-meta-state');
    await waitSettled(container, 'data-artifacts-state');

    const page = container.querySelector('[data-audit-page]') as HTMLElement;
    expect(page).not.toBeNull();
    // 边界声明
    expect(page.querySelector('[data-boundary-statement]')).not.toBeNull();
    // 两节有据内容
    expect(page.querySelector('[data-meta-facts]')).not.toBeNull();
    expect(page.querySelector('[data-boundary-facts]')).not.toBeNull();
    // 返回结果页入口
    expect(page.querySelector('[data-results-link]')).not.toBeNull();
  });

  it('边界声明用「受控云端环境」，不宣称零数据出域', async () => {
    const { container } = renderAuditPage();
    await waitSettled(container, 'data-meta-state');

    const statement = container.querySelector('[data-boundary-statement]') as HTMLElement;
    expect(statement).not.toBeNull();
    expect(statement.textContent).toContain('受控云端环境');
    expect(statement.textContent).toContain('不宣称「零数据出域」');
  });

  it('禁止字段扫描只报数量，不渲染名字本身', async () => {
    state.artifacts = [
      artifact({ artifact_id: 'holdout-set', display_name: 'holdout_labels.csv' }),
    ];
    const { container } = renderAuditPage();
    await waitSettled(container, 'data-artifacts-state');

    const page = container.querySelector('[data-audit-page]') as HTMLElement;
    expect(page).not.toBeNull();
    // 扫描结果应该存在
    const leakScan = page.querySelector('[data-leak-scan]') as HTMLElement;
    expect(leakScan).not.toBeNull();
    // 扫描结果里应该报告命中数
    expect(leakScan.textContent).toContain('命中 2 个受保护名称');
    // 但扫描结果本身不应该渲染名字（名字在边界清单里，那是后端给的数据）
    // 扫描结果只报数量，不重复名字
    expect(leakScan.textContent).not.toContain('holdout-set');
    expect(leakScan.textContent).not.toContain('holdout_labels.csv');
  });
});
