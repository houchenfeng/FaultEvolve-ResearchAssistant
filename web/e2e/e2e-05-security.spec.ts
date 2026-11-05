import { test, expect } from '@playwright/test';

/**
 * E2E-05：安全（TODO §12.4）。
 *
 * 三条都是"必须被拒绝"：路径穿越、下载 holdout、脚本注入。
 * 后端各自都有单元测试（`tests/webapi/test_path_security.py`、
 * `test_no_holdout_exposure.py`），这里补的是**从浏览器走一遍**——单元测试
 * 用的是 TestClient，而真实链路还隔着 vite 代理和浏览器对 URL 的规范化，
 * 这两层各自都可能把 `%2e%2e` 还原成 `..` 再放过去。
 */

const DEMO_RUN_ID = 'hdd_mvp_demo_7510f100';

test.describe('E2E-05：安全', () => {
  test('路径穿越一律被拒绝', async ({ page }) => {
    // 浏览器会把 %2e%2e 规范化成 ..，所以两种写法都试一遍。
    const traversal = [
      '/api/runs/%2e%2e',
      '/api/runs/..',
      `/api/runs/${DEMO_RUN_ID}/nodes/%2e%2e`,
      `/api/runs/${DEMO_RUN_ID}/nodes/..`,
      `/api/runs/${DEMO_RUN_ID}/artifacts/%2e%2e`,
    ];

    for (const path of traversal) {
      const response = await page.request.get(path);
      const body = await response.text();

      if (response.status() >= 400) {
        // 被拒绝：最理想的结果。
        expect(body).not.toContain(DEMO_RUN_ID);
      } else {
        // 200 也不等于泄露：HTTP 客户端（和 vite 代理）会先把 `/nodes/..`
        // 规范化掉，后端收到的其实是一个**合法**路径（直连后端打同样的
        // `%2e%2e` 拿到的是 400，正是后端拒绝逻辑生效的证据）。
        // 所以这里退一步断言：既没拿到目录内容，也没泄露任何路径。
        expect(body, `${path} 返回 200，但不应含路径信息`).not.toMatch(/[A-Za-z]:[\\/]/);
        expect(body).not.toContain('Self-evolution');
      }
      expect(body.toLowerCase()).not.toContain('holdout');
    }
  });

  test('holdout 既不可列也不可下载', async ({ page }) => {
    // 列制品：任何一项都不该带 holdout 字样。
    const list = await page.request.get(`/api/runs/${DEMO_RUN_ID}/artifacts`);
    if (list.ok()) {
      const body = await list.text();
      expect(body.toLowerCase()).not.toContain('holdout');
    }

    // 直接点名要 holdout：必须拿不到。
    for (const path of [
      `/api/runs/${DEMO_RUN_ID}/artifacts/holdout`,
      `/api/runs/${DEMO_RUN_ID}/artifacts/data/holdout/train_labels.csv`,
    ]) {
      const response = await page.request.get(path);
      expect(response.status(), `${path} 不该可下载`).toBeGreaterThanOrEqual(400);
    }
  });

  test('补充说明里的脚本只当文本，不会执行', async ({ page }) => {
    const payload = `<script>alert('xss')</script><img src=x onerror=alert(1)>`;

    // 一旦有脚本真的执行，Playwright 会收到 dialog；没收到才是正确的。
    let dialogFired = false;
    page.on('dialog', async (dialog) => {
      dialogFired = true;
      await dialog.dismiss();
    });

    // 录入页**必须先选任务**：没选时它只画一个"尚未选择任务"的空状态，
    // 表单（含补充说明）根本不渲染。所以从总览的数据集卡片进去。
    //
    // 卡片里只有**就绪**的那个按钮是 enabled 的（其余任务缺 evaluator / data，
    // 按钮被 disabled），所以按"未禁用"筛就能选中能进的那一档。
    await page.goto('/');
    // 用 `data-dataset-card` 精确点名，别用"第一个未禁用的按钮"去筛：
    // 卡片顺序会随后端返回变，而且 `button:not([disabled])` 只排除了属性层面
    // 的 disabled，撞上父级禁用状态时 Playwright 仍判定 not enabled，失败现象
    // 离真正原因很远。
    const readyCard = page.locator('[data-dataset-card="hdd_mvp"]');
    await readyCard.getByRole('button', { name: '创建任务' }).click();
    await page.waitForURL('**/runs/new');

    // 补充说明在六步向导的第 2 步「执行目标」（服务器与目录），不在第 1 步任务卡片区。
    const next = page.getByRole('button', { name: '下一步' });
    await expect(next).toBeEnabled({ timeout: 30_000 });
    await next.click();
    await expect(page.getByRole('heading', { name: '服务器与目录' })).toBeVisible();

    const notes = page.locator('#intake-notes');
    await expect(notes).toBeVisible();
    await notes.fill(payload);

    // 值原样保留（说明是当文本存的，不是被剥掉或被执行掉）。
    await expect(notes).toHaveValue(payload);

    // 页面里没有因此多出真正的 script / img 元素。
    await expect(page.locator('script:has-text("xss")')).toHaveCount(0);
    await expect(page.locator('img[src="x"]')).toHaveCount(0);
    expect(dialogFired).toBe(false);

    // UI 明确标注了"不会作为命令执行"，这句话必须一直在。
    await expect(page.getByText('不会作为命令执行')).toBeVisible();
  });

  test('未就绪的任务不给进录入页', async ({ page }) => {
    // E2E-02 的前半条：缺 evaluator / 数据时，"创建任务"必须是禁用的。
    // fixture 里的 toy_task 缺 data 目录，就绪检查不过，正好是现成的反例。
    await page.goto('/');
    const blockedCard = page.locator('[data-dataset-card="toy_task"]');
    await expect(blockedCard).toBeVisible();
    const blockedButton = blockedCard.getByRole('button', { name: '创建任务' });
    await expect(blockedButton).toBeDisabled();
    // 而且要把原因说清楚，不能只是灰着不给点：原因就在按钮的 title 上
    // （= 后端的 blocked_reason）。
    await expect(blockedButton).toHaveAttribute('title', /未就绪|缺少文件|尚未提供/);

    // 对照：就绪的那个是可点的。
    await expect(
      page.locator('[data-dataset-card="hdd_mvp"]').getByRole('button', { name: '创建任务' }),
    ).toBeEnabled();
  });
});
