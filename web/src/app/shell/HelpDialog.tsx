/**
 * 帮助弹窗（TODO 3.2 / PRD 5.1）。
 *
 * PRD 明确：帮助与演示说明放在页面右上角帮助弹窗中，**不进入左侧栏**。
 */
import { useEffect } from 'react';

const MODULES: { name: string; question: string }[] = [
  { name: '总览', question: '我要用什么任务、数据和环境开始一次进化？' },
  { name: '进化工作台', question: '算法正在怎样进化，为什么选择或淘汰某个节点？' },
  { name: '知识发现', question: '系统发现了什么新知识，这些知识经得起证伪吗？' },
  { name: '结果与报告', question: '最终得到什么算法、证据和可交付制品？' },
];

export interface HelpDialogProps {
  open: boolean;
  onClose: () => void;
}

export function HelpDialog({ open, onClose }: HelpDialogProps) {
  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 grid place-items-center p-4">
      <button
        type="button"
        aria-label="关闭帮助"
        onClick={onClose}
        className="absolute inset-0 bg-[var(--fe-overlay)]"
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-label="帮助"
        className="relative w-full max-w-lg overflow-hidden rounded-panel bg-surface shadow-pop"
      >
        <div className="flex items-center justify-between border-b border-border-subtle px-4 py-3">
          <h2 className="text-sm font-semibold text-fg">帮助</h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="关闭"
            className="fe-btn fe-btn-ghost fe-btn-sm px-2 py-1"
          >
            关闭
          </button>
        </div>

        <div className="px-4 py-4">
          <p className="text-xs text-fg-muted">本产品固定四个一级模块：</p>
          <ul className="mt-2 flex flex-col gap-1.5">
            {MODULES.map((module) => (
              <li key={module.name} className="text-xs">
                <span className="font-medium text-fg">{module.name}</span>
                <span className="text-fg-muted"> — {module.question}</span>
              </li>
            ))}
          </ul>

          <div className="mt-4 fe-card bg-surface-muted p-3 text-[11px] text-fg-muted">
            <p className="font-medium text-fg">关于评分</p>
            <p className="mt-1">
              所有分数只来自引擎的 evaluator，前端只展示、不重算；缺失的字段显示为「未记录」，不会用
              0 冒充。
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
