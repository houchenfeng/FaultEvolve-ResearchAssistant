import { test, expect } from '@playwright/test';

/**
 * E2E-03：实时运行（TODO §12.4）。
 *
 * 五步走：启动 mock 运行 → 观察节点增加 → 断开 SSE → 重连补拉 → 完成后切稳定快照。
 *
 * 这条用例真正要钉住的是**第 4 步**：断线重连后既不能重播、也不能漏。
 * 阶段 8 设计 SSE 时定的规矩是「`Last-Event-ID` 请求头优先于查询串游标」，
 * 因为 EventSource 断线重连会带着同一个 URL 再连并附上该头——若查询串优先，
 * 每重连一次就把全部事件重播一遍。这里直接在浏览器里手动断流、手动带上上次
 * 的 id 重连，把这条规矩验成可观测的事实。
 *
 * 注意 `readStream` 是被 Playwright 序列化后丢进浏览器执行的，函数体里
 * **不能引用本文件的任何变量**，一切走参数。
 */

interface StreamArgs {
  url: string;
  lastEventId: number | null;
  maxFrames: number;
  deadlineMs: number;
}

interface StreamResult {
  ids: number[];
  types: string[];
}

async function readStream(args: StreamArgs): Promise<StreamResult> {
  const { url, lastEventId, maxFrames, deadlineMs } = args;
  const headers: Record<string, string> = {};
  if (lastEventId != null) headers['Last-Event-ID'] = String(lastEventId);

  const res = await fetch(url, { headers });
  const reader = res.body!.getReader();
  const decoder = new TextDecoder();
  let buf = '';
  const ids: number[] = [];
  const types: string[] = [];
  const deadline = Date.now() + deadlineMs;

  try {
    while (Date.now() < deadline && types.length < maxFrames) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const parts = buf.split('\n\n');
      buf = parts.pop() || '';
      for (const frame of parts) {
        let id: number | null = null;
        let type = '';
        for (const line of frame.split('\n')) {
          if (line.startsWith('id:')) id = Number(line.slice(3).trim());
          else if (line.startsWith('event:')) type = line.slice(6).trim();
        }
        if (id != null) ids.push(id);
        if (type) types.push(type);
      }
    }
  } finally {
    // 这就是「断开 SSE」：客户端单方面砍掉连接。
    try {
      await reader.cancel();
    } catch {
      /* 已经关了 */
    }
  }
  return { ids, types };
}

test.describe('E2E-03：实时运行', () => {
  test('启动 mock 运行 → 断线 → 带 Last-Event-ID 重连 → 收敛到稳定快照', async ({ page }) => {
    // 真实运行要跑几十秒，默认 60 s 不够。
    test.setTimeout(240_000);

    await page.goto('/');

    const started = await page.evaluate(async () => {
      const servers = await (await fetch('/api/servers')).json();
      const res = await fetch('/api/runs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          task_id: 'hdd_mvp',
          server_profile_id: servers.profiles[0].profile_id,
          preset: 'quick',
          mock_llm: true,
        }),
      });
      return res.json();
    });
    const runId = started.run_id as string;
    expect(runId).toBeTruthy();
    const streamUrl = `/api/runs/${runId}/stream`;

    // 步骤 1-2：启动后先读一小段，看到实时事件（含新节点）在增加。
    const first = await page.evaluate(readStream, {
      url: streamUrl,
      lastEventId: null,
      maxFrames: 3,
      deadlineMs: 20_000,
    });
    expect(first.types.length, '应当先收到若干实时事件').toBeGreaterThan(0);
    expect(first.ids.length).toBe(first.types.length);

    // 步骤 3-4：上面读完已经 cancel（= 断线），用最后一个 id 重连。
    const lastId = first.ids[first.ids.length - 1];
    const second = await page.evaluate(readStream, {
      url: streamUrl,
      lastEventId: lastId,
      maxFrames: 500,
      deadlineMs: 150_000,
    });

    // 重连后必须**不重播**：新帧的 id 全部严格大于断点。
    const replayed = second.ids.filter((id: number) => id <= lastId);
    expect(
      replayed,
      `重连后重播了 ${replayed.length} 条（<= ${lastId}）——Last-Event-ID 没生效`,
    ).toHaveLength(0);

    // 步骤 2 的硬要求：节点在增加（根节点的 node_created 不算）。
    const allTypes = [...first.types, ...second.types];
    const nodeCreated = allTypes.filter((t: string) => t === 'node_created').length;
    expect(nodeCreated, '运行过程中应当持续有新节点产生').toBeGreaterThan(1);

    // 步骤 5：完成后收敛到稳定快照。
    expect(second.types, '流里应当出现 run_finished').toContain('run_finished');
    expect(second.types, '流末尾应当发出 snapshot_ready').toContain('snapshot_ready');

    // 不重：两段拼起来没有重复 id。
    const merged = [...first.ids, ...second.ids].sort((a, b) => a - b);
    const dupes = merged.filter((id, i) => i > 0 && id === merged[i - 1]);
    expect(dupes, '两段流拼接后不应有重复 id').toHaveLength(0);

    // 不漏：补拉后应当追上 REST 侧的最新事件。
    const restIds = await page.evaluate(async (rid: string) => {
      const res = await fetch(`/api/runs/${rid}/events?limit=2000`);
      const body = await res.json();
      return (body.events ?? body).map((e: { id: number }) => e.id);
    }, runId);
    const restMax = Math.max(...restIds);
    expect(
      Math.max(...merged),
      'SSE 补拉后应当追上 REST 侧的最新事件（没漏）',
    ).toBeGreaterThanOrEqual(restMax - 1);

    // 收敛后，运行详情应当是可信的稳定状态。
    const detail = await page.evaluate(async (rid: string) => {
      const res = await fetch(`/api/runs/${rid}`);
      return res.json();
    }, runId);
    expect(detail.data_state).toBe('complete');
  });
});
