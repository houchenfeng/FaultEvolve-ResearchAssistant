/**
 * `useEventStream` 的测试。
 *
 * 测的是**行为**而不是实现：去重、降级、收敛、游标传递。这些都是"接上去之后
 * 时间轴对不对"的唯一判据，而它们全都不需要真服务器——`EventSource` 是个
 * 纯客户端 API，用一个假的替身就能把重连、降级和具名事件派发完整地走一遍。
 *
 * 顺带覆盖一件真机上才看得见的事：jsdom 没有 `EventSource`，所以"不支持"
 * 这条降级路在测试里天然被走到——如果这条分支坏了，测试环境反而是第一个
 * 发现的人。
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook, waitFor } from '@testing-library/react';
import { createElement, type ReactNode } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  FALLBACK_POLL_MS,
  SNAPSHOT_READY,
  useEventStream,
  type StreamStatus,
} from '@/features/workbench/use-event-stream';
import { queryKeys } from '@/lib/query-keys';

interface FakeSource {
  url: string;
  closed: boolean;
  listeners: Map<string, Array<(event: MessageEvent) => void>>;
  emit: (name: string, data: unknown) => void;
  onopen: (() => void) | null;
  onerror: (() => void) | null;
  onmessage: ((event: MessageEvent) => void) | null;
}

const sources: FakeSource[] = [];

function installFakeEventSource(): void {
  class FakeEventSourceImpl {
    private readonly record: FakeSource;

    constructor(url: string) {
      this.record = {
        url,
        closed: false,
        listeners: new Map(),
        emit: (name, data) => {
          const event = {
            data: typeof data === 'string' ? data : JSON.stringify(data),
            lastEventId: '',
          } as MessageEvent;
          for (const listener of this.record.listeners.get(name) ?? []) listener(event);
        },
        onopen: null,
        onerror: null,
        onmessage: null,
      };
      sources.push(this.record);
    }

    // The hook assigns `onopen` / `onerror` / `onmessage` as properties, so the
    // fake has to funnel them into the record the test holds -- otherwise the
    // test calls a field nothing ever wrote to and the "connected" case silently
    // never runs.
    get onopen() {
      return this.record.onopen;
    }

    set onopen(handler: (() => void) | null) {
      this.record.onopen = handler;
    }

    get onerror() {
      return this.record.onerror;
    }

    set onerror(handler: (() => void) | null) {
      this.record.onerror = handler;
    }

    get onmessage() {
      return this.record.onmessage;
    }

    set onmessage(handler: ((event: MessageEvent) => void) | null) {
      this.record.onmessage = handler;
    }

    close() {
      this.record.closed = true;
    }

    addEventListener(name: string, listener: (event: MessageEvent) => void) {
      const existing = this.record.listeners.get(name) ?? [];
      existing.push(listener);
      this.record.listeners.set(name, existing);
    }
  }

  vi.stubGlobal('EventSource', FakeEventSourceImpl as unknown as typeof EventSource);
}

function wrapper({ children }: { children: ReactNode }) {
  return createElement(
    QueryClientProvider,
    { client: new QueryClient({ defaultOptions: { queries: { retry: false } } }) },
    children,
  );
}

function event(id: number, type: string, payload: Record<string, unknown> = {}) {
  return {
    id,
    run_id: 'run-1',
    type,
    payload,
    ts: '2026-10-03T00:00:00Z',
    is_known_type: true,
  };
}

beforeEach(() => {
  sources.length = 0;
  vi.stubGlobal('fetch', vi.fn());
});

afterEach(() => {
  // A test that times out never reaches its own `useRealTimers`, and fake
  // timers leak into every test after it -- which turns one failure into a
  // cascade of unrelated timeouts. Unconditional restore here.
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

/** Fake timers that still let the microtask queue drain, so `waitFor` works. */
function useFakeTimersWithTime() {
  vi.useFakeTimers({ shouldAdvanceTime: true });
}

describe('useEventStream', () => {
  it('连上后状态是 open，并把事件按收到的顺序交出去', async () => {
    installFakeEventSource();
    const { result } = renderHook(() => useEventStream({ runId: 'run-1' }), { wrapper });

    await waitFor(() => expect(result.current.status).toBe<StreamStatus>('connecting'));
    act(() => {
      sources[0].onopen?.();
    });
    expect(result.current.status).toBe('open');

    act(() => {
      sources[0].emit('init_evaluated', event(1, 'init_evaluated'));
      sources[0].emit('node_created', event(2, 'node_created'));
    });

    expect(result.current.events.map((e) => e.type)).toEqual([
      'init_evaluated',
      'node_created',
    ]);
    expect(result.current.lastEventId).toBe(2);
  });

  it('同一个 id 事件两次只算一次', () => {
    installFakeEventSource();
    const { result } = renderHook(() => useEventStream({ runId: 'run-1' }), { wrapper });

    act(() => {
      sources[0].emit('iteration_complete', event(1, 'iteration_complete'));
      // 断线重连后服务端从同一个游标重发，客户端不能变成两条。
      sources[0].emit('iteration_complete', event(1, 'iteration_complete'));
    });

    expect(result.current.events).toHaveLength(1);
  });

  it('收到 snapshot_ready 就停下流，并把这一片缓存全部作废', async () => {
    installFakeEventSource();
    const client = new QueryClient();
    const invalidate = vi.spyOn(client, 'invalidateQueries');
    const { result } = renderHook(
      () => useEventStream({ runId: 'run-1' }),
      { wrapper: ({ children }) => createElement(QueryClientProvider, { client }, children) },
    );

    act(() => {
      sources[0].emit(SNAPSHOT_READY, { event: SNAPSHOT_READY });
    });

    await waitFor(() => expect(result.current.snapshotReady).toBe(true));
    expect(result.current.status).toBe('closed');
    expect(sources[0].closed).toBe(true);
    // 制品现在是权威，必须让 REST 重新读，而不是停在流的最后一条。
    const keys = invalidate.mock.calls.map((call) => call[0]?.queryKey);
    expect(keys).toContainEqual(queryKeys.run('run-1'));
    expect(keys).toContainEqual(queryKeys.tree('run-1'));
  });

  it('首连把已知游标带上去，不重放整条时间线', async () => {
    installFakeEventSource();
    renderHook(() => useEventStream({ runId: 'run-1', afterId: 42 }), { wrapper });

    await waitFor(() => expect(sources).toHaveLength(1));
    expect(sources[0].url).toContain('after_id=42');
  });

  it('没有 EventSource 时降级成轮询，而不是一直显示连接中', async () => {
    // jsdom 默认就没有 EventSource：这条断言同时证明"不支持"这条路是通的。
    vi.stubGlobal('EventSource', undefined);
    useFakeTimersWithTime();

    const { result } = renderHook(() => useEventStream({ runId: 'run-1' }), { wrapper });

    await waitFor(() => expect(result.current.status).toBe<StreamStatus>('polling'));
    expect(fetch).toHaveBeenCalledWith('/api/runs/run-1/events?limit=2000');

  });

  it('轮询把 REST 拿到的旧事件也并进来，且照样去重', async () => {
    vi.stubGlobal('EventSource', undefined);
    useFakeTimersWithTime();
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true,
      json: async () => ({ events: [event(1, 'init_evaluated'), event(2, 'node_created')] }),
    });

    const { result } = renderHook(() => useEventStream({ runId: 'run-1' }), { wrapper });

    await waitFor(() => expect(result.current.events).toHaveLength(2));
    // 再来一轮同样的数据，长度不变。
    await act(async () => {
      await vi.advanceTimersByTimeAsync(FALLBACK_POLL_MS);
    });
    expect(result.current.events).toHaveLength(2);

  });

  it('一帧坏数据不会断开整条流', async () => {
    installFakeEventSource();
    const { result } = renderHook(() => useEventStream({ runId: 'run-1' }), { wrapper });

    act(() => {
      sources[0].emit('llm_error', 'this is not json');
      sources[0].emit('llm_error', event(9, 'llm_error'));
    });

    expect(result.current.events).toHaveLength(1);
    expect(result.current.events[0]?.id).toBe(9);
  });

  it('卸载时把流和降级轮询都停掉', async () => {
    installFakeEventSource();
    const { unmount } = renderHook(() => useEventStream({ runId: 'run-1' }), { wrapper });
    const source = sources[0];

    unmount();

    expect(source.closed).toBe(true);
  });

  it('enabled=false 时什么都不做', async () => {
    installFakeEventSource();
    const { result } = renderHook(
      () => useEventStream({ runId: 'run-1', enabled: false }),
      { wrapper },
    );

    await waitFor(() => expect(result.current.status).toBe<StreamStatus>('idle'));
    expect(sources).toHaveLength(0);
  });
});
