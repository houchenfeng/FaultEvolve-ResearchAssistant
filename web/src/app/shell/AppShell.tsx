/**
 * 应用外壳：左侧一级导航 + 顶部全局栏 + 主内容区。
 * `/demo` 是全屏路演页，自带顶栏，不套外壳。
 */
import { Outlet, useRouterState } from '@tanstack/react-router';

import { RailNav } from '@/app/shell/RailNav';
import { TopBar } from '@/app/shell/TopBar';

export function AppShell() {
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  if (pathname.startsWith('/demo')) return <Outlet />;

  return (
    <div className="flex h-full">
      <RailNav />
      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar />
        <main className="min-h-0 flex-1 overflow-auto p-5">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
