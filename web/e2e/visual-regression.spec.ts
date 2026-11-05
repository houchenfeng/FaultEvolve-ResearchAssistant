import { test, expect, type Page } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { join } from 'node:path';

/**
 * 视觉回归（TODO §12.5）。
 *
 * 三个固定视口 × 明暗两套主题 × 七个画面，每个画面都截图，并且**除了截图之外
 * 还跑硬断言** —— 只有截图的话，"多了个导航项""横向溢出""文字被截断"这类退化
 * 根本不会让用例变红，得靠人一张张翻。
 *
 * 截图落在 `test-results/visual/`（已在 .gitignore 里），**不做像素基线**。
 * 理由：基线 PNG 要进仓库才有用，而字体渲染在不同机器上必然不同，基线一进
 * 仓库就把"换个机器跑"变成"全红"。这里改成：结构性退化由断言拦住（可合并门禁），
 * 观感由截图给人看（人工验收）。
 */

/**
 * 历史单树运行：21 节点 / 6 层 / 含交叉与修复链 / 四档显著性齐全。
 *
 * 目录名里的 `showcase` 是历史遗留（专用展示页已按 D6.5 删除），现在它只是
 * 一份由通用页面回放的旧单岛运行。树形态的断言必须用它：三岛那份每岛只有
 * 7 个节点、层数撑不起分层带与显著性四档的画面。
 */
const SINGLE_TREE_RUN_ID = 'hdd_mvp_showcase_c89e2a01';
/** 三岛运行：3 岛 × 7 节点，含摘要交换与跨岛嫁接边（S6/D6.4 的展示对象）。 */
const ISLANDS_RUN_ID = 'hdd_mvp_islands_15l4nd01';
/** 合成运行：discovery 全是空表，用来拍「空状态」。 */
const EMPTY_RUN_ID = 'hdd_mvp_faildemo_4b81c0d2';

const VIEWPORTS = [
  { name: '1440x900', width: 1440, height: 900 },
  { name: '1920x1080', width: 1920, height: 1080 },
  { name: '1024x768', width: 1024, height: 768 },
] as const;

const THEMES = [
  { name: 'light', label: '浅色' },
  { name: 'dark', label: '深色' },
] as const;

interface Screen {
  id: string;
  /** 打开这个画面。 */
  open: (page: Page) => Promise<void>;
  /** 该画面必然出现的东西（可访问性树里的名字）。 */
  expectHeading?: string;
  /** 侧栏在这个画面上是否存在。404 之类的整页错误没有侧栏。 */
  hasSidebar: boolean;
  /** 这个画面**故意**要显示错误面板（拍错误状态）。 */
  expectsAlert?: boolean;
}

const SCREENS: Screen[] = [
  {
    id: 'overview',
    open: async (page) => {
      await page.goto('/');
    },
    hasSidebar: true,
  },
  {
    id: 'tree',
    open: async (page) => {
      await page.goto(`/runs/${SINGLE_TREE_RUN_ID}/tree`);
      await expect(page.locator('[data-testid="tree-canvas"]')).toBeVisible({
        timeout: 20_000,
      });
      // 这一屏没有 h1：画布就是整页内容，标题只在侧栏的导航项上。
      // 所以这里验画布而非标题（见下方 expectHeading 的注释）。
    },
    hasSidebar: true,
  },
  {
    id: 'node-detail',
    open: async (page) => {
      await page.goto(`/runs/${SINGLE_TREE_RUN_ID}/tree`);
      const node = page.locator('.react-flow__node').first();
      await expect(node).toBeVisible({ timeout: 20_000 });
      await node.click();
      await expect(page.locator('[data-testid="node-drawer"]')).toBeVisible({
        timeout: 20_000,
      });
    },
    hasSidebar: true,
  },
  {
    // D6.4 画面之一：三岛的岛卡 + 交换计数 + 全局最优落在哪个岛。
    id: 'islands-overview',
    open: async (page) => {
      await page.goto(`/runs/${ISLANDS_RUN_ID}`);
      await expect(page.getByRole('heading', { name: '进化工作台' })).toBeVisible({
        timeout: 20_000,
      });
      await page.locator('[data-panel="islands"]').click();
      await expect(page.locator('[data-testid="island-overview"]')).toBeVisible({
        timeout: 20_000,
      });
    },
    hasSidebar: true,
  },
  {
    // D6.4 画面之一：并列三岛的树（岛筛选芯片默认不选，三岛同屏）。
    id: 'island-tree',
    open: async (page) => {
      await page.goto(`/runs/${ISLANDS_RUN_ID}/tree`);
      await expect(page.locator('[data-testid="tree-canvas"]')).toBeVisible({
        timeout: 20_000,
      });
      await expect(page.locator('.react-flow__node').first()).toBeVisible({
        timeout: 20_000,
      });
    },
    hasSidebar: true,
  },
  {
    // D6.4 画面之一：摘要交换详情（发布/投递/拒绝/采用各算各的）。
    id: 'exchange-detail',
    open: async (page) => {
      await page.goto(`/runs/${ISLANDS_RUN_ID}`);
      await expect(page.getByRole('heading', { name: '进化工作台' })).toBeVisible({
        timeout: 20_000,
      });
      await page.locator('[data-panel="exchange"]').click();
      await expect(page.locator('[data-testid="exchange-panel"]')).toBeVisible({
        timeout: 20_000,
      });
    },
    hasSidebar: true,
  },
  {
    id: 'knowledge',
    open: async (page) => {
      await page.goto(`/runs/${SINGLE_TREE_RUN_ID}/knowledge`);
    },
    expectHeading: '知识发现',
    hasSidebar: true,
  },
  {
    id: 'results',
    open: async (page) => {
      await page.goto(`/runs/${SINGLE_TREE_RUN_ID}/results`);
    },
    expectHeading: '结果与报告',
    hasSidebar: true,
  },
  {
    id: 'empty-state',
    open: async (page) => {
      // 这份合成运行没有知识卡，知识页必然走空状态分支。
      await page.goto(`/runs/${EMPTY_RUN_ID}/knowledge`);
    },
    expectHeading: '知识发现',
    hasSidebar: true,
  },
  {
    id: 'error-state',
    open: async (page) => {
      await page.goto('/runs/definitely-not-a-run');
    },
    hasSidebar: false,
    expectsAlert: true,
  },
];

async function setTheme(page: Page, label: string) {
  // `exact` 不能省：侧栏的运行配置入口叫「项目设置」，模糊匹配会同时命中它，
  // 于是 strict mode 直接抛错（60 个用例全挂在这一行）。
  await page.getByRole('button', { name: '设置', exact: true }).click();
  await page.getByRole('button', { name: label, exact: true }).click();
  // 主题写在 <html data-theme> 上，等它真的落上去再截图。
  const expected = label === '浅色' ? 'light' : 'dark';
  await expect(page.locator('html')).toHaveAttribute('data-theme', expected);
  await page.keyboard.press('Escape');
}

test.describe('视觉回归：三视口 × 明暗 × 十画面', () => {
  for (const viewport of VIEWPORTS) {
    for (const theme of THEMES) {
      for (const screen of SCREENS) {
        const title = `${viewport.name}/${theme.name} — ${screen.id}`;

        test(title, async ({ page }) => {
          await page.setViewportSize({
            width: viewport.width,
            height: viewport.height,
          });

          // 先在总览上把主题设好：设置抽屉在每一页的顶栏里都有，
          // 但只有先有一个能渲染的页面才点得到它。
          await page.goto('/');
          await setTheme(page, theme.label);

          await screen.open(page);

          // 断言 1：侧栏只能有四项（PRD 5.1：不在侧栏追加设置/终端/帮助）。
          // 「任何新导航项都应阻止合并」—— 这条就是那个门禁。
          if (screen.hasSidebar) {
            await expect(
              page.locator('aside[aria-label="主导航"] [data-nav-item]'),
            ).toHaveCount(4);
          }

          // 断言 2：不允许横向溢出。窄视口（1024）最容易暴露，
          // 溢出往往意味着某个面板写了固定宽度。
          const overflow = await page.evaluate(() => ({
            scrollWidth: document.documentElement.scrollWidth,
            clientWidth: document.documentElement.clientWidth,
          }));
          expect(
            overflow.scrollWidth,
            `页面横向溢出 ${overflow.scrollWidth} > ${overflow.clientWidth}`,
          ).toBeLessThanOrEqual(overflow.clientWidth + 1);

          // 断言 3：该出现的标题出现了（防止容器塌陷成 0 高度后整块消失）。
          if (screen.expectHeading) {
            const heading = page.getByRole('heading', { name: screen.expectHeading });
            await expect(heading).toBeVisible();
            const box = await heading.boundingBox();
            expect(box?.height ?? 0, '标题高度为 0，容器多半塌了').toBeGreaterThan(0);
          }

          // 断言 4：不该冒出未处理的错误面板；错误状态那一屏反过来必须显示。
          //        用 `toBeVisible` 而不是直接数 count —— 错误面板要等 query
          //        失败之后才渲染，数得太早会假红。
          const alerts = page.locator('[role="alert"]');
          if (screen.expectsAlert) {
            await expect(alerts.first(), '错误状态画面应当显示错误面板').toBeVisible({
              timeout: 20_000,
            });
          } else {
            await expect(alerts).toHaveCount(0);
          }

          // 截图只截视口：全页截图会在滚动容器里重排，反而看不出真实布局。
          //
          // 落在 **`web/test-results/visual/`**（已 gitignore）而不是 Playwright
          // 的 outputDir —— 后者每轮都是新的临时目录，跑完就找不着了，而截图
          // 本来就是给人翻的。
          const outDir = join('test-results', 'visual', viewport.name, theme.name);
          mkdirSync(outDir, { recursive: true });
          await page.screenshot({ path: join(outDir, `${screen.id}.png`) });
        });
      }
    }
  }
});

/**
 * 单树形态的**结构性**断言（TODO §12.5）。
 *
 * 上面 60 个用例只保证"没退化"，不保证"阶段 7 做的东西真的出现了"。
 * 更薄的数据就完美通过上面所有断言 —— 分层带只有两条、没有交叉边、四档里
 * 只占一档，截图看上去和没改过一个样。所以这里单独对着形态完整的单树
 * fixture 把每一条视觉特性点名验一遍。
 *
 * 放在同一个文件里是因为它们的失败原因相同：数据太薄，看不出改动。
 */
test.describe('单树形态：阶段 7 的视觉特性必须真的出现', () => {
  test.beforeEach(async ({ page }) => {
    await page.setViewportSize({ width: 1920, height: 1080 });
    await page.goto(`/runs/${SINGLE_TREE_RUN_ID}/tree`);
    await expect(page.locator('[data-testid="tree-canvas"]')).toBeVisible({
      timeout: 20_000,
    });
    // 画布开了 `onlyRenderVisibleElements`：视口外的节点**根本不在 DOM 里**。
    // 所以这里刻意**不**手动点「适应视图」——它验证的正是"打开树页就能看到
    // 全部 21 个节点"这件事，手动 fit 会把"初始视口不对"这个 bug 掩盖掉。
  });

  test('21 个节点全部渲染', async ({ page }) => {
    await expect(page.locator('.react-flow__node')).toHaveCount(21);
  });

  test('六层分层带全部渲染', async ({ page }) => {
    for (let depth = 0; depth <= 5; depth += 1) {
      await expect(
        page.locator(`[data-testid="tree-band-${depth}"]`),
        `第 ${depth} 层的分层带没有渲染`,
      ).toHaveCount(1);
    }
    // 明确反例：不该出现第 6 层，否则说明分层带是按节点算而不是按 depth 算。
    await expect(page.locator('[data-testid="tree-band-6"]')).toHaveCount(0);
  });

  test('显著性四档每档都有节点，不存在"分档等于没分"', async ({ page }) => {
    const summary = page.locator('[data-testid="significance-summary"]');
    await expect(summary).toBeVisible();
    const text = (await summary.textContent()) ?? '';
    for (const label of ['当前最优', '有效改进', '噪声内', '无法判断']) {
      const matched = text.match(new RegExp(`(\\d+)\\s*${label}`));
      expect(matched, `分布条里没有「${label}」的计数：${text}`).not.toBeNull();
      expect(
        Number(matched![1]),
        `「${label}」计数为 0，这一档在图上根本看不到`,
      ).toBeGreaterThan(0);
    }
  });

  test('交叉节点带「双亲」标记，最优节点唯一', async ({ page }) => {
    // 只挑这两个标记数：节点数受 `onlyRenderVisibleElements` 影响，
    // 不能拿总数做相等断言，但"图上有几个双亲/最优"是形态问题，是稳定的。
    await expect(page.locator('.react-flow__node', { hasText: '⑂ 双亲' })).toHaveCount(1);
    await expect(page.locator('.react-flow__node', { hasText: '★ 最优' })).toHaveCount(1);
  });

  test('修复链节点存在，且抽屉里能看到来自被修节点的记账', async ({ page }) => {
    const repair = page.locator('[data-testid="tree-node-n16a9b0db"]');
    await expect(repair, '修复节点 n16a9b0db 没有渲染').toBeVisible({ timeout: 20_000 });
    await repair.click();
    const drawer = page.locator('[data-testid="node-drawer"]');
    await expect(drawer).toBeVisible({ timeout: 20_000 });
    await expect(drawer.getByText('修复来源').first()).toBeVisible();
  });
});

/**
 * 三岛形态的**结构性**断言（TODO D6.4）。
 *
 * 与上面同一条理由：三岛 fixture 的岛卡、交换计数、嫁接边如果没渲染出来，
 * 上面 60 个截图用例照样全绿。这里把它们逐个点名。
 *
 * 断言值全部来自 fixture 的实测内容（`tests/fixtures/runs/hdd_mvp_islands_15l4nd01`
 * 与 PROVENANCE.md）：3 岛 × 7 节点、全局最优 54b71757 落在岛 a、六个交换
 * 计数互不相等（发布 1 / 投递 2 / 采用 12），所以"并成一个数"必定被这里抓住。
 */
test.describe('三岛形态：岛卡、交换计数与岛筛选必须真的出现', () => {
  test.beforeEach(async ({ page }) => {
    await page.setViewportSize({ width: 1920, height: 1080 });
  });

  test('三岛概览：三张岛卡、六个独立交换计数、全局最优落在岛 a', async ({ page }) => {
    await page.goto(`/runs/${ISLANDS_RUN_ID}`);
    await expect(page.getByRole('heading', { name: '进化工作台' })).toBeVisible({
      timeout: 20_000,
    });
    await page.locator('[data-panel="islands"]').click();
    const overview = page.locator('[data-testid="island-overview"]');
    await expect(overview).toBeVisible({ timeout: 20_000 });

    for (const island of ['a', 'b', 'c']) {
      await expect(overview.locator(`[data-island-card="${island}"]`)).toHaveCount(1);
    }
    // 每岛 7 个树内节点：卡片上的数字来自树，不是 run_summary 的转述。
    // 按 `data-island-tree-count` 取值，不按文本 —— fixture 里「尝试」与
    // 「树内节点」都是 7，getByText('7') 会命中两个元素。
    for (const island of ['a', 'b', 'c']) {
      await expect(
        overview.locator(`[data-island-tree-count="${island}"]`),
        `岛 ${island} 卡片的树内节点数不对`,
      ).toHaveText('7');
    }

    // 六个计数各自独立：投递 2 而采用 12，若界面把它们并成一个数就取不出这两项。
    await expect(overview.locator('[data-exchange-fact="deliveries"]')).toHaveText('2');
    await expect(overview.locator('[data-exchange-fact="applications"]')).toHaveText('12');
    await expect(overview.locator('[data-exchange-fact="summaries"]')).toHaveText('1');

    // 全局最优与它的落点都写出来（fixture 实测：岛 a）。
    await expect(overview.locator('[data-global-best]')).toHaveText('22.81');
    await expect(overview.getByText('（落在岛 a）')).toBeVisible();
  });

  test('岛筛选芯片：按岛收窄后画布只剩该岛的 7 个节点', async ({ page }) => {
    await page.goto(`/runs/${ISLANDS_RUN_ID}/tree`);
    await expect(page.locator('[data-testid="tree-canvas"]')).toBeVisible({ timeout: 20_000 });
    await expect(page.locator('.react-flow__node')).toHaveCount(21);

    const chip = page.locator('button[aria-pressed]', { hasText: '岛 a' }).first();
    await chip.click();
    await expect(chip).toHaveAttribute('aria-pressed', 'true');
    // 单岛视图：只有岛 a 的 7 个节点；跨岛嫁接边不在这个视图里显示。
    await expect(page.locator('.react-flow__node')).toHaveCount(7);
    await expect(page.getByRole('button', { name: '看全部岛' })).toBeVisible();
  });

  test('历史单树运行打开三岛面板：明说没有岛记账，不编三个岛', async ({ page }) => {
    await page.goto(`/runs/${SINGLE_TREE_RUN_ID}`);
    await expect(page.getByRole('heading', { name: '进化工作台' })).toBeVisible({
      timeout: 20_000,
    });
    await page.locator('[data-panel="islands"]').click();
    const legacy = page.locator('[data-island-shape="legacy-single"]');
    await expect(legacy).toBeVisible({ timeout: 20_000 });
    // 组件自己的缺失说明必须出现（不依赖 fixture 里写了什么 reason）。
    await expect(legacy).toContainText('该运行没有产出 islands / exchange 记账');
  });
});
