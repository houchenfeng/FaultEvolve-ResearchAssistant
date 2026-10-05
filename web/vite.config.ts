import { fileURLToPath, URL } from 'node:url';

import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

/**
 * FaultEvolve WebUI 构建配置。
 *
 * 契约说明：`web/openapi/*.json` 由 `scripts/export_web_contracts.py` 生成并入库，
 * TypeScript 客户端由 `pnpm generate:api` 从该契约生成，因此构建不需要运行后端。
 */

/**
 * Web API 的代理目标。
 *
 * 默认 8000 = `fe web serve` 的默认端口，日常 `pnpm dev` 不受影响。
 * E2E 必须能改它：测试要起**自己那份**后端（指向 fixture 运行目录、临时
 * registry），不能蹭开发者手上那个端口——否则测试结果取决于旁边有没有人在跑
 * 服务，`reuseExistingServer` 还会把测试悄悄连到错误的实现上。
 */
const apiProxyTarget = process.env.VITE_API_PROXY_TARGET ?? 'http://127.0.0.1:8000';

export default defineConfig(({ mode }) => ({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: Number(process.env.VITE_DEV_PORT ?? 5173),
    // 开发期把 /api 反代到本机 Web API（fe web serve 默认端口）。
    proxy: {
      '/api': {
        target: apiProxyTarget,
        changeOrigin: true,
        // E2E-03 reads SSE through this proxy with fetch + ReadableStream. Some
        // platforms (notably Windows dev) buffer text/event-stream until the
        // connection closes unless we flush headers and disable compression.
        configure: (proxy) => {
          proxy.on('proxyRes', (proxyRes, _req, res) => {
            const type = proxyRes.headers['content-type'];
            if (typeof type === 'string' && type.includes('text/event-stream')) {
              delete proxyRes.headers['content-encoding'];
              res.setHeader('Cache-Control', 'no-store');
              res.setHeader('X-Accel-Buffering', 'no');
              if (typeof res.flushHeaders === 'function') {
                res.flushHeaders();
              }
            }
          });
        },
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: true,
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.{test,spec}.{ts,tsx}'],
    css: false,
    // 1000 节点的 dagre 布局单跑要 2.1 s，默认 5 s 超时会在坐标断言之前
    // 把测试掐掉，失败原因显示成超时而不是真实断言。
    testTimeout: 20_000,
    // `pnpm test:perf`（= vitest run --mode perf）才是墙钟预算的正式入口。
    //
    // 1000 节点的 dagre 布局**独占**跑 0.97 s，多 worker 并发时被抢 CPU 会
    // 飘到 7 s（实测 7046 ms，×7）。同一份代码、同一台机器，差的只是旁边
    // 有没有人在跑别的 —— 拿这种数字当预算，测的是调度器不是算法。
    //
    // 所以 mode=perf 时把 FE_PERF_EXCLUSIVE 打开：性能文件里的
    // `it.skipIf(!PERF_EXCLUSIVE)` 才让这些用例执行，wall-clock 断言
    // 才生效。普通 `pnpm test` 照跑全部用例（结构、纯度、复杂度比值），
    // 只把墙钟那几条标成 skipped 并在报告里说明原因 —— 不静默跳过。
    env: {
      FE_PERF_EXCLUSIVE: mode === 'perf' ? '1' : '0',
    },
  },
}));
