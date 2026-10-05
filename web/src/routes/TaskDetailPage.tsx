/**
 * 任务详情（PRD §5.2 路由 `/overview/tasks/:taskId` / §7.8 / TODO §4.6）。
 *
 * 三个请求各自独立缓存：`/api/tasks/{id}`（文档与文件清单）、`/card`
 * （指标与就绪标志）、`/readiness`（阻塞项）。任一个失败都不该让另外两个
 * 已经拿到的事实消失，所以错误只汇总成一块面板，数据照常渲染。
 */
import { useQuery } from '@tanstack/react-query';
import { Link, useParams } from '@tanstack/react-router';

import {
  getTaskApiTasksTaskIdGet,
  getTaskCardApiTasksTaskIdCardGet,
  getTaskReadinessApiTasksTaskIdReadinessGet,
} from '@/generated/api';
import { toApiError, unwrap } from '@/lib/api';
import { queryKeys } from '@/lib/query-keys';
import { TaskDetailPanel } from '@/features/intake/TaskDetailPanel';

export function TaskDetailPage() {
  const { taskId } = useParams({ from: '/overview/tasks/$taskId' });

  const detailQuery = useQuery({
    queryKey: queryKeys.task(taskId),
    queryFn: () => unwrap(getTaskApiTasksTaskIdGet({ path: { task_id: taskId } })),
    retry: 1,
  });
  const cardQuery = useQuery({
    queryKey: queryKeys.taskCard(taskId),
    queryFn: () => unwrap(getTaskCardApiTasksTaskIdCardGet({ path: { task_id: taskId } })),
    retry: 1,
  });
  const readinessQuery = useQuery({
    queryKey: queryKeys.taskReadiness(taskId),
    queryFn: () => unwrap(getTaskReadinessApiTasksTaskIdReadinessGet({ path: { task_id: taskId } })),
    retry: 1,
  });

  const queries = [detailQuery, cardQuery, readinessQuery];
  const failed = queries.find((query) => query.isError);

  return (
    <div className="flex flex-col gap-4">
      <Link to="/" className="self-start text-xs text-brand-600 hover:underline">
        ← 返回总览
      </Link>

      <TaskDetailPanel
        taskId={taskId}
        detail={{
          data: detailQuery.data ?? null,
          pending: detailQuery.isPending,
          failed: detailQuery.isError,
        }}
        card={{
          data: cardQuery.data ?? null,
          pending: cardQuery.isPending,
          failed: cardQuery.isError,
        }}
        readiness={{
          data: readinessQuery.data ?? null,
          pending: readinessQuery.isPending,
          failed: readinessQuery.isError,
        }}
        error={failed ? toApiError(failed.error) : null}
        onRetry={() => {
          for (const query of queries) void query.refetch();
        }}
      />
    </div>
  );
}
