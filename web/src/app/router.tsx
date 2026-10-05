/**
 * 路由树（代码式，非文件式）。
 *
 * 路由集合以 PRD 5.2 为准。注意：
 *  - 侧栏只有四项，树 / 时间轴 / 审计是**运行内部的深链接**，不构成导航项；
 *  - `/runs/new` 是静态段，优先级高于 `/runs/$runId`。
 */
import type { RouterHistory } from '@tanstack/react-router';
import { createRootRoute, createRoute, createRouter } from '@tanstack/react-router';

import { AppShell } from '@/app/shell/AppShell';
import { ComparePage } from '@/routes/ComparePage';
import { NewRunPage } from '@/routes/NewRunPage';
import { NotFoundPage } from '@/routes/NotFoundPage';
import { OverviewPage } from '@/routes/OverviewPage';
import { RunAuditPage } from '@/routes/RunAuditPage';
import { RunKnowledgePage } from '@/routes/RunKnowledgePage';
import { RunLayout } from '@/routes/RunLayout';
import { RunResultsPage } from '@/routes/RunResultsPage';
import { RunTimelinePage } from '@/routes/RunTimelinePage';
import { RunTreePage } from '@/routes/RunTreePage';
import { RunWorkbenchPage } from '@/routes/RunWorkbenchPage';
import { TaskDetailPage } from '@/routes/TaskDetailPage';

function buildRouteTree() {
  const rootRoute = createRootRoute({
    component: AppShell,
    notFoundComponent: NotFoundPage,
  });

  // 总览模块
  const indexRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: '/',
    component: OverviewPage,
  });
  const taskDetailRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: '/overview/tasks/$taskId',
    component: TaskDetailPage,
  });
  const newRunRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: '/runs/new',
    component: NewRunPage,
  });

  // 运行作用域（工作台 / 知识发现 / 结果 / 审计都是它的深链接）
  const runRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: '/runs/$runId',
    component: RunLayout,
  });
  const runIndexRoute = createRoute({
    getParentRoute: () => runRoute,
    path: '/',
    component: RunWorkbenchPage,
  });
  const runTreeRoute = createRoute({
    getParentRoute: () => runRoute,
    path: 'tree',
    component: RunTreePage,
  });
  const runTimelineRoute = createRoute({
    getParentRoute: () => runRoute,
    path: 'timeline',
    component: RunTimelinePage,
  });
  const runKnowledgeRoute = createRoute({
    getParentRoute: () => runRoute,
    path: 'knowledge',
    component: RunKnowledgePage,
  });
  const runResultsRoute = createRoute({
    getParentRoute: () => runRoute,
    path: 'results',
    component: RunResultsPage,
  });
  const runAuditRoute = createRoute({
    getParentRoute: () => runRoute,
    path: 'audit',
    component: RunAuditPage,
  });

  const compareRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: '/compare',
    component: ComparePage,
  });

  return rootRoute.addChildren([
    indexRoute,
    taskDetailRoute,
    newRunRoute,
    compareRoute,
    runRoute.addChildren([
      runIndexRoute,
      runTreeRoute,
      runTimelineRoute,
      runKnowledgeRoute,
      runResultsRoute,
      runAuditRoute,
    ]),
  ]);
}

/** 每次调用都新建路由树，便于测试注入 memory history。 */
export function createAppRouter(options?: { history?: RouterHistory }) {
  return createRouter({
    routeTree: buildRouteTree(),
    defaultPreload: 'intent',
    ...options,
  });
}

export const router = createAppRouter();

declare module '@tanstack/react-router' {
  interface Register {
    router: typeof router;
  }
}
