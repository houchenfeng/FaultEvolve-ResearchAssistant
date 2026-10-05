/**
 * 状态徽章：小圆点 + 文字，用于顶部栏服务状态与各页状态标记。
 * 配色遵循概念图：绿=正常/成功，红=失败，黄=等待/降级，蓝=中性信息，灰=未接入。
 */
import type { ReactNode } from 'react';

export type BadgeTone = 'success' | 'danger' | 'warning' | 'info' | 'neutral' | 'brand';

const TONE_CLASS: Record<BadgeTone, string> = {
  success:
    'border-success-500/30 bg-success-50 text-success-700 dark:border-success-500/40 dark:bg-success-500/10 dark:text-success-500',
  danger:
    'border-danger-500/30 bg-danger-50 text-danger-700 dark:border-danger-500/40 dark:bg-danger-500/10 dark:text-danger-500',
  warning:
    'border-warning-500/30 bg-warning-50 text-warning-700 dark:border-warning-500/40 dark:bg-warning-500/10 dark:text-warning-500',
  info: 'border-info-500/30 bg-info-50 text-info-700 dark:border-info-500/40 dark:bg-info-500/10 dark:text-info-500',
  neutral:
    'border-border-subtle bg-surface-muted text-fg-muted dark:border-border-strong dark:text-fg-muted',
  brand:
    'border-brand-200 bg-brand-50 text-brand-600 dark:border-brand-500/40 dark:bg-brand-500/10 dark:text-brand-300',
};

const DOT_CLASS: Record<BadgeTone, string> = {
  success: 'bg-success-500',
  danger: 'bg-danger-500',
  warning: 'bg-warning-500',
  info: 'bg-info-500',
  neutral: 'bg-neutral-500',
  brand: 'bg-brand-500',
};

export interface StatusBadgeProps {
  tone?: BadgeTone;
  children: ReactNode;
  showDot?: boolean;
  title?: string;
}

export function StatusBadge({ tone = 'neutral', children, showDot = true, title }: StatusBadgeProps) {
  return (
    <span
      title={title}
      data-badge-tone={tone}
      className={`inline-flex items-center gap-1.5 rounded-pill border px-2 py-0.5 text-[11px] font-medium whitespace-nowrap ${TONE_CLASS[tone]}`}
    >
      {showDot ? (
        <span aria-hidden className={`size-1.5 rounded-full ${DOT_CLASS[tone]}`} />
      ) : null}
      {children}
    </span>
  );
}
