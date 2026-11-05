import { test, expect } from '@playwright/test';

/**
 * E2E-04：错误恢复（TODO §12.4）。
 *
 * 1. 使用故意失败候选
 * 2. 查看失败原因
 * 3. 查看 repair 关联
 * 4. 刷新页面
 * 5. 状态保持一致
 *
 * 数据来自 `scripts/make_failure_fixture.py` 合成的 ``hdd_mvp_faildemo_4b81c0d2``：
 * mock 通路不产失败候选，已入库的 demo 运行六个节点全是 done，拿它验错误恢复
 * 等于没验。这份运行有两个失败候选，一条被修好、一条修复耗尽。
 *
 * **第 3 步是这条用例真正要守的东西**：引擎把 `repair_count` /
 * `repair_exhausted` 写在**被修的失败节点**上（`engine.py:2009` /
 * `engine.py:2006`），而 `repair_parent_id` 指针在修复节点身上。抽屉如果只盯
 * 当前节点读，这两处就恒显示不出来 —— 修好之前这条用例是红的。
 */

const FAIL_RUN_ID = 'hdd_mvp_faildemo_4b81c0d2';
/** 超时，三次修复都没过，链根标记 exhausted。 */
const FAILED_B = 'fa11ed02';
const REPAIR_B = 'f1xed002';
/** 沙箱参数错，被修好了（第 3c 步：重试 1 次、没耗尽）。 */
const REPAIR_A = 'f1xed001';

test.describe('E2E-04：错误恢复', () => {
  test('失败候选 → 失败原因 → repair 关联 → 刷新后一致', async ({ page }) => {
    const treeUrl = `/runs/${FAIL_RUN_ID}/tree`;

    // 1. 打开这份「故意失败」的运行，树上应当有全部五个节点。
    await page.goto(treeUrl);
    await expect(page.locator('[data-testid="tree-canvas"]')).toBeVisible();
    const cards = page.locator('.react-flow__node');
    await expect(cards.first()).toBeVisible({ timeout: 20_000 });
    await expect(cards).toHaveCount(5);
    await expect(page.locator(`[data-testid="tree-node-${FAILED_B}"]`)).toBeVisible();

    // 2. 点失败节点看失败原因：概览给错误分类，指标给 evaluator 的原话。
    await page.locator(`[data-testid="tree-node-${FAILED_B}"]`).click();
    const drawer = page.locator('[data-testid="node-drawer"]');
    await expect(drawer).toBeVisible({ timeout: 20_000 });
    await drawer.getByRole('button', { name: '概览' }).click();
    await expect(drawer.getByText('错误分类')).toBeVisible();
    await expect(drawer.getByText('timeout', { exact: true })).toBeVisible();

    await drawer.getByRole('button', { name: '指标' }).click();
    const reason = drawer.getByText(/900s 预算内未写出 pred\.csv/);
    await expect(reason).toBeVisible();
    const reasonText = (await reason.textContent()) ?? '';

    // 3. 看 repair 关联：修复节点上写着它修的是谁、重试了几次、有没有耗尽。
    //    切回「概览」是必须的 —— 抽屉不会因换节点而重挂载，标签页会留在上一步。
    await page.locator(`[data-testid="tree-node-${REPAIR_B}"]`).click();
    await expect(drawer).toBeVisible({ timeout: 20_000 });
    await drawer.getByRole('button', { name: '概览' }).click();
    await expect(drawer.getByText('修复来源')).toBeVisible();
    // 这两个数字来自**被修的** fa11ed02，不是修复节点自己（它身上是 0 / false）。
    await expect(drawer.getByText(/重试 3 次/)).toBeVisible();
    await expect(drawer.getByText(/已耗尽/)).toBeVisible();

    // 3b. 点「修复来源」能跳回失败节点 —— 关联是能用的，不只是一行文字。
    await drawer.getByRole('button', { name: FAILED_B }).click();
    await expect(drawer).toBeVisible();
    await drawer.getByRole('button', { name: '概览' }).click();
    await expect(drawer.getByText('timeout', { exact: true })).toBeVisible();

    // 3c. 另一条链是修好了的：重试 1 次、没有耗尽。
    await page.locator(`[data-testid="tree-node-${REPAIR_A}"]`).click();
    await drawer.getByRole('button', { name: '概览' }).click();
    await expect(drawer.getByText(`（重试 1 次）`)).toBeVisible();
    await expect(drawer.getByText(/已耗尽/)).toHaveCount(0);

    // 4-5. 刷新后状态一致。
    //
    //    注意这里**不**断言抽屉还在：URL 是唯一事实来源，RunLayout 进入时
    //    `resetRunView()` 会清掉选中节点（`ui-store` 里 `setCurrentRunId` 也
    //    顺带重置），所以刷新后抽屉是关的 —— 那是设计，不是 bug。
    //    「状态保持一致」指的是**同一份数据**：重新点同一个节点，失败原因与
    //    修复关联跟刷新前逐字相同。
    await page.reload();
    await expect(page.locator('[data-testid="tree-canvas"]')).toBeVisible();
    await expect(page.locator('.react-flow__node')).toHaveCount(5);
    await expect(page.locator('[data-testid="node-drawer"]')).toHaveCount(0);

    await page.locator(`[data-testid="tree-node-${FAILED_B}"]`).click();
    await expect(drawer).toBeVisible({ timeout: 20_000 });
    await drawer.getByRole('button', { name: '指标' }).click();
    await expect(drawer.getByText(reasonText)).toBeVisible();

    await page.locator(`[data-testid="tree-node-${REPAIR_B}"]`).click();
    await drawer.getByRole('button', { name: '概览' }).click();
    await expect(drawer.getByText(/重试 3 次/)).toBeVisible();
    await expect(drawer.getByText(/已耗尽/)).toBeVisible();

    // 全程不该冒出未处理的错误面板（ApiErrorPanel 渲染成 role="alert"）。
    await expect(page.locator('[role="alert"]')).toHaveCount(0);
  });
});
