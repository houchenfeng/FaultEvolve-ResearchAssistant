/**
 * 示例与数据集卡片区（TODO 4.1 / PRD 7.1 第 3 区 / PRD 7.7）。
 *
 * 卡片数据逐任务取 `/api/tasks/{id}/card`；stub 数据集显示「示例（未就绪）」
 * 且 CTA 禁用并给出原因——按 PRD 7.7「按实际就绪状态」如实呈现，不隐藏。
 */
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from '@tanstack/react-router';

import { ApiErrorPanel } from '@/components/states/ApiErrorPanel';
import { EmptyState } from '@/components/states/EmptyState';
import { StatusBadge } from '@/components/ui/StatusBadge';
import type { TaskSummaryResponse } from '@/generated/api';
import { getTaskCardApiTasksTaskIdCardGet } from '@/generated/api';
import { toApiError, unwrap } from '@/lib/api';
import { queryKeys } from '@/lib/query-keys';
import { useIntakeStore } from '@/stores/intake-store';

const PUBLIC_DATASET_INFO: Record<string, { description: string; href: string; linkLabel: string }> = {
  hdd_mvp: {
    description: 'Backblaze 数据中心硬盘 SMART 日快照；最长 14 天观测窗口，预测未来 7 天故障。',
    href: 'https://www.backblaze.com/cloud-storage/resources/hard-drive-test-data',
    linkLabel: 'Backblaze Drive Stats',
  },
  smartmem: {
    description: '服务器内存 CE/UE 事件与工单数据；用于内存故障预测和跨器件知识迁移。',
    href: 'https://www.codabench.org/competitions/3586/',
    linkLabel: 'SmartMem Competition',
  },
};

function readableSummary(raw: string | null | undefined): string {
  if (!raw) return '暂无简介。';
  const lines = raw
    .replace(/<!--[\s\S]*?-->/g, '')
    .split(/\r?\n/)
    .map((line) => line.replace(/^\s*(?:#{1,6}\s*|[-*]\s*)/, '').trim())
    .filter(Boolean);
  return lines.find((line) => /[\u4e00-\u9fff]/.test(line) && line.length > 15) ?? lines[0] ?? '暂无简介。';
}

function DatasetCard({ task }: { task: TaskSummaryResponse }) {
  const navigate = useNavigate();
  const setTask = useIntakeStore((state) => state.setTask);

  const cardQuery = useQuery({
    queryKey: queryKeys.taskCard(task.task_id),
    queryFn: () => unwrap(getTaskCardApiTasksTaskIdCardGet({ path: { task_id: task.task_id } })),
    retry: 1,
  });

  const card = cardQuery.data;
  const blocked = card?.blocked_reason ?? null;
  const publicInfo = PUBLIC_DATASET_INFO[task.task_id];

  return (
    <div
      data-dataset-card={task.task_id}
      className="flex flex-col gap-2 fe-card-panel fe-card-interactive p-4 shadow-[var(--shadow-fluent-sm)]"
    >
      <div className="flex items-start justify-between gap-2">
        <div>
          <h3 className="text-sm font-medium text-fg">{task.display_name}</h3>
          <p className="mt-0.5 text-[11px] text-fg-subtle">
            {task.task_id}
            {card?.device_type ? ` · ${card.device_type}` : ''}
          </p>
        </div>
        {cardQuery.isPending ? (
          <StatusBadge tone="info">检查中…</StatusBadge>
        ) : card?.is_stub ? (
          <StatusBadge tone="neutral">示例（未就绪）</StatusBadge>
        ) : blocked ? (
          <StatusBadge tone="warning">未就绪</StatusBadge>
        ) : (
          <StatusBadge tone="success">完整可运行</StatusBadge>
        )}
      </div>

      {cardQuery.isError ? (
        <ApiErrorPanel error={toApiError(cardQuery.error)} onRetry={() => void cardQuery.refetch()} />
      ) : card ? (
        <>
          <p className="line-clamp-2 min-h-[2.5em] text-xs text-fg-muted">{readableSummary(card.summary)}</p>
          {publicInfo ? (
            <div className="rounded-md border border-brand-200/70 bg-brand-50/60 px-3 py-2 text-[11px] leading-5">
              <p className="text-fg-muted">{publicInfo.description}</p>
              <a
                href={publicInfo.href}
                target="_blank"
                rel="noreferrer"
                className="mt-1 inline-flex font-medium text-brand-700 hover:underline"
              >
                数据来源：{publicInfo.linkLabel} ↗
              </a>
            </div>
          ) : null}
          <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-[11px]">
            <div>
              <dt className="text-fg-subtle">主指标</dt>
              <dd className="text-fg">{card.metrics?.primary_metric || '—'}</dd>
            </div>
            <div>
              <dt className="text-fg-subtle">数据准备</dt>
              <dd className="text-fg">{card.data_ready ? '已就绪' : (card.data_missing?.length ?? 0) > 0 ? `缺 ${card.data_missing?.length} 个文件` : '未就绪'}</dd>
            </div>
            <div>
              <dt className="text-fg-subtle">evaluator</dt>
              <dd className="text-fg">{card.evaluator_ready ? '通过' : '未通过'}</dd>
            </div>
            <div>
              <dt className="text-fg-subtle">初始算法</dt>
              <dd className="text-fg">{card.init_ready ? '通过' : '未通过'}</dd>
            </div>
            <div>
              <dt className="text-fg-subtle">知识卡</dt>
              <dd className="tabular text-fg">{card.knowledge_card_count ?? '—'}</dd>
            </div>
            <div>
              <dt className="text-fg-subtle">初始基线分</dt>
              <dd className="tabular text-fg">
                {card.metrics?.initial_score != null ? card.metrics.initial_score : '待评估'}
              </dd>
            </div>
          </dl>
        </>
      ) : null}

      <div className="mt-auto flex items-center justify-between gap-2 pt-1">
        {blocked ? (
          <p className="text-[11px] text-warning-700" title={blocked}>
            {blocked}
          </p>
        ) : (
          <p className="text-[11px] text-fg-subtle">点击进入任务录入</p>
        )}
        <button
          type="button"
          disabled={Boolean(blocked)}
          title={blocked ?? undefined}
          onClick={() => {
            setTask(task.task_id);
            void navigate({ to: '/runs/new' });
          }}
          className="shrink-0 fe-btn fe-btn-secondary fe-btn-sm px-2.5 py-1 disabled:cursor-not-allowed"
        >
          创建任务
        </button>
      </div>
    </div>
  );
}

export function DatasetCardGrid({ tasks }: { tasks: TaskSummaryResponse[] }) {
  if (tasks.length === 0) {
    return (
      <EmptyState
        title="任务目录中没有任务"
        reason="配置的任务目录下一层没有发现可识别的任务目录。"
        nextStep="检查 FE_WEB_TASK_ROOTS 是否指向 benchmark/ 一类的任务根目录。"
      />
    );
  }
  return (
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      {tasks.map((task) => (
        <DatasetCard key={task.task_id} task={task} />
      ))}
    </div>
  );
}
