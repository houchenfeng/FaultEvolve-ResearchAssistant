/**
 * 左侧一级导航栏（TODO 3.2 / PRD 5.1）。
 *
 * 严格四项；设置、系统状态、帮助一律不放这里（它们在顶部栏）。
 * 需要 run 的模块在没有当前运行时降级为提示按钮，点击回总览去选运行。
 */
import { Link, useRouterState } from '@tanstack/react-router';
import { useState } from 'react';

import type { NavModule, NavModuleId } from '@/app/navigation';
import { NAV_MODULES, resolveActiveModule } from '@/app/navigation';
import { SettingsDrawer } from '@/app/shell/SettingsDrawer';
import { cn } from '@/lib/cn';
import { useUiStore } from '@/stores/ui-store';

function ModuleIcon({ id }: { id: NavModuleId }) {
  const common = {
    width: 16,
    height: 16,
    viewBox: '0 0 24 24',
    fill: 'none',
    stroke: 'currentColor',
    strokeWidth: 1.8,
    strokeLinecap: 'round' as const,
    strokeLinejoin: 'round' as const,
    'aria-hidden': true,
    className: 'fe-icon-wrap shrink-0',
  };
  switch (id) {
    case 'overview':
      return (
        <svg {...common}>
          <rect x="3" y="3" width="7" height="9" rx="1.5" />
          <rect x="14" y="3" width="7" height="5" rx="1.5" />
          <rect x="14" y="12" width="7" height="9" rx="1.5" />
          <rect x="3" y="16" width="7" height="5" rx="1.5" />
        </svg>
      );
    case 'workbench':
      return (
        <svg {...common}>
          <circle cx="6" cy="6" r="2.5" />
          <circle cx="18" cy="9" r="2.5" />
          <circle cx="10" cy="18" r="2.5" />
          <path d="M8 7.5 15.6 8.6M7.2 8.3 9 15.6M16.4 10.8 11.6 16.4" />
        </svg>
      );
    case 'knowledge':
      return (
        <svg {...common}>
          <path d="M12 3a6 6 0 0 0-3.6 10.8c.5.4.9 1 1.7h5.2c.1-.7.5-1.3 1-1.7A6 6 0 0 0 12 3Z" />
          <path d="M10 19h4M10.6 21.5h2.8" />
        </svg>
      );
    case 'results':
      return (
        <svg {...common}>
          <path d="M5 20V10M12 20V4M19 20v-6" />
        </svg>
      );
  }
}

function itemClassName(isActive: boolean): string {
  return cn('fe-nav-item group', isActive ? 'fe-nav-item-active' : 'fe-nav-item-idle');
}

function renderItem(module: NavModule, isActive: boolean, currentRunId: string | null) {
  const content = (
    <>
      <ModuleIcon id={module.id} />
      <span>{module.label}</span>
    </>
  );

  if (!module.requiresRun) {
    return (
      <Link to="/" className={itemClassName(isActive)} data-nav-item={module.id}>
        {content}
      </Link>
    );
  }

  if (!currentRunId) {
    return (
      <Link
        to="/"
        data-nav-item={module.id}
        data-nav-disabled="true"
        title={`请先在「总览」中选择一个运行，再进入${module.label}`}
        className={cn(itemClassName(false), 'opacity-60')}
      >
        {content}
      </Link>
    );
  }

  switch (module.id) {
    case 'workbench':
      return (
        <Link
          to="/runs/$runId"
          params={{ runId: currentRunId }}
          className={itemClassName(isActive)}
          data-nav-item={module.id}
        >
          {content}
        </Link>
      );
    case 'knowledge':
      return (
        <Link
          to="/runs/$runId/knowledge"
          params={{ runId: currentRunId }}
          className={itemClassName(isActive)}
          data-nav-item={module.id}
        >
          {content}
        </Link>
      );
    case 'results':
      return (
        <Link
          to="/runs/$runId/results"
          params={{ runId: currentRunId }}
          className={itemClassName(isActive)}
          data-nav-item={module.id}
        >
          {content}
        </Link>
      );
    default:
      return (
        <Link to="/" className={itemClassName(isActive)} data-nav-item={module.id}>
          {content}
        </Link>
      );
  }
}

export function RailNav() {
  const [settingsOpen, setSettingsOpen] = useState(false);
  const pathname = useRouterState({ select: (state) => state.location.pathname });
  const currentRunId = useUiStore((state) => state.currentRunId);
  const activeModule = resolveActiveModule(pathname);

  return (
    <aside className="fe-shell-nav flex w-52 shrink-0 flex-col" aria-label="主导航">
      <div className="flex items-center gap-2 px-4 py-4">
        <img src="/assets/faultevolve-icon.png" alt="" aria-hidden className="size-8 object-contain" />
        <span className="text-sm font-semibold tracking-tight text-fg">FaultEvolve</span>
      </div>

      <nav className="flex flex-col gap-1 px-2">
        {NAV_MODULES.map((module) => {
          const isActive = activeModule === module.id;
          return <div key={module.id}>{renderItem(module, isActive, currentRunId)}</div>;
        })}
      </nav>

      <div className="mx-3 mt-4 overflow-hidden rounded-lg border border-brand-200 bg-brand-50">
        <img src="/assets/faultevolve-hero-bg.png" alt="三岛算法演化与数据中心" className="h-20 w-full object-cover object-[75%_center] opacity-80" />
        <p className="border-t border-brand-200 bg-white/85 px-2.5 py-2 text-[10px] leading-4 text-fg-muted">HDD 故障预测<br/><strong className="text-brand-700">三岛协同自演化</strong></p>
      </div>

      <div className="mt-auto border-t border-border-subtle p-3">
        <div className="flex items-center gap-2 rounded-lg bg-surface-muted p-2"><div className="grid size-8 shrink-0 place-items-center rounded-full bg-gradient-to-br from-brand-500 to-success-500 text-xs font-semibold text-white">我</div><div className="min-w-0 flex-1"><p className="truncate text-xs font-semibold text-fg">我的账号</p><p className="truncate text-[9px] text-fg-subtle">FaultEvolve Workspace</p></div></div>
        <button type="button" onClick={()=>setSettingsOpen(true)} className="mt-2 flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-[11px] text-fg-muted hover:bg-surface-muted hover:text-fg"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden><circle cx="12" cy="12" r="3"/><path d="M19 12a7 7 0 0 0-.1-1l2-1.5-2-3.4-2.4 1a8 8 0 0 0-1.7-1L14.5 3h-5l-.4 3.1a8 8 0 0 0-1.7 1l-2.4-1-2 3.4L5.1 11a7 7 0 0 0 0 2L3 14.5l2 3.4 2.4-1a8 8 0 0 0 1.7 1l.4 3.1h5l.4-3.1a8 8 0 0 0 1.7-1l2.4 1 2-3.4-2.1-1.5a7 7 0 0 0 .1-1Z"/></svg>项目设置</button>
        <p className="mt-2 px-2 text-[9px] text-rail-fg-muted">边云协同 · 数据不出域</p>
      </div>
      <SettingsDrawer open={settingsOpen} onClose={()=>setSettingsOpen(false)} />
    </aside>
  );
}
