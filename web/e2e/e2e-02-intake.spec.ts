import { test, expect } from '@playwright/test';

/**
 * E2E-02：自定义任务校验（TODO §12.4）。
 *
 * 原样五步是「创建自定义任务 → 缺 evaluator 不能继续 → 填有效 evaluator/init →
 * 服务器检查通过 → 选标准进化并启动 mock 运行」。**第一步在本仓做不到**，而且
 * 是设计上做不到，不是没实现：
 *
 * - 契约 1.5.0 里 `/api/tasks` 全是 GET，没有任何写端点；
 * - 录入页也因此不收自由路径 —— `NewRunPage` 在没有 taskId 时给的是
 *   EmptyState，明说"这里不提供自由输入路径"。
 *
 * 按 §15 的规矩（做不到就明确说明、UI 禁用并解释、不写假实现），这条用例
 * 把第一步验成"UI 如实说明做不到"，而不是伪造一个上传框去满足字面要求。
 * 第三步同理：三张必填卡展示的是**任务目录的实测就绪状态**，不是自由上传表单，
 * 所以"填写有效 evaluator/init"落成"选一个 evaluator/init 都齐的任务，三张卡
 * 都通过"。
 */

/** 由 `scripts/e2e_serve.py` 在 scratch 里现造：抄 toy_task 但不抄 evaluator.py。 */
const INCOMPLETE_TASK = 'toy_task_no_eval';
const READY_TASK = 'hdd_mvp';

test.describe('E2E-02：自定义任务校验', () => {
  test('无自由输入 → 缺 evaluator 被挡 → 就绪任务三卡通过 → 服务器可连 → 启动', async ({
    page,
  }) => {
    // 启动一个真实运行要几十秒，默认 30 s 不够。
    test.setTimeout(180_000);

    // 1. 创建自定义任务：做不到，而且 UI 如实说了。
    await page.goto('/runs/new');
    await expect(page.getByText('尚未选择任务')).toBeVisible();
    await expect(page.getByText(/不提供自由输入路径/)).toBeVisible();

    // 2. 缺 evaluator 的任务：入口按钮禁用，原因挂在 title 上（不在正文里）。
    await page.goto('/');
    const brokenCard = page.locator(`[data-dataset-card="${INCOMPLETE_TASK}"]`);
    await expect(brokenCard).toBeVisible();
    const brokenButton = brokenCard.getByRole('button', { name: '创建任务' });
    await expect(brokenButton).toBeDisabled();
    await expect(brokenButton).toHaveAttribute('title', /缺少文件：evaluator\.py/);

    // 3. 就绪任务：三张必填卡（数据集 / evaluator / 初始算法）全部「通过」。
    //    用 `data-card-state` 而不是颜色或文案位置 —— 五态徽章的状态是唯一事实。
    //    卡片在六步流程的第 1 步；服务器、强度和启动分属后面的步骤。
    await page
      .locator(`[data-dataset-card="${READY_TASK}"]`)
      .getByRole('button', { name: '创建任务' })
      .click();
    await page.waitForURL('**/runs/new');
    for (const cardId of ['dataset', 'evaluator', 'init']) {
      await expect(page.locator(`[data-artifact-card="${cardId}"] [data-card-state]`)).toHaveAttribute(
        'data-card-state',
        'pass',
        { timeout: 30_000 },
      );
    }

    async function advanceUntil(target: ReturnType<typeof page.locator>) {
      const next = page.getByRole('button', { name: '下一步' });
      for (let i = 0; i < 6; i += 1) {
        if (await target.isVisible()) return;
        await expect(next).toBeEnabled({ timeout: 60_000 });
        await next.click();
      }
      await expect(target).toBeVisible();
    }

    // 4. 服务器检查：默认执行目标是本机，探测结果有 `data-probe-result`。
    await advanceUntil(page.getByRole('button', { name: '本机（local_cloud）' }));
    await page.getByRole('button', { name: '本机（local_cloud）' }).click();
    await page.getByRole('button', { name: '测试连接' }).click();
    await expect(page.locator('[data-probe-result="reachable"]')).toBeVisible({
      timeout: 60_000,
    });

    // 5. 选「标准进化」，到最后一步再勾选 mock LLM 并启动。
    //    POST 是 202，只要跳到运行页即可，不必等它跑完（跑完是 E2E-03 的事）。
    await advanceUntil(page.locator('input[name="preset"][value="standard"]'));
    await page.locator('input[name="preset"][value="standard"]').check();
    await advanceUntil(page.locator('[data-mock-llm="true"]'));
    await page.locator('[data-mock-llm="true"]').check();
    await page.getByRole('button', { name: '启动运行' }).click();

    // ⚠️ 不能用 `/\/runs\/[^/]+$/`：我们**现在就站在** `/runs/new`，那个模式
    // 立刻匹配成功，拿到的"运行 id"会是字符串 `new`。这里显式排除 new。
    await page.waitForURL(/\/runs\/(?!new$)[^/]+$/, { timeout: 60_000 });
    const runId = page.url().split('/').pop() ?? '';
    expect(runId).toBeTruthy();
    expect(runId).not.toBe('new');
    await expect(page.getByRole('heading', { name: '进化工作台' })).toBeVisible();

    // 全程不该冒出未处理的错误面板（ApiErrorPanel 渲染成 role="alert"）。
    await expect(page.locator('[role="alert"]')).toHaveCount(0);

    // 这里验的是「能不能启动」，不是「能不能跑完」—— 跑完是 E2E-03 的事。
    // standard 档要跑 20 轮，放着不管它会一直占着后端子进程，跟后面的
    // E2E-03 抢 CPU，让那边的超时假红。所以这里直接取消掉（取消本身也是
    // 一条要验的路径：停止运行不得删掉已产出的东西）。
    const cancelled = await page.evaluate(async (id) => {
      const res = await fetch(`/api/runs/${id}/cancel`, { method: 'POST' });
      return { status: res.status, body: await res.text() };
    }, runId);
    expect(
      cancelled.status,
      `取消刚启动的运行：${cancelled.status} ${cancelled.body}`,
    ).toBeLessThan(300);
  });
});
