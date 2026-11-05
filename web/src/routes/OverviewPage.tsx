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

function RunsSection() {
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
            nextStep="点击新建运行启动任务；也可先进入成果展示查看归档实验。"
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
              {/* 展示 API 返回的全部运行。**不**按 demo_run_ids 之类的固定 ID
                  过滤：产品路径只认索引给出的来源与可读状态，fixture 是否出现
                  由后端索引决定（D6.2），不由这个页面临时挑选。 */}
              {runsQuery.data.map((run) => (
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
          <Link to="/overview/showcase" className="fe-btn fe-btn-secondary fe-btn-sm">成果展示 ↗</Link>
          <Link to="/runs/new" className="fe-btn fe-btn-primary fe-btn-sm">
            新建运行
          </Link>
        </div>
      </div>

      <section className="fe-home-hero relative overflow-hidden rounded-xl border border-brand-200 bg-white px-5 py-5 dark:border-brand-500/30">
        <img src="/assets/faultevolve-hero-bg.png" alt="" aria-hidden className="pointer-events-none absolute inset-0 size-full object-cover object-center opacity-55" />
        <div className="pointer-events-none absolute inset-0 bg-gradient-to-r from-white via-white/90 to-white/20 dark:from-surface dark:via-surface/90 dark:to-surface/30" />
        <div className="relative">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <p className="text-[11px] font-semibold tracking-[0.18em] text-brand-700 dark:text-brand-300">FAULT EVOLVE · 算法自进化平台</p>
            <h2 className="mt-2 text-xl font-semibold text-fg">三岛协作，让每一次尝试成为下一次进化的起点</h2>
            <p className="mt-1 max-w-2xl text-xs leading-5 text-fg-muted">性能、误漏报与效率独立探索，通过摘要交换学习经验。查看真实运行的进化树、各岛最佳方案与分层调优结果。</p>
            <Link to="/overview/showcase" className="mt-3 inline-flex text-xs font-semibold text-brand-700 dark:text-brand-300">查看归档实验对照与机制演示 →</Link>
          </div>
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
          <p className="mt-1 text-[11px] text-fg-muted">选择一个任务，查看数据说明与公开来源后进入运行配置。</p>
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
          <DatasetCardGrid tasks={tasksQuery.data} />
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

      <RunsSection />
      <CloudSummary />
    </div>
  );
}
