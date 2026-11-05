import { test, expect } from '@playwright/test';

/**
 * E2E-01：运行回放（TODO §12.4）。
 *
 * 总览 → 最近运行「查看证据」→ 树 → 节点 → 知识发现 → 结果与报告。
 *
 * 走的是一份**历史单树运行**（目录名里的 showcase 是历史遗留，见
 * `scripts/e2e_serve.py` 的 `LEGACY_SINGLE_TREE_RUN_ID`）：它的 21 节点树
 * 能撑起树页与节点抽屉，而单岛形态又要求页面替它补出「没有岛记账」的说明。
 * 三岛形态另在 `visual-regression.spec.ts` 里拍。
 */

const REPLAY_RUN_ID = 'hdd_mvp_showcase_c89e2a01';

test.describe('E2E-01：运行回放', () => {
  test('总览 → 回放 → 树 → 节点 → 知识发现 → 报告', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByRole('heading', { name: '任务中心' })).toBeVisible();

    const navItems = page.locator('aside[aria-label="主导航"] [data-nav-item]');
    await expect(navItems).toHaveCount(4);

    // 从运行列表进去。总览按 API 返回的**全部**运行成行（D6.4），
    // 所以先定位到这一行再点，避免依赖行序。
    const row = page.getByRole('row', { name: new RegExp(REPLAY_RUN_ID) });
    await expect(row).toBeVisible();
    await row.getByRole('button', { name: '查看证据' }).click();
    await page.waitForURL(`**/runs/${REPLAY_RUN_ID}`);
    await expect(page.getByRole('heading', { name: '进化工作台' })).toBeVisible();

    await page.getByRole('link', { name: '进化树' }).click();
    await page.waitForURL(`**/runs/${REPLAY_RUN_ID}/tree`);
    await expect(page.locator('[data-testid="tree-canvas"]')).toBeVisible();
    const nodes = page.locator('.react-flow__node');
    await expect(nodes.first()).toBeVisible({ timeout: 20_000 });
    expect(await nodes.count()).toBeGreaterThan(0);

    await nodes.first().click();
    const drawer = page.locator('[data-testid="node-drawer"]');
    await expect(drawer).toBeVisible({ timeout: 20_000 });
    await expect(drawer.getByText(/代码|diff|Code/i).first()).toBeVisible();

    await page.getByRole('link', { name: '知识发现' }).click();
    await page.waitForURL(`**/runs/${REPLAY_RUN_ID}/knowledge`);
    await expect(page.getByRole('heading', { name: '知识发现' })).toBeVisible();

    await page.getByRole('link', { name: '结果与报告' }).click();
    await page.waitForURL(`**/runs/${REPLAY_RUN_ID}/results`);
    await expect(page.getByRole('heading', { name: '结果与报告' })).toBeVisible();

    await expect(page.locator('[role="alert"]')).toHaveCount(0);
  });
});
