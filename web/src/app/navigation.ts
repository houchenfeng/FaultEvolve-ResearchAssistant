/**
 * 一级导航的单一事实来源。
 *
 * PRD 5.1：左侧栏**严格只有四项**，不在侧栏追加设置、终端、系统状态、帮助
 * 或二级页面。TODO 3.2 要求测试断言"只有四项"。
 * 标签取值与 `web/openapi/engine-catalog.json` 的 `nav_module_labels_zh` 一致，
 * 并由 `navigation.test.ts` 断言二者不会漂移。
 */
export type NavModuleId = 'overview' | 'workbench' | 'knowledge' | 'results';

export interface NavModule {
  id: NavModuleId;
  label: string;
  /** 是否必须先选定一个运行才能进入。 */
  requiresRun: boolean;
}

export const NAV_MODULES: readonly NavModule[] = [
  { id: 'overview', label: '总览', requiresRun: false },
  { id: 'workbench', label: '进化工作台', requiresRun: true },
  { id: 'knowledge', label: '知识发现', requiresRun: true },
  { id: 'results', label: '结果与报告', requiresRun: true },
] as const;

/**
 * 由当前 pathname 解析出高亮的一级模块。
 *
 * 运行内部的树 / 时间轴 / 审计都是**深链接**（PRD 5.2），
 * 它们高亮所属的一级模块，但不在侧栏形成新入口。
 */
export function resolveActiveModule(pathname: string): NavModuleId | null {
  const path = pathname.replace(/\/+$/, '') || '/';

  if (path === '/' || path.startsWith('/overview')) return 'overview';
  if (path === '/runs/new') return 'overview';

  const runScoped = /^\/runs\/([^/]+)(\/.*)?$/.exec(path);
  if (runScoped) {
    const section = (runScoped[2] ?? '').replace(/^\//, '');
    if (section === 'knowledge') return 'knowledge';
    if (section === 'results' || section === 'audit') return 'results';
    return 'workbench';
  }

  if (path === '/compare') return 'results';

  return null;
}
