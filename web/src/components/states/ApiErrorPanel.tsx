/**
 * 统一错误面板（TODO 3.5 / PRD 15.3）。
 *
 * 结构固定为：中文摘要 → 稳定错误码 → 是否可重试 → 建议处理方式 → 折叠技术详情。
 * 技术详情默认收起，且已在归一化阶段做路径脱敏。
 */
import type { ApiError } from '@/lib/api-error';

export interface ApiErrorPanelProps {
  error: ApiError;
  /** 提供后显示重试按钮；仅在 error.retryable 为真时可用。 */
  onRetry?: () => void;
  /** 覆盖默认标题。 */
  title?: string;
  className?: string;
}

export function ApiErrorPanel({ error, onRetry, title, className }: ApiErrorPanelProps) {
  return (
    <div
      role="alert"
      className={[
        'rounded-panel border border-danger-500/30 bg-danger-50 p-4 text-sm',
        'dark:border-danger-500/40 dark:bg-danger-500/10',
        className ?? '',
      ].join(' ')}
    >
      <div className="flex items-start gap-2">
        <span aria-hidden className="mt-0.5 text-danger-500">
          ●
        </span>
        <div className="min-w-0 flex-1">
          <p className="font-medium text-danger-700 dark:text-danger-500">
            {title ?? error.message}
          </p>

          <p className="mt-1 text-xs text-fg-muted">
            错误码 <code className="font-mono text-[11px] select-all">{error.errorCode}</code>
            <span className="mx-1.5 text-fg-subtle">·</span>
            {error.retryable ? '可重试' : '重试无法解决，请按建议处理'}
          </p>

          <p className="mt-1 text-xs text-fg-muted">建议：{error.hint}</p>

          {error.detail ? (
            <details className="mt-2">
              <summary className="cursor-pointer text-xs text-fg-subtle hover:text-fg-muted">
                技术详情
              </summary>
              <pre className="mt-1 overflow-x-auto rounded-card bg-surface-muted p-2 font-mono text-[11px] whitespace-pre-wrap text-fg-muted">
                {error.detail}
              </pre>
            </details>
          ) : null}

          {onRetry ? (
            <button
              type="button"
              onClick={onRetry}
              disabled={!error.retryable}
              className="mt-3 fe-btn fe-btn-secondary fe-btn-sm disabled:cursor-not-allowed"
            >
              {error.retryable ? '重试' : '不可重试'}
            </button>
          ) : null}
        </div>
      </div>
    </div>
  );
}
