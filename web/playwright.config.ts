import os from 'node:os';
import path from 'node:path';

import { defineConfig, devices } from '@playwright/test';

/**
 * FaultEvolve WebUI 的端到端测试（TODO §12.4）。
 *
 * 两条服务都由 Playwright 自己拉起，不依赖开发者手上正在跑的那个：
 *
 * 1. Web API —— `scripts/e2e_serve.py`，指向仓库内 fixture 运行目录 +
 *    每轮全新的 run registry。配置写死在脚本里，不吃 `FE_WEB_*` 环境变量，
 *    所以同一份代码在不同机器上结果一致。
 * 2. 前端 —— `pnpm dev`，通过 `VITE_API_PROXY_TARGET` 把 /api 代理到上面
 *    那个端口（默认 8000 是给日常开发用的，这里必须指到 E2E 那份后端）。
 *
 * `reuseExistingServer` 关掉是刻意的：开发机上常常还挂着一个旧后端，复用它
 * 会让测试连到错误的实现上，失败现象会离真正的改动很远。宁可每次多等几秒。
 */

const API_PORT = 8011;
const WEB_PORT = 4318;

const venvPython =
  process.platform === 'win32' ? '..\\.venv\\Scripts\\python.exe' : '../.venv/bin/python';

/**
 * 产物目录：每次运行一个**全新**的目录。
 *
 * Playwright 在开跑前会清空 outputDir。本机对批量删除有守卫（超过阈值直接
 * 抛错，而且配额是按轮次累计的），共用 `web/test-results` 会让第二轮起就
 * 撞上它——现象是"用例还没跑，命令就 exit 1"。新目录里没有东西可删，
 * 绕开这个限制。需要固定位置时用 `FE_E2E_OUTPUT_DIR` 覆盖。
 */
const outputDir =
  process.env.FE_E2E_OUTPUT_DIR ??
  path.join(os.tmpdir(), `fe-e2e-${new Date().toISOString().replace(/[:.]/g, '-')}`);

export default defineConfig({
  testDir: './e2e',
  outputDir,
  // 后端持有一份进程/registry 状态，用例之间并行会互相踩。
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : [['list']],
  timeout: 60_000,
  expect: { timeout: 15_000 },

  use: {
    baseURL: `http://127.0.0.1:${WEB_PORT}`,
    // trace 关掉是这台机器的现实约束：Playwright 在每轮开始时清空
    // test-results，而一个 trace 展开就是几千个文件，会被本机的批量删除守卫
    // 拦下并直接抛错 —— 结果变成"用例本身过了、exit code 却是 1"的假红。
    // 只留失败截图（几个文件），既够定位又不触发守卫。
    trace: 'off',
    screenshot: 'only-on-failure',
    // 视觉回归（TODO §12.5）要靠固定视口才能对比，默认给最大的那档。
    viewport: { width: 1440, height: 900 },
  },

  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],

  webServer: [
    {
      command: `${venvPython} ../scripts/e2e_serve.py --port ${API_PORT}`,
      url: `http://127.0.0.1:${API_PORT}/api/meta`,
      reuseExistingServer: false,
      timeout: 120_000,
      stdout: 'pipe',
      stderr: 'pipe',
    },
    {
      // `--host 127.0.0.1` 不能省：vite 默认绑 localhost，在本机上会解析到
      // IPv6 的 ::1，而下面 health check 探的是 127.0.0.1 —— 两边对不上，
      // Playwright 会一直等到 webServer 超时（实测 120 s 全耗在这里）。
      command: `pnpm dev --port ${WEB_PORT} --host 127.0.0.1`,
      url: `http://127.0.0.1:${WEB_PORT}/`,
      reuseExistingServer: false,
      timeout: 120_000,
      env: {
        VITE_API_PROXY_TARGET: `http://127.0.0.1:${API_PORT}`,
      },
      stdout: 'pipe',
      stderr: 'pipe',
    },
  ],
});
