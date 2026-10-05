/**
 * 设置抽屉（TODO 3.2 / PRD 14）。
 *
 * 关键约束：设置**不占左侧栏**，只从顶部齿轮打开。
 * 阶段 3 只有「外观」是真实可用的；Qwen 与服务状态如实标注「未接入」，
 * 因为后端尚未提供对应字段（不写假实现，TODO 15）。
 */
import { useEffect } from 'react';

import { useUiStore } from '@/stores/ui-store';

export interface SettingsDrawerProps {
  open: boolean;
  onClose: () => void;
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="border-b border-border-subtle px-4 py-4 last:border-b-0">
      <h3 className="mb-2 text-xs font-semibold tracking-wide text-fg-muted">{title}</h3>
      {children}
    </section>
  );
}

function NotYet({ what }: { what: string }) {
  return (
    <p className="rounded-card border border-dashed border-border-subtle px-3 py-2 text-xs text-fg-subtle">
      {what} 尚未接入后端，本阶段不可配置。
    </p>
  );
}

export function SettingsDrawer({ open, onClose }: SettingsDrawerProps) {
  const theme = useUiStore((state) => state.theme);
  const setTheme = useUiStore((state) => state.setTheme);

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
    <div className="fixed inset-0 z-50 flex justify-end">
      <button
        type="button"
        aria-label="关闭设置"
        onClick={onClose}
        className="absolute inset-0 bg-[var(--fe-overlay)]"
      />
      <aside
        role="dialog"
        aria-modal="true"
        aria-label="设置"
        className="relative flex w-80 max-w-[85vw] flex-col overflow-y-auto bg-surface shadow-pop"
      >
        <div className="flex items-center justify-between border-b border-border-subtle px-4 py-3">
          <h2 className="text-sm font-semibold text-fg">设置</h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="关闭"
            className="fe-btn fe-btn-ghost fe-btn-sm px-2 py-1"
          >
            关闭
          </button>
        </div>

        <Section title="外观与演示">
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setTheme('light')}
              aria-pressed={theme === 'light'}
              className={`flex-1 rounded-card border px-3 py-1.5 text-xs ${theme === 'light' ? 'border-brand-500 bg-brand-50 font-medium text-brand-600 dark:bg-brand-500/10' : 'border-border-subtle text-fg-muted hover:bg-surface-muted'}`}
            >
              浅色
            </button>
            <button
              type="button"
              onClick={() => setTheme('dark')}
              aria-pressed={theme === 'dark'}
              className={`flex-1 rounded-card border px-3 py-1.5 text-xs ${theme === 'dark' ? 'border-brand-500 bg-brand-50 font-medium text-brand-600 dark:bg-brand-500/10' : 'border-border-subtle text-fg-muted hover:bg-surface-muted'}`}
            >
              深色
            </button>
          </div>
          <p className="mt-2 text-[11px] text-fg-subtle">
            主题切换不会改变图表颜色语义（PRD 14.3）。
          </p>
        </Section>

        <Section title="Qwen 设置">
          <p className="rounded-card border border-dashed border-border-subtle px-3 py-2 text-xs text-fg-subtle">
            模型、Base URL 和 API Key 不能在这里修改。是否连通看顶部徽章，那是后端对模型列表的请求结果。
          </p>
        </Section>

        <Section title="服务状态">
          <NotYet what="Web API / 引擎 / Qwen / 执行器 / SQLite 的实时健康检查" />
        </Section>
      </aside>
    </div>
  );
}
