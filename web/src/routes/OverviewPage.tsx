/**
 * 总览页（PRD §7 / TODO 4.1–4.2）。
 *
 * 布局自上而下：新建运行入口 → 数据集与示例卡片（来自 /api/tasks）→
 * 最近运行（/api/runs，阶段 2 交付的只读回放）→ 云端执行目标摘要。
 */
import { useQuery } from '@tanstack/react-query';
import { Link, useNavigate } from '@tanstack/react-router';
import { useState } from 'react';

import { ApiErrorPanel } from '@/components/states/ApiErrorPanel';
import { EmptyState } from '@/components/states/EmptyState';
import { StatusBadge } from '@/components/ui/StatusBadge';
import type { RunSummaryResponse } from '@/generated/api';
import {
  listRunsApiRunsGet,
  listServersApiServersGet,
  listTasksApiTasksGet,
  metaApiMetaGet,
} from '@/generated/api';
import { toApiError, unwrap } from '@/lib/api';
import { queryKeys } from '@/lib/query-keys';
import { DatasetCardGrid } from '@/features/intake/DatasetCardGrid';
import { QwenRuntimeConfig } from '@/features/intake/QwenRuntimeConfig';
import { ServerProfileForm } from '@/features/intake/ServerProfileForm';
import { useUiStore } from '@/stores/ui-store';

const DATA_STATE_TONE = {
  complete: 'success',
  live: 'info',
  unreadable: 'danger',
} as const;

const DATA_STATE_LABEL = {
  complete: '完整',
  live: '运行中',
  unreadable: '不可读',
} as const;

function RunRow({ run, onOpen }: { run: RunSummaryResponse; onOpen: (runId: string) => void }) {
  return (
    <tr className="border-b border-border-subtle last:border-b-0 hover:bg-surface-muted">
      <td className="px-3 py-2 font-mono text-xs text-fg">{run.run_id}</td>
      <td className="px-3 py-2 text-xs text-fg-muted">{run.task_id?.trim() || '未记录'}</td>
      <td className="px-3 py-2">
        <StatusBadge tone={DATA_STATE_TONE[run.data_state]}>{DATA_STATE_LABEL[run.data_state]}</StatusBadge>
      </td>
      <td className="px-3 py-2 text-xs text-fg-muted">{run.status ?? '未记录'}</td>
      <td className="tabular px-3 py-2 text-xs text-fg-muted">
        {run.iterations_done != null ? run.iterations_done : '未记录'}
      </td>
      <td className="tabular px-3 py-2 text-xs text-fg-muted">
        {run.best_score != null ? run.best_score.toFixed(2) : '未评分'}
      </td>
      <td className="px-3 py-2 text-right">
        <button
          type="button"
          onClick={() => onOpen(run.run_id)}
          className="fe-btn fe-btn-secondary fe-btn-sm px-2 py-1"
        >
          查看证据
        </button>
      </td>
    </tr>
  );
}

function RunsSection({ showcaseRunId }: { showcaseRunId: string | null }) {
  const navigate = useNavigate();
  const setCurrentRunId = useUiStore((state) => state.setCurrentRunId);

  const runsQuery = useQuery({
    queryKey: queryKeys.runList(),
    queryFn: () => unwrap(listRunsApiRunsGet()),
    retry: 1,
  });

  const openRun = (runId: string) => {
    setCurrentRunId(runId);
    void navigate({ to: '/runs/$runId', params: { runId } });
  };

  return (
    <section className="fe-card-panel fe-home-module-bg">
      <div className="flex items-center justify-between border-b border-border-subtle px-4 py-3">
        <h2 className="text-sm font-semibold text-fg">验证运行</h2>
        <button
          type="button"
          onClick={() => void runsQuery.refetch()}
          className="fe-btn fe-btn-ghost fe-btn-sm px-2 py-1"
        >
          刷新
        </button>
      </div>

      {runsQuery.isPending ? (
        <div className="px-4 py-10 text-center text-xs text-fg-subtle">正在读取运行列表…</div>
      ) : runsQuery.isError ? (
        <div className="p-4">
          <ApiErrorPanel error={toApiError(runsQuery.error)} onRetry={() => void runsQuery.refetch()} />
        </div>
      ) : runsQuery.data.length === 0 ? (
        <div className="p-4">
          <EmptyState
            title="还没有可回放的运行"
            reason="后端在配置的运行目录下一层没有发现任何运行目录。"
            nextStep="通过 CLI 产生一次进化运行，或等待阶段 7 的运行创建能力。"
          />
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-left">
            <thead>
              <tr className="bg-surface-muted text-[11px] text-fg-muted">
                <th className="px-3 py-2 font-medium">运行 ID</th>
                <th className="px-3 py-2 font-medium">任务</th>
                <th className="px-3 py-2 font-medium">制品</th>
                <th className="px-3 py-2 font-medium">状态</th>
                <th className="px-3 py-2 font-medium">轮次</th>
                <th className="px-3 py-2 font-medium">最佳分</th>
                <th className="px-3" />
              </tr>
            </thead>
            <tbody>
              {runsQuery.data.filter((run) => !showcaseRunId || run.run_id === showcaseRunId).map((run) => (
                <RunRow key={run.run_id} run={run} onOpen={openRun} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function CloudSummary() {
  const serversQuery = useQuery({
    queryKey: queryKeys.serverList(),
    queryFn: () => unwrap(listServersApiServersGet()),
    retry: 1,
  });
  const data = serversQuery.data;
  if (serversQuery.isPending) return null;
  if (serversQuery.isError || !data) return null;
  const localAvailable = (data.profiles ?? []).length > 0;
  return (
    <section
      data-cloud-summary="true"
      className="flex flex-wrap items-center gap-3 fe-card-panel px-4 py-3 text-[11px] text-fg-muted"
    >
      <span className="text-xs font-medium text-fg">云端执行目标</span>
      <StatusBadge tone={localAvailable ? 'success' : 'warning'}>
        local_cloud {localAvailable ? '已配置' : '未配置'}
      </StatusBadge>
      <StatusBadge tone={data.ssh_available ? 'success' : 'neutral'}>
        ssh_cloud {data.ssh_available ? '可用' : '未安装 asyncssh'}
      </StatusBadge>
      <span>共 {data.profiles?.length ?? 0} 个配置</span>
    </section>
  );
}

export function OverviewPage() {
  const [configExpanded, setConfigExpanded] = useState(false);
  const metaQuery = useQuery({
    queryKey: queryKeys.meta(),
    queryFn: () => unwrap(metaApiMetaGet()),
    retry: 1,
  });
  const showcaseRunId = metaQuery.data?.demo_run_ids?.[0] ?? null;

  const tasksQuery = useQuery({
    queryKey: queryKeys.taskList(),
    queryFn: () => unwrap(listTasksApiTasksGet()),
    retry: 1,
  });

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-base font-semibold text-fg">任务中心</h1>
          <p className="mt-1 text-xs text-fg-muted">
            选择已有运行进入回放，或按流程配置新的进化任务。
          </p>
        </div>
        <div className="flex shrink-0 flex-wrap gap-2">
          {showcaseRunId ? (
            <Link
              to="/runs/$runId"
              params={{ runId: showcaseRunId }}
              className="fe-btn fe-btn-secondary fe-btn-sm"
              data-showcase-run-link="true"
            >
              进入 HDD 案例
            </Link>
          ) : null}
          <Link to="/runs/new" className="fe-btn fe-btn-primary fe-btn-sm">
            新建运行
          </Link>
        </div>
      </div>

      <section className="fe-showcase-hero relative overflow-hidden rounded-xl border border-brand-200 bg-white px-5 py-5 dark:border-brand-500/30">
        <img src="/assets/faultevolve-hero-bg.png" alt="" aria-hidden className="pointer-events-none absolute inset-0 size-full object-cover object-center opacity-55" />
        <div className="pointer-events-none absolute inset-0 bg-gradient-to-r from-white via-white/90 to-white/20 dark:from-surface dark:via-surface/90 dark:to-surface/30" />
        <div className="relative">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <p className="text-[11px] font-semibold tracking-[0.18em] text-brand-700 dark:text-brand-300">FAULT EVOLVE · 演示导览</p>
            <h2 className="mt-2 text-xl font-semibold text-fg">从候选生成到故障预测结果</h2>
            <p className="mt-1 max-w-2xl text-xs leading-5 text-fg-muted">沿着进化树查看每轮尝试，再看知识发现与评估结果，完整理解算法如何迭代。</p>
          </div>
          {showcaseRunId ? (
            <Link to="/runs/$runId/tree" params={{ runId: showcaseRunId }} className="fe-btn fe-btn-primary fe-btn-md">
              查看进化过程 →
            </Link>
          ) : null}
        </div>
        <div className="mt-5 grid gap-2 sm:grid-cols-3">
          {['01 任务与数据', '02 进化搜索', '03 结果与证据'].map((step) => (
            <div key={step} className="rounded-lg border border-white/70 bg-white/70 px-3 py-2 text-xs font-medium text-fg shadow-sm dark:border-white/10 dark:bg-white/5">{step}</div>
          ))}
        </div>
        </div>
      </section>

      {/* 数据集与示例 */}
      <section className="fe-home-module-bg flex flex-col gap-3 rounded-xl border border-border-subtle p-4">
        <div>
          <h2 className="text-sm font-semibold text-fg">任务与数据</h2>
          <p className="mt-1 text-[11px] text-fg-muted">选择 HDD 或 SmartMem 任务，查看数据说明与公开来源后进入运行配置。</p>
        </div>
        {tasksQuery.isPending ? (
          <div className="fe-card-panel px-4 py-10 text-center text-xs text-fg-subtle">
            正在读取任务目录…
          </div>
        ) : tasksQuery.isError ? (
          <div className="p-2">
            <ApiErrorPanel
              error={toApiError(tasksQuery.error)}
              onRetry={() => void tasksQuery.refetch()}
            />
          </div>
        ) : (
          <DatasetCardGrid tasks={tasksQuery.data.filter((task) => ['hdd_mvp', 'smartmem'].includes(task.task_id))} />
        )}
      </section>

      <section className="fe-home-module-bg overflow-hidden rounded-xl border border-border-subtle">
        <button
          type="button"
          aria-expanded={configExpanded}
          aria-controls="overview-run-config"
          onClick={() => setConfigExpanded((expanded) => !expanded)}
          className="flex w-full items-center justify-between gap-4 px-4 py-4 text-left hover:bg-surface-muted/60"
        >
          <div>
            <h2 className="text-sm font-semibold text-fg">运行配置</h2>
            <p className="mt-1 text-[11px] text-fg-muted">集中配置模型服务、执行服务器、工作目录、运行环境与额外要求。</p>
          </div>
          <span className="shrink-0 rounded-full border border-border-subtle bg-white px-3 py-1.5 text-[11px] font-medium text-brand-700 shadow-sm">
            {configExpanded ? '收起配置 ↑' : '展开配置 ↓'}
          </span>
        </button>
        {configExpanded ? (
          <div id="overview-run-config" className="flex flex-col gap-3 border-t border-border-subtle p-4">
            <QwenRuntimeConfig />
            <div className="fe-card-panel p-4"><ServerProfileForm /></div>
          </div>
        ) : null}
      </section>

      <RunsSection showcaseRunId={showcaseRunId} />
      <CloudSummary />
    </div>
  );
}
