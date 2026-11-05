import { chromium } from '@playwright/test';
import { mkdir } from 'node:fs/promises';
import assert from 'node:assert/strict';

// Run against showcase_serve.py and Vite on ports 8011 and 4318.
const browser = await chromium.launch();
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('http://127.0.0.1:4318/overview/showcase');
  await page.getByRole('button', { name: '运行耗时', exact: true }).click();
  await page.getByText('25.80 s', { exact: true }).waitFor();
  await page.getByRole('button', { name: '综合得分 ROS', exact: true }).click();
  await mkdir('../docs/screenshots', { recursive: true });
  assert.equal(await page.locator('h1').evaluate(el => getComputedStyle(el).color), 'rgb(234, 242, 250)');
  await page.setViewportSize({ width: 1440, height: Math.ceil(await page.locator('.sc-page').evaluate(el => el.scrollHeight)) });
  await page.screenshot({ path: '../docs/screenshots/tmall-integrated-showcase.png' });
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.getByRole('tab', { name: '三岛协作' }).click();
  await page.getByRole('button', { name: /误漏报优化岛/ }).click();
  await page.getByRole('button', { name: /交换经验/ }).click();
  await page.getByText(/接收岛独立决定是否采纳/).waitFor();
  const [download] = await Promise.all([
    page.waitForEvent('download'),
    page.getByRole('link', { name: /下载实验摘要/ }).click(),
  ]);
  assert.equal(download.suggestedFilename(), 'hdd-results.json');
  await page.setViewportSize({ width: 390, height: 844 });
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
  assert.equal(await page.locator('.sc-shell').evaluate(el => el.scrollWidth <= innerWidth), true);
  await page.setViewportSize({ width: 390, height: Math.ceil(await page.locator('.sc-page').evaluate(el => el.scrollHeight)) });
  await page.screenshot({ path: '../docs/screenshots/tmall-integrated-mobile.png' });
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.getByRole('link', { name: /初赛历史案例回放/ }).click();
  await page.waitForTimeout(1500);
  assert.ok((await page.locator('body').innerText()).includes('hdd_mvp'));
  const response = await page.request.get('http://127.0.0.1:8011/api/runs/hdd_mvp_showcase_c89e2a01');
  assert.equal(response.status(), 200);
  assert.deepEqual(errors, []);
  console.log('PASS: desktop/mobile layout, metrics, island interaction, download, legacy run API and navigation');
} finally {
  await browser.close();
}
