/**
 * 运行控制条（阶段 7：取消 / 恢复 / 追加轮次）。
 *
 * ## 为什么读 `/live` 而不是读运行目录
 *
 * `/api/runs/{id}`（回放态，读磁盘制品）与 `/api/runs/{id}/live`（进程态，读注册表）
 * 是两件事：运行刚结束、`run_summary.json` 已落盘但注册表还没标终态时，两者会不一致。
 * 控制条要回答的是"进程还在不在"，所以只认 `/live`，并且**只在进程存活时轮询**
 * （进程没了就停，别让一个看完的页面永远每 2 秒发一次请求）。
 *
 * ## 不是本服务启动的运行
 *
 * demo / 回放目录里的运行在注册表里没有记录，`/live` 返回 404 `run.not_found`。
 * 这时不给任何控制按钮，也不假装它们是"已完成"—— 如实说明它没有可控进程。
 */
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import { StatusBadge } from '@/components/ui/StatusBadge';
import type { BadgeTone } from '@/components/ui/StatusBadge';
import {
  appendRoundsApiRunsRunIdRoundsPost,
  cancelRunApiRunsRunIdCancelPost,
  resumeRunApiRunsRunIdResumePost,
} from '@/generated/api';
import { toApiError, unwrap } from '@/lib/api';
import { queryKeys, runScopedKeys } from '@/lib/query-keys';
import { useRunLive } from '@/features/workbench/use-run-live';

const DEFAULT_APPEND_ROUNDS = 8;

const STATUS_LABEL: Record<string, string> = {
  running: '进行中',
  completed: '已完成',
  failed: '已失败',
  cancelled: '已取消',
  interrupted: '已中断',
};

const STATUS_TONE: Record<string, BadgeTone> = {
  running: 'info',
  completed: 'success',
  failed: 'danger',
  cancelled: 'neutral',
  interrupted: 'warning',
};

/** 可恢复的状态：进程已经不在，但实验本身还没走完。 */
const RESUMABLE_STATUSES = ['failed', 'cancelled', 'interrupted'];

export function RunControls({ runId }: { runId: string }) {
  const queryClient = useQueryClient();
  const [rounds, setRounds] = useState(DEFAULT_APPEND_ROUNDS);
  const [flash, setFlash] = useState<string | null>(null);

  const liveQuery = useRunLive(runId);

  // 一次控制动作会同时改变进程态与（随时间）磁盘制品，所以整片运行缓存一起失效。
  const afterControl = (message: string) => {
    setFlash(message);
    for (const key of runScopedKeys(runId)) {
      void queryClient.invalidateQueries({ queryKey: key });
    }
    void queryClient.invalidateQueries({ queryKey: queryKeys.runList() });
  };

  const cancel = useMutation({
    mutationFn: () => unwrap(cancelRunApiRunsRunIdCancelPost({ path: { run_id: runId } })),
    onSuccess: (result) => afterControl(result.detail ?? '已取消'),
  });
  const resume = useMutation({
    mutationFn: () => unwrap(resumeRunApiRunsRunIdResumePost({ path: { run_id: runId } })),
    onSuccess: (result) => afterControl(result.detail ?? '已恢复'),
  });
  const append = useMutation({
    mutationFn: () =>
      unwrap(
        appendRoundsApiRunsRunIdRoundsPost({
          path: { run_id: runId },
          body: { additional_iterations: rounds },
        }),
      ),
    onSuccess: (result) => afterControl(result.detail ?? `已追加 ${rounds} 轮`),
  });

  const busy = cancel.isPending || resume.isPending || append.isPending;
  const failure = cancel.error ?? resume.error ?? append.error;

  if (liveQuery.isPending) {
    return (
      <div data-run-controls="loading" className="text-[11px] text-fg-subtle">
        正在读取进程状态…
      </div>
    );
  }

  if (liveQuery.isError) {
    const error = toApiError(liveQuery.error);
    // 404 = 这个运行不是本服务启动的（demo / 回放目录），如实说明并撤掉控制按钮。
    const unregistered = error.errorCode === 'run.not_found';
    return (
      <div
        data-run-controls={unregistered ? 'unregistered' : 'error'}
        className="text-[11px] text-fg-subtle"
      >
        {unregistered
          ? '该运行不是由本服务启动的（例如历史运行或演示数据），没有可控进程。'
          : `${error.message}：${error.hint}`}
      </div>
    );
  }

  const live = liveQuery.data;
  const status = live.status ?? 'unknown';
  const running = live.process_alive === true;
  const canResume = RESUMABLE_STATUSES.includes(status) && !running;
  const canCancel = running || status === 'running';
  const canAppend = !running;

  const logArtifacts = live.log_artifacts ?? [];

  return (
    <div
      data-run-controls="ready"
      className="flex flex-wrap items-center gap-2 fe-card-panel px-3 py-2"
    >
      <span className="text-[11px] font-medium text-fg">运行控制</span>
      <StatusBadge
        tone={STATUS_TONE[status] ?? 'neutral'}
        title={live.detail ?? undefined}
      >
        {STATUS_LABEL[status] ?? status}
      </StatusBadge>

      <span className="text-[11px] text-fg-subtle">
        {live.pid !== null && live.pid !== undefined ? `PID ${live.pid}` : '无进程'}
        {running ? ' · 进程存活' : ' · 进程已退出'}
        {live.exit_code !== null && live.exit_code !== undefined ? ` · 退出码 ${live.exit_code}` : ''}
      </span>

      <span className="flex-1" />

      <button
        type="button"
        data-control="cancel"
        disabled={busy || !canCancel}
        onClick={() => cancel.mutate()}
        className="rounded-card border border-danger-500/40 px-2 py-0.5 text-[11px] text-danger-700 hover:bg-danger-50 disabled:opacity-40 disabled:hover:bg-transparent"
      >
        取消运行
      </button>

      <button
        type="button"
        data-control="resume"
        disabled={busy || !canResume}
        onClick={() => resume.mutate()}
        title="沿用原运行 id 与其配置快照继续（--resume）"
        className="fe-btn fe-btn-secondary fe-btn-sm px-2 py-0.5 text-[11px] disabled:opacity-40"
      >
        恢复运行
      </button>

      <label className="flex items-center gap-1 text-[11px] text-fg-muted">
        追加
        <input
          type="number"
          min={1}
          max={500}
          value={rounds}
          aria-label="追加轮次数量"
          data-control="rounds-input"
          onChange={(event) => setRounds(Number(event.target.value))}
          className="w-14 fe-input fe-input-sm px-1 py-0.5 text-[11px]"
        />
        轮
      </label>
      <button
        type="button"
        data-control="rounds-submit"
        disabled={busy || !canAppend || !Number.isInteger(rounds) || rounds < 1 || rounds > 500}
        onClick={() => append.mutate()}
        className="fe-btn fe-btn-secondary fe-btn-sm px-2 py-0.5 text-[11px] disabled:opacity-40"
      >
        追加轮次
      </button>

      {flash !== null ? (
        <span data-control-notice="ok" className="w-full text-[11px] text-success-700">
          {flash}
        </span>
      ) : null}

      {failure !== null && failure !== undefined ? (
        <span data-control-notice="error" className="w-full text-[11px] text-danger-700">
          {toApiError(failure).message}：{toApiError(failure).hint}
        </span>
      ) : null}

      {logArtifacts.length > 0 ? (
        <span className="w-full text-[11px] text-fg-subtle">
          日志：{logArtifacts.join(' · ')}
        </span>
      ) : null}

      {/*
        日志尾巴是**唯一**能解释"进程为什么没了"的通道：日志本身被列成制品，
        但 kind=log 在不可下载集合里，浏览器根本取不到。所以进程一退出就把
        服务端脱敏过的末尾几行摊开，别让用户对着"无制品"发呆。
      */}
      {!running && live.log_tail ? (
        <details
          data-log-tail="true"
          open={live.exit_code !== 0 && live.exit_code !== null}
          className="w-full rounded-card border border-border-subtle bg-surface-muted px-2 py-1"
        >
          <summary className="cursor-pointer text-[11px] text-fg-muted">
            运行日志末尾{live.log_tail_truncated ? '（已截断）' : ''}
          </summary>
          <pre className="mt-1 max-h-48 overflow-auto text-[11px] leading-relaxed whitespace-pre-wrap text-fg-muted">
            {live.log_tail}
          </pre>
        </details>
      ) : null}
    </div>
  );
}
