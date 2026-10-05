/**
 * 运行对比（PRD §13.3）。
 *
 * 只并排展示同一 task_id 下两次运行的制品字段。没有任务身份就不放分数。
 */
import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';

import { ApiErrorPanel } from '@/components/states/ApiErrorPanel';
import {
  getNodeApiRunsRunIdNodesNodeIdGet,
  getRunApiRunsRunIdGet,
  listRunsApiRunsGet,
} from '@/generated/api';
import {
  NOISE_UNRECORDED,
  comparableTaskIds,
  compareOutcomeRows,
  runsForTask,
  sharedMetricRows,
} from '@/features/results/compare-logic';
import { toApiError, unwrap } from '@/lib/api';
import { queryKeys } from '@/lib/query-keys';

function CellText({ value, recorded }: { value: string; recorded: boolean }) {
  return <span className={recorded ? 'tabular text-fg' : 'text-fg-subtle'}>{value}</span>;
}

export function ComparePage() {
  const listQuery = useQuery({
    queryKey: queryKeys.runList(),
    queryFn: () => unwrap(listRunsApiRunsGet()),
    retry: 1,
  });
  const runs = listQuery.data ?? [];
  const tasks = comparableTaskIds(runs);
  const [taskPick, setTaskPick] = useState<string | null>(null);
  const [leftPick, setLeftPick] = useState<string | null>(null);
  const [rightPick, setRightPick] = useState<string | null>(null);

  const taskId = taskPick && tasks.includes(taskPick) ? taskPick : (tasks[0] ?? null);
  const options = taskId ? runsForTask(runs, taskId) : [];
  const leftId =
    leftPick && options.some((run) => run.run_id === leftPick) ? leftPick : (options[0]?.run_id ?? null);
  const rightId =
    rightPick && options.some((run) => run.run_id === rightPick) && rightPick !== leftId
      ? rightPick
      : (options.find((run) => run.run_id !== leftId)?.run_id ?? null);

  const leftQuery = useQuery({
    queryKey: queryKeys.run(leftId ?? ''),
    queryFn: () => unwrap(getRunApiRunsRunIdGet({ path: { run_id: leftId ?? '' } })),
    enabled: leftId !== null,
    retry: false,
  });
  const rightQuery = useQuery({
    queryKey: queryKeys.run(rightId ?? ''),
    queryFn: () => unwrap(getRunApiRunsRunIdGet({ path: { run_id: rightId ?? '' } })),
    enabled: rightId !== null,
    retry: false,
  });

  const leftNode = leftQuery.data?.outcome?.best_node_id ?? null;
  const rightNode = rightQuery.data?.outcome?.best_node_id ?? null;
  const leftNodeQuery = useQuery({
    queryKey: queryKeys.node(leftId ?? '', leftNode ?? ''),
    queryFn: () =>
      unwrap(getNodeApiRunsRunIdNodesNodeIdGet({ path: { run_id: leftId ?? '', node_id: leftNode ?? '' } })),
    enabled: leftId !== null && leftNode !== null,
    retry: false,
  });
  const rightNodeQuery = useQuery({
    queryKey: queryKeys.node(rightId ?? '', rightNode ?? ''),
    queryFn: () =>
      unwrap(
        getNodeApiRunsRunIdNodesNodeIdGet({ path: { run_id: rightId ?? '', node_id: rightNode ?? '' } }),
      ),
    enabled: rightId !== null && rightNode !== null,
    retry: false,
  });

  const outcomeRows =
    leftQuery.data && rightQuery.data ? compareOutcomeRows(leftQuery.data, rightQuery.data) : [];
  // `metric` 挂在节点的 evaluation 上；节点详情本身没有这个字段，且 evaluation 可空。
  const metricRows = sharedMetricRows(
    leftNodeQuery.data?.evaluation?.metric,
    rightNodeQuery.data?.evaluation?.metric,
  );

  return (
    <div className="flex flex-col gap-3" data-compare-page="true">
      <h1 className="text-base font-semibold text-fg">运行对比</h1>
      <p className="max-w-2xl text-xs text-fg-muted">
        只对比带有同一任务身份的运行。分数来自各次运行的制品，本页不计算分差。
      </p>

      {listQuery.isPending ? (
        <p className="text-xs text-fg-subtle">正在读取运行列表…</p>
      ) : null}
      {listQuery.isError ? (
        <ApiErrorPanel error={toApiError(listQuery.error)} onRetry={() => void listQuery.refetch()} />
      ) : null}

      {listQuery.isSuccess && tasks.length === 0 ? (
        <p className="text-xs text-fg-muted" data-compare-empty="true">
          这批运行都没有任务身份，或同一任务不足两次。不能确认它们属于同一任务，因此不并排罗列分数。
          任务身份只在本服务启动并写入注册表时记录。
        </p>
      ) : null}

      {taskId && options.length >= 2 ? (
        <div className="flex flex-wrap items-end gap-3 text-xs">
          <label className="flex flex-col gap-1">
            任务
            <select
              value={taskId}
              onChange={(event) => {
                setTaskPick(event.target.value);
                setLeftPick(null);
                setRightPick(null);
              }}
              className="rounded-card border border-border-subtle bg-surface px-2 py-1"
            >
              {tasks.map((id) => (
                <option key={id} value={id}>
                  {id}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1">
            运行 A
            <select
              aria-label="运行 A"
              value={leftId ?? ''}
              onChange={(event) => setLeftPick(event.target.value)}
              className="rounded-card border border-border-subtle bg-surface px-2 py-1 font-mono"
            >
              {options.map((run) => (
                <option key={run.run_id} value={run.run_id}>
                  {run.run_id}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1">
            运行 B
            <select
              aria-label="运行 B"
              value={rightId ?? ''}
              onChange={(event) => setRightPick(event.target.value)}
              className="rounded-card border border-border-subtle bg-surface px-2 py-1 font-mono"
            >
              {options.map((run) => (
                <option key={run.run_id} value={run.run_id}>
                  {run.run_id}
                </option>
              ))}
            </select>
          </label>
        </div>
      ) : null}

      {outcomeRows.length > 0 ? (
        <table className="w-full max-w-3xl border-collapse text-left text-xs">
          <thead>
            <tr className="bg-surface-muted text-fg-muted">
              <th className="px-3 py-2 font-medium">字段</th>
              <th className="px-3 py-2 font-medium">运行 A</th>
              <th className="px-3 py-2 font-medium">运行 B</th>
            </tr>
          </thead>
          <tbody>
            {outcomeRows.map((row) => (
              <tr key={row.label} className="border-b border-border-subtle">
                <td className="px-3 py-2 text-fg-muted">{row.label}</td>
                <td className="px-3 py-2">
                  <CellText {...row.left} />
                </td>
                <td className="px-3 py-2">
                  <CellText {...row.right} />
                </td>
              </tr>
            ))}
            {metricRows.map((row) => (
              <tr key={row.label} className="border-b border-border-subtle">
                <td className="px-3 py-2 font-mono text-fg-muted">{row.label}</td>
                <td className="px-3 py-2">
                  <CellText {...row.left} />
                </td>
                <td className="px-3 py-2">
                  <CellText {...row.right} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}

      {taskId ? <p className="text-[11px] text-fg-subtle">{NOISE_UNRECORDED}</p> : null}
    </div>
  );
}
