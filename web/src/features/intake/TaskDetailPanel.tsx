/**
 * 任务详情面板（PRD §7.8 四个区 / TODO §4.6）。
 *
 * 四个区自上而下：任务说明 → 评价契约 → 就绪检查 → 历史运行。
 * 本组件只吃 props、不发请求（请求在路由页里），这样渲染测试不必 mock SDK。
 *
 * 三条不能破的线：
 * 1. 契约没给的字段显示「未记录」，不显示 0（PRD §2.3）。
 * 3. 只渲染后端给的文件**名**，不拼路径、不提供任何数据下载入口（PRD §7.8）。
 */
import type { ReactNode } from 'react';

import { ApiErrorPanel } from '@/components/states/ApiErrorPanel';
import { StatusBadge } from '@/components/ui/StatusBadge';
import type { BadgeTone } from '@/components/ui/StatusBadge';
import type {
  TaskDatasetCardResponse,
  TaskDetailResponse,
  TaskReadinessResponse,
} from '@/generated/api';
import type { ApiError } from '@/lib/api-error';
import {
  deriveBlockers,
  deriveFileListing,
  deriveReadinessRows,
  deriveScoreContractRows,
  detectProtectedNameLeak,
  type ReadinessState,
} from '@/features/intake/task-detail-logic';

const READINESS_TONE: Record<ReadinessState, BadgeTone> = {
  pass: 'success',
  fail: 'danger',
  unknown: 'neutral',
};

const READINESS_LABEL: Record<ReadinessState, string> = {
  pass: '通过',
  fail: '失败',
  unknown: '未检查',
};

function Section({
  title,
  note,
  children,
}: {
  title: string;
  note?: string;
  children: ReactNode;
}) {
  return (
    <section className="fe-card-panel">
      <div className="border-b border-border-subtle px-4 py-3">
        <h2 className="text-sm font-semibold text-fg">{title}</h2>
        {note ? <p className="mt-0.5 text-[11px] text-fg-subtle">{note}</p> : null}
      </div>
      <div className="p-4">{children}</div>
    </section>
  );
}

/** 只列名字，永远不渲染成链接或下载按钮（PRD §7.8 的内容安全边界）。 */
function NameList({ names, emptyText }: { names: string[]; emptyText: string }) {
  if (names.length === 0) {
    return <p className="text-xs text-fg-subtle">{emptyText}</p>;
  }
  return (
    <ul className="flex flex-wrap gap-1.5">
      {names.map((name) => (
        <li
          key={name}
          className="rounded-card border border-border-subtle bg-surface-muted px-2 py-0.5 font-mono text-[11px] text-fg-muted"
        >
          {name}
        </li>
      ))}
    </ul>
  );
}

/** 一个请求的三态。分开传而不是传整个 query 对象，组件才好测。 */
export interface QueryState<T> {
  data: T | null;
  pending: boolean;
  failed: boolean;
}

export interface TaskDetailPanelProps {
  taskId: string;
  detail: QueryState<TaskDetailResponse>;
  card: QueryState<TaskDatasetCardResponse>;
  readiness: QueryState<TaskReadinessResponse>;
  /** 三个请求里第一个失败的错误；共用一块面板，避免堆三块红。 */
  error: ApiError | null;
  onRetry?: () => void;
}

export function TaskDetailPanel({
  taskId,
  detail,
  card,
  readiness,
  error,
  onRetry,
}: TaskDetailPanelProps) {
  // 六行检查项与评价契约都由 card 驱动，所以只看 card 的状态：
  // readiness 挂了不该把 card 已经拿到的事实一起抹掉。
  const rows = deriveReadinessRows({
    detail: detail.data,
    card: card.data,
    pending: card.pending,
    error: card.failed,
  });
  const blockers = deriveBlockers(readiness.data, readiness.pending, readiness.failed);
  const scoreRows = deriveScoreContractRows(card.data, card.pending, card.failed);
  const files = deriveFileListing(detail.data);
  // detail 的四个清单之外，card.data_missing 也是后端给的文件名，同样要查。
  const leak = [...files.leak, ...detectProtectedNameLeak(card.data?.data_missing ?? [])];
  const anyPending = detail.pending || card.pending || readiness.pending;
  const displayName = detail.data?.display_name ?? card.data?.display_name ?? taskId;
  const adapter = detail.data?.adapter ?? card.data?.adapter ?? readiness.data?.adapter ?? null;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h1 className="text-base font-semibold text-fg">{displayName}</h1>
          <p className="mt-1 font-mono text-[11px] text-fg-subtle">
            {taskId}
            {adapter ? ` · 适配器 ${adapter}` : ''}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {card.data?.is_stub ? <StatusBadge tone="neutral">示例（未就绪）</StatusBadge> : null}
          {blockers.ready === null ? (
            <StatusBadge tone="info">{anyPending ? '检查中…' : '未检查'}</StatusBadge>
          ) : blockers.ready ? (
            <StatusBadge tone="success">就绪</StatusBadge>
          ) : (
            <StatusBadge tone="danger">未就绪</StatusBadge>
          )}
        </div>
      </div>

      {error ? <ApiErrorPanel error={error} onRetry={onRetry} /> : null}

      {/* 区 1：任务说明 */}
      <Section
        title="任务说明"
        note="problem.md 由后端读取、脱敏并限长后送达；若正文以 … 结尾，表示超出后端长度上限被截断。前端不渲染 Markdown，避免任何 HTML 注入（PRD §17.3）。"
      >
        {leak.length > 0 ? (
          <div
            role="alert"
            data-protected-leak="true"
            className="mb-3 rounded-panel border border-danger-500/30 bg-danger-50 p-3 text-xs text-danger-700 dark:border-danger-500/40 dark:bg-danger-500/10 dark:text-danger-500"
          >
            <p className="font-medium">后端返回了受保护名称，这是一个缺陷</p>
            <p className="mt-1">
              {`任务目录服务应当已过滤掉 evaluator 专用区域的名字，但本次响应里出现了 ${leak.length} 个。为避免泄露，本页不渲染这些名字。`}
            </p>
          </div>
        ) : null}

        {detail.data ? (
          <pre
            data-problem-md="true"
            className="max-h-96 overflow-auto fe-card bg-surface-muted p-3 font-mono text-[11px] whitespace-pre-wrap text-fg-muted"
          >
            {detail.data.problem_md || '（后端未读到 problem.md 内容）'}
          </pre>
        ) : (
          <p className="text-xs text-fg-subtle">{detail.pending ? '正在读取…' : '未记录'}</p>
        )}

        <dl className="mt-4 grid gap-4 sm:grid-cols-2">
          <div>
            <dt className="text-[11px] font-medium text-fg-subtle">必需文件</dt>
            <dd className="mt-1">
              <NameList names={files.required} emptyText="未记录" />
            </dd>
          </div>
          <div>
            <dt className="text-[11px] font-medium text-fg-subtle">缺失文件</dt>
            <dd className="mt-1">
              <NameList names={files.missing} emptyText="无" />
            </dd>
          </div>
          <div>
            <dt className="text-[11px] font-medium text-fg-subtle">候选算法文件</dt>
            <dd className="mt-1">
              <NameList names={files.candidates} emptyText="未记录" />
            </dd>
          </div>
          <div>
            <dt className="text-[11px] font-medium text-fg-subtle">
              数据目录（仅名称；受保护目录已由后端过滤）
            </dt>
            <dd className="mt-1">
              <NameList names={files.dataDirs} emptyText="未记录" />
            </dd>
          </div>
        </dl>
      </Section>

      {/* 区 2：评价契约 */}
      <Section
        title="评价契约"
        note="分数只能来自仓库 evaluator（PRD §2.2）。本页只回显契约字段，不做任何计算。"
      >
        <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-xs sm:grid-cols-3">
          {scoreRows.map((row) => (
            <div key={row.label}>
              <dt className="text-[11px] text-fg-subtle">{row.label}</dt>
              <dd
                data-score-row={row.label}
                data-score-state={row.state}
                className={row.state === 'value' ? 'tabular text-fg' : 'tabular text-fg-subtle'}
              >
                {row.value}
              </dd>
            </div>
          ))}
        </dl>
      </Section>

      {/* 区 3：就绪检查 */}
      <Section
        title="就绪检查"
        note="只读检查，不触发任何执行。检查项取自 /api/tasks/{id} 、/card 与 /readiness 三个接口。"
      >
        <table className="w-full border-collapse text-left">
          <thead>
            <tr className="bg-surface-muted text-[11px] text-fg-muted">
              <th className="px-3 py-2 font-medium">检查项</th>
              <th className="px-3 py-2 font-medium">结果</th>
              <th className="px-3 py-2 font-medium">说明</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr
                key={row.id}
                data-readiness-row={row.id}
                className="border-b border-border-subtle last:border-b-0"
              >
                <td className="px-3 py-2 text-xs text-fg">{row.label}</td>
                <td className="px-3 py-2">
                  <StatusBadge tone={READINESS_TONE[row.state]}>{READINESS_LABEL[row.state]}</StatusBadge>
                </td>
                <td className="px-3 py-2 text-xs text-fg-muted">{row.detail}</td>
              </tr>
            ))}
          </tbody>
        </table>

        <div className="mt-3">
          {blockers.ready === null ? (
            <p className="text-xs text-fg-subtle">
              {readiness.pending ? '正在读取阻塞项…' : '阻塞项未记录'}
            </p>
          ) : blockers.checks.length === 0 ? (
            <p className="text-xs text-fg-muted">没有阻塞项。</p>
          ) : (
            <>
              <p className="text-xs font-medium text-danger-700 dark:text-danger-500">
                {blockers.checks.length} 条阻塞项
              </p>
              <ul className="mt-1 list-disc pl-5 text-xs text-fg-muted">
                {blockers.checks.map((check) => (
                  <li key={`${check.field}:${check.reason}`}>
                    <span className="font-medium text-fg">{check.field}</span>：{check.reason}
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
      </Section>
    </div>
  );
}
