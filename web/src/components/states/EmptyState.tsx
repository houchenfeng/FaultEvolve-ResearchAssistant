/**
 * 统一空状态（TODO 3.5 / PRD 15.2）。
 *
 * 空状态必须说明「原因」和「下一步」，不能只显示一句"暂无数据"。
 */
import type { ReactNode } from 'react';

export interface EmptyStateProps {
  /** 一句话说明当前没有什么。 */
  title: string;
  /** 为什么是空的（必填：PRD 要求说明原因）。 */
  reason: string;
  /** 用户接下来可以做什么。 */
  nextStep?: string;
  /** 可选图标。 */
  icon?: ReactNode;
  /** 可选操作按钮。 */
  action?: ReactNode;
}

export function EmptyState({ title, reason, nextStep, icon, action }: EmptyStateProps) {
  return (
    <div
      role="status"
      className="flex flex-col items-center gap-2 rounded-panel border border-dashed border-border-subtle bg-surface px-6 py-12 text-center"
    >
      {icon ? <div className="text-fg-subtle">{icon}</div> : null}
      <p className="text-sm font-medium text-fg">{title}</p>
      <p className="max-w-md text-xs text-fg-muted">{reason}</p>
      {nextStep ? <p className="max-w-md text-xs text-fg-subtle">下一步：{nextStep}</p> : null}
      {action ? <div className="mt-2">{action}</div> : null}
    </div>
  );
}
