/**
 * 制品缺失提示（TODO 3.5）。
 *
 * 与 ApiErrorPanel 的区别：这里不是"请求失败"，而是**运行确实没有产出该制品**。
 * 依据 TODO 2.3 的读取规则，前端必须如实说明"没有"，不得伪造空结果。
 */
export interface MissingArtifactNoticeProps {
  /** 缺失的制品名，例如 `tree.json`。 */
  artifact: string;
  /** 为什么没有（例如"运行尚未进入该阶段"）。 */
  reason: string;
  /** 下一步建议。 */
  nextStep?: string;
  className?: string;
}

export function MissingArtifactNotice({
  artifact,
  reason,
  nextStep,
  className,
}: MissingArtifactNoticeProps) {
  return (
    <div
      role="status"
      data-artifact-state="missing"
      className={[
        'rounded-panel border border-warning-500/30 bg-warning-50 p-3 text-xs',
        'dark:border-warning-500/40 dark:bg-warning-500/10',
        className ?? '',
      ].join(' ')}
    >
      <p className="font-medium text-warning-700 dark:text-warning-500">
        该运行没有产出 <code className="font-mono">{artifact}</code>
      </p>
      <p className="mt-1 text-fg-muted">{reason}</p>
      {nextStep ? <p className="mt-0.5 text-fg-subtle">下一步：{nextStep}</p> : null}
    </div>
  );
}
