/**
 * SSE 事件流客户端（阶段 8，PRD §16.2-§16.3）。
 *
 * ## 为什么不用生成的 SDK
 *
 * `EventSource` 有一套自己的重连语义，而这套语义**恰好是本设计要依赖的**：
 * 浏览器断线后自动带 `Last-Event-ID` 重连到同一个 URL。生成的 fetch 客户端
 * 没有这个行为，自己实现就等于把浏览器已经做对的事重写一遍，还必然写错。
 *
 * ## 降级不是"失败"，是一条正常的路
 *
 * PRD §9.4 要求 SSE 不可用时回落到轮询。这里把回落写成显式的三态
 * （`connecting` / `open` / `polling`），而不是"重试几次然后放弃"：本项目
 * 的部署形态有纯本地 Worker，浏览器不支持或代理掐断都是常态，一条永远显示
 * "连接中"的时间轴比一条慢一点的轮询时间轴没用得多。
 *
 * ## 去重在客户端做，因为服务端保证不了
 *
 * 同一 id 可能从两条路各来一次（SSE 补拉 + REST 快照）。`dedupeEvents` 按 id
 * 去重、id 缺失时按 (type, ts) 兜底，所以顺序上"先到的赢"不会产生重复节点。
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';

import type { EventResponse } from '@/generated/api';
import { runScopedKeys } from '@/lib/query-keys';
import { dedupeEvents } from '@/features/workbench/iteration-logic';

/** 服务端在制品稳定后发出的收敛信号。不是引擎事件类型。 */
export const SNAPSHOT_READY = 'snapshot_ready';

/** 流不可用时，多久拉一次 `/events`。和 SSE 的 0.5s 尾随比，慢一个量级。 */
export const FALLBACK_POLL_MS = 3_000;

/** 首连与每次重连之间的退避上限。 */
const RECONNECT_BASE_MS = 1_000;
const RECONNECT_MAX_MS = 30_000;

export type StreamStatus = 'idle' | 'connecting' | 'open' | 'polling' | 'closed';

export interface UseEventStreamOptions {
  /** 已有事件的最后一个 id；首连时作为游标传上去，避免重放整条时间线。 */
  afterId?: number | null;
  /** 关闭流（离开页面时）。 */
  enabled?: boolean;
  /** 关掉它就知道这条流不是这个页面要的。 */
  runId: string;
}

export interface UseEventStreamResult {
  /** 已收到的引擎事件（已去重、按 id 升序）。不含 snapshot_ready。 */
  events: EventResponse[];
  status: StreamStatus;
  /** 最近一次事件的 id，供上层在重挂载时续上。 */
  lastEventId: number | null;
  /** 制品是否已收敛（收到过 snapshot_ready）。 */
  snapshotReady: boolean;
  /** 手动重连（降级态下让用户能自己再试一次）。 */
  reconnect: () => void;
}

function buildUrl(runId: string, afterId: number | null | undefined): string {
  const query = afterId === null || afterId === undefined ? '' : `?after_id=${afterId}`;
  return `/api/runs/${encodeURIComponent(runId)}/stream${query}`;
}

export function useEventStream(options: UseEventStreamOptions): UseEventStreamResult {
  const { runId, afterId, enabled = true } = options;
  const queryClient = useQueryClient();

  const [events, setEvents] = useState<EventResponse[]>([]);
  const [status, setStatus] = useState<StreamStatus>('idle');
  const [snapshotReady, setSnapshotReady] = useState(false);
  const [attempt, setAttempt] = useState(0);

  // 用 ref 记住已经见过的 id：`addEvent` 会被 `EventSource` 的回调长期持有，
  // 放进 state 就会每来一个事件重建一次回调，进而重连。
  const seen = useRef<Set<number>>(new Set());
  const cursor = useRef<number | null>(afterId ?? null);
  const sourceRef = useRef<EventSource | null>(null);
  const fallbackTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const addEvent = useCallback((event: EventResponse) => {
    if (typeof event.id === 'number') {
      if (seen.current.has(event.id)) return;
      seen.current.add(event.id);
      cursor.current = event.id;
    }
    setEvents((previous) => dedupeEvents([...previous, event]));
  }, []);

  const onSnapshotReady = useCallback(() => {
    setSnapshotReady(true);
    // 制品现在是权威：把这一片缓存全部作废，让 REST 重新读一遍稳定文件。
    for (const key of runScopedKeys(runId)) {
      void queryClient.invalidateQueries({ queryKey: key });
    }
  }, [queryClient, runId]);

  // ---- 降级轮询 -------------------------------------------------------
  //
  // 只在 SSE 确认不可用时启用。反过来做（先轮询、失败再升级）会让每个页面
  // 都白白发一份 REST 请求，而那条请求的答案流自己也会送到。
  const startFallbackPolling = useCallback(() => {
    if (fallbackTimer.current !== null) return;
    setStatus('polling');
    const tick = async () => {
      try {
        const response = await fetch(
          `/api/runs/${encodeURIComponent(runId)}/events?limit=2000`,
        );
        if (response.ok) {
          const body = (await response.json()) as { events?: EventResponse[] };
          for (const event of body.events ?? []) addEvent(event);
        }
      } catch {
        // 轮询失败不改状态：下一轮还会来，保持"慢但在工作"的语义。
      }
      fallbackTimer.current = setTimeout(tick, FALLBACK_POLL_MS);
    };
    void tick();
  }, [runId, addEvent]);

  useEffect(() => {
    if (!enabled) {
      setStatus('idle');
      return;
    }
    if (typeof EventSource === 'undefined') {
      startFallbackPolling();
      return;
    }

    let cancelled = false;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;
    let failed = false;
    setStatus('connecting');

    const open = () => {
      if (cancelled) return;
      const source = new EventSource(buildUrl(runId, cursor.current));
      sourceRef.current = source;

      source.onopen = () => {
        if (!cancelled) setStatus('open');
      };

      source.onmessage = (message) => {
        // 无 `event:` 名的帧走这里；本服务所有帧都带名字，所以正常不会触发。
        // 留着是为了不把未知帧静默丢掉。
        if (message.lastEventId) return;
        try {
          addEvent(JSON.parse(message.data) as EventResponse);
        } catch {
          /* 一帧坏数据不该断开整条流 */
        }
      };

      source.addEventListener(SNAPSHOT_READY, () => {
        onSnapshotReady();
        source.close();
        if (!cancelled) setStatus('closed');
      });

      // 具名事件要逐个挂：`event:` 里的类型就是事件名，而事件名是开放集合。
      for (const name of KNOWN_EVENT_NAMES) {
        source.addEventListener(name, (message) => {
          const data = (message as MessageEvent).data;
          try {
            addEvent(JSON.parse(data) as EventResponse);
          } catch {
            /* 同上 */
          }
        });
      }

      source.onerror = () => {
        if (cancelled) return;
        source.close();
        if (sourceRef.current === source) sourceRef.current = null;
        if (failed) return; // 已经降级，别在轮询期间还在重连
        failed = true;
        // 连不上可能是代理掐断或浏览器不支持。与其无限重连把日志刷满，
        // 不如承认这条路走不通，改用轮询——慢，但一定有答案。
        if (attempt >= 2) {
          startFallbackPolling();
          return;
        }
        const delay = Math.min(RECONNECT_BASE_MS * 2 ** attempt, RECONNECT_MAX_MS);
        retryTimer = setTimeout(() => {
          setAttempt((value) => value + 1);
          open();
        }, delay);
      };
    };

    open();

    return () => {
      cancelled = true;
      if (retryTimer !== null) clearTimeout(retryTimer);
      sourceRef.current?.close();
      sourceRef.current = null;
    };
  }, [runId, enabled, attempt, addEvent, onSnapshotReady, startFallbackPolling]);

  // 卸载时把降级轮询也停掉，否则组件没了还在每 3 秒打一次请求。
  useEffect(
    () => () => {
      if (fallbackTimer.current !== null) {
        clearTimeout(fallbackTimer.current);
        fallbackTimer.current = null;
      }
    },
    [],
  );

  const reconnect = useCallback(() => {
    setSnapshotReady(false);
    setAttempt((value) => value + 1);
  }, []);

  return useMemo(
    () => ({
      events,
      status,
      lastEventId: cursor.current,
      snapshotReady,
      reconnect,
    }),
    [events, status, snapshotReady, reconnect],
  );
}

/**
 * 需要逐个 `addEventListener` 的事件名。
 *
 * 来自引擎目录（`engine-catalog.json` 的 `event_types`），因此新增事件类型时
 * 下一条命令就会把它带进来；后端那条漂移测试保证它同时也在分类表里。
 * 保持为字面量而不是运行时读契约：这份名单必须能被 `event-taxonomy.test.ts`
 * 与后端目录对照，动态读就没有可对照的固定物了。
 */
export const KNOWN_EVENT_NAMES: readonly string[] = [
  'analysis_complete',
  'analysis_failed',
  'budget_stage_cap_hit',
  'budget_stop',
  'crossover_parents',
  'crossover_reflection_skipped',
  'discovery_round_finished',
  'discovery_skipped',
  'expand_redirected_budget',
  'hypothesis_refuted',
  'init_evaluated',
  'insight_extracted',
  'invalid_generation',
  'iteration_complete',
  'jev_audited',
  'jev_circuit_open',
  'jev_deferred_evaluated',
  'jev_error',
  'jev_prescreen',
  'jev_screened',
  'llm_error',
  'mechanism_refuted',
  'node_created',
  'objective_brief_failed',
  'objective_spec_failed',
  'operator_fallback',
  'operator_selected',
  'perf_rejected',
  'perf_self_fix_success',
  'precheck_fix',
  'precheck_fix_repair',
  'reflection_design',
  'reflection_implementation',
  'reflection_mechanism',
  'repair_failed',
  'repair_perf_rejected',
  'repair_smoke_failed',
  'repair_success',
  'run_finished',
  'selection_failed',
  'smoke_data_build_failed',
  'smoke_data_built',
  'smoke_failed',
  'smoke_fix_success',
  'tournament_round_finished',
  'tournament_skipped',
  'value_mode_fallback',
];
