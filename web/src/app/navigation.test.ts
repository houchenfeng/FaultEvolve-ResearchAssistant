import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { describe, expect, it } from 'vitest';

import { NAV_MODULES, resolveActiveModule } from '@/app/navigation';

describe('一级导航（PRD 5.1 / TODO 3.2）', () => {
  it('严格只有四项，且顺序与文案固定', () => {
    expect(NAV_MODULES).toHaveLength(4);
    expect(NAV_MODULES.map((module) => module.id)).toEqual([
      'overview',
      'workbench',
      'knowledge',
      'results',
    ]);
    expect(NAV_MODULES.map((module) => module.label)).toEqual([
      '总览',
      '进化工作台',
      '知识发现',
      '结果与报告',
    ]);
  });

  it('与 engine-catalog.json 保持一致，防止契约漂移', () => {
    // vitest 下的 import.meta.url 不是 file: scheme，所以用工作目录解析。
    const catalogPath = resolve(process.cwd(), 'openapi/engine-catalog.json');
    const catalog = JSON.parse(readFileSync(catalogPath, 'utf-8')) as {
      nav_modules: string[];
      nav_module_labels_zh: Record<string, string>;
    };

    expect(catalog.nav_modules).toEqual(NAV_MODULES.map((module) => module.id));
    for (const module of NAV_MODULES) {
      expect(catalog.nav_module_labels_zh[module.id]).toBe(module.label);
    }
  });
});

describe('resolveActiveModule', () => {
  it.each([
    ['/', 'overview'],
    ['/overview/tasks/t1', 'overview'],
    ['/runs/new', 'overview'],
    ['/runs/abc', 'workbench'],
    ['/runs/abc/', 'workbench'],
    ['/runs/abc/tree', 'workbench'],
    ['/runs/abc/timeline', 'workbench'],
    ['/runs/abc/knowledge', 'knowledge'],
    ['/runs/abc/results', 'results'],
    ['/runs/abc/audit', 'results'],
    ['/compare', 'results'],
  ])('%s → %s', (pathname, expected) => {
    expect(resolveActiveModule(pathname)).toBe(expected);
  });

  it('未知路径不高亮任何模块', () => {
    expect(resolveActiveModule('/nope')).toBeNull();
  });

  it('深链接不产生新的侧栏项（树/时间轴仍属工作台）', () => {
    expect(resolveActiveModule('/runs/abc/tree')).toBe('workbench');
    const ids: string[] = NAV_MODULES.map((module) => module.id);
    expect(ids).not.toContain('tree');
    expect(ids).not.toContain('timeline');
    expect(ids).not.toContain('settings');
  });
});
